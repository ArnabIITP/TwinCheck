"""Command-line interface for TwinCheck."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .engine import run_comparison
from .contract import contract_from_dict, load_contract
from .packs import export_cases_from_report, load_compatibility_pack
from .stateful_packs import export_stateful_sequence_pack, load_stateful_sequence_pack
from .schema import generate_schema_inputs, load_json_schema
from .http_engine import parse_request_headers, run_http_comparison
from .stateful_http import load_sequence, run_http_sequence_comparison, validate_sequence
from .stateful_explore import run_http_sequence_exploration
from .generators import STRATEGIES
from .report import print_summary, report_as_json, write_junit_report, write_json_report


def _add_process_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reference", required=True, help="reference program command")
    parser.add_argument("--candidate", required=True, help="candidate program command under test")
    parser.add_argument("--timeout", type=float, default=5.0, help="timeout per process, in seconds (default: 5)")
    parser.add_argument("--repeat", type=int, default=1, help="run each target this many times per input to detect observable instability (default: 1)")
    parser.add_argument("--max-output-bytes", type=int, default=1_000_000, help="maximum retained bytes per output stream and process (default: 1000000)")
    parser.add_argument("--cwd", help="working directory for both programs")
    parser.add_argument("--normalize-eol", action="store_true", help="treat CRLF and CR as LF in outputs")
    parser.add_argument("--ignore-trailing-whitespace", action="store_true", help="ignore spaces/tabs at line ends")
    parser.add_argument("--ignore-stderr", action="store_true", help="do not compare standard error")
    parser.add_argument("--ignore-exit-code", action="store_true", help="do not compare process exit codes")
    parser.add_argument("--output", help="write a machine-readable JSON report to this path")
    parser.add_argument("--junit", help="write a JUnit XML report to this path for CI ingestion")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="console output format")
    parser.add_argument("--contract", help="JSON compatibility contract file controlling semantic output comparison")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twincheck",
        description="Find and reproduce behavioral differences between two command-line programs.",
        epilog=(
            "Commands are parsed without a shell. By default, each input is sent to stdin; "
            "use {input} in an argument to pass the input as an argv value. "
            "Only execute trusted target programs: TwinCheck is not a sandbox."
        ),
    )
    parser.add_argument("--version", action="version", version=f"TwinCheck {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    compare = subparsers.add_parser("compare", help="generate inputs and compare two implementations")
    _add_process_options(compare)
    compare.add_argument("--cases", type=int, default=100, help="number of unique inputs to run (default: 100)")
    compare.add_argument("--seed", type=int, default=0, help="random seed for reproducible input generation")
    compare.add_argument("--strategy", choices=STRATEGIES, default="mixed", help="input generation strategy")
    compare.add_argument("--corpus", help="directory of UTF-8 input files to try before generated inputs")
    compare.add_argument("--schema", help="generate JSON request/input samples from a local JSON Schema file (incompatible with --corpus)")
    compare.add_argument("--minimize", action="store_true", help="shrink stable failing inputs using bounded delta debugging")
    compare.add_argument("--max-minimize", type=int, default=1, help="maximum findings to minimize (default: 1)")
    compare.add_argument("--max-minimization-trials", type=int, default=30, help="trial budget per minimized finding (default: 30)")


    http_compare = subparsers.add_parser(
        "compare-http",
        help="compare two local HTTP implementations with schema-generated JSON request bodies",
        description=(
            "Send the same schema-generated JSON request bodies to two loopback HTTP services and "
            "compare status, selected response headers, and response bodies. Remote hosts are rejected."
        ),
    )
    http_compare.add_argument("--reference-url", required=True, help="reference origin, e.g. http://127.0.0.1:8001")
    http_compare.add_argument("--candidate-url", required=True, help="candidate origin, e.g. http://127.0.0.1:8002")
    http_compare.add_argument("--schema", required=True, help="local JSON Schema describing request bodies")
    http_compare.add_argument("--method", choices=("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"), default="POST", help="HTTP method (default: POST)")
    http_compare.add_argument("--path", default="/", help="fixed path and optional query string (default: /)")
    http_compare.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="request header; may be repeated, values are not recorded in reports")
    http_compare.add_argument("--response-header", action="append", default=[], metavar="NAME", help="additional response header to compare (content-type is always compared)")
    http_compare.add_argument("--cases", type=int, default=100, help="number of unique generated requests to try (default: 100)")
    http_compare.add_argument("--seed", type=int, default=0, help="random seed for reproducible input generation")
    http_compare.add_argument("--timeout", type=float, default=5.0, help="timeout per HTTP request, in seconds (default: 5)")
    http_compare.add_argument("--repeat", type=int, default=1, help="repeat each request to detect observable instability (default: 1)")
    http_compare.add_argument("--max-output-bytes", type=int, default=1_000_000, help="maximum retained bytes per response observation (default: 1000000)")
    http_compare.add_argument("--output", help="write a machine-readable JSON report to this path")
    http_compare.add_argument("--junit", help="write a JUnit XML report to this path for CI ingestion")
    http_compare.add_argument("--format", choices=("text", "json"), default="text", help="console output format")
    http_compare.add_argument("--contract", help="JSON compatibility contract file controlling semantic response comparison")

    sequence_compare = subparsers.add_parser(
        "compare-http-sequence",
        help="compare two local APIs across the same stateful request sequence",
        description=(
            "Execute a user-authored sequence of HTTP requests against two loopback services. "
            "Captured JSON values can be reused in later paths and bodies; cookies persist independently per service."
        ),
    )
    sequence_compare.add_argument("--reference-url", required=True, help="reference origin, e.g. http://127.0.0.1:8001")
    sequence_compare.add_argument("--candidate-url", required=True, help="candidate origin, e.g. http://127.0.0.1:8002")
    sequence_compare.add_argument("--sequence", required=True, help="stateful sequence definition JSON file")
    sequence_compare.add_argument("--reset-sequence", help="optional reset workflow; may embed a read-only health contract to verify state after each reset")
    sequence_compare.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="request header for every step; values are not recorded in reports")
    sequence_compare.add_argument("--response-header", action="append", default=[], metavar="NAME", help="additional response header to compare (content-type is always compared)")
    sequence_compare.add_argument("--timeout", type=float, default=5.0, help="timeout per HTTP request, in seconds (default: 5)")
    sequence_compare.add_argument("--repeat", type=int, default=1, help="run the complete sequence this many times, from fresh cookie jars (1-5)")
    sequence_compare.add_argument("--max-output-bytes", type=int, default=100_000, help="maximum retained bytes per response observation (default/max: 100000)")
    sequence_compare.add_argument("--output", help="write a machine-readable JSON evidence report to this path")
    sequence_compare.add_argument("--junit", help="write JUnit XML for CI ingestion")
    sequence_compare.add_argument("--format", choices=("text", "json"), default="text", help="console output format")
    sequence_compare.add_argument("--contract", help="JSON compatibility contract file controlling semantic response comparison")

    sequence_explore = subparsers.add_parser(
        "explore-http-sequence",
        help="mutate and minimize stateful API workflows using a reset endpoint",
        description=(
            "Generate deterministic request-value, adjacent-order, step-removal, and step-repeat variants. "
            "A user-authored reset workflow is required and executed before every case and minimization trial. "
            "This mutates local service state and requires --allow-side-effects."
        ),
    )
    sequence_explore.add_argument("--reference-url", required=True, help="reference origin, e.g. http://127.0.0.1:8001")
    sequence_explore.add_argument("--candidate-url", required=True, help="candidate origin, e.g. http://127.0.0.1:8002")
    sequence_explore.add_argument("--sequence", required=True, help="base stateful workflow definition JSON file")
    sequence_explore.add_argument("--reset-sequence", required=True, help="reset workflow run before every test; embed a health contract to verify state beyond HTTP status")
    sequence_explore.add_argument("--allow-side-effects", action="store_true", help="acknowledge that exploration sends repeated state-changing requests to local services")
    sequence_explore.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="request header for every step; values are not recorded in reports")
    sequence_explore.add_argument("--response-header", action="append", default=[], metavar="NAME", help="additional response header to compare")
    sequence_explore.add_argument("--cases", type=int, default=40, help="maximum workflow variants including the baseline (1-200, default: 40)")
    sequence_explore.add_argument("--seed", type=int, default=0, help="seed for reproducibly ordering generated variants")
    sequence_explore.add_argument("--timeout", type=float, default=5.0, help="timeout per HTTP request")
    sequence_explore.add_argument("--repeat", type=int, default=1, help="repeat each workflow independently after reset (1-5)")
    sequence_explore.add_argument("--max-output-bytes", type=int, default=100_000, help="maximum retained bytes per response observation (maximum: 100000)")
    sequence_explore.add_argument("--contract", help="JSON compatibility contract file")
    sequence_explore.add_argument("--minimize", action="store_true", help="reduce up to three failing workflows by deleting steps and shrinking JSON request bodies while preserving the same mismatch")
    sequence_explore.add_argument("--max-findings-to-minimize", type=int, default=3, help="maximum findings to minimize (0-20, default: 3)")
    sequence_explore.add_argument("--max-minimization-trials", type=int, default=30, help="maximum reset-backed minimization trials per finding (1-200, default: 30)")
    sequence_explore.add_argument("--output", help="write a machine-readable JSON evidence report to this path")
    sequence_explore.add_argument("--junit", help="write JUnit XML for CI ingestion")
    sequence_explore.add_argument("--format", choices=("text", "json"), default="text", help="console output format")

    sequence_replay = subparsers.add_parser(
        "replay-http-sequence",
        help="replay a stateful HTTP sequence saved in a TwinCheck evidence report",
        description=(
            "Re-run an explicitly selected saved workflow against two explicitly supplied loopback origins. "
            "Requires --allow-side-effects because request sequences can modify service state."
        ),
    )
    sequence_replay.add_argument("--report", required=True, help="TwinCheck stateful HTTP report with a saved finding")
    sequence_replay.add_argument("--finding", type=int, default=1, help="1-based finding number (default: 1)")
    sequence_replay.add_argument("--reset-sequence", help="optional reset workflow; if the report pins one, its canonical definition must match")
    sequence_replay.add_argument("--reference-url", required=True, help="reference loopback origin")
    sequence_replay.add_argument("--candidate-url", required=True, help="candidate loopback origin")
    sequence_replay.add_argument("--allow-side-effects", action="store_true", help="acknowledge that replayed requests may create, update, or delete local data")
    sequence_replay.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="request header for every step; values are not recorded in reports")
    sequence_replay.add_argument("--response-header", action="append", default=[], metavar="NAME", help="additional response header to compare")
    sequence_replay.add_argument("--timeout", type=float, default=5.0, help="timeout per HTTP request")
    sequence_replay.add_argument("--repeat", type=int, default=1, help="run the complete sequence this many times (1-5)")
    sequence_replay.add_argument("--max-output-bytes", type=int, default=100_000, help="maximum retained bytes per response observation (maximum: 100000)")
    sequence_replay.add_argument("--output", help="write a machine-readable JSON evidence report to this path")
    sequence_replay.add_argument("--junit", help="write JUnit XML for CI ingestion")
    sequence_replay.add_argument("--format", choices=("text", "json"), default="text", help="console output format")

    replay = subparsers.add_parser(
        "replay",
        help="re-run one finding's exact input from a TwinCheck JSON report",
        description=(
            "Re-execute one saved input using explicitly supplied target commands. "
            "Commands embedded in the report are never executed automatically."
        ),
    )
    _add_process_options(replay)
    replay.add_argument("--report", required=True, help="path to a TwinCheck JSON report")
    replay.add_argument("--finding", type=int, default=1, help="1-based finding number in the report (default: 1)")

    export_pack = subparsers.add_parser(
        "export-pack",
        help="export reported counterexamples and their contract as a portable regression pack",
    )
    export_pack.add_argument("--report", required=True, help="TwinCheck JSON report containing findings")
    export_pack.add_argument("--output", required=True, help="new directory to create for the pack; existing paths are never overwritten")

    replay_pack = subparsers.add_parser(
        "replay-pack",
        help="re-run every input in a contract-pinned counterexample regression pack",
    )
    _add_process_options(replay_pack)
    replay_pack.add_argument("--pack", required=True, help="counterexample regression pack directory")

    export_sequence_pack = subparsers.add_parser("export-http-sequence-pack", help="save one stateful HTTP finding as a portable regression pack")
    export_sequence_pack.add_argument("--report", required=True, help="TwinCheck stateful HTTP report with a finding")
    export_sequence_pack.add_argument("--finding", type=int, default=1, help="1-based finding number (default: 1)")
    export_sequence_pack.add_argument("--output", required=True, help="new directory to create; existing paths are never overwritten")

    replay_sequence_pack = subparsers.add_parser("replay-http-sequence-pack", help="replay a portable stateful HTTP regression pack against two loopback services")
    replay_sequence_pack.add_argument("--pack", required=True, help="stateful HTTP regression pack directory")
    replay_sequence_pack.add_argument("--reference-url", required=True, help="reference loopback origin")
    replay_sequence_pack.add_argument("--candidate-url", required=True, help="candidate loopback origin")
    replay_sequence_pack.add_argument("--allow-side-effects", action="store_true", help="acknowledge that the saved sequence may change local service state")
    replay_sequence_pack.add_argument("--header", action="append", default=[], metavar="NAME: VALUE", help="request header for every step; values are not stored")
    replay_sequence_pack.add_argument("--response-header", action="append", default=[], metavar="NAME", help="additional response header to compare")
    replay_sequence_pack.add_argument("--timeout", type=float, default=5.0, help="timeout per HTTP request")
    replay_sequence_pack.add_argument("--repeat", type=int, default=1, help="repeat the complete sequence after reset (1-5)")
    replay_sequence_pack.add_argument("--max-output-bytes", type=int, default=100_000, help="maximum retained bytes per response observation")
    replay_sequence_pack.add_argument("--output", help="write a machine-readable JSON evidence report")
    replay_sequence_pack.add_argument("--junit", help="write JUnit XML for CI ingestion")
    replay_sequence_pack.add_argument("--format", choices=("text", "json"), default="text", help="console output format")

    return parser


def _write_outputs(args: argparse.Namespace, report: dict[str, object]) -> int:
    if args.output:
        write_json_report(args.output, report)  # type: ignore[arg-type]
    if args.junit:
        write_junit_report(args.junit, report)  # type: ignore[arg-type]
    if args.format == "json":
        print(report_as_json(report))  # type: ignore[arg-type]
    else:
        print_summary(report, stream=sys.stdout)  # type: ignore[arg-type]
        if args.output:
            print(f"\nJSON report: {Path(args.output)}")
        if args.junit:
            print(f"JUnit report: {Path(args.junit)}")
    return 1 if report["findings"] else 0  # type: ignore[index]


def _run_replay(args: argparse.Namespace) -> dict[str, object]:
    report_path = Path(args.report)
    # Bound report reads to avoid accidentally loading enormous or malformed artifacts.
    if report_path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("source report exceeds 50 MiB; use a smaller report artifact")
    source = json.loads(report_path.read_text(encoding="utf-8"))
    findings = source.get("findings") if isinstance(source, dict) else None
    if not isinstance(findings, list) or not findings:
        raise ValueError("source report contains no findings to replay")
    if args.finding < 1 or args.finding > len(findings):
        raise ValueError(f"finding must be between 1 and {len(findings)}")
    finding = findings[args.finding - 1]
    if not isinstance(finding, dict) or not isinstance(finding.get("input"), str):
        raise ValueError("selected finding does not contain a text input")
    input_text = finding["input"]
    if len(input_text.encode("utf-8")) > 10 * 1024 * 1024:
        raise ValueError("selected input exceeds 10 MiB; replay it with a dedicated corpus workflow")

    contract = load_contract(args.contract) if args.contract else None
    replay_report = run_comparison(
        reference=args.reference,
        candidate=args.candidate,
        cases=1,
        strategy="text",
        timeout=args.timeout,
        cwd=args.cwd,
        minimize=False,
        normalize_eol=args.normalize_eol,
        ignore_trailing_whitespace=args.ignore_trailing_whitespace,
        ignore_stderr=args.ignore_stderr,
        ignore_exit_code=args.ignore_exit_code,
        repeat=args.repeat,
        max_output_bytes=args.max_output_bytes,
        input_cases=[input_text],
        input_source="saved-report-replay",
        contract=contract,
    )
    replay_report["replay"] = {
        "source_report": str(report_path),
        "source_finding_number": args.finding,
        "source_input_sha256": finding.get("input_sha256"),
        "note": "Commands were supplied explicitly to this replay invocation; saved commands were not executed.",
    }
    return replay_report


def _run_replay_pack(args: argparse.Namespace) -> dict[str, object]:
    inputs, contract, manifest = load_compatibility_pack(args.pack)
    if args.contract:
        supplied_contract = load_contract(args.contract)
        if supplied_contract.sha256 != contract.sha256:
            raise ValueError(
                "supplied --contract does not match the contract pinned in the pack; "
                "export a new pack to deliberately change the compatibility rules"
            )
    report = run_comparison(
        reference=args.reference,
        candidate=args.candidate,
        cases=len(inputs),
        strategy="text",
        timeout=args.timeout,
        cwd=args.cwd,
        minimize=False,
        normalize_eol=args.normalize_eol,
        ignore_trailing_whitespace=args.ignore_trailing_whitespace,
        ignore_stderr=args.ignore_stderr,
        ignore_exit_code=args.ignore_exit_code,
        repeat=args.repeat,
        max_output_bytes=args.max_output_bytes,
        input_cases=inputs,
        input_source="compatibility-pack-replay",
        contract=contract,
    )
    report["compatibility_pack"] = {
        "path": str(Path(args.pack)),
        "schema_version": manifest["schema_version"],
        "source_report_sha256": manifest.get("source_report_sha256"),
        "contract_sha256": manifest["contract_sha256"],
        "case_count": len(inputs),
        "note": "Commands were supplied explicitly to this replay invocation; saved commands are never executed.",
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "export-pack":
            manifest = export_cases_from_report(args.report, args.output)
            print(f"Exported {manifest['case_count']} unique counterexample(s) to {Path(args.output)}")
            print(f"Pinned contract SHA-256: {manifest['contract_sha256']}")
            return 0
        if args.subcommand == "export-http-sequence-pack":
            manifest = export_stateful_sequence_pack(args.report, args.output, finding_number=args.finding)
            print(f"Exported stateful HTTP finding {manifest['source_finding_number']} to {Path(args.output)}")
            print(f"Sequence SHA-256: {manifest['sequence_file_sha256']}")
            print(f"Pinned contract SHA-256: {manifest['contract_sha256']}")
            return 0
        if args.subcommand == "replay-http-sequence-pack":
            if not args.allow_side_effects:
                raise ValueError("stateful HTTP regression-pack replay requires --allow-side-effects; saved steps may modify local service data")
            sequence, sequence_digest, reset_sequence, reset_digest, contract, manifest = load_stateful_sequence_pack(args.pack)
            report = run_http_sequence_comparison(
                reference_url=args.reference_url, candidate_url=args.candidate_url, sequence=sequence,
                sequence_sha256=sequence_digest, timeout=args.timeout, repeat=args.repeat,
                max_output_bytes=args.max_output_bytes, request_headers=parse_request_headers(args.header),
                response_headers=args.response_header, contract=contract, reset_sequence=reset_sequence,
                reset_sequence_sha256=reset_digest,
            )
            report["stateful_regression_pack"] = {
                "path": str(Path(args.pack)), "schema_version": manifest["schema_version"],
                "source_report_sha256": manifest["source_report_sha256"],
                "source_finding_number": manifest["source_finding_number"],
                "sequence_file_sha256": manifest["sequence_file_sha256"],
                "contract_sha256": manifest["contract_sha256"], "reset_enabled": manifest["reset_enabled"],
            }
            report["replay"] = {"side_effects_acknowledged": True, "request_header_values_recorded": False,
                                "source_sequence_sha256": manifest["sequence_source_sha256"]}
            return _write_outputs(args, report)
        if args.subcommand == "replay-pack":
            report = _run_replay_pack(args)
        elif args.subcommand == "replay":
            report = _run_replay(args)
        elif args.subcommand == "replay-http-sequence":
            if not args.allow_side_effects:
                raise ValueError("stateful HTTP replay requires --allow-side-effects; saved steps may modify local service data")
            report_path = Path(args.report)
            if report_path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("source report exceeds 50 MiB")
            source_report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(source_report, dict) or source_report.get("input_source") not in {
                "stateful-http-sequence", "stateful-http-exploration"
            }:
                raise ValueError("source report is not a TwinCheck stateful HTTP sequence or exploration report")
            source_findings = source_report.get("findings")
            if not isinstance(source_findings, list) or not source_findings:
                raise ValueError("source report contains no stateful sequence findings to replay")
            if args.finding < 1 or args.finding > len(source_findings):
                raise ValueError(f"finding must be between 1 and {len(source_findings)}")
            selected_finding = source_findings[args.finding - 1]
            if not isinstance(selected_finding, dict):
                raise ValueError("selected finding is malformed")
            sequence = selected_finding.get("sequence_definition")
            validate_sequence(sequence)
            digest = selected_finding.get("sequence_file_sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("selected finding does not contain a valid source sequence hash")
            canonical_sequence = json.dumps(sequence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            canonical_digest = hashlib.sha256(canonical_sequence.encode("utf-8")).hexdigest()
            if selected_finding.get("sequence_canonical_sha256") != canonical_digest:
                raise ValueError("saved stateful sequence does not match its canonical SHA-256; report may have been modified")
            saved_contract = source_report.get("compatibility_contract")
            if not isinstance(saved_contract, dict):
                raise ValueError("source report does not contain a compatibility contract")
            contract = contract_from_dict(saved_contract)
            if source_report.get("compatibility_contract_sha256") != contract.sha256:
                raise ValueError("saved compatibility contract hash does not match the report")
            saved_reset = source_report.get("state_reset", {})
            if not isinstance(saved_reset, dict):
                raise ValueError("source report state_reset metadata is malformed")
            reset_sequence = None
            reset_sequence_digest = None
            if saved_reset.get("enabled"):
                embedded_reset = saved_reset.get("sequence_definition")
                validate_sequence(embedded_reset)
                canonical_reset = json.dumps(embedded_reset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                canonical_reset_digest = hashlib.sha256(canonical_reset.encode("utf-8")).hexdigest()
                if saved_reset.get("canonical_sha256") != canonical_reset_digest:
                    raise ValueError("saved reset sequence canonical SHA-256 does not match; report may have been modified")
                reset_sequence = embedded_reset
                reset_sequence_digest = saved_reset.get("sequence_sha256")
                if not isinstance(reset_sequence_digest, str) or len(reset_sequence_digest) != 64 or any(char not in "0123456789abcdef" for char in reset_sequence_digest):
                    raise ValueError("saved reset sequence does not contain a valid source SHA-256")
            if args.reset_sequence:
                supplied_reset, supplied_reset_digest = load_sequence(args.reset_sequence)
                supplied_canonical = json.dumps(supplied_reset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if reset_sequence is not None and hashlib.sha256(supplied_canonical.encode("utf-8")).hexdigest() != saved_reset.get("canonical_sha256"):
                    raise ValueError("supplied --reset-sequence differs from the reset workflow pinned in the report")
                reset_sequence, reset_sequence_digest = supplied_reset, supplied_reset_digest
            report = run_http_sequence_comparison(
                reference_url=args.reference_url,
                candidate_url=args.candidate_url,
                sequence=sequence,
                sequence_sha256=digest,
                timeout=args.timeout,
                repeat=args.repeat,
                max_output_bytes=args.max_output_bytes,
                request_headers=parse_request_headers(args.header),
                response_headers=args.response_header,
                contract=contract,
                reset_sequence=reset_sequence,
                reset_sequence_sha256=reset_sequence_digest,
            )
            report["replay"] = {
                "source_report_path": str(report_path),
                "source_finding_number": args.finding,
                "source_sequence_sha256": digest,
                "side_effects_acknowledged": True,
                "reset_sequence_sha256": reset_sequence_digest,
                "request_header_values_recorded": False,
            }
        elif args.subcommand == "explore-http-sequence":
            if not args.allow_side_effects:
                raise ValueError("stateful HTTP exploration requires --allow-side-effects; generated sequences may modify local service data")
            sequence, sequence_digest = load_sequence(args.sequence)
            reset_sequence, reset_sequence_digest = load_sequence(args.reset_sequence)
            headers = parse_request_headers(args.header)
            report = run_http_sequence_exploration(
                reference_url=args.reference_url,
                candidate_url=args.candidate_url,
                sequence=sequence,
                sequence_sha256=sequence_digest,
                reset_sequence=reset_sequence,
                reset_sequence_sha256=reset_sequence_digest,
                seed=args.seed,
                max_cases=args.cases,
                timeout=args.timeout,
                repeat=args.repeat,
                max_output_bytes=args.max_output_bytes,
                request_headers=headers,
                response_headers=args.response_header,
                contract=load_contract(args.contract) if args.contract else None,
                minimize=args.minimize,
                max_findings_to_minimize=args.max_findings_to_minimize,
                max_minimization_trials=args.max_minimization_trials,
            )
        elif args.subcommand == "compare-http-sequence":
            sequence, sequence_digest = load_sequence(args.sequence)
            if args.reset_sequence:
                reset_sequence, reset_sequence_digest = load_sequence(args.reset_sequence)
            else:
                reset_sequence, reset_sequence_digest = None, None
            headers = parse_request_headers(args.header)
            report = run_http_sequence_comparison(
                reference_url=args.reference_url,
                candidate_url=args.candidate_url,
                sequence=sequence,
                sequence_sha256=sequence_digest,
                timeout=args.timeout,
                repeat=args.repeat,
                max_output_bytes=args.max_output_bytes,
                request_headers=headers,
                response_headers=args.response_header,
                contract=load_contract(args.contract) if args.contract else None,
                reset_sequence=reset_sequence,
                reset_sequence_sha256=reset_sequence_digest,
            )
        elif args.subcommand == "compare-http":
            schema_doc = load_json_schema(args.schema)
            inputs = generate_schema_inputs(schema_doc.schema, count=args.cases, seed=args.seed)
            headers = parse_request_headers(args.header)
            report = run_http_comparison(
                reference_url=args.reference_url,
                candidate_url=args.candidate_url,
                method=args.method,
                path=args.path,
                inputs=inputs,
                seed=args.seed,
                timeout=args.timeout,
                repeat=args.repeat,
                max_output_bytes=args.max_output_bytes,
                request_headers=headers,
                response_headers=args.response_header,
                contract=load_contract(args.contract) if args.contract else None,
                schema_sha256=schema_doc.sha256,
                schema_title=schema_doc.title,
                requested_cases=args.cases,
            )
        else:
            schema_inputs = None
            input_source = None
            input_metadata = None
            strategy = args.strategy
            if args.schema:
                if args.corpus:
                    raise ValueError("--schema and --corpus cannot be combined in this release; choose schema-guided generation or a saved corpus")
                schema_doc = load_json_schema(args.schema)
                schema_inputs = generate_schema_inputs(schema_doc.schema, count=args.cases, seed=args.seed)
                input_source = "json-schema"
                strategy = "json-schema"
                input_metadata = {
                    "method": "json-schema",
                    "json_schema_sha256": schema_doc.sha256,
                    "schema_title": schema_doc.title,
                    "unique_sample_count": len(schema_inputs),
                    "seed": args.seed,
                }
            report = run_comparison(
                reference=args.reference,
                candidate=args.candidate,
                cases=args.cases,
                seed=args.seed,
                strategy=strategy,
                timeout=args.timeout,
                cwd=args.cwd,
                corpus=args.corpus,
                minimize=args.minimize,
                max_minimize=args.max_minimize,
                max_minimization_trials=args.max_minimization_trials,
                normalize_eol=args.normalize_eol,
                ignore_trailing_whitespace=args.ignore_trailing_whitespace,
                ignore_stderr=args.ignore_stderr,
                ignore_exit_code=args.ignore_exit_code,
                repeat=args.repeat,
                max_output_bytes=args.max_output_bytes,
                input_cases=schema_inputs,
                input_source=input_source,
                input_metadata=input_metadata,
                contract=load_contract(args.contract) if args.contract else None,
            )
        return _write_outputs(args, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"twincheck: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("twincheck: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
