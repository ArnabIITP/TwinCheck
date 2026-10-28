"""Synthetic inventory/reservation API for an independent TwinCheck domain corpus."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

class InventoryHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else None

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._read_body()
        with self.server.state_lock:
            if path == "/__test/reset":
                self.server.available = self.server.initial_stock
                self.server.reservations = {}
                self.server.next_id = 1
                self._send(200, {"reset": True})
                return
            if path == "/reservations":
                if not isinstance(body, dict) or body.get("sku") != "sku-1" or type(body.get("quantity")) is not int or body["quantity"] < 1:
                    self._send(400, {"error": "sku and positive integer quantity required"})
                    return
                quantity = body["quantity"]
                if quantity > self.server.available and not self.server.allow_overbooking:
                    self._send(409, {"error": "insufficient stock"})
                    return
                self.server.available -= quantity
                reservation_id = str(self.server.next_id)
                self.server.next_id += 1
                reservation = {"id": reservation_id, "sku": "sku-1", "quantity": quantity, "status": self.server.reservation_status}
                self.server.reservations[reservation_id] = reservation
                self._send(201, {"id": reservation_id, "accepted": True})
                return
        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        with self.server.state_lock:
            if path == "/__test/state":
                self._send(200, {"available": self.server.available, "reservation_count": len(self.server.reservations)})
                return
            if path == "/inventory/sku-1":
                self._send(200, {"sku": "sku-1", "available": self.server.available})
                return
            prefix = "/reservations/"
            if path.startswith(prefix):
                reservation = self.server.reservations.get(path[len(prefix):])
                if reservation is None:
                    self._send(404, {"error": "reservation not found"})
                else:
                    self._send(200, reservation)
                return
        self._send(404, {"error": "not found"})

    def log_message(self, *_args: Any) -> None:
        pass

def start_service(*, service_id: str, initial_stock: int = 5, allow_overbooking: bool = False, reservation_status: str = "confirmed"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), InventoryHandler)
    server.daemon_threads = True
    server.service_id = service_id
    server.initial_stock = initial_stock
    server.available = initial_stock
    server.allow_overbooking = allow_overbooking
    server.reservation_status = reservation_status
    server.reservations = {}
    server.next_id = 1
    server.state_lock = threading.RLock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
