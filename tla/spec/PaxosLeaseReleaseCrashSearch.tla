---- MODULE PaxosLeaseReleaseCrashSearch ----
(***************************************************************************)
(* A directed counterexample search, not a check.  Early release (P6/A3)   *)
(* with two proposers and an acceptor restart, with overwriting acceptors *)
(* (RefuseLiveOverwrite = FALSE in PaxosLeaseReleaseCrashSearch.cfg).      *)
(*                                                                          *)
(* SearchConstraint only prunes: it forbids proposer crashes, lets only    *)
(* acceptor A2 crash, and fixes which ballots each proposer may use.  Every *)
(* behavior TLC explores is therefore a behavior of PaxosLease.tla with   *)
(* the same constants, so a violation found here is a violation of it.    *)
(* The pruning only makes the 40-state execution reachable by             *)
(* breadth-first search.  The Python counterexample                        *)
(* release-after-stale-accept replays the same schedule.  With             *)
(* RefuseLiveOverwrite = TRUE (PaxosLeaseReleaseCrashSearchA2.cfg) the     *)
(* constrained space is exhausted with no violation.                       *)
(***************************************************************************)
EXTENDS PaxosLease

CONSTANTS P1, P2, A2

SearchConstraint ==
    /\ StateConstraint
    /\ crashedP = {}
    /\ crashedA \subseteq {A2}
    /\ pBallot[P1] \in {0, 1}
    /\ pBallot[P2] \in {0, 2, 3}
    /\ (now = 0) => (pBallot[P1] = 0)

====
