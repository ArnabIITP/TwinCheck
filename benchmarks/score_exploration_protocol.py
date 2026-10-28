#!/usr/bin/env python3
"""Score the pinned static/adaptive exploration report against corpus ground truth.

A case is a seeded defect if either mode is expected to find it. A case is a
clean control only if neither mode is expected to find it. This distinction
makes a defect missed by static exploration count as a false negative rather
than redefining it as a clean case.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "exploration-corpus-v1" / "manifest.json"


class ScorecardError(ValueError):
    """Input evidence cannot be scored safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ScorecardError(f"cannot read JSON file {path}: {exc}") from exc


def build_scorecard(manifest: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    cases = manifest.get("cases")
    results = report.get("results")
    if not isinstance(cases, list) or not isinstance(results, list):
        raise ScorecardError("manifest cases and report results must be arrays")
    truth: dict[str, bool] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ScorecardError("manifest contains a malformed case")
        expected = case.get("expected", {})
        modes = [expected.get(mode, {}).get("finding") for mode in ("static", "adaptive")]
        if any(not isinstance(value, bool) for value in modes):
            raise ScorecardError(f"{case['id']}: each mode must declare an expected finding boolean")
        truth[case["id"]] = any(modes)

    observed: dict[tuple[str, str, int, int], bool] = {}
    for item in results:
        if not isinstance(item, dict):
            raise ScorecardError("report contains a malformed result row")
        case_id, mode = item.get("case_id"), item.get("mode")
        seed, round_index, finding = item.get("seed"), item.get("round"), item.get("finding")
        if case_id not in truth or mode not in ("static", "adaptive"):
            raise ScorecardError(f"result references an unknown case or mode: {case_id!r}/{mode!r}")
        if not isinstance(seed, int) or not isinstance(round_index, int) or not isinstance(finding, bool):
            raise ScorecardError(f"{case_id}/{mode}: invalid seed, round, or finding value")
        key = (case_id, mode, seed, round_index)
        if key in observed:
            raise ScorecardError(f"duplicate result row: {key}")
        observed[key] = finding

    expected_rows = sum(len(case.get("seeds", [])) * 2 * report.get("settings", {}).get("rounds", 0) for case in cases)
    if len(observed) != expected_rows:
        raise ScorecardError(f"incomplete evidence: expected {expected_rows} result rows, found {len(observed)}")
    if not report.get("passed", False):
        raise ScorecardError("protocol report is not marked passed; score only passing evidence")

    per_mode: dict[str, Any] = {}
    for mode in ("static", "adaptive"):
        tp = fp = tn = fn = 0
        for (case_id, row_mode, _seed, _round), found in observed.items():
            if row_mode != mode:
                continue
            actual_defect = truth[case_id]
            if actual_defect and found:
                tp += 1
            elif actual_defect and not found:
                fn += 1
            elif not actual_defect and found:
                fp += 1
            else:
                tn += 1
        total = tp + fp + tn + fn
        per_mode[mode] = {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "runs": total,
            "detection_rate": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
        }

    return {
        "schema_version": 1,
        "scorecard": "TwinCheck synthetic exploration scorecard v1",
        "ground_truth_rule": "A scenario is a seeded defect when either mode's pinned expectation requires a finding; otherwise it is a clean control.",
        "scope": "Pinned synthetic fixtures, seeds and execution budgets only. These metrics are not estimates of real-world defect detection or false-positive rates.",
        "source_protocol_passed": report["passed"],
        "case_labels": {
            case_id: ("seeded_defect" if is_defect else "clean_control")
            for case_id, is_defect in sorted(truth.items())
        },
        "modes": per_mode,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="JSON report from run_exploration_protocol.py")
    parser.add_argument("--manifest", default=str(MANIFEST), help="ground-truth corpus manifest")
    parser.add_argument("--output", help="optional path for the scorecard JSON")
    args = parser.parse_args(argv)
    try:
        scorecard = build_scorecard(_read_json(Path(args.manifest)), _read_json(Path(args.report)))
        rendered = json.dumps(scorecard, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (ScorecardError, OSError, TypeError) as exc:
        print(f"[FAIL] exploration scorecard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
