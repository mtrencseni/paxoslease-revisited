---- MODULE PaxosLeaseImpl ----
(***************************************************************************)
(* A model of the protocol that Keyspace and ScalienDB actually implement,  *)
(* as opposed to the protocol in spec/PaxosLease.tla.  Its acceptors       *)
(* overwrite, as the audited acceptors do, and it differs from the base    *)
(* specification with overwriting acceptors in three rules, all taken from *)
(* the audited sources (see the paper's audit section): the two below, and *)
(* DeliverPromise's own-lease rule, which counts any reported own lease as *)
(* open, with no renewal base.                                              *)
(*                                                                          *)
(*   1. The lease timer starts when the proposer has a prepare quorum in    *)
(*      hand (StartProposing in PLeaseProposer.cpp and                      *)
(*      PaxosLeaseProposer.cpp: expireTime = Now() + duration), which is    *)
(*      the step-3 rule of the 2012 paper, not the figure's prepare-time    *)
(*      rule.  In this module pendingDeadline is therefore set in           *)
(*      SendAccept, not StartAcquire.                                       *)
(*                                                                          *)
(*   2. A separate attempt timeout of RetryTimeout time units               *)
(*      (ACQUIRELEASE_TIMEOUT in the sources) starts when Prepare is sent.  *)
(*      When it fires, the attempt is abandoned: the real code re-prepares  *)
(*      with a fresh proposal identifier, which this module represents as   *)
(*      the phase returning to "idle" (a subsequent StartAcquire is the     *)
(*      re-prepare).  Responses to the abandoned ballot are then unusable,  *)
(*      exactly as the proposalID comparison discards them in the sources.  *)
(*                                                                          *)
(* The constant TimelyDispatch selects between two semantics for that      *)
(* timeout, corresponding to the two sides of the audit's conclusion:      *)
(*                                                                          *)
(*   TimelyDispatch = TRUE: the timeout callback runs as soon as the        *)
(*      deadline passes, before any further message processing by that     *)
(*      proposer.  Tick enforces this by abandoning every overdue attempt   *)
(*      as time advances.  This models an event loop that is never paused   *)
(*      between its timer scan and its socket poll.                         *)
(*                                                                          *)
(*   TimelyDispatch = FALSE: expiry merely enables AbandonAttempt, which    *)
(*      may be delayed arbitrarily (or forever, within the horizon).        *)
(*      Message processing remains enabled while the overdue timeout       *)
(*      waits, which is what a process suspension between the timer scan    *)
(*      and the poll produces in the shipped event loop.                    *)
(*                                                                          *)
(* The implementations do not check an attempt deadline in their Phase 2    *)
(* response handlers (OnProposeResponse checks only the lease expiry), so   *)
(* DeliverAccepted deliberately has no such guard here: under delayed       *)
(* dispatch a stale attempt can activate.  That is the defect, not a        *)
(* modeling artifact.                                                       *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Proposers,
    Acceptors,
    Ballots,
    NoOwner,
    MaxTime,
    ProposerDuration,
    AcceptorDuration,
    RetryTimeout,
    TimelyDispatch,
    CrashableAcceptors,
    Quarantine,
    AllowCrash,
    AllowRelease,
    AllowDrop,
    AllowRenewal,
    CrashDropsIncoming,
    MaxNetwork

ASSUME NoOwner \notin Proposers
ASSUME 0 \notin Ballots
ASSUME ProposerDuration <= AcceptorDuration
ASSUME RetryTimeout >= 1
ASSUME TimelyDispatch \in BOOLEAN
(***************************************************************************)
(* Which acceptors may crash.  In the deployed systems, proposer and       *)
(* acceptor roles are colocated in one process, and a node's durable       *)
(* restart counter is spliced into its proposal identifiers, so a crash of *)
(* a proposer-hosting node changes that proposer's ballot ordering.  This  *)
(* module keeps ballots abstract; restricting crashes to acceptors whose   *)
(* colocated proposer takes no part in the violating schedule (in the      *)
(* colocated configuration, the single acceptor in the intersection of     *)
(* the two proposers' quorums) yields traces that are valid for the        *)
(* deployed, colocated systems without modeling restart counters.          *)
(***************************************************************************)
ASSUME CrashableAcceptors \subseteq Acceptors

Ballots0 == Ballots \cup {0}
Owners == Proposers \cup {NoOwner}
MaxDeadline == MaxTime + AcceptorDuration + Quarantine + RetryTimeout + 1

LeaseRec == [owner : Owners, ballot : Ballots0, deadline : 0..MaxDeadline]
NoLease == [owner |-> NoOwner, ballot |-> 0, deadline |-> 0]

Msg ==
    [kind : {"Prepare"}, from : Proposers, to : Acceptors, ballot : Ballots]
  \cup [kind : {"Promise"}, from : Acceptors, to : Proposers,
        ballot : Ballots, owner : Owners, acceptedBallot : Ballots0,
        acceptedDeadline : 0..MaxDeadline]
  \cup [kind : {"AcceptReq"}, from : Proposers, to : Acceptors,
        ballot : Ballots, owner : Proposers]
  \cup [kind : {"Accepted"}, from : Acceptors, to : Proposers,
        ballot : Ballots, deadline : 0..MaxDeadline]
  \cup [kind : {"Release"}, from : Proposers, to : Acceptors,
        ballot : Ballots]

VARIABLES
    now,
    network,
    promised,
    accepted,
    phase,
    pBallot,
    usedBallots,
    pDeadline,
    pendingDeadline,
    attemptDeadline,
    okResp,
    acceptResp,
    active,
    activeBallot,
    cert,
    certDeadline,
    crashedP,
    crashedA,
    quarantineUntil

vars == << now, network, promised, accepted, phase, pBallot, usedBallots, pDeadline,
           pendingDeadline, attemptDeadline, okResp, acceptResp, active, activeBallot,
           cert, certDeadline, crashedP, crashedA, quarantineUntil >>

IsQuorum(S) ==
    S \subseteq Acceptors /\ Cardinality(S) * 2 > Cardinality(Acceptors)

Cap(t) == IF t > MaxDeadline THEN MaxDeadline ELSE t

ValidLease(r) == r.owner # NoOwner /\ now < r.deadline

ReportLease(a) == IF ValidLease(accepted[a]) THEN accepted[a] ELSE NoLease

CanParticipateA(a) == a \notin crashedA /\ now >= quarantineUntil[a]

RunningP(p) == p \notin crashedP

Init ==
    /\ now = 0
    /\ network = {}
    /\ promised = [a \in Acceptors |-> 0]
    /\ accepted = [a \in Acceptors |-> NoLease]
    /\ phase = [p \in Proposers |-> "idle"]
    /\ pBallot = [p \in Proposers |-> 0]
    /\ usedBallots = {}
    /\ pDeadline = [p \in Proposers |-> 0]
    /\ pendingDeadline = [p \in Proposers |-> 0]
    /\ attemptDeadline = [p \in Proposers |-> 0]
    /\ okResp = [p \in Proposers |-> {}]
    /\ acceptResp = [p \in Proposers |-> {}]
    /\ active = {}
    /\ activeBallot = [p \in Proposers |-> 0]
    /\ cert = [p \in Proposers |-> {}]
    /\ certDeadline = [p \in Proposers |-> [a \in Acceptors |-> 0]]
    /\ crashedP = {}
    /\ crashedA = {}
    /\ quarantineUntil = [a \in Acceptors |-> 0]

(***************************************************************************)
(* StartAcquire starts the attempt timeout, not the lease timer: the       *)
(* shipped StartPreparing resets ACQUIRELEASE_TIMEOUT and touches no lease  *)
(* deadline.                                                                *)
(***************************************************************************)
StartAcquire ==
    \E p \in Proposers, b \in Ballots :
        /\ RunningP(p)
        /\ phase[p] = "idle"
        /\ (p \notin active \/ AllowRenewal)
        /\ b > pBallot[p]
        /\ b \notin usedBallots
        /\ pBallot' = [pBallot EXCEPT ![p] = b]
        /\ usedBallots' = usedBallots \cup {b}
        /\ attemptDeadline' = [attemptDeadline EXCEPT ![p] = Cap(now + RetryTimeout)]
        /\ phase' = [phase EXCEPT ![p] = "preparing"]
        /\ okResp' = [okResp EXCEPT ![p] = {}]
        /\ acceptResp' = [acceptResp EXCEPT ![p] = {}]
        /\ network' = network \cup
            { [kind |-> "Prepare", from |-> p, to |-> a, ballot |-> b] :
                a \in Acceptors }
        /\ UNCHANGED << now, promised, accepted, pDeadline, pendingDeadline,
                        active, activeBallot, cert, certDeadline, crashedP,
                        crashedA, quarantineUntil >>

DeliverPrepare ==
    \E m \in network :
        /\ m.kind = "Prepare"
        /\ CanParticipateA(m.to)
        /\ LET r == ReportLease(m.to) IN
            /\ network' =
                (network \ {m}) \cup
                (IF m.ballot >= promised[m.to]
                 THEN { [kind |-> "Promise", from |-> m.to, to |-> m.from,
                         ballot |-> m.ballot, owner |-> r.owner,
                         acceptedBallot |-> r.ballot,
                         acceptedDeadline |-> r.deadline] }
                 ELSE {})
            /\ promised' =
                IF m.ballot >= promised[m.to]
                THEN [promised EXCEPT ![m.to] = m.ballot]
                ELSE promised
        /\ UNCHANGED << now, accepted, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp,
                        active, activeBallot, cert, certDeadline, crashedP,
                        crashedA, quarantineUntil >>

DeliverPromise ==
    \E m \in network :
        /\ m.kind = "Promise"
        /\ RunningP(m.to)
        /\ m.ballot = pBallot[m.to]
        /\ network' = network \ {m}
        /\ okResp' =
            [okResp EXCEPT ![m.to] =
                IF m.owner = NoOwner \/ m.owner = m.to
                THEN @ \cup {m.from}
                ELSE @]
        /\ UNCHANGED << now, promised, accepted, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, acceptResp, active, activeBallot,
                        cert, certDeadline, crashedP, crashedA,
                        quarantineUntil >>

(***************************************************************************)
(* SendAccept is StartProposing: this is where the shipped code sets        *)
(* expireTime = Now() + duration, so this is where pendingDeadline starts.  *)
(* The phase guard means the attempt has not been abandoned; under timely   *)
(* dispatch that implies now < attemptDeadline[p].                          *)
(***************************************************************************)
SendAccept ==
    \E p \in Proposers :
        /\ RunningP(p)
        /\ phase[p] = "preparing"
        /\ IsQuorum(okResp[p])
        /\ pendingDeadline' = [pendingDeadline EXCEPT ![p] = Cap(now + ProposerDuration)]
        /\ phase' = [phase EXCEPT ![p] = "accepting"]
        /\ acceptResp' = [acceptResp EXCEPT ![p] = {}]
        /\ network' = network \cup
            { [kind |-> "AcceptReq", from |-> p, to |-> a,
                ballot |-> pBallot[p], owner |-> p] : a \in Acceptors }
        /\ UNCHANGED << now, promised, accepted, pBallot, usedBallots, pDeadline,
                        attemptDeadline, okResp, active, activeBallot, cert,
                        certDeadline, crashedP, crashedA, quarantineUntil >>

DeliverAcceptReq ==
    \E m \in network :
        /\ m.kind = "AcceptReq"
        /\ CanParticipateA(m.to)
        /\ network' =
            (network \ {m}) \cup
            (IF m.ballot >= promised[m.to]
             THEN { [kind |-> "Accepted", from |-> m.to, to |-> m.from,
                     ballot |-> m.ballot,
                     deadline |-> Cap(now + AcceptorDuration)] }
             ELSE {})
        /\ promised' =
            IF m.ballot >= promised[m.to]
            THEN [promised EXCEPT ![m.to] = m.ballot]
            ELSE promised
        /\ accepted' =
            IF m.ballot >= promised[m.to]
            THEN [accepted EXCEPT ![m.to] =
                    [owner |-> m.owner, ballot |-> m.ballot,
                     deadline |-> Cap(now + AcceptorDuration)]]
            ELSE accepted
        /\ UNCHANGED << now, phase, pBallot, usedBallots, pDeadline, pendingDeadline,
                        attemptDeadline, okResp, acceptResp, active, activeBallot,
                        cert, certDeadline, crashedP, crashedA,
                        quarantineUntil >>

(***************************************************************************)
(* No attempt-deadline guard here, matching OnProposeResponse in both      *)
(* audited sources, which checks only the lease expiry.  Under timely      *)
(* dispatch the phase guard suffices; under delayed dispatch it does not,  *)
(* and that is the point.                                                   *)
(***************************************************************************)
DeliverAccepted ==
    \E m \in network :
        /\ m.kind = "Accepted"
        /\ RunningP(m.to)
        /\ m.ballot = pBallot[m.to]
        /\ phase[m.to] = "accepting"
        /\ LET newResp == acceptResp[m.to] \cup {m.from}
               canActivate == IsQuorum(newResp) /\ now < pendingDeadline[m.to]
            IN
            /\ network' = network \ {m}
            /\ acceptResp' = [acceptResp EXCEPT ![m.to] = newResp]
            /\ certDeadline' =
                [certDeadline EXCEPT ![m.to] =
                    [@ EXCEPT ![m.from] = m.deadline]]
            /\ active' = IF canActivate
                         THEN active \cup {m.to}
                         ELSE active
            /\ activeBallot' = IF canActivate
                               THEN [activeBallot EXCEPT ![m.to] = m.ballot]
                               ELSE activeBallot
            /\ pDeadline' = IF canActivate
                            THEN [pDeadline EXCEPT ![m.to] = pendingDeadline[m.to]]
                            ELSE pDeadline
            /\ cert' = IF canActivate
                       THEN [cert EXCEPT ![m.to] = newResp]
                       ELSE cert
            /\ phase' = IF IsQuorum(newResp)
                        THEN [phase EXCEPT ![m.to] = "idle"]
                        ELSE phase
        /\ UNCHANGED << now, promised, accepted, pBallot, usedBallots, pendingDeadline,
                        attemptDeadline, okResp, crashedP, crashedA,
                        quarantineUntil >>

Release ==
    \E p \in active :
        /\ AllowRelease
        /\ RunningP(p)
        /\ active' = active \ {p}
        /\ network' = network \cup
            { [kind |-> "Release", from |-> p, to |-> a,
                ballot |-> activeBallot[p]] : a \in Acceptors }
        /\ UNCHANGED << now, promised, accepted, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp,
                        activeBallot, cert, certDeadline, crashedP, crashedA,
                        quarantineUntil >>

DeliverRelease ==
    \E m \in network :
        /\ m.kind = "Release"
        /\ CanParticipateA(m.to)
        /\ network' = network \ {m}
        /\ accepted' =
            IF accepted[m.to].owner = m.from /\ accepted[m.to].ballot = m.ballot
            THEN [accepted EXCEPT ![m.to] = NoLease]
            ELSE accepted
        /\ UNCHANGED << now, promised, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp,
                        active, activeBallot, cert, certDeadline, crashedP,
                        crashedA, quarantineUntil >>

DropMessage ==
    \E m \in network :
        /\ AllowDrop
        /\ network' = network \ {m}
        /\ UNCHANGED << now, promised, accepted, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp,
                        active, activeBallot, cert, certDeadline, crashedP,
                        crashedA, quarantineUntil >>

(***************************************************************************)
(* Under timely dispatch, advancing time abandons every attempt whose      *)
(* timeout has come due: the callback runs before anything else happens at  *)
(* the new time.  Under delayed dispatch, time advances and the overdue    *)
(* timeout just sits there; AbandonAttempt below may fire it eventually,   *)
(* or never.                                                                *)
(***************************************************************************)
Tick ==
    /\ now < MaxTime
    /\ LET nn == now + 1 IN
        /\ now' = nn
        /\ active' = {p \in active : nn < pDeadline[p] /\ p \notin crashedP}
        /\ phase' = IF TimelyDispatch
                    THEN [p \in Proposers |->
                            IF phase[p] # "idle" /\ nn >= attemptDeadline[p]
                            THEN "idle"
                            ELSE phase[p]]
                    ELSE phase
    /\ UNCHANGED << network, promised, accepted, pBallot, usedBallots, pDeadline,
                    pendingDeadline, attemptDeadline, okResp, acceptResp, activeBallot,
                    cert, certDeadline, crashedP, crashedA, quarantineUntil >>

AbandonAttempt ==
    \E p \in Proposers :
        /\ ~TimelyDispatch
        /\ RunningP(p)
        /\ phase[p] # "idle"
        /\ now >= attemptDeadline[p]
        /\ phase' = [phase EXCEPT ![p] = "idle"]
        /\ UNCHANGED << now, network, promised, accepted, pBallot, usedBallots,
                        pDeadline, pendingDeadline, attemptDeadline, okResp,
                        acceptResp, active, activeBallot, cert, certDeadline,
                        crashedP, crashedA, quarantineUntil >>

CrashProposer ==
    \E p \in Proposers :
        /\ AllowCrash
        /\ p \notin crashedP
        /\ crashedP' = crashedP \cup {p}
        /\ active' = active \ {p}
        /\ phase' = [phase EXCEPT ![p] = "idle"]
        /\ UNCHANGED << now, network, promised, accepted, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp,
                        activeBallot, cert, certDeadline, crashedA,
                        quarantineUntil >>

RestartProposer ==
    \E p \in crashedP :
        /\ AllowCrash
        /\ crashedP' = crashedP \ {p}
        /\ UNCHANGED << now, network, promised, accepted, phase, pBallot,
                        usedBallots, pDeadline, pendingDeadline, attemptDeadline, okResp,
                        acceptResp, active, activeBallot, cert, certDeadline,
                        crashedA, quarantineUntil >>

(***************************************************************************)
(* With CrashDropsIncoming, delivery is connection-lifecycle: messages     *)
(* addressed to the acceptor are discarded both at its crash (undelivered  *)
(* inbound data dies with the receiver) and at its restart (anything sent  *)
(* while it was down was queued to a dead connection), so every delivered  *)
(* message was sent after the acceptor's most recent restart.  Messages    *)
(* FROM the crashed acceptor may survive.  FALSE is the connectionless     *)
(* reading, in which a request sent before the crash may be delivered      *)
(* after the restart.                                                      *)
(***************************************************************************)
CrashAcceptor ==
    \E a \in CrashableAcceptors :
        /\ AllowCrash
        /\ a \notin crashedA
        /\ crashedA' = crashedA \cup {a}
        /\ promised' = [promised EXCEPT ![a] = 0]
        /\ accepted' = [accepted EXCEPT ![a] = NoLease]
        /\ network' = IF CrashDropsIncoming
                      THEN {m \in network : m.to # a}
                      ELSE network
        /\ UNCHANGED << now, phase, pBallot, usedBallots, pDeadline,
                        pendingDeadline, attemptDeadline, okResp, acceptResp, active,
                        activeBallot, cert, certDeadline, crashedP,
                        quarantineUntil >>

RestartAcceptor ==
    \E a \in crashedA :
        /\ AllowCrash
        /\ crashedA' = crashedA \ {a}
        /\ quarantineUntil' = [quarantineUntil EXCEPT ![a] = Cap(now + Quarantine)]
        /\ network' = IF CrashDropsIncoming
                      THEN {m \in network : m.to # a}
                      ELSE network
        /\ UNCHANGED << now, promised, accepted, phase, pBallot,
                        usedBallots, pDeadline, pendingDeadline, attemptDeadline, okResp,
                        acceptResp, active, activeBallot, cert, certDeadline,
                        crashedP >>

StutterAtEnd ==
    /\ now = MaxTime
    /\ UNCHANGED vars

Next ==
    StartAcquire \/ DeliverPrepare \/ DeliverPromise \/ SendAccept \/
    DeliverAcceptReq \/ DeliverAccepted \/ Release \/ DeliverRelease \/
    DropMessage \/ Tick \/ AbandonAttempt \/ CrashProposer \/ RestartProposer \/
    CrashAcceptor \/ RestartAcceptor \/ StutterAtEnd

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ now \in 0..MaxTime
    /\ network \in SUBSET Msg
    /\ promised \in [Acceptors -> Ballots0]
    /\ accepted \in [Acceptors -> LeaseRec]
    /\ phase \in [Proposers -> {"idle", "preparing", "accepting"}]
    /\ pBallot \in [Proposers -> Ballots0]
    /\ usedBallots \subseteq Ballots
    /\ pDeadline \in [Proposers -> 0..MaxDeadline]
    /\ pendingDeadline \in [Proposers -> 0..MaxDeadline]
    /\ attemptDeadline \in [Proposers -> 0..MaxDeadline]
    /\ okResp \in [Proposers -> SUBSET Acceptors]
    /\ acceptResp \in [Proposers -> SUBSET Acceptors]
    /\ active \subseteq Proposers
    /\ activeBallot \in [Proposers -> Ballots0]
    /\ cert \in [Proposers -> SUBSET Acceptors]
    /\ certDeadline \in [Proposers -> [Acceptors -> 0..MaxDeadline]]
    /\ crashedP \subseteq Proposers
    /\ crashedA \subseteq Acceptors
    /\ quarantineUntil \in [Acceptors -> 0..MaxDeadline]

AcceptedCoherence ==
    \A a \in Acceptors :
        \/ accepted[a] = NoLease
        \/ /\ accepted[a].owner \in Proposers
           /\ accepted[a].ballot \in Ballots
           /\ accepted[a].deadline \in 1..MaxDeadline

ActiveImpliesUnexpired ==
    \A p \in active : now < pDeadline[p]

LeaseExclusivity ==
    Cardinality(active) <= 1

ActivationHasQuorum ==
    \A p \in active : IsQuorum(cert[p])

TimerContainment ==
    \A p \in active :
        \A a \in cert[p] : pDeadline[p] <= certDeadline[p][a]

QuarantinePreventsParticipation ==
    \A a \in Acceptors :
        now < quarantineUntil[a] => accepted[a] = NoLease /\ promised[a] = 0

ActiveBallotWellFormed ==
    \A p \in active : activeBallot[p] \in Ballots

(***************************************************************************)
(* Under timely dispatch a live attempt is never overdue.  Not meaningful   *)
(* (and not checked) under delayed dispatch.                                *)
(***************************************************************************)
AttemptFreshness ==
    \A p \in Proposers :
        phase[p] # "idle" => now < attemptDeadline[p]

Safety ==
    TypeOK /\ AcceptedCoherence /\ ActiveImpliesUnexpired /\
    LeaseExclusivity /\ ActivationHasQuorum /\ TimerContainment /\
    QuarantinePreventsParticipation /\ ActiveBallotWellFormed

StateConstraint ==
    Cardinality(network) <= MaxNetwork

====
