"""Compatibility tests for TwinCheck's supported public Python API."""
from __future__ import annotations

import json
import shlex
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import twincheck
from twincheck import (
    API_VERSION,
    CONTRACT_SCHEMA_VERSION,
    CompatibilityContract,
    OutputContract,
    compare_commands,
    contract_from_dict,
    load_contract,
    report_as_json,
    write_json_report,
    write_junit_report,
)
from twincheck import api


class PublicAPITests(unittest.TestCase):
    def test_api_version_and_root_exports_match_api_module(self):
        self.assertEqual(API_VERSION, 1)
        self.assertEqual(twincheck.API_VERSION, api.API_VERSION)
        self.assertEqual(set(api.__all__), set(twincheck.__all__) - {"__version__"})
        for name in api.__all__:
            with self.subTest(name=name):
                self.assertIs(getattr(twincheck, name), getattr(api, name))
        self.assertEqual(CONTRACT_SCHEMA_VERSION, 1)
        self.assertIs(CompatibilityContract, api.CompatibilityContract)
        self.assertIs(OutputContract, api.OutputContract)

    def test_compare_commands_returns_a_versioned_evidence_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference_script = root / "reference.py"
            candidate_script = root / "candidate.py"
            reference_script.write_text(
                "import sys\\nsys.stdout.write(sys.stdin.read().upper())\\n",
                encoding="utf-8",
            )
            candidate_script.write_text(
                "import sys\\nsys.stdout.write(sys.stdin.read().lower())\\n",
                encoding="utf-8",
            )
            reference_command = shlex.join([sys.executable, str(reference_script)])
            candidate_command = shlex.join([sys.executable, str(candidate_script)])
            contract = contract_from_dict({"name": "public-api-smoke"})

            report = compare_commands(
                reference_command,
                candidate_command,
                cases=3,
                strategy="text",
                seed=0,
                contract=contract,
            )

            self.assertIn("schema_version", report)
            self.assertEqual(report["tool"], "TwinCheck")
            self.assertEqual(report["cases_requested"], 3)
            self.assertEqual(report["cases_executed"], 3)
            self.assertGreater(report["summary"]["differences_found"], 0)
            self.assertEqual(report["compatibility_contract"], contract.to_dict())
            self.assertEqual(report["compatibility_contract_sha256"], contract.sha256)
            self.assertEqual(json.loads(report_as_json(report)), report)

    def test_public_contract_loading_and_report_writers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps({"name": "public-contract", "stdout": {"mode": "json"}}),
                encoding="utf-8",
            )
            contract = load_contract(contract_path)
            self.assertEqual(contract.name, "public-contract")
            self.assertEqual(contract.stdout.mode, "json")
            self.assertEqual(contract, contract_from_dict(contract.to_dict()))

            report = {
                "tool": "TwinCheck",
                "tool_version": twincheck.__version__,
                "schema_version": "1.2",
                "strategy": "text",
                "seed": 1,
                "repeat": 1,
                "summary": {"differences_found": 0},
                "cases_executed": 1,
                "elapsed_seconds": 0.001,
                "findings": [],
                "executions": [
                    {"case_index": 1, "input_sha256": "a" * 64, "differences": []}
                ],
            }
            json_path = root / "report.json"
            junit_path = root / "report.xml"
            write_json_report(json_path, report)
            write_junit_report(junit_path, report)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), report)
            self.assertEqual(ET.parse(junit_path).getroot().tag, "testsuite")


if __name__ == "__main__":
    unittest.main()
