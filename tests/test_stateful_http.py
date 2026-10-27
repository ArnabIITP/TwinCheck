import contextlib
import hashlib
import http.server
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from twincheck.cli import main
from twincheck.contract import contract_from_dict
from twincheck.stateful_http import (
    load_sequence,
    run_http_sequence_comparison,
    validate_sequence,
)
from twincheck.stateful_explore import (
    _select_next_variant,
    _variant_mutation_features,
    generate_sequence_variants,
    run_http_sequence_exploration,
)


class _CartHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, payload, *, set_cookie=False):
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if set_cookie:
            self.send_header("Set-Cookie", f"sid={self.server.cart_id}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(encoded)

    def _cookie_ok(self):
        return f"sid={self.server.cart_id}" in self.headers.get("Cookie", "")

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else None
        if path == "/__test/reset":
            self.server.items = []
            self.server.total_delta = self.server.base_total_delta
            self._send(200, {"reset": True})
            return
        if path == "/carts":
            self.server.items = []
            self._send(201, {"id": self.server.cart_id, "created": True}, set_cookie=True)
            return
        prefix = f"/carts/{self.server.cart_id}/items"
        if path == prefix:
            if not self._cookie_ok():
                self._send(401, {"error": "missing session"})
                return
            if not isinstance(body, dict) or type(body.get("quantity")) is not int:
                self._send(400, {"error": "quantity must be an integer"})
                return
            self.server.items.append(body)
            self.server.cookie_protected_step_seen = True
            self._send(200, {"added": True, "count": len(self.server.items)})
            return
        self._send(404, {"error": "not found"})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == f"/carts/{self.server.cart_id}":
            if not self._cookie_ok():
                self._send(401, {"error": "missing session"})
                return
            total = sum(item["quantity"] * 3 for item in self.server.items) + self.server.total_delta
            self._send(200, {"id": self.server.cart_id, "total": total, "item_count": len(self.server.items)})
            if self.server.increment_on_get:
                self.server.total_delta += 1
            return
        self._send(404, {"error": "not found"})

    def log_message(self, *_args):
        pass


def _start_cart_server(cart_id, delta=0):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CartHandler)
    server.cart_id = cart_id
    server.base_total_delta = delta
    server.total_delta = delta
    server.increment_on_read = False
    server.items = []
    server.cookie_protected_step_seen = False
    server.increment_on_get = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _sequence():
    return {
        "schema_version": 1,
        "name": "cart-create-add-read",
        "steps": [
            {
                "name": "create-cart",
                "method": "POST",
                "path": "/carts",
                "body": {"currency": "USD"},
                "capture": {"cart_id": "/body/id"},
            },
            {
                "name": "add-item",
                "method": "POST",
                "path": "/carts/{{cart_id}}/items",
                "body": {"sku": "demo-sku", "quantity": 2},
            },
            {
                "name": "read-cart",
                "method": "GET",
                "path": "/carts/{{cart_id}}",
            },
        ],
    }


def _contract():
    return contract_from_dict({
        "name": "cart-response-compatibility",
        "stdout": {"mode": "json", "ignore_paths": ["/body/id"]},
    })


