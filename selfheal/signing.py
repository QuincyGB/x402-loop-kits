"""Signing for fleet-health nudges — the canonical form from
nudge-inbox.md §3, byte-identical to the sender engine's
(nudge.py) and the receiving inbox's (stall-row
app/services/nudge.py). The spec's worked test vector is pinned in
test_selfheal.py so this implementation cannot drift from either.
"""

import json

from eth_account import Account
from eth_account.messages import encode_defunct

PROTOCOL_LINE = "fleet-health-nudge/v1"


def canonical_text(message: dict) -> str:
    """The exact text that gets signed: protocol line + canonical
    JSON (keys sorted recursively, no insignificant whitespace,
    non-ASCII unescaped) of the message WITHOUT its signature."""
    unsigned = {k: v for k, v in message.items() if k != "signature"}
    body = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return f"{PROTOCOL_LINE}\n{body}"


def recover_signer(message: dict):
    """The address the message's signature recovers to, or None if
    it does not recover at all."""
    try:
        return Account.recover_message(
            encode_defunct(text=canonical_text(message)),
            signature=message["signature"],
        )
    except Exception:  # noqa: BLE001 — an unrecoverable signature is a failed check
        return None


def verify_message(message: dict) -> bool:
    """True iff the signature recovers to the claimed sender."""
    signer = recover_signer(message)
    if signer is None:
        return False
    return signer.lower() == str(message.get("sender", "")).lower()


def dedupe_key(message: dict) -> str:
    """One knock per (sender, route, defect, first_seen) — the same
    key the receiving inbox stores by (stall-row's dedupe_key), so
    the receiver can recognise a knock it has already processed
    when the inbox is re-polled. An escalation knock joins its
    `escalation` marker, exactly as the inbox does."""
    import hashlib

    parts = [
        str(message.get("sender", "")).lower(),
        str(message.get("route", "")),
        str((message.get("defect") or {}).get("code", "")),
        str(message.get("first_seen", "")),
    ]
    if message.get("escalation"):
        parts.append(str(message["escalation"]))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
