"""Synthetic cart service used only by the pinned exploration protocol.

Binds to an ephemeral loopback port. It is not a production API or sandbox.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class ExplorationHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any], *, set_cookie: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", f"sid={self.server.cart_id}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else None

    def _has_session(self) -> bool:
        return f"sid={self.server.cart_id}" in self.headers.get("Cookie", "")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._read_body()
        if path == "/__test/reset":
            with self.server.state_lock:
                self.server.items = []
                self.server.total_delta = self.server.base_total_delta
            self._send(200, {"reset": True})
            return

        if path == "/carts":
            with self.server.state_lock:
                self.server.items = []
            self._send(201, {"id": self.server.cart_id, "created": True}, set_cookie=True)
            return

        if path == f"/carts/{self.server.cart_id}/items":
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            if not isinstance(body, dict) or type(body.get("quantity")) is not int:
                self._send(400, {"error": "quantity must be an integer"})
                return
            with self.server.state_lock:
                self.server.items.append(body)
                count = len(self.server.items)
                paired_defect = (
                    self.server.compound_defect
                    and body.get("sku") == ""
                    and body.get("quantity") == 0
                )
            self._send(200, {"added": not paired_defect, "count": count})
            return

        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/__test/state":
            with self.server.state_lock:
                self._send(200, {
                    "item_count": len(self.server.items),
                    "total_delta": self.server.total_delta,
                })
            return

        if path == f"/carts/{self.server.cart_id}":
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            with self.server.state_lock:
                total = sum(item["quantity"] * 3 for item in self.server.items) + self.server.total_delta
                item_count = len(self.server.items)
                should_increment = self.server.increment_on_read
                if should_increment:
                    self.server.total_delta += 1
            self._send(200, {
                "id": self.server.cart_id,
                "total": total,
                "item_count": item_count,
            })
            return

        self._send(404, {"error": "not found"})

    def log_message(self, *_args: Any) -> None:
        pass


def start_service(
    *,
    cart_id: str,
    total_delta: int = 0,
    increment_on_read: bool = False,
    compound_defect: bool = False,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start a deterministic fixture service on an ephemeral loopback port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ExplorationHandler)
    server.daemon_threads = True
    server.cart_id = cart_id
    server.base_total_delta = total_delta
    server.total_delta = total_delta
    server.increment_on_read = increment_on_read
    server.compound_defect = compound_defect
    server.items = []
    server.state_lock = threading.RLock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
