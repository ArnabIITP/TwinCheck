"""Local HTTP differential testing using the same comparison contracts as CLI targets."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import __version__
from .compare import CompareOptions, _behavior_signature, difference_kinds
from .contract import CompatibilityContract, OutputContract
from .report import REPORT_SCHEMA_VERSION
from .runner import Observation

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_RESERVED_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat redirects as responses; never follow a server-controlled URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Explicitly disable ambient HTTP(S)_PROXY settings and automatic redirects so
# a loopback request cannot be sent through a proxy or redirected to a remote host.
_LOCAL_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


@dataclass(frozen=True)
class HttpTarget:
    base_url: str
    method: str
    path: str
    headers: tuple[tuple[str, str], ...]
    response_headers: tuple[str, ...]

    @property
    def display_url(self) -> str:
        parsed = urlsplit(self.path)
        # Static query values can contain credentials or customer data. Keep the
        # path useful for diagnosis without writing query values into evidence.
        safe_path = parsed.path + ("?<query-redacted>" if parsed.query else "")
        return f"{self.base_url}{safe_path}"


def validate_local_base_url(value: str, *, label: str) -> str:
    """Accept a bare local HTTP(S) origin only; no credentials or remote hosts."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an http:// or https:// local URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain embedded username or password credentials")
    if parsed.hostname.lower() not in _ALLOWED_HOSTS:
        raise ValueError(f"{label} must target localhost, 127.0.0.1, or ::1; remote hosts are not allowed")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"{label} must be an origin only, such as http://127.0.0.1:8000")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid port") from exc
    return value.rstrip("/")


