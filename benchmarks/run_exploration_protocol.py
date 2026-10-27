#!/usr/bin/env python3
"""Run the pinned, synthetic static-vs-adaptive exploration protocol.

The corpus checks correctness and repeatability under matched candidate budgets.
It is not a general effectiveness benchmark or a comparison against other tools.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "exploration-corpus-v1"
MANIFEST_PATH = CORPUS / "manifest.json"
SCHEMA_PATH = ROOT / "benchmarks" / "exploration-corpus-v1.schema.json"

sys.path.insert(0, str(CORPUS))
from service import start_service  # noqa: E402

from twincheck.contract import load_contract  # noqa: E402
from twincheck.stateful_explore import run_http_sequence_exploration  # noqa: E402
from twincheck.stateful_http import load_sequence  # noqa: E402


class ProtocolFailure(RuntimeError):
    """A corpus, expectation, or repeatability check failed."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolFailure(f"cannot read JSON {path}: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return _sha256(encoded.encode("utf-8"))


def _checked_corpus_path(relative: str) -> Path:
    candidate = CORPUS / relative
    if candidate.is_symlink():
        raise ProtocolFailure(f"fixture is a symbolic link: {relative}")
    path = candidate.resolve()
    if not path.is_relative_to(CORPUS.resolve()):
        raise ProtocolFailure(f"fixture path escapes corpus directory: {relative}")
    if not path.is_file():
        raise ProtocolFailure(f"fixture is missing or not a regular file: {relative}")
    return path


