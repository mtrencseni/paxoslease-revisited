PYTHON := .venv/bin/python
PIP := .venv/bin/python -m pip
LATEXMK ?= latexmk
TLC_WORKERS ?= 8
MONTE_CARLO_SCHEDULES ?= 10000
MONTE_CARLO_STEPS ?= 100

# Every file any tool generates lands under build/, which is disposable and
# git-ignored: LaTeX auxiliaries, TLC state directories, and the Python
# caches.  Recorded evidence is not generated output in this sense and stays
# in results/, under version control.
BUILD := $(CURDIR)/build
TLC_META := $(BUILD)/tlc
export PYTHONPYCACHEPREFIX := $(BUILD)/pycache
export HYPOTHESIS_STORAGE_DIRECTORY := $(BUILD)/hypothesis

PAPER_DIR := paper
PAPER_TEX := $(PAPER_DIR)/PaxosLease-Revisited.tex
PAPER_PDF := $(PAPER_DIR)/PaxosLease-Revisited.pdf

# TLC writes its state directory under -metadir; -cleanup removes it on a
# successful run, and the ones left by violating runs stay inside build/.
TLC := tlc -cleanup -workers $(TLC_WORKERS) -difftrace -metadir $(TLC_META)

PHONY_EXTRA := nodeowner-base latetimer-a2 check-release-crash2 check-renew-crash3 check-release-crash3
.PHONY: $(PHONY_EXTRA)
.PHONY: all venv paper-source pdf parse lint check check-standalone check-composition paper-evidence paper-evidence-full paper-claims quick check-impl check-impl-colocated check-retry check-retry-mn5 check-renew-retry check-redeliver-crash counterexamples counterexamples-3acceptors counterexamples-staleowner counterexamples-releasecrash releasecrash-a2 counterexamples-renewcrash renewcrash-a2 transport-refinement staleowner-tcp staleowner-a2 interaction-configs impl-colocated-tcp impl-staleowner variant-check expected-counterexamples trace-smoke-test timing-examples unsafe-configs prove test demo monte-carlo results clean

all: parse variant-check check counterexamples prove test monte-carlo expected-counterexamples trace-smoke-test timing-examples unsafe-configs pdf

venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e .[test]


paper-source:
	test -f $(PAPER_TEX)

pdf: paper-source
	mkdir -p $(BUILD)/latex
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error \
		-outdir=$(BUILD)/latex $(PAPER_TEX)
	cp $(BUILD)/latex/PaxosLease-Revisited.pdf $(PAPER_PDF)

parse:
	cd tla/spec && sany PaxosLease.tla
	cd tla/spec && sany PaxosLeaseChecked.tla
	cd tla/spec && sany PaxosLeasePaxos.tla
	cd tla/spec && sany PaxosLeaseImpl.tla
	cd tla/counterexamples && sany LateTimer.tla
	cd tla/counterexamples && sany LateTimerSym.tla
	cd tla/counterexamples && sany OwnerOnlyRelease.tla
	cd tla/counterexamples && sany ScalarQuorumCounting.tla
	cd tla/counterexamples && sany StaleOwnerOpen.tla
	cd tla/counterexamples && sany NodeOwner.tla
	cd tla/counterexamples && sany NodeOwnerSearch.tla
	cd tla/spec && sany NodeOwnerSearchBase.tla
	cd tla/spec && sany PaxosLeaseRenewCrashSearch.tla
	cd tla/spec && sany PaxosLeaseReleaseCrashSearch.tla
	cd tla/spec && sany PaxosLeaseSym.tla
	cd tla/spec && sany PaxosLeaseCheckedSym.tla
	cd tla/proof && sany PaxosLeaseProof.tla

check: check-standalone check-composition

check-standalone:
	cd tla/spec && ($(TLC) -config PaxosLeaseBase.cfg PaxosLeaseChecked.tla || true) > ../../results/check-base.txt 2>&1 && grep -q "No error has been found" ../../results/check-base.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewRelease.cfg PaxosLeaseChecked.tla || true) > ../../results/check-renew-release.txt 2>&1 && grep -q "No error has been found" ../../results/check-renew-release.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseCrashRestart.cfg PaxosLeaseChecked.tla || true) > ../../results/check-crash-restart.txt 2>&1 && grep -q "No error has been found" ../../results/check-crash-restart.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseDrift.cfg PaxosLeaseChecked.tla || true) > ../../results/check-drift.txt 2>&1 && grep -q "No error has been found" ../../results/check-drift.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseQuarantineEqualsProposer.cfg PaxosLeaseChecked.tla || true) > ../../results/check-qep.txt 2>&1 && grep -q "No error has been found" ../../results/check-qep.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseQuarantineEqualsProposer23.cfg PaxosLeaseChecked.tla || true) > ../../results/check-qep23.txt 2>&1 && grep -q "No error has been found" ../../results/check-qep23.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseRedeliver.cfg PaxosLeaseChecked.tla || true) > ../../results/check-redeliver.txt 2>&1 && grep -q "No error has been found" ../../results/check-redeliver.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseReleaseRace.cfg PaxosLeaseChecked.tla || true) > ../../results/release-race.txt 2>&1 && grep -q "No error has been found" ../../results/release-race.txt

