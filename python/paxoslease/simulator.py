from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .messages import Message, MessageKind
from .model import Acceptor, Proposer, quorum_size
from .timing import TimingParameters
from .trace import TraceEvent, TraceRecorder


@dataclass
class Simulator:
    proposer_ids: tuple[str, ...] = ("p1", "p2")
    acceptor_ids: tuple[str, ...] = ("a1", "a2", "a3")
    proposer_duration: int = 3
    acceptor_duration: int = 3
    quarantine: int = 3
    now: int = 0
    queue: list[Message] = field(default_factory=list)
    unsafe: bool = False
    timer_at_quorum: bool = False
    self_open_when_inactive: bool = False
    refuse_live_overwrite: bool = True
    incarnation_owner: bool = True
    trace: TraceRecorder | None = None

    def __post_init__(self) -> None:
        if len(set(self.proposer_ids)) != len(self.proposer_ids):
            raise ValueError("proposer ids must be distinct")
        if len(set(self.acceptor_ids)) != len(self.acceptor_ids):
            raise ValueError("acceptor ids must be distinct")
        if self.proposer_duration <= 0 or self.acceptor_duration <= 0:
            raise ValueError("durations must be positive")
        if self.quarantine < 0:
            raise ValueError("quarantine must be non-negative")
        if not self.unsafe:
            TimingParameters(
                self.proposer_duration,
                self.acceptor_duration,
                self.quarantine,
            ).validate()
        self._next_message_id = 1
        self._step = 0
        self.acceptors = {
            aid: Acceptor(
                aid,
                self.acceptor_duration,
                refuse_live_overwrite=self.refuse_live_overwrite,
                incarnation_owner=self.incarnation_owner,
            )
            for aid in self.acceptor_ids
        }
        self.proposers = {
            pid: Proposer(
                pid,
                self.proposer_duration,
                self.acceptor_ids,
                timer_at_quorum=self.timer_at_quorum,
                self_open_when_inactive=self.self_open_when_inactive,
            )
            for pid in self.proposer_ids
        }

    @property
    def quorum(self) -> int:
        return quorum_size(len(self.acceptor_ids))

    def snapshot(self) -> dict[str, Any]:
        return {
            "now": self.now,
            "queue": [
                {
                    "id": msg.id,
                    "kind": str(msg.kind),
                    "src": msg.src,
                    "dst": msg.dst,
                    "ballot": msg.ballot,
                }
                for msg in self.queue
            ],
            "proposers": {
                pid: {
                    "phase": p.phase,
                    "active": p.active,
                    "deadline": p.deadline,
                    "ballot": p.ballot,
                    "active_ballot": p.active_ballot,
                    "certificate": sorted(p.certificate),
                    "crashed": p.crashed,
                }
                for pid, p in self.proposers.items()
            },
            "acceptors": {
                aid: {
                    "promised": a.promised,
                    "accepted": None if a.accepted is None else {
                        "owner": a.accepted.owner,
                        "ballot": a.accepted.ballot,
                        "deadline": a.accepted.deadline,
                    },
                    "crashed": a.crashed,
                    "quarantine_until": a.quarantine_until,
                }
                for aid, a in self.acceptors.items()
            },
        }

    def _record(self, event: str, params: dict[str, Any], before: dict[str, Any]) -> None:
        if self.trace is None:
            return
        violation = None
        ok = True
        try:
            self.check_safety()
        except AssertionError as exc:  # pragma: no cover - recorded counterexample path
            ok = False
            violation = str(exc)
        self.trace.append(
            TraceEvent(
                step=self._step,
                time=self.now,
                event=event,
                parameters=params,
                before=before,
                after=self.snapshot(),
                invariant_ok=ok,
                violation=violation,
            )
        )

    def send(self, messages: list[Message]) -> None:
        assigned = []
        for msg in messages:
            if msg.id == 0:
                msg = replace(msg, id=self._next_message_id)
                self._next_message_id += 1
            assigned.append(msg)
        self.queue.extend(assigned)

    def start_acquire(self, proposer: str) -> None:
        before = self.snapshot()
        self.send(self.proposers[proposer].start_acquire(self.now))
        self._step += 1
        self.check_safety()
        self._record("StartAcquire", {"proposer": proposer}, before)

    def abandon(self, proposer: str) -> None:
        before = self.snapshot()
        self.proposers[proposer].abandon()
        self._step += 1
        self.check_safety()
        self._record("AbandonAttempt", {"proposer": proposer}, before)

    def release(self, proposer: str) -> None:
        before = self.snapshot()
        self.send(self.proposers[proposer].release())
        self._step += 1
        self.check_safety()
        self._record("Release", {"proposer": proposer}, before)

    def deliver_by_id(self, message_id: int) -> None:
        for index, msg in enumerate(self.queue):
            if msg.id == message_id:
                self.deliver(index)
                return
        raise AssertionError(f"no queued message id={message_id}")

    def deliver(self, index: int = 0) -> None:
        before = self.snapshot()
        msg = self.queue.pop(index)
        if msg.kind == MessageKind.PREPARE:
            response = self.acceptors[msg.dst].on_prepare(msg, self.now)
            if response is not None:
                self.send([response])
        elif msg.kind == MessageKind.PROMISE:
            self.send(self.proposers[msg.dst].on_promise(msg, self.now))
        elif msg.kind == MessageKind.ACCEPT:
            response = self.acceptors[msg.dst].on_accept(msg, self.now)
            if response is not None:
                self.send([response])
        elif msg.kind == MessageKind.ACCEPTED:
            self.proposers[msg.dst].on_accepted(msg, self.now)
        elif msg.kind == MessageKind.RELEASE:
            self.acceptors[msg.dst].on_release(msg, self.now)
        else:  # pragma: no cover
            raise ValueError(f"unknown message kind {msg.kind!r}")
        self._step += 1
        self.check_safety()
        self._record("Deliver" + MessageKind(msg.kind).value.title().replace("_", ""), {"message_id": msg.id}, before)

    def deliver_kind(self, kind: str, dst: str | None = None, src: str | None = None) -> None:
        target = MessageKind(kind)
        for i, msg in enumerate(self.queue):
            if msg.kind == target and (dst is None or msg.dst == dst) and (src is None or msg.src == src):
                self.deliver(i)
                return
        raise AssertionError(f"no queued message kind={kind} dst={dst} src={src}")

    def drop(self, index: int = 0) -> None:
        before = self.snapshot()
        msg = self.queue.pop(index)
        self._step += 1
        self.check_safety()
        self._record("DropMessage", {"message_id": msg.id}, before)

    def duplicate(self, index: int = 0) -> None:
        before = self.snapshot()
        original = self.queue[index]
        self.send([replace(original, id=0)])
        self._step += 1
        self.check_safety()
        self._record("DuplicateMessage", {"message_id": original.id}, before)

    def tick(self, steps: int = 1) -> None:
        if steps < 0:
            raise ValueError("steps must be non-negative")
        before = self.snapshot()
        for _ in range(steps):
            self.now += 1
            for proposer in self.proposers.values():
                proposer.tick(self.now)
            self.check_safety()
        self._step += 1
        self._record("Tick", {"steps": steps}, before)

    def crash_acceptor(self, acceptor: str) -> None:
        before = self.snapshot()
        self.acceptors[acceptor].crash()
        self._step += 1
        self.check_safety()
        self._record("CrashAcceptor", {"acceptor": acceptor}, before)

    def restart_acceptor(self, acceptor: str) -> None:
        before = self.snapshot()
        if self.acceptors[acceptor].crashed:
            self.acceptors[acceptor].restart(self.now, self.quarantine)
        self._step += 1
        self.check_safety()
        self._record("RestartAcceptor", {"acceptor": acceptor}, before)

    def crash_proposer(self, proposer: str) -> None:
        before = self.snapshot()
        self.proposers[proposer].crash()
        self._step += 1
        self.check_safety()
        self._record("CrashProposer", {"proposer": proposer}, before)

    def restart_proposer(self, proposer: str) -> None:
        before = self.snapshot()
        self.proposers[proposer].restart()
        self._step += 1
        self.check_safety()
        self._record("RestartProposer", {"proposer": proposer}, before)

    def active_owners(self) -> set[str]:
        return {pid for pid, proposer in self.proposers.items() if proposer.active}

    def check_safety(self) -> None:
        active = self.active_owners()
        assert len(active) <= 1, f"lease exclusivity violated: {active}"
        for pid in active:
            proposer = self.proposers[pid]
            assert self.now < proposer.deadline
            assert len(proposer.certificate) >= self.quorum
            assert set(proposer.certificate) <= set(self.acceptor_ids)
            for aid, entry in proposer.certificate.items():
                assert entry.acceptor == aid
                assert entry.owner == pid
                assert entry.ballot == proposer.active_ballot
                assert proposer.deadline <= entry.deadline
        for acceptor in self.acceptors.values():
            if self.now < acceptor.quarantine_until:
                assert acceptor.promised is None
                assert acceptor.accepted is None
