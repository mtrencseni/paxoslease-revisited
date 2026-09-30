---- MODULE PaxosLeaseRenewCrashSearch ----
(***************************************************************************)
(* A directed counterexample search, not a check.  Renewal together with a *)
(* single acceptor restart and three acceptors, on the UNMODIFIED rules    *)
(* with the renewal qualifier (P2) in force and quarantine at the          *)
(* containment bound, no release and no clock error.                        *)
(*                                                                          *)
(* Guide only prunes nondeterminism: p1 uses ballot 1, p2 uses 2 then 3,   *)
(* only a2 may crash and it restarts at time 0, a3 never promises ballot 2 *)
(* except by accepting it, and no proposer crashes.  Every behavior TLC    *)
(* explores is therefore a behavior of PaxosLease.tla itself.  With      *)
(* RefuseLiveOverwrite = FALSE TLC finds a 39-state two-owner trace: a     *)
(* promise forgotten in the restart protected the lease that overwrote     *)
(* another owner's live record, and the quarantine covers that attempt but *)
(* not the renewal built on it.  With RefuseLiveOverwrite = TRUE the        *)
(* constrained space is exhausted with no violation.  The configurations   *)
(* checked earlier that combine renewal and crash have two acceptors, where *)
(* every majority is the whole set and this execution cannot occur.        *)
(* The Python counterexample renewal-over-overwritten-grant replays an     *)
(* execution of the same shape.                                            *)
(***************************************************************************)
EXTENDS PaxosLease

CONSTANTS p1, p2, a1, a2, a3

Guide ==
    /\ Cardinality(network) <= MaxNetwork
    /\ pBallot[p1] \in {0, 1}
    /\ pBallot[p2] \in {0, 2, 3}
    /\ (pBallot[p2] = 3 => 2 \in usedBallots)
    /\ crashedA \subseteq {a2}
    /\ quarantineUntil[a2] <= 2
    /\ quarantineUntil[a1] = 0 /\ quarantineUntil[a3] = 0
    /\ crashedP = {}
    /\ (promised[a3] = 2 => accepted[a3].ballot = 2)   \* a3 reaches ballot 2 only by accepting it
    /\ accepted[a1].ballot # 1
    /\ accepted[a2].ballot # 2
    /\ (pBallot[p1] = 1 => now >= 1)

====