# Explicit-retry configuration (AbandonAttempt enabled, three ballots, crash,
# quarantine boundary).  Exhaustive but very large; recorded evidence like
# the other long searches, validated by `paper-claims`, re-run by
# `paper-evidence-full`.
check-retry:
	cd tla/spec && ($(TLC) -config PaxosLeaseRetry.cfg PaxosLeaseChecked.tla || true) > ../../results/retry.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/retry.txt

# Redelivering transport with acceptor crash/restart at the quarantine
# boundary.  Exhaustive but very large; recorded evidence like check-retry.
# The no-crash form (PaxosLeaseRedeliver.cfg) runs fail-fast in
# check-standalone.
check-redeliver-crash:
	cd tla/spec && ($(TLC) -config PaxosLeaseRedeliverCrash.cfg PaxosLeaseChecked.tla || true) > ../../results/redeliver-crash.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/redeliver-crash.txt

check-composition:
	cd tla/spec && ($(TLC) PaxosLeasePaxos.tla || true) > ../../results/composition.txt 2>&1 && grep -q "No error has been found" ../../results/composition.txt

counterexamples:
	cd tla/counterexamples && ($(TLC) -config LateTimer.cfg LateTimer.tla || true) > ../../results/counterexample-latetimer.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-latetimer.txt
	cd tla/counterexamples && ($(TLC) -config OwnerOnlyRelease.cfg OwnerOnlyRelease.tla || true) > ../../results/counterexample-owneronlyrelease.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-owneronlyrelease.txt
	cd tla/counterexamples && ($(TLC) -config ScalarQuorumCounting.cfg ScalarQuorumCounting.tla || true) > ../../results/counterexample-scalarquorumcounting.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-scalarquorumcounting.txt
	cd tla/counterexamples && ($(TLC) -config NodeOwnerSearch.cfg NodeOwnerSearch.tla || true) > ../../results/counterexample-nodeowner.txt 2>&1 && grep -q "Invariant Safety is violated" ../../results/counterexample-nodeowner.txt

# The directed incarnation search on the specification itself (A2 compares
# incarnations): exhausts its constrained space with no violation.
nodeowner-base:
	cd tla/spec && ($(TLC) -config NodeOwnerSearchBase.cfg NodeOwnerSearchBase.tla || true) > ../../results/nodeowner-base.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/nodeowner-base.txt

# The late timer with A2's refusal: unsafe only with overwriting acceptors.
latetimer-a2:
	cd tla/counterexamples && ($(TLC) -config LateTimerA2.cfg LateTimer.tla || true) > ../../results/latetimer-a2.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/latetimer-a2.txt

# Release and renewal with two proposers across crashes, with A2's rule.
# Multi-hour recorded runs; the three-acceptor forms use symmetry reduction.
check-release-crash2:
	cd tla/spec && ($(TLC) -config PaxosLeaseReleaseCrash2.cfg PaxosLeaseChecked.tla || true) > ../../results/release-crash2.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/release-crash2.txt

check-renew-crash3:
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewCrash3.cfg PaxosLeaseCheckedSym.tla || true) > ../../results/renew-crash3.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/renew-crash3.txt

check-release-crash3:
	cd tla/spec && ($(TLC) -config PaxosLeaseReleaseCrash.cfg PaxosLeaseCheckedSym.tla || true) > ../../results/release-crash3.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/release-crash3.txt

variant-check:
	$(PYTHON) python/scripts/generate_variants.py --check

# Static checks over every Python artifact: ruff, and mypy --strict (the
# strictness is not decorative; a ballot tuple built with the wrong element
# order once survived the test suite because homogeneous wrong tuples still
# compare).
lint:
	$(PYTHON) -m ruff check
	$(PYTHON) -m mypy

# Fail-fast evidence target: every result the paper cites except the
# multi-hour searches, whose recorded outputs under results/ are instead
# checked by `paper-claims` (trace lengths and distinct-state counts must
# match what the paper cites).  Any expected pass that fails or expected
# counterexample that is not found aborts with a nonzero exit.
# `paper-evidence-full` additionally re-runs the multi-hour searches.
paper-evidence: parse lint variant-check check check-impl counterexamples unsafe-configs prove test expected-counterexamples trace-smoke-test timing-examples paper-claims

