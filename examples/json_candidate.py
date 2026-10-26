"""Replacement JSON processor with harmless volatile fields and key ordering."""

import json
import sys

request = json.load(sys.stdin)
# Same compatibility-relevant response; volatile fields differ by design.
response = {
    "data": request,
    "meta": {"generated_at": "2026-02-02T12:30:00Z"},
    "request_id": "candidate-request-987",
    "ok": True,
}
json.dump(response, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
