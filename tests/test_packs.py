import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from twincheck.contract import CompatibilityContract
from twincheck.packs import export_cases_from_report, load_compatibility_pack


class PackTests(unittest.TestCase):
    def report(self, *inputs):
        findings = []
        for index, input_text in enumerate(inputs, start=1):
            digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
            findings.append({
                "case_index": index,
                "input": input_text,
                "input_sha256": digest,
                "differences": ["stdout"],
            })
        contract = CompatibilityContract()
        return {
            "tool": "TwinCheck",
            "tool_version": "test",
            "schema_version": "1.2",
            "compatibility_contract": contract.to_dict(),
            "compatibility_contract_sha256": contract.sha256,
            "findings": findings,
        }

    def test_export_round_trips_exact_utf8_inputs_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            output_path = root / "pack"
            # CRLF and NUL are deliberate: input bytes must not be newline-normalized.
            report_path.write_text(json.dumps(self.report("line1\r\nline2\x00", "line1\r\nline2\x00", "other")), encoding="utf-8")
            manifest = export_cases_from_report(report_path, output_path)
            self.assertEqual(manifest["case_count"], 2)
            self.assertEqual(manifest["contract_sha256"], CompatibilityContract().sha256)
            inputs, contract, loaded_manifest = load_compatibility_pack(output_path)
            self.assertEqual(inputs, ["line1\r\nline2\x00", "other"])
            self.assertEqual(contract.sha256, manifest["contract_sha256"])
            self.assertEqual(loaded_manifest["source_report_sha256"], manifest["source_report_sha256"])

    def test_pack_detects_tampered_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            pack_path = root / "pack"
            report_path.write_text(json.dumps(self.report("valid input")), encoding="utf-8")
            export_cases_from_report(report_path, pack_path)
            case_path = next((pack_path / "cases").glob("*.txt"))
            case_path.write_text("tampered input", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 verification failed"):
                load_compatibility_pack(pack_path)

    def test_export_rejects_mismatched_report_contract_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            report = self.report("input")
            report["compatibility_contract_sha256"] = "0" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                export_cases_from_report(report_path, root / "pack")

    def test_export_will_not_overwrite_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            destination = root / "pack"
            destination.mkdir()
            report_path.write_text(json.dumps(self.report("input")), encoding="utf-8")
            with self.assertRaises(FileExistsError):
                export_cases_from_report(report_path, destination)


if __name__ == "__main__":
    unittest.main()
