"""Shared rails for the Verdict Row loop kits — copied from verdict-loop.

Honesty header (same discipline as verdict-loop, the public reference
buyer): these kits are TEMPLATES. Dry-run is the default and cannot pay:
it reports the price it *would* pay and never invents a verdict. Live
mode for PAID legs is not implemented in the templates — wire
`PaidClient` to x402-guard's GuardedClient (or verdict_loop.x402) in
your own fork, behind your own --live flag + signer. The one live
path that ships is the inspector kit's pack mode (live_clients.py):
a recheck pack id is a prepaid credential, so spending a credit
needs no signer and settles nothing. The kits ship with an injectable
client so the decision logic is testable offline for $0.

Cap discipline (verdict-loop's rule, kept verbatim in spirit): a daily
spend cap authorizes every payment BEFORE anything is signed; a payment
that would break the cap is BLOCKED, never signed. Pack credits are not
money, but pack *spends* are counted, and a pack mint is a payment like
any other — it goes through the cap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

USDC = 1_000_000  # base units per $1


class SpendCapExceeded(Exception):
    """Raised before signing when a payment would break the daily cap."""


class DailyCap:
    """File-backed daily cap (UTC), authorize-before-sign. Mirrors
    verdict_loop.budget.DailySpendCap's contract in miniature."""

    def __init__(self, cap_units: int, state_path: str | Path | None = None,
                 *, now: datetime | None = None):
        if cap_units <= 0:
            raise ValueError("daily cap must be positive")
        self.cap_units = cap_units
        self.state_path = Path(state_path) if state_path else None
        self._now = now
        self._date, self._spent = self._load()

    def _today(self) -> str:
        return (self._now or datetime.now(timezone.utc)).date().isoformat()

    def _load(self) -> tuple[str, int]:
        today = self._today()
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = None
            if isinstance(data, dict) and data.get("date") == today:
                return today, int(data.get("spent_units", 0))
        return today, 0

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(
            {"date": self._date, "cap_units": self.cap_units,
             "spent_units": self._spent}, indent=2), encoding="utf-8")

    @property
    def spent_units(self) -> int:
        return self._spent

    @property
    def remaining_units(self) -> int:
        return max(0, self.cap_units - self._spent)

    def authorize(self, units: int) -> None:
        """Checked BEFORE any payment is signed. Raises, never truncates."""
        if units < 0:
            raise ValueError("payment units must be >= 0")
        if self._spent + units > self.cap_units:
            raise SpendCapExceeded(
                f"${units / USDC:.3f} would push today's spend "
                f"${self._spent / USDC:.3f} over the "
                f"${self.cap_units / USDC:.3f} cap — BLOCKED, not signed")
        self._spent += units
        self._save()


@dataclass
class PlannedCall:
    label: str
    price_units: int
    note: str = ""


@dataclass
class PassResult:
    mode: str  # "DRY-RUN" | "STUB" (tests) — templates never go live
    planned: list[PlannedCall] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    spent_units: int = 0

    @property
    def planned_units(self) -> int:
        return sum(c.price_units for c in self.planned)


# Pack low-balance policy (see ../2-pack-default/COPY-DRAFTS.md §L):
# warn at <=25 credits (10%) and <=10, warn at <=7 days to expiry,
# stop at 0. Never auto-buy, never fall back to per-call billing.
PACK_WARN_CREDITS = 25
PACK_WARN_CREDITS_LOW = 10
PACK_WARN_EXPIRY_DAYS = 7


def pack_warnings(balance: dict, *, today: datetime | None = None) -> list[str]:
    """Pure function over a /v1/recheck/pack-balance response shape:
    {credits_remaining, credits_total, expires_at (ISO), expired}."""
    out: list[str] = []
    remaining = int(balance.get("credits_remaining", 0))
    total = int(balance.get("credits_total", 250))
    if balance.get("expired"):
        out.append("PACK EXPIRED — recheck spends will return 410. "
                   "Renewal is a new $1.00 pack purchase; this loop will "
                   "not buy one and will not fall back to per-call billing.")
        return out
    if remaining == 0:
        out.append("PACK EXHAUSTED — spends return 402. This loop stops; "
                   "it does not fall back to per-call billing.")
        return out
    if remaining <= PACK_WARN_CREDITS_LOW:
        out.append(f"PACK LOW: {remaining} of {total} credits left — "
                   "renew soon (new pack via POST /v1/recheck/pack, $1.00).")
    elif remaining <= PACK_WARN_CREDITS:
        out.append(f"Pack low: {remaining} of {total} credits left "
                   "(balance reads are free).")
    expires = balance.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            now = today or datetime.now(timezone.utc)
            days = (exp - now).days
            if 0 <= days <= PACK_WARN_EXPIRY_DAYS:
                out.append(f"Pack expires in {days} day(s) ({expires}); "
                           "credits do not roll over — renewal is a new pack.")
        except ValueError:
            pass
    return out


def pack_usable(balance: dict) -> bool:
    return not balance.get("expired") and int(balance.get("credits_remaining", 0)) > 0
