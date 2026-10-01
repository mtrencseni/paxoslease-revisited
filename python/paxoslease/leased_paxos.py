from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .messages import Ballot
from .model import quorum_size
from .simulator import Simulator


@dataclass
class PaxosAcceptor:
    """Durable Paxos acceptor state used below the volatile lease layer."""

    id: str
    promised: Optional[Ballot] = None
    accepted: dict[int, tuple[Ballot, str]] = field(default_factory=dict)

    def prepare(self, ballot: Ballot) -> Optional[dict[int, tuple[Ballot, str]]]:
        if self.promised is not None and ballot < self.promised:
            return None
        self.promised = ballot
        return dict(self.accepted)

    def accept(self, ballot: Ballot, slot: int, value: str) -> bool:
        if self.promised is not None and ballot < self.promised:
            return False
        self.promised = ballot
        self.accepted[slot] = (ballot, value)
        return True


@dataclass
class LeasedPaxosCluster:
    """Small deterministic Multi-Paxos composition guarded by PaxosLease.

    The lease layer decides which process may attempt leadership. Durable Paxos
    acceptor state decides which log values are safe to choose. A node becomes
    client-ready only while it holds a live lease and after completing this
    leadership epoch's Paxos Phase 1 and every repair round it reported.
    """

    proposer_ids: tuple[str, ...] = ("p1", "p2")
    lease_acceptor_ids: tuple[str, ...] = ("la1", "la2", "la3")
    paxos_acceptor_ids: tuple[str, ...] = ("pa1", "pa2", "pa3")
    max_slots: int = 4
    proposer_duration: int = 4
    acceptor_duration: int = 4
    quarantine: int = 4

    def __post_init__(self) -> None:
        self.lease = Simulator(
            proposer_ids=self.proposer_ids,
            acceptor_ids=self.lease_acceptor_ids,
            proposer_duration=self.proposer_duration,
            acceptor_duration=self.acceptor_duration,
            quarantine=self.quarantine,
        )
        self.acceptors = {aid: PaxosAcceptor(aid) for aid in self.paxos_acceptor_ids}
        self.state = {pid: "not-elected" for pid in self.proposer_ids}
        self.recovered: dict[str, dict[int, str]] = {pid: {} for pid in self.proposer_ids}
        self.ballot_counter = {pid: 0 for pid in self.proposer_ids}
        self.leader_ballot: dict[str, Ballot] = {}
        self.admissions: list[tuple[int, str, int, str]] = []
        self.check_safety()

    @property
    def now(self) -> int:
        return self.lease.now

    @property
    def quorum(self) -> int:
        return quorum_size(len(self.paxos_acceptor_ids))

    def _next_ballot(self, proposer: str) -> Ballot:
        # (counter, restart, node); this harness does not model proposer
        # restarts, so the restart component is a constant 0.
        self.ballot_counter[proposer] += 1
        return (self.ballot_counter[proposer], 0, proposer)

    def lease_active(self, proposer: str) -> bool:
        return proposer in self.lease.active_owners()

    def acquire_lease(self, proposer: str) -> bool:
        # A successful renewal keeps ownership continuous, so the leadership
        # epoch, its recovery and its reserved ballot carry over (M1).
        renewing = self.lease_active(proposer)
        self.lease.start_acquire(proposer)
        while self.lease.queue:
            self.lease.deliver(0)
        if self.lease_active(proposer):
            if not renewing:
                self.state[proposer] = "elected"
            self.check_safety()
            return True
        self.check_safety()
        return False

    def tick(self, steps: int = 1) -> None:
        self.lease.tick(steps)
        for proposer in self.proposer_ids:
            if not self.lease_active(proposer):
                self.state[proposer] = "not-elected"
        self.check_safety()

    def recover_and_become_ready(self, proposer: str) -> None:
        """Phase 1 reserves the ballot and discovers the values that
        constrain recovery; repair then re-proposes every forced value so
        the recovered prefix is complete BEFORE any client command is
        admitted.  Phase 1 alone is not cleanup: a forced value that is
        merely discovered, not re-proposed, would otherwise be finished by
        the next client append, which would then silently replace the
        client's command."""
        if not self.lease_active(proposer):
            raise RuntimeError("leader recovery requires an active lease")
        self.state[proposer] = "recovering"
        ballot = self._next_ballot(proposer)
        replies = []
        for acceptor in self.acceptors.values():
            reply = acceptor.prepare(ballot)
            if reply is not None:
                replies.append(reply)
        if len(replies) < self.quorum:
            self.state[proposer] = "elected"
            raise RuntimeError("Paxos Phase 1 failed to reach quorum")

        recovered: dict[int, str] = {}
        for slot in range(1, self.max_slots + 1):
            accepted = [reply[slot] for reply in replies if slot in reply]
            if accepted:
                _ballot, value = max(accepted, key=lambda item: item[0])
                recovered[slot] = value
        # Repair: complete every forced slot with a Phase 2 round under the
        # reserved ballot.
        for slot, value in sorted(recovered.items()):
            acks = [a.accept(ballot, slot, value) for a in self.acceptors.values()]
            if sum(acks) < self.quorum:
                self.state[proposer] = "elected"
                raise RuntimeError("Paxos repair failed to reach quorum")
        self.recovered[proposer] = recovered
        self.leader_ballot[proposer] = ballot
        self.state[proposer] = "ready"
        self.check_safety()

    def _first_open_slot(self, proposer: str) -> int:
        chosen = self.chosen_log()
        for slot in range(1, self.max_slots + 1):
            if slot not in chosen:
                return slot
        raise RuntimeError("log is full")

    def append(self, proposer: str, value: str) -> tuple[int, str]:
        """Fast-mode client admission: one Phase 2 round under the ballot
        reserved at recovery, into a genuinely new slot.  Repair has
        already completed every forced slot, so the client's command is
        appended as given, never replaced by a recovered value."""
        if not self.lease_active(proposer) or self.state[proposer] != "ready":
            raise RuntimeError("client admission requires an active ready lease holder")
        slot = self._first_open_slot(proposer)
        if slot in self.recovered[proposer]:
            raise RuntimeError("repair left a forced slot open; admission refused")
        ballot = self.leader_ballot[proposer]
        acks = [a.accept(ballot, slot, value) for a in self.acceptors.values()]
        if sum(acks) < self.quorum:
            raise RuntimeError("Paxos Phase 2 failed to reach quorum")
        self.admissions.append((self.now, proposer, slot, value))
        self.check_safety()
        return slot, value

    def accept_without_leader_learning(
        self,
        proposer: str,
        slot: int,
        value: str,
        acceptor_ids: tuple[str, ...],
    ) -> None:
        """Model a value accepted by acceptors before the leader records the result."""

        if not self.lease_active(proposer) or self.state[proposer] != "ready":
            raise RuntimeError("partial Paxos accepts require an active ready leader")
        ballot = self.leader_ballot[proposer]
        for aid in acceptor_ids:
            if not self.acceptors[aid].accept(ballot, slot, value):
                raise RuntimeError(f"acceptor {aid} rejected ballot {ballot}")
        self.check_safety()

    def chosen_log(self) -> dict[int, str]:
        chosen: dict[int, str] = {}
        for slot in range(1, self.max_slots + 1):
            counts = Counter(
                value
                for acceptor in self.acceptors.values()
                for accepted_slot, (_ballot, value) in acceptor.accepted.items()
                if accepted_slot == slot
            )
            quorum_values = [value for value, count in counts.items() if count >= self.quorum]
            if quorum_values:
                # check_safety separately rejects more than one quorum value.
                chosen[slot] = quorum_values[0]
        return chosen

    def check_safety(self) -> None:
        self.lease.check_safety()
        ready = {p for p, s in self.state.items() if s == "ready"}
        active = self.lease.active_owners()
        assert ready <= active, f"ready without lease: ready={ready} active={active}"
        assert len(ready) <= 1, f"multiple ready leaders: {ready}"

        by_slot: dict[int, Counter[str]] = defaultdict(Counter)
        for acceptor in self.acceptors.values():
            for slot, (_ballot, value) in acceptor.accepted.items():
                by_slot[slot][value] += 1
        for slot, counts in by_slot.items():
            quorum_values = [value for value, count in counts.items() if count >= self.quorum]
            assert len(quorum_values) <= 1, (
                f"Paxos agreement violated at slot {slot}: {quorum_values}"
            )

        chosen = self.chosen_log()
        for _time, proposer, slot, value in self.admissions:
            assert slot in chosen and chosen[slot] == value
            assert proposer in self.proposer_ids
