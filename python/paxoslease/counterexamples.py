from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .event_loop import run_suspended_loop, run_timely_loop
from .fencing import FencedResource, UnfencedResource
from .messages import Message
from .monte_carlo import acquire_on
from .simulator import Simulator


@dataclass(frozen=True)
class CounterexampleResult:
    scenario: str
    violated_invariant: str
    minimal_fix: str
    trace: tuple[str, ...]
    category: str


# The witnesses are NOT all comparable evidence, and the category says which
# kind each one is:
#   simulator-execution  -- a deterministic protocol execution in the
#                           reference simulator violates a checked invariant;
#   composed-model-execution -- same, in the composed lease+Paxos model;
#   illustrative-example -- executable, but the broken rule is applied by the
#                           witness itself rather than by the protocol model;
#   unit-rule            -- a direct assertion connecting a local rule to its
#                           failure, with no protocol execution at all.
# The TLC counterexamples in counterexamples/*.tla are a separate, stronger
# class: there the model checker finds the violating schedule itself.
CATEGORIES = {
    "insufficient-quarantine": "simulator-execution",
    "owner-only-release": "illustrative-example",
    "duplicate-quorum-counting": "unit-rule",
    "ballot-reuse-after-restart": "unit-rule",
    "skipped-paxos-recovery": "composed-model-execution",
    "unfenced-external-effect": "illustrative-example",
    "nonintersecting-reconfiguration": "illustrative-example",
    "unsafe-clock-source": "unit-rule",
    "renewal-without-quorum": "unit-rule",
    "stale-accept-overwrites-newer": "unit-rule",
    "late-promise-reuse": "simulator-execution",
    "stale-owner-open": "simulator-execution",
    "release-after-stale-accept": "simulator-execution",
    "renewal-over-overwritten-grant": "simulator-execution",
    "release-across-proposer-restart": "simulator-execution",
    "split-brain-read-without-fence": "unit-rule",
    "suspended-event-loop": "simulator-execution",
    "unsigned-expiry-underflow": "unit-rule",
}

# The assertion message each witness is required to fail with.  Matching the
# message keeps an unrelated AssertionError from masquerading as the expected
# violation.
EXPECTED_VIOLATION = {
    "insufficient-quarantine": "lease exclusivity violated",
    "owner-only-release": "owner-only release erased newer lease",
    "duplicate-quorum-counting": "duplicate responses counted as a quorum",
    "ballot-reuse-after-restart": "ballot reused after restart",
    "skipped-paxos-recovery": "skipped recovery ignored a prior accepted value",
    "nonintersecting-reconfiguration": "do not intersect",
    "unsafe-clock-source": "wall-clock step made an expired lease look live",
    "renewal-without-quorum": "failed renewal extended authority",
    "stale-accept-overwrites-newer": "stale lower-ballot accept overwrote newer promise",
    "late-promise-reuse": "lease exclusivity violated",
    "stale-owner-open": "lease exclusivity violated",
    "release-after-stale-accept": "lease exclusivity violated",
    "renewal-over-overwritten-grant": "lease exclusivity violated",
    "release-across-proposer-restart": "lease exclusivity violated",
    "split-brain-read-without-fence": "unfenced read was concurrent",
    "suspended-event-loop": "lease exclusivity violated during event-loop suspension",
    "unsigned-expiry-underflow": "unsigned expiry subtraction underflowed",
}


def _expect_violation(scenario: str, fn: Callable[[], tuple[str, ...]]) -> CounterexampleResult:
    try:
        trace = fn()
    except AssertionError as exc:
        expected = EXPECTED_VIOLATION[scenario]
        if expected not in str(exc):
            raise AssertionError(
                f"{scenario} failed with an unexpected assertion: {exc!r} "
                f"(expected message containing {expected!r})"
            ) from exc
        return CounterexampleResult(
            scenario=scenario,
            violated_invariant=str(exc),
            minimal_fix=FIXES[scenario],
            trace=(f"violation: {exc}",),
            category=CATEGORIES[scenario],
        )
    raise AssertionError(f"{scenario} did not fail; trace={trace}")


