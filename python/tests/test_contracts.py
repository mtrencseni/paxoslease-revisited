from __future__ import annotations

import pytest

from paxoslease.counterexamples import COUNTEREXAMPLES, CounterexampleResult
from paxoslease.fencing import FencedResource, UnfencedResource
from paxoslease.messages import Message
from paxoslease.monte_carlo import acquire_on
from paxoslease.simulator import Simulator
from paxoslease.timing import ClockRateBounds, TimingParameters, safe_timing_parameters
from paxoslease.trace import TraceRecorder


def test_safe_quarantine_boundary_is_allowed() -> None:
    Simulator(proposer_duration=4, acceptor_duration=4, quarantine=4)


def test_insufficient_quarantine_rejected_by_default() -> None:
    with pytest.raises(ValueError, match="unsafe quarantine"):
        Simulator(proposer_duration=4, acceptor_duration=4, quarantine=3)


def test_quarantine_below_acceptor_duration_is_allowed() -> None:
    # The quarantine bound tracks the proposer attempt duration, not the
    # acceptor exclusion duration: Q = D_P < D_A is safe under the
    # prepare-time timer rule (TLC: spec/PaxosLeaseQuarantineEqualsProposer.cfg).
    Simulator(proposer_duration=2, acceptor_duration=4, quarantine=2)


def test_unsafe_counterfactual_constructor_allows_bad_quarantine() -> None:
    Simulator(proposer_duration=4, acceptor_duration=4, quarantine=0, unsafe=True)


def test_release_during_quarantine_is_ignored() -> None:
    sim = Simulator(proposer_duration=4, acceptor_duration=4, quarantine=4)
    acquire_on(sim, "p1")
    ballot = sim.proposers["p1"].active_ballot
    sim.crash_acceptor("a1")
    sim.restart_acceptor("a1")
    # Inject impossible state to verify the chosen semantics: quarantine ignores release too.
    sim.acceptors["a1"].accepted = sim.acceptors["a2"].accepted
    msg = Message("release", "p1", "a1", ballot=ballot)
    sim.acceptors["a1"].on_release(msg, sim.now)
    assert sim.acceptors["a1"].accepted is not None


def test_proposer_restart_never_reuses_ballots() -> None:
    sim = Simulator(proposer_duration=4, acceptor_duration=4, quarantine=4)
    sim.start_acquire("p1")
    first = sim.proposers["p1"].ballot
    sim.crash_proposer("p1")
    sim.restart_proposer("p1")
    sim.start_acquire("p1")
    second = sim.proposers["p1"].ballot
    assert second != first


def test_restart_guarantees_uniqueness_not_ordering() -> None:
    # The restart component makes ballots unique across a crash, but it does
    # not order them: the attempt counter restarts from zero under a higher
    # restart component, so a post-restart ballot can be lower than a
    # pre-crash one.  That is safe (acceptors reject the low ballot) but it
    # stalls the proposer, which is why liveness needs the catch-up rule of
    # raising the counter above observed ballots.
    from paxoslease.model import Proposer

    p = Proposer(id="p1", proposer_duration=4, acceptor_ids=("a1", "a2"))
    p.next_ballot()
    before_crash = p.next_ballot()
    p.restart()
    after_restart = p.next_ballot()
    assert after_restart != before_crash
    assert after_restart < before_crash  # unique, not greater


def test_timing_derivation_validates_clock_rate_bounds() -> None:
    bounds = ClockRateBounds(r_min=0.99, r_max=1.01)
    params = safe_timing_parameters(1000, bounds, operation_margin=10)
    params.validate()
    assert params.acceptor_duration >= 1031
    assert params.quarantine_duration >= params.proposer_duration


def test_invalid_timer_containment_is_rejected() -> None:
    with pytest.raises(ValueError, match="timer containment"):
        TimingParameters(5, 4, 5).validate()


def test_fenced_resource_rejects_stale_operation() -> None:
    old = (1, 1, "p1")
    new = (2, 1, "p2")
    unfenced = UnfencedResource()
    assert unfenced.apply(new, "new")
    assert unfenced.apply(old, "old-delayed")

    fenced = FencedResource()
    assert fenced.apply(new, "new")
    assert not fenced.apply(old, "old-delayed")


