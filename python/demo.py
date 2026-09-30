#!/usr/bin/env python3
"""PaxosLease in one file, on real timers.

This is the companion program to the paper "PaxosLease Revisited": the
algorithm of Section 4, written to be read in one sitting and run in a few
seconds.  Three nodes live in one asyncio event loop, each hosting the
three roles (proposer, acceptor, learner), and every method names the
paper step it implements: P1..P5 on the proposer, A1/A2/A4 on the
acceptor, L1 on the learner, T1/T2/T3 as the timing rules.

This is correct PaxosLease and nothing else.  Where the paper shows that a
plausible alternative to a rule is unsafe, the comment at that rule says
so and points at the section; the unsafe versions are not implemented
here.  They live as weakened TLA+ variants under tla/counterexamples/,
where a model checker rather than a print statement demonstrates the
two-owner execution.

This program is a demonstration, not evidence.  TLC checks the finite
models, TLAPS proves the timing arithmetic, and the deterministic models
under python/paxoslease/ test specific schedules.  This file exists so that
a reader can watch the protocol behave against real clocks.

Run it:

    python python/demo.py            # an owner emerges, renews, dies, fails over
    python python/demo.py --fast     # the same with short timers (tests)

Note that the scenario crashes acceptor roles while proposer roles
keep running, which is the setting of the paper's base model.  In a
deployment where the roles share a process, a crash restarts both, and the
paper's implementation audit treats that refinement (colocation).
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from dataclasses import dataclass

# ----------------------------------------------------------------------
# Time and identifiers
# ----------------------------------------------------------------------

def now() -> float:
    """The one clock in this program.

    Monotonic, never gettimeofday: lease timers measure elapsed time, and
    a wall clock that steps backward extends authority (unsafe on a
    proposer) while one that steps forward shrinks exclusion (unsafe on
    an acceptor).  See the paper's fifth audit finding.
    """
    return time.monotonic()


# A ballot is (counter, restart, node): counter-major, so ballots grow with
# every attempt; the restart component is a durably stored counter bumped at
# every process start, so no ballot is ever reused across a crash (P1).
Ballot = tuple[int, int, int]

NO_BALLOT: Ballot = (0, 0, 0)


@dataclass(frozen=True)
class Timing:
    """T2 and T3: the two inequalities that make the timers safe."""

    proposer_duration: float   # D_P: how long an attempt's evidence lives (T1)
    acceptor_duration: float   # D_A: how long an acceptor excludes others
    quarantine: float          # Q:   silence after an acceptor restart (T3)

    def check(self) -> None:
        assert self.proposer_duration <= self.acceptor_duration, "T2: containment"
        assert self.quarantine >= self.proposer_duration, "T3: quarantine >= D_P"


# ----------------------------------------------------------------------
# Messages: five kinds, fire-and-forget
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Prepare:
    ballot: Ballot
    src: int


@dataclass(frozen=True)
class Promise:
    ballot: Ballot                      # the ballot being answered
    src: int
    lease_owner: int | None             # the live accepted lease, if any
    lease_ballot: Ballot


@dataclass(frozen=True)
class Rejected:
    ballot: Ballot                      # the ballot being refused
    src: int
    promised: Ballot                    # what to exceed (P1's catch-up aid)


@dataclass(frozen=True)
class Accept:
    ballot: Ballot
    src: int
    owner: int


@dataclass(frozen=True)
class Accepted:
    ballot: Ballot
    src: int


@dataclass(frozen=True)
class LearnChosen:
    owner: int
    deadline: float                     # absolute, on the owner's clock
    src: int


Message = Prepare | Promise | Rejected | Accept | Accepted | LearnChosen


class Network:
    """Delivers each message once, asynchronously.

    Nothing here duplicates, drops or reorders messages.  The protocol
    tolerates all three, and the TLA+ models explore them; a single event
    loop is not the place to demonstrate that.
    """

    def __init__(self) -> None:
        self.nodes: dict[int, "Node"] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    def send(self, dst: int, msg: Message) -> None:
        task = asyncio.get_running_loop().create_task(self._deliver(dst, msg))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _deliver(self, dst: int, msg: Message) -> None:
        self.nodes[dst].handle(msg)


# ----------------------------------------------------------------------
# The safety referee
# ----------------------------------------------------------------------

class Monitor:
    """Receives every learner's "node N owns the lease until t" claim and
    reports any two overlapping claims by different owners.  It may use one
    clock for all nodes because all nodes live in this one process."""

    def __init__(self) -> None:
        self.claims: dict[int, float] = {}      # owner -> deadline
        self.owners_seen: set[int] = set()
        self.violations: list[str] = []

    def claim(self, owner: int, deadline: float) -> None:
        self.owners_seen.add(owner)
        self.claims[owner] = max(self.claims.get(owner, 0.0), deadline)
        live = [o for o, d in self.claims.items() if d > now()]
        if len(live) > 1:
            msg = f"TWO OWNERS at once: nodes {sorted(live)}"
            self.violations.append(msg)
            log("monitor", msg)


def log(who: object, text: str) -> None:
    print(f"{now() % 1000:8.3f}  {who}: {text}")


# ----------------------------------------------------------------------
# Acceptor: three volatile variables and a quarantine
# ----------------------------------------------------------------------

class AcceptorRole:
    def __init__(self, node_id: int, net: Network, timing: Timing) -> None:
        self.node_id = node_id
        self.net = net
        self.timing = timing
        self.promised: Ballot = NO_BALLOT
        self.lease_owner: int | None = None
        self.lease_ballot: Ballot = NO_BALLOT
        self.lease_deadline: float = 0.0
        self.crashed = False
        self.quarantine_until = 0.0     # A4/T3

    def participating(self) -> bool:
        return not self.crashed and now() >= self.quarantine_until

    def live_lease(self) -> bool:
        return self.lease_owner is not None and now() < self.lease_deadline

    def on_prepare(self, msg: Prepare) -> None:
        """A1: promise the ballot and report the live accepted lease.
        An expired lease is reported as no lease.  A rejection carries the
        promised ballot: that is P1's liveness half, and this demo needs
        it, because after an owner dies its final ballot is still promised
        everywhere and a survivor climbing one counter per attempt would
        stall for many attempt durations."""
        if not self.participating():
            return
        if msg.ballot < self.promised:
            self.net.send(msg.src, Rejected(msg.ballot, self.node_id, self.promised))
            return
        self.promised = msg.ballot
        if self.live_lease():
            assert self.lease_owner is not None
            reply = Promise(msg.ballot, self.node_id, self.lease_owner, self.lease_ballot)
        else:
            reply = Promise(msg.ballot, self.node_id, None, NO_BALLOT)
        self.net.send(msg.src, reply)

    def on_accept(self, msg: Accept) -> None:
        """A2: record the lease instance (owner, ballot) and start the
        exclusion interval of D_A on this acceptor's own clock.  Never
        replace a live lease of a different owner, even under a higher
        ballot: overwriting it lets a renewal and a single acceptor restart
        produce two owners (see "Overwriting Acceptors" in the paper).
        The owner is an incarnation, the node together with the restart
        component of its ballot: a restarted proposer's ballots may be lower
        than its previous incarnation's, and a delayed Accept of that
        previous incarnation must not replace the new one's lease."""
        if not self.participating() or msg.ballot < self.promised:
            return
        if (
            self.lease_owner is not None
            and (self.lease_owner, self.lease_ballot[1])
            != (msg.owner, msg.ballot[1])
            and now() < self.lease_deadline
        ):
            return                       # refused, like a ballot rejection
        self.promised = msg.ballot
        self.lease_owner = msg.owner
        self.lease_ballot = msg.ballot
        self.lease_deadline = now() + self.timing.acceptor_duration
        self.net.send(msg.src, Accepted(msg.ballot, self.node_id))

    def crash(self) -> None:
        """Diskless: everything above is volatile and dies here."""
        self.crashed = True
        self.promised = NO_BALLOT
        self.lease_owner = None
        self.lease_ballot = NO_BALLOT
        self.lease_deadline = 0.0
        log(f"a{self.node_id}", "crashed, volatile lease state lost")

    def restart(self) -> None:
        """A4: refuse every lease-layer message for Q after a restart, so
        that everything this acceptor forgot has expired before it speaks
        again (T3, and "Restart Quarantine Bound" in the paper for why
        Q = D_P suffices)."""
        self.crashed = False
        self.quarantine_until = now() + self.timing.quarantine
        log(f"a{self.node_id}", f"restarted, quarantined for {self.timing.quarantine}s")


