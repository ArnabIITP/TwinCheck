"""Stateful, multi-request HTTP compatibility workflows for local services."""

from __future__ import annotations

import hashlib
import json
import re
import time
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, build_opener

from . import __version__
from .compare import CompareOptions, _behavior_signature, difference_kinds
from .contract import CompatibilityContract, OutputContract
from .http_engine import (
    HttpTarget,
    _NoRedirectHandler,
    _read_response,
    parse_request_headers,
    validate_local_base_url,
)
from .report import REPORT_SCHEMA_VERSION
from .runner import Observation

_MAX_SEQUENCE_FILE_BYTES = 5 * 1024 * 1024
_MAX_SEQUENCE_STEPS = 25
_MAX_SEQUENCE_BODY_BYTES = 10 * 1024 * 1024
_MAX_SEQUENCE_REPEAT = 5
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEMPLATE_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_PLACEHOLDER_SENTINEL = "\u0000TWINCHECK_TEMPLATE_"


def load_sequence(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load a bounded stateful workflow JSON file and return its byte hash."""
    source_path = Path(path)
    raw = source_path.read_bytes()
    if len(raw) > _MAX_SEQUENCE_FILE_BYTES:
        raise ValueError("stateful sequence file exceeds 5 MiB")
    digest = hashlib.sha256(raw).hexdigest()
    def reject_nonstandard_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant {value!r}")

    try:
        decoded = json.loads(raw.decode("utf-8"), parse_constant=reject_nonstandard_constant)
    except UnicodeDecodeError as exc:
        raise ValueError("stateful sequence file must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid stateful sequence JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError("stateful sequence JSON is nested too deeply") from exc
    validate_sequence(decoded)
    return decoded, digest


def _validate_reset_health_contract(health: Any) -> None:
    """Validate a read-only, value-pinned post-reset state assertion contract."""
    if not isinstance(health, dict) or set(health) != {"schema_version", "method", "path", "assertions"}:
        raise ValueError("reset health contract must contain schema_version, method, path, and assertions")
    if type(health.get("schema_version")) is not int or health["schema_version"] != 1:
        raise ValueError("reset health schema_version must be integer 1")
    if health.get("method") != "GET":
        raise ValueError("reset health method must be GET so verification cannot mutate target state")
    path = health.get("path")
    if not isinstance(path, str) or _TEMPLATE_RE.search(path) or "{{" in path or "}}" in path:
        raise ValueError("reset health path must be a string without template expressions")
    _validate_request_path(path, index=0, allow_templates=False)
    assertions = health.get("assertions")
    if not isinstance(assertions, list) or not 1 <= len(assertions) <= 32:
        raise ValueError("reset health assertions must contain between 1 and 32 checks")
    seen_pointers: set[str] = set()
    for index, assertion in enumerate(assertions, start=1):
        if not isinstance(assertion, dict) or set(assertion) != {"pointer", "equals"}:
            raise ValueError(f"reset health assertion {index} must contain only pointer and equals")
        pointer = assertion.get("pointer")
        if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/" or re.search(r"~(?![01])", pointer):
            raise ValueError(f"reset health assertion {index} must use a valid non-root JSON Pointer")
        if pointer in seen_pointers:
            raise ValueError(f"duplicate reset health assertion pointer {pointer!r}")
        seen_pointers.add(pointer)
        expected = assertion.get("equals")
        if isinstance(expected, (dict, list)) or not (expected is None or type(expected) in {str, int, float, bool}):
            raise ValueError(f"reset health assertion {index} equals value must be a scalar JSON value")
        try:
            json.dumps(expected, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"reset health assertion {index} equals value must be valid JSON") from exc


def validate_sequence(sequence: Any) -> None:
    """Strictly validate a stateful HTTP workflow and its optional metadata."""
    if not isinstance(sequence, dict):
        raise ValueError("stateful sequence must be a JSON object")
    allowed_root = {"schema_version", "name", "steps", "health"}
    unknown = set(sequence) - allowed_root
    if unknown:
        raise ValueError(f"unknown stateful sequence key(s): {', '.join(sorted(unknown))}")
    version = sequence.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("stateful sequence schema_version must be integer 1")
    name = sequence.get("name", "unnamed-sequence")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("stateful sequence name must be a non-empty string of at most 120 characters")
    steps = sequence.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("stateful sequence must contain at least one step")
    if len(steps) > _MAX_SEQUENCE_STEPS:
        raise ValueError(f"stateful sequence may contain at most {_MAX_SEQUENCE_STEPS} steps")
    total_body_bytes = 0
    seen_step_names: set[str] = set()
    explicitly_named_steps: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"sequence step {index} must be an object")
        unknown_step_keys = set(step) - {"name", "method", "path", "body", "capture", "depends_on"}
        if unknown_step_keys:
            raise ValueError(f"unknown key(s) in sequence step {index}: {', '.join(sorted(unknown_step_keys))}")
        step_name = step.get("name", f"step-{index}")
        if not isinstance(step_name, str) or not step_name.strip() or len(step_name) > 120:
            raise ValueError(f"sequence step {index} name must be a non-empty string")
        if step_name in seen_step_names:
            raise ValueError(f"duplicate sequence step name {step_name!r}")
        dependencies = step.get("depends_on", [])
        if not isinstance(dependencies, list) or len(dependencies) > _MAX_SEQUENCE_STEPS:
            raise ValueError(f"sequence step {index} depends_on must be a bounded array of earlier step names")
        if any(not isinstance(dependency, str) for dependency in dependencies):
            raise ValueError(f"sequence step {index} has an invalid dependency name")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError(f"sequence step {index} depends_on contains duplicate names")
        for dependency in dependencies:
            if not dependency.strip() or len(dependency) > 120:
                raise ValueError(f"sequence step {index} has an invalid dependency name")
            if dependency not in seen_step_names or dependency not in explicitly_named_steps:
                raise ValueError(f"sequence step {index} dependency {dependency!r} must name an explicitly named earlier step")
        if "name" in step:
            explicitly_named_steps.add(step_name)
        seen_step_names.add(step_name)
        method = step.get("method")
        if not isinstance(method, str) or method.upper() not in _ALLOWED_METHODS:
            raise ValueError(f"sequence step {index} method must be one of {', '.join(sorted(_ALLOWED_METHODS))}")
        if not isinstance(step.get("path"), str):
            raise ValueError(f"sequence step {index} path must be a string")
        _validate_request_path(step["path"], index=index, allow_templates=True)
        if "body" in step:
            try:
                body_text = json.dumps(step["body"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError, RecursionError) as exc:
                raise ValueError(f"sequence step {index} body must be valid JSON data") from exc
            total_body_bytes += len(body_text.encode("utf-8"))
            if len(body_text.encode("utf-8")) > 1 * 1024 * 1024:
                raise ValueError(f"sequence step {index} body exceeds 1 MiB")
        captures = step.get("capture", {})
        if not isinstance(captures, dict):
            raise ValueError(f"sequence step {index} capture must be an object mapping names to JSON Pointers")
        for variable, pointer in captures.items():
            if not isinstance(variable, str) or not _NAME_RE.fullmatch(variable):
                raise ValueError(f"sequence step {index} has invalid capture variable name {variable!r}")
            if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
                raise ValueError(f"capture {variable!r} in step {index} must use a non-root JSON Pointer")
            if re.search(r"~(?![01])", pointer):
                raise ValueError(f"capture {variable!r} in step {index} has invalid JSON Pointer escaping")
    if total_body_bytes > _MAX_SEQUENCE_BODY_BYTES:
        raise ValueError("combined sequence request bodies exceed 10 MiB")
    if "health" in sequence:
        _validate_reset_health_contract(sequence["health"])


def _validate_request_path(path: str, *, index: int, allow_templates: bool) -> None:
    if not path.startswith("/") or path.startswith("//") or "#" in path:
        raise ValueError(f"sequence step {index} path must begin with one slash and must not contain a fragment")
    scrubbed = _TEMPLATE_RE.sub("placeholder", path) if allow_templates else path
    if any(ord(character) < 0x20 or character == " " for character in scrubbed):
        raise ValueError(f"sequence step {index} path must percent-encode spaces and contain no control characters")
    parsed = urlsplit(scrubbed)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"sequence step {index} path cannot contain a URL scheme or host")
    # Unclosed or malformed double-brace expressions are almost always typos.
    if "{{" in path or "}}" in path:
        if allow_templates and not _TEMPLATE_RE.search(path):
            raise ValueError(f"sequence step {index} path has an invalid template expression")


def _decode_pointer_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw_segment in pointer[1:].split("/"):
        segment = _decode_pointer_segment(raw_segment)
        if isinstance(current, dict):
            if segment not in current:
                raise ValueError("JSON Pointer path does not exist")
            current = current[segment]
        elif isinstance(current, list):
            if segment == "0":
                position = 0
            elif not segment or segment.startswith("0") or not segment.isascii() or not segment.isdigit():
                raise ValueError("JSON Pointer array index is invalid")
            else:
                position = int(segment)
            if position >= len(current):
                raise ValueError("JSON Pointer array index is out of range")
            current = current[position]
        else:
            raise ValueError("JSON Pointer traverses a scalar value")
    if isinstance(current, (dict, list)):
        raise ValueError("capture value must be a scalar JSON value")
    return current


def _render_value(value: Any, variables: Mapping[str, Any], *, encode_for_path: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _render_value(item, variables, encode_for_path=False) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_value(item, variables, encode_for_path=False) for item in value]
    if not isinstance(value, str):
        return value

    matches = list(_TEMPLATE_RE.finditer(value))
    if not matches:
        return value
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        variable = matches[0].group(1)
        if variable not in variables:
            raise ValueError(f"template variable {variable!r} has not been captured by an earlier step")
        captured = variables[variable]
        if encode_for_path:
            return quote(str(captured), safe="")
        return captured

    result = value
    # Replace from right to left so string offsets remain valid.
    for match in reversed(matches):
        variable = match.group(1)
        if variable not in variables:
            raise ValueError(f"template variable {variable!r} has not been captured by an earlier step")
        captured = variables[variable]
        if isinstance(captured, (dict, list)):
            raise ValueError(f"template variable {variable!r} is not scalar")
        replacement = str(captured)
        if encode_for_path:
            replacement = quote(replacement, safe="")
        result = result[:match.start()] + replacement + result[match.end():]
    return result


def _body_text(step: Mapping[str, Any], variables: Mapping[str, Any]) -> str | None:
    if "body" not in step:
        return None
    rendered = _render_value(step["body"], variables)
    try:
        return json.dumps(rendered, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"step {step.get('name', '<unnamed>')} rendered body is not valid JSON") from exc


def _safe_path(path: str) -> str:
    parsed = urlsplit(path)
    return parsed.path + ("?<query-redacted>" if parsed.query else "")


def _make_session_opener():
    # Cookie jars are deliberately separate for reference and candidate and reset
    # for each repeated sequence. Proxy environment variables and redirects stay off.
    return build_opener(ProxyHandler({}), _NoRedirectHandler(), HTTPCookieProcessor(CookieJar()))


_SENSITIVE_POINTER_SEGMENT = re.compile(
    r"(?:pass(?:word)?|secret|token|authorization|cookie|session|credential|api[_-]?key)",
    re.IGNORECASE,
)


def _pointer_escape(segment: str) -> str:
    if _SENSITIVE_POINTER_SEGMENT.search(segment):
        return "<redacted-key>"
    return segment.replace("~", "~0").replace("/", "~1")


def _is_ignored_pointer(pointer: str, ignored_paths: Sequence[str]) -> bool:
    return any(pointer == item or pointer.startswith(item.rstrip("/") + "/") for item in ignored_paths)


def _sanitize_pointer(pointer: str) -> str:
    """Redact sensitive key names in a JSON Pointer used for display."""
    if not pointer.startswith("/"):
        return pointer
    segments = pointer[1:].split("/")
    return "/" + "/".join(
        "<redacted-key>" if _SENSITIVE_POINTER_SEGMENT.search(segment) else segment
        for segment in segments
    )


def _collect_safe_json_differences(
    left: Any,
    right: Any,
    *,
    pointer: str = "",
    display_pointer: str = "",
    ignored_paths: Sequence[str] = (),
    output: list[str] | None = None,
    max_pointers: int = 24,
    depth: int = 0,
) -> list[str]:
    """Collect bounded JSON Pointer paths without copying values or leaking sensitive keys.

    `pointer` always follows the original JSON document and is used for contract
    matching. `display_pointer` is the sanitized path shown to users. Keeping
    these separate prevents sensitive-key redaction from accidentally defeating
    an ignore-path rule.
    """
    paths = output if output is not None else []
    if len(paths) >= max_pointers or depth > 8 or _is_ignored_pointer(pointer, ignored_paths):
        return paths
    if type(left) is not type(right):
        paths.append(display_pointer or "/")
        return paths
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right), key=str)
        for key in keys:
            if len(paths) >= max_pointers:
                break
            raw_segment = str(key).replace("~", "~0").replace("/", "~1")
            raw_child = f"{pointer}/{raw_segment}"
            display_child = f"{display_pointer}/{_pointer_escape(str(key))}"
            if key not in left or key not in right:
                if not _is_ignored_pointer(raw_child, ignored_paths):
                    paths.append(display_child)
            else:
                _collect_safe_json_differences(
                    left[key],
                    right[key],
                    pointer=raw_child,
                    display_pointer=display_child,
                    ignored_paths=ignored_paths,
                    output=paths,
                    max_pointers=max_pointers,
                    depth=depth + 1,
                )
    elif isinstance(left, list):
        if len(left) != len(right):
            paths.append(display_pointer or "/")
            return paths
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            if len(paths) >= max_pointers:
                break
            _collect_safe_json_differences(
                left_item,
                right_item,
                pointer=f"{pointer}/{index}",
                display_pointer=f"{display_pointer}/{index}",
                ignored_paths=ignored_paths,
                output=paths,
                max_pointers=max_pointers,
                depth=depth + 1,
            )
    elif left != right:
        paths.append(display_pointer or "/")
    return paths


def _observation_envelope(observation: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(observation, Mapping) or observation.get("timed_out") or observation.get("returncode") != 0:
        return None
    try:
        decoded = json.loads(observation.get("stdout", ""))
    except (json.JSONDecodeError, TypeError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _explain_step_difference(
    step: Mapping[str, Any],
    *,
    categories: Sequence[str],
    contract: CompatibilityContract,
) -> dict[str, Any]:
    """Explain which safe observables differed without duplicating field values."""
    reference = _observation_envelope(step.get("reference"))
    candidate = _observation_envelope(step.get("candidate"))
    pointers: list[str] = []
    if reference is not None and candidate is not None:
        _collect_safe_json_differences(
            reference, candidate, ignored_paths=contract.stdout.ignore_paths, output=pointers
        )
    def status(envelope: Mapping[str, Any] | None) -> int | None:
        value = envelope.get("status") if envelope is not None else None
        return value if type(value) is int else None
    def content_type(envelope: Mapping[str, Any] | None) -> str | None:
        headers = envelope.get("headers", {}) if envelope is not None else {}
        if not isinstance(headers, dict):
            return None
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "content-type" and isinstance(value, str):
                return value.split(";", 1)[0].strip().lower()
        return None
    return {
        "difference_categories": list(categories),
        "reference_status": status(reference),
        "candidate_status": status(candidate),
        "reference_content_type": content_type(reference),
        "candidate_content_type": content_type(candidate),
        "comparison_rules": {
            "stdout_mode": contract.stdout.mode,
            "stdout_ignored_json_pointers": [_sanitize_pointer(item) for item in contract.stdout.ignore_paths],
            "stderr_mode": contract.stderr.mode,
            "stderr_ignored_json_pointers": [_sanitize_pointer(item) for item in contract.stderr.ignore_paths],
            "compare_exit_code": contract.compare_exit_code,
            "compare_timeout": contract.compare_timeout,
        },
        "safe_difference_pointers": pointers,
        "difference_pointer_limit": 24,
        "values_included": False,
    }


def _one_sequence_run(
    *,
    sequence: Mapping[str, Any],
    reference_url: str,
    candidate_url: str,
    timeout: float,
    max_output_bytes: int,
    request_headers: tuple[tuple[str, str], ...],
    response_headers: tuple[str, ...],
    options: CompareOptions,
) -> dict[str, Any]:
    variables = {"reference": {}, "candidate": {}}
    openers = {"reference": _make_session_opener(), "candidate": _make_session_opener()}
    bases = {"reference": reference_url, "candidate": candidate_url}
    traces: list[dict[str, Any]] = []
    sequence_differences: list[str] = []

    for index, step in enumerate(sequence["steps"], start=1):
        step_result: dict[str, Any] = {
            "step_index": index,
            "name": step.get("name", f"step-{index}"),
            "method": step["method"].upper(),
            "path_template": _safe_path(step["path"]),
        }
        observations: dict[str, Observation] = {}
        rendered_paths: dict[str, str] = {}
        rendered_bodies: dict[str, str | None] = {}
        body_digests: dict[str, str | None] = {}
        render_errors: dict[str, str] = {}
        # Preflight both requests before sending either one. Diverging capture
        # values must never cause a half-executed step due to a render error.
        for side in ("reference", "candidate"):
            try:
                rendered_path = _render_value(step["path"], variables[side], encode_for_path=True)
                if not isinstance(rendered_path, str):
                    raise ValueError("rendered path is not text")
                _validate_request_path(rendered_path, index=index, allow_templates=False)
                rendered_body = _body_text(step, variables[side])
                rendered_paths[side] = rendered_path
                rendered_bodies[side] = rendered_body
                body_digests[side] = hashlib.sha256(rendered_body.encode("utf-8")).hexdigest() if rendered_body is not None else None
            except ValueError as exc:
                render_errors[side] = str(exc)

        step_differences: list[str] = []
        if render_errors:
            for side in render_errors:
                category = f"{side}_request_render_error"
                step_differences.append(category)
                step_result.setdefault("errors", {})[side] = render_errors[side]
            # Do not run a partial pair or let an invalid path send a request.
            sequence_differences.extend(step_differences)
            step_result["differences"] = step_differences
            traces.append(step_result)
            break

        for side in ("reference", "candidate"):
            target = HttpTarget(
                bases[side], step["method"].upper(), rendered_paths[side],
                tuple((name.lower(), value) for name, value in request_headers), response_headers,
            )
            observations[side] = _read_response(
                target, rendered_bodies[side], timeout=timeout,
                max_output_bytes=max_output_bytes, opener=openers[side],
            )

        ref_obs, cand_obs = observations["reference"], observations["candidate"]
        step_differences.extend(difference_kinds(ref_obs, cand_obs, options))
        step_result["reference"] = ref_obs.to_dict()
        step_result["candidate"] = cand_obs.to_dict()
        step_result["reference_request"] = {
            "method": step["method"].upper(),
            "path": _safe_path(step["path"]),
            "body_sha256": body_digests["reference"],
            "body_recorded": "body" in step,
        }
        step_result["candidate_request"] = {
            "method": step["method"].upper(),
            "path": _safe_path(step["path"]),
            "body_sha256": body_digests["candidate"],
            "body_recorded": "body" in step,
        }

        capture_errors: dict[str, list[str]] = {"reference": [], "candidate": []}
        for side in ("reference", "candidate"):
            if not step.get("capture"):
                continue
            try:
                envelope = json.loads(observations[side].stdout)
            except (json.JSONDecodeError, RecursionError):
                envelope = None
            for variable, pointer in step.get("capture", {}).items():
                try:
                    if envelope is None:
                        raise ValueError("response envelope is not valid JSON")
                    variables[side][variable] = _resolve_pointer(envelope, pointer)
                except ValueError:
                    capture_errors[side].append(variable)
        for side, error_variables in capture_errors.items():
            if error_variables:
                category = f"{side}_capture_error"
                step_differences.append(category)
                step_result.setdefault("capture_errors", {})[side] = error_variables

        step_result["differences"] = list(dict.fromkeys(step_differences))
        if step_result["differences"]:
            step_result["explanation"] = _explain_step_difference(
                step_result, categories=step_result["differences"], contract=options.contract
            )
        traces.append(step_result)
        sequence_differences.extend(step_result["differences"])
        # A missing capture prevents correct continuation. Keep the partial trace
        # and stop instead of substituting arbitrary data or corrupting state.
        if capture_errors["reference"] or capture_errors["candidate"]:
            break

    return {"step_results": traces, "differences": list(dict.fromkeys(sequence_differences))}


def _verify_reset_health(
    *,
    health: Mapping[str, Any],
    reference_url: str,
    candidate_url: str,
    timeout: float,
    max_output_bytes: int,
    request_headers: tuple[tuple[str, str], ...],
    response_headers: tuple[str, ...],
) -> dict[str, Any]:
    """Verify state assertions after reset without retaining observed values."""
    failures: list[str] = []
    checks: list[dict[str, Any]] = []
    for side, base_url in (("reference", reference_url), ("candidate", candidate_url)):
        target = HttpTarget(base_url, "GET", health["path"], request_headers, response_headers)
        observation = _read_response(target, None, timeout=timeout, max_output_bytes=max_output_bytes, opener=_make_session_opener())
        envelope: Any = None
        status: int | None = None
        transport_ok = not observation.timed_out and observation.returncode == 0
        if transport_ok:
            try:
                envelope = json.loads(observation.stdout)
                candidate_status = envelope.get("status") if isinstance(envelope, dict) else None
                if type(candidate_status) is int:
                    status = candidate_status
            except (json.JSONDecodeError, RecursionError):
                envelope = None
        side_check: dict[str, Any] = {"side": side, "status": status, "transport_ok": transport_ok, "passed": False, "assertions": []}
        if not transport_ok:
            failures.append(f"{side}: health request transport failed or timed out")
        elif status is None or not 200 <= status < 300:
            failures.append(f"{side}: health endpoint did not return 2xx")
        else:
            assertion_failed = False
            for assertion in health["assertions"]:
                pointer, expected = assertion["pointer"], assertion["equals"]
                try:
                    actual = _resolve_pointer(envelope, pointer)
                    matched = type(actual) is type(expected) and actual == expected
                except ValueError:
                    matched = False
                side_check["assertions"].append({"pointer": pointer, "passed": matched})
                if not matched:
                    assertion_failed = True
                    failures.append(f"{side}: assertion failed at {pointer}")
            side_check["passed"] = not assertion_failed
        checks.append(side_check)
    result = {"verified": not failures, "path": health["path"], "checks": checks}
    if failures:
        raise ValueError("reset health check failed; no tested workflow was sent: " + "; ".join(failures[:8]))
    return result


def _validate_sequence_reset(run: Mapping[str, Any]) -> None:
    """Require every reset step to complete with a successful HTTP status on both targets."""
    side_failures: list[str] = []
    for step in run.get("step_results", []):
        name = step.get("name", "unnamed-reset-step")
        for side in ("reference", "candidate"):
            observation = step.get(side)
            if not isinstance(observation, dict):
                side_failures.append(f"{name} ({side}: no response)")
                continue
            if observation.get("timed_out") or observation.get("returncode") != 0:
                side_failures.append(f"{name} ({side}: transport failure or timeout)")
                continue
            try:
                envelope = json.loads(observation.get("stdout", ""))
                status = envelope.get("status") if isinstance(envelope, dict) else None
            except (json.JSONDecodeError, RecursionError):
                status = None
            if type(status) is not int or not 200 <= status < 300:
                side_failures.append(f"{name} ({side}: reset status was not 2xx)")
        if step.get("errors") or step.get("capture_errors"):
            side_failures.append(f"{name} (reset request rendering or capture failed)")
    if side_failures:
        raise ValueError("reset sequence failed; no exploration request was sent: " + "; ".join(side_failures[:8]))


def _json_shape(value: Any, *, depth: int = 0) -> str:
    """Return a bounded, value-free description of a JSON response shape."""
    if depth >= 5:
        return "depth-limit"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        keys = sorted(value)
        parts = [f"{key}:{_json_shape(value[key], depth=depth + 1)}" for key in keys[:20]]
        if len(keys) > 20:
            parts.append("…:more-keys")
        return "object{" + ",".join(parts) + "}"
    if isinstance(value, list):
        if not value:
            return "array[empty]"
        shapes = sorted({_json_shape(item, depth=depth + 1) for item in value})
        length_class = "one" if len(value) == 1 else "many"
        return "array[" + length_class + ";" + ",".join(shapes[:8]) + "]"
    return type(value).__name__


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _response_branch_signature(step: Mapping[str, Any], side: str) -> str:
    """Hash response behavior without retaining actual response field values."""
    observation = step.get(side)
    descriptor: dict[str, Any] = {
        "method": step.get("method", "?"),
        "path": step.get("path_template", ""),
        "side": side,
    }
    if not isinstance(observation, dict):
        descriptor["outcome"] = "no-observation"
    elif observation.get("timed_out"):
        descriptor["outcome"] = "timeout"
    elif observation.get("returncode") != 0:
        descriptor["outcome"] = "transport-error"
        try:
            envelope = json.loads(observation.get("stdout", ""))
        except (json.JSONDecodeError, TypeError, RecursionError):
            envelope = {}
        descriptor["error_type"] = envelope.get("transport_error", "unknown") if isinstance(envelope, dict) else "unknown"
    else:
        try:
            envelope = json.loads(observation.get("stdout", ""))
        except (json.JSONDecodeError, TypeError, RecursionError):
            envelope = None
        if isinstance(envelope, dict):
            descriptor["status"] = envelope.get("status")
            headers = envelope.get("headers", {})
            content_type = ""
            if isinstance(headers, dict):
                for key, value in headers.items():
                    if isinstance(key, str) and key.lower() == "content-type" and isinstance(value, str):
                        content_type = value.split(";", 1)[0].strip().lower()
                        break
            descriptor["content_type"] = content_type
            descriptor["body_shape"] = _json_shape(envelope.get("body"))
        else:
            descriptor["outcome"] = "invalid-observation"
    return _sha256_json(descriptor)


def _build_behavior_coverage(step_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Create value-free response-branch and adjacent-transition fingerprints."""
    branches: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    previous: dict[str, str] = {}
    for index, step in enumerate(step_results, start=1):
        name = str(step.get("name", f"step-{index}"))
        method = str(step.get("method", "?"))
        path = str(step.get("path_template", ""))
        branch_entry: dict[str, Any] = {
            "step_index": index,
            "step_name": name,
            "operation": f"{method} {path}",
            "differences": sorted({str(item) for item in step.get("differences", [])}),
        }
        for side in ("reference", "candidate"):
            signature = _response_branch_signature(step, side)
            branch_entry[f"{side}_signature"] = signature
            if side in previous:
                transitions.append({
                    "step_index": index,
                    "step_name": name,
                    "side": side,
                    "signature": _sha256_json({"previous": previous[side], "current": signature}),
                })
            previous[side] = signature
        branches.append(branch_entry)
    return {"response_branches": branches, "transitions": transitions}


def run_http_sequence_comparison(
    *,
    reference_url: str,
    candidate_url: str,
    sequence: Mapping[str, Any],
    sequence_sha256: str,
    timeout: float = 5.0,
    repeat: int = 1,
    max_output_bytes: int = 100_000,
    request_headers: Sequence[tuple[str, str]] = (),
    response_headers: Sequence[str] = (),
    contract: CompatibilityContract | None = None,
    reset_sequence: Mapping[str, Any] | None = None,
    reset_sequence_sha256: str | None = None,
    include_behavior_coverage: bool = False,
) -> dict[str, Any]:
    """Run a defined multi-request API workflow on both loopback implementations."""
    validate_sequence(dict(sequence))
    if reset_sequence is not None:
        validate_sequence(dict(reset_sequence))
        if reset_sequence_sha256 is None:
            reset_canonical = json.dumps(reset_sequence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            reset_sequence_sha256 = hashlib.sha256(reset_canonical.encode("utf-8")).hexdigest()
        if not isinstance(reset_sequence_sha256, str) or len(reset_sequence_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in reset_sequence_sha256
        ):
            raise ValueError("reset sequence SHA-256 must be a 64-character lowercase hexadecimal digest")
    elif reset_sequence_sha256 is not None:
        raise ValueError("reset_sequence_sha256 cannot be supplied without reset_sequence")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if type(repeat) is not int or repeat < 1 or repeat > _MAX_SEQUENCE_REPEAT:
        raise ValueError(f"repeat must be between 1 and {_MAX_SEQUENCE_REPEAT}")
    if type(max_output_bytes) is not int or max_output_bytes < 1 or max_output_bytes > 100_000:
        raise ValueError("max_output_bytes must be between 1 and 100000")
    if not isinstance(sequence_sha256, str) or len(sequence_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sequence_sha256
    ):
        raise ValueError("sequence source SHA-256 must be a 64-character lowercase hexadecimal digest")
    reference_base = validate_local_base_url(reference_url, label="--reference-url")
    candidate_base = validate_local_base_url(candidate_url, label="--candidate-url")
    validated_headers = parse_request_headers([f"{name}: {value}" for name, value in request_headers])
    normalized_headers = tuple((name.lower(), value) for name, value in validated_headers)
    normalized_response_headers = tuple(sorted({"content-type", *(name.strip().lower() for name in response_headers)}))
    from .http_engine import _HEADER_NAME
    if any(not _HEADER_NAME.fullmatch(name) for name in normalized_response_headers):
        raise ValueError("--response-header must name a valid HTTP header")

    contract = contract or CompatibilityContract(name="stateful-http-json-default", stdout=OutputContract(mode="json"))
    options = CompareOptions(timeout=timeout, max_output_bytes=max_output_bytes, contract=contract)
    started = time.perf_counter()
    runs: list[dict[str, Any]] = []
    reset_health_runs: list[dict[str, Any]] = []
    for repeat_index in range(repeat):
        if reset_sequence is not None:
            reset_run = _one_sequence_run(
                sequence=reset_sequence,
                reference_url=reference_base,
                candidate_url=candidate_base,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
                request_headers=normalized_headers,
                response_headers=normalized_response_headers,
                options=options,
            )
            _validate_sequence_reset(reset_run)
            if "health" in reset_sequence:
                health_result = _verify_reset_health(
                    health=reset_sequence["health"],
                    reference_url=reference_base,
                    candidate_url=candidate_base,
                    timeout=timeout,
                    max_output_bytes=max_output_bytes,
                    request_headers=normalized_headers,
                    response_headers=normalized_response_headers,
                )
                reset_health_runs.append({"repeat_index": repeat_index + 1, **health_result})
        runs.append(
            _one_sequence_run(
                sequence=sequence,
                reference_url=reference_base,
                candidate_url=candidate_base,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
                request_headers=normalized_headers,
                response_headers=normalized_response_headers,
                options=options,
            )
        )

    differences = list(runs[0]["differences"])
    unstable_repeat_indexes: dict[str, int] = {}
    if repeat > 1:
        for side in ("reference", "candidate"):
            signatures: list[tuple[Any, ...]] = []
            for run in runs:
                step_signatures: list[Any] = []
                for step_result in run["step_results"]:
                    observation = step_result.get(side)
                    if isinstance(observation, dict):
                        reconstructed = Observation(
                            returncode=observation.get("returncode"),
                            stdout=observation.get("stdout", ""),
                            stderr=observation.get("stderr", ""),
                            timed_out=observation.get("timed_out", False),
                            duration_seconds=observation.get("duration_seconds", 0.0),
                            stdout_truncated=observation.get("stdout_truncated", False),
                            stderr_truncated=observation.get("stderr_truncated", False),
                            stdout_bytes_seen=observation.get("stdout_bytes_seen", 0),
                            stderr_bytes_seen=observation.get("stderr_bytes_seen", 0),
                            output_limit_exceeded=observation.get("output_limit_exceeded", False),
                        )
                        step_signatures.append(_behavior_signature(reconstructed, options))
                    elif step_result.get("errors", {}).get(side):
                        step_signatures.append(("request-render-error", step_result["errors"][side]))
                signatures.append(tuple(step_signatures))
            if len(set(signatures)) > 1:
                differences.append(f"{side}_unstable")
                unstable_repeat_indexes[side] = next(
                    (index for index, signature in enumerate(signatures[1:], start=1) if signature != signatures[0]),
                    1,
                )

    unique_differences = list(dict.fromkeys(differences))
    sequence_json = json.dumps(sequence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    canonical_digest = hashlib.sha256(sequence_json.encode("utf-8")).hexdigest()
    # The generic input hash always hashes the exact string stored in `input`;
    # a separate field preserves the original file-byte hash including whitespace.
    executions = [{"case_index": 1, "input_sha256": canonical_digest, "differences": unique_differences}]
    findings: list[dict[str, Any]] = []
    if unique_differences:
        finding: dict[str, Any] = {
            "case_index": 1,
            "input": sequence_json,
            "input_sha256": canonical_digest,
            "differences": unique_differences,
            "minimized": False,
            "minimization_trials": 0,
            "minimization_limit_reached": False,
            "sequence_definition": sequence,
            "sequence_file_sha256": sequence_sha256,
            "sequence_canonical_sha256": canonical_digest,
            "sequence_name": sequence.get("name", "unnamed-sequence"),
            "step_results": runs[0]["step_results"],
        }
        if unstable_repeat_indexes:
            # Preserve only first alternate traces for unstable sides; duplicate runs
            # otherwise inflate evidence reports without adding reproducibility value.
            alternate_indexes = sorted(set(unstable_repeat_indexes.values()))
            finding["repeat_instability"] = {
                side: {"first_differing_repeat": repeat_index + 1}
                for side, repeat_index in unstable_repeat_indexes.items()
            }
            finding["repeat_traces"] = [
                {"repeat_index": repeat_index + 1, "step_results": runs[repeat_index]["step_results"]}
                for repeat_index in alternate_indexes
                if repeat_index < len(runs)
            ]
        findings.append(finding)

    elapsed = time.perf_counter() - started
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": "TwinCheck",
        "tool_version": __version__,
        "reference_command": f"HTTP SEQUENCE {reference_base}",
        "candidate_command": f"HTTP SEQUENCE {candidate_base}",
        "strategy": "stateful-http-sequence",
        "seed": None,
        "repeat": repeat,
        "max_output_bytes": max_output_bytes,
        "working_directory": None,
        "compatibility_contract": contract.to_dict(),
        "compatibility_contract_sha256": contract.sha256,
        "comparison_policy": {
            "normalize_eol": False,
            "ignore_trailing_whitespace": False,
            "ignore_stderr": False,
            "ignore_exit_code": False,
        },
        "input_source": "stateful-http-sequence",
        "sequence": {
            "name": sequence.get("name", "unnamed-sequence"),
            "schema_version": sequence.get("schema_version", 1),
            "step_count": len(sequence["steps"]),
            "source_sha256": sequence_sha256,
            "canonical_sha256": canonical_digest,
            "definition_included_in_findings": True,
        },
        "state_reset": {
            "enabled": reset_sequence is not None,
            "sequence_sha256": reset_sequence_sha256,
            "canonical_sha256": hashlib.sha256(
                json.dumps(reset_sequence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest() if reset_sequence is not None else None,
            "sequence_definition": dict(reset_sequence) if reset_sequence is not None else None,
            "performed_before_each_repeat": reset_sequence is not None,
            "reset_responses_recorded": False,
            "health_check": {
                "configured": reset_sequence is not None and "health" in reset_sequence,
                "verification_mode": ("explicit-json-pointer-assertions" if reset_sequence is not None and "health" in reset_sequence else "status-only" if reset_sequence is not None else "not-configured"),
                "verified_before_each_repeat": reset_sequence is not None and "health" in reset_sequence and len(reset_health_runs) == repeat,
                "assertion_pointers": [item["pointer"] for item in reset_sequence["health"]["assertions"]] if reset_sequence is not None and "health" in reset_sequence else [],
                "runs": reset_health_runs,
            },
        },
        "http_adapter": {
            "mode": "stateful-sequence",
            "request_header_names": sorted(name.lower() for name, _ in normalized_headers),
            "response_headers_compared": list(normalized_response_headers),
            "cookies_persist_within_each_sequence": True,
            "cookie_jars_shared_between_targets": False,
            "request_header_values_recorded": False,
            "remote_hosts_allowed": False,
            "redirects_followed": False,
        },
        "cases_requested": 1,
        "cases_executed": 1,
        "timeout_seconds": timeout,
        "minimization_enabled": False,
        "executions": executions,
        "elapsed_seconds": round(elapsed, 6),
        "findings": findings,
        "summary": {
            "differences_found": len(findings),
            "cases_with_differences": len(findings),
            "minimized_findings": 0,
            "unstable_reference_findings": sum(1 for item in unique_differences if item == "reference_unstable"),
            "unstable_candidate_findings": sum(1 for item in unique_differences if item == "candidate_unstable"),
            "truncated_output_findings": sum(1 for item in unique_differences if item == "output_truncated"),
            "output_limit_findings": sum(1 for item in unique_differences if item == "output_limit_exceeded"),
            "invalid_json_findings": sum(1 for item in unique_differences if item.endswith("_invalid_json")),
            "steps_with_differences": sum(
                1 for step in runs[0]["step_results"] if step.get("differences")
            ),
        },
        "limitations": [
            "Stateful workflows are explicit request sequences; automatic transition exploration requires the explore-http-sequence command.",
            "A reset sequence must return 2xx for every step on both targets. This confirms endpoint success only, not that all hidden state was cleared.",
            "When the reset sequence embeds a health contract, a separate GET probe checks its JSON Pointer assertions on both targets before every tested repeat; observed health response values are not retained in the health-check summary.",
            "Capture values are scalar JSON values selected by RFC 6901 JSON Pointer from the response observation envelope.",
            "Cookies persist independently within each target sequence and are reset between repeated sequence runs.",
            "Only loopback targets are allowed; this adapter is not a sandbox and request bodies can change local service state.",
            "The sequence definition and response observations are included with findings; do not test with secrets or sensitive customer data.",
            "A clean run is evidence only for the particular workflow and sequence tested, not proof of API equivalence.",
        ],
    }
    if include_behavior_coverage:
        report["behavior_coverage"] = _build_behavior_coverage(runs[0]["step_results"])
    return report
