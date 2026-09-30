from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

# Both configurations set Quarantine one unit below ProposerDuration, at two
# separated duration pairs.  They run against the raw module (no timing
# assumption), so TLC must exhibit the two-owner execution rather than reject
# the configuration.
UNSAFE_CONFIGS = {
    "PaxosLeaseUnsafeQuarantine.cfg": "unsafe-config.txt",      # (Dp, Da, Q) = (2, 3, 1)
    "PaxosLeaseUnsafeQuarantine12.cfg": "unsafe-config12.txt",  # (Dp, Da, Q) = (1, 2, 0)
}


def main() -> None:
    for cfg, record in UNSAFE_CONFIGS.items():
        proc = subprocess.run(
            [
                "tlc",
                "-cleanup",
                "-workers",
                "8",
                "-difftrace",
                "-config",
                cfg,
                "PaxosLease.tla",
            ],
            cwd=ROOT / "tla" / "spec",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        out = proc.stdout
        (RESULTS / record).write_text(out, encoding="utf-8")
        if proc.returncode == 0:
            raise SystemExit(f"{cfg}: unsafe quarantine config unexpectedly passed")
        if "Invariant LeaseExclusivity is violated" not in out:
            raise SystemExit(
                f"{cfg}: failed, but not with a lease-exclusivity violation"
            )
        trace_states = sum(1 for line in out.splitlines() if line.startswith("State "))
        print(
            f"{cfg}: TLC exhibits a lease-exclusivity violation "
            f"({trace_states}-state trace)"
        )


if __name__ == "__main__":
    main()
