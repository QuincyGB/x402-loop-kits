"""Stall Watch sample generator: a live drift report on a prospect's
OWN stall, built only from real Verdict Index snapshot data.

Input is two catalog snapshots in the Index's normalized JSONL shape
(one row per resource: resource, serviceName, description, amount,
asset, network, payTo, calls30d, payers30d) — the same rows StallRow's
IndexStore stores and the drift board renders. The target stall is
selected by service name, origin host, or payTo.

Honesty contract (fleet rule, carried from the outreach pack):
- Every number in the report comes from the two snapshots named in
  it. Nothing is estimated, interpolated, or invented.
- Field-change / added / removed events for the target's resources
  are OBSERVED changes and are reported as such.
- When a window contains NO target-specific change event, the report
  says so and is labelled COUNTS-ONLY: it carries only the counts the
  catalog itself publishes (routes, catalog-reported 30d calls) for
  the two snapshot moments. A counts-only sample is never dressed up
  as an observed drift.

Usage:
  python stallwatch_sample.py --before snap1.jsonl --after snap2.jsonl \
      --service-name "Pocket Network" --out sample.md
  (or --origin agent.pocket.network, or --pay-to 0x…)
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlsplit

TRACKED_FIELDS = ("amount", "asset", "network", "payTo", "description", "serviceName")


def load_snapshot(path: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            resource = row.get("resource")
            if isinstance(resource, str) and resource:
                rows[resource] = row  # last sighting wins, as in the Index
    return rows


def _matches(row: dict, *, service_name=None, origin=None, pay_to=None) -> bool:
    if service_name is not None:
        if service_name.lower() not in (row.get("serviceName") or "").lower():
            return False
    if origin is not None:
        host = urlsplit(row.get("resource") or "").netloc.lower()
        if host != origin.lower():
            return False
    if pay_to is not None:
        if (row.get("payTo") or "").lower() != pay_to.lower():
            return False
    return True


def _target(rows: dict[str, dict], **selector) -> dict[str, dict]:
    return {r: row for r, row in rows.items() if _matches(row, **selector)}


def build_sample(before: dict[str, dict], after: dict[str, dict], **selector) -> dict:
    """The sample as data: target counts for both moments, the
    target-specific change events (possibly none), and the
    catalogue-wide context counts. Pure function of the inputs."""
    b = _target(before, **selector)
    a = _target(after, **selector)
    events: list[dict] = []
    for resource, nrow in a.items():
        orow = b.get(resource)
        if orow is None:
            events.append({"resource": resource, "kind": "added"})
            continue
        for field in TRACKED_FIELDS:
            if orow.get(field) != nrow.get(field):
                events.append(
                    {
                        "resource": resource,
                        "kind": "field_changed",
                        "field": field,
                        "before": orow.get(field),
                        "after": nrow.get(field),
                    }
                )
    for resource in b:
        if resource not in a:
            events.append({"resource": resource, "kind": "removed"})
    events.sort(key=lambda e: (e["resource"], e["kind"], e.get("field") or ""))

    def calls(rows: dict[str, dict]) -> int:
        return sum(int(r.get("calls30d") or 0) for r in rows.values())

    return {
        "selector": {k: v for k, v in selector.items() if v is not None},
        "observation_level": "observed_changes" if events else "counts_only",
        "target": {
            "resources_before": len(b),
            "resources_after": len(a),
            "calls30d_before": calls(b),
            "calls30d_after": calls(a),
            "pay_tos_before": sorted({r.get("payTo") for r in b.values() if r.get("payTo")}),
            "pay_tos_after": sorted({r.get("payTo") for r in a.values() if r.get("payTo")}),
        },
        "catalogue": {"resources_before": len(before), "resources_after": len(after)},
        "events": events,
    }


def render_markdown(sample: dict, *, before_label: str, after_label: str) -> str:
    sel = sample["selector"]
    who = (
        sel.get("service_name")
        or sel.get("origin")
        or sel.get("pay_to")
        or "(unnamed target)"
    )
    t = sample["target"]
    lines = [
        f"# Stall Watch sample — {who}",
        "",
        f"Built {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} from two "
        f"Verdict Index catalog snapshots: `{before_label}` → `{after_label}`. "
        "Every figure below is read from those snapshots; nothing is estimated.",
        "",
    ]
    if sample["observation_level"] == "counts_only":
        lines += [
            "> **Counts-only sample.** No change event touching this stall's "
            "resources was observed between the two snapshots. This report "
            "therefore carries only the counts the catalog itself publishes — "
            "it does not claim any drift was seen.",
            "",
        ]
    lines += [
        "## This stall in the catalog",
        "",
        f"- Listed resources: {t['resources_before']} → {t['resources_after']}",
        f"- Catalog-reported calls, trailing 30d: {t['calls30d_before']:,} → {t['calls30d_after']:,}",
        f"- PayTo(s) in the earlier snapshot: {', '.join(t['pay_tos_before']) or 'none recorded'}",
        f"- PayTo(s) in the later snapshot: {', '.join(t['pay_tos_after']) or 'none recorded'}",
        "",
        "## Observed changes in this window",
        "",
    ]
    if sample["events"]:
        for e in sample["events"]:
            if e["kind"] == "field_changed":
                lines.append(
                    f"- `{e['resource']}` — {e['field']} changed: "
                    f"`{e['before']}` → `{e['after']}`"
                )
            else:
                lines.append(f"- `{e['resource']}` — {e['kind']} in the catalog")
    else:
        lines.append("- None observed for this stall's resources in this window.")
    c = sample["catalogue"]
    lines += [
        "",
        "## Market context (whole catalog, same window)",
        "",
        f"- Catalogued resources overall: {c['resources_before']:,} → {c['resources_after']:,}",
        "",
        "Stall Watch runs this comparison on every new catalog snapshot "
        "(about every 6 hours) and pushes an alert when a change touches "
        "your stall: a payTo rotation, a price change, a listing "
        "vanishing or appearing. Samples are generated from public "
        "catalog metadata only.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--service-name")
    ap.add_argument("--origin")
    ap.add_argument("--pay-to")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    sample = build_sample(
        load_snapshot(args.before),
        load_snapshot(args.after),
        service_name=args.service_name,
        origin=args.origin,
        pay_to=args.pay_to,
    )
    md = render_markdown(sample, before_label=args.before, after_label=args.after)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(json.dumps({"out": args.out, **sample["target"],
                      "observation_level": sample["observation_level"],
                      "events": len(sample["events"])}))


if __name__ == "__main__":
    main()
