# Counterexample variants

These modules are full copies of `tla/spec/PaxosLease.tla` with exactly one rule
weakened. They are not sketches: TLC exhibits a `LeaseExclusivity` violation
for each under its `.cfg`, i.e. an execution with two simultaneously active
lease owners. Run them with `make counterexamples`. The configurations of
`LateTimer` and `StaleOwnerOpen` set `RefuseLiveOverwrite = FALSE`, the
overwriting acceptors of the 2012 paper and of Keyspace and ScalienDB, since
the rules they weaken matter only for such acceptors; with A2's refusal both
pass (`LateTimerA2.cfg`, `StaleOwnerOpenA2.cfg`). The other variants keep the
refusal. Trace lengths and state counts are in `results/`.

- `LateTimer.tla`: the proposer starts its pending deadline when it receives
  a prepare quorum (step 3 of the pseudocode in the original 2012 PaxosLease
  paper) instead of when it sends `Prepare`. Nothing then bounds the age of a
  prepare quorum, so with overwriting acceptors no finite quarantine makes
  acceptor restart safe: the configuration uses the full quarantine bound and
  TLC still finds a two-owner trace. The three-acceptor configuration
  (`LateTimer3.cfg` with the `LateTimerSym.tla` symmetry wrapper,
  `make counterexamples-3acceptors`) yields a trace in which a *single*
  crashed-and-restarted acceptor suffices; it is not in the default targets.
  With A2's refusal, exclusion needs only a timer start before the first
  acceptance, and `LateTimerA2.cfg` passes (`make latetimer-a2`).
- `OwnerOnlyRelease.tla`: a release message clears any lease of the same
  owner instead of the exact `(owner, ballot)` instance. A release delayed
  past a re-acquisition by the same owner erases the newer lease, and a
  second proposer acquires while the first is still active.
- `ScalarQuorumCounting.tla`: the proposer counts quorum responses by
  message instead of by distinct acceptor identity, under the base module's
  redelivering transport (`AllowRedeliver`). This is how both audited
  implementations count votes (scalar counters in Keyspace's
  `PLeaseProposer.cpp`, membership-check-only vote objects in ScalienDB's
  `MajorityQuorum.cpp`); it is sound only under at-most-once delivery per
  response, which their TCP transports provide by construction (pending
  writes are discarded on disconnect, nothing retransmits) but nothing
  documents. With redelivery allowed, a single acceptor's doubled response
  counts as a quorum and TLC finds a two-owner trace with no crash at all.
- `StaleOwnerOpen.tla`: the proposer counts a reported lease it owns as an
  open response even when it is not currently active (renewing), dropping
  rule P2's renewal qualifier. With overwriting acceptors and retry enabled,
  an accept request left in flight by an abandoned attempt overwrites a
  competitor's live lease record and then, on the proposer's own retry, is
  read back as "its own" lease everywhere, licensing a fresh acquisition
  beside the still-active competitor. The trace uses the full quarantine
  bound, and no quarantine length prevents it. Both audited implementations
  implement the unqualified rule. Multi-hour search
  (`make counterexamples-staleowner`), recorded evidence rather than a
  default target. With A2's refusal the qualifier is not needed for safety:
  `StaleOwnerOpenA2.cfg` passes (`make staleowner-a2`).
- `NodeOwner.tla`: A2 compares owners by proposer only, not by proposer
  incarnation (`owner` and `inc`). A restarted proposer resets its attempt
  counter, so its ballots may be lower than before, and a stale accept
  request of its previous incarnation then passes as the current owner's:
  it replaces the new incarnation's live lease with a released instance, the
  stale release clears it, and a second proposer acquires. The directed
  search `NodeOwnerSearch.tla`/`.cfg`, whose state constraint only prunes
  behaviors, finds a 43-state two-owner trace (`make counterexamples`). The
  same search on the specification, `tla/spec/NodeOwnerSearchBase.tla`/`.cfg`,
  exhausts its space with no violation (`make nodeowner-base`).

Two further failure modes need no modified module. Insufficient quarantine
is a configuration of the unmodified spec. `tla/spec/PaxosLeaseUnsafeQuarantine.cfg`
(durations 2/3) and `tla/spec/PaxosLeaseUnsafeQuarantine12.cfg` (durations 1/2)
set `Quarantine` one unit below `ProposerDuration`, one below the bound that
is tight in the checked model, and TLC finds a two-owner trace in each
(`make unsafe-configs`). Overwriting acceptors are also a configuration of
the unmodified spec (`RefuseLiveOverwrite = FALSE`): renewal across one
acceptor restart (`tla/spec/PaxosLeaseRenewCrashSearch.cfg`) and early
release across a restart (`tla/spec/PaxosLeaseReleaseCrashSearch.cfg`) give
two owners.

The Python model mirrors the LateTimer failure as the `late-promise-reuse`
structured witness (`Simulator(timer_at_quorum=True)`), and
`tests/test_contracts.py` checks that the prepare-time rule blocks the exact
same schedule. The NodeOwner failure has the `release-across-proposer-restart`
witness, one of 18.
