"""Token Verdict as an OpenAI Agents SDK tool — a runnable example.

The screening logic lives in `screen_token`, a plain function with no
SDK dependency: it POSTs to Token Verdict ($0.02 over x402 on Base),
paying through a caller-supplied `pay` callable — the seam where
x402-guard plugs in, so caps and drift checks run BEFORE signing.
With no payer it returns the unpaid 402 challenge as data.

`build_agent` wires the function into an Agents SDK `Agent` via
`function_tool`. Run this file directly for a no-SDK smoke pass
(challenge-only against the live endpoint, spends $0):

    python token_verdict_agent.py            # live 402 probe, $0
    TOKEN_VERDICT_PAY=guard python ...       # (documented seam, see README)
"""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Callable, Optional

import httpx

TOKEN_VERDICT_URL = "https://token-verdict-production.up.railway.app/v1/verdict"
PayFn = Callable[[str, dict], dict]


def _decode_challenge(response: httpx.Response) -> dict | None:
    raw = response.headers.get("payment-required")
    if raw:
        try:
            data = json.loads(base64.b64decode(raw))
            if isinstance(data, dict) and data.get("accepts"):
                return data
        except ValueError:
            pass
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("accepts"):
            return data
    except ValueError:
        pass
    return None


def screen_token(
    address: str,
    chain: str = "base",
    *,
    pay: Optional[PayFn] = None,
    http: httpx.Client | None = None,
    url: str = TOKEN_VERDICT_URL,
) -> dict:
    """Return a Token Verdict screen for one contract: the verdict
    JSON when paid, or {"payment_required": <402 challenge>} when no
    payer is configured."""
    body = {"address": address, "chain": chain}
    if pay is not None:
        return pay(url, body)
    client = http or httpx.Client(timeout=30.0)
    response = client.post(url, json=body)
    if response.status_code == 200:
        return response.json()
    if response.status_code == 402:
        challenge = _decode_challenge(response)
        if challenge is not None:
            return {"payment_required": challenge}
    return {
        "error": f"token verdict returned HTTP {response.status_code}",
        "detail": response.text[:300],
    }


def build_agent(pay: Optional[PayFn] = None, model: str = "gpt-5.2"):
    """Wire screen_token into an OpenAI Agents SDK agent. The SDK is
    imported lazily — this module imports and tests without it."""
    from agents import Agent, function_tool

    @function_tool
    def token_verdict(address: str, chain: str = "base") -> dict:
        """Screen a token contract for risk (SOLID / CAUTION /
        DANGER, 0-100 score) before buying or routing funds."""
        return screen_token(address, chain, pay=pay)

    return Agent(
        name="Token Screener",
        instructions=(
            "You screen tokens before any purchase. Always call "
            "token_verdict first and refuse to endorse a token rated "
            "DANGER; flag CAUTION with its score and reasons."
        ),
        tools=[token_verdict],
        model=model,
    )


if __name__ == "__main__":
    for _v in ("no_proxy", "NO_PROXY"):
        _val = os.environ.get(_v)
        if _val:
            os.environ[_v] = ",".join(
                e for e in _val.split(",") if "[" not in e and "]" not in e
            )
    out = screen_token("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    if "payment_required" in out:
        accept = out["payment_required"]["accepts"][0]
        print(
            "challenge ok: "
            f"{accept['amount']} units on {accept['network']} to {accept['payTo']}"
        )
        sys.exit(0)
    print(f"unexpected result: {str(out)[:200]}")
    sys.exit(1)
