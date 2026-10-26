"""Versioned compatibility contracts for observable process behavior.

Contracts let a team define which output fields belong to the compatibility
surface. They deliberately stay declarative: loading a contract never imports
user code or executes commands.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_SCHEMA_VERSION = 1
_MAX_CONTRACT_BYTES = 1 * 1024 * 1024
_POINTER_ESCAPE_RE = re.compile(r"~(?![01])")


@dataclass(frozen=True)
class OutputContract:
    """Comparison mode for one output stream."""

    mode: str = "exact"
    ignore_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "ignore_paths": list(self.ignore_paths)}


@dataclass(frozen=True)
class CompatibilityContract:
    """Declarative rules for behavioral compatibility between two programs."""

    name: str = "default"
    stdout: OutputContract = OutputContract()
    stderr: OutputContract = OutputContract()
    compare_exit_code: bool = True
    compare_timeout: bool = True
    schema_version: int = CONTRACT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "stdout": self.stdout.to_dict(),
            "stderr": self.stderr.to_dict(),
            "compare_exit_code": self.compare_exit_code,
            "compare_timeout": self.compare_timeout,
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _output_rule(value: Any, label: str) -> OutputContract:
    if not isinstance(value, dict):
        raise ValueError(f"contract field {label!r} must be an object")
    unknown = set(value) - {"mode", "ignore_paths"}
    if unknown:
        raise ValueError(f"unknown key(s) in {label}: {', '.join(sorted(unknown))}")
    mode = value.get("mode", "exact")
    if not isinstance(mode, str) or mode not in {"exact", "json"}:
        raise ValueError(f"{label}.mode must be 'exact' or 'json'")
    raw_paths = value.get("ignore_paths", [])
    if not isinstance(raw_paths, list) or any(not isinstance(path, str) for path in raw_paths):
        raise ValueError(f"{label}.ignore_paths must be an array of JSON Pointer strings")
    paths = tuple(raw_paths)
    if paths and mode != "json":
        raise ValueError(f"{label}.ignore_paths is only valid when mode is 'json'")
    for path in paths:
        if not path.startswith("/"):
            raise ValueError(f"{label} path {path!r} must be a non-root JSON Pointer beginning with '/'")
        if _POINTER_ESCAPE_RE.search(path):
            raise ValueError(f"{label} path {path!r} contains an invalid JSON Pointer escape")
    if len(paths) != len(set(paths)):
        raise ValueError(f"{label}.ignore_paths must not contain duplicates")
    return OutputContract(mode=mode, ignore_paths=paths)


def contract_from_dict(data: Any) -> CompatibilityContract:
    """Validate and parse an already-decoded contract object."""
    if not isinstance(data, dict):
        raise ValueError("compatibility contract must be a JSON object")
    allowed = {"schema_version", "name", "stdout", "stderr", "compare_exit_code", "compare_timeout"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown contract key(s): {', '.join(sorted(unknown))}")
    version = data.get("schema_version", CONTRACT_SCHEMA_VERSION)
    if type(version) is not int or version != CONTRACT_SCHEMA_VERSION:
        raise ValueError(f"unsupported contract schema_version {version!r}; expected {CONTRACT_SCHEMA_VERSION}")
    name = data.get("name", "unnamed")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("contract name must be a non-empty string")
    compare_exit_code = data.get("compare_exit_code", True)
    compare_timeout = data.get("compare_timeout", True)
    if not isinstance(compare_exit_code, bool):
        raise ValueError("compare_exit_code must be a boolean")
    if not isinstance(compare_timeout, bool):
        raise ValueError("compare_timeout must be a boolean")
    return CompatibilityContract(
        name=name.strip(),
        stdout=_output_rule(data.get("stdout", {}), "stdout"),
        stderr=_output_rule(data.get("stderr", {}), "stderr"),
        compare_exit_code=compare_exit_code,
        compare_timeout=compare_timeout,
        schema_version=version,
    )


def load_contract(path: str | Path) -> CompatibilityContract:
    """Load a bounded, local JSON contract file."""
    contract_path = Path(path)
    if contract_path.stat().st_size > _MAX_CONTRACT_BYTES:
        raise ValueError("compatibility contract exceeds 1 MiB")
    try:
        content = contract_path.read_text(encoding="utf-8")
        decoded = json.loads(content)
    except UnicodeDecodeError as exc:
        raise ValueError("compatibility contract must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid compatibility contract JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError("compatibility contract JSON is nested too deeply") from exc
    return contract_from_dict(decoded)


def _decode_pointer_segment(segment: str) -> str:
    # RFC 6901 decoding order matters: ~1 first, then ~0.
    return segment.replace("~1", "/").replace("~0", "~")


def _array_index(segment: str) -> int | None:
    if segment == "0":
        return 0
    if not segment or segment.startswith("0") or not segment.isascii() or not segment.isdigit():
        return None
    return int(segment)


def _redact_pointer(document: Any, pointer: str) -> None:
    """Remove an object key or replace an array item without shifting indices.

    Missing paths and paths whose parent type does not match are no-ops. That
    allows one contract to span compatible API versions where a volatile field
    may not exist in every response.
    """
    segments = [_decode_pointer_segment(item) for item in pointer[1:].split("/")]
    parent = document
    for segment in segments[:-1]:
        if isinstance(parent, dict):
            if segment not in parent:
                return
            parent = parent[segment]
        elif isinstance(parent, list):
            index = _array_index(segment)
            if index is None or index >= len(parent):
                return
            parent = parent[index]
        else:
            return
    leaf = segments[-1]
    if isinstance(parent, dict):
        parent.pop(leaf, None)
    elif isinstance(parent, list):
        index = _array_index(leaf)
        if index is not None and index < len(parent):
            # A private object sentinel cannot collide with any parsed JSON value.
            parent[index] = _IGNORED_ARRAY_VALUE


_IGNORED_ARRAY_VALUE = object()


def _freeze_json(value: Any) -> Any:
    """Convert a parsed JSON value into a hashable, order-stable signature."""
    if value is _IGNORED_ARRAY_VALUE:
        return ("ignored-array-value",)
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, Decimal):
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        while len(digits) > 1 and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if not any(digits):
            sign, digits, exponent = 0, [0], 0
        return ("number", sign, tuple(digits), exponent)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_freeze_json(item) for item in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((key, _freeze_json(item)) for key, item in value.items())))
    # json.loads is expected to produce only the types handled above.
    raise TypeError(f"unsupported parsed JSON value: {type(value).__name__}")


def json_output_signature(text: str, rule: OutputContract) -> tuple[str, Any]:
    """Return a semantic, hashable signature for JSON output or invalid marker.

    Object key ordering is ignored and JSON integer/decimal numbers compare by
    numeric value. Invalid JSON is never treated as equivalent, even if both
    targets emit the same malformed string.
    """
    def reject_nonstandard_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON number {value}")

    try:
        parsed = json.loads(
            text,
            parse_constant=reject_nonstandard_constant,
            parse_int=Decimal,
            parse_float=Decimal,
        )
    except (json.JSONDecodeError, ValueError, InvalidOperation, RecursionError):
        return "invalid_json", text
    for pointer in rule.ignore_paths:
        _redact_pointer(parsed, pointer)
    return "json", _freeze_json(parsed)