FIXES = {
    "insufficient-quarantine": "quarantine for at least the proposer attempt duration in real time",
    "owner-only-release": "release must name the exact owner and ballot",
    "duplicate-quorum-counting": "count quorum responses by distinct acceptor identity",
    "ballot-reuse-after-restart": "include a durable restart counter or external uniqueness component in ballots",
    "skipped-paxos-recovery": "client admission requires completed Paxos Phase 1 recovery",
    "unfenced-external-effect": "protected resources must reject stale fencing tokens",
    "nonintersecting-reconfiguration": "configuration changes must preserve quorum intersection or wait out old leases",
    "unsafe-clock-source": "lease timers must be monotonic elapsed-time measurements with bounded rate error",
    "renewal-without-quorum": "renewal may extend authority only after a fresh accept quorum",
    "stale-accept-overwrites-newer": "acceptors must reject lower ballots after promising a higher ballot",
    "late-promise-reuse": "with acceptors that overwrite, start the attempt deadline when Prepare is sent, so prepare responses expire with the attempt that collected them; A2's acceptor-side rule also prevents this",
    "stale-owner-open": "with acceptors that overwrite, count a reported own lease as open only while renewing (currently active); a stale own record must block like a foreign lease; A2's acceptor-side rule also prevents this",
    "release-after-stale-accept": "with early release enabled, an acceptor must never replace a live lease of a different owner (A2's acceptor-side rule); exact-instance matching in A3 is not enough",
    "renewal-over-overwritten-grant": "an acceptor must never replace a live lease of a different owner (A2's acceptor-side rule); the renewal qualifier alone does not prevent this",
    "release-across-proposer-restart": "A2 must compare owners as proposer incarnations (node and restart counter), since a restarted proposer's ballots may be lower than its previous incarnation's",
    "split-brain-read-without-fence": "external reads and writes require either log ordering or fencing",
    "suspended-event-loop": "store the attempt deadline as protocol state and check it in the Phase 2 response handler, instead of relying on timer dispatch order",
    "unsigned-expiry-underflow": "read the clock once per handler, compare before subtracting, and keep deadline arithmetic away from unsigned wraparound",
}


def insufficient_quarantine() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        sim = Simulator(proposer_duration=4, acceptor_duration=4, quarantine=0, unsafe=True)
        acquire_on(sim, "p1")
        for aid in ("a1", "a2"):
            sim.crash_acceptor(aid)
            sim.restart_acceptor(aid)
        sim.start_acquire("p2")
        for aid in ("a1", "a2"):
            sim.deliver_kind("prepare", dst=aid, src="p2")
        for aid in ("a1", "a2"):
            sim.deliver_kind("promise", dst="p2", src=aid)
        for aid in ("a1", "a2"):
            sim.deliver_kind("accept", dst=aid, src="p2")
        for aid in ("a1", "a2"):
            sim.deliver_kind("accepted", dst="p2", src=aid)
        return ()

    return _expect_violation("insufficient-quarantine", run)


def owner_only_release() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        sim = Simulator(proposer_duration=6, acceptor_duration=6, quarantine=6)
        acquire_on(sim, "p1")
        old = sim.proposers["p1"].active_ballot
        sim.start_acquire("p1")
        for aid in ("a1", "a2"):
            sim.deliver_kind("prepare", dst=aid, src="p1")
        for aid in ("a1", "a2"):
            sim.deliver_kind("promise", dst="p1", src=aid)
        for aid in ("a1", "a2"):
            sim.deliver_kind("accept", dst=aid, src="p1")
        for aid in ("a1", "a2"):
            sim.deliver_kind("accepted", dst="p1", src=aid)
        new = sim.proposers["p1"].active_ballot
        assert old != new
        stale = Message("release", "p1", "a1", ballot=old)
        # Broken behavior: owner-only release clears the newer lease.
        if sim.acceptors["a1"].accepted is not None and sim.acceptors["a1"].accepted.owner == stale.src:
            sim.acceptors["a1"].accepted = None
        assert sim.acceptors["a1"].accepted is not None, "owner-only release erased newer lease"
        return ()

    return _expect_violation("owner-only-release", run)


def duplicate_quorum_counting() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        responders = ["a1", "a1"]
        assert len(responders) == len(set(responders)), "duplicate responses counted as a quorum"
        return ()

    return _expect_violation("duplicate-quorum-counting", run)


