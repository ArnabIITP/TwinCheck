"""JSON and JUnit report writers for TwinCheck."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, TextIO

REPORT_SCHEMA_VERSION = "1.1"


def write_json_report(path: str | Path, report: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def print_summary(report: dict[str, Any], *, stream: TextIO) -> None:
    findings = report["findings"]
    summary = report["summary"]
    print("TwinCheck differential report", file=stream)
    print("=" * 34, file=stream)
    print(f"Strategy:          {report['strategy']}", file=stream)
    print(f"Seed:              {report['seed']}", file=stream)
    print(f"Repeat runs:       {report.get('repeat', 1)}", file=stream)
    print(f"Cases executed:    {report['cases_executed']}", file=stream)
    print(f"Differences found: {summary['differences_found']}", file=stream)
    if summary.get("unstable_reference_findings") or summary.get("unstable_candidate_findings"):
        print(
            "Unstable targets:  "
            f"reference={summary.get('unstable_reference_findings', 0)}, "
            f"candidate={summary.get('unstable_candidate_findings', 0)}",
            file=stream,
        )
    if summary.get("truncated_output_findings"):
        print(f"Truncated output:   {summary['truncated_output_findings']} finding(s)", file=stream)
    if summary.get("output_limit_findings"):
        print(f"Output limit:       {summary['output_limit_findings']} finding(s)", file=stream)
    print(f"Elapsed:           {report['elapsed_seconds']:.3f}s", file=stream)
    for index, finding in enumerate(findings[:10], start=1):
        preview = finding["input"].encode("unicode_escape").decode("ascii")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        minimized = " (minimized)" if finding.get("minimized") else ""
        print(f"\n[{index}] {', '.join(finding['differences'])}{minimized}", file=stream)
        print(f"    input: {preview!r}", file=stream)
    if len(findings) > 10:
        print(f"\n... {len(findings) - 10} additional finding(s) in the JSON report", file=stream)


def write_junit_report(path: str | Path, report: dict[str, Any]) -> None:
    """Write JUnit XML with one testcase for each tested input.

    The failure text contains hashes and difference categories, not raw test
    input, to avoid leaking credentials or sensitive corpus values into CI logs.
    Store the JSON report as the evidence artifact.
    """
    executions = report.get("executions", [])
    by_index = {finding["case_index"]: finding for finding in report.get("findings", [])}
    failures = sum(1 for item in executions if item.get("differences"))
    suite = ET.Element("testsuite", {
        "name": "TwinCheck",
        "tests": str(len(executions)),
        "failures": str(failures),
        "errors": "0",
        "skipped": "0",
        "time": f"{float(report.get('elapsed_seconds', 0.0)):.6f}",
    })
    for execution in executions:
        index = execution.get("case_index", 0)
        digest = str(execution.get("input_sha256", "unknown"))
        categories = execution.get("differences", [])
        case = ET.SubElement(suite, "testcase", {
            "classname": "TwinCheck.differential",
            "name": f"case-{index}-{digest[:12]}",
            "time": "0",
        })
        if categories:
            failure = ET.SubElement(case, "failure", {
                "message": ", ".join(str(category) for category in categories),
                "type": "BehavioralDifference",
            })
            failure.text = (
                f"Input SHA-256: {digest}. Difference categories: {', '.join(categories)}. "
                "See the TwinCheck JSON report for the minimized input and execution evidence."
            )
    tree = ET.ElementTree(suite)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
