"""Badge v2 evaluator: the outcome-scoring criterion.

Badge v1 certifies the payment surface (live 402 exact-match,
delivery evidence, no unannounced drift). V2 adds, for services
with routes whose claims we score, a fourth question: DO THE
CLAIMS TURN OUT RIGHT — measured by a public accuracy ledger whose
rules were fixed before scoring?

This evaluator reads the Accuracy Ledger snapshot
(accuracy-ledger/snapshot.json, produced by accuracy-ledger/score.py
under accuracy-ledger/METHODOLOGY.md) and reports, per fleet
service:

  - scored_route: whether the service has a route whose claims the
    ledger scores (today only Token Verdict's verdicts);
  - ledger_state: tracking (records exist, none mature yet),
    scored (mature records exist and a hit rate — or an honest
    inconclusive accounting — is published), or no_ledger;
  - v2_status: for scored services, TRACKING until the first mature
    scores publish, then PASS/FAIL on whether the ledger publishes
    its outcomes (hit rate WITH its n) — v2 grades the existence
    and honesty of the outcome record, not a hit-rate threshold:
    a low hit rate honestly published passes v2; a hidden one fails;
  - for services with no scored route: NOT_APPLICABLE, stated as
    such — they are not failed for lacking a claim we never scored,
    and they are not credited with an outcome record they don't have.

Output: badge/badge-v2-<date>.json + a printed summary. $0, offline.
"""

from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_SNAPSHOT = os.path.join(HERE, "..", "accuracy-ledger", "snapshot.json")

SCORED_SERVICES = {
    "token-verdict": "Token Verdict verdicts (SOLID/CAUTION/DANGER) — scored at +7d/+30d under accuracy-ledger/METHODOLOGY.md",
}
FLEET = ["token-verdict", "route-verdict", "list-smith", "stall-row", "lock-smith"]


def evaluate(snapshot: dict, today: str) -> dict:
    horizons = snapshot.get("horizons", {})
    mature = sum(h.get("records_mature", 0) for h in horizons.values())
    services = {}
    for name in FLEET:
        if name not in SCORED_SERVICES:
            services[name] = {
                "scored_route": None,
                "ledger_state": "no_ledger",
                "v2_status": "NOT_APPLICABLE — no outcome-scored route; v1 criteria only",
            }
            continue
        if snapshot.get("status") == "tracking_started_no_mature_records" or mature == 0:
            state, status = "tracking", "TRACKING — ledger live, no mature outcomes yet; v2 cannot pass until the first mature scores publish"
        else:
            state = "scored"
            seven = horizons.get("7", {})
            published = seven.get("hit_rate") is not None or seven.get("records_mature", 0) > 0
            status = "PASS — outcomes published with their n" if published else "FAIL — mature records exist but no outcomes published"
        services[name] = {
            "scored_route": SCORED_SERVICES[name],
            "ledger_state": state,
            "v2_status": status,
            "coverage": snapshot.get("coverage"),
            "horizons": horizons,
        }
    return {
        "evaluated_at": today,
        "criterion": "Badge v2 — accuracy-ledger outcome scoring (see CRITERIA.md)",
        "ledger_snapshot_generated_at": snapshot.get("generated_at"),
        "services": services,
    }


def main() -> None:
    with open(LEDGER_SNAPSHOT, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    out = evaluate(snapshot, today)
    path = os.path.join(HERE, f"badge-v2-{today}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    for name, svc in out["services"].items():
        print(f"{name}: {svc['v2_status']}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
