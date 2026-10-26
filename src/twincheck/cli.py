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
from .report import print_summary, report_as_json, write_json_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twincheck",
        description="Find behavioral differences between two command-line programs.",
        epilog=(
            "Commands are parsed without a shell. By default each input is sent to stdin; "
            "use {input} in an argument to pass the input as an argv value."
        ),
    )
    parser.add_argument("--version", action="version", version=f"TwinCheck {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    compare = subparsers.add_parser("compare", help="compare two implementations using generated inputs")
    compare.add_argument("--reference", required=True, help="command for the reference implementation")
    compare.add_argument("--candidate", required=True, help="command for the implementation under test")
    compare.add_argument("--cases", type=int, default=100, help="number of unique inputs to run (default: 100)")
    compare.add_argument("--seed", type=int, default=0, help="random seed for reproducible input generation")
    compare.add_argument("--strategy", choices=STRATEGIES, default="mixed", help="input generation strategy")
    compare.add_argument("--timeout", type=float, default=2.0, help="timeout per process, in seconds (default: 2)")
    compare.add_argument("--cwd", help="working directory for both programs")
    compare.add_argument("--corpus", help="directory of UTF-8 input files to try before generated inputs")
    compare.add_argument("--minimize", action="store_true", help="try to shrink inputs that expose differences")
    compare.add_argument("--max-minimize", type=int, default=1, help="maximum findings to minimize (default: 1)")
    compare.add_argument("--max-minimization-trials", type=int, default=30, help="trial budget per minimized finding (default: 30)")
    compare.add_argument("--normalize-eol", action="store_true", help="treat CRLF and CR as LF in outputs")
    compare.add_argument("--ignore-trailing-whitespace", action="store_true", help="ignore spaces/tabs at line ends")
    compare.add_argument("--ignore-stderr", action="store_true", help="do not compare standard error")
    compare.add_argument("--ignore-exit-code", action="store_true", help="do not compare process exit codes")
    compare.add_argument("--output", help="write a machine-readable JSON report to this path")
    compare.add_argument("--format", choices=("text", "json"), default="text", help="console output format")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand != "compare":
        parser.error("unknown command")

    try:
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
        )
        if args.output:
            write_json_report(args.output, report)
        if args.format == "json":
            print(report_as_json(report))
        else:
            print_summary(report, stream=sys.stdout)
            if args.output:
                print(f"\nJSON report: {Path(args.output)}")
        return 1 if report["findings"] else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"twincheck: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("twincheck: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