def ballot_reuse_after_restart() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        first = (1, 1, "p1")
        after_restart = (1, 1, "p1")  # broken: same counter, same restart component
        assert after_restart != first, "ballot reused after restart"
        return ()

    return _expect_violation("ballot-reuse-after-restart", run)


def skipped_paxos_recovery() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        from .leased_paxos import LeasedPaxosCluster

        cluster = LeasedPaxosCluster()
        assert cluster.acquire_lease("p1")
        cluster.recover_and_become_ready("p1")
        cluster.accept_without_leader_learning("p1", 1, "old", ("pa1",))
        cluster.tick(4)
        assert cluster.acquire_lease("p2")
        cluster.state["p2"] = "ready"  # Broken: skips recovery.
        cluster.leader_ballot["p2"] = (99, 0, "p2")
        slot, value = cluster.append("p2", "new")
        assert not (slot == 1 and value == "new"), "skipped recovery ignored a prior accepted value"
        return ()

    return _expect_violation("skipped-paxos-recovery", run)


def unfenced_external_effect() -> CounterexampleResult:
    old = (1, 1, "p1")
    new = (2, 1, "p2")
    unfenced = UnfencedResource()
    assert unfenced.apply(new, "new-owner-write")
    assert unfenced.apply(old, "delayed-old-owner-write")

    fenced = FencedResource()
    assert fenced.apply(new, "new-owner-write")
    assert not fenced.apply(old, "delayed-old-owner-write")
    return CounterexampleResult(
        scenario="unfenced-external-effect",
        violated_invariant="unfenced resource accepted delayed stale owner operation",
        minimal_fix=FIXES["unfenced-external-effect"],
        trace=("new owner writes", "old delayed write is accepted without fencing", "fenced model rejects it"),
        category=CATEGORIES["unfenced-external-effect"],
    )


def nonintersecting_reconfiguration() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        old_quorum = {"a1", "a2"}
        new_quorum = {"a3", "a4"}
        assert old_quorum & new_quorum, "old and new lease quorums do not intersect"
        return ()

    return _expect_violation("nonintersecting-reconfiguration", run)


def unsafe_clock_source() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        monotonic_elapsed = 4
        wall_clock_elapsed_after_step_back = 1
        assert wall_clock_elapsed_after_step_back >= monotonic_elapsed, (
            "wall-clock step made an expired lease look live"
        )
        return ()

    return _expect_violation("unsafe-clock-source", run)


def renewal_without_quorum() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        old_deadline = 4
        renewal_acks = {"a1"}
        quorum_size_needed = 2
        new_deadline = 8 if renewal_acks else old_deadline
        assert not (len(renewal_acks) < quorum_size_needed and new_deadline > old_deadline), (
            "failed renewal extended authority without a quorum"
        )
        return ()

    return _expect_violation("renewal-without-quorum", run)


def stale_accept_overwrites_newer() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        promised = (7, 1, "p2")
        stale_accept_ballot = (3, 1, "p1")
        accepted = stale_accept_ballot  # Broken acceptor ignores its promise.
        assert not (stale_accept_ballot < promised and accepted == stale_accept_ballot), (
            "stale lower-ballot accept overwrote newer promise"
        )
        return ()

    return _expect_violation("stale-accept-overwrites-newer", run)


def late_promise_reuse() -> CounterexampleResult:
    """Two leaders under the original 2012 step-3 timer rule, despite full quarantine.

    The proposer timer starts only when a prepare quorum is received, so nothing
    bounds how stale that quorum is.  Both proposers legitimately collect empty
    promises, the acceptors crash, forget their promises, restart, and serve the
    entire quarantine -- and then both proposers complete Phase 2 against the
    amnesiac acceptors and are active at the same instant.  This mirrors the TLC
    trace for counterexamples/LateTimer.tla.
    """

    def run() -> tuple[str, ...]:
        # Under the overwriting A2 of the 2012 paper and both audited
        # implementations, the rule this witness was found against.
        sim = Simulator(
            proposer_duration=4,
            acceptor_duration=4,
            quarantine=4,
            timer_at_quorum=True,
            refuse_live_overwrite=False,
        )
        sim.start_acquire("p1")
        sim.start_acquire("p2")
        for pid in ("p1", "p2"):
            for aid in ("a1", "a2"):
                sim.deliver_kind("prepare", dst=aid, src=pid)
        # The promise responses stay in flight while the acceptors crash,
        # forget them, restart, and wait out the FULL quarantine.
        for aid in ("a1", "a2"):
            sim.crash_acceptor(aid)
            sim.restart_acceptor(aid)
        sim.tick(4)
        # Under the step-3 rule each proposer's timer starts only now.
        for pid in ("p1", "p2"):
            for aid in ("a1", "a2"):
                sim.deliver_kind("promise", dst=pid, src=aid)
            for aid in ("a1", "a2"):
                sim.deliver_kind("accept", dst=aid, src=pid)
            for aid in ("a1", "a2"):
                sim.deliver_kind("accepted", dst=pid, src=aid)
        return ()

    return _expect_violation("late-promise-reuse", run)


