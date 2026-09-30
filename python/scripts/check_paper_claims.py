"""Cross-check the paper's cited numbers against the recorded results.

Every TLC run the paper cites has a recorded output under results/.  For a
violation run this script checks that the invariant is reported violated and
that the error trace has exactly the cited number of states; for a passing
run, that model checking completed with no error over exactly the cited
number of distinct states.  It also checks that each number appears in the
paper, and that the witness count the paper states in words matches the
witness registry.  A mismatch means the paper or the recorded evidence
drifted; the target fails until they agree again.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEX = ROOT / "paper" / "PaxosLease-Revisited.tex"
RESULTS = ROOT / "results"

# Violation runs: each recorded file must report the named invariant as
# violated, with an error trace of exactly the cited length (breadth-first
# search finds a minimum-depth trace, so the length is stable across runs).
VIOLATIONS: dict[str, tuple[str, int]] = {
    "counterexample-latetimer.txt": ("LeaseExclusivity", 27),
    "counterexample-latetimer-tcp.txt": ("LeaseExclusivity", 27),
    "counterexample-latetimer-3acceptors.txt": ("LeaseExclusivity", 25),
    "counterexample-owneronlyrelease.txt": ("LeaseExclusivity", 36),
    "counterexample-scalarquorumcounting.txt": ("LeaseExclusivity", 18),
    "counterexample-staleowneropen.txt": ("LeaseExclusivity", 36),
    "staleowner-tcp.txt": ("LeaseExclusivity", 36),
    "counterexample-nodeowner.txt": ("Safety", 43),
    "counterexample-renewcrash.txt": ("Safety", 39),
    "counterexample-releasecrash.txt": ("Safety", 40),
    "unsafe-config.txt": ("LeaseExclusivity", 26),
    "unsafe-config12.txt": ("LeaseExclusivity", 25),
    "unsafe-config-3acceptors.txt": ("LeaseExclusivity", 24),
    "impl-timely-below.txt": ("LeaseExclusivity", 26),
    "impl-timely-rdominant.txt": ("LeaseExclusivity", 26),
    "impl-delayed-shipped.txt": ("LeaseExclusivity", 27),
    "impl-delayed-shipped-tcp.txt": ("LeaseExclusivity", 27),
    "impl-delayed-colocated.txt": ("LeaseExclusivity", 25),
    "impl-delayed-colocated-tcp.txt": ("LeaseExclusivity", 25),
    "impl-staleowner.txt": ("Safety", 35),
}

# Passing runs: each recorded file must report that model checking
# completed with no error, over exactly the cited number of distinct states.
PASSES: dict[str, int] = {
    "check-base.txt": 491_037,
    "check-renew-release.txt": 7_717,
    "check-crash-restart.txt": 37_425_056,
    "check-drift.txt": 40_784,
    "check-qep.txt": 76_749_192,
    "check-qep23.txt": 36_772_096,
    "check-redeliver.txt": 1_857_563,
    "release-race.txt": 23_743_497,
    "retry-redeliver.txt": 53_723_103,
    "renew-release-stale.txt": 204_050,
    "nodeowner-base.txt": 220_119,
    "renewcrash-a2.txt": 6_330_050,
    "latetimer-a2.txt": 23_777_320,
    "releasecrash-a2.txt": 224_164_193,
    "retry.txt": 2_179_760_458,
    "renew-retry.txt": 2_411_951_538,
    "composition.txt": 2_095,
    "impl-timely-boundary.txt": 37_160_904,
    "impl-timely-rdominant-safe.txt": 37_476_080,
    "impl-timely-shipped.txt": 18_160_464,
}

def _tex_number(n: int) -> str:
    return f"{n:,}"


def main() -> None:
    failures: list[str] = []

    tex = TEX.read_text(encoding="utf-8").replace("{,}", ",")

    for name, (invariant, depth) in VIOLATIONS.items():
        path = RESULTS / name
        if not path.exists():
            failures.append(f"{name}: recorded results file missing")
            continue
        text = path.read_text(encoding="utf-8")
        if f"Invariant {invariant} is violated" not in text:
            failures.append(f"{name}: expected violation of {invariant} not recorded")
        states = len(re.findall(r"^State \d+:", text, flags=re.M))
        if states != depth:
            failures.append(f"{name}: trace has {states} states, paper cites {depth}")
        if f"{depth}-state" not in tex and f"{depth} states" not in tex:
            failures.append(f"paper: trace length {depth} of {name} not cited")

    for name, distinct in PASSES.items():
        path = RESULTS / name
        if not path.exists():
            failures.append(f"{name}: recorded results file missing")
            continue
        text = path.read_text(encoding="utf-8")
        if "Model checking completed. No error has been found" not in text:
            failures.append(f"{name}: recorded run did not complete without error")
        if not re.search(rf"\b{distinct} distinct states found\b", text):
            failures.append(f"{name}: recorded run does not show {distinct} distinct states")
        if _tex_number(distinct) not in tex:
            failures.append(f"paper: count {_tex_number(distinct)} of {name} not cited")

    # The witness count the paper states in words must match the recorded
    # witness registry.
    witnesses = json.loads((RESULTS / "counterexamples.json").read_text(encoding="utf-8"))
    count_words = {13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen"}
    word = count_words.get(len(witnesses))
    if word is None:
        failures.append(f"witness registry has unmapped count {len(witnesses)}")
    elif f"{word} structured" not in tex:
        failures.append(
            f"paper: witness count mismatch: registry has {len(witnesses)} "
            f"({word}), but '{word} structured' not found in the tex"
        )
    for stale_word in count_words.values():
        if stale_word != word and f"{stale_word} structured" in tex:
            failures.append(f"paper: stale witness count '{stale_word} structured' present")

    if failures:
        for f in failures:
            print(f"FAIL {f}", file=sys.stderr)
        sys.exit(1)
    print(
        f"paper claims consistent: {len(VIOLATIONS)} violation runs, "
        f"{len(PASSES)} passing runs"
    )


if __name__ == "__main__":
    main()
