"""Token Verdict as a LlamaIndex tool.

Wraps POST /v1/verdict ($0.02, x402 on Base) in a LlamaIndex
`FunctionTool`. Payment goes through a caller-supplied `pay` callable
— the seam where x402-guard plugs in (GuardedClient.pay enforces the
Settled pre-flight, the Recheck drift check, and your spend cap
BEFORE signing). Without a payer, the tool returns the unpaid 402
challenge as structured data instead of raising, so an agent can
decide whether the call is worth paying for.

Usage:
    from token_verdict_tool import token_verdict_tool

    agent_tools = [token_verdict_tool()]                      # dry / challenge-only
    agent_tools = [token_verdict_tool(pay=my_guard_pay_fn)]   # live, via x402-guard
"""

from __future__ import annotations

import base64
import json
from typing import Callable, Optional

import httpx

TOKEN_VERDICT_URL = "https://token-verdict-production.up.railway.app/v1/verdict"

# pay(url, body) -> parsed JSON of the PAID response. x402-guard's
# GuardedClient.pay(url, body) returns a GuardResult whose .data is
# exactly that; adapt it with a one-line lambda (see README).
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


def get_token_verdict(
    address: str,
    chain: str = "base",
    *,
    pay: Optional[PayFn] = None,
    http: httpx.Client | None = None,
    url: str = TOKEN_VERDICT_URL,
) -> dict:
    """Screen one token contract before an agent buys, swaps, or
    routes funds into it. Returns the verdict JSON (SOLID / CAUTION /
    DANGER with a 0–100 score and six market-structure signals), or —
    with no payer configured — {"payment_required": <the 402
    challenge>} so the caller decides whether to pay."""
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


def token_verdict_tool(pay: Optional[PayFn] = None, **kwargs):
    """Build the LlamaIndex FunctionTool. Imported lazily so this
    module (and its tests) work without llama-index installed."""
    from llama_index.core.tools import FunctionTool

    def _tool(address: str, chain: str = "base") -> dict:
        return get_token_verdict(address, chain, pay=pay, **kwargs)

    return FunctionTool.from_defaults(
        fn=_tool,
        name="token_verdict",
        description=(
            "Screen a token contract address for risk before buying or "
            "routing funds: returns SOLID / CAUTION / DANGER with a "
            "0-100 score. Costs $0.02 over x402 (Base USDC) per call."
        ),
    )
