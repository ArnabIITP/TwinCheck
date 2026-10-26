"""Reproducible end-to-end smoke benchmark; not a cross-tool performance claim."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from twincheck.engine import run_comparison  # noqa: E402
from twincheck.runner import parse_command  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=123)
    args = parser.parse_args()
    if args.cases < 1 or args.rounds < 1:
        parser.error("--cases and --rounds must be at least 1")

    # Same interpreter and a simple identity operation keep the workload
    # deterministic. This measures orchestration/startup more than fuzz quality.
    code = "import sys; sys.stdout.write(sys.stdin.read())"
    command = __import__("shlex").join([sys.executable, "-c", code])
    durations: list[float] = []
    for _round in range(args.rounds):
        report = run_comparison(
            command,
            command,
            cases=args.cases,
            seed=args.seed,
            strategy="text",
            timeout=10,
            max_output_bytes=1_000_000,
        )
        if report["findings"]:
            print(json.dumps({"error": "identity comparison unexpectedly found a difference", "report": report}, indent=2))
            return 1
        durations.append(float(report["elapsed_seconds"]))

    median_seconds = statistics.median(durations)
    result = {
        "benchmark": "twincheck-identity-cli-smoke",
        "tool_version": report["tool_version"],
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cases_per_round": args.cases,
        "rounds": args.rounds,
        "seed": args.seed,
        "elapsed_seconds_by_round": durations,
        "median_seconds": median_seconds,
        "median_cases_per_second": args.cases / median_seconds if median_seconds else None,
        "note": "End-to-end process startup benchmark; not a cross-tool comparison or fuzzing effectiveness score.",
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
