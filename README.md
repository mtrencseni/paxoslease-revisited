# PaxosLease

This repository contains a LaTeX paper, executable TLA+ models, TLAPS support obligations, deterministic Python reference models, negative witnesses, and recorded verification outputs for:

**PaxosLease Revisited: A Checked Model of Diskless Distributed Leases**

The paper is `paper/PaxosLease-Revisited.pdf`; its source is `paper/PaxosLease-Revisited.tex`.

## Central question

Under what exact conditions can a quorum-based lease protocol safely discard all acceptor lease state after a crash?

The checked model's answer has two parts. First, an acceptor never replaces a live lease of a different owner, even under a higher ballot (rule A2), where the owner is a proposer incarnation: the proposer together with the durable restart counter its ballots carry. Second, a restarted acceptor refuses all lease-layer participation until every lease it may have forgotten can no longer support an active proposer. Everything an acceptor can forget belongs to an attempt whose Prepare preceded the crash, and with A2's rule a forgotten promise imposes no bound of its own, so in the discrete model:

```text
Quarantine >= ProposerDuration
```

The bound tracks the proposer attempt duration, not the acceptor exclusion duration. The Python timing helper generalizes this to bounded elapsed-clock rates and an operation margin.

## Findings about the original 2012 paper

- **Overwriting acceptors are unsafe.** The acceptor of the 2012 paper, and of
  Keyspace and ScalienDB, records every accept request whose ballot is high
  enough, replacing whatever lease it holds. With such acceptors TLC finds two
  simultaneous owners after a renewal across a single acceptor restart
  (`tla/spec/PaxosLeaseRenewCrashSearch.cfg`) and after an early release
  across a restart (`tla/spec/PaxosLeaseReleaseCrashSearch.cfg`), both with
  the full quarantine. A2 refuses to replace a live lease of a different
  owner; `tla/spec/PaxosLeaseChecked.tla` assumes it (`RefuseLiveOverwrite`),
  and the same two searches with the refusal exhaust their space with no
  violation. Owners are compared as incarnations, since a restarted proposer
  restarts its attempt counter and its ballots may be lower than before:
  comparing by proposer alone gives two owners in a 43-state trace
  (`tla/counterexamples/NodeOwner.tla`).
- **The pseudocode's timer rule is unsafe with overwriting acceptors.** The
  2012 paper is internally inconsistent: its Figure 2 starts the proposer's
  timer before the prepare requests, its step-3 pseudocode starts it at
  prepare-quorum receipt. Under the pseudocode rule the attempt has no
  deadline yet, so arbitrarily old prepare responses stay usable, and with
  overwriting acceptors TLC exhibits two simultaneous lease owners even with
  the full quarantine (`tla/counterexamples/LateTimer.tla`). With A2's rule
  the same configuration passes (`LateTimerA2.cfg`), and exclusion needs only
  a timer start before the first acceptance. This model starts the pending
  deadline when `Prepare` is sent, the rule the figure draws.
- **The quarantine bound is tight in the checked model, and it is
  `Quarantine >= Dp`, not `max(Dp, Da)`.** With A2's rule, quarantine equal to the
  proposer duration and strictly below the acceptor duration passes an
  exhaustive two-proposer crash/restart check
  (`tla/spec/PaxosLeaseQuarantineEqualsProposer.cfg`), and
  one unit below the proposer duration TLC exhibits two owners
  (`tla/spec/PaxosLeaseUnsafeQuarantine.cfg`). The separated-duration experiment refutes the
  `max(D_P, D_A)` bound by ruling out its acceptor half. State counts are in
  `results/`.

## Reproduce

Use a Python virtual environment. The `venv` target installs this repository as an editable package, so tests and scripts import `paxoslease` without modifying `PYTHONPATH`.

```sh
make venv
make paper-evidence
```

`paper-evidence` is the fail-fast target: it re-runs every result the paper
cites except the long searches, whose recorded outputs under
`results/` it instead validates against the paper's cited trace lengths and
state counts (`python/scripts/check_paper_claims.py`, target `paper-claims`).
`make paper-evidence-full` re-runs the long searches too. `make results`
regenerates the recorded report `results/verification-results.md`, and
`make all` builds everything including the PDF.

Useful partial targets:

```sh
make pdf
make parse
make lint
make check-standalone
make check-composition
make counterexamples
make unsafe-configs
make prove
make test
make monte-carlo
make expected-counterexamples
make variant-check
make trace-smoke-test
make timing-examples
```

The TLA+ wrappers expected on this machine are `sany`, `tlc`, and `tlapm`. Do not install TLA+ tooling or call `java -jar` directly for normal work in this repository.

## Project map

| Path | Contents |
|---|---|
| `paper/` | The paper: `PaxosLease-Revisited.tex` and the built `.pdf`. |
| `tla/spec/` | Executable TLA+ models and TLC configurations. |
| `tla/counterexamples/` | Intentionally weakened variants; TLC finds a two-owner trace for each, and the `LateTimer` and `StaleOwnerOpen` configurations use overwriting acceptors. |
| `tla/proof/` | TLAPS support-obligation module. |
| `python/paxoslease/` | Executable reference model: simulator, composed PaxosLease/Paxos model, timing, tracing, fencing, and the structured witnesses. |
| `python/demo.py` | Single-file runnable demonstration: correct PaxosLease on real timers, three nodes in one event loop. Reading material, not evidence. |
| `python/tests/` | Scenario tests, property tests, and contract tests. |
| `python/scripts/` | Verification pipeline: claim checking, variant generation, recording. |
| `results/` | Recorded outputs from checks and experiments. |
| `docs/implementation-contract.md` | The protocol/implementation assumptions and evidence boundary. |
| `docs/tooling-instructions.md` | Installing Java, the TLA+ tools, TLAPS, and Python. |
| `build/` | Everything the tools generate. Disposable; `make clean` removes it. |

## Evidence boundary

| Claim type | Repository evidence |
|---|---|
| Finite-state protocol safety | TLC configurations in `tla/spec/`. |
| Arithmetic/proof support | TLAPS obligations in `tla/proof/`. |
| Implementation behavior | Python scenario/property/randomized tests. |
| Unsafe variants | TLA+ counterexamples and `results/counterexamples.json`. |
| Paxos composition | Abstract TLA+ model and deterministic Python admission/recovery model. |

The repository does not claim a complete parameterized TLAPS proof, a production Paxos implementation, or a full reconfiguration protocol. Those boundaries are stated explicitly in the paper and in `docs/implementation-contract.md`.
