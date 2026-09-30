# PaxosLease implementation contract

This document states what the executable models in this repository require from an implementation. It is intentionally stricter than the informal protocol sketch: every item below is either checked directly, represented by a negative example, or marked as outside the current proof boundary.

## Safety question

The central question is:

> Under what exact conditions can a quorum-based lease protocol safely discard all acceptor lease state after a crash?

The answer modeled here has two parts. An acceptor never replaces a live lease of a different owner, even under a higher ballot (A2), where the owner is a proposer incarnation. And an acceptor may discard volatile PaxosLease state only if, after restart, it refuses all lease-layer participation until every lease that it might have forgotten is unable to support an active owner. Everything an acceptor can forget belongs to a proposer attempt whose Prepare preceded the crash, and that attempt is unusable one proposer duration later; with A2's rule a forgotten promise imposes no bound of its own. In the discrete model this is captured by:

```text
Quarantine >= ProposerDuration
```

The bound tracks the proposer attempt duration, not the acceptor exclusion duration: TLC passes exhaustively with `Quarantine = ProposerDuration < AcceptorDuration` and violates lease exclusivity one unit below (the separated-duration model-checking experiment rules out the acceptor half of a `max(ProposerDuration, AcceptorDuration)` bound). The Python timing layer generalizes the bound to bounded local clock-rate error and operation margin. With A2's rule the bound needs only a timer start before the first acceptance; with overwriting acceptors and the 2012 paper's step-3 timer rule no finite quarantine suffices.

## Required protocol rules

