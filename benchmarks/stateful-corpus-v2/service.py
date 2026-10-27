"""Small deterministic local HTTP fixture for TwinCheck's v0.9 regression corpus.

This fixture is intentionally synthetic. It binds only to loopback and is not a
production API, isolation boundary, or security test target.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class CorpusHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any], *, set_cookie: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", f"sid={self.server.cart_id}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else None

    def _has_session(self) -> bool:
        return f"sid={self.server.cart_id}" in self.headers.get("Cookie", "")

    def _record_test_request(self) -> None:
        with self.server.state_lock:
            self.server.tested_workflow_requests += 1

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._body()
        if path == "/__test/reset":
            with self.server.state_lock:
                if not self.server.broken_reset:
                    self.server.items = []
                    self.server.payments = {}
                    self.server.charge_count = 0
                    self.server.total_delta = self.server.base_total_delta
                self.server.reset_calls += 1
            self._send(200, {"reset": True})
            return

        if path == "/carts":
            self._record_test_request()
            with self.server.state_lock:
                self.server.items = []
            self._send(201, {"id": self.server.cart_id, "created": True}, set_cookie=True)
            return

        if path == "/payments":
            self._record_test_request()
            key = self.headers.get("Idempotency-Key", "")
            if not key:
                self._send(400, {"error": "missing idempotency key"})
                return
            with self.server.state_lock:
                existing = self.server.payments.get(key)
                if existing is not None and not self.server.idempotency_defect:
                    response = {
                        "id": existing["id"],
                        "charge_count": self.server.charge_count,
                        "replayed": True,
                    }
                else:
                    self.server.charge_count += 1
                    payment_id = f"{self.server.payment_prefix}-{self.server.charge_count}"
                    response = {
                        "id": payment_id,
                        "charge_count": self.server.charge_count,
                        "replayed": False,
                    }
                    if not self.server.idempotency_defect:
                        self.server.payments[key] = {"id": payment_id}
            self._send(201, response)
            return

        if path == f"/carts/{self.server.cart_id}/items":
            self._record_test_request()
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            if not isinstance(body, dict) or type(body.get("quantity")) is not int:
                self._send(400, {"error": "quantity must be an integer"})
                return
            with self.server.state_lock:
                self.server.items.append(body)
                count = len(self.server.items)
            self._send(200, {"added": True, "count": count})
            return

        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/__test/state":
            with self.server.state_lock:
                state = {
                    "item_count": len(self.server.items),
                    "charge_count": self.server.charge_count,
                }
            self._send(200, state)
            return

        if path == f"/carts/{self.server.cart_id}":
            self._record_test_request()
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            with self.server.state_lock:
                total = sum(item["quantity"] * 3 for item in self.server.items) + self.server.total_delta
                item_count = len(self.server.items)
                if self.server.increment_on_read:
                    self.server.total_delta += 1
            self._send(200, {"id": self.server.cart_id, "total": total, "item_count": item_count})
            return

        self._send(404, {"error": "not found"})

    def log_message(self, *_args: Any) -> None:
        pass


def start_service(
    *,
    cart_id: str,
    total_delta: int = 0,
    increment_on_read: bool = False,
    broken_reset: bool = False,
    initial_item_quantity: int | None = None,
    idempotency_defect: bool = False,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start a configured synthetic target on an ephemeral loopback port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), CorpusHandler)
    server.daemon_threads = True
    server.cart_id = cart_id
    server.payment_prefix = cart_id
    server.base_total_delta = total_delta
    server.total_delta = total_delta
    server.increment_on_read = increment_on_read
    server.broken_reset = broken_reset
    server.idempotency_defect = idempotency_defect
    server.items = [] if initial_item_quantity is None else [{"quantity": initial_item_quantity}]
    server.payments = {}
    server.charge_count = 0
    server.reset_calls = 0
    server.tested_workflow_requests = 0
    server.state_lock = threading.RLock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
