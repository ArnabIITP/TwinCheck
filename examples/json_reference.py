"""Reference JSON processor used to demonstrate contract-based comparison."""

import json
import sys

request = json.load(sys.stdin)
response = {
    "ok": True,
    "request_id": "reference-request-123",
    "meta": {"generated_at": "2026-01-01T00:00:00Z"},
    "data": request,
}
json.dump(response, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
