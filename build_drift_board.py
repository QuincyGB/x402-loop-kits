#!/usr/bin/env python3
"""build_drift_board.py — regenerate docs/drift-board.html.

The Public Bazaar Drift Board is a free static page generated from
REAL Verdict Index data:

  --changes  the evidence JSON of a paid POST /v1/index/changes call
             (seed_once.py output: {"url", "price_units", "receipt",
             "response"}). That call is Verdict Row's OWN data pull
             and the page labels it as such, with the settlement tx.
  --catalog  a fresh free public CDP catalog pull:
             {"pulled_at": iso, "count": n, "rows": [normalized rows]}
             (rows as produced by stall-row's indexfeed.fetch_catalogue).

Regenerate with:
  python3 build_drift_board.py --changes <evidence.json> \
      --catalog <pull.json> --out docs/drift-board.html

Honesty rules baked into the page: the diff's summary counts are
full counts; the per-event sections show the route's capped event
sample and say so; "most called" and "most recently updated" come
from the current-catalog pull and are labelled as current-catalog
reads, not diff results; every figure carries its as-of time.
"""

from __future__ import annotations

import argparse
import html
import json
import time

STYLE = """
  body { font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; color: #1a1a1a; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.92rem; }
  th { background: #f4f4f4; }
  .note { background: #f8f8f2; border-left: 4px solid #c9a227; padding: 0.6rem 1rem; }
  .tiles { display: flex; flex-wrap: wrap; gap: 0.6rem; margin: 1rem 0; }
  .tile { border: 1px solid #ccc; border-radius: 6px; padding: 0.5rem 0.9rem; min-width: 8.5rem; }
  .tile b { display: block; font-size: 1.25rem; }
  code { background: #f0f0f0; padding: 0 0.25rem; word-break: break-all; }
  footer { color: #666; font-size: 0.85rem; margin-top: 2rem; }
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _usd(units) -> str:
    try:
        return f"${int(units) / 1_000_000:.4g}"
    except (TypeError, ValueError):
        return esc(units)


def _pct(before, after) -> float | None:
    try:
        b, a = int(before), int(after)
    except (TypeError, ValueError):
        return None
    if b == 0:
        return None
    return (a - b) / b * 100.0


def _rows_table(rows: list[list[str]], headers: list[str]) -> str:
    out = ["<table><tr>"] + [f"<th>{esc(h)}</th>" for h in headers] + ["</tr>"]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def build(changes_evidence: dict, catalog: dict) -> str:
    changes = changes_evidence["response"]
    receipt = changes_evidence.get("receipt") or {}
    summary = changes["summary"]
    events = changes.get("events") or []
    rows = catalog.get("rows") or []

    before = summary["resources_before"]
    after = summary["resources_after"]
    removed = summary["removed"]
    vanish_rate = (removed / before * 100.0) if before else 0.0

    field_changes = [e for e in events if e["kind"] == "field_changed"]
    rotations = [e for e in field_changes if e["field"] == "payTo"]
    price_moves = []
    for e in field_changes:
        if e["field"] == "amount":
            pct = _pct(e.get("before"), e.get("after"))
            if pct is not None:
                price_moves.append((abs(pct), pct, e))
    price_moves.sort(key=lambda t: -t[0])
    added_sample = [e for e in events if e["kind"] == "added"]
    removed_sample = [e for e in events if e["kind"] == "removed"]
    total_events = summary["field_changes"] + summary["added"] + summary["removed"]

    by_calls = sorted(
        rows, key=lambda r: (r.get("calls30d") or 0), reverse=True
    )[:15]
    solana_rows = [
        r for r in rows if not str(r.get("network") or "").startswith("eip155:")
    ]
    solana_by_calls = sorted(
        solana_rows, key=lambda r: (r.get("calls30d") or 0), reverse=True
    )[:10]
    recent = sorted(
        (r for r in rows if r.get("lastUpdated")),
        key=lambda r: str(r["lastUpdated"]),
        reverse=True,
    )[:10]

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Bazaar Drift Board — Verdict Row</title>",
        f"<style>{STYLE}</style></head><body>",
        "<h1>Bazaar Drift Board</h1>",
        f"<p><strong>Generated {esc(now_iso)}.</strong> What moved in the "
        "x402 Bazaar catalog between the Verdict Index snapshots of "
        f"<strong>{esc(changes['baseline_at'])}</strong> and "
        f"<strong>{esc(changes['current_at'])}</strong>, plus a current-"
        "catalog read pulled "
        f"<strong>{esc(catalog.get('pulled_at'))}</strong>.</p>",
        '<p class="note">Data sources, stated plainly: the diff below '
        "comes from Verdict Row's <em>own</em> paid call to its Verdict "
        "Index (<code>POST /v1/index/changes</code>, $0.10, settled tx "
        f"<code>{esc(receipt.get('transaction'))}</code>) — our own data "
        "pull, labelled as such. Summary counts are the full diff; the "
        f"per-event sections show the route's capped sample "
        f"({esc(changes.get('events_returned'))} of {total_events:,} "
        "events, field changes first). The most-called, Solana, and "
        "recently-updated sections are reads of the current public CDP "
        "catalog pull, not diff results.</p>",
        '<div class="tiles">',
        f'<div class="tile"><b>{before:,}</b>resources before</div>',
        f'<div class="tile"><b>{after:,}</b>resources after</div>',
        f'<div class="tile"><b>{summary["added"]:,}</b>added</div>',
        f'<div class="tile"><b>{removed:,}</b>removed ({vanish_rate:.2f}% vanishing rate)</div>',
        f'<div class="tile"><b>{summary["field_changes"]}</b>field changes</div>',
        f'<div class="tile"><b>{len(rotations)}</b>payTo rotations in sample</div>',
        "</div>",
    ]

    if price_moves:
        parts.append("<h2>Biggest price moves (diff sample)</h2>")
        parts.append(_rows_table(
            [
                [
                    f"<code>{esc(e['resource'])}</code>",
                    f"{_usd(e.get('before'))} → {_usd(e.get('after'))}",
                    f"{pct:+.1f}%",
                ]
                for _abs, pct, e in price_moves[:10]
            ],
            ["Resource", "Price", "Change"],
        ))

    if rotations:
        parts.append("<h2>Notable payTo rotations (diff sample)</h2>")
        parts.append(_rows_table(
            [
                [
                    f"<code>{esc(e['resource'])}</code>",
                    f"<code>{esc(e.get('before'))}</code>",
                    f"<code>{esc(e.get('after'))}</code>",
                ]
                for e in rotations[:25]
            ],
            ["Resource", "payTo before", "payTo after"],
        ))

    if added_sample:
        parts.append(
            f"<h2>New listings (diff sample — {summary['added']:,} added in total)</h2>"
        )
        parts.append(_rows_table(
            [
                [f"<code>{esc(e['resource'])}</code>", esc(e.get("serviceName"))]
                for e in added_sample[:25]
            ],
            ["Resource", "Service"],
        ))

    if removed_sample:
        parts.append(
            f"<h2>Vanished listings (diff sample — {removed:,} removed in total)</h2>"
        )
        parts.append(_rows_table(
            [
                [f"<code>{esc(e['resource'])}</code>", esc(e.get("serviceName"))]
                for e in removed_sample[:25]
            ],
            ["Resource", "Service"],
        ))

    parts.append("<h2>Most called in the current catalog (30d)</h2>")
    parts.append(_rows_table(
        [
            [
                f"<code>{esc(r['resource'])}</code>",
                esc(r.get("serviceName")),
                f"{(r.get('calls30d') or 0):,}",
                _usd(r.get("amount")),
            ]
            for r in by_calls
        ],
        ["Resource", "Service", "Calls 30d", "Price"],
    ))

    parts.append(
        f"<h2>Solana slice</h2><p>{len(solana_rows):,} of "
        f"{catalog.get('count', len(rows)):,} current catalog resources "
        "are on non-EVM (Solana) networks. Most called among them:</p>"
    )
    parts.append(_rows_table(
        [
            [
                f"<code>{esc(r['resource'])}</code>",
                esc(r.get("network")),
                f"{(r.get('calls30d') or 0):,}",
                _usd(r.get("amount")),
            ]
            for r in solana_by_calls
        ],
        ["Resource", "Network", "Calls 30d", "Price"],
    ))

    if recent:
        parts.append("<h2>Most recently updated (current catalog)</h2>")
        parts.append(_rows_table(
            [
                [
                    f"<code>{esc(r['resource'])}</code>",
                    esc(r.get("serviceName")),
                    esc(r.get("lastUpdated")),
                ]
                for r in recent
            ],
            ["Resource", "Service", "Last updated"],
        ))

    parts.append(
        "<footer>Built by Verdict Row from its Verdict Index "
        "(snapshots of the public CDP Bazaar catalog, refreshed about "
        "every 6 hours). Regenerate: <code>python3 build_drift_board.py "
        "--changes &lt;seed evidence&gt; --catalog &lt;catalog pull&gt; "
        "--out docs/drift-board.html</code>. Figures are catalog reads "
        "at the stated times, not endorsements of any listing.</footer>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changes", required=True, help="seed_once.py evidence JSON")
    ap.add_argument("--catalog", required=True, help="CDP catalog pull JSON")
    ap.add_argument("--out", default="docs/drift-board.html")
    args = ap.parse_args()
    with open(args.changes) as f:
        changes = json.load(f)
    with open(args.catalog) as f:
        catalog = json.load(f)
    page = build(changes, catalog)
    with open(args.out, "w") as f:
        f.write(page)
    print(f"wrote {args.out} ({len(page)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
