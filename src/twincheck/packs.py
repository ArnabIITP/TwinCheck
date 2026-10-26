"""Portable counterexample packs pinned to the contract that found them."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .contract import CompatibilityContract, contract_from_dict, load_contract

PACK_SCHEMA_VERSION = 1
_MAX_REPORT_BYTES = 50 * 1024 * 1024
_MAX_MANIFEST_BYTES = 5 * 1024 * 1024
_MAX_CASE_BYTES = 10 * 1024 * 1024
_MAX_PACK_CASE_BYTES = 50 * 1024 * 1024
_CASE_FILE_RE = re.compile(r"^cases/([a-f0-9]{64})\.txt$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json_object(path: Path, *, limit: int, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"{label} exceeds {limit // (1024 * 1024)} MiB")
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError(f"{label} exceeds {limit // (1024 * 1024)} MiB")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError(f"{label} JSON is nested too deeply") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed, data


def export_cases_from_report(report_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Export report findings as exact UTF-8 files plus a pinned contract.

    The destination must not already exist; exporting never overwrites a user's
    existing corpus. Duplicate input strings are stored once and retain all
    source finding numbers in the manifest.
    """
    report_file = Path(report_path)
    report, report_bytes = _read_json_object(report_file, limit=_MAX_REPORT_BYTES, label="source report")
    raw_findings = report.get("findings")
    if not isinstance(raw_findings, list) or not raw_findings:
        raise ValueError("source report contains no findings to export")

    raw_contract = report.get("compatibility_contract", CompatibilityContract().to_dict())
    contract = contract_from_dict(raw_contract)
    reported_contract_hash = report.get("compatibility_contract_sha256")
    if reported_contract_hash is not None and reported_contract_hash != contract.sha256:
        raise ValueError("source report compatibility-contract hash does not match its embedded contract")

    cases: dict[str, dict[str, Any]] = {}
    total_unique_case_bytes = 0
    for finding_number, finding in enumerate(raw_findings, start=1):
        if not isinstance(finding, dict) or not isinstance(finding.get("input"), str):
            raise ValueError(f"finding {finding_number} has no text input")
        input_bytes = finding["input"].encode("utf-8")
        if len(input_bytes) > _MAX_CASE_BYTES:
            raise ValueError(f"finding {finding_number} input exceeds 10 MiB and cannot be packed")
        digest = _sha256(input_bytes)
        declared_digest = finding.get("input_sha256")
        if declared_digest is not None and declared_digest != digest:
            raise ValueError(f"finding {finding_number} input SHA-256 does not match its input")
        if digest not in cases:
            cases[digest] = {
                "case_id": f"case-{len(cases) + 1:04d}-{digest[:12]}",
                "file": f"cases/{digest}.txt",
                "input_sha256": digest,
                "source_finding_numbers": [],
                "original_differences": [],
                "_input_bytes": input_bytes,
            }
            total_unique_case_bytes += len(input_bytes)
            if total_unique_case_bytes > _MAX_PACK_CASE_BYTES:
                raise ValueError("combined unique counterexample data exceeds 50 MiB")
        entry = cases[digest]
        entry["source_finding_numbers"].append(finding_number)
        for difference in finding.get("differences", []):
            if isinstance(difference, str) and difference not in entry["original_differences"]:
                entry["original_differences"].append(difference)

    destination = Path(output_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing pack destination: {destination}")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        (staging / "cases").mkdir()
        (staging / "contract.json").write_text(
            json.dumps(contract.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        manifest_cases = []
        for entry in cases.values():
            (staging / entry["file"]).write_bytes(entry.pop("_input_bytes"))
            manifest_cases.append(entry)
        manifest = {
            "schema_version": PACK_SCHEMA_VERSION,
            "tool": "TwinCheck",
            "pack_type": "counterexample-regression-pack",
            "source_tool_version": report.get("tool_version", "unknown"),
            "source_report_sha256": _sha256(report_bytes),
            "contract_file": "contract.json",
            "contract_sha256": contract.sha256,
            "case_count": len(manifest_cases),
            "cases": manifest_cases,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # Stage beside the destination and rename only after the complete pack
        # is valid, avoiding a half-written directory after a failed export.
        staging.rename(destination)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def load_compatibility_pack(pack_dir: str | Path) -> tuple[list[str], CompatibilityContract, dict[str, Any]]:
    """Validate a counterexample pack and return its exact inputs and contract."""
    root = Path(pack_dir)
    if not root.is_dir():
        raise ValueError(f"pack path must be an existing directory: {root}")
    manifest, _ = _read_json_object(root / "manifest.json", limit=_MAX_MANIFEST_BYTES, label="pack manifest")
    if manifest.get("schema_version") != PACK_SCHEMA_VERSION or type(manifest.get("schema_version")) is not int:
        raise ValueError(f"unsupported pack schema_version {manifest.get('schema_version')!r}")
    if manifest.get("tool") != "TwinCheck" or manifest.get("pack_type") != "counterexample-regression-pack":
        raise ValueError("directory is not a TwinCheck counterexample regression pack")
    if manifest.get("contract_file") != "contract.json":
        raise ValueError("pack contract_file must be contract.json")
    if (root / "contract.json").is_symlink():
        raise ValueError("pack contract.json must not be a symbolic link")
    contract = load_contract(root / "contract.json")
    if manifest.get("contract_sha256") != contract.sha256:
        raise ValueError("pack contract SHA-256 does not match contract.json")

    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("pack manifest must contain at least one case")
    if type(manifest.get("case_count")) is not int or manifest.get("case_count") != len(raw_cases):
        raise ValueError("pack case_count does not match the manifest cases array")

    inputs: list[str] = []
    seen_hashes: set[str] = set()
    total_bytes = 0
    for index, case in enumerate(raw_cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"pack case {index} must be an object")
        relative_path = case.get("file")
        digest = case.get("input_sha256")
        if not isinstance(relative_path, str) or not (match := _CASE_FILE_RE.fullmatch(relative_path)):
            raise ValueError(f"pack case {index} has an unsafe or invalid file path")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest) or match.group(1) != digest:
            raise ValueError(f"pack case {index} has an invalid or inconsistent SHA-256")
        if digest in seen_hashes:
            raise ValueError(f"pack case {index} duplicates an earlier input hash")
        seen_hashes.add(digest)
        case_path = root / relative_path
        if case_path.is_symlink():
            raise ValueError(f"pack case {index} must not be a symbolic link")
        if case_path.stat().st_size > _MAX_CASE_BYTES:
            raise ValueError(f"pack case {index} exceeds 10 MiB")
        payload = case_path.read_bytes()
        if len(payload) > _MAX_CASE_BYTES:
            raise ValueError(f"pack case {index} exceeds 10 MiB")
        total_bytes += len(payload)
        if total_bytes > _MAX_PACK_CASE_BYTES:
            raise ValueError("combined pack case data exceeds 50 MiB")
        if _sha256(payload) != digest:
            raise ValueError(f"pack case {index} input SHA-256 verification failed")
        try:
            inputs.append(payload.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError(f"pack case {index} is not UTF-8 text") from exc
    return inputs, contract, manifest
