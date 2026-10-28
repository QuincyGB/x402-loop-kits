"""The owner-read client for a stall's own nudge inbox — the same
pattern the fleet's sender engine uses against StallRow
(POST /v1/internal/nudges, gated by the fleet internal secret).
Every fleet stall's inbox port answers this shape:
{"count": n, "nudges": [{"message": {...}, ...}], "optouts": [...]}.
"""

import json


def read_inbox(origin: str, secret: str, http, limit: int = 100) -> list[dict]:
    """The knock messages stored in `origin`'s inbox. Raises
    RuntimeError on a non-200 read (404 = the secret is not set on
    that service; 403 = wrong secret) — the caller decides whether
    an unreadable inbox is fatal or a logged skip."""
    status, _h, body, err = http(
        "POST",
        origin.rstrip("/") + "/v1/internal/nudges",
        body=json.dumps({"limit": limit}),
        headers={"x-fleet-internal-secret": secret},
        attempts=2,
    )
    if status != 200:
        raise RuntimeError(f"inbox read at {origin} failed: status={status} error={err}")
    doc = json.loads(body)
    messages = []
    for item in doc.get("nudges") or []:
        if isinstance(item, dict) and isinstance(item.get("message"), dict):
            messages.append(item["message"])
    return messages
