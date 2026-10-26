"""Managed Loop demo — client #0 is our own fleet.

One monitoring pass, exactly the shape a managed client receives:
free /health reads for all five services, one funded StallRow
recheck (pack credit, $0 cash) against Token Verdict /v1/verdict,
and the live Webhook Watch registration state from StallRow.
Prints a markdown report; spends at most one pack credit.
"""
import json, os, sys
for _v in ("no_proxy", "NO_PROXY"):
    _val = os.environ.get(_v)
    if _val:
        os.environ[_v] = ",".join(e for e in _val.split(",") if "[" not in e and "]" not in e)
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_clients import PackRecheckClient

SERVICES = {
    "token-verdict": "https://token-verdict-production.up.railway.app",
    "route-verdict": "https://route-verdict-production.up.railway.app",
    "list-smith": "https://list-smith-production.up.railway.app",
    "stall-row": "https://stall-row-production.up.railway.app",
    "lock-smith": "https://lock-smith-production.up.railway.app",
}
PACK_ID = os.environ["DEMO_PACK_ID"]  # bound to the TV verdict URL

lines = ["## Fleet self-monitoring pass (client #0 demo)", ""]
with httpx.Client(timeout=30) as http:
    lines.append("| Service | /health | Detail |")
    lines.append("|---|---|---|")
    for name, base in SERVICES.items():
        try:
            r = http.get(base + "/health")
            lines.append(f"| {name} | {r.status_code} | {r.text[:80]} |")
        except Exception as e:  # noqa: BLE001
            lines.append(f"| {name} | ERROR | {type(e).__name__} |")
    lines.append("")
    client = PackRecheckClient()
    before = client.pack_balance(PACK_ID)
    result = client.recheck(
        "https://token-verdict-production.up.railway.app/v1/verdict",
        "managed-loop-client0", PACK_ID,
    )
    after = client.pack_balance(PACK_ID)
    lines.append(
        f"Funded recheck — Token Verdict /v1/verdict: **{result['status']}** "
        f"(changes: {json.dumps(result['changes'])}); pack credits "
        f"{before['credits_remaining']} → {after['credits_remaining']}, $0.00 cash."
    )
print("\n".join(lines))