| Rule | Status | Evidence |
|---|---|---|
| Quorums must intersect. | Assumption for majority configs. | TLA definitions, Python quorum checks, `nonintersecting-reconfiguration` witness. |
| A proposer is active only after an accepted quorum. | Direct model rule. | TLC invariants, Python simulator checks. |
| Quorum responses are counted by distinct acceptor id, or the transport guarantees at-most-once delivery per response. | Direct model rule. | `duplicate-quorum-counting` witness; `tla/spec/PaxosLeaseRedeliver.cfg` checks identity counting safe under the base module's redelivering transport (`AllowRedeliver`); TLC trace for `tla/counterexamples/ScalarQuorumCounting.tla` (no crash) shows scalar counting unsafe under the same transport. Both audited implementations count scalars; in the audited sources no redelivery path was found (pending writes are discarded on disconnect), but at-most-once delivery is an undocumented accident there, not a stated guarantee, and a complete proof of the transport was not performed. |
| A lease instance is identified by owner and ballot. | Direct model rule. | exact release logic, `owner-only-release` witness, TLC trace for `tla/counterexamples/OwnerOnlyRelease.tla`. |
| The acceptor never replaces a live lease of a different owner, even under a higher ballot (A2). | Direct model rule (A2's `RefuseLiveOverwrite`, required and assumed by `tla/spec/PaxosLeaseChecked.tla`; the reference models default to it). | `renewal-over-overwritten-grant` witness and its contract test: with overwriting acceptors, a renewal across a single acceptor restart gives two owners with the renewal qualifier in force. `tla/spec/PaxosLeaseRenewCrashSearch.cfg` (`RefuseLiveOverwrite = FALSE`) finds the trace with three acceptors (`results/counterexample-renewcrash.txt`), and `PaxosLeaseRenewCrashSearchA2.cfg` exhausts the same constrained space with the rule on (`results/renewcrash-a2.txt`). `PaxosLeaseRenewCrash3.cfg` checks renewal with two proposers across acceptor crash and restart with three acceptors and the rule on (`make check-renew-crash3`). Overwriting is the rule of the 2012 paper, and both audited implementations overwrite. |
| A2 compares owners as proposer incarnations: the proposer together with the durable restart counter its ballots carry. A restarted proposer resets its attempt counter, so its ballots may be lower than its previous incarnation's, and a stale accept of the previous incarnation must not replace the new incarnation's lease. | Direct model rule (`SameOwner` in `DeliverAcceptReq` compares `owner` and `inc`; `RestartProposer` increments `pInc` and resets `pBallot`). | `release-across-proposer-restart` witness; the variant `tla/counterexamples/NodeOwner.tla` compares by proposer only, and the directed search `NodeOwnerSearch.cfg` finds a 43-state two-owner trace (`results/counterexample-nodeowner.txt`); the same search on the specification, `tla/spec/NodeOwnerSearchBase.cfg`, exhausts its space with no violation (`make nodeowner-base`). |
| Early release relies on the same rule: exact-instance matching in release is necessary but not sufficient, since after an acceptor restart a stale accept can reinstall a released instance over another owner's live lease, and the matching stale release then clears it, exclusion deadline included. | Direct model rule (A2's `RefuseLiveOverwrite`, together with P6/A3). | `release-after-stale-accept` witness (overwriting acceptors, one acceptor restart, full quarantine) and its contract test showing `refuse_live_overwrite` blocks the same schedule; `tla/spec/PaxosLeaseReleaseCrashSearch.cfg` finds the violation on the specification with overwriting acceptors (`RefuseLiveOverwrite = FALSE`, `results/counterexample-releasecrash.txt`); its state constraint only prunes behaviors, so the trace is one of the full specification. `PaxosLeaseReleaseCrashSearchA2.cfg` exhausts the same constrained space with the rule on, no violation (`results/releasecrash-a2.txt`). Release with two proposers and the rule on is checked by `PaxosLeaseReleaseRace.cfg` (three acceptors, no crash), `PaxosLeaseReleaseCrash2.cfg` (two acceptors, crash and restart) and `PaxosLeaseReleaseCrash.cfg` (three acceptors, crash and restart, symmetry reduced). Neither audited implementation ships release. |
| Acceptors reject lower ballots after promising higher ballots. | Direct model rule. | TLC checks, `stale-accept-overwrites-newer` witness. |
| A renewal extends authority only after a fresh accept quorum. | Direct model rule. | scenario tests, `renewal-without-quorum` witness. |
| The attempt deadline starts when Prepare is sent, so prepare responses expire with the attempt that collected them. With A2's rule, exclusion needs only a start before the first acceptance. | Direct model rule. | prepare-time pending deadline; `late-promise-reuse` witness and TLC trace for `tla/counterexamples/LateTimer.tla` (`RefuseLiveOverwrite = FALSE`) show the step-3 timer rule of the 2012 paper is unsafe with overwriting acceptors; `LateTimerA2.cfg` passes with the refusal (`make latetimer-a2`). |
| A reported lease the proposer owns is an open prepare response only for a renewal attempt AND only when the reported ballot matches the renewal base captured at P1 (a fresh attempt has none); the proposer must not infer renewal from ownership at response delivery. The reported instance is the lease being renewed (ballot match); otherwise it blocks like a foreign lease. The base must also still be held when the response is processed (the TLA+ `DeliverPromise` tests activity at delivery; the executable models test the captured base is still active). | Direct model rule (P2's renewal qualifier). With A2's rule the qualifier is not needed for safety; it is kept, and it is needed with overwriting acceptors. | `stale-owner-open` witness; TLC trace for `tla/counterexamples/StaleOwnerOpen.tla` (`RefuseLiveOverwrite = FALSE`, full quarantine, retry enabled); with the refusal and the qualifier dropped, `StaleOwnerOpenA2.cfg` passes exhaustively (`results/staleowner-a2.txt`). The execution is still reachable under the connection-lifecycle transport refinement (`CrashDropsIncoming`, purging at crash and at restart; the recorded trace sends the stale accepts after the restart), so connection teardown does not mask it, and the checked implementation projection composes the two shipped mechanisms into the same execution under shipped timely constants (`results/impl-staleowner.txt`). Both audited implementations implement the unqualified rule: `StartProposing` proceeds with a full fresh duration whenever the discovered lease owner is the node itself (keyspace `PLeaseProposer.cpp`, scaliendb `PaxosLeaseProposer.cpp`), so their retry timeout can convert an abandoned attempt's stale accept into a second owner. |
| The attempt time bound is enforced as stored protocol state checked in the response handlers, not as timer dispatch order. | Direct model rule. | `suspended-event-loop` witness (executable colocated-node abstraction of the shipped iteration order, asserted at learner level); `tla/spec/PaxosLeaseImpl.tla` under delayed dispatch, TLC two-owner traces with the shipped constants, including the colocation-valid `PaxosLeaseImplDelayedColocated.cfg`. |
| Expiry comparisons read the clock once per handler and compare before subtracting; deadline arithmetic must not be exposed to unsigned wraparound. | Contract rule from the audit. | `unsigned-expiry-underflow` witness; both audited Phase 2 handlers read the clock twice on `uint64_t` deadlines. |
| The acting owner's learner preserves the proposer's absolute deadline; remote learners that re-anchor durations at arrival must state their delivery-delay bound. | Contract rule from the audit. | Both audited learners preserve the absolute deadline for the owner and re-anchor with an undocumented 500 ms hedge for remote nodes. |
| Restarted acceptors ignore prepare, accept, and release while quarantined. | Direct model rule. | Python contract test and TLC guards. |
| Proposer restart cannot reuse a ballot. | Python rule. | restart-component ballot test, `ballot-reuse-after-restart` witness. |
| Paxos client admission requires Paxos recovery after lease acquisition. | Composition rule. | composed Python model, TLC abstraction, `skipped-paxos-recovery` witness. |
| External side effects require fencing or log ordering. | Contract rule. | `FencedResource`, `unfenced-external-effect`, `split-brain-read-without-fence`. |
| Reconfiguration preserves quorum intersection or waits out old leases. | Open design rule. | documented; negative witness only. |

## Timing contract

The model assumes local elapsed-time measurements, not synchronized clocks. The Python helper uses bounds

```text
r_min * real_elapsed <= local_elapsed <= r_max * real_elapsed
```

for every live timer. A safe acceptor exclusion must outlast the proposer's usable interval in real time. A safe quarantine must outlast, in real time, the proposer attempt interval; forgotten acceptor exclusions matter only through the attempts they support.

Unsafe time sources include wall clocks that can step backward, timers that pause during suspend without treating the process as failed, and virtualized clocks whose rate bounds are unknown. The repository treats those cases as outside the implementation contract unless the runtime can re-establish the same elapsed-time bounds.

## Evidence labels

| Label | Meaning in this repository |
|---|---|
| TLC-checked | A finite TLA+ configuration was exhaustively model checked. |
| TLAPS-support | A formula-level support obligation was machine checked. |
| Python-tested | Deterministic scenarios, property tests, or randomized schedules exercised the executable model. |
| Counterexample-backed | A deliberately broken rule has a reproducible witness. |
| Informal | The argument is written in the paper but is not fully mechanized. |
| Open | The paper states the required condition but does not implement a full model. |

## What is not claimed

The repository does not contain a complete parameterized TLAPS proof of PaxosLease. It does not contain a full production Multi-Paxos implementation. The composed Paxos model is an admission and recovery model meant to check that PaxosLease does not remove the need for Paxos recovery. Reconfiguration is not implemented as a full protocol; the contract states the necessary intersection/wait-out condition and includes a negative witness for the unsafe case.
