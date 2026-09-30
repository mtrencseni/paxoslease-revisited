---- MODULE PaxosLeaseCheckedSym ----
(* PaxosLeaseChecked under proposer and acceptor symmetry, for the larger   *)
(* three-acceptor configurations.                                           *)
EXTENDS PaxosLeaseChecked, TLC
Symm == Permutations(Proposers) \cup Permutations(Acceptors)
====
