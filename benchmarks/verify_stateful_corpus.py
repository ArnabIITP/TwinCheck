#!/usr/bin/env python3
"""Verify TwinCheck's versioned stateful regression corpus end to end.

Run after installing the test extra:
    python -m pip install -e ".[test]"
    python benchmarks/verify_stateful_corpus.py

All HTTP traffic stays on ephemeral 127.0.0.1 ports. This is a correctness
verification script, not a performance benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from jsonschema import Draft202012Validator, RefResolver, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "stateful-corpus-v2"
MANIFEST_PATH = CORPUS / "manifest.json"
sys.path.insert(0, str(CORPUS))
from service import start_service  # noqa: E402

from twincheck.contract import load_contract  # noqa: E402
from twincheck.stateful_explore import run_http_sequence_exploration  # noqa: E402
from twincheck.stateful_http import load_sequence, run_http_sequence_comparison  # noqa: E402
from twincheck.stateful_packs import (  # noqa: E402
    export_stateful_sequence_pack,
    load_stateful_sequence_pack,
)


class CorpusFailure(RuntimeError):
    """The checked-in expected corpus result was not reproduced."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CorpusFailure(f"cannot load JSON fixture {path.relative_to(ROOT)}: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _schema(path: Path) -> dict[str, Any]:
    value = _json(path)
    if not isinstance(value, dict):
        raise CorpusFailure(f"schema is not a JSON object: {path.relative_to(ROOT)}")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise CorpusFailure(f"invalid JSON Schema {path.relative_to(ROOT)}: {exc}") from exc
    return value


def _validator(schema_path: Path, schemas_by_name: dict[str, dict[str, Any]] | None = None) -> Draft202012Validator:
    schema = _schema(schema_path)
    store: dict[str, dict[str, Any]] = {}
    if schemas_by_name:
        base = str(schema.get("$id", ""))
        for name, item in schemas_by_name.items():
            store[urljoin(base, name)] = item
    resolver = RefResolver.from_schema(schema, store=store)
    return Draft202012Validator(schema, resolver=resolver)


def _validate(validator: Draft202012Validator, value: Any, label: str) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda err: list(err.absolute_path))
    if errors:
        error = errors[0]
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        raise CorpusFailure(f"{label} does not match its versioned schema at {where}: {error.message}")


def _check_fixture_hashes(manifest: dict[str, Any]) -> None:
    pins = manifest.get("fixture_hashes")
    if not isinstance(pins, dict):
        raise CorpusFailure("manifest fixture_hashes must be an object")
    referenced = {
        "benchmarks/stateful-corpus-v2.schema.json",
        "docs/stateful-http-sequence-v1.schema.json",
        "docs/compatibility-contract-v1.schema.json",
        "docs/report-schema-v1.schema.json",
        "docs/stateful-regression-pack-v1.schema.json",
        "benchmarks/stateful-corpus-v2/service.py",
    }
    for case in manifest["cases"]:
        referenced.add(f"benchmarks/stateful-corpus-v2/{case['sequence']}")
        referenced.add(f"benchmarks/stateful-corpus-v2/{case['contract']}")
        if case.get("reset_sequence"):
            referenced.add(f"benchmarks/stateful-corpus-v2/{case['reset_sequence']}")
    missing = sorted(referenced - set(pins))
    if missing:
        raise CorpusFailure("manifest does not pin every referenced fixture: " + ", ".join(missing))
    drift: list[str] = []
    for relative, expected in sorted(pins.items()):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            drift.append(f"{relative}: missing or not a regular file")
            continue
        # Normalize checkout line endings so this pin is stable on Windows and POSIX.
        actual = _sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8"))
        if actual != expected:
            drift.append(f"{relative}: expected {expected}, got {actual}")
    if drift:
        raise CorpusFailure("fixture SHA-256 drift:\n  " + "\n  ".join(drift))


def _validate_checked_in_schemas(manifest_validator: Draft202012Validator) -> tuple[
    Draft202012Validator, Draft202012Validator, Draft202012Validator, Draft202012Validator
]:
    _validate(manifest_validator, _json(MANIFEST_PATH), "stateful corpus manifest")
    sequence_schema = _schema(ROOT / "docs" / "stateful-http-sequence-v1.schema.json")
    contract_schema = _schema(ROOT / "docs" / "compatibility-contract-v1.schema.json")
    report_schema = _schema(ROOT / "docs" / "report-schema-v1.schema.json")
    pack_schema = _schema(ROOT / "docs" / "stateful-regression-pack-v1.schema.json")
    report_validator = _validator(
        ROOT / "docs" / "report-schema-v1.schema.json",
        {
            "compatibility-contract-v1.schema.json": contract_schema,
            "stateful-http-sequence-v1.schema.json": sequence_schema,
        },
    )
    sequence_validator = Draft202012Validator(sequence_schema)
    contract_validator = Draft202012Validator(contract_schema)
    pack_validator = Draft202012Validator(pack_schema)
    return sequence_validator, contract_validator, report_validator, pack_validator


