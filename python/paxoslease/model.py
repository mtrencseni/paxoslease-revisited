from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .messages import Ballot, Lease, Message, MessageKind


def quorum_size(n: int) -> int:
    if n <= 0:
        raise ValueError("quorum requires at least one acceptor")
    return n // 2 + 1


@dataclass(frozen=True)
class CertificateEntry:
    acceptor: str
    owner: str
    ballot: Ballot
    deadline: int


@dataclass
class Acceptor:
    id: str
    acceptor_duration: int
    promised: Optional[Ballot] = None
    accepted: Optional[Lease] = None
    crashed: bool = False
    quarantine_until: int = 0
    # A2's acceptor-side rule: refuse to replace a live accepted lease of a
    # different owner, even under a higher ballot.  Required: without it,
    # renewals and a single acceptor restart give two owners even with the
    # renewal qualifier (counterexamples.renewal_over_overwritten_grant),
    # and exact-instance release is unsafe (release_after_stale_accept).
    # False reproduces the rule of the 2012 paper and of both audited
    # implementations, which overwrite; it is kept for the counterexamples.
    refuse_live_overwrite: bool = True
    # The owner A2 compares is the proposer INCARNATION, (node, restart),
    # read from the ballot's restart component.  A restarted proposer's
    # ballots may be lower than its previous incarnation's, so comparing by
    # node alone lets a delayed accept of the previous incarnation replace
    # the new one's live lease (counterexamples.release_across_proposer_restart).
    # False is kept for that counterexample.
    incarnation_owner: bool = True

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("acceptor id must be non-empty")
        if self.acceptor_duration <= 0:
            raise ValueError("acceptor duration must be positive")

    def can_participate(self, now: int) -> bool:
        return not self.crashed and now >= self.quarantine_until

    def current_lease(self, now: int) -> Optional[Lease]:
        if self.accepted is not None and now < self.accepted.deadline:
            return self.accepted
        return None

    def on_prepare(self, msg: Message, now: int) -> Optional[Message]:
        if msg.ballot is None or not self.can_participate(now):
            return None
        if self.promised is not None and msg.ballot < self.promised:
            return None
        self.promised = msg.ballot
        return Message(MessageKind.PROMISE, self.id, msg.src, ballot=msg.ballot, lease=self.current_lease(now))

    def on_accept(self, msg: Message, now: int) -> Optional[Message]:
        if msg.ballot is None or msg.lease is None or not self.can_participate(now):
            return None
        if self.promised is not None and msg.ballot < self.promised:
            return None
        if self.refuse_live_overwrite:
            live = self.current_lease(now)
            if live is not None and not self._same_owner(live, msg):
                return None  # treated exactly like a ballot rejection
        self.promised = msg.ballot
        self.accepted = Lease(msg.lease.owner, msg.ballot, now + self.acceptor_duration)
        return Message(MessageKind.ACCEPTED, self.id, msg.src, ballot=msg.ballot, lease=self.accepted)

    def _same_owner(self, live: Lease, msg: Message) -> bool:
        assert msg.lease is not None and msg.ballot is not None
        if live.owner != msg.lease.owner:
            return False
        return not self.incarnation_owner or live.ballot[1] == msg.ballot[1]

    def on_release(self, msg: Message, now: int) -> None:
        if msg.ballot is None or not self.can_participate(now):
            return
        if self.accepted is not None and self.accepted.owner == msg.src and self.accepted.ballot == msg.ballot:
            self.accepted = None

    def crash(self) -> None:
        self.crashed = True
        self.promised = None
        self.accepted = None

    def restart(self, now: int, quarantine: int) -> None:
        if quarantine < 0:
            raise ValueError("quarantine must be non-negative")
        self.crashed = False
        self.quarantine_until = now + quarantine


