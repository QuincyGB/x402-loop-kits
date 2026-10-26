"""INSPECTOR LOOP kit — re-check endpoints on a schedule, diff, report.

Pattern: the loop an inspector/router/catalogue runs to keep its records
honest (it is also the template behind Settled-style re-tests and behind
the fleet's own keepalive checks):
  For each endpoint: POST /v1/recheck with a watch_id. First pass stores
  the BASELINE; later passes return UNCHANGED or CHANGED with a
  field-by-field diff (amount, asset, payTo, network, schema hash,
  description hash, page body). The server keeps watch state across
  redeploys; this kit keeps only the last report, for diffing summaries.

Payment: spend RECHECK PACK credits by default — buy the pack once per
endpoint (POST /v1/recheck/pack, $1.00 = 250 checks, 90 days), then every
check is a credit, not a settlement. Per-call mode ($0.005/check) exists
in the config for one-endpoint trials, and it goes through the daily cap
like everything else. Balance reads are FREE.

Low balance follows ../2-pack-default/COPY-DRAFTS.md §L: warn at <=25 and
<=10 credits and at <=7 days to expiry; stop at 0 / expired; NEVER
auto-buy a pack and NEVER silently fall back from pack to per-call.

DRY-RUN IS THE DEFAULT AND CANNOT PAY. Live pack mode IS implemented
(`--live`, client in live_clients.py): a pack id is the credential, so
a live inspector pass spends pack credits and $0 cash — no signer, no
settlement. Per-call live mode stays deliberately unimplemented: pay
through x402-guard in your fork.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from loopkit_common import (DailyCap, PassResult, PlannedCall,
                            SpendCapExceeded, pack_usable, pack_warnings)

RECHECK_URL = "https://stall-row-production.up.railway.app/v1/recheck"
RECHECK_PER_CALL_UNITS = 5_000  # $0.005

# Fields whose change should always alert loudly (money-moving terms).
CRITICAL_FIELDS = {"amount", "payTo", "asset", "network"}


class InspectorClient(Protocol):
    def recheck(self, url: str, watch_id: str, pack_id: str | None) -> dict: ...
    def pack_balance(self, pack_id: str) -> dict: ...


@dataclass
class InspectorConfig:
    endpoints: list[dict] = field(default_factory=list)  # {url, watch_id, pack_id?}
    use_packs: bool = True
    daily_cap_units: int = 100_000  # $0.10: caps per-call mode + nothing else
    budget_state: str = "inspector-budget.json"


def classify_changes(payload: dict) -> tuple[str, list[str]]:
    """(status, alerts) from a /v1/recheck response. CHANGED on a critical
    field is a loud alert; CHANGED elsewhere is a noted alert."""
    status = str(payload.get("status", ""))
    alerts: list[str] = []
    if status == "CHANGED":
        for change in payload.get("changes", []):
            f = str(change.get("field"))
            loud = "CRITICAL " if f in CRITICAL_FIELDS else ""
            alerts.append(f"{loud}CHANGED {payload.get('url')}: {f} "
                          f"{change.get('before')} -> {change.get('after')}")
    return status, alerts


def run_pass(cfg: InspectorConfig, client: InspectorClient | None,
             *, dry_run: bool = True) -> PassResult:
    result = PassResult(mode="DRY-RUN" if dry_run else "STUB")
    for ep in cfg.endpoints:
        if cfg.use_packs and ep.get("pack_id"):
            result.planned.append(PlannedCall(
                f"recheck {ep.get('watch_id')} (pack credit)", 0,
                "1 pack credit, no settlement"))
        else:
            result.planned.append(PlannedCall(
                f"recheck {ep.get('watch_id')} (per-call)", RECHECK_PER_CALL_UNITS))

    if dry_run or client is None:
        for c in result.planned:
            result.lines.append(
                f"DRY-RUN would pay ${c.price_units / 1_000_000:.3f} — {c.label}"
                if c.price_units else f"DRY-RUN would spend a pack credit — {c.label}")
        result.lines.append(
            "policy: first pass = BASELINE, then alert on CHANGED; amount / "
            "payTo / asset / network changes are CRITICAL. No result invented.")
        return result

    cap = DailyCap(cfg.daily_cap_units, cfg.budget_state)
    for ep in cfg.endpoints:
        pack_id = ep.get("pack_id") if cfg.use_packs else None
        if pack_id:
            balance = client.pack_balance(pack_id)  # free
            for w in pack_warnings(balance):
                result.alerts.append(f"{ep.get('watch_id')}: {w}")
            if not pack_usable(balance):
                result.lines.append(f"recheck {ep.get('watch_id')}: SKIPPED — "
                                    "pack unusable, no per-call fallback.")
                continue
        else:
            try:
                cap.authorize(RECHECK_PER_CALL_UNITS)  # BEFORE signing
            except SpendCapExceeded as e:
                result.alerts.append(f"CAP STOP: {e}")
                break
            result.spent_units += RECHECK_PER_CALL_UNITS
        payload = client.recheck(ep["url"], ep.get("watch_id", ""), pack_id)
        status, alerts = classify_changes(payload)
        result.alerts.extend(alerts)
        result.lines.append(f"recheck {ep.get('watch_id')}: {status}")
    return result


if __name__ == "__main__":
    import os
    import sys

    if "--live" in sys.argv:
        # Live pack mode: spends ONE pack credit per endpoint, $0 cash.
        # Pack id comes from the environment — never hard-code one.
        pack_id = os.environ.get("LOOPKIT_PACK_ID", "").strip()
        if not pack_id:
            print("LOOPKIT_PACK_ID is not set — refusing to run live.")
            sys.exit(2)
        from live_clients import PackRecheckClient

        live = InspectorConfig(endpoints=[{
            "url": "https://token-verdict-production.up.railway.app/v1/verdict",
            "watch_id": "x402-loop-kits-demo", "pack_id": pack_id}])
        out = run_pass(live, PackRecheckClient(), dry_run=False)
        for line in out.lines:
            print(line)
        for alert in out.alerts:
            print(f"ALERT: {alert}")
        print(f"spent: ${out.spent_units / 1_000_000:.2f} cash (pack credits only)")
    else:  # dry-run demo: spends $0, calls nothing
        demo = InspectorConfig(endpoints=[{
            "url": "https://token-verdict-production.up.railway.app/v1/verdict",
            "watch_id": "token-verdict-main", "pack_id": "pack_demo"}])
        out = run_pass(demo, None)
        for line in out.lines:
            print(line)
        print("spent: $0.00 (dry-run)")