def parse_request_headers(raw_headers: Sequence[str] | None) -> tuple[tuple[str, str], ...]:
    """Parse user header declarations while rejecting framing and control headers."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for declaration in raw_headers or ():
        if ":" not in declaration:
            raise ValueError("each --header must use 'Name: value' syntax")
        name, value = declaration.split(":", 1)
        name, value = name.strip(), value.strip()
        normalized = name.lower()
        if not _HEADER_NAME.fullmatch(name):
            raise ValueError(f"invalid HTTP header name {name!r}")
        if normalized in _RESERVED_HEADERS:
            raise ValueError(f"--header cannot override the transport header {name!r}")
        if "\r" in value or "\n" in value:
            raise ValueError(f"HTTP header {name!r} contains a forbidden newline")
        if normalized in seen:
            raise ValueError(f"duplicate request header {name!r}; provide each header once")
        seen.add(normalized)
        result.append((name, value))
    return tuple(result)


def _read_response(
    target: HttpTarget,
    input_text: str | None,
    *,
    timeout: float,
    max_output_bytes: int,
    opener: Any = None,
) -> Observation:
    started = time.perf_counter()
    url = target.base_url + target.path
    payload = input_text.encode("utf-8") if input_text is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    headers.update(dict(target.headers))
    request = Request(url, data=payload, headers=headers, method=target.method)
    active_opener = opener if opener is not None else _LOCAL_OPENER

    try:
        try:
            response = active_opener.open(request, timeout=timeout)
        except HTTPError as exc:
            # HTTP error status codes are normal API responses, not adapter failures.
            response = exc
        with response:
            status = int(response.status)
            raw_body = response.read(max_output_bytes + 1)
            too_large = len(raw_body) > max_output_bytes
            if too_large:
                raw_body = raw_body[:max_output_bytes]
            response_header_map = {name.lower(): value for name, value in response.headers.items()}
            selected_headers = {
                name: response_header_map[name]
                for name in target.response_headers
                if name in response_header_map
            }
    except (socket.timeout, TimeoutError):
        return Observation(
            returncode=None, stdout="", stderr="", timed_out=True,
            duration_seconds=time.perf_counter() - started,
        )
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return Observation(
                returncode=None, stdout="", stderr="", timed_out=True,
                duration_seconds=time.perf_counter() - started,
            )
        error_type = type(exc.reason).__name__
        payload_text = json.dumps({"transport_error": error_type}, sort_keys=True, separators=(",", ":"))
        return Observation(
            returncode=1, stdout=payload_text, stderr="", timed_out=False,
            duration_seconds=time.perf_counter() - started,
        )
    except (OSError, ValueError) as exc:
        payload_text = json.dumps({"transport_error": type(exc).__name__}, sort_keys=True, separators=(",", ":"))
        return Observation(
            returncode=1, stdout=payload_text, stderr="", timed_out=False,
            duration_seconds=time.perf_counter() - started,
        )

    if too_large:
        body: Any = {"truncated": True, "preview": raw_body[: min(len(raw_body), 4096)].decode("utf-8", errors="replace")}
    else:
        decoded = raw_body.decode("utf-8", errors="replace")
        try:
            body = json.loads(decoded, parse_constant=_reject_nonstandard_json_constant)
        except (json.JSONDecodeError, ValueError, RecursionError):
            body = decoded
    envelope = {"status": status, "headers": selected_headers, "body": body}
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded_bytes = encoded.encode("utf-8")
    output_truncated = too_large or len(encoded_bytes) > max_output_bytes
    if len(encoded_bytes) > max_output_bytes:
        encoded = encoded_bytes[:max_output_bytes].decode("utf-8", errors="ignore")
    return Observation(
        returncode=0,
        stdout=encoded,
        stderr="",
        timed_out=False,
        duration_seconds=time.perf_counter() - started,
        stdout_truncated=output_truncated,
        stdout_bytes_seen=len(encoded_bytes) + (1 if output_truncated else 0),
        output_limit_exceeded=output_truncated,
    )


def run_http_comparison(
    *,
    reference_url: str,
    candidate_url: str,
    method: str,
    path: str,
    inputs: Sequence[str],
    seed: int = 0,
    timeout: float = 5.0,
    repeat: int = 1,
    max_output_bytes: int = 1_000_000,
    request_headers: Sequence[tuple[str, str]] = (),
    response_headers: Sequence[str] = (),
    contract: CompatibilityContract | None = None,
    schema_sha256: str | None = None,
    schema_title: str | None = None,
    requested_cases: int | None = None,
) -> dict[str, Any]:
    """Compare two local HTTP endpoints with generated JSON request bodies."""
    if not inputs:
        raise ValueError("HTTP comparison requires at least one JSON input")
    if requested_cases is not None and requested_cases < 1:
        raise ValueError("requested_cases must be at least 1")
    total_input_bytes = sum(len(value.encode("utf-8")) for value in inputs)
    if any(len(value.encode("utf-8")) > 1 * 1024 * 1024 for value in inputs):
        raise ValueError("HTTP request input exceeds 1 MiB")
    if total_input_bytes > 50 * 1024 * 1024:
        raise ValueError("HTTP request inputs exceed the 50 MiB total payload limit")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")
    method = method.upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise ValueError("HTTP method must be one of GET, POST, PUT, PATCH, DELETE, OPTIONS")
    if not path.startswith("/") or path.startswith("//") or "#" in path:
        raise ValueError("--path must be an absolute path beginning with one slash and must not contain a fragment")
    if any(ord(character) < 0x20 or character == " " for character in path):
        raise ValueError("--path must percent-encode spaces and contain no control characters")
    parsed_path = urlsplit(path)
    if parsed_path.scheme or parsed_path.netloc:
        raise ValueError("--path cannot contain a URL scheme or host")
    ref_base = validate_local_base_url(reference_url, label="--reference-url")
    cand_base = validate_local_base_url(candidate_url, label="--candidate-url")
    for name, value in request_headers:
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise ValueError(f"invalid HTTP header name {name!r}")
        if name.lower() in _RESERVED_HEADERS:
            raise ValueError(f"--header cannot override the transport header {name!r}")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError(f"HTTP header {name!r} has an invalid value")
    validated_headers = parse_request_headers([f"{name}: {value}" for name, value in request_headers])
    normalized_headers = tuple((name.lower(), value) for name, value in validated_headers)
    selected_response_headers = tuple(sorted({"content-type", *(name.strip().lower() for name in response_headers)}))
    if any(not _HEADER_NAME.fullmatch(name) for name in selected_response_headers):
        raise ValueError("--response-header must name a valid HTTP header")

    reference = HttpTarget(ref_base, method, path, normalized_headers, selected_response_headers)
    candidate = HttpTarget(cand_base, method, path, normalized_headers, selected_response_headers)
    contract = contract or CompatibilityContract(name="http-json-default", stdout=OutputContract(mode="json"))
    options = CompareOptions(timeout=timeout, max_output_bytes=max_output_bytes, contract=contract)
    started = time.perf_counter()
    findings: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []

    for case_index, input_text in enumerate(list(dict.fromkeys(inputs)), start=1):
        reference_runs: list[Observation] = []
        candidate_runs: list[Observation] = []
        for _ in range(repeat):
            reference_runs.append(_read_response(reference, input_text, timeout=timeout, max_output_bytes=max_output_bytes))
            candidate_runs.append(_read_response(candidate, input_text, timeout=timeout, max_output_bytes=max_output_bytes))
        differences = difference_kinds(reference_runs[0], candidate_runs[0], options)
        if len({_behavior_signature(item, options) for item in reference_runs}) > 1:
            differences.append("reference_unstable")
        if len({_behavior_signature(item, options) for item in candidate_runs}) > 1:
            differences.append("candidate_unstable")
        digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        executions.append({"case_index": case_index, "input_sha256": digest, "differences": list(differences)})
        if not differences:
            continue
        finding: dict[str, Any] = {
            "case_index": case_index,
            "input": input_text,
            "input_sha256": digest,
            "differences": differences,
            "minimized": False,
            "minimization_trials": 0,
            "minimization_limit_reached": False,
            "reference": reference_runs[0].to_dict(),
            "candidate": candidate_runs[0].to_dict(),
        }
        if repeat > 1:
            finding["reference_runs"] = [item.to_dict() for item in reference_runs]
            finding["candidate_runs"] = [item.to_dict() for item in candidate_runs]
        findings.append(finding)

    elapsed = time.perf_counter() - started
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": "TwinCheck",
        "tool_version": __version__,
        "reference_command": f"HTTP {method} {reference.display_url}",
        "candidate_command": f"HTTP {method} {candidate.display_url}",
        "strategy": "json-schema",
        "seed": seed,
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
        "input_source": "json-schema",
        "input_generation": {
            "method": "json-schema",
            "json_schema_sha256": schema_sha256,
            "schema_title": schema_title,
            "unique_sample_count": len(dict.fromkeys(inputs)),
            "seed": seed,
        },
        "http_adapter": {
            "method": method,
            "path": (urlsplit(path).path + ("?<query-redacted>" if urlsplit(path).query else "")),
            "request_header_names": sorted(name.lower() for name, _ in request_headers),
            "response_headers_compared": list(selected_response_headers),
            "request_header_values_recorded": False,
            "remote_hosts_allowed": False,
        },
        "cases_requested": requested_cases if requested_cases is not None else len(inputs),
        "cases_executed": len(executions),
        "timeout_seconds": timeout,
        "minimization_enabled": False,
        "executions": executions,
        "elapsed_seconds": round(elapsed, 6),
        "findings": findings,
        "summary": {
            "differences_found": len(findings),
            "cases_with_differences": len(findings),
            "minimized_findings": 0,
            "unstable_reference_findings": sum(1 for finding in findings if "reference_unstable" in finding["differences"]),
            "unstable_candidate_findings": sum(1 for finding in findings if "candidate_unstable" in finding["differences"]),
            "truncated_output_findings": sum(1 for finding in findings if "output_truncated" in finding["differences"]),
            "output_limit_findings": sum(1 for finding in findings if "output_limit_exceeded" in finding["differences"]),
            "invalid_json_findings": sum(1 for finding in findings if any(
                category.endswith("_invalid_json") for category in finding["differences"]
            )),
        },
        "limitations": [
            "HTTP mode accepts only loopback services and currently sends a generated JSON request body to one fixed path.",
            "Only JSON response bodies are compared structurally; non-JSON bodies are compared as decoded text.",
            "Only content-type and explicitly selected response headers are compared by default.",
            "Request header values are not written to the report; do not put secrets in input JSON or server responses.",
            "A clean run is evidence only for the tested inputs, not proof of API equivalence.",
            "HTTP mode is a local test adapter, not a network scanner or an isolation boundary for the services themselves.",
        ],
    }
    return report
