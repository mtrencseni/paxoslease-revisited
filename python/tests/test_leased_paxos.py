from __future__ import annotations


import pytest
from hypothesis import given, settings, strategies as st

from paxoslease import LeasedPaxosCluster

def make_ready(cluster: LeasedPaxosCluster, proposer: str) -> None:
    assert cluster.acquire_lease(proposer)
    cluster.recover_and_become_ready(proposer)
    assert cluster.state[proposer] == "ready"

def test_client_admission_requires_ready_lease_holder() -> None:
    cluster = LeasedPaxosCluster()
    with pytest.raises(RuntimeError):
        cluster.append("p1", "v1")

    assert cluster.acquire_lease("p1")
    with pytest.raises(RuntimeError):
        cluster.append("p1", "v1")

    cluster.recover_and_become_ready("p1")
    assert cluster.append("p1", "v1") == (1, "v1")
    assert cluster.chosen_log() == {1: "v1"}

def test_renewal_keeps_ready_leader_in_fast_mode() -> None:
    cluster = LeasedPaxosCluster(proposer_duration=3, acceptor_duration=3, quarantine=3)
    make_ready(cluster, "p1")
    assert cluster.append("p1", "v1") == (1, "v1")
    cluster.tick(1)
    assert cluster.acquire_lease("p1")
    assert cluster.state["p1"] == "ready"
    assert cluster.append("p1", "v2") == (2, "v2")

def test_lease_expiry_revokes_ready_leader() -> None:
    cluster = LeasedPaxosCluster(proposer_duration=2, acceptor_duration=2, quarantine=2)
    make_ready(cluster, "p1")
    cluster.tick(2)
    assert cluster.state["p1"] == "not-elected"
    with pytest.raises(RuntimeError):
        cluster.append("p1", "v1")

def test_new_leader_preserves_value_accepted_by_old_quorum() -> None:
    cluster = LeasedPaxosCluster(proposer_duration=3, acceptor_duration=3, quarantine=3)
    make_ready(cluster, "p1")
    cluster.accept_without_leader_learning("p1", 1, "old", ("pa1", "pa2"))
    assert cluster.chosen_log() == {1: "old"}

    cluster.tick(3)
    assert cluster.acquire_lease("p2")
    cluster.recover_and_become_ready("p2")
    assert cluster.append("p2", "new") == (2, "new")
    assert cluster.chosen_log() == {1: "old", 2: "new"}

def test_recovery_repairs_forced_slot_before_client_admission() -> None:
    cluster = LeasedPaxosCluster(proposer_duration=3, acceptor_duration=3, quarantine=3)
    make_ready(cluster, "p1")
    cluster.accept_without_leader_learning("p1", 1, "maybe", ("pa1",))
    assert cluster.chosen_log() == {}

    cluster.tick(3)
    assert cluster.acquire_lease("p2")
    # Repair inside recovery completes the forced slot; the client's
    # command then lands unaltered in a genuinely new slot.
    cluster.recover_and_become_ready("p2")
    assert cluster.chosen_log() == {1: "maybe"}
    assert cluster.append("p2", "client") == (2, "client")
    assert cluster.chosen_log() == {1: "maybe", 2: "client"}

@given(st.lists(st.sampled_from([
    "acquire_p1", "recover_p1", "append_p1", "acquire_p2", "recover_p2",
    "append_p2", "tick", "tick2",
]), min_size=1, max_size=35))
@settings(max_examples=70, deadline=None)
def test_generated_leased_paxos_schedules_preserve_invariants(ops: list[str]) -> None:
    cluster = LeasedPaxosCluster(proposer_duration=3, acceptor_duration=3, quarantine=3)
    for op in ops:
        try:
            if op == "acquire_p1":
                cluster.acquire_lease("p1")
            elif op == "recover_p1":
                cluster.recover_and_become_ready("p1")
            elif op == "append_p1":
                cluster.append("p1", "v1")
            elif op == "acquire_p2":
                cluster.acquire_lease("p2")
            elif op == "recover_p2":
                cluster.recover_and_become_ready("p2")
            elif op == "append_p2":
                cluster.append("p2", "v2")
            elif op == "tick":
                cluster.tick(1)
            elif op == "tick2":
                cluster.tick(2)
        except RuntimeError:
            pass
        cluster.check_safety()
