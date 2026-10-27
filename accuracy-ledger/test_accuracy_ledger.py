"""Accuracy ledger: parser + scoring rules (fixed in METHODOLOGY.md
before the first run — these tests pin the rules, not the outcomes)."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_live_log
import score

LOG = """# header
## 2026-10-25 — live run

- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 17.3 → **WOULD_BUY**
    - take: WETH (Wrapped Ether) trades at $2365.19 on uniswap with $8.46M in liquidity. On the positive side...
  - Aerodrome AERO (Base) (AERO): verdict **DANGER**, risk 88.0 → **SKIP**
    - take: AERO (Aerodrome) trades at $0.6888 on aerodrome with $7.87M in liquidity. ...
## 2026-10-25 — live run — recovered/backfilled entry
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 16.4 → **WOULD_BUY**
"""

CONFIG = {
    "tokens": [
        {"address": "0x4200000000000000000000000000000000000006", "chain": "base", "label": "Wrapped Ether (Base)"},
        {"address": "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "chain": "base", "label": "Aerodrome AERO (Base)"},
    ]
}


def test_parser_extracts_records_and_takes():
    rows = parse_live_log.parse(LOG, CONFIG)
    assert len(rows) == 3
    weth = rows[0]
    assert weth["verdict"] == "SOLID" and weth["score"] == 17.3
    assert weth["address"] == CONFIG["tokens"][0]["address"]
    assert weth["price_usd_at_verdict"] == 2365.19
    assert weth["liquidity_usd_at_verdict"] == 8_460_000
    assert weth["dex"] == "uniswap"
    # The backfilled entry has no take: nulls, never invented values.
    assert rows[2]["price_usd_at_verdict"] is None
    assert rows[2]["liquidity_usd_at_verdict"] is None


def _pair(price, liq):
    return {"priceUsd": str(price), "liquidity": {"usd": liq}, "pairAddress": "0xp"}


def _rec(verdict, price=100.0):
    return {"verdict": verdict, "price_usd_at_verdict": price}


def test_solid_rules():
    assert score.evaluate(_rec("SOLID"), ("ok", _pair(90, 500_000)))["outcome"] == "correct"
    assert score.evaluate(_rec("SOLID"), ("ok", _pair(69, 500_000)))["outcome"] == "incorrect"
    assert score.evaluate(_rec("SOLID"), ("ok", _pair(90, 500)))["outcome"] == "incorrect"
    assert score.evaluate(_rec("SOLID"), ("ok", None))["outcome"] == "incorrect"


def test_danger_rules():
    assert score.evaluate(_rec("DANGER"), ("ok", _pair(50, 500_000)))["outcome"] == "correct"
    assert score.evaluate(_rec("DANGER"), ("ok", None))["outcome"] == "correct"
    assert score.evaluate(_rec("DANGER"), ("ok", _pair(131, 500_000)))["outcome"] == "incorrect"
    assert score.evaluate(_rec("DANGER"), ("ok", _pair(100, 500_000)))["outcome"] == "inconclusive"


def test_caution_excluded_and_pending_and_no_baseline():
    assert score.evaluate(_rec("CAUTION"), ("ok", _pair(1, 1)))["outcome"] == "excluded_caution"
    assert score.evaluate(_rec("SOLID"), ("error", None))["outcome"] == "pending_fetch_error"
    rec = {"verdict": "SOLID", "price_usd_at_verdict": None}
    assert score.evaluate(rec, ("ok", _pair(5, 50_000)))["outcome"] == "survived_no_baseline"
    assert score.evaluate(rec, ("ok", None))["outcome"] == "incorrect"


def test_snapshot_immature_records_publish_no_hit_rate():
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    recs = [
        {"ts": "2026-10-25T00:00:00Z", "address": "0xa", "chain": "base", "verdict": "SOLID", "score": 10},
        {"ts": "2026-10-26T00:00:00Z", "address": "0xb", "chain": "base", "verdict": "SOLID", "score": 12},
    ]
    snap = score.build_snapshot(recs, now, fetcher=lambda *a: ("error", None))
    assert snap["status"] == "tracking_started_no_mature_records"
    assert snap["coverage"]["records"] == 2
    assert snap["horizons"]["7"]["hit_rate"] is None
    assert snap["horizons"]["7"]["records_mature"] == 0
