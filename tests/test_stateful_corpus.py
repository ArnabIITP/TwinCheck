import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from test_stateful_http import _start_cart_server
from twincheck.cli import main
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

    def test_corpus_reproduces_exports_and_replays_a_stateful_finding(self):
        reference, ref_thread = _start_cart_server("reference-cart", delta=0)
        candidate, cand_thread = _start_cart_server("candidate-cart", delta=1)
        try:
            with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
                root = Path(temp)
                report_path = root / "corpus-report.json"
                pack_path = root / "regression-pack"
                replay_path = root / "replay-report.json"
                base_args = [
                    "--reference-url", f"http://127.0.0.1:{reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{candidate.server_port}",
                    "--repeat", "2",
                ]
                compare_status = main([
                    "compare-http-sequence", *base_args,
                    "--sequence", str(CORPUS / "sequence.json"),
                    "--reset-sequence", str(CORPUS / "reset-sequence.json"),
                    "--contract", str(CORPUS / "contract.json"),
                    "--output", str(report_path),
                ])
                self.assertEqual(compare_status, 1, "the injected cart-total mismatch should be found")
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertGreater(report["summary"]["differences_found"], 0)
                self.assertTrue(report["state_reset"]["health_check"]["verified_before_each_repeat"])

                self.assertEqual(main([
                    "export-http-sequence-pack",
                    "--report", str(report_path),
                    "--output", str(pack_path),
                ]), 0)
                self.assertTrue((pack_path / "manifest.json").is_file())
                replay_status = main([
                    "replay-http-sequence-pack", "--pack", str(pack_path),
                    *base_args, "--allow-side-effects",
                    "--output", str(replay_path),
                ])
                self.assertEqual(replay_status, 1, "replaying the pack should reproduce the same mismatch")
                replay_report = json.loads(replay_path.read_text(encoding="utf-8"))
                self.assertGreater(replay_report["summary"]["differences_found"], 0)
                self.assertTrue(replay_report["state_reset"]["health_check"]["verified_before_each_repeat"])
        finally:
            for server in (reference, candidate):
                server.shutdown()
                server.server_close()
            ref_thread.join(timeout=1)
            cand_thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