def _stale_owner_open_schedule(sim: Simulator) -> None:
    """The shared schedule: p2 abandons an attempt with its accepts still in
    flight, p1 acquires under a lower ballot after crash, restart, and the
    FULL quarantine, the stale accepts overwrite p1's records, and p2
    retries, seeing "its own" lease reported everywhere."""
    # p2's first attempt: (1, 1, "p2"), which beats p1's (1, 1, "p1") on
    # the node tiebreak, mirroring a retrying proposer's higher ballot.
    sim.start_acquire("p2")
    for aid in ("a1", "a2"):
        sim.deliver_kind("prepare", dst=aid, src="p2")
    for aid in ("a1", "a2"):
        sim.deliver_kind("promise", dst="p2", src=aid)
    # The accept requests are now in flight; p2 gives up the attempt.
    sim.abandon("p2")
    for aid in ("a1", "a2"):
        sim.crash_acceptor(aid)
        sim.restart_acceptor(aid)
    sim.tick(2)  # the FULL quarantine is served
    # p1 acquires cleanly under its lower first ballot.
    sim.start_acquire("p1")
    for aid in ("a1", "a2"):
        sim.deliver_kind("prepare", dst=aid, src="p1")
    for aid in ("a1", "a2"):
        sim.deliver_kind("promise", dst="p1", src=aid)
    for aid in ("a1", "a2"):
        sim.deliver_kind("accept", dst=aid, src="p1")
    for aid in ("a1", "a2"):
        sim.deliver_kind("accepted", dst="p1", src=aid)
    assert "p1" in sim.active_owners()
    # The abandoned attempt's higher-ballot accepts land late, overwriting
    # p1's records with a stale p2-owned lease (ballot order permits it;
    # p1's authority is untouched, only its acceptor records are erased).
    for aid in ("a1", "a2"):
        sim.deliver_kind("accept", dst=aid, src="p2")
    # p2 retries with a fresh higher ballot and sees "its own" lease
    # reported by every acceptor.
    sim.start_acquire("p2")
    for aid in ("a1", "a2"):
        sim.deliver_kind("prepare", dst=aid, src="p2")
    for aid in ("a1", "a2"):
        sim.deliver_kind("promise", dst="p2", src=aid)


def stale_owner_open() -> CounterexampleResult:
    """Two owners when a proposer counts its own stale lease as open.

    Dropping P2's renewal qualifier (an own lease counts as open even while
    not active) lets a retrying proposer treat the record installed by its
    own abandoned attempt as permission.  Mirrors the 36-state TLC trace for
    counterexamples/StaleOwnerOpen.tla; both audited implementations implement
    the unqualified rule (StartProposing proceeds with a full fresh duration
    whenever the discovered lease owner is the node itself)."""

    def run() -> tuple[str, ...]:
        sim = Simulator(
            acceptor_ids=("a1", "a2"),
            proposer_duration=2,
            acceptor_duration=2,
            quarantine=2,
            self_open_when_inactive=True,
            refuse_live_overwrite=False,  # the overwriting A2 it was found against
        )
        _stale_owner_open_schedule(sim)
        # The unqualified rule counted the stale own lease as open, so the
        # accept round completes and p2 activates beside p1.  Draining the
        # queue delivers p2's fresh accepts and their responses (the
        # abandoned attempt's stale responses are discarded by the ballot
        # check on the way).
        while sim.queue:
            sim.deliver(0)
        return ()

    return _expect_violation("stale-owner-open", run)


