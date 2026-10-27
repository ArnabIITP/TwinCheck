import contextlib
import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from twincheck.cli import main
from twincheck.engine import run_comparison

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @staticmethod
    def call_main(arguments):
        with contextlib.redirect_stdout(io.StringIO()):
            return main(arguments)

    def test_comparison_finds_and_minimizes_example_bug(self):
        report = run_comparison(
            f'"{sys.executable}" examples/reference.py',
            f'"{sys.executable}" examples/candidate.py',
            cases=1,
            seed=7,
            strategy="text",
            cwd=str(ROOT),
            input_cases=["\n"],
            minimize=True,
            max_minimize=1,
            max_minimization_trials=3,
        )
        self.assertGreater(report["summary"]["differences_found"], 0)
        self.assertEqual(report["cases_executed"], 1)
        self.assertTrue(all(item["input_sha256"] for item in report["findings"]))

    def test_cli_writes_valid_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested" / "report.json"
            code = self.call_main([
                "compare",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--cases", "2", "--strategy", "text", "--output", str(output),
            ])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["differences_found"], 0)
            self.assertEqual(report["cases_executed"], 2)
            self.assertEqual(len(report["executions"]), 2)

    def test_cli_returns_one_when_difference_found(self):
        code = self.call_main([
            "compare",
            "--reference", f'"{sys.executable}" -c "print(1)"',
            "--candidate", f'"{sys.executable}" -c "print(2)"',
            "--cases", "1", "--strategy", "text",
        ])
        self.assertEqual(code, 1)

    def test_cli_writes_junit_xml_for_all_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "reports" / "results.xml"
            code = self.call_main([
                "compare",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--cases", "1", "--strategy", "text", "--junit", str(junit),
            ])
            self.assertEqual(code, 0)
            root = ET.parse(junit).getroot()
            self.assertEqual(root.attrib["tests"], "1")
            self.assertEqual(len(root.findall("testcase")), 1)

    def test_compare_cli_generates_inputs_from_json_schema_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "request.schema.json"
            report_path = Path(tmp) / "report.json"
            schema_path.write_text(json.dumps({
                "title": "EchoRequest",
                "type": "object",
                "required": ["quantity"],
                "properties": {"quantity": {"type": "integer", "minimum": 0, "maximum": 10}},
                "additionalProperties": False,
            }), encoding="utf-8")
            echo = f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"'
            code = self.call_main([
                "compare", "--reference", echo, "--candidate", echo,
                "--schema", str(schema_path), "--cases", "2", "--seed", "11",
                "--output", str(report_path),
            ])
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["input_source"], "json-schema")
            self.assertEqual(report["strategy"], "json-schema")
            self.assertEqual(report["input_generation"]["schema_title"], "EchoRequest")
            self.assertEqual(len(report["input_generation"]["json_schema_sha256"]), 64)

    def test_replay_uses_saved_input_and_explicit_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.json"
            replay = Path(tmp) / "replay.json"
            code = self.call_main([
                "compare",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(\'different\')"',
                "--cases", "1", "--strategy", "text", "--output", str(source),
            ])
            self.assertEqual(code, 1)
            code = self.call_main([
                "replay", "--report", str(source), "--finding", "1",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(\'different\')"',
                "--output", str(replay),
            ])
            self.assertEqual(code, 1)
            report = json.loads(replay.read_text(encoding="utf-8"))
            self.assertEqual(report["input_source"], "saved-report-replay")
            self.assertEqual(report["replay"]["source_finding_number"], 1)
            self.assertEqual(report["cases_executed"], 1)


    def test_counterexample_pack_replays_after_candidate_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "source-report.json"
            pack_path = Path(tmp) / "regression-pack"
            replay_path = Path(tmp) / "replayed-report.json"
            buggy = self.call_main([
                "compare",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "print(\'different\')"',
                "--cases", "1", "--strategy", "text", "--output", str(report_path),
            ])
            self.assertEqual(buggy, 1)
            exported = self.call_main(["export-pack", "--report", str(report_path), "--output", str(pack_path)])
            self.assertEqual(exported, 0)
            fixed = self.call_main([
                "replay-pack", "--pack", str(pack_path),
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--output", str(replay_path),
            ])
            self.assertEqual(fixed, 0)
            replayed = json.loads(replay_path.read_text(encoding="utf-8"))
            self.assertEqual(replayed["input_source"], "compatibility-pack-replay")
            self.assertEqual(replayed["compatibility_pack"]["case_count"], 1)
            self.assertEqual(replayed["summary"]["differences_found"], 0)

    def test_json_compatibility_contract_ignores_declared_volatile_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "contract-report.json"
            contract_path = ROOT / "examples" / "contracts" / "json-api-v1.json"
            code = self.call_main([
                "compare",
                "--reference", f'"{sys.executable}" "{ROOT / "examples/json_reference.py"}"',
                "--candidate", f'"{sys.executable}" "{ROOT / "examples/json_candidate.py"}"',
                "--cases", "3", "--seed", "17", "--strategy", "json",
                "--cwd", str(ROOT), "--contract", str(contract_path),
                "--output", str(report_path),
            ])
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["differences_found"], 0)
            self.assertEqual(report["compatibility_contract"]["stdout"]["mode"], "json")
            self.assertEqual(len(report["compatibility_contract_sha256"]), 64)

    def test_repeat_is_recorded_and_unstable_behavior_is_reported(self):
        report = run_comparison(
            f'"{sys.executable}" -c "print(1)"',
            f'"{sys.executable}" -c "import time; print(time.time_ns())"',
            cases=1,
            strategy="text",
            repeat=2,
        )
        self.assertEqual(report["repeat"], 2)
        self.assertIn("candidate_unstable", report["findings"][0]["differences"])
        self.assertEqual(len(report["findings"][0]["candidate_runs"]), 2)


if __name__ == "__main__":
    unittest.main()
