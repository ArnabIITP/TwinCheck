"""Portable stateful HTTP sequence regression packs.

Packs contain request and optional reset definitions plus a pinned semantic contract.
Response traces and request-header values are deliberately excluded.
"""
from __future__ import annotations
import hashlib, json, re, shutil, tempfile
from pathlib import Path
from typing import Any
from .contract import CompatibilityContract, contract_from_dict
from .stateful_http import validate_sequence

PACK_SCHEMA_VERSION = 1
_MAX_REPORT_BYTES = 50 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_SEQUENCE_BYTES = 5 * 1024 * 1024
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def _read_json(path: Path, *, limit: int, label: str) -> tuple[Any, bytes]:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError(f"{label} exceeds {limit // (1024 * 1024)} MiB")
    try:
        def reject_constant(item: str) -> None:
            raise ValueError(f"non-standard JSON constant {item!r}")
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError(f"{label} JSON is nested too deeply") from exc
    return value, raw

def export_stateful_sequence_pack(report_path: str | Path, output_dir: str | Path, *, finding_number: int = 1) -> dict[str, Any]:
    """Package one stateful HTTP finding without copying response observations."""
    if type(finding_number) is not int or finding_number < 1:
        raise ValueError("finding number must be a positive integer")
    report, report_bytes = _read_json(Path(report_path), limit=_MAX_REPORT_BYTES, label="source report")
    if not isinstance(report, dict) or report.get("input_source") not in {"stateful-http-sequence", "stateful-http-exploration"}:
        raise ValueError("source report is not a TwinCheck stateful HTTP sequence or exploration report")
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ValueError("source report contains no stateful sequence findings to export")
    if finding_number > len(findings):
        raise ValueError(f"finding number must be between 1 and {len(findings)}")
    finding = findings[finding_number - 1]
    if not isinstance(finding, dict):
        raise ValueError("selected finding is malformed")
    sequence = finding.get("sequence_definition")
    validate_sequence(sequence)
    source_sequence_hash = finding.get("sequence_file_sha256")
    if not isinstance(source_sequence_hash, str) or not _SHA256_RE.fullmatch(source_sequence_hash):
        raise ValueError("selected finding does not contain a valid source sequence SHA-256")
    canonical_hash = _sha256(_canonical_bytes(sequence))
    if finding.get("sequence_canonical_sha256") != canonical_hash:
        raise ValueError("saved stateful sequence does not match its canonical SHA-256; report may have been modified")
    raw_contract = report.get("compatibility_contract")
    if not isinstance(raw_contract, dict):
        raise ValueError("source report does not contain a compatibility contract")
    contract = contract_from_dict(raw_contract)
    if report.get("compatibility_contract_sha256") != contract.sha256:
        raise ValueError("source compatibility-contract hash does not match the report")
    differences = finding.get("differences", [])
    if not isinstance(differences, list) or any(not isinstance(item, str) for item in differences):
        raise ValueError("selected finding differences must be an array of strings")
    sequence_bytes = (json.dumps(sequence, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(sequence_bytes) > _MAX_SEQUENCE_BYTES:
        raise ValueError("selected sequence exceeds 5 MiB and cannot be packed")
    reset_meta = report.get("state_reset", {})
    if not isinstance(reset_meta, dict) or type(reset_meta.get("enabled")) is not bool:
        raise ValueError("source report state_reset metadata is malformed")
    reset_sequence = reset_bytes = reset_source_hash = reset_canonical_hash = None
    if reset_meta["enabled"]:
        reset_sequence = reset_meta.get("sequence_definition")
        validate_sequence(reset_sequence)
        reset_canonical_hash = _sha256(_canonical_bytes(reset_sequence))
        if reset_meta.get("canonical_sha256") != reset_canonical_hash:
            raise ValueError("saved reset sequence canonical SHA-256 does not match; report may have been modified")
        reset_source_hash = reset_meta.get("sequence_sha256")
        if not isinstance(reset_source_hash, str) or not _SHA256_RE.fullmatch(reset_source_hash):
            raise ValueError("source reset sequence does not contain a valid SHA-256")
        reset_bytes = (json.dumps(reset_sequence, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(reset_bytes) > _MAX_SEQUENCE_BYTES:
            raise ValueError("reset sequence exceeds 5 MiB and cannot be packed")
    elif any(reset_meta.get(k) is not None for k in ("sequence_definition", "sequence_sha256", "canonical_sha256")):
        raise ValueError("reset sequence metadata is present although reset is disabled")
    destination = Path(output_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing pack destination: {destination}")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        (staging / "sequence.json").write_bytes(sequence_bytes)
        contract_bytes = (json.dumps(contract.to_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (staging / "contract.json").write_bytes(contract_bytes)
        manifest: dict[str, Any] = {
            "schema_version": PACK_SCHEMA_VERSION, "tool": "TwinCheck", "pack_type": "stateful-http-regression-pack",
            "source_tool_version": report.get("tool_version", "unknown"), "source_report_sha256": _sha256(report_bytes),
            "source_input_source": report["input_source"], "source_finding_number": finding_number,
            "source_differences": differences, "sequence_file": "sequence.json",
            "sequence_file_sha256": _sha256(sequence_bytes), "sequence_source_sha256": source_sequence_hash,
            "sequence_canonical_sha256": canonical_hash, "contract_file": "contract.json",
            "contract_sha256": contract.sha256, "reset_enabled": reset_bytes is not None,
        }
        if reset_bytes is not None:
            (staging / "reset-sequence.json").write_bytes(reset_bytes)
            manifest.update({"reset_sequence_file": "reset-sequence.json", "reset_sequence_file_sha256": _sha256(reset_bytes),
                             "reset_sequence_source_sha256": reset_source_hash, "reset_sequence_canonical_sha256": reset_canonical_hash})
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        staging.rename(destination)
        return manifest
    finally:
        if staging.exists(): shutil.rmtree(staging, ignore_errors=True)

def load_stateful_sequence_pack(pack_dir: str | Path) -> tuple[dict[str, Any], str, dict[str, Any] | None, str | None, CompatibilityContract, dict[str, Any]]:
    """Integrity-check and load a stateful regression pack."""
    root = Path(pack_dir)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"pack path must be an existing directory: {root}")
    value, _ = _read_json(root / "manifest.json", limit=_MAX_MANIFEST_BYTES, label="pack manifest")
    if not isinstance(value, dict): raise ValueError("pack manifest must be a JSON object")
    m = value
    required = {"schema_version", "tool", "pack_type", "source_tool_version", "source_report_sha256", "source_input_source",
                "source_finding_number", "source_differences", "sequence_file", "sequence_file_sha256", "sequence_source_sha256",
                "sequence_canonical_sha256", "contract_file", "contract_sha256", "reset_enabled"}
    reset_keys = {"reset_sequence_file", "reset_sequence_file_sha256", "reset_sequence_source_sha256", "reset_sequence_canonical_sha256"}
    if type(m.get("schema_version")) is not int or m.get("schema_version") != 1:
        raise ValueError(f"unsupported pack schema_version {m.get('schema_version')!r}")
    if m.get("tool") != "TwinCheck" or m.get("pack_type") != "stateful-http-regression-pack":
        raise ValueError("directory is not a TwinCheck stateful HTTP regression pack")
    if not required.issubset(m): raise ValueError("pack manifest is missing required fields")
    unknown = set(m) - required - reset_keys
    if unknown: raise ValueError(f"pack manifest has unknown field(s): {', '.join(sorted(unknown))}")
    if m.get("source_input_source") not in {"stateful-http-sequence", "stateful-http-exploration"}:
        raise ValueError("pack source_input_source is invalid")
    if not isinstance(m.get("source_tool_version"), str): raise ValueError("pack source_tool_version must be a string")
    if type(m.get("source_finding_number")) is not int or m["source_finding_number"] < 1:
        raise ValueError("pack source_finding_number must be a positive integer")
    if not isinstance(m.get("source_differences"), list) or any(not isinstance(i, str) for i in m["source_differences"]):
        raise ValueError("pack source_differences must be an array of strings")
    for key in ("source_report_sha256", "sequence_file_sha256", "sequence_source_sha256", "sequence_canonical_sha256", "contract_sha256"):
        if not isinstance(m.get(key), str) or not _SHA256_RE.fullmatch(m[key]): raise ValueError(f"pack {key} is not a valid SHA-256 digest")
    if m.get("sequence_file") != "sequence.json" or m.get("contract_file") != "contract.json":
        raise ValueError("pack has an unexpected sequence or contract file path")
    seq, seq_bytes = _read_json(root / "sequence.json", limit=_MAX_SEQUENCE_BYTES, label="sequence file")
    if m.get("sequence_file_sha256") != _sha256(seq_bytes): raise ValueError("pack sequence file SHA-256 verification failed")
    validate_sequence(seq)
    if m.get("sequence_canonical_sha256") != _sha256(_canonical_bytes(seq)):
        raise ValueError("pack sequence canonical SHA-256 verification failed")
    contract_value, _ = _read_json(root / "contract.json", limit=1024 * 1024, label="contract file")
    if not isinstance(contract_value, dict): raise ValueError("pack contract must be a JSON object")
    contract = contract_from_dict(contract_value)
    if m.get("contract_sha256") != contract.sha256: raise ValueError("pack contract SHA-256 verification failed")
    reset = reset_file_hash = reset_source_hash = None
    if m.get("reset_enabled") is True:
        if not reset_keys.issubset(m): raise ValueError("pack manifest is missing reset-sequence integrity fields")
        if m.get("reset_sequence_file") != "reset-sequence.json": raise ValueError("pack reset sequence file path is invalid")
        for key in ("reset_sequence_file_sha256", "reset_sequence_source_sha256", "reset_sequence_canonical_sha256"):
            if not isinstance(m.get(key), str) or not _SHA256_RE.fullmatch(m[key]): raise ValueError(f"pack {key} is not a valid SHA-256 digest")
        reset, reset_bytes = _read_json(root / "reset-sequence.json", limit=_MAX_SEQUENCE_BYTES, label="reset sequence file")
        if m.get("reset_sequence_file_sha256") != _sha256(reset_bytes): raise ValueError("pack reset sequence file SHA-256 verification failed")
        validate_sequence(reset)
        if m.get("reset_sequence_canonical_sha256") != _sha256(_canonical_bytes(reset)):
            raise ValueError("pack reset sequence canonical SHA-256 verification failed")
        reset_source_hash = m["reset_sequence_source_sha256"]
        reset_file_hash = _sha256(reset_bytes)
    elif m.get("reset_enabled") is False:
        if reset_keys.intersection(m): raise ValueError("pack includes reset metadata although reset_enabled is false")
        if (root / "reset-sequence.json").exists() or (root / "reset-sequence.json").is_symlink():
            raise ValueError("pack contains a reset sequence although reset_enabled is false")
    else:
        raise ValueError("pack reset_enabled must be boolean")
    return seq, _sha256(seq_bytes), reset, reset_file_hash, contract, m
