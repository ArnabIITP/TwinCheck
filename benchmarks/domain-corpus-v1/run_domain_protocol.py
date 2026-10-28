#!/usr/bin/env python3
"""Run the pinned stateful exploration protocol on an independent inventory API domain."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "benchmarks" / "domain-corpus-v1"
sys.path.insert(0, str(CORPUS))
from service import start_service  # noqa: E402
from twincheck.contract import load_contract  # noqa: E402
from twincheck.stateful_explore import run_http_sequence_exploration  # noqa: E402
from twincheck.stateful_http import load_sequence  # noqa: E402

class DomainProtocolError(ValueError):
    pass

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainProtocolError(f"cannot read {path}: {exc}") from exc

def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()

def _load() -> dict[str, Any]:
    manifest = _read_json(CORPUS / "manifest.json")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("cases"), list):
        raise DomainProtocolError("unsupported or malformed domain corpus manifest")
    for relative, expected in manifest.get("fixture_hashes", {}).items():
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise DomainProtocolError(f"fixture missing or not a regular file: {relative}")
        actual = _file_hash(path)
        if actual != expected:
            raise DomainProtocolError(f"fixture hash mismatch for {relative}: expected {expected}, got {actual}")
    for case in manifest["cases"]:
        if not isinstance(case.get("id"), str) or not isinstance(case.get("expected"), dict):
            raise DomainProtocolError("malformed domain case")
        for mode in ("static", "adaptive"):
            if type(case["expected"].get(mode, {}).get("finding")) is not bool:
                raise DomainProtocolError(f"{case['id']}: expected {mode}.finding boolean")
        load_sequence(CORPUS / case["sequence"])
    load_sequence(CORPUS / "sequences/reset-v1.json")
    load_contract(CORPUS / "contracts/inventory-compatibility-v1.json")
    return manifest

def _stop(server: Any, thread: threading.Thread) -> None:
    stopper = threading.Thread(target=server.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    server.server_close()
    thread.join(timeout=2)

def _run_once(manifest: dict[str, Any], case: dict[str, Any], mode: str, seed: int, round_index: int, max_run_seconds: float) -> dict[str, Any]:
    sequence, sequence_hash = load_sequence(CORPUS / case["sequence"])
    reset, reset_hash = load_sequence(CORPUS / "sequences/reset-v1.json")
    contract = load_contract(CORPUS / "contracts/inventory-compatibility-v1.json")
    reference, reference_thread = start_service(service_id=f"ref-{case['id']}-{mode}-{round_index}", **case["reference"])
    candidate, candidate_thread = start_service(service_id=f"cand-{case['id']}-{mode}-{round_index}", **case["candidate"])
    started = time.perf_counter()
    try:
        report = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{reference.server_port}",
            candidate_url=f"http://127.0.0.1:{candidate.server_port}",
            sequence=sequence,
            sequence_sha256=sequence_hash,
            reset_sequence=reset,
            reset_sequence_sha256=reset_hash,
            seed=seed,
            max_cases=case["max_cases"],
            timeout=manifest["timeout_seconds"],
            repeat=manifest["repeat"],
            max_output_bytes=manifest["max_output_bytes"],
            contract=contract,
            minimize=False,
            max_findings_to_minimize=0,
            max_minimization_trials=1,
            mode=mode,
            max_adaptive_candidates=case["max_adaptive_candidates"],
            max_run_seconds=max_run_seconds,
        )
    finally:
        _stop(reference, reference_thread)
        _stop(candidate, candidate_thread)
    elapsed = time.perf_counter() - started
    finding = report["summary"]["differences_found"] > 0
    expected = case["expected"][mode]["finding"]
    if finding != expected:
        raise DomainProtocolError(f"{case['id']}/{mode}/seed={seed}/round={round_index}: expected finding={expected}, observed {finding}")
    return {
        "case_id": case["id"], "mode": mode, "seed": seed, "round": round_index,
        "expected_finding": expected, "finding": finding,
        "finding_count": report["summary"]["differences_found"],
        "cases_executed": report.get("cases_executed", 0),
        "elapsed_seconds": round(float(report.get("elapsed_seconds", elapsed)), 6),
        "wall_seconds": round(elapsed, 6),
        "stop_reason": report.get("exploration", {}).get("stop_reason"),
        "expectation_met": True,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2, help="repeat fixed seeds and modes to check expected outcomes")
    parser.add_argument("--max-run-seconds", type=float, default=10.0)
    parser.add_argument("--output", help="optional path for JSON evidence")
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 5 or not 1 <= args.max_run_seconds <= 60:
        parser.error("--rounds must be 1-5 and --max-run-seconds must be 1-60")
    try:
        manifest = _load()
        results = []
        for case in manifest["cases"]:
            for seed in case["seeds"]:
                for round_index in range(1, args.rounds + 1):
                    for mode in ("static", "adaptive"):
                        results.append(_run_once(manifest, case, mode, seed, round_index, args.max_run_seconds))
        per_mode = {}
        for mode in ("static", "adaptive"):
            rows = [row for row in results if row["mode"] == mode]
            defect_runs = [row for row in rows if row["expected_finding"]]
            per_mode[mode] = {
                "runs": len(rows),
                "expected_outcomes_met": sum(row["expectation_met"] for row in rows),
                "seeded_defect_detection_rate": sum(row["finding"] and row["expected_finding"] for row in defect_runs) / len(defect_runs) if defect_runs else None,
                "false_positive_runs": sum(row["finding"] and not row["expected_finding"] for row in rows),
                "median_wall_seconds": round(statistics.median(row["wall_seconds"] for row in rows), 6) if rows else None,
            }
        result = {
            "schema_version": 1,
            "protocol": "TwinCheck independent inventory domain protocol v1",
            "purpose": "Verify known clean and seeded-defect outcomes on a second API domain under matched static/adaptive case budgets.",
            "claim_boundary": "Only the pinned in-memory inventory/reservation fixtures and tested seeds/budgets are covered; this is not a real-world effectiveness estimate.",
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "source_revision": os.environ.get("GITHUB_SHA")},
            "corpus": {"name": manifest["name"], "fixture_hashes": manifest["fixture_hashes"], "known_blind_spots": manifest["known_blind_spots"]},
            "settings": {"rounds": args.rounds, "max_run_seconds": args.max_run_seconds, "matched_case_budgets": True},
            "modes": per_mode, "results": results, "passed": True,
        }
        rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        print(f"[PASS] inventory domain: {len(results)} expected-outcome runs across {len(manifest['cases'])} scenarios", file=sys.stderr)
        return 0
    except (DomainProtocolError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"[FAIL] inventory domain protocol: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