def _deliver_exact(sim: Simulator, kind: str, dst: str, src: str, ballot: object) -> None:
    """Deliver the queued message matching kind, endpoints AND ballot, so a
    stale message of an earlier attempt cannot be picked by mistake."""
    for msg in sim.queue:
        if str(msg.kind) == kind and msg.dst == dst and msg.src == src and msg.ballot == ballot:
            sim.deliver_by_id(msg.id)
            return
    raise AssertionError(f"no queued {kind} {src}->{dst} under ballot {ballot}")


def _release_after_stale_accept_schedule(sim: Simulator) -> object:
    """The shared schedule, on the UNMODIFIED rules: p2 acquires and
    releases early with its accept and release to a3 still in flight; one
    acceptor restarts and serves the FULL quarantine; p1 acquires under a
    lower ballot through a2 and a3; the stale accept then reinstalls p2's
    released instance over p1's live record at a3 (ballot order permits it),
    and the stale release, matching that instance exactly, clears it.  p2
    finally prepares a fresh ballot on a1 and a3.  Returns that ballot."""
    # p2's first ballot (1, 1, "p2") beats p1's (1, 1, "p1") on the node
    # tiebreak.  a3 never sees p2's prepare, so it never promises that ballot.
    sim.start_acquire("p2")
    first = sim.proposers["p2"].ballot
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "prepare", aid, "p2", first)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "promise", "p2", aid, first)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "accept", aid, "p2", first)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "accepted", "p2", aid, first)
    assert sim.active_owners() == {"p2"}
    # P6: p2 stops owning and releases; the release to a3 stays in flight.
    sim.release("p2")
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "release", aid, "p2", first)
    # a2 forgets its promise of p2's ballot and serves the FULL quarantine.
    sim.crash_acceptor("a2")
    sim.restart_acceptor("a2")
    sim.tick(sim.quarantine)
    # p1 acquires cleanly under its lower first ballot through a2 and a3.
    sim.start_acquire("p1")
    lower = sim.proposers["p1"].ballot
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "prepare", aid, "p1", lower)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "promise", "p1", aid, lower)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "accept", aid, "p1", lower)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "accepted", "p1", aid, lower)
    assert sim.active_owners() == {"p1"}
    # The stale accept reinstalls p2's released instance over p1's live
    # record at a3, and the stale release then matches it exactly (A3).
    _deliver_exact(sim, "accept", "a3", "p2", first)
    _deliver_exact(sim, "release", "a3", "p2", first)
    # p2 prepares afresh; a1's record was released and a3's just cleared.
    sim.start_acquire("p2")
    fresh = sim.proposers["p2"].ballot
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "prepare", aid, "p2", fresh)
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "promise", "p2", aid, fresh)
    return fresh


def release_after_stale_accept() -> CounterexampleResult:
    """Two owners under the overwriting A2 once early release is enabled.

    A3 clears a record only if it names the exact released instance, which
    stops a stale release from erasing a NEWER lease of the same owner
    (owner-only-release), but not from erasing an instance a stale accept
    has just REINSTALLED over another owner's live lease.  The clear takes
    the exclusion deadline with it, so the live owner's protection is gone.
    Neither the renewal qualifier (P2) nor any quarantine length prevents
    it; the acceptor-side rule of refusing to replace a live lease of a
    different owner does (see the contract test).  One acceptor restart is
    enough.  The directed TLC search PaxosLeaseReleaseCrashSearch.cfg, with
    overwriting acceptors, finds the same kind of violation."""

    def run() -> tuple[str, ...]:
        sim = Simulator(
            proposer_duration=1,
            acceptor_duration=1,
            quarantine=1,
            refuse_live_overwrite=False,  # the overwriting A2 it defeats
        )
        fresh = _release_after_stale_accept_schedule(sim)
        for aid in ("a1", "a3"):
            _deliver_exact(sim, "accept", aid, "p2", fresh)
        for aid in ("a1", "a3"):
            _deliver_exact(sim, "accepted", "p2", aid, fresh)
        return ()

    return _expect_violation("release-after-stale-accept", run)


