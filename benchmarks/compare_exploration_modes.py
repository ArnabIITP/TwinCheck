#!/usr/bin/env python3
"""Compare static and observation-driven exploration on a pinned synthetic case.

This is a correctness/measurement harness for the checked-in fixture, not a
performance benchmark or a comparison with other testing tools.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "stateful-corpus-v2"
sys.path.insert(0, str(CORPUS))

from service import start_service  # noqa: E402
from twincheck.contract import load_contract  # noqa: E402
from twincheck.stateful_explore import run_http_sequence_exploration  # noqa: E402
from twincheck.stateful_http import load_sequence  # noqa: E402


def _run_mode(
    mode: str,
    case: dict[str, Any],
    manifest: dict[str, Any],
    *,
    seed: int,
    max_cases: int,
    max_adaptive_candidates: int,
    max_run_seconds: float,
    minimization_trials: int,
) -> dict[str, Any]:
    sequence, sequence_digest = load_sequence(CORPUS / case["sequence"])
    reset, reset_digest = load_sequence(CORPUS / case["reset_sequence"])
    contract = load_contract(CORPUS / case["contract"])
    reference, reference_thread = start_service(
        cart_id=f"comparison-reference-{mode}", **case["reference"]
    )
    candidate, candidate_thread = start_service(
        cart_id=f"comparison-candidate-{mode}", **case["candidate"]
    )
    try:
        report = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{reference.server_port}",
            candidate_url=f"http://127.0.0.1:{candidate.server_port}",
            sequence=sequence,
            sequence_sha256=sequence_digest,
            reset_sequence=reset,
            reset_sequence_sha256=reset_digest,
            seed=seed,
            max_cases=max_cases,
            timeout=manifest["timeout_seconds"],
            repeat=manifest["repeat"],
            max_output_bytes=manifest["max_output_bytes"],
            contract=contract,
            minimize=True,
            max_findings_to_minimize=1,
            max_minimization_trials=minimization_trials,
            mode=mode,
            max_adaptive_candidates=max_adaptive_candidates,
            max_run_seconds=max_run_seconds,
        )
        coverage = report["exploration"]["coverage_summary"]
        return {
            "mode": mode,
            "seed": seed,
            "case_budget": max_cases,
            "case_count_executed": report["cases_executed"],
            "candidates_generated": report["exploration"]["candidate_count"],
            "adaptive_candidates_generated": report["exploration"]["adaptive_generated_count"],
            "adaptive_candidates_executed": report["exploration"]["adaptive_executed_count"],
            "unique_response_branches": coverage["unique_response_branches"],
            "unique_adjacent_transitions": coverage["unique_adjacent_transitions"],
            "unique_difference_signatures": coverage["unique_difference_signatures"],
            "finding_count": report["summary"]["differences_found"],
            "minimization_trial_budget": minimization_trials,
            "minimization_trials_executed": report["exploration"]["minimization_trials_total"],
            "minimization_successes": report["summary"]["minimized_findings"],
            "elapsed_seconds": report["elapsed_seconds"],
            "stop_reason": report["exploration"]["stop_reason"],
        }
    finally:
        for server in (reference, candidate):
            server.shutdown()
            server.server_close()
        reference_thread.join(timeout=1)
        candidate_thread.join(timeout=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="stateful-read-ordering", help="case id from the pinned v0.9-derived corpus")
    parser.add_argument("--seed", type=int, default=19)
    parser.add_argument("--max-cases", type=int, default=12, help="same candidate-execution budget for both modes (1-200)")
    parser.add_argument("--max-adaptive-candidates", type=int, default=8, help="maximum adaptive candidates generated (0-200)")
    parser.add_argument("--max-run-seconds", type=float, default=60.0)
    parser.add_argument("--minimization-trials", type=int, default=12, help="same minimization-trial budget for both modes")
    parser.add_argument("--output", help="optional path for the JSON comparison report")
    args = parser.parse_args(argv)
    if not 1 <= args.max_cases <= 200:
        parser.error("--max-cases must be between 1 and 200")
    if not 0 <= args.max_adaptive_candidates <= 200:
        parser.error("--max-adaptive-candidates must be between 0 and 200")
    if not 1 <= args.max_run_seconds <= 3600:
        parser.error("--max-run-seconds must be between 1 and 3600")
    if not 1 <= args.minimization_trials <= 200:
        parser.error("--minimization-trials must be between 1 and 200")

    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    case = next((item for item in manifest["cases"] if item["id"] == args.case), None)
    if case is None:
        parser.error(f"unknown corpus case {args.case!r}")
    if not case.get("reset_sequence"):
        parser.error("selected corpus case must define reset_sequence")

    result = {
        "schema_version": 1,
        "purpose": "fixture-only static/adaptive stateful exploration comparison",
        "claim_boundary": (
            "These measurements describe this pinned synthetic fixture and settings only. "
            "They are not general performance, effectiveness, or superiority claims."
        ),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "fixture": {
            "corpus": manifest["name"],
            "corpus_schema_version": manifest["schema_version"],
            "case_id": args.case,
            "fixture_hashes": manifest["fixture_hashes"],
        },
        "shared_settings": {
            "seed": args.seed,
            "max_cases": args.max_cases,
            "max_run_seconds": args.max_run_seconds,
            "minimization_trial_budget": args.minimization_trials,
        },
        "results": [
            _run_mode(
                mode, case, manifest,
                seed=args.seed,
                max_cases=args.max_cases,
                max_adaptive_candidates=args.max_adaptive_candidates,
                max_run_seconds=args.max_run_seconds,
                minimization_trials=args.minimization_trials,
            )
            for mode in ("static", "adaptive")
        ],
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
