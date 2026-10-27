"""Accuracy Ledger — Nov 1 publish automation.

The ledger's first records (2026-10-25/26, from verdict-loop's live
log) mature at +7 days under METHODOLOGY.md: the first mature
scores exist on **2026-11-01**, and not a day before. This script
is the publish step for that date and every scoring run after:

  python publish.py             # gated: before 2026-11-01 it
                                # REFUSES (exit 2) and changes nothing
  python publish.py --dry-run   # any date: prints the maturity
                                # accounting as of today and what the
                                # publish will contain; writes nothing
                                # public, fetches no outcome data
  python publish.py --now 2026-11-01   # test/explicit-clock override
                                # (used by the dry-run tests; a real
                                # publish run leaves --now off)

A real publish run (on/after 2026-11-01):
  1. re-runs score.py, regenerating snapshot.json under the rules
     fixed 2026-10-26 (METHODOLOGY.md) — scores are never edited
     by hand on the way out;
  2. copies the fresh snapshot to docs/accuracy-ledger.json, the
     file the public badge/status pages read;
  3. prints the mature counts and the hit rate WITH its n (null
     stays null — zero mature records publish as zero, not as a
     rate).

Nothing in this script sends, posts, or pushes; committing the
regenerated files is the operator's normal git step.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VERDICTS = os.path.join(HERE, "verdicts.jsonl")
SNAPSHOT = os.path.join(HERE, "snapshot.json")
PUBLIC_OUT = os.path.join(HERE, "..", "docs", "accuracy-ledger.json")
SCORE_PY = os.path.join(HERE, "score.py")

FIRST_PUBLISH_DATE = "2026-11-01"  # first +7d maturity of the 2026-10-25 records
MATURITY_DAYS = 7


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def maturity_accounting(today: datetime) -> dict:
    """Mature/immature record counts as of `today`, from the local
    ledger only — no outcome data, no network. A record is mature
    when today >= ts + 7 days (METHODOLOGY.md)."""
    records = []
    with open(VERDICTS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    mature, immature = [], []
    for r in records:
        (mature if today >= _parse_ts(r["ts"]) + timedelta(days=MATURITY_DAYS) else immature).append(r)
    return {
        "today": today.strftime("%Y-%m-%d"),
        "records": len(records),
        "mature_7d": len(mature),
        "immature_7d": len(immature),
        "first_maturity": (
            min((_parse_ts(r["ts"]) + timedelta(days=MATURITY_DAYS)).strftime("%Y-%m-%d") for r in records)
            if records else None
        ),
    }


def publish(today: datetime) -> dict:
    """The real publish: regenerate the snapshot via score.py and
    copy it to the public docs path. Caller has already passed the
    date gate."""
    proc = subprocess.run([sys.executable, SCORE_PY], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"score.py failed: {proc.stderr[-500:]}")
    with open(SNAPSHOT, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    os.makedirs(os.path.dirname(PUBLIC_OUT), exist_ok=True)
    with open(PUBLIC_OUT, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2)
    seven = snapshot.get("horizons", {}).get("7", {})
    return {
        "published_to": PUBLIC_OUT,
        "records_mature_7d": seven.get("records_mature"),
        "hit_rate": seven.get("hit_rate"),
        "hit_rate_n": seven.get("hit_rate_n"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="override today's date (YYYY-MM-DD) — tests only")
    args = ap.parse_args()
    today = (
        datetime.strptime(args.now, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.now
        else datetime.now(timezone.utc)
    )
    accounting = maturity_accounting(today)
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", **accounting,
                          "would_publish_on": max(FIRST_PUBLISH_DATE, accounting["today"])}, indent=2))
        return 0
    if today.strftime("%Y-%m-%d") < FIRST_PUBLISH_DATE:
        print(
            f"REFUSED: first mature scores exist on {FIRST_PUBLISH_DATE}; "
            f"today is {accounting['today']} ({accounting['mature_7d']} mature records). "
            "Nothing was published, fetched, or changed.",
            file=sys.stderr,
        )
        return 2
    out = publish(today)
    print(json.dumps({"mode": "published", **accounting, **out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
