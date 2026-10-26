"""MONITOR LOOP kit — screen a token feed + watch the endpoints you rely on.

Pattern: the loop a screener/monitoring agent runs on a schedule.
  1. POST /v1/batch-verdict ($0.20 flat, up to 25 Base tokens) per chunk —
     one settlement instead of 25 singles ($0.50). Output is riskiest-first
     with SOLID / CAUTION / DANGER / UNKNOWN per token; UNKNOWN is a real
     answer (data unfetchable), never a guess.
  2. POST /v1/recheck per watched endpoint, spending RECHECK PACK credits
     (pack bought once: POST /v1/recheck/pack, $1.00 = 250 checks on ONE
     endpoint, 90 days). Alert only on a FLIP: a token whose verdict label
     changed since the last pass, or a recheck status of CHANGED.
  3. Pack balance is read FREE (POST /v1/recheck/pack-balance) before the
     pass; low-balance warnings follow ../2-pack-default §L. At 0 credits
     the recheck leg stops — no per-call fallback, no auto-renewal.

DRY-RUN IS THE DEFAULT AND CANNOT PAY. Live mode is deliberately not
implemented here: inject a client backed by x402-guard in your fork.
Prices below are server-side constants verified 2026-10-26; the cap is
authorized BEFORE any (stub) payment is recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loopkit_common import (DailyCap, PassResult, PlannedCall,
                            SpendCapExceeded, pack_usable, pack_warnings)

BATCH_VERDICT_URL = "https://token-verdict-production.up.railway.app/v1/batch-verdict"
RECHECK_URL = "https://stall-row-production.up.railway.app/v1/recheck"
RECHECK_PACK_URL = "https://stall-row-production.up.railway.app/v1/recheck/pack"
BATCH_PRICE_UNITS = 200_000        # $0.20 flat, up to 25 tokens
PACK_PRICE_UNITS = 1_000_000       # $1.00, only when minting (manual step)
BATCH_CHUNK = 25


class MonitorClient(Protocol):
    """Implement over x402-guard. Methods return the services' published
    output shapes; `recheck` spends a pack credit server-side."""

    def batch_verdict(self, addresses: list[str]) -> dict: ...
    def recheck(self, url: str, watch_id: str, pack_id: str) -> dict: ...
    def pack_balance(self, pack_id: str) -> dict: ...


@dataclass
class MonitorConfig:
    tokens: list[str] = field(default_factory=list)          # Base addresses
    watched_endpoints: list[dict] = field(default_factory=list)  # {url, watch_id, pack_id}
    daily_cap_units: int = 1_000_000   # $1.00 default: 5 batch screens/day
    state_path: str = "monitor-state.json"   # last verdict label per token
    budget_state: str = "monitor-budget.json"


def _load_state(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (ValueError, OSError):
            pass
    return {}


def run_pass(cfg: MonitorConfig, client: MonitorClient | None,
             *, dry_run: bool = True) -> PassResult:
    """One pass. With dry_run=True or client=None nothing is called and
    nothing is spent: the result only plans the calls and their prices."""
    result = PassResult(mode="DRY-RUN" if dry_run else "STUB")
    chunks = [cfg.tokens[i:i + BATCH_CHUNK]
              for i in range(0, len(cfg.tokens), BATCH_CHUNK)] or []
    for chunk in chunks:
        result.planned.append(PlannedCall(
            f"batch-verdict x{len(chunk)} tokens", BATCH_PRICE_UNITS))
    for ep in cfg.watched_endpoints:
        result.planned.append(PlannedCall(
            f"recheck {ep.get('watch_id', ep.get('url'))} (pack credit)",
            0, "spends 1 pack credit ($0.004 effective), no settlement"))

    if dry_run or client is None:
        for c in result.planned:
            result.lines.append(
                f"DRY-RUN would pay ${c.price_units / 1_000_000:.3f} — {c.label}"
                if c.price_units else f"DRY-RUN would spend a pack credit — {c.label}")
        result.lines.append(
            "policy: ALERT only on a verdict flip vs the last pass, or a "
            "recheck status of CHANGED. No verdict is invented in dry-run.")
        return result

    cap = DailyCap(cfg.daily_cap_units, cfg.budget_state)
    state_path = Path(cfg.state_path)
    state = _load_state(state_path)
    labels: dict[str, str] = state.get("token_labels", {})

    # Recheck leg first: free balance reads gate the pack spends.
    usable_packs: dict[str, bool] = {}
    for ep in cfg.watched_endpoints:
        pack_id = ep.get("pack_id")
        if not pack_id:
            result.lines.append(f"recheck {ep.get('watch_id')}: no pack_id "
                                "configured — skipped (per-call mode is not "
                                "this kit's default).")
            usable_packs[ep.get("watch_id", "")] = False
            continue
        balance = client.pack_balance(pack_id)  # free, spends nothing
        for w in pack_warnings(balance):
            result.alerts.append(w)
        usable_packs[ep.get("watch_id", "")] = pack_usable(balance)

    for chunk in chunks:
        try:
            cap.authorize(BATCH_PRICE_UNITS)  # BEFORE signing, always
        except SpendCapExceeded as e:
            result.alerts.append(f"CAP STOP: {e}")
            break
        result.spent_units += BATCH_PRICE_UNITS
        payload = client.batch_verdict(chunk)
        for entry in payload.get("results", []):
            addr = str(entry.get("address", "")).lower()
            label = str(entry.get("verdict", "UNKNOWN"))
            prev = labels.get(addr)
            if prev is not None and prev != label:
                result.alerts.append(
                    f"FLIP {addr}: {prev} -> {label} "
                    f"(score {entry.get('score')})")
            labels[addr] = label
        result.lines.append(
            f"batch-verdict: screened {len(chunk)} tokens; summary "
            f"{payload.get('summary', {})}")

    for ep in cfg.watched_endpoints:
        wid = ep.get("watch_id", "")
        if not usable_packs.get(wid):
            continue
        payload = client.recheck(ep["url"], wid, ep["pack_id"])
        status = str(payload.get("status", ""))
        if status == "CHANGED":
            fields = ", ".join(str(c.get("field")) for c in payload.get("changes", []))
            result.alerts.append(f"CHANGED {ep['url']}: {fields}")
        result.lines.append(f"recheck {wid}: {status}")

    state["token_labels"] = labels
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":  # dry-run demo: spends $0, calls nothing
    demo = MonitorConfig(
        tokens=["0x4200000000000000000000000000000000000006"] * 3,
        watched_endpoints=[{"url": BATCH_VERDICT_URL.replace("batch-verdict", "verdict"),
                            "watch_id": "token-verdict-main", "pack_id": "pack_demo"}],
    )
    out = run_pass(demo, None)
    for line in out.lines:
        print(line)
    print(f"planned: ${out.planned_units / 1_000_000:.3f} — spent: $0.00 (dry-run)")
