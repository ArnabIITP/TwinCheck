#!/usr/bin/env python3
"""Verify the pinned second-domain booking API compatibility corpus."""
from __future__ import annotations
import argparse, hashlib, json, sys, threading, time
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "exploration-corpus-v2"
MANIFEST = CORPUS / "manifest.json"
SCHEMA = ROOT / "benchmarks" / "exploration-corpus-v2.schema.json"
sys.path.insert(0, str(CORPUS))
from service import start_service
from twincheck.contract import load_contract
from twincheck.stateful_http import load_sequence, run_http_sequence_comparison

class CorpusError(RuntimeError):
    pass

def read_json(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CorpusError(f"cannot read {path}: {exc}") from exc

def normalized_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()

def checked_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or path.is_symlink():
        raise CorpusError(f"invalid or missing pinned path: {relative}")
    return path

def stop_pair(ref, ref_thread, cand, cand_thread) -> None:
    stoppers = [threading.Thread(target=s.shutdown, daemon=True) for s in (ref, cand)]
    for item in stoppers: item.start()
    for item in stoppers: item.join(timeout=2)
    for item in (ref, cand): item.server_close()
    ref_thread.join(timeout=2); cand_thread.join(timeout=2)

def run_case(case: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    seq_path = checked_path("benchmarks/exploration-corpus-v2/" + case["sequence"])
    reset_path = checked_path("benchmarks/exploration-corpus-v2/" + case["reset_sequence"])
    contract_path = checked_path("benchmarks/exploration-corpus-v2/" + case["contract"])
    sequence, seq_hash = load_sequence(seq_path)
    reset, reset_hash = load_sequence(reset_path)
    contract = load_contract(contract_path)
    ref, rt = start_service(service_id=f"ref-{case['id']}", **case["reference"])
    cand, ct = start_service(service_id=f"cand-{case['id']}", **case["candidate"])
    started = time.perf_counter()
    try:
        report = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{ref.server_port}",
            candidate_url=f"http://127.0.0.1:{cand.server_port}",
            sequence=sequence, sequence_sha256=seq_hash,
            reset_sequence=reset, reset_sequence_sha256=reset_hash,
            timeout=manifest["timeout_seconds"], repeat=manifest["repeat"],
            max_output_bytes=manifest["max_output_bytes"], contract=contract,
        )
    finally:
        stop_pair(ref, rt, cand, ct)
    finding = report["summary"]["differences_found"] > 0
    return {
        "case_id": case["id"], "expected_finding": case["expected_finding"],
        "observed_finding": finding, "passed": finding is case["expected_finding"],
        "differences_found": report["summary"]["differences_found"],
        "steps_with_differences": report["summary"]["steps_with_differences"],
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "sequence_sha256": seq_hash, "reset_sequence_sha256": reset_hash,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write evidence JSON to this path")
    args = parser.parse_args()
    try:
        manifest = read_json(MANIFEST)
        schema = read_json(SCHEMA)
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(manifest))
        if errors: raise CorpusError(f"manifest schema error: {errors[0].message}")
        pins = manifest["fixture_hashes"]
        required = {
            "benchmarks/exploration-corpus-v2.schema.json",
            "benchmarks/exploration-corpus-v2/service.py",
            "benchmarks/exploration-corpus-v2/sequences/booking-session-reserve-read-v1.json",
            "benchmarks/exploration-corpus-v2/sequences/reset-v1.json",
            "benchmarks/exploration-corpus-v2/contracts/booking-compatibility-v1.json",
            "docs/stateful-http-sequence-v1.schema.json",
            "docs/compatibility-contract-v1.schema.json",
            "benchmarks/run_multi_domain_protocol.py",
        }
        if not required.issubset(pins): raise CorpusError("manifest omits required SHA-256 pins")
        drift = []
        for relative, expected in sorted(pins.items()):
            path = checked_path(relative)
            actual = normalized_sha(path)
            if actual != expected: drift.append(f"{relative}: expected Git blob SHA {expected}, got {actual}")
        if drift: raise CorpusError("fixture hash mismatch:\n  " + "\n  ".join(drift))
        sequence_schema = Draft202012Validator(read_json(ROOT / "docs/stateful-http-sequence-v1.schema.json"))
        contract_schema = Draft202012Validator(read_json(ROOT / "docs/compatibility-contract-v1.schema.json"))
        results = []
        for case in manifest["cases"]:
            seq = read_json(checked_path("benchmarks/exploration-corpus-v2/" + case["sequence"]))
            reset = read_json(checked_path("benchmarks/exploration-corpus-v2/" + case["reset_sequence"]))
            contract = read_json(checked_path("benchmarks/exploration-corpus-v2/" + case["contract"]))
            for label, validator, value in (("sequence", sequence_schema, seq), ("reset sequence", sequence_schema, reset), ("contract", contract_schema, contract)):
                errors = list(validator.iter_errors(value))
                if errors: raise CorpusError(f"{case['id']} {label} schema error: {errors[0].message}")
            results.append(run_case(case, manifest))
        tp = sum(x["expected_finding"] and x["observed_finding"] for x in results)
        fp = sum((not x["expected_finding"]) and x["observed_finding"] for x in results)
        tn = sum((not x["expected_finding"]) and (not x["observed_finding"]) for x in results)
        fn = sum(x["expected_finding"] and (not x["observed_finding"]) for x in results)
        passed = all(x["passed"] for x in results) and fp == 0
        evidence = {
            "schema_version": 1, "protocol": "TwinCheck second-domain booking corpus v1",
            "passed": passed, "scope": "small synthetic booking API only; not a real-world effectiveness estimate",
            "fixture_git_blob_sha1": pins, "results": results,
            "metrics": {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn,
                "detection_rate": tp / (tp + fn) if tp + fn else None,
                "false_positive_rate": fp / (fp + tn) if fp + tn else None,
                "precision": tp / (tp + fp) if tp + fp else None},
            "limitations": manifest["limitations"],
        }
        rendered = json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            destination = Path(args.output); destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, TypeError, CorpusError) as exc:
        print(f"[FAIL] multi-domain corpus: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