def test_structured_counterexamples_are_reproducible() -> None:
    results = [fn() for fn in COUNTEREXAMPLES]
    assert {r.scenario for r in results} >= {
        "insufficient-quarantine",
        "owner-only-release",
        "duplicate-quorum-counting",
        "ballot-reuse-after-restart",
        "skipped-paxos-recovery",
        "unfenced-external-effect",
    }
    assert all(isinstance(r, CounterexampleResult) for r in results)
    assert all(r.violated_invariant for r in results)
    assert all(r.minimal_fix for r in results)
    allowed = {
        "simulator-execution",
        "composed-model-execution",
        "illustrative-example",
        "unit-rule",
    }
    assert all(r.category in allowed for r in results)
    # The strongest Python witnesses are real protocol executions.
    executions = {r.scenario for r in results if r.category.endswith("execution")}
    assert {"insufficient-quarantine", "late-promise-reuse", "skipped-paxos-recovery", "release-after-stale-accept", "renewal-over-overwritten-grant"} <= executions


def _late_promise_schedule(sim: Simulator) -> None:
    """The adversarial schedule behind the late-promise-reuse counterexample."""
    sim.start_acquire("p1")
    sim.start_acquire("p2")
    for pid in ("p1", "p2"):
        for aid in ("a1", "a2"):
            sim.deliver_kind("prepare", dst=aid, src=pid)
    for aid in ("a1", "a2"):
        sim.crash_acceptor(aid)
        sim.restart_acceptor(aid)
    sim.tick(4)
    for pid in ("p1", "p2"):
        for aid in ("a1", "a2"):
            sim.deliver_kind("promise", dst=pid, src=aid)


def test_prepare_time_rule_blocks_late_promise_schedule() -> None:
    # Under the prepare-time timer rule, the stale promise quorums arrive
    # after both pending deadlines expired: no Accept is ever sent and
    # nobody activates.  The identical schedule violates exclusivity when
    # timer_at_quorum=True (see counterexamples.late_promise_reuse).
    sim = Simulator(proposer_duration=4, acceptor_duration=4, quarantine=4)
    _late_promise_schedule(sim)
    from paxoslease.messages import MessageKind

    assert not any(msg.kind == MessageKind.ACCEPT for msg in sim.queue)
    assert sim.active_owners() == set()


def test_renewal_qualifier_blocks_stale_owner_open_schedule() -> None:
    # P2's renewal qualifier: an own reported lease counts as open only
    # while the proposer is active.  Under the fixed rule, p2's fresh
    # attempt sees the stale record its abandoned attempt installed and is
    # blocked by it like any foreign lease: no promise counts, no Accept
    # is sent, and p1 remains the only owner.  The identical schedule
    # violates exclusivity when self_open_when_inactive=True (see
    # counterexamples.stale_owner_open).
    from paxoslease.counterexamples import _stale_owner_open_schedule
    from paxoslease.messages import MessageKind

    sim = Simulator(
        acceptor_ids=("a1", "a2"),
        proposer_duration=2,
        acceptor_duration=2,
        quarantine=2,
        refuse_live_overwrite=False,  # the qualifier alone
    )
    _stale_owner_open_schedule(sim)
    assert not any(
        msg.kind == MessageKind.ACCEPT and msg.src == "p2" for msg in sim.queue
    )
    assert sim.active_owners() == {"p1"}


def test_acceptor_refusal_blocks_stale_owner_schedule_without_p2_qualifier() -> None:
    # The acceptor-side repair alone: even with the UNQUALIFIED own-lease
    # rule (self_open_when_inactive=True), an acceptor that refuses to
    # overwrite a live lease of a different owner never records the
    # abandoned attempt's stale lease, so the retrying proposer sees the
    # competitor's live lease and is blocked by it.
    from paxoslease.counterexamples import _stale_owner_open_schedule
    from paxoslease.messages import MessageKind

    sim = Simulator(
        acceptor_ids=("a1", "a2"),
        proposer_duration=2,
        acceptor_duration=2,
        quarantine=2,
        self_open_when_inactive=True,
        refuse_live_overwrite=True,
    )
    _stale_owner_open_schedule(sim)
    while sim.queue:
        sim.deliver(0)
    assert sim.active_owners() == {"p1"}
    assert not any(
        msg.kind == MessageKind.ACCEPT and msg.src == "p2" for msg in sim.queue
    )


def test_acceptor_refusal_blocks_release_after_stale_accept() -> None:
    # The same schedule that gives two owners under the unmodified rules
    # (counterexamples.release_after_stale_accept) is blocked by the
    # acceptor-side rule: a3 refuses to replace p1's live lease with the
    # stale p2 instance, so the stale release matches nothing, a3 reports
    # p1's live lease to p2's fresh prepare, and p2 never sends an accept.
    from paxoslease.counterexamples import _release_after_stale_accept_schedule
    from paxoslease.messages import MessageKind

    sim = Simulator(
        proposer_duration=1,
        acceptor_duration=1,
        quarantine=1,
        refuse_live_overwrite=True,
    )
    fresh = _release_after_stale_accept_schedule(sim)
    assert sim.acceptors["a3"].accepted is not None
    assert sim.acceptors["a3"].accepted.owner == "p1"
    assert not any(
        msg.kind == MessageKind.ACCEPT and msg.src == "p2" and msg.ballot == fresh
        for msg in sim.queue
    )
    while sim.queue:
        sim.deliver(0)
    assert sim.active_owners() == {"p1"}


