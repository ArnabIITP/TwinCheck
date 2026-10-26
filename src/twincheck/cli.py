"""Command-line interface for TwinCheck."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .engine import run_comparison
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
    compare.add_argument("--minimize", action="store_true", help="shrink stable failing inputs using bounded delta debugging")
    compare.add_argument("--max-minimize", type=int, default=1, help="maximum findings to minimize (default: 1)")
    compare.add_argument("--max-minimization-trials", type=int, default=30, help="trial budget per minimized finding (default: 30)")

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
    )
    replay_report["replay"] = {
        "source_report": str(report_path),
        "source_finding_number": args.finding,
        "source_input_sha256": finding.get("input_sha256"),
        "note": "Commands were supplied explicitly to this replay invocation; saved commands were not executed.",
    }
    return replay_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "replay":
            report = _run_replay(args)
        else:
            report = run_comparison(
                reference=args.reference,
                candidate=args.candidate,
                cases=args.cases,
                seed=args.seed,
                strategy=args.strategy,
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
