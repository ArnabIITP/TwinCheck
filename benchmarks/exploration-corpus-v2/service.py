"""Deterministic in-memory booking API for the second benchmark domain."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any], session: bool = False) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if session: self.send_header("Set-Cookie", f"sid={self.server.service_id}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(raw)
    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else None
    def _auth(self) -> bool:
        return f"sid={self.server.service_id}" in self.headers.get("Cookie", "")
    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._body()
        if path == "/__test/reset":
            with self.server.lock:
                self.server.reservations = []
                self.server.capacity = self.server.initial_capacity
            self._send(200, {"reset": True}); return
        if path == "/sessions":
            self._send(201, {"session_id": self.server.service_id}, True); return
        if path == "/reservations":
            if not self._auth():
                self._send(401, {"error": "missing session"}); return
            if not isinstance(body, dict) or body.get("room_type") not in ("standard", "deluxe") or type(body.get("nights")) is not int or not 1 <= body["nights"] <= 30:
                self._send(400, {"error": "invalid reservation"}); return
            with self.server.lock:
                accepted = self.server.capacity > 0
                reservation_id = f"r-{len(self.server.reservations) + 1}"
                if accepted:
                    self.server.capacity -= 1
                    self.server.reservations.append(body)
            self._send(201 if accepted else 409, {"reservation_id": reservation_id if accepted else None, "accepted": accepted}); return
        self._send(404, {"error": "not found"})
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/__test/state":
            with self.server.lock:
                self._send(200, {"count": len(self.server.reservations), "capacity": self.server.capacity})
            return
        if path == "/reservations":
            if not self._auth():
                self._send(401, {"error": "missing session"}); return
            with self.server.lock:
                total = sum((8 if x["room_type"] == "deluxe" else 5) * x["nights"] for x in self.server.reservations) + self.server.fee_delta
                count = len(self.server.reservations)
            self._send(200, {"reservation_count": count, "total_fee": total}); return
        self._send(404, {"error": "not found"})
    def log_message(self, *_args: Any) -> None: pass

def start_service(*, service_id: str, fee_delta: int = 0, capacity: int = 2):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.service_id = service_id
    server.fee_delta = fee_delta
    server.capacity = capacity
    server.initial_capacity = capacity
    server.reservations = []
    server.lock = threading.RLock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