def test_acceptor_refusal_blocks_renewal_over_overwritten_grant() -> None:
    # With A2's acceptor-side rule (the default), a1 refuses p2's Accept
    # while it holds p1's live lease, so p2 never completes its acquisition
    # and has nothing to renew.
    from paxoslease.counterexamples import _renewal_over_overwritten_grant_schedule

    sim = Simulator(proposer_duration=100, acceptor_duration=100, quarantine=100)
    _renewal_over_overwritten_grant_schedule(sim)
    assert sim.acceptors["a1"].accepted is not None
    assert sim.acceptors["a1"].accepted.owner == "p1"
    assert "p2" not in sim.active_owners()


def test_renewal_qualifier_requires_base_still_held() -> None:
    # P2 counts a report of the renewal base as open only while the base is
    # still held.  Here the base expires while the renewal is in flight, a
    # stale Accept reinstalls it at z over p1's live lease (overwriting A2),
    # and z reports it; the expired base must not count.
    from paxoslease.counterexamples import _deliver_exact as dl
    from paxoslease.messages import MessageKind

    sim = Simulator(
        proposer_ids=("A", "B"),
        acceptor_ids=("x", "y", "z"),
        proposer_duration=10,
        acceptor_duration=10,
        quarantine=10,
        refuse_live_overwrite=False,
    )
    for _ in range(9):
        sim.proposers["B"].next_ballot()
    sim.start_acquire("B")
    base = sim.proposers["B"].ballot
    for a in "xy":
        dl(sim, "prepare", a, "B", base)
    for a in "xy":
        dl(sim, "promise", "B", a, base)
    for a in "xy":
        dl(sim, "accept", a, "B", base)
    for a in "xy":
        dl(sim, "accepted", "B", a, base)
    for a in "xy":
        sim.crash_acceptor(a)
        sim.restart_acceptor(a)
    sim.tick(9)
    sim.start_acquire("B")
    renewal = sim.proposers["B"].ballot
    sim.tick(1)  # the base expires with the renewal in flight
    sim.start_acquire("A")
    low = sim.proposers["A"].ballot
    for a in "yz":
        dl(sim, "prepare", a, "A", low)
    for a in "yz":
        dl(sim, "promise", "A", a, low)
    for a in "yz":
        dl(sim, "accept", a, "A", low)
    for a in "yz":
        dl(sim, "accepted", "A", a, low)
    sim.tick(1)
    dl(sim, "accept", "z", "B", base)  # stale Accept reinstalls the base at z
    for a in "xz":
        dl(sim, "prepare", a, "B", renewal)
    for a in "xz":
        dl(sim, "promise", "B", a, renewal)
    assert not any(
        msg.kind == MessageKind.ACCEPT and msg.src == "B" and msg.ballot == renewal
        for msg in sim.queue
    )
    assert sim.active_owners() == {"A"}


def test_trace_records_mapped_actions_and_invariant_status() -> None:
    trace = TraceRecorder()
    sim = Simulator(proposer_duration=4, acceptor_duration=4, quarantine=4, trace=trace)
    sim.start_acquire("p1")
    while sim.queue:
        sim.deliver(0)
    assert "p1" in sim.active_owners()
    assert trace.events
    assert all(event.invariant_ok for event in trace.events)
    assert {event.event for event in trace.events} >= {"StartAcquire", "DeliverPrepare"}


def test_incarnation_owner_blocks_release_across_proposer_restart() -> None:
    # The schedule of counterexamples.release_across_proposer_restart, with
    # A2 comparing owners as proposer incarnations: the previous
    # incarnation's stale accept is refused at a3, its stale release matches
    # nothing, and p2's prepare finds p1's live lease, so p2 never sends an
    # accept request.
    import pytest

    from paxoslease.counterexamples import _release_across_proposer_restart_schedule
    from paxoslease.simulator import Simulator

    sim = Simulator(proposer_duration=2, acceptor_duration=2, quarantine=2)
    with pytest.raises(AssertionError, match="no queued accept"):
        _release_across_proposer_restart_schedule(sim)
    assert sim.active_owners() == {"p1"}