def _renewal_over_overwritten_grant_schedule(sim: Simulator) -> None:
    """p2 (higher ballot) and p1 (lower ballot) race; a3 promises p2 and then
    restarts, forgetting the promise.  a1 accepts p1's lease; p2 then
    acquires through promises from a3 (sent before the crash) and a2, and
    its Accept reaches a1 and a2.  Under the overwriting A2, a1 replaces
    p1's live record with p2's.  p2 renews while it still holds its lease,
    so the qualifier counts a1's and a2's reports of that exact lease as
    open.  When a3 leaves quarantine it has forgotten its promise to p2 and
    accepts p1's delayed Accept, completing p1's majority {a1, a3}.  No
    message is stale, no clock errs, and the quarantine is the full bound."""
    sim.start_acquire("p2")
    high = sim.proposers["p2"].ballot
    _deliver_exact(sim, "prepare", "a3", "p2", high)
    _deliver_exact(sim, "promise", "p2", "a3", high)
    sim.tick(1)
    sim.crash_acceptor("a3")
    sim.restart_acceptor("a3")
    sim.tick(1)
    sim.start_acquire("p1")
    low = sim.proposers["p1"].ballot
    assert low is not None and high is not None and low < high
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "prepare", aid, "p1", low)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "promise", "p1", aid, low)
    _deliver_exact(sim, "accept", "a1", "p1", low)
    _deliver_exact(sim, "accepted", "p1", "a1", low)
    _deliver_exact(sim, "prepare", "a2", "p2", high)
    _deliver_exact(sim, "promise", "p2", "a2", high)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "accept", aid, "p2", high)
    for aid in ("a1", "a2"):
        for msg in sim.queue:
            if str(msg.kind) == "accepted" and msg.src == aid and msg.dst == "p2" and msg.ballot == high:
                sim.deliver_by_id(msg.id)
                break


def renewal_over_overwritten_grant() -> CounterexampleResult:
    """Two owners with the renewal qualifier in force, once an acceptor may
    overwrite a live lease of a different owner.  A forgotten promise
    protected the overwriting lease, and the quarantine covers that attempt
    but not the renewal built on it.  The TLC configuration
    PaxosLeaseRenewCrashSearch.cfg finds the same violation on the
    specification (39-state trace); with RefuseLiveOverwrite it passes."""

    def run() -> tuple[str, ...]:
        sim = Simulator(
            proposer_duration=100,
            acceptor_duration=100,
            quarantine=100,
            refuse_live_overwrite=False,  # the overwriting A2
        )
        _renewal_over_overwritten_grant_schedule(sim)
        assert sim.active_owners() == {"p2"}
        sim.tick(48)
        sim.start_acquire("p2")  # renewal of the lease p2 still holds
        renewal = sim.proposers["p2"].ballot
        for aid in ("a1", "a2"):
            _deliver_exact(sim, "prepare", aid, "p2", renewal)
        for aid in ("a1", "a2"):
            _deliver_exact(sim, "promise", "p2", aid, renewal)
        for aid in ("a1", "a2"):
            _deliver_exact(sim, "accept", aid, "p2", renewal)
        for aid in ("a1", "a2"):
            _deliver_exact(sim, "accepted", "p2", aid, renewal)
        sim.tick(51)  # a3 leaves quarantine; p2's renewal runs to t=150
        low = sim.proposers["p1"].ballot
        _deliver_exact(sim, "accept", "a3", "p1", low)
        _deliver_exact(sim, "accepted", "p1", "a3", low)
        return ()

    return _expect_violation("renewal-over-overwritten-grant", run)


def split_brain_read_without_fence() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        p1_serves_read = True
        p2_commits_write = True
        ordered_by_log_or_fence = False
        assert not (p1_serves_read and p2_commits_write and not ordered_by_log_or_fence), (
            "unfenced read was concurrent with a newer owner write"
        )
        return ()

    return _expect_violation("split-brain-read-without-fence", run)


def suspended_event_loop() -> CounterexampleResult:
    def run() -> tuple[str, ...]:
        # The paired timely execution must NOT violate: the acquisition
        # timeout fires first and rotates the proposal identifier.
        run_timely_loop()
        return run_suspended_loop()

    return _expect_violation("suspended-event-loop", run)


