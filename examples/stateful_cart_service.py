"""Tiny local stateful cart API used to demonstrate TwinCheck sequences.

Start one reference and one candidate instance in separate terminals. This demo
stores data in memory and is intended only for local compatibility testing.
"""

from __future__ import annotations

import argparse
import json
import http.server
from urllib.parse import urlsplit


class CartHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict, *, set_cookie: bool = False) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if set_cookie:
            self.send_header("Set-Cookie", f"sid={self.server.cart_id}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(encoded)

    def _has_session(self) -> bool:
        return f"sid={self.server.cart_id}" in self.headers.get("Cookie", "")

    def do_POST(self) -> None:
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
        if path == f"/carts/{self.server.cart_id}/items":
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            if not isinstance(body, dict) or type(body.get("quantity")) is not int:
                self._send(400, {"error": "quantity must be an integer"})
                return
            self.server.items.append(body)
            self._send(200, {"added": True, "count": len(self.server.items)})
            return
        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        if urlsplit(self.path).path == f"/carts/{self.server.cart_id}":
            if not self._has_session():
                self._send(401, {"error": "missing session"})
                return
            total = sum(item["quantity"] * 3 for item in self.server.items) + self.server.total_delta
            self._send(200, {"id": self.server.cart_id, "total": total, "item_count": len(self.server.items)})
            if self.server.increment_on_read:
                self.server.total_delta += 1
            return
        self._send(404, {"error": "not found"})

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--cart-id", default="reference-cart")
    parser.add_argument("--total-delta", type=int, default=0, help="add this integer to every returned total to simulate an immediate response bug")
    parser.add_argument("--increment-on-read", action="store_true", help="simulate a stateful defect: each cart read increments the next read's total")
    args = parser.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), CartHandler)
    server.cart_id = args.cart_id
    server.base_total_delta = args.total_delta
    server.total_delta = args.total_delta
    server.increment_on_read = args.increment_on_read
    server.items = []
    print(f"Stateful cart demo listening on http://127.0.0.1:{args.port} (cart id: {args.cart_id})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
