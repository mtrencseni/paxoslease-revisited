---- MODULE NodeOwnerSearchBase ----
(***************************************************************************)
(* The directed search of counterexamples/NodeOwnerSearch.tla, over the    *)
(* specification itself, whose A2 compares owners as proposer             *)
(* incarnations.  Guide only prunes nondeterminism, as there.             *)
(***************************************************************************)
EXTENDS PaxosLeaseChecked

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
