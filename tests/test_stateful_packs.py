import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from twincheck.contract import CompatibilityContract
from twincheck.stateful_packs import export_stateful_sequence_pack, load_stateful_sequence_pack


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class StatefulPackTests(unittest.TestCase):
    def sequence(self, name="cart-flow"):
        return {
            "schema_version": 1,
            "name": name,
            "steps": [
                {"name": "create", "method": "POST", "path": "/cart", "body": {"sku": "x"}, "capture": {"cart_id": "/id"}},
                {"name": "read", "method": "GET", "path": "/cart/{{cart_id}}"},
            ],
        }

    def report(self, *, with_reset=False, source="stateful-http-sequence"):
        sequence = self.sequence()
        original_bytes = (json.dumps(sequence, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        contract_obj = CompatibilityContract()
        contract = contract_obj.to_dict()
        reset = self.sequence("reset-cart") if with_reset else None
        reset_original = (json.dumps(reset, ensure_ascii=False, indent=2) + "\n").encode("utf-8") if reset else None
        finding = {
            "sequence_definition": sequence,
            "sequence_file_sha256": sha256(original_bytes),
            "sequence_canonical_sha256": sha256(canonical(sequence)),
            "differences": ["json_body"],
            "step_results": [{"reference": {"stdout": "secret response body"}}],
        }
        return {
            "tool": "TwinCheck", "tool_version": "0.7.0a1", "input_source": source,
            "compatibility_contract": contract, "compatibility_contract_sha256": contract_obj.sha256,
            "state_reset": {
                "enabled": bool(reset), "sequence_definition": reset,
                "sequence_sha256": sha256(reset_original) if reset_original else None,
                "canonical_sha256": sha256(canonical(reset)) if reset else None,
            },
            "findings": [finding],
        }

    def write_report(self, root, report):
        path = root / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_export_and_load_pins_sequence_reset_and_contract_without_response_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = self.write_report(root, self.report(with_reset=True))
            manifest = export_stateful_sequence_pack(report_path, root / "pack")
            sequence, sequence_hash, reset, reset_hash, contract, loaded = load_stateful_sequence_pack(root / "pack")
            self.assertEqual(sequence["name"], "cart-flow")
            self.assertEqual(loaded["sequence_file_sha256"], sequence_hash)
            self.assertEqual(loaded["contract_sha256"], contract.sha256)
            self.assertEqual(reset["name"], "reset-cart")
            self.assertEqual(loaded["reset_sequence_file_sha256"], reset_hash)
            self.assertTrue(manifest["reset_enabled"])
            pack_text = "".join(p.read_text(encoding="utf-8") for p in (root / "pack").glob("*.json"))
            self.assertNotIn("secret response body", pack_text)

    def test_export_rejects_non_stateful_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report(source="json-schema"))
            with self.assertRaisesRegex(ValueError, "not a TwinCheck stateful HTTP"):
                export_stateful_sequence_pack(path, root / "pack")

    def test_export_rejects_modified_canonical_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.report()
            report["findings"][0]["sequence_definition"]["name"] = "tampered"
            path = self.write_report(root, report)
            with self.assertRaisesRegex(ValueError, "canonical SHA-256"):
                export_stateful_sequence_pack(path, root / "pack")

    def test_pack_detects_sequence_file_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report())
            export_stateful_sequence_pack(path, root / "pack")
            (root / "pack" / "sequence.json").write_text('{"schema_version":1,"name":"tampered","steps":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file SHA-256 verification failed"):
                load_stateful_sequence_pack(root / "pack")

    def test_contract_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report())
            export_stateful_sequence_pack(path, root / "pack")
            contract_path = root / "pack" / "contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["name"] = "tampered"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contract SHA-256 verification failed"):
                load_stateful_sequence_pack(root / "pack")

    def test_manifest_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report())
            export_stateful_sequence_pack(path, root / "pack")
            manifest_path = root / "pack" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unrecognized"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown field"):
                load_stateful_sequence_pack(root / "pack")

    def test_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report())
            destination = root / "pack"
            destination.mkdir()
            with self.assertRaises(FileExistsError):
                export_stateful_sequence_pack(path, destination)

    def test_no_reset_pack_rejects_stray_reset_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_report(root, self.report())
            export_stateful_sequence_pack(path, root / "pack")
            (root / "pack" / "reset-sequence.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "although reset_enabled is false"):
                load_stateful_sequence_pack(root / "pack")


if __name__ == "__main__":
    unittest.main()