def _normalized_file_hash(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProtocolFailure(f"cannot hash fixture {path}: {exc}") from exc
    return _sha256(content)


def _validate(validator: Draft202012Validator, value: Any, label: str) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "(root)"
        raise ProtocolFailure(f"{label} violates its schema at {where}: {first.message}")


def _load_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _json(MANIFEST_PATH)
    schema = _json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    _validate(Draft202012Validator(schema), manifest, "exploration corpus manifest")

    sequence_schema_path = ROOT / "docs" / "stateful-http-sequence-v1.schema.json"
    contract_schema_path = ROOT / "docs" / "compatibility-contract-v1.schema.json"
    sequence_schema = _json(sequence_schema_path)
    contract_schema = _json(contract_schema_path)
    Draft202012Validator.check_schema(sequence_schema)
    Draft202012Validator.check_schema(contract_schema)
    sequence_validator = Draft202012Validator(sequence_schema)
    contract_validator = Draft202012Validator(contract_schema)

    required_pins = {
        "benchmarks/exploration-corpus-v1.schema.json",
        "benchmarks/exploration-corpus-v1/service.py",
        "docs/stateful-http-sequence-v1.schema.json",
        "docs/compatibility-contract-v1.schema.json",
    }
    for case in manifest["cases"]:
        for field in ("sequence", "reset_sequence", "contract"):
            required_pins.add(f"benchmarks/exploration-corpus-v1/{case[field]}")
    pins = manifest["fixture_hashes"]
    missing = sorted(required_pins - set(pins))
    if missing:
        raise ProtocolFailure("manifest is missing fixture hash pins: " + ", ".join(missing))

    drift: list[str] = []
    for relative, expected in sorted(pins.items()):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            drift.append(f"{relative}: missing or not a regular file")
            continue
        actual = _normalized_file_hash(path)
        if actual != expected:
            drift.append(f"{relative}: expected {expected}, got {actual}")
    if drift:
        raise ProtocolFailure("fixture hash mismatch:\n  " + "\n  ".join(drift))

    for case in manifest["cases"]:
        sequence_path = _checked_corpus_path(case["sequence"])
        reset_path = _checked_corpus_path(case["reset_sequence"])
        contract_path = _checked_corpus_path(case["contract"])
        _validate(sequence_validator, _json(sequence_path), f"{case['id']} sequence")
        _validate(sequence_validator, _json(reset_path), f"{case['id']} reset sequence")
        _validate(contract_validator, _json(contract_path), f"{case['id']} contract")
        # Parse with the production loader too, not just the JSON Schema.
        load_sequence(sequence_path)
        load_sequence(reset_path)
        load_contract(contract_path)
    return manifest, {
        "sequence_validator": sequence_validator,
        "contract_validator": contract_validator,
    }


def _finding_evidence(report: dict[str, Any]) -> tuple[list[str], list[str]]:
    step_names: list[str] = []
    categories: list[str] = []
    for finding in report.get("findings", []):
        for step in finding.get("step_results", []):
            if not isinstance(step, dict) or not step.get("differences"):
                continue
            name = step.get("name")
            if isinstance(name, str):
                step_names.append(name)
            categories.extend(str(item) for item in step.get("differences", []))
    return sorted(set(step_names)), sorted(set(categories))


def _stop_pair(
    reference: Any,
    reference_thread: threading.Thread,
    candidate: Any,
    candidate_thread: threading.Thread,
) -> None:
    # Shut down both servers concurrently so a paired measurement is not
    # dominated by sequential server.shutdown polling delays.
    stoppers = [
        threading.Thread(target=server.shutdown, daemon=True)
        for server in (reference, candidate)
    ]
    for stopper in stoppers:
        stopper.start()
    for stopper in stoppers:
        stopper.join(timeout=2)
    for server in (reference, candidate):
        server.server_close()
    reference_thread.join(timeout=2)
    candidate_thread.join(timeout=2)


def _run_once(
    case: dict[str, Any],
    manifest: dict[str, Any],
    *,
    mode: str,
    seed: int,
    round_index: int,
    max_run_seconds: float,
) -> dict[str, Any]:
    sequence, sequence_digest = load_sequence(_checked_corpus_path(case["sequence"]))
    reset_sequence, reset_digest = load_sequence(_checked_corpus_path(case["reset_sequence"]))
    contract = load_contract(_checked_corpus_path(case["contract"]))

    reference, reference_thread = start_service(
        cart_id=f"ref-{case['id']}-{mode}-{seed}-{round_index}",
        **case["reference"],
    )
    candidate, candidate_thread = start_service(
        cart_id=f"cand-{case['id']}-{mode}-{seed}-{round_index}",
        **case["candidate"],
    )
    started = time.perf_counter()
    try:
        report = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{reference.server_port}",
            candidate_url=f"http://127.0.0.1:{candidate.server_port}",
            sequence=sequence,
            sequence_sha256=sequence_digest,
            reset_sequence=reset_sequence,
            reset_sequence_sha256=reset_digest,
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
        _stop_pair(reference, reference_thread, candidate, candidate_thread)
    wall_seconds = time.perf_counter() - started

    if not isinstance(report, dict) or not isinstance(report.get("exploration"), dict):
        raise ProtocolFailure(f"{case['id']} ({mode}): malformed exploration report")
    finding = report["summary"]["differences_found"] > 0
    step_names, categories = _finding_evidence(report)
    expected = case["expected"][mode]
    matches = finding is expected["finding"]
    if matches and expected.get("step_name"):
        matches = expected["step_name"] in step_names
    if matches and expected.get("difference_category"):
        matches = expected["difference_category"] in categories
    executions = report.get("executions", [])
    if expected.get("mutation_type"):
        matches = matches and any(
            isinstance(item, dict) and item.get("mutation_type") == expected["mutation_type"]
            for item in executions
        )

    # This fingerprints only the tested mutation schedule (types and input
    # digests), not request/response bodies or other potentially sensitive data.
    schedule = [
        {
            "mutation_type": item.get("mutation_type"),
            "input_sha256": item.get("input_sha256"),
        }
        for item in executions if isinstance(item, dict)
    ]
    exploration = report["exploration"]
    coverage = exploration.get("coverage_summary", {})
    return {
        "case_id": case["id"],
        "mode": mode,
        "seed": seed,
        "round": round_index,
        "case_budget": case["max_cases"],
        "cases_executed": report.get("cases_executed", len(executions)),
        "candidate_count": exploration.get("candidate_count", 0),
        "adaptive_generated_count": exploration.get("adaptive_generated_count", 0),
        "adaptive_executed_count": exploration.get("adaptive_executed_count", 0),
        "unique_response_branches": coverage.get("unique_response_branches", 0),
        "unique_adjacent_transitions": coverage.get("unique_adjacent_transitions", 0),
        "unique_difference_signatures": coverage.get("unique_difference_signatures", 0),
        "finding": finding,
        "finding_count": report["summary"].get("differences_found", 0),
        "finding_steps": step_names,
        "difference_categories": categories,
        "schedule_sha256": _canonical_hash(schedule),
        "elapsed_seconds": round(float(report.get("elapsed_seconds", wall_seconds)), 6),
        "wall_seconds": round(wall_seconds, 6),
        "stop_reason": exploration.get("stop_reason"),
        "expectation_met": matches,
    }


def _build_result(
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    rounds: int,
    max_run_seconds: float,
) -> dict[str, Any]:
    failures: list[str] = []
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault((record["case_id"], record["mode"], record["seed"]), []).append(record)
        if not record["expectation_met"]:
            failures.append(
                f"{record['case_id']} / {record['mode']} / seed {record['seed']} / "
                f"round {record['round']}: expected outcome not reproduced "
                f"(finding={record['finding']}, steps={record['finding_steps']})"
            )

    repeatability_groups = 0
    repeatability_passes = 0
    for (case_id, mode, seed), repeated in sorted(groups.items()):
        repeated.sort(key=lambda item: item["round"])
        if len(repeated) < 2:
            continue
        repeatability_groups += 1
        first = repeated[0]
        same = all(
            item["schedule_sha256"] == first["schedule_sha256"]
            and item["finding"] == first["finding"]
            and item["finding_count"] == first["finding_count"]
            and item["finding_steps"] == first["finding_steps"]
            and item["cases_executed"] == first["cases_executed"]
            for item in repeated[1:]
        )
        if same:
            repeatability_passes += 1
        else:
            failures.append(f"{case_id} / {mode} / seed {seed}: repeated schedule or outcome changed")

    aggregates = []
    for case in manifest["cases"]:
        for mode in ("static", "adaptive"):
            subset = [item for item in records if item["case_id"] == case["id"] and item["mode"] == mode]
            elapsed = [item["wall_seconds"] for item in subset]
            aggregates.append({
                "case_id": case["id"],
                "mode": mode,
                "runs": len(subset),
                "expected_outcomes_met": sum(1 for item in subset if item["expectation_met"]),
                "expectation_pass_fraction": (
                    sum(1 for item in subset if item["expectation_met"]) / len(subset) if subset else 0.0
                ),
                "finding_runs": sum(1 for item in subset if item["finding"]),
                "median_wall_seconds": round(statistics.median(elapsed), 6) if elapsed else None,
                "min_wall_seconds": round(min(elapsed), 6) if elapsed else None,
                "max_wall_seconds": round(max(elapsed), 6) if elapsed else None,
            })

    paired = {"both_found": 0, "static_only": 0, "adaptive_only": 0, "neither_found": 0, "pairs": 0}
    paired_groups: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}
    for item in records:
        paired_groups.setdefault((item["case_id"], item["seed"], item["round"]), {})[item["mode"]] = item
    for key, pair in paired_groups.items():
        if "static" not in pair or "adaptive" not in pair:
            failures.append(f"{key}: missing static/adaptive pair")
            continue
        paired["pairs"] += 1
        static_finding = pair["static"]["finding"]
        adaptive_finding = pair["adaptive"]["finding"]
        if static_finding and adaptive_finding:
            paired["both_found"] += 1
        elif static_finding:
            paired["static_only"] += 1
        elif adaptive_finding:
            paired["adaptive_only"] += 1
        else:
            paired["neither_found"] += 1

    return {
        "schema_version": 1,
        "protocol": "TwinCheck synthetic exploration protocol v1",
        "purpose": "Expected-outcome and repeatability checks under paired static/adaptive execution budgets.",
        "claim_boundary": (
            "Results describe only the versioned synthetic in-memory HTTP fixtures, seeds, budgets, "
            "Python version and platform in this report. They do not establish general effectiveness, "
            "real-world API coverage, or superiority over other testing tools."
        ),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "source_revision": os.environ.get("GITHUB_SHA"),
        },
        "corpus": {
            "name": manifest["name"],
            "schema_version": manifest["schema_version"],
            "fixture_hashes": manifest["fixture_hashes"],
            "known_blind_spots": manifest["known_blind_spots"],
        },
        "settings": {
            "rounds": rounds,
            "max_run_seconds": max_run_seconds,
            "seed_values_by_case": {case["id"]: case["seeds"] for case in manifest["cases"]},
            "minimization_enabled": False,
            "candidate_budget_is_paired": True,
        },
        "paired_outcomes": paired,
        "repeatability": {
            "groups_checked": repeatability_groups,
            "groups_passed": repeatability_passes,
            "all_repeated_schedules_stable": repeatability_groups == repeatability_passes,
        },
        "aggregates": aggregates,
        "results": records,
        "failures": failures,
        "passed": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2, help="repeat each fixed seed/mode pair to verify schedule stability (1-5)")
    parser.add_argument("--max-run-seconds", type=float, default=20.0, help="exploration start deadline for each run (1-60 seconds)")
    parser.add_argument("--output", help="optional path for the full JSON evidence report")
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds must be between 1 and 5")
    if not 1 <= args.max_run_seconds <= 60:
        parser.error("--max-run-seconds must be between 1 and 60")

    try:
        manifest, _ = _load_manifest()
        records: list[dict[str, Any]] = []
        for case in manifest["cases"]:
            for seed in case["seeds"]:
                for round_index in range(1, args.rounds + 1):
                    for mode in ("static", "adaptive"):
                        records.append(_run_once(
                            case, manifest, mode=mode, seed=seed,
                            round_index=round_index, max_run_seconds=args.max_run_seconds,
                        ))
        result = _build_result(
            manifest, records, rounds=args.rounds,
            max_run_seconds=args.max_run_seconds,
        )
        rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        if result["failures"]:
            print("[FAIL] exploration protocol expectations or repeatability checks failed", file=sys.stderr)
            return 1
        print(
            f"[PASS] {len(records)} paired mode runs; "
            f"{result['repeatability']['groups_passed']}/{result['repeatability']['groups_checked']} "
            "repeatability groups stable",
            file=sys.stderr,
        )
        return 0
    except (OSError, ValueError, ProtocolFailure) as exc:
        print(f"[FAIL] exploration protocol: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