paper-evidence-full: paper-evidence nodeowner-base latetimer-a2 transport-refinement interaction-configs check-retry check-renew-retry counterexamples-staleowner counterexamples-releasecrash releasecrash-a2 counterexamples-renewcrash renewcrash-a2 staleowner-tcp staleowner-a2 counterexamples-3acceptors check-impl-colocated impl-colocated-tcp impl-staleowner
	$(PYTHON) python/scripts/check_paper_claims.py

# Cross-check the paper's cited numbers (trace lengths, exhaustive state
# counts, recorded-search sizes) against results/.
paper-claims:
	$(PYTHON) python/scripts/check_paper_claims.py

# Fast subset for iteration: parses, lint, variant drift, Python tests, witnesses.
quick: parse lint variant-check test expected-counterexamples

# The implementation's protocol (spec/PaxosLeaseImpl.tla): lease timer at
# prepare-quorum receipt plus an attempt timeout, as shipped in Keyspace and
# ScalienDB.  Three passing boundary configs under timely timeout dispatch,
# three violation configs (below the bound, retry timeout exceeding the
# quarantine, and the shipped constants under delayed dispatch); the
# colocation-valid three-acceptor violation has its own target below.
# Long-running; part of `paper-evidence` but not of `all`.
check-impl:
	cd tla/spec && ($(TLC) -config PaxosLeaseImplTimelyShipped.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-timely-shipped.txt 2>&1 && grep -q "No error has been found" ../../results/impl-timely-shipped.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplTimelyBoundary.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-timely-boundary.txt 2>&1 && grep -q "No error has been found" ../../results/impl-timely-boundary.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplTimelyRDominantSafe.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-timely-rdominant-safe.txt 2>&1 && grep -q "No error has been found" ../../results/impl-timely-rdominant-safe.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplTimelyBelow.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-timely-below.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-timely-below.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplTimelyRDominant.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-timely-rdominant.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-timely-rdominant.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplDelayedShipped.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-delayed-shipped.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-delayed-shipped.txt

# The colocation-valid three-acceptor delayed-dispatch violation (only the
# quorum-intersection acceptor may crash).  Multi-hour search; recorded
# evidence like the three-acceptor counterexamples, not part of
# `paper-evidence`.
check-impl-colocated:
	cd tla/spec && ($(TLC) -config PaxosLeaseImplDelayedColocated.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-delayed-colocated.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-delayed-colocated.txt

# The stale-owner-open violation: P2's renewal qualifier dropped, retry
# enabled, full quarantine.  Multi-hour search (the recorded run explored
# 2.67B distinct states); recorded evidence like the other long searches.
counterexamples-staleowner:
	cd tla/counterexamples && ($(TLC) -config StaleOwnerOpen.cfg StaleOwnerOpen.tla || true) > ../../results/counterexample-staleowneropen.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-staleowneropen.txt

# Transport-realizability refinement (CrashDropsIncoming = TRUE): the two
# fast checks.  Every trap survives connection semantics; the multi-hour
# forms (StaleOwnerOpenTcp, StaleOwnerOpenA2, ImplDelayedColocatedTcp) are
# recorded evidence validated by `paper-claims`.
transport-refinement:
	cd tla/counterexamples && ($(TLC) -config LateTimerTcp.cfg LateTimer.tla || true) > ../../results/counterexample-latetimer-tcp.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-latetimer-tcp.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseImplDelayedShippedTcp.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-delayed-shipped-tcp.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-delayed-shipped-tcp.txt

# The multi-hour transport and repair experiments, recorded evidence.
# Early release across an acceptor restart: a directed search (its state
# constraint only prunes behaviours) that finds a 40-state two-owner trace on
# the specification with overwriting acceptors (RefuseLiveOverwrite = FALSE).
# About 50 minutes on 8 workers.
counterexamples-releasecrash:
	cd tla/spec && ($(TLC) -config PaxosLeaseReleaseCrashSearch.cfg PaxosLeaseReleaseCrashSearch.tla || true) > ../../results/counterexample-releasecrash.txt 2>&1 && grep -q "Invariant Safety is violated" ../../results/counterexample-releasecrash.txt

releasecrash-a2:
	cd tla/spec && ($(TLC) -config PaxosLeaseReleaseCrashSearchA2.cfg PaxosLeaseReleaseCrashSearch.tla || true) > ../../results/releasecrash-a2.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/releasecrash-a2.txt

# Renewal with one acceptor restart and three acceptors, qualifier in force:
# a directed search (its state constraint only prunes behaviours) that finds a
# 39-state two-owner trace with overwriting acceptors, and the same
# search with A2's acceptor-side rule, which exhausts the space with no error.
# About 7 minutes each on 8 workers.
counterexamples-renewcrash:
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewCrashSearch.cfg PaxosLeaseRenewCrashSearch.tla || true) > ../../results/counterexample-renewcrash.txt 2>&1 && grep -q "Invariant Safety is violated" ../../results/counterexample-renewcrash.txt

renewcrash-a2:
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewCrashSearchA2.cfg PaxosLeaseRenewCrashSearch.tla || true) > ../../results/renewcrash-a2.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/renewcrash-a2.txt

