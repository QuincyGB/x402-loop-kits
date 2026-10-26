# Framework shelves

Token Verdict ($0.02 over x402, Base USDC) packaged for the agent
frameworks loop-builders actually start from. Every shelf shares one
shape: a plain screening function, and a **payment seam** — a
`pay(url, body)` callable you supply. That seam is where
[x402-guard](https://github.com/QuincyGB/x402-guard) plugs in, so the
Settled pre-flight, the Recheck drift check (which can itself spend
**Fleet Pass / recheck-pack credits** via the guard's
`recheck_pack_id` config), and your spend cap all run *before*
anything is signed. With no payer configured, each shelf returns the
unpaid 402 challenge as structured data instead of failing — the
agent decides whether the screen is worth $0.02.

| Shelf | Path | Shape |
|---|---|---|
| ElizaOS plugin | `eliza/` | TypeScript plugin, one `TOKEN_VERDICT` action; `npm run typecheck` to verify |
| LlamaIndex tool | `llamaindex/token_verdict_tool.py` | `FunctionTool` via `token_verdict_tool(pay=...)`; logic importable without llama-index |
| OpenAI Agents SDK example | `openai-agents/token_verdict_agent.py` | `screen_token()` + `build_agent()`; runnable $0 challenge probe: `python token_verdict_agent.py` |

Tests: `frameworks/tests/test_shelves.py` (offline, MockTransport) —
run with the loop-kits venv: `python -m pytest frameworks/tests -q`.

Honest status: these are examples published in this repo, not
registry packages (the GOAT plugin and the AgentKit providers are
the fleet's registry-published shelves). No shelf here has an
external user yet — like the kits themselves, they exist so a
loop-builder can copy one in minutes instead of writing x402
plumbing.
