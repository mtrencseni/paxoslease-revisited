---- MODULE NodeOwnerSearch ----
(***************************************************************************)
(* A directed counterexample search over the NodeOwner variant, not a     *)
(* check.  Guide only prunes nondeterminism: p1 uses ballot 2 and, after   *)
(* its one restart, ballot 1; p2 uses ballot 3 and starts only after p1    *)
(* has restarted; only p1 may crash among the proposers, and only after it *)
(* has been active; only a2 may crash among the acceptors, and only after  *)
(* p1 has crashed; a3 hears nothing from p1's first incarnation until it  *)
(* restarts, time advances only after that, and p2 starts only while p1  *)
(* is active again.  Every behavior TLC explores is therefore a behavior of *)
(* NodeOwner.tla.  The same Guide over the specification itself, whose A2 *)
(* compares owners as incarnations, is spec/NodeOwnerSearchBase.tla.       *)
(***************************************************************************)
EXTENDS NodeOwner

CONSTANTS p1, p2, a2, a3

Guide ==
    /\ Cardinality(network) <= MaxNetwork
    /\ pBallot[p1] \in (IF pInc[p1] = 0 THEN {0, 2} ELSE {0, 1})
    /\ pBallot[p2] \in {0, 3}
    /\ (pBallot[p2] = 3 => pInc[p1] = 1)
    /\ crashedP \subseteq {p1}
    /\ crashedA \subseteq {a2}
    /\ (p1 \in crashedP \/ pInc[p1] = 1) => activeBallot[p1] # 0
    /\ (a2 \in crashedA \/ quarantineUntil[a2] > 0) => (p1 \in crashedP \/ pInc[p1] = 1)
    /\ pInc[p1] = 0 => (promised[a3] = 0 /\ accepted[a3] = NoLease)
    /\ now > 0 => pInc[p1] = 1
    /\ pBallot[p2] = 3 => (p1 \in active /\ activeBallot[p1] = 1)

====