@dataclass
class Proposer:
    id: str
    proposer_duration: int
    acceptor_ids: tuple[str, ...]
    counter: int = 0
    restart_count: int = 1
    ballot: Optional[Ballot] = None
    phase: str = "idle"
    promises: dict[str, Optional[Lease]] = field(default_factory=dict)
    ok_promises: set[str] = field(default_factory=set)
    accepted_from: set[str] = field(default_factory=set)
    accepted_deadlines: dict[str, int] = field(default_factory=dict)
    pending_deadline: int = 0
    active: bool = False
    deadline: int = 0
    active_ballot: Optional[Ballot] = None
    # P2's renewal provenance, captured when the attempt begins (P1): the
    # ballot of the lease this attempt renews, or None for a fresh
    # acquisition.  Stored state, not inferred at response delivery, so a
    # fresh attempt cannot be reclassified as a renewal by ownership
    # changing while responses arrive.
    renewal_base: Optional[Ballot] = None
    certificate: dict[str, CertificateEntry] = field(default_factory=dict)
    crashed: bool = False
    # The original 2012 paper's step-3 rule: the timer starts only on receipt
    # of a prepare quorum, so nothing bounds how stale that quorum is.
    # Unsafe under acceptor crash and restart; kept only for the
    # late-promise-reuse counterexample.
    timer_at_quorum: bool = False
    # The unqualified own-lease-open rule: a reported lease owned by this
    # proposer counts as open even when the proposer is not active (not
    # renewing).  This is how both audited implementations behave
    # (StartProposing proceeds whenever the discovered owner is the node
    # itself).  Unsafe with retry: kept only for the stale-owner-open
    # counterexample.
    self_open_when_inactive: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("proposer id must be non-empty")
        if self.proposer_duration <= 0:
            raise ValueError("proposer duration must be positive")
        if len(set(self.acceptor_ids)) != len(self.acceptor_ids):
            raise ValueError("acceptor ids must be distinct")

    @property
    def quorum(self) -> int:
        return quorum_size(len(self.acceptor_ids))

    def tick(self, now: int) -> None:
        if self.active and now >= self.deadline:
            self.active = False

    def next_ballot(self) -> Ballot:
        self.counter += 1
        return (self.counter, self.restart_count, self.id)

    def start_acquire(self, now: int) -> list[Message]:
        if self.crashed or self.phase != "idle":
            return []
        self.ballot = self.next_ballot()
        # P1 captures the attempt's provenance: a renewal renews exactly
        # the lease that is active now, at the start of the attempt.
        self.renewal_base = self.active_ballot if self.active else None
        self.phase = "preparing"
        if not self.timer_at_quorum:
            self.pending_deadline = now + self.proposer_duration
        self.promises.clear()
        self.ok_promises.clear()
        self.accepted_from.clear()
        return [Message(MessageKind.PREPARE, self.id, aid, ballot=self.ballot) for aid in self.acceptor_ids]

    def on_promise(self, msg: Message, now: int) -> list[Message]:
        if self.crashed or self.phase != "preparing" or msg.ballot != self.ballot:
            return []
        self.promises[msg.src] = msg.lease
        # P2: an own lease counts as open only for a renewal attempt, and
        # only if the reported instance is that exact lease captured as this
        # attempt's renewal base at P1.  A self-owned record under any
        # other ballot is an artifact of an abandoned attempt and must
        # block like a foreign lease.
        # The base must also still be held when the response is processed,
        # as the TLA+ DeliverPromise checks: a base that expired while the
        # renewal was in flight no longer protects anything.
        renewing_this = (
            self.renewal_base is not None
            and msg.lease is not None
            and msg.lease.ballot == self.renewal_base
            and self.active
            and self.active_ballot == self.renewal_base
        )
        if msg.lease is None or (
            msg.lease.owner == self.id and (renewing_this or self.self_open_when_inactive)
        ):
            self.ok_promises.add(msg.src)
        if len(self.ok_promises) < self.quorum:
            return []
        if self.timer_at_quorum:
            self.pending_deadline = now + self.proposer_duration
        elif now >= self.pending_deadline:
            return []
        self.phase = "accepting"
        assert self.ballot is not None  # set by start_acquire before phase leaves "idle"
        lease = Lease(self.id, self.ballot, 0)
        return [Message(MessageKind.ACCEPT, self.id, aid, ballot=self.ballot, lease=lease) for aid in self.acceptor_ids]

    def on_accepted(self, msg: Message, now: int) -> None:
        if self.crashed or self.phase != "accepting" or msg.ballot != self.ballot or msg.lease is None:
            return
        if msg.lease.owner != self.id or msg.lease.ballot != self.ballot:
            return
        self.accepted_from.add(msg.src)
        self.accepted_deadlines[msg.src] = msg.lease.deadline
        if len(self.accepted_from) >= self.quorum:
            self.phase = "idle"
            if now < self.pending_deadline:
                self.active = True
                self.deadline = self.pending_deadline
                self.active_ballot = self.ballot
                self.certificate = {
                    aid: CertificateEntry(aid, self.id, self.ballot, self.accepted_deadlines[aid])
                    for aid in self.accepted_from
                }

    def abandon(self) -> None:
        # P5: give up a non-idle attempt, staying alive and keeping any
        # active lease; a later start_acquire retries with a higher ballot,
        # and the ballot checks discard the abandoned attempt's responses.
        if self.crashed or self.phase == "idle":
            return
        self.phase = "idle"

    def release(self) -> list[Message]:
        if self.crashed or not self.active or self.active_ballot is None:
            return []
        ballot = self.active_ballot
        self.active = False
        self.phase = "idle"
        return [Message(MessageKind.RELEASE, self.id, aid, ballot=ballot) for aid in self.acceptor_ids]

    def crash(self) -> None:
        self.crashed = True
        self.active = False
        self.phase = "idle"
        self.renewal_base = None

    def restart(self) -> None:
        self.crashed = False
        self.phase = "idle"
        self.restart_count += 1
        self.counter = 0
