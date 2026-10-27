#!/usr/bin/env python3
"""Parse verdict-loop's public live log into accuracy-ledger records.

The live log is the only surviving pre-2026-10-26 verdict history:
Token Verdict itself kept no verdict log before the recorder shipped.
Each daily run screens the watchlist tokens and prints, per token, the
verdict + risk score and (in most entries) an analyst "take" carrying
the price and liquidity the verdict was derived from. Records whose
entry has no take (one backfilled run) carry null market fields and
are scored later on liquidity survival only — see METHODOLOGY.md.

Usage: parse_live_log.py <live-log.md> <verdict-loop-config.json>
Writes verdict records as JSON lines to stdout.
"""

from __future__ import annotations

import json
import re
import sys

SECTION = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")
TOKEN_LINE = re.compile(
    r"^-\s+(.+?)\s+\(([A-Z0-9]+)\):\s+verdict \*\*(SOLID|CAUTION|DANGER)\*\*,\s+risk ([0-9.]+)"
)
TAKE_LINE = re.compile(r"^-\s+take:\s+(.*)$")
MONEY = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)([Mk]?)")


def parse_money(text: str) -> float | None:
    m = MONEY.search(text)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    if m.group(2) == "M":
        value *= 1_000_000
    elif m.group(2) == "k":
        value *= 1_000
    return value


def money_after(text: str, marker: str) -> float | None:
    idx = text.find(marker)
    if idx < 0:
        return None
    return parse_money(text[idx:])


def parse(log_text: str, config: dict) -> list[dict]:
    by_label = {t["label"]: t for t in config.get("tokens", [])}
    records: list[dict] = []
    date = None
    pending: dict | None = None

    def flush():
        nonlocal pending
        if pending is not None:
            records.append(pending)
            pending = None

    for raw in log_text.splitlines():
        line = raw.strip()
        sec = SECTION.match(line)
        if sec:
            flush()
            date = sec.group(1)
            continue
        tok = TOKEN_LINE.match(line)
        if tok and date:
            flush()
            label, symbol, verdict, risk = tok.groups()
            token = by_label.get(label)
            pending = {
                "ts": f"{date}T00:00:00Z",
                "ts_precision": "day",
                "source": "verdict-loop-live-log",
                "self_funded": True,
                "address": token["address"] if token else None,
                "chain": token["chain"] if token else "base",
                "symbol": symbol,
                "verdict": verdict,
                "score": float(risk),
                "price_usd_at_verdict": None,
                "liquidity_usd_at_verdict": None,
                "pair_address": None,
                "dex": None,
            }
            continue
        take = TAKE_LINE.match(line)
        if take and pending is not None:
            text = take.group(1)
            pending["price_usd_at_verdict"] = money_after(text, "trades at ")
            pending["liquidity_usd_at_verdict"] = money_after(text, "with ")
            dex = re.search(r"\bon\s+(\w+)\s+with\b", text)
            if dex:
                pending["dex"] = dex.group(1)
    flush()
    return records


def main() -> None:
    with open(sys.argv[1]) as f:
        log_text = f.read()
    with open(sys.argv[2]) as f:
        config = json.load(f)
    for row in parse(log_text, config):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
