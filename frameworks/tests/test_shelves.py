"""Smoke tests for the framework shelves (LlamaIndex tool + OpenAI
Agents example). Fully offline: a MockTransport plays Token Verdict.
The Eliza plugin is typechecked separately (npm run typecheck in
frameworks/eliza) because it is TypeScript."""

import base64
import importlib.util
import json
import pathlib

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHALLENGE = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": "20000",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "payTo": "0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F",
            "extra": {"name": "USD Coin", "version": "2"},
        }
    ],
}


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _challenge_handler(request):
    return httpx.Response(
        402,
        headers={
            "payment-required": base64.b64encode(
                json.dumps(CHALLENGE).encode()
            ).decode()
        },
        json={"error": "Payment required"},
    )


def test_llamaindex_tool_returns_challenge_without_payer():
    mod = _load("tv_llama", "llamaindex/token_verdict_tool.py")
    out = mod.get_token_verdict(
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", http=_client(_challenge_handler)
    )
    assert out["payment_required"]["accepts"][0]["amount"] == "20000"


def test_llamaindex_tool_uses_payer_seam():
    mod = _load("tv_llama2", "llamaindex/token_verdict_tool.py")
    seen = {}

    def pay(url, body):
        seen.update(body)
        return {"verdict": "SOLID", "score": 12}

    out = mod.get_token_verdict("0xabc", pay=pay)
    assert out["verdict"] == "SOLID"
    assert seen["address"] == "0xabc"


def test_openai_agents_screen_returns_challenge_without_payer():
    mod = _load("tv_agents", "openai-agents/token_verdict_agent.py")
    out = mod.screen_token(
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", http=_client(_challenge_handler)
    )
    assert out["payment_required"]["accepts"][0]["network"] == "eip155:8453"


def test_openai_agents_screen_paid_path():
    mod = _load("tv_agents2", "openai-agents/token_verdict_agent.py")

    def handler(request):
        return httpx.Response(200, json={"verdict": "CAUTION", "score": 55})

    out = mod.screen_token("0xabc", http=_client(handler))
    assert out["verdict"] == "CAUTION"
