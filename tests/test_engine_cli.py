import json
import sys
import tempfile
import unittest
from pathlib import Path

from twincheck.cli import main
from twincheck.engine import run_comparison

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    def test_comparison_finds_and_minimizes_example_bug(self):
        report = run_comparison(
            f'"{sys.executable}" examples/reference.py',
            f'"{sys.executable}" examples/candidate.py',
            cases=8,
            seed=7,
            strategy="text",
            cwd=str(ROOT),
            minimize=True,
            max_minimize=1,
            max_minimization_trials=12,
        )
        self.assertGreater(report["summary"]["differences_found"], 0)
        self.assertEqual(report["cases_executed"], 8)
        self.assertTrue(all(item["input_sha256"] for item in report["findings"]))

    def test_cli_writes_valid_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested" / "report.json"
            code = main([
                "compare",
                "--reference", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--candidate", f'"{sys.executable}" -c "import sys; sys.stdout.write(sys.stdin.read())"',
                "--cases", "5", "--strategy", "text", "--output", str(output),
            ])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["differences_found"], 0)
            self.assertEqual(report["cases_executed"], 5)

    def test_cli_returns_one_when_difference_found(self):
        code = main([
            "compare",
            "--reference", f'"{sys.executable}" -c "print(1)"',
            "--candidate", f'"{sys.executable}" -c "print(2)"',
            "--cases", "1", "--strategy", "text",
        ])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
