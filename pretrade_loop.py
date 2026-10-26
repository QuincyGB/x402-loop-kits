"""PRE-TRADE LOOP kit — gate every intended trade behind one verdict.

Pattern: before a trading/treasury agent spends from a wallet on a token,
it buys ONE combined check instead of three:
  POST /v1/pre-trade ($0.05, Token Verdict service) — token leg +
  wallet leg (sanctions/age/poisoning) + optional allowance leg, combined
  as PROCEED / CAUTION / ABORT with the worst leg driving the result.
  An unevaluable leg caps the combined verdict at CAUTION; a hard ABORT
  (token DANGER / wallet AVOID / sanctions match) is final.

Policy (config-tunable, defaults are the strict ones):
  PROCEED -> the trade may go ahead (this kit never executes trades).
  CAUTION -> SKIP the trade this pass (re-check next pass).
  ABORT   -> SKIP and raise an alert; do not retry-loop an ABORT.

DRY-RUN IS THE DEFAULT AND CANNOT PAY. Live mode is deliberately not
implemented: inject a client backed by x402-guard in your fork. The cap
is authorized BEFORE any (stub) payment is recorded. The per-trade
planned spend is printed before the pass starts, so a misconfigured
trade list can never silently overspend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from loopkit_common import DailyCap, PassResult, PlannedCall, SpendCapExceeded

PRETRADE_URL = "https://token-verdict-production.up.railway.app/v1/pre-trade"
PRETRADE_PRICE_UNITS = 50_000  # $0.05


class PreTradeClient(Protocol):
    def pre_trade(self, token_address: str, wallet_address: str | None,
                  spender: str | None) -> dict: ...


@dataclass
class TradeIntent:
    token_address: str
    wallet_address: str | None = None
    spender: str | None = None
    label: str = ""


@dataclass
class PreTradeConfig:
    trades: list[TradeIntent] = field(default_factory=list)
    daily_cap_units: int = 500_000  # $0.50 default: 10 gated trades/day
    budget_state: str = "pretrade-budget.json"
    allow_caution: bool = False     # default: CAUTION skips the trade


def decide_pretrade(payload: dict, *, allow_caution: bool = False) -> tuple[str, str]:
    """Map a /v1/pre-trade response to (action, reason).
    Actions: PROCEED | SKIP | ABORT. Malformed payloads raise — a gate
    must fail loud, never invent a verdict (verdict-loop's rule)."""
    if "verdict" not in payload:
        raise ValueError("pre-trade payload is missing 'verdict'")
    verdict = str(payload["verdict"])
    if verdict not in ("PROCEED", "CAUTION", "ABORT"):
        raise ValueError(f"unknown pre-trade verdict: {verdict!r}")
    worst = payload.get("worst_leg") or payload.get("worst leg") or "combined"
    if verdict == "ABORT":
        return "ABORT", f"hard abort (worst leg: {worst}) — do not trade, do not retry-loop"
    if verdict == "CAUTION":
        if payload.get("unknown_legs"):
            reason = f"a leg could not be evaluated (worst leg: {worst}); verdict capped at CAUTION"
        else:
            reason = f"caution (worst leg: {worst})"
        return ("PROCEED" if allow_caution else "SKIP"), reason
    return "PROCEED", "all evaluated legs passed"


def run_pass(cfg: PreTradeConfig, client: PreTradeClient | None,
             *, dry_run: bool = True) -> PassResult:
    result = PassResult(mode="DRY-RUN" if dry_run else "STUB")
    for t in cfg.trades:
        result.planned.append(PlannedCall(
            f"pre-trade {t.label or t.token_address}", PRETRADE_PRICE_UNITS))

    if dry_run or client is None:
        for c in result.planned:
            result.lines.append(f"DRY-RUN would pay $0.050 — {c.label}")
        result.lines.append(
            f"planned total: ${result.planned_units / 1_000_000:.3f} against a "
            f"${cfg.daily_cap_units / 1_000_000:.3f} daily cap. Policy: ABORT "
            "blocks, CAUTION skips (unless allow_caution), no verdict invented.")
        return result

    cap = DailyCap(cfg.daily_cap_units, cfg.budget_state)
    for t in cfg.trades:
        try:
            cap.authorize(PRETRADE_PRICE_UNITS)  # BEFORE signing, always
        except SpendCapExceeded as e:
            result.alerts.append(f"CAP STOP: {e}")
            break
        result.spent_units += PRETRADE_PRICE_UNITS
        payload = client.pre_trade(t.token_address, t.wallet_address, t.spender)
        action, reason = decide_pretrade(payload, allow_caution=cfg.allow_caution)
        line = f"{action}: {t.label or t.token_address} — {reason}"
        if action == "ABORT":
            result.alerts.append(line)
        else:
            result.lines.append(line)
    return result


if __name__ == "__main__":  # dry-run demo: spends $0, calls nothing
    demo = PreTradeConfig(trades=[TradeIntent(
        token_address="0x4200000000000000000000000000000000000006",
        wallet_address=None, label="WETH buy (token leg only)")])
    out = run_pass(demo, None)
    for line in out.lines:
        print(line)
    print("spent: $0.00 (dry-run)")