def unsigned_expiry_underflow() -> CounterexampleResult:
    """The Phase 2 handlers in both audited systems read the clock once for
    the expiry guard and again for the activation-margin subtraction, with
    uint64_t deadlines (PLeaseProposer.cpp:124 and 144-145,
    PaxosLeaseProposer.cpp:114 and 129).  If the clock crosses the deadline
    between the two reads (a pause between the calls, or a forward step),
    the subtraction wraps and the margin check passes on an expired
    lease."""

    def run() -> tuple[str, ...]:
        u64 = 1 << 64
        expire_time = 8000
        # First read: the expiry guard passes with a millisecond to spare.
        now = 7999
        assert not (expire_time < now)
        # Second read: the clock has crossed the deadline in between.
        now = 8001
        remaining = (expire_time - now) % u64  # uint64_t arithmetic
        assert not (remaining > 500), (
            f"unsigned expiry subtraction underflowed to {remaining} and "
            "passed the activation margin after the expiry guard had "
            "already been cleared"
        )
        return ()

    return _expect_violation("unsigned-expiry-underflow", run)


def _release_across_proposer_restart_schedule(sim: Simulator) -> None:
    """p1's first incarnation acquires under (2, 1, p1) through a1 and a2 and
    releases, with its prepare, accept and release to a3 still in flight.
    p1 restarts; its attempt counter starts again, so its new ballot
    (1, 2, p1) is LOWER than the old one.  a2 restarts and serves the full
    quarantine, and p1's new incarnation acquires through a2 and a3.  The
    stale accept of the old incarnation then reaches a3: its ballot is
    higher and its node is the same, so an acceptor that compares owners by
    node replaces the live record, and the stale release clears it.  p2
    then acquires through a1 and a3 while p1 is active."""
    sim.start_acquire("p1")
    sim.abandon("p1")
    sim.start_acquire("p1")
    old = sim.proposers["p1"].ballot
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "prepare", aid, "p1", old)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "promise", "p1", aid, old)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "accept", aid, "p1", old)
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "accepted", "p1", aid, old)
    sim.release("p1")
    for aid in ("a1", "a2"):
        _deliver_exact(sim, "release", aid, "p1", old)
    sim.crash_proposer("p1")
    sim.restart_proposer("p1")
    sim.crash_acceptor("a2")
    sim.restart_acceptor("a2")
    sim.tick(sim.quarantine)
    sim.start_acquire("p1")
    new = sim.proposers["p1"].ballot
    assert new is not None and old is not None and new < old
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "prepare", aid, "p1", new)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "promise", "p1", aid, new)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "accept", aid, "p1", new)
    for aid in ("a2", "a3"):
        _deliver_exact(sim, "accepted", "p1", aid, new)
    assert sim.proposers["p1"].active
    _deliver_exact(sim, "accept", "a3", "p1", old)
    _deliver_exact(sim, "release", "a3", "p1", old)
    for _ in range(3):
        sim.start_acquire("p2")
        sim.abandon("p2")
    sim.start_acquire("p2")
    high = sim.proposers["p2"].ballot
    assert high is not None and high > old
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "prepare", aid, "p2", high)
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "promise", "p2", aid, high)
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "accept", aid, "p2", high)
    for aid in ("a1", "a3"):
        _deliver_exact(sim, "accepted", "p2", aid, high)


def release_across_proposer_restart() -> CounterexampleResult:
    """Two owners with A2's refusal in force, if the refusal compares owners
    by node rather than by proposer incarnation.  A restart resets the
    attempt counter, so a stale accept request of the previous incarnation
    can carry a higher ballot than the current lease."""

    def run() -> tuple[str, ...]:
        sim = Simulator(
            proposer_duration=2,
            acceptor_duration=2,
            quarantine=2,
            incarnation_owner=False,  # the node-only comparison it defeats
        )
        _release_across_proposer_restart_schedule(sim)
        return ()

    return _expect_violation("release-across-proposer-restart", run)


COUNTEREXAMPLES = (
    insufficient_quarantine,
    owner_only_release,
    duplicate_quorum_counting,
    ballot_reuse_after_restart,
    skipped_paxos_recovery,
    unfenced_external_effect,
    nonintersecting_reconfiguration,
    unsafe_clock_source,
    renewal_without_quorum,
    stale_accept_overwrites_newer,
    late_promise_reuse,
    stale_owner_open,
    release_after_stale_accept,
    release_across_proposer_restart,
    renewal_over_overwritten_grant,
    split_brain_read_without_fence,
    suspended_event_loop,
    unsigned_expiry_underflow,
)
