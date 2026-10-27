"""Managed Loop runner: one monitoring pass for one managed client,
plus the weekly report — the operational half of OFFER.md.

We (the operator) run this; the client integrates nothing. A client
config (JSON, schema in CLIENT-PACKAGE.md) names the endpoints to
watch and how each is funded:

  - a recheck pack bound to that endpoint (pack credit per check), or
  - a Fleet Pass (listed price per check, debited server-side).

One pass rechecks every endpoint, classifies the changes (payTo and
amount changes are CRITICAL, mirroring the inspector kit), pushes an
alert to the client's webhook for each CHANGED endpoint, and writes
the weekly-report markdown — per-endpoint status, every change with
its diff, and the funding balances after the pass.

Modes:
  (default)  DRY RUN — mock recheck results, $0, no webhook POSTs;
             the report is labelled DRY RUN so it can never be
             mistaken for a delivered client report.
  --live     Real funded checks via live_clients (pack or pass).
             Webhook alerts are POSTed only in this mode.

The runner never buys packs or passes and never falls back between
funding kinds: a check that cannot be funded is reported FAILED for
that endpoint, in the report, in plain words.
"""

from __future__ import annotations

import argparse
import json
import time

CRITICAL_FIELDS = {"payTo", "amount", "asset", "network"}


def classify(result: dict) -> tuple[str, list[str]]:
    """(status, alert lines) for one recheck result. CHANGED with a
    critical field leads with a CRITICAL line, as in inspector_loop."""
    status = result.get("status", "UNKNOWN")
    alerts: list[str] = []
    for change in result.get("changes", []):
        field = change.get("field")
        line = f"{field}: {change.get('before')} -> {change.get('after')}"
        if field in CRITICAL_FIELDS:
            alerts.append(f"CRITICAL {line}")
        else:
            alerts.append(line)
    return status, alerts


class DryRunRechecker:
    """$0 stand-in: every endpoint reports a labelled dry-run
    BASELINE. Used whenever --live is absent, whatever the config."""

    def recheck(self, endpoint: dict) -> dict:
        return {
            "status": "BASELINE",
            "changes": [],
            "dry_run": True,
            "url": endpoint["url"],
        }

    def balance(self, endpoint: dict) -> dict | None:
        return None


class LiveRechecker:
    """Funded checks via live_clients. One client per funding kind,
    built lazily so a config using only packs never needs a pass."""

    def __init__(self, http=None):
        self._http = http
        self._pack_client = None
        self._pass_clients: dict[str, object] = {}

    def _pack(self):
        if self._pack_client is None:
            from live_clients import PackRecheckClient

            self._pack_client = PackRecheckClient(http=self._http)
        return self._pack_client

    def _pass(self, pass_id: str):
        if pass_id not in self._pass_clients:
            from live_clients import FleetPassClient

            self._pass_clients[pass_id] = FleetPassClient(pass_id, http=self._http)
        return self._pass_clients[pass_id]

    def recheck(self, endpoint: dict) -> dict:
        funding = endpoint["funding"]
        if funding["kind"] == "pack":
            return self._pack().recheck(
                endpoint["url"], endpoint.get("watch_id") or "", funding["pack_id"]
            )
        if funding["kind"] == "fleet_pass":
            return self._pass(funding["pass_id"]).call(
                "/v1/recheck",
                {"url": endpoint["url"], "watch_id": endpoint.get("watch_id")},
            )
        raise ValueError(f"unknown funding kind: {funding['kind']}")

    def balance(self, endpoint: dict) -> dict | None:
        funding = endpoint["funding"]
        try:
            if funding["kind"] == "pack":
                return self._pack().pack_balance(funding["pack_id"])
            if funding["kind"] == "fleet_pass":
                return self._pass(funding["pass_id"]).balance()
        except Exception:  # noqa: BLE001 — a balance read must not kill the pass
            return None
        return None


def run_pass(config: dict, rechecker, *, deliver=None, now=None) -> tuple[str, dict]:
    """One pass over the config's endpoints. `deliver(payload)` is
    called once per CHANGED endpoint (the caller wires the webhook;
    tests capture). Returns (report_markdown, summary)."""
    now = now or time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    dry = isinstance(rechecker, DryRunRechecker)
    lines = [
        f"# Managed Loop weekly report — {config['client']}",
        "",
        f"Pass at {stamp} · tier: {config.get('tier', 'Watch')}"
        + (" · **DRY RUN — mock results, not a delivered report**" if dry else ""),
        "",
        "| Endpoint | Status | Changes | Funding balance after pass |",
        "|---|---|---|---|",
    ]
    alerts: list[dict] = []
    summary = {"client": config["client"], "endpoints": 0, "changed": 0,
               "critical": 0, "failed": 0, "alerts": 0, "dry_run": dry}
    detail: list[str] = []
    for endpoint in config["endpoints"]:
        summary["endpoints"] += 1
        url = endpoint["url"]
        try:
            result = rechecker.recheck(endpoint)
            status, changes = classify(result)
        except Exception as e:  # noqa: BLE001 — one endpoint must not kill the pass
            status, changes = "FAILED", []
            detail.append(f"## {url}\n\nCheck FAILED: {type(e).__name__}: {e}\n")
            summary["failed"] += 1
            result = {}
        balance = rechecker.balance(endpoint)
        bal = "—"
        if balance is not None:
            if "credits_remaining" in balance:
                bal = f"{balance['credits_remaining']} pack credits"
            elif "balance_usd" in balance:
                bal = f"${balance['balance_usd']:.2f} pass balance"
        lines.append(f"| {url} | {status} | {len(changes)} | {bal} |")
        if status == "CHANGED":
            summary["changed"] += 1
            critical = [c for c in changes if c.startswith("CRITICAL")]
            summary["critical"] += len(critical)
            payload = {
                "event": "managed_loop_alert",
                "client": config["client"],
                "endpoint": url,
                "status": status,
                "changes": result.get("changes", []),
                "alerts": changes,
                "at": stamp,
            }
            alerts.append(payload)
            detail.append(f"## {url} — CHANGED\n\n" + "\n".join(f"- {c}" for c in changes) + "\n")
        elif status not in ("FAILED",):
            detail.append(f"## {url} — {status}\n")
    lines += ["", *detail]
    if deliver is not None:
        for payload in alerts:
            deliver(payload)
            summary["alerts"] += 1
    lines.append(
        f"_Pass summary: {summary['endpoints']} endpoints, "
        f"{summary['changed']} changed ({summary['critical']} critical), "
        f"{summary['failed']} failed, {summary['alerts']} alerts pushed._"
    )
    return "\n".join(lines) + "\n", summary


def _webhook_deliverer(config: dict, http):
    webhook = config.get("webhook_url")
    if not webhook:
        return None

    def deliver(payload: dict) -> None:
        http.post(webhook, json=payload, timeout=15)

    return deliver


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    with open(args.config, encoding="utf-8") as fh:
        config = json.load(fh)
    if args.live:
        import httpx

        from live_clients import _default_http

        http = _default_http()
        rechecker = LiveRechecker(http=http)
        deliver = _webhook_deliverer(config, http)
    else:
        rechecker = DryRunRechecker()
        deliver = None
    report, summary = run_pass(config, rechecker, deliver=deliver)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
