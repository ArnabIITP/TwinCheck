import json
import unittest
from pathlib import Path

from twincheck.stateful_http import load_sequence, validate_sequence

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "stateful-corpus-v1"


class StatefulCorpusTests(unittest.TestCase):
    def test_versioned_corpus_definitions_validate_and_pin_reset_health(self):
        sequence, sequence_hash = load_sequence(CORPUS / "sequence.json")
        reset, reset_hash = load_sequence(CORPUS / "reset-sequence.json")
        contract = json.loads((CORPUS / "contract.json").read_text(encoding="utf-8"))
        validate_sequence(sequence)
        validate_sequence(reset)
        self.assertEqual(len(sequence_hash), 64)
        self.assertEqual(len(reset_hash), 64)
        self.assertEqual(sequence["steps"][1]["depends_on"], ["create-cart"])
        self.assertEqual(sequence["steps"][2]["depends_on"], ["add-item"])
        self.assertEqual(reset["health"]["method"], "GET")
        self.assertEqual(reset["health"]["assertions"][0], {"pointer": "/body/item_count", "equals": 0})
        self.assertEqual(contract["stdout"]["mode"], "json")


if __name__ == "__main__":
    unittest.main()
