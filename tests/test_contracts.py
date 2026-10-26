import json
import tempfile
import unittest
from pathlib import Path

from twincheck.compare import CompareOptions, difference_kinds
from twincheck.contract import CompatibilityContract, contract_from_dict, load_contract
from twincheck.runner import Observation


class ContractTests(unittest.TestCase):
    def observation(self, *, stdout="", stderr="", returncode=0, timed_out=False):
        return Observation(returncode, stdout, stderr, timed_out, 0.001)

    def test_json_contract_ignores_volatile_fields_and_object_key_order(self):
        contract = contract_from_dict({
            "schema_version": 1,
            "name": "api-response",
            "stdout": {"mode": "json", "ignore_paths": ["/request_id", "/meta/generated_at"]},
        })
        reference = self.observation(stdout='{"ok":true,"request_id":"ref","meta":{"generated_at":"yesterday"},"data":{"n":1}}\n')
        candidate = self.observation(stdout='{"data":{"n":1},"meta":{"generated_at":"today"},"request_id":"candidate","ok":true}\n')
        self.assertEqual(difference_kinds(reference, candidate, CompareOptions(contract=contract)), [])

    def test_nested_json_pointer_escaping_and_array_redaction(self):
        contract = contract_from_dict({
            "stdout": {"mode": "json", "ignore_paths": ["/a~1b/~0key", "/items/1"]}
        })
        reference = self.observation(stdout='{"a/b":{"~key":"x","keep":1},"items":["first","volatile-a","last"]}')
        candidate = self.observation(stdout='{"items":["first","volatile-b","last"],"a/b":{"~key":"changed","keep":1}}')
        self.assertEqual(difference_kinds(reference, candidate, CompareOptions(contract=contract)), [])

    def test_json_contract_compares_numbers_by_numeric_value(self):
        contract = contract_from_dict({"stdout": {"mode": "json"}})
        reference = self.observation(stdout='{"value":1}')
        candidate = self.observation(stdout='{"value":1.0}')
        self.assertEqual(difference_kinds(reference, candidate, CompareOptions(contract=contract)), [])

    def test_json_contract_rejects_invalid_json_even_if_both_outputs_match(self):
        contract = contract_from_dict({"stdout": {"mode": "json"}})
        observation = self.observation(stdout="not-json")
        self.assertEqual(
            difference_kinds(observation, observation, CompareOptions(contract=contract)),
            ["stdout_invalid_json"],
        )

    def test_contract_can_exclude_exit_code_and_timeout(self):
        contract = contract_from_dict({"compare_exit_code": False, "compare_timeout": False})
        reference = self.observation(returncode=0, timed_out=False)
        candidate = self.observation(returncode=None, timed_out=True)
        self.assertEqual(difference_kinds(reference, candidate, CompareOptions(contract=contract)), [])

    def test_contract_hash_is_stable_and_sensitive_to_policy(self):
        first = contract_from_dict({"name": "same", "stdout": {"mode": "json"}})
        second = contract_from_dict({"stdout": {"mode": "json"}, "name": "same"})
        third = contract_from_dict({"name": "same", "stdout": {"mode": "exact"}})
        self.assertEqual(first.sha256, second.sha256)
        self.assertNotEqual(first.sha256, third.sha256)
        self.assertEqual(len(first.sha256), 64)

    def test_contract_validation_is_strict(self):
        with self.assertRaises(ValueError):
            contract_from_dict({"unknown": True})
        with self.assertRaises(ValueError):
            contract_from_dict({"stdout": {"mode": "json", "ignore_paths": ["not-a-pointer"]}})
        with self.assertRaises(ValueError):
            contract_from_dict({"stdout": {"mode": "exact", "ignore_paths": ["/field"]}})
        with self.assertRaises(ValueError):
            contract_from_dict({"stdout": {"mode": "json", "ignore_paths": ["/bad~escape"]}})
        with self.assertRaises(ValueError):
            contract_from_dict({"schema_version": True})

    def test_load_contract_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            path.write_text(json.dumps({"name": "from-file", "stdout": {"mode": "json"}}), encoding="utf-8")
            contract = load_contract(path)
            self.assertEqual(contract.name, "from-file")
            self.assertEqual(contract.stdout.mode, "json")


if __name__ == "__main__":
    unittest.main()
