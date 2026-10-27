import contextlib
import io
import tempfile
import http.server
import json
import threading
import unittest
from pathlib import Path

from twincheck.contract import contract_from_dict
from twincheck.http_engine import parse_request_headers, run_http_comparison, validate_local_base_url
from twincheck.cli import main


class _ApiHandler(http.server.BaseHTTPRequestHandler):
    delta = 0

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(size).decode("utf-8"))
        except Exception:
            request = {}
        body = {
            "total": request.get("quantity", 0) * 3 + self.delta,
            "request_id": f"request-{self.delta}",
            "metadata": {"generated_at": "volatile-time"},
        }
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass



class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    location = "http://example.com/should-not-be-followed"

    def do_POST(self):
        self.send_response(302)
        self.send_header("Location", self.location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        pass


class _RedirectTargetHandler(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_POST(self):
        type(self).hits += 1
        payload = b'{"followed":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


def _start_server(delta):
    handler = type(f"ApiHandler{delta}", (_ApiHandler,), {"delta": delta})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class HttpAdapterTests(unittest.TestCase):
    def test_contract_ignores_volatile_body_fields_but_finds_real_behavior_change(self):
        reference, ref_thread = _start_server(0)
        candidate, cand_thread = _start_server(0)
        try:
            contract = contract_from_dict({
                "name": "http-test-v1",
                "stdout": {"mode": "json", "ignore_paths": ["/body/request_id", "/body/metadata/generated_at"]},
            })
            report = run_http_comparison(
                reference_url=f"http://127.0.0.1:{reference.server_port}",
                candidate_url=f"http://127.0.0.1:{candidate.server_port}",
                method="POST",
                path="/orders",
                inputs=['{"quantity":2}', '{"quantity":5}'],
                seed=17,
                contract=contract,
                schema_sha256="a" * 64,
                schema_title="OrderRequest",
            )
            self.assertEqual(report["summary"]["differences_found"], 0)
            self.assertEqual(report["input_generation"]["method"], "json-schema")
            self.assertEqual(report["http_adapter"]["response_headers_compared"], ["content-type"])

        finally:
            reference.shutdown(); reference.server_close()
            candidate.shutdown(); candidate.server_close()
            ref_thread.join(timeout=1); cand_thread.join(timeout=1)

        reference, ref_thread = _start_server(0)
        candidate, cand_thread = _start_server(1)
        try:
            contract = contract_from_dict({
                "name": "http-test-v1",
                "stdout": {"mode": "json", "ignore_paths": ["/body/request_id", "/body/metadata/generated_at"]},
            })
            report = run_http_comparison(
                reference_url=f"http://127.0.0.1:{reference.server_port}",
                candidate_url=f"http://127.0.0.1:{candidate.server_port}",
                method="POST",
                path="/orders",
                inputs=['{"quantity":2}'],
                contract=contract,
            )
            self.assertEqual(report["summary"]["differences_found"], 1)
            self.assertIn("stdout", report["findings"][0]["differences"])
            self.assertEqual(json.loads(report["findings"][0]["reference"]["stdout"])["body"]["total"], 6)
        finally:
            reference.shutdown(); reference.server_close()
            candidate.shutdown(); candidate.server_close()
            ref_thread.join(timeout=1); cand_thread.join(timeout=1)

    def test_compare_http_cli_writes_provenance_report(self):
        reference, ref_thread = _start_server(0)
        candidate, cand_thread = _start_server(0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                schema_path = Path(tmp) / "schema.json"
                report_path = Path(tmp) / "http-report.json"
                schema_path.write_text(json.dumps({
                    "title": "QuantityRequest",
                    "type": "object",
                    "required": ["quantity"],
                    "properties": {"quantity": {"type": "integer", "minimum": 1, "maximum": 10}},
                    "additionalProperties": False,
                }), encoding="utf-8")
                args = [
                    "compare-http",
                    "--reference-url", f"http://127.0.0.1:{reference.server_port}",
                    "--candidate-url", f"http://127.0.0.1:{candidate.server_port}",
                    "--path", "/quotes", "--method", "POST",
                    "--schema", str(schema_path), "--cases", "3", "--seed", "5",
                    "--output", str(report_path),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(args)
                self.assertEqual(code, 0)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["input_source"], "json-schema")
                self.assertEqual(report["http_adapter"]["method"], "POST")
                self.assertEqual(report["input_generation"]["schema_title"], "QuantityRequest")
                self.assertEqual(report["cases_executed"], 3)
        finally:
            reference.shutdown(); reference.server_close()
            candidate.shutdown(); candidate.server_close()
            ref_thread.join(timeout=1); cand_thread.join(timeout=1)

    def test_redirects_are_compared_without_following_location(self):
        target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RedirectTargetHandler)
        _RedirectTargetHandler.hits = 0
        redirect_handler = type(
            "LocalRedirectHandler",
            (_RedirectHandler,),
            {"location": f"http://127.0.0.1:{target.server_port}/must-not-be-followed"},
        )
        servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), redirect_handler) for _ in range(2)]
        all_servers = [target, *servers]
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in all_servers]
        for thread in threads:
            thread.start()
        try:
            report = run_http_comparison(
                reference_url=f"http://127.0.0.1:{servers[0].server_port}",
                candidate_url=f"http://127.0.0.1:{servers[1].server_port}",
                method="POST", path="/redirect", inputs=['{"quantity":1}'],
                response_headers=["location"],
            )
            self.assertEqual(report["summary"]["differences_found"], 0)
            self.assertEqual(_RedirectTargetHandler.hits, 0)
        finally:
            for server in all_servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=1)

    def test_remote_hosts_and_embedded_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "remote hosts are not allowed"):
            validate_local_base_url("https://example.com", label="--reference-url")
        with self.assertRaisesRegex(ValueError, "embedded username or password"):
            validate_local_base_url("http://user:password@localhost:8000", label="--reference-url")

    def test_query_values_are_redacted_from_report_metadata(self):
        reference, ref_thread = _start_server(0)
        candidate, cand_thread = _start_server(0)
        try:
            report = run_http_comparison(
                reference_url=f"http://127.0.0.1:{reference.server_port}",
                candidate_url=f"http://127.0.0.1:{candidate.server_port}",
                method="POST", path="/orders?token=private&tenant=demo",
                inputs=['{"quantity":1}'],
            )
            self.assertIn("?<query-redacted>", report["http_adapter"]["path"])
            self.assertNotIn("private", report["http_adapter"]["path"])
            self.assertNotIn("private", report["reference_command"])
        finally:
            reference.shutdown(); reference.server_close()
            candidate.shutdown(); candidate.server_close()
            ref_thread.join(timeout=1); cand_thread.join(timeout=1)

    def test_request_header_validation(self):
        self.assertEqual(parse_request_headers(["X-Tenant: demo"]), (("X-Tenant", "demo"),))
        with self.assertRaisesRegex(ValueError, "transport header"):
            parse_request_headers(["Content-Length: 20"])
        with self.assertRaisesRegex(ValueError, "duplicate request header"):
            parse_request_headers(["X-Key: a", "x-key: b"])


if __name__ == "__main__":
    unittest.main()
