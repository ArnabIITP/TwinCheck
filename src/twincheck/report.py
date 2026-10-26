"""JSON report serialization and human-readable summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "1.0"


def write_json_report(path: str | Path, report: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def print_summary(report: dict[str, Any], *, stream: Any) -> None:
    findings = report["findings"]
    print("TwinCheck differential report", file=stream)
    print("=" * 28, file=stream)
    print(f"Strategy:          {report['strategy']}", file=stream)
    print(f"Seed:              {report['seed']}", file=stream)
    print(f"Cases executed:    {report['cases_executed']}", file=stream)
    print(f"Differences found: {len(findings)}", file=stream)
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