def _sequence_and_contract(case: dict[str, Any], sequence_validator: Draft202012Validator,
                           contract_validator: Draft202012Validator):
    sequence_path = CORPUS / case["sequence"]
    contract_path = CORPUS / case["contract"]
    sequence, sequence_hash = load_sequence(sequence_path)
    contract_dict = _json(contract_path)
    _validate(sequence_validator, sequence, f"sequence fixture {case['id']}")
    _validate(contract_validator, contract_dict, f"contract fixture {case['id']}")
    contract = load_contract(contract_path)
    reset, reset_hash = (None, None)
    if case.get("reset_sequence"):
        reset, reset_hash = load_sequence(CORPUS / case["reset_sequence"])
        _validate(sequence_validator, reset, f"reset sequence fixture {case['id']}")
    return sequence, sequence_hash, contract, reset, reset_hash


def _find_step(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    for finding in report.get("findings", []):
        for step in finding.get("step_results", []):
            if step.get("name") == name and step.get("differences"):
                return step
    return None


def _verify_finding(report: dict[str, Any], expected: dict[str, Any], case_id: str) -> dict[str, Any]:
    if not report.get("findings"):
        raise CorpusFailure(f"{case_id}: expected a finding but TwinCheck reported none")
    step_name = expected.get("step_name")
    step = _find_step(report, step_name) if step_name else None
    if step_name and step is None:
        raise CorpusFailure(f"{case_id}: expected a difference at named step {step_name!r}")
    if step is None:
        step = next(
            (item for finding in report["findings"] for item in finding.get("step_results", []) if item.get("differences")),
            None,
        )
    if step is None:
        raise CorpusFailure(f"{case_id}: findings had no step-level differences")
    actual_categories = sorted(set(step.get("differences", [])))
    expected_categories = sorted(set(expected.get("difference_categories", [])))
    if actual_categories != expected_categories:
        raise CorpusFailure(f"{case_id}: expected categories {expected_categories}, got {actual_categories}")
    explanation = step.get("explanation")
    if not isinstance(explanation, dict):
        raise CorpusFailure(f"{case_id}: difference explanation is missing")
    if explanation.get("values_included") is not False:
        raise CorpusFailure(f"{case_id}: difference explanation must not include observed values")
    pointers = sorted(set(explanation.get("safe_difference_pointers", [])))
    expected_pointers = sorted(set(expected.get("safe_difference_pointers", [])))
    if pointers != expected_pointers:
        raise CorpusFailure(f"{case_id}: expected safe pointers {expected_pointers}, got {pointers}")
    return {
        "step_name": step.get("name"),
        "difference_categories": actual_categories,
        "safe_difference_pointers": pointers,
        "reference_status": explanation.get("reference_status"),
        "candidate_status": explanation.get("candidate_status"),
        "comparison_rules": explanation.get("comparison_rules"),
    }


def _start_pair(case_id: str, reference_config: dict[str, Any], candidate_config: dict[str, Any]):
    reference, ref_thread = start_service(cart_id=f"reference-{case_id}", **reference_config)
    candidate, cand_thread = start_service(cart_id=f"candidate-{case_id}", **candidate_config)
    return reference, ref_thread, candidate, cand_thread


def _close_pair(reference: Any, ref_thread: Any, candidate: Any, cand_thread: Any) -> None:
    for server in (reference, candidate):
        server.shutdown()
        server.server_close()
    ref_thread.join(timeout=2)
    cand_thread.join(timeout=2)


def _run_case(
    case: dict[str, Any],
    manifest: dict[str, Any],
    output_dir: Path,
    sequence_validator: Draft202012Validator,
    contract_validator: Draft202012Validator,
    report_validator: Draft202012Validator,
    pack_validator: Draft202012Validator,
) -> dict[str, Any]:
    sequence, sequence_hash, contract, reset, reset_hash = _sequence_and_contract(
        case, sequence_validator, contract_validator
    )
    reference, ref_thread, candidate, cand_thread = _start_pair(
        case["id"], case.get("reference", {}), case.get("candidate", {})
    )
    headers = tuple((entry[0], entry[1]) for entry in case.get("request_headers", []))
    expected = case["expected"]
    record: dict[str, Any] = {"id": case["id"], "mode": case["mode"], "expected_outcome": expected["outcome"]}
    try:
        base_options = {
            "reference_url": f"http://127.0.0.1:{reference.server_port}",
            "candidate_url": f"http://127.0.0.1:{candidate.server_port}",
            "sequence": sequence,
            "sequence_sha256": sequence_hash,
            "timeout": manifest["timeout_seconds"],
            "repeat": manifest["repeat"],
            "max_output_bytes": manifest["max_output_bytes"],
            "request_headers": headers,
            "contract": contract,
            "reset_sequence": reset,
            "reset_sequence_sha256": reset_hash,
        }
        if case["mode"] == "reset_guard":
            try:
                run_http_sequence_comparison(**base_options)
            except ValueError as exc:
                error_text = str(exc)
            else:
                raise CorpusFailure(f"{case['id']}: expected a reset-health guard failure")
            if expected["guard_error_contains"] not in error_text:
                raise CorpusFailure(f"{case['id']}: reset guard error did not contain expected text: {error_text}")
            if reference.tested_workflow_requests != expected.get("workflow_requests", 0):
                raise CorpusFailure(f"{case['id']}: reference workflow executed before the reset guard")
            if candidate.tested_workflow_requests != expected.get("workflow_requests", 0):
                raise CorpusFailure(f"{case['id']}: candidate workflow executed before the reset guard")
            record.update({
                "outcome": "reset_guard",
                "guard_error": error_text,
                "tested_workflow_requests": {
                    "reference": reference.tested_workflow_requests,
                    "candidate": candidate.tested_workflow_requests,
                },
            })
            _write_json(output_dir / "cases" / f"{case['id']}.json", record)
            return record

        if case["mode"] == "explore":
            exploration = case.get("exploration", {})
            report = run_http_sequence_exploration(
                **base_options,
                seed=manifest["seed"],
                max_cases=exploration.get("cases", 12),
                minimize=exploration.get("minimize", True),
                max_findings_to_minimize=1,
                max_minimization_trials=exploration.get("minimization_trials", 24),
            )
        else:
            report = run_http_sequence_comparison(**base_options)

        _validate(report_validator, report, f"generated report {case['id']}")
        report_path = output_dir / "reports" / f"{case['id']}.json"
        _write_json(report_path, report)
        outcome = expected["outcome"]
        if outcome == "pass":
            if report["summary"]["differences_found"] != 0 or report["findings"]:
                raise CorpusFailure(f"{case['id']}: expected a clean pass, got {report['summary']['differences_found']} differences")
            record.update({"outcome": "pass", "differences_found": 0})
        else:
            detail = _verify_finding(report, expected, case["id"])
            if report["summary"]["differences_found"] < 1:
                raise CorpusFailure(f"{case['id']}: expected at least one reported difference")
            record.update({"outcome": outcome, "finding": detail, "differences_found": report["summary"]["differences_found"]})
            if outcome == "minimized_finding":
                target = next((finding for finding in report["findings"]
                               if finding.get("minimized") and _find_step({"findings": [finding]}, expected["step_name"])), None)
                if target is None:
                    raise CorpusFailure(f"{case['id']}: expected the seeded finding to be minimized")
                steps_after = len(target.get("sequence_definition", {}).get("steps", []))
                minimum = expected.get("maximum_steps_after_minimization", 1)
                if steps_after > minimum or steps_after >= len(sequence["steps"]):
                    raise CorpusFailure(f"{case['id']}: minimization kept {steps_after} steps; expected at most {minimum}")
                record["minimization"] = {
                    "minimized": True,
                    "step_count_before": len(sequence["steps"]),
                    "step_count_after": steps_after,
                    "target_step": expected["step_name"],
                    "mismatch_preserved": True,
                }
                _write_json(output_dir / "minimized" / f"{case['id']}.json", {
                    "sequence": target["sequence_definition"],
                    "sequence_canonical_sha256": target.get("sequence_canonical_sha256"),
                    "minimization": record["minimization"],
                    "finding": detail,
                })

            if case["id"] == "idempotency-retry":
                serialized_report = report_path.read_text(encoding="utf-8")
                key_value = dict(case.get("request_headers", [])).get("Idempotency-Key", "")
                if key_value and key_value in serialized_report:
                    raise CorpusFailure("idempotency-retry: request header value leaked into the evidence report")

            if case["id"] == "cart-value-drift":
                pack_path = output_dir / "packs" / "cart-value-drift"
                pack = export_stateful_sequence_pack(report_path, pack_path)
                _validate(pack_validator, pack, "exported stateful pack manifest")
                packed_sequence, packed_hash, packed_reset, packed_reset_hash, packed_contract, loaded_manifest = load_stateful_sequence_pack(pack_path)
                replay = run_http_sequence_comparison(
                    reference_url=base_options["reference_url"],
                    candidate_url=base_options["candidate_url"],
                    sequence=packed_sequence,
                    sequence_sha256=packed_hash,
                    timeout=manifest["timeout_seconds"],
                    repeat=manifest["repeat"],
                    max_output_bytes=manifest["max_output_bytes"],
                    request_headers=headers,
                    contract=packed_contract,
                    reset_sequence=packed_reset,
                    reset_sequence_sha256=packed_reset_hash,
                )
                _validate(report_validator, replay, "replayed regression report")
                replay_path = output_dir / "reports" / "cart-value-drift-replay.json"
                _write_json(replay_path, replay)
                replay_detail = _verify_finding(replay, expected, "cart-value-drift replay")
                record["pack_replay"] = {
                    "pack_schema_version": loaded_manifest["schema_version"],
                    "pack_manifest_valid": True,
                    "tamper_detection": "pending",
                    "replay_reproduced": True,
                    "replay_finding": replay_detail,
                }
                tampered_path = output_dir / "packs" / "cart-value-drift-tampered"
                shutil.copytree(pack_path, tampered_path)
                sequence_file = tampered_path / "sequence.json"
                sequence_file.write_text(sequence_file.read_text(encoding="utf-8") + " ", encoding="utf-8")
                try:
                    load_stateful_sequence_pack(tampered_path)
                except ValueError:
                    record["pack_replay"]["tamper_detection"] = "passed"
                else:
                    raise CorpusFailure("cart-value-drift: tampered pack was not rejected")
                if record["pack_replay"]["tamper_detection"] != "passed":
                    raise CorpusFailure("cart-value-drift: pack tamper detection did not pass")
                record["pack_replay"]["pack_schema"] = "docs/stateful-regression-pack-v1.schema.json"
        _write_json(output_dir / "cases" / f"{case['id']}.json", record)
        return record
    finally:
        _close_pair(reference, ref_thread, candidate, cand_thread)


def verify(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_schema = _schema(ROOT / "benchmarks" / "stateful-corpus-v2.schema.json")
    manifest_validator = Draft202012Validator(manifest_schema)
    manifest = _json(MANIFEST_PATH)
    _validate(manifest_validator, manifest, "stateful corpus manifest")
    _check_fixture_hashes(manifest)

    sequence_validator, contract_validator, report_validator, pack_validator = _validate_checked_in_schemas(
        manifest_validator
    )
    # Explicitly prove the corpus manifest schema rejects malformed version metadata.
    malformed_manifest = dict(manifest)
    malformed_manifest["schema_version"] = 999
    try:
        _validate(manifest_validator, malformed_manifest, "intentionally malformed manifest")
    except CorpusFailure:
        pass
    else:
        raise CorpusFailure("manifest schema accepted an unsupported schema_version")

    records = []
    for case in manifest["cases"]:
        print(f"[RUN] {case['id']}")
        record = _run_case(
            case, manifest, output_dir, sequence_validator, contract_validator, report_validator, pack_validator
        )
        records.append(record)
        print(f"[PASS] {case['id']}: {record['outcome']}")

    summary = {
        "schema_version": 1,
        "corpus": manifest["name"],
        "corpus_schema_version": manifest["schema_version"],
        "fixture_hashes": manifest["fixture_hashes"],
        "settings": {
            "seed": manifest["seed"],
            "repeat": manifest["repeat"],
            "timeout_seconds": manifest["timeout_seconds"],
            "max_output_bytes": manifest["max_output_bytes"],
        },
        "all_cases_passed": True,
        "case_count": len(records),
        "cases": records,
        "known_blind_spots": manifest["known_blind_spots"],
    }
    _write_json(output_dir / "summary.json", summary)
    print(f"\nVerified {len(records)} corpus cases. Evidence directory: {output_dir}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="reports/stateful-corpus-v2",
        help="new directory for synthetic reports and packs (must not already exist)",
    )
    args = parser.parse_args(argv)
    try:
        verify(Path(args.output_dir).resolve())
    except (CorpusFailure, OSError, ValueError, ValidationError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