staleowner-tcp:
	cd tla/counterexamples && ($(TLC) -config StaleOwnerOpenTcp.cfg StaleOwnerOpen.tla || true) > ../../results/staleowner-tcp.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/staleowner-tcp.txt

staleowner-a2:
	cd tla/counterexamples && ($(TLC) -config StaleOwnerOpenA2.cfg StaleOwnerOpen.tla || true) > ../../results/staleowner-a2.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/staleowner-a2.txt

# Feature-interaction configurations.  The two fast ones run here; the
# multi-hour RenewRetry and the MaxNetwork = 5 sensitivity run are recorded
# evidence with their own targets.
interaction-configs:
	cd tla/spec && ($(TLC) -config PaxosLeaseRetryRedeliver.cfg PaxosLeaseChecked.tla || true) > ../../results/retry-redeliver.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/retry-redeliver.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewReleaseStale.cfg PaxosLeaseChecked.tla || true) > ../../results/renew-release-stale.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/renew-release-stale.txt

check-renew-retry:
	cd tla/spec && ($(TLC) -config PaxosLeaseRenewRetry.cfg PaxosLeaseChecked.tla || true) > ../../results/renew-retry.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/renew-retry.txt

check-retry-mn5:
	cd tla/spec && ($(TLC) -config PaxosLeaseRetryMN5.cfg PaxosLeaseChecked.tla || true) > ../../results/retry-mn5.txt 2>&1 && grep -q "Model checking completed. No error has been found" ../../results/retry-mn5.txt

impl-colocated-tcp:
	cd tla/spec && ($(TLC) -config PaxosLeaseImplDelayedColocatedTcp.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-delayed-colocated-tcp.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/impl-delayed-colocated-tcp.txt

# The stale-owner composition inside the implementation projection: shipped
# timely constants, three ballots, connection-lifecycle transport.
# Multi-hour recorded run.
impl-staleowner:
	cd tla/spec && ($(TLC) -config PaxosLeaseImplStaleOwner.cfg PaxosLeaseImpl.tla || true) > ../../results/impl-staleowner.txt 2>&1 && grep -q "Invariant Safety is violated" ../../results/impl-staleowner.txt

# Three-acceptor LateTimer violation (~40 min, ~150M states even with
# symmetry reduction); recorded evidence, not part of `all`.
counterexamples-3acceptors:
	cd tla/counterexamples && ($(TLC) -config LateTimer3.cfg LateTimerSym.tla || true) > ../../results/counterexample-latetimer-3acceptors.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/counterexample-latetimer-3acceptors.txt
	cd tla/spec && ($(TLC) -config PaxosLeaseUnsafeQuarantine3.cfg PaxosLeaseSym.tla || true) > ../../results/unsafe-config-3acceptors.txt 2>&1 && grep -q "Invariant LeaseExclusivity is violated" ../../results/unsafe-config-3acceptors.txt

expected-counterexamples:
	$(PYTHON) python/scripts/run_counterexamples.py

trace-smoke-test:
	$(PYTHON) python/scripts/trace_smoke_test.py

timing-examples:
	$(PYTHON) python/scripts/timing_examples.py

unsafe-configs:
	$(PYTHON) python/scripts/check_unsafe_config.py

prove:
	cd tla/proof && tlapm --threads $(TLC_WORKERS) PaxosLeaseProof.tla

test:
	$(PYTHON) -m pytest -q

# The single-file demonstration: correct PaxosLease, three nodes on real
# timers.  Reading material, not evidence.
demo:
	$(PYTHON) python/demo.py

monte-carlo:
	$(PYTHON) python/scripts/run_monte_carlo.py --schedules $(MONTE_CARLO_SCHEDULES) --steps $(MONTE_CARLO_STEPS)

results: parse
	$(PYTHON) python/scripts/run_and_record.py

clean:
	rm -rf $(BUILD)
