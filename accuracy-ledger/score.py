#!/usr/bin/env python3
"""Score the accuracy ledger under the rules in METHODOLOGY.md.

Rules were fixed in writing on 2026-10-26 BEFORE the first run:
mature at +7d (and re-evaluated at +30d); collapsed = pair gone or
liquidity < $1,000; SOLID correct iff not collapsed and move > -30%;
DANGER correct iff collapsed or move <= -30%, incorrect iff move
>= +30% without collapse, else inconclusive; CAUTION never scored;
records without a baseline price are survival-scored only; transient
fetch failures stay pending. Hit rate is published only when at least
one record has matured, always with its n.

Usage: score.py [verdicts.jsonl] [snapshot.json]
Network (DEXScreener) is touched only for mature records.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

DEX = "https://api.dexscreener.com"
COLLAPSE_LIQUIDITY_USD = 1_000.0
MOVE_BAND_PCT = 30.0
HORIZONS = (7, 30)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_pair(address: str, chain: str, pair_address: str | None):
    """Returns ('ok', pair|None) — pair None means DEXScreener answered
    and has no pair for the token — or ('error', None) on any transient
    failure, so a network hiccup never reads as a collapse."""
    url = f"{DEX}/tokens/v1/{chain}/{address}"
    req = urllib.request.Request(url, headers={"User-Agent": "accuracy-ledger/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pairs = json.load(r)
    except Exception:
        return "error", None
    if not isinstance(pairs, list):
        return "error", None
    pairs = [
        p
        for p in pairs
        if (p.get("baseToken") or {}).get("address", "").lower() == address.lower()
    ]
    if not pairs:
        return "ok", None
    if pair_address:
        for p in pairs:
            if (p.get("pairAddress") or "").lower() == pair_address.lower():
                return "ok", p
    pairs.sort(key=lambda p: _num((p.get("liquidity") or {}).get("usd")) or 0, reverse=True)
    return "ok", pairs[0]


def evaluate(record: dict, outcome) -> dict:
    """Pure scoring: outcome is ('ok', pair|None) or ('error', None)."""
    verdict = record.get("verdict")
    if verdict == "CAUTION":
        return {"outcome": "excluded_caution"}
    status, pair = outcome
    if status == "error":
        return {"outcome": "pending_fetch_error"}
    base_price = record.get("price_usd_at_verdict")
    if pair is None:
        collapsed, liq_now, price_now, move = True, None, None, None
    else:
        liq_now = _num((pair.get("liquidity") or {}).get("usd"))
        price_now = _num(pair.get("priceUsd"))
        collapsed = liq_now is not None and liq_now < COLLAPSE_LIQUIDITY_USD
    if base_price and price_now:
        move = (price_now - base_price) / base_price * 100.0
    else:
        move = None
    detail = {
        "collapsed": collapsed,
        "liquidity_usd_now": liq_now,
        "price_usd_now": price_now,
        "price_move_pct": round(move, 2) if move is not None else None,
    }
    if move is None and not collapsed and pair is not None:
        # No baseline price: survival only, per methodology.
        return {"outcome": "survived_no_baseline", **detail}
    if verdict == "SOLID":
        detail["outcome"] = "incorrect" if (collapsed or move <= -MOVE_BAND_PCT) else "correct"
    elif verdict == "DANGER":
        if collapsed or move <= -MOVE_BAND_PCT:
            detail["outcome"] = "correct"
        elif move >= MOVE_BAND_PCT:
            detail["outcome"] = "incorrect"
        else:
            detail["outcome"] = "inconclusive"
    else:
        detail["outcome"] = "excluded_unknown_verdict"
    return detail


def _age_days(record: dict, now: datetime) -> int:
    ts = datetime.strptime(record["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (now - ts).days


def build_snapshot(records: list[dict], now: datetime, fetcher=fetch_pair) -> dict:
    scored = []
    for rec in records:
        age = _age_days(rec, now)
        entry = {**rec, "age_days": age, "evaluations": {}}
        for horizon in HORIZONS:
            if age < horizon:
                entry["evaluations"][str(horizon)] = {"outcome": "immature"}
                continue
            outcome = fetcher(rec["address"], rec.get("chain") or "base", rec.get("pair_address"))
            entry["evaluations"][str(horizon)] = evaluate(rec, outcome)
        scored.append(entry)

    def horizon_stats(h: int) -> dict:
        outcomes = [e["evaluations"][str(h)]["outcome"] for e in scored]
        correct = outcomes.count("correct")
        incorrect = outcomes.count("incorrect")
        mature = sum(1 for e in scored if e["age_days"] >= h)
        return {
            "records_mature": mature,
            "correct": correct,
            "incorrect": incorrect,
            "inconclusive": outcomes.count("inconclusive"),
            "survived_no_baseline": outcomes.count("survived_no_baseline"),
            "excluded_caution": outcomes.count("excluded_caution"),
            "pending_fetch_error": outcomes.count("pending_fetch_error"),
            "hit_rate": (
                round(correct / (correct + incorrect), 4)
                if (correct + incorrect) > 0
                else None
            ),
            "hit_rate_n": correct + incorrect,
        }

    by_verdict: dict[str, int] = {}
    for e in scored:
        by_verdict[e["verdict"]] = by_verdict.get(e["verdict"], 0) + 1
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules": "METHODOLOGY.md fixed 2026-10-26",
        "status": (
            "tracking"
            if any(e["age_days"] >= HORIZONS[0] for e in scored)
            else "tracking_started_no_mature_records"
        ),
        "coverage": {
            "records": len(scored),
            "by_verdict": by_verdict,
            "tokens": sorted({(e.get("symbol") or e["address"]) for e in scored}),
            "first_record": min((e["ts"] for e in scored), default=None),
            "last_record": max((e["ts"] for e in scored), default=None),
            "self_funded_records": sum(1 for e in scored if e.get("self_funded")),
        },
        "horizons": {str(h): horizon_stats(h) for h in HORIZONS},
        "records": scored,
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "verdicts.jsonl"
    dst = sys.argv[2] if len(sys.argv) > 2 else "snapshot.json"
    with open(src) as f:
        records = [json.loads(line) for line in f if line.strip()]
    snap = build_snapshot(records, datetime.now(timezone.utc))
    with open(dst, "w") as f:
        json.dump(snap, f, indent=2)
    print(
        f"records={snap['coverage']['records']} status={snap['status']} "
        f"mature7={snap['horizons']['7']['records_mature']} "
        f"hit_rate_7d={snap['horizons']['7']['hit_rate']}"
    )


if __name__ == "__main__":
    main()
