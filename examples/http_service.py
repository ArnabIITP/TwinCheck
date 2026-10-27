"""Tiny local HTTP service used by the TwinCheck HTTP-adapter walkthrough."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4


class QuoteHandler(BaseHTTPRequestHandler):
    delta = 0

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            quantity = request.get("quantity", 0)
            currency = request.get("currency", "USD")
            total = quantity * 3 + self.delta
            payload = {
                "total": total,
                "currency": currency,
                "request_id": str(uuid4()),
                "metadata": {"generated_at": datetime.now(timezone.utc).isoformat()},
            }
            status = 200
        except Exception:
            payload = {"error": "invalid_request"}
            status = 400
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--delta", type=int, default=0, help="deliberate compatibility bug; set to 1 for the candidate")
    args = parser.parse_args()
    handler = type("ConfiguredQuoteHandler", (QuoteHandler,), {"delta": args.delta})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Local quote service listening on http://{args.host}:{args.port} (delta={args.delta})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