# ----------------------------------------------------------------------
# Proposer: one attempt is P1..P5; the deadline is data, not a callback
# ----------------------------------------------------------------------

class ProposerRole:
    def __init__(
        self,
        node_id: int,
        net: Network,
        timing: Timing,
        acceptor_ids: tuple[int, ...],
    ) -> None:
        self.node_id = node_id
        self.net = net
        self.timing = timing
        self.acceptor_ids = acceptor_ids
        self.counter = 0
        self.restart_count = 0
        self.ballot: Ballot = NO_BALLOT
        self.phase = "idle"
        self.deadline = 0.0             # T1: the attempt's stored deadline
        self.promises_ok: set[int] = set()
        self.accepted_from: set[int] = set()
        self.active_until = 0.0
        self.active_ballot: Ballot = NO_BALLOT
        # P2's renewal provenance, captured at P1: the ballot of the lease
        # this attempt renews, or None for a fresh acquisition.
        self.renewal_base: Ballot | None = None
        self.quorum_event = asyncio.Event()
        self.on_activate: list[LearnChosen] = []

    def quorum(self) -> int:
        return len(self.acceptor_ids) // 2 + 1

    def is_active(self) -> bool:
        return now() < self.active_until

    async def attempt(self) -> bool:
        """One acquisition attempt, steps P1 through P5.  Returns True if
        this proposer became (or stayed) the owner."""
        # P1: a fresh ballot, and the pending deadline stored AS DATA the
        # moment Prepare is broadcast.  This is rule T1.
        #
        # Moving this assignment below the wait for a prepare quorum, so
        # that the deadline starts when the evidence is about to be used,
        # would be UNSAFE: the prepare quorum then never expires and no
        # finite quarantine covers it, with acceptors that overwrite.  See
        # "Overwriting Acceptors" in the paper, which gives the 27-state
        # two-owner execution, and tla/counterexamples/LateTimer.tla.
        self.counter += 1
        self.ballot = (self.counter, self.restart_count, self.node_id)
        # P1 also captures the attempt's provenance as stored state: a
        # renewal renews exactly the lease that is active now, at the
        # start of the attempt (P2 checks the reported ballot against it).
        self.renewal_base = self.active_ballot if self.is_active() else None
        self.deadline = now() + self.timing.proposer_duration
        self.phase = "preparing"
        self.promises_ok = set()
        self.accepted_from = set()
        self.quorum_event.clear()
        log(f"p{self.node_id}", f"P1 Prepare {self.ballot}")
        for aid in self.acceptor_ids:
            self.net.send(aid, Prepare(self.ballot, self.node_id))

        if not await self._wait_for_quorum():
            return self._abandon("no prepare quorum before the deadline")

        # P3: broadcast Accept only while the attempt is fresh.
        if now() >= self.deadline:
            return self._abandon("deadline passed before Accept")
        self.phase = "accepting"
        self.quorum_event.clear()
        log(f"p{self.node_id}", f"P3 Accept {self.ballot}")
        for aid in self.acceptor_ids:
            self.net.send(aid, Accept(self.ballot, self.node_id, self.node_id))

        if not await self._wait_for_quorum():
            return self._abandon("no accept quorum before the deadline")

        # P4: activation, guarded by the same stored deadline.
        self.phase = "idle"
        self.active_until = self.deadline
        self.active_ballot = self.ballot
        log(f"p{self.node_id}", f"P4 ACTIVE until +{self.active_until - now():.2f}s")
        for node_id in self.net.nodes:
            self.net.send(node_id, LearnChosen(self.node_id, self.active_until, self.node_id))
        return True

    async def _wait_for_quorum(self) -> bool:
        remaining = self.deadline - now()
        if remaining <= 0:
            return False
        try:
            await asyncio.wait_for(self.quorum_event.wait(), timeout=remaining)
            return True
        except asyncio.TimeoutError:
            return False

    def _abandon(self, why: str) -> bool:
        """P5: give up, keep any lease already held, retry later under a
        fresh higher ballot.  Messages of this attempt may still be in
        flight; the ballot checks in on_promise and on_accepted discard
        their responses."""
        self.phase = "idle"
        log(f"p{self.node_id}", f"P5 abandon: {why}")
        return False

    def on_promise(self, msg: Promise) -> None:
        """P2: count a promise by acceptor IDENTITY, and count it as open
        only if it reports no live lease or, for a renewal attempt, the
        exact lease captured as this attempt's renewal base at P1, and
        only while that lease is still held.  The provenance is stored
        state, not inferred at delivery.

        Both qualifications are safety-critical.  Counting responses
        rather than distinct identities lets one acceptor's doubled reply
        pass for a quorum under a transport that may re-deliver (an
        18-state two-owner execution;
        tla/counterexamples/ScalarQuorumCounting.tla).  Treating any
        self-owned lease as open, instead of only the one being renewed,
        lets a record installed by this proposer's own abandoned attempt
        license a fresh acquisition while a competitor still owns the
        lease, with acceptors that overwrite; see "Overwriting Acceptors"
        in the paper and tla/counterexamples/StaleOwnerOpen.tla."""
        if self.phase != "preparing" or msg.ballot != self.ballot:
            return                       # stale response of an abandoned attempt
        renewing_this = (
            self.renewal_base is not None
            and msg.lease_ballot == self.renewal_base
            and self.is_active()
            and self.active_ballot == self.renewal_base
        )
        if msg.lease_owner is None or (msg.lease_owner == self.node_id and renewing_this):
            self.promises_ok.add(msg.src)
        else:
            log(f"p{self.node_id}", f"P2 blocked by live lease of node {msg.lease_owner}")
        if len(self.promises_ok) >= self.quorum():
            self.quorum_event.set()

    def on_rejected(self, msg: Rejected) -> None:
        """P1, the liveness half: raise the counter above any ballot this
        proposer observes, so the next attempt is not doomed to lose the
        same comparison.  Safety never depends on this."""
        if msg.ballot != self.ballot:
            return
        self.counter = max(self.counter, msg.promised[0])

    def on_accepted(self, msg: Accepted) -> None:
        """P4's counting half: identities again, current ballot only."""
        if self.phase != "accepting" or msg.ballot != self.ballot:
            return
        self.accepted_from.add(msg.src)
        if len(self.accepted_from) >= self.quorum():
            self.quorum_event.set()

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Owner life for the failover scenario: acquire, then renew at
        half-life (renewal is a fresh attempt under a higher ballot, and
        the P2 qualifier admits our own still-live lease); on failure,
        back off randomly like any competitor."""
        while not stop.is_set():
            if self.is_active():
                await asyncio.sleep((self.active_until - now()) / 2)
                if not stop.is_set():
                    await self.attempt()          # renewal
            else:
                if await self.attempt():
                    continue
                await asyncio.sleep(random.uniform(0.3, 1.0) * self.timing.proposer_duration)


# ----------------------------------------------------------------------
# Learner (L1) and the node bundle
# ----------------------------------------------------------------------

class LearnerRole:
    """L1: ownership becomes application-visible here.  The owner's own
    learner installs the absolute deadline its proposer computed; a remote
    learner records the owner with a conservative expiry and never acts on
    the lease itself."""

    def __init__(self, node_id: int, monitor: Monitor, timing: Timing) -> None:
        self.node_id = node_id
        self.monitor = monitor
        self.timing = timing
        self.owner: int | None = None
        self.owner_until = 0.0

    def on_learn(self, msg: LearnChosen) -> None:
        self.owner = msg.owner
        if msg.owner == self.node_id:
            self.owner_until = msg.deadline
            log(f"l{self.node_id}", f"node {msg.owner} is owner (that is us)")
            self.monitor.claim(msg.owner, msg.deadline)
        else:
            self.owner_until = now() + self.timing.proposer_duration
            log(f"l{self.node_id}", f"node {msg.owner} is owner")


class Node:
    """One process: proposer + acceptor + learner sharing an event loop."""

    def __init__(
        self,
        node_id: int,
        net: Network,
        timing: Timing,
        monitor: Monitor,
        acceptor_ids: tuple[int, ...],
    ) -> None:
        self.node_id = node_id
        self.acceptor = AcceptorRole(node_id, net, timing)
        self.proposer = ProposerRole(node_id, net, timing, acceptor_ids)
        self.learner = LearnerRole(node_id, monitor, timing)
        net.nodes[node_id] = self

    def handle(self, msg: Message) -> None:
        if isinstance(msg, Prepare):
            self.acceptor.on_prepare(msg)
        elif isinstance(msg, Promise):
            self.proposer.on_promise(msg)
        elif isinstance(msg, Rejected):
            self.proposer.on_rejected(msg)
        elif isinstance(msg, Accept):
            self.acceptor.on_accept(msg)
        elif isinstance(msg, Accepted):
            self.proposer.on_accepted(msg)
        elif isinstance(msg, LearnChosen):
            self.learner.on_learn(msg)


# ----------------------------------------------------------------------
# The scenario
# ----------------------------------------------------------------------

def build(timing: Timing, count: int = 3) -> tuple[Network, Monitor, list[Node]]:
    net = Network()
    monitor = Monitor()
    acceptor_ids = tuple(range(count))
    nodes = [Node(i, net, timing, monitor, acceptor_ids) for i in range(count)]
    return net, monitor, nodes


async def scenario_failover(timing: Timing) -> bool:
    """Normal operation: an owner emerges, renews, dies; a survivor takes over
    after the lease expires.  Success is a change of owner with zero
    overlap."""
    timing.check()
    net, monitor, nodes = build(timing)
    stop = asyncio.Event()
    tasks = [asyncio.create_task(n.proposer.run_forever(stop)) for n in nodes]
    lease = timing.proposer_duration

    await asyncio.sleep(3 * lease)
    victim = max(nodes, key=lambda n: n.proposer.active_until)
    log("scenario", f"killing node {victim.node_id}, the current owner")
    tasks[victim.node_id].cancel()
    victim.acceptor.crash()
    victim.proposer.active_until = 0.0

    await asyncio.sleep(4 * lease)
    stop.set()
    for t in tasks:
        t.cancel()
    took_over = monitor.owners_seen - {victim.node_id}
    ok = not monitor.violations and bool(took_over)
    log("scenario", f"owners seen {sorted(monitor.owners_seen)}, "
        f"violations {len(monitor.violations)}")
    return ok


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fast", action="store_true",
                        help="short timers, for the test suite")
    args = parser.parse_args()

    d = 0.5 if args.fast else 2.0
    timing = Timing(proposer_duration=d, acceptor_duration=1.2 * d, quarantine=d)
    random.seed(7)

    ok = asyncio.run(scenario_failover(timing))
    print("RESULT: failover with exclusive ownership" if ok else "RESULT: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