class StatefulHttpTests(unittest.TestCase):
    def setUp(self):
        self.reference, self.ref_thread = _start_cart_server("reference-cart")
        self.candidate, self.cand_thread = _start_cart_server("candidate-cart")

    def tearDown(self):
        for server in (self.reference, self.candidate):
            server.shutdown()
            server.server_close()
        self.ref_thread.join(timeout=1)
        self.cand_thread.join(timeout=1)

    def run_comparison(self, *, candidate_delta=0, repeat=1):
        self.candidate.base_total_delta = candidate_delta
        self.candidate.total_delta = candidate_delta
        sequence = _sequence()
        source = json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(source).hexdigest(),
            contract=_contract(),
            repeat=repeat,
        )

    def test_captured_ids_and_cookies_keep_multistep_workflow_aligned(self):
        report = self.run_comparison()
        self.assertEqual(report["summary"]["differences_found"], 0)
        self.assertTrue(self.reference.cookie_protected_step_seen)
        self.assertTrue(self.candidate.cookie_protected_step_seen)
        self.assertEqual(report["sequence"]["step_count"], 3)
        self.assertEqual(report["http_adapter"]["cookies_persist_within_each_sequence"], True)
        finding_data = report["input_source"]
        self.assertEqual(finding_data, "stateful-http-sequence")

    def test_difference_only_on_later_step_has_replayable_trace(self):
        report = self.run_comparison(candidate_delta=1)
        self.assertEqual(report["summary"]["differences_found"], 1)
        finding = report["findings"][0]
        self.assertEqual(finding["sequence_name"], "cart-create-add-read")
        self.assertEqual(finding["sequence_definition"], _sequence())
        self.assertEqual(finding["step_results"][-1]["name"], "read-cart")
        self.assertEqual(finding["step_results"][-1]["differences"], ["stdout"])
        self.assertNotIn("reference-cart", finding["sequence_definition"]["steps"][1]["path"])
        self.assertEqual(finding["sequence_file_sha256"], report["sequence"]["source_sha256"])
        self.assertEqual(finding["input_sha256"], hashlib.sha256(finding["input"].encode("utf-8")).hexdigest())
        candidate_output = json.loads(finding["step_results"][-1]["candidate"]["stdout"])
        self.assertEqual(candidate_output["body"]["total"], 7)

    def test_repeat_restarts_cookie_jars_and_flags_unstable_target(self):
        report = self.run_comparison(repeat=2)
        self.assertEqual(report["summary"]["differences_found"], 0)

    def test_repeat_records_first_alternate_trace_for_unstable_services(self):
        self.reference.increment_on_get = True
        self.candidate.increment_on_get = True
        report = self.run_comparison(repeat=3)
        self.assertIn("reference_unstable", report["findings"][0]["differences"])
        self.assertIn("candidate_unstable", report["findings"][0]["differences"])
        self.assertEqual(report["findings"][0]["repeat_instability"]["reference"]["first_differing_repeat"], 2)
        self.assertEqual(len(report["findings"][0]["repeat_traces"]), 1)
        self.assertEqual(report["findings"][0]["repeat_traces"][0]["repeat_index"], 2)

    def test_reset_sequence_runs_before_each_workflow_and_rejects_failed_reset(self):
        sequence = _sequence()
        reset_sequence = {"schema_version": 1, "name": "reset", "steps": [
            {"name": "reset-state", "method": "POST", "path": "/__test/reset"}
        ]}
        digest = hashlib.sha256(json.dumps(sequence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        reset_digest = hashlib.sha256(json.dumps(reset_sequence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.reference.items = [{"quantity": 100}]
        self.candidate.items = [{"quantity": 200}]
        report = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence, sequence_sha256=digest,
            reset_sequence=reset_sequence, reset_sequence_sha256=reset_digest,
            contract=_contract(),
        )
        self.assertEqual(report["summary"]["differences_found"], 0)
        self.assertEqual(report["state_reset"]["sequence_sha256"], reset_digest)
        bad_reset = {"schema_version": 1, "name": "bad-reset", "steps": [
            {"name": "reset-fails", "method": "POST", "path": "/not-a-reset-endpoint"}
        ]}
        with self.assertRaisesRegex(ValueError, "reset sequence failed"):
            run_http_sequence_comparison(
                reference_url=f"http://127.0.0.1:{self.reference.server_port}",
                candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
                sequence=sequence, sequence_sha256=digest,
                reset_sequence=bad_reset,
                contract=_contract(),
            )

    def test_variant_generator_covers_boundaries_transitions_and_is_seeded(self):
        sequence = _sequence()
        first = generate_sequence_variants(sequence, max_cases=30, seed=19)
        second = generate_sequence_variants(sequence, max_cases=30, seed=19)
        self.assertEqual([item.sha256 for item in first], [item.sha256 for item in second])
        kinds = {item.mutation_type for item in first}
        self.assertIn("baseline", kinds)
        self.assertIn("value_boundary", kinds)
        self.assertIn("step_removal", kinds)
        self.assertIn("step_repeat", kinds)
        self.assertIn("order_swap", kinds)
        for variant in first:
            validate_sequence(variant.sequence)

    def test_explorer_minimizes_stateful_mismatch_after_reset(self):
        self.candidate.base_total_delta = 1
        self.candidate.total_delta = 1
        sequence = _sequence()
        reset_sequence = {"schema_version": 1, "name": "reset-cart-state", "steps": [
            {"name": "reset", "method": "POST", "path": "/__test/reset"}
        ]}
        sequence_bytes = json.dumps(sequence, indent=2).encode()
        reset_bytes = json.dumps(reset_sequence, indent=2).encode()
        report = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(sequence_bytes).hexdigest(),
            reset_sequence=reset_sequence,
            reset_sequence_sha256=hashlib.sha256(reset_bytes).hexdigest(),
            seed=4,
            max_cases=12,
            contract=_contract(),
            minimize=True,
            max_findings_to_minimize=1,
            max_minimization_trials=12,
        )
        self.assertEqual(report["cases_executed"], 12)
        self.assertGreater(report["summary"]["cases_with_differences"], 0)
        self.assertTrue(report["state_reset"]["enabled"])
        self.assertEqual(report["exploration"]["candidate_count"], 12)
        finding = next((item for item in report["findings"] if item.get("minimized")), None)
        self.assertIsNotNone(finding)
        self.assertLess(len(finding["sequence_definition"]["steps"]), len(finding["original_sequence_definition"]["steps"]))
        self.assertTrue(finding["minimization"]["request_bodies_shrunk"])
        self.assertEqual(finding["minimization"]["step_count_after"], len(finding["sequence_definition"]["steps"]))
        with tempfile.TemporaryDirectory() as temp:
            source_report = Path(temp) / "exploration.json"
            replay_report = Path(temp) / "replay.json"
            source_report.write_text(json.dumps(report), encoding="utf-8")
            self.candidate.base_total_delta = 0
            self.candidate.total_delta = 0
            with contextlib.redirect_stdout(io.StringIO()):
                replay_code = main([
                    "replay-http-sequence", "--report", str(source_report),
                    "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                    "--allow-side-effects", "--output", str(replay_report),
                ])
            self.assertEqual(replay_code, 0)
            replayed = json.loads(replay_report.read_text(encoding="utf-8"))
            self.assertTrue(replayed["state_reset"]["enabled"])
            self.assertEqual(replayed["summary"]["differences_found"], 0)

    def test_explorer_finds_a_defect_only_after_repeating_a_transition(self):
        self.candidate.increment_on_get = True
        sequence = _sequence()
        reset_sequence = {"schema_version": 1, "name": "reset-cart-state", "steps": [
            {"name": "reset", "method": "POST", "path": "/__test/reset"}
        ]}
        seq_raw = json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode()
        reset_raw = json.dumps(reset_sequence, ensure_ascii=False, separators=(",", ":")).encode()
        kwargs = {
            "reference_url": f"http://127.0.0.1:{self.reference.server_port}",
            "candidate_url": f"http://127.0.0.1:{self.candidate.server_port}",
            "sequence": sequence,
            "sequence_sha256": hashlib.sha256(seq_raw).hexdigest(),
            "reset_sequence": reset_sequence,
            "reset_sequence_sha256": hashlib.sha256(reset_raw).hexdigest(),
            "contract": _contract(),
        }
        baseline = run_http_sequence_comparison(**kwargs)
        self.assertEqual(baseline["summary"]["differences_found"], 0)
        explored = run_http_sequence_exploration(**kwargs, seed=7, max_cases=30)
        self.assertGreater(explored["summary"]["cases_with_differences"], 0)
        duplicate_read = next(
            item for item in explored["findings"]
            if item.get("mutation_type") == "step_repeat"
            and any(step.get("name", "").startswith("read-cart-repeat") for step in item.get("step_results", []))
        )
        self.assertEqual(duplicate_read["step_results"][-1]["name"], "read-cart-repeat-3")
        last_body = json.loads(duplicate_read["step_results"][-1]["candidate"]["stdout"])
        self.assertEqual(last_body["status"], 200)
        self.assertEqual(last_body["body"]["total"], 7)

    def test_behavior_coverage_fingerprints_response_branches_without_values(self):
        sequence = _sequence()
        digest = hashlib.sha256(json.dumps(sequence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        ordinary = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence, sequence_sha256=digest, contract=_contract(),
        )
        self.assertNotIn("behavior_coverage", ordinary)
        covered = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence, sequence_sha256=digest, contract=_contract(), include_behavior_coverage=True,
        )
        branches = covered["behavior_coverage"]["response_branches"]
        self.assertEqual(len(branches), 3)
        self.assertTrue(all(len(item["reference_signature"]) == 64 for item in branches))
        self.assertGreaterEqual(len(covered["behavior_coverage"]["transitions"]), 2)
        self.assertNotIn("reference-cart", json.dumps(covered["behavior_coverage"]))

        mutated = json.loads(json.dumps(sequence))
        mutated["steps"][1]["body"]["quantity"] = "invalid"
        mutated_digest = hashlib.sha256(json.dumps(mutated, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        changed = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=mutated, sequence_sha256=mutated_digest, contract=_contract(), include_behavior_coverage=True,
        )
        original_branch = next(item for item in branches if item["step_name"] == "add-item")
        changed_branch = next(item for item in changed["behavior_coverage"]["response_branches"] if item["step_name"] == "add-item")
        self.assertNotEqual(original_branch["reference_signature"], changed_branch["reference_signature"])

    def test_feedback_selector_prioritizes_a_step_with_new_response_behavior(self):
        sequence = _sequence()
        variants = generate_sequence_variants(sequence, max_cases=60, seed=5)
        add_item_variant = None
        create_cart_variant = None
        for variant in variants[1:]:
            if variant.mutation_type != "value_boundary":
                continue
            _, targets = _variant_mutation_features(sequence, variant)
            if "add-item" in targets and add_item_variant is None:
                add_item_variant = variant
            if "create-cart" in targets and create_cart_variant is None:
                create_cart_variant = variant
        self.assertIsNotNone(add_item_variant)
        self.assertIsNotNone(create_cart_variant)
        pending = [create_cart_variant, add_item_variant]
        tie_rank = {create_cart_variant.sha256: 1.0, add_item_variant.sha256: 0.0}
        selected, details = _select_next_variant(
            pending,
            base_sequence=sequence,
            attempted_features=set(),
            category_counts={"value_boundary": 1},
            step_interest={"add-item": 3},
            tie_rank=tie_rank,
        )
        self.assertEqual(selected, add_item_variant)
        self.assertTrue(any("newly observed response branches" in reason for reason in details["reasons"]))

    def test_explorer_uses_feedback_priorities_and_reports_coverage(self):
        sequence = _sequence()
        reset_sequence = {"schema_version": 1, "name": "reset", "steps": [
            {"name": "reset", "method": "POST", "path": "/__test/reset"}
        ]}
        seq_raw = json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode()
        reset_raw = json.dumps(reset_sequence, ensure_ascii=False, separators=(",", ":")).encode()
        report = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(seq_raw).hexdigest(),
            reset_sequence=reset_sequence,
            reset_sequence_sha256=hashlib.sha256(reset_raw).hexdigest(),
            seed=19, max_cases=8, contract=_contract(),
        )
        self.assertEqual(report["exploration"]["algorithm_version"], 2)
        self.assertIn("feedback-guided", report["exploration"]["scheduler"])
        self.assertEqual(report["executions"][0]["mutation_type"], "baseline")
        self.assertIn("priority_score", report["executions"][1])
        self.assertGreater(report["exploration"]["coverage_summary"]["unique_response_branches"], 0)
        self.assertGreater(report["exploration"]["coverage_summary"]["unique_adjacent_transitions"], 0)
        self.assertEqual(len(report["exploration"]["coverage_by_case"]), 8)
        repeated = run_http_sequence_exploration(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(seq_raw).hexdigest(),
            reset_sequence=reset_sequence,
            reset_sequence_sha256=hashlib.sha256(reset_raw).hexdigest(),
            seed=19, max_cases=8, contract=_contract(),
        )
        self.assertEqual(
            [item["input_sha256"] for item in report["executions"]],
            [item["input_sha256"] for item in repeated["executions"]],
        )

    def test_explore_cli_writes_a_replayable_exploration_report(self):
        self.candidate.total_delta = 1
        with tempfile.TemporaryDirectory() as temp:
            sequence_path = Path(temp) / "workflow.json"
            reset_path = Path(temp) / "reset.json"
            report_path = Path(temp) / "exploration.json"
            sequence_path.write_text(json.dumps(_sequence()), encoding="utf-8")
            reset_path.write_text(json.dumps({"schema_version": 1, "name": "reset", "steps": [
                {"name": "reset", "method": "POST", "path": "/__test/reset"}
            ]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "explore-http-sequence",
                    "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                    "--sequence", str(sequence_path), "--reset-sequence", str(reset_path),
                    "--allow-side-effects", "--cases", "5", "--seed", "3",
                    "--output", str(report_path),
                ])
            self.assertEqual(code, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["input_source"], "stateful-http-exploration")
            self.assertEqual(report["cases_executed"], 5)
            self.assertTrue(report["state_reset"]["sequence_definition"])
            self.assertGreater(report["summary"]["differences_found"], 0)

    def test_stateful_regression_pack_cli_exports_and_replays_with_reset(self):
        self.candidate.base_total_delta = 1
        self.candidate.total_delta = 1
        sequence = _sequence()
        reset_sequence = {
            "schema_version": 1,
            "name": "reset-cart",
            "steps": [{"name": "reset", "method": "POST", "path": "/__test/reset"}],
        }
        sequence_bytes = json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reset_bytes = json.dumps(reset_sequence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        report = run_http_sequence_comparison(
            reference_url=f"http://127.0.0.1:{self.reference.server_port}",
            candidate_url=f"http://127.0.0.1:{self.candidate.server_port}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(sequence_bytes).hexdigest(),
            contract=_contract(),
            reset_sequence=reset_sequence,
            reset_sequence_sha256=hashlib.sha256(reset_bytes).hexdigest(),
        )
        self.assertEqual(report["summary"]["differences_found"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "source-report.json"
            pack_path = root / "stateful-pack"
            replay_path = root / "replay-report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                export_code = main(["export-http-sequence-pack", "--report", str(report_path), "--output", str(pack_path)])
            self.assertEqual(export_code, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                replay_code = main([
                    "replay-http-sequence-pack", "--pack", str(pack_path),
                    "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                    "--allow-side-effects", "--repeat", "2", "--output", str(replay_path),
                ])
            self.assertEqual(replay_code, 1)
            replay_report = json.loads(replay_path.read_text(encoding="utf-8"))
            self.assertTrue(replay_report["stateful_regression_pack"]["reset_enabled"])
            self.assertEqual(replay_report["repeat"], 2)
            self.assertEqual(replay_report["summary"]["differences_found"], 1)

    def test_explore_cli_requires_side_effect_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temp:
            sequence_path = Path(temp) / "workflow.json"
            reset_path = Path(temp) / "reset.json"
            sequence_path.write_text(json.dumps(_sequence()), encoding="utf-8")
            reset_path.write_text(json.dumps({"schema_version": 1, "name": "reset", "steps": [
                {"name": "reset", "method": "POST", "path": "/__test/reset"}
            ]}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code = main([
                    "explore-http-sequence",
                    "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                    "--sequence", str(sequence_path), "--reset-sequence", str(reset_path),
                    "--cases", "1",
                ])
            self.assertEqual(code, 2)

    def test_cli_writes_stateful_sequence_report(self):
        with tempfile.TemporaryDirectory() as temp:
            sequence_path = Path(temp) / "workflow.json"
            report_path = Path(temp) / "report.json"
            contract_path = Path(temp) / "contract.json"
            sequence_path.write_text(json.dumps(_sequence()), encoding="utf-8")
            contract_path.write_text(json.dumps({
                "name": "cart-response-compatibility",
                "stdout": {"mode": "json", "ignore_paths": ["/body/id"]},
            }), encoding="utf-8")
            argv = [
                "compare-http-sequence",
                "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                "--sequence", str(sequence_path), "--contract", str(contract_path),
                "--output", str(report_path),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(argv)
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["input_source"], "stateful-http-sequence")
            self.assertEqual(report["sequence"]["source_sha256"], hashlib.sha256(sequence_path.read_bytes()).hexdigest())

    def test_failed_trace_can_be_replayed_after_fix_with_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temp:
            source_report = Path(temp) / "source-report.json"
            replay_report = Path(temp) / "replay-report.json"
            failing = self.run_comparison(candidate_delta=1)
            source_report.write_text(json.dumps(failing), encoding="utf-8")
            self.candidate.total_delta = 0
            common = [
                "replay-http-sequence", "--report", str(source_report),
                "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                "--output", str(replay_report),
            ]
            with contextlib.redirect_stderr(io.StringIO()):
                refused = main(common)
            self.assertEqual(refused, 2)
            with contextlib.redirect_stdout(io.StringIO()):
                replayed = main([*common, "--allow-side-effects"])
            self.assertEqual(replayed, 0)
            evidence = json.loads(replay_report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["replay"]["source_sequence_sha256"], failing["sequence"]["source_sha256"])
            self.assertEqual(evidence["summary"]["differences_found"], 0)

            tampered = json.loads(source_report.read_text(encoding="utf-8"))
            tampered["findings"][0]["sequence_definition"]["steps"][0]["path"] = "/tampered"
            tampered_report = Path(temp) / "tampered-report.json"
            tampered_report.write_text(json.dumps(tampered), encoding="utf-8")
            tampered_args = [
                "replay-http-sequence", "--report", str(tampered_report),
                "--reference-url", f"http://127.0.0.1:{self.reference.server_port}",
                "--candidate-url", f"http://127.0.0.1:{self.candidate.server_port}",
                "--allow-side-effects",
            ]
            with contextlib.redirect_stderr(io.StringIO()):
                tampered_code = main(tampered_args)
            self.assertEqual(tampered_code, 2)

    def test_sequence_validation_rejects_bad_methods_unknown_fields_and_bad_pointers(self):
        bad = _sequence()
        bad["unknown"] = "no"
        with self.assertRaisesRegex(ValueError, "unknown stateful sequence key"):
            validate_sequence(bad)
        bad = _sequence()
        bad["steps"][0]["method"] = "TRACE"
        with self.assertRaisesRegex(ValueError, "method must be one of"):
            validate_sequence(bad)
        bad = _sequence()
        bad["steps"][0]["capture"] = {"cart_id": "/body/bad~2pointer"}
        with self.assertRaisesRegex(ValueError, "invalid JSON Pointer escaping"):
            validate_sequence(bad)

    def test_load_sequence_hashes_exact_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "workflow.json"
            exact_bytes = json.dumps(_sequence(), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            source.write_bytes(exact_bytes)
            sequence, digest = load_sequence(source)
            self.assertEqual(sequence, _sequence())
            self.assertEqual(digest, hashlib.sha256(exact_bytes).hexdigest())


if __name__ == "__main__":
    unittest.main()
