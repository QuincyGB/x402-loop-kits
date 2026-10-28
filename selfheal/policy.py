"""The owner policy — the only authority a receiver spends under
(self-heal.md §2). A small JSON file the owner edits; the shipped
example sets every cap to 0, which makes any receiver report-only.
"""

import json
from pathlib import Path

BASE_NETWORK = "eip155:8453"  # both catalogue rails (cdp, payai) settle Base USDC
USDC_DECIMALS = 6

DEFAULT_LAG_WINDOWS_HOURS = {"cdp": 168, "payai": 24}
DEFAULT_MIN_CHECK_GAP_HOURS = 1


class Policy:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.allowed_classes = list(data.get("allowed_classes") or [])
        self.per_fix_cap_usd = float(data.get("per_fix_cap_usd") or 0)
        self.monthly_cap_usd = float(data.get("monthly_cap_usd") or 0)
        self.wallet = str(data.get("wallet") or "")
        self.service_rails = {
            str(k).rstrip("/"): str(v)
            for k, v in (data.get("service_rails") or {}).items()
        }
        self.lag_windows_hours = {
            **DEFAULT_LAG_WINDOWS_HOURS,
            **{k: float(v) for k, v in (data.get("lag_windows_hours") or {}).items()},
        }
        self.listing_min_check_gap_hours = float(
            data.get("listing_min_check_gap_hours", DEFAULT_MIN_CHECK_GAP_HOURS)
        )

    @classmethod
    def from_file(cls, path) -> "Policy":
        return cls(json.loads(Path(path).read_text()))

    @property
    def report_only(self) -> bool:
        return self.per_fix_cap_usd <= 0 or self.monthly_cap_usd <= 0

    def allows(self, defect_code: str) -> bool:
        return defect_code in self.allowed_classes

    def lag_window_hours(self, rail: str) -> float:
        return self.lag_windows_hours.get(rail, 24.0)

    def current_rail(self, stall: str):
        return self.service_rails.get(stall.rstrip("/"))


def declared_price_usd(declared_entry, network: str = BASE_NETWORK):
    """The route's real price in USD from its declared accepts
    (USDC, 6 decimals). None if the entry declares no amount on
    that network — a fix whose price cannot be known cannot be
    cap-checked, and an uncheckable fix is never bought."""
    if not declared_entry:
        return None
    accepts = [a for a in (declared_entry.get("accepts") or []) if isinstance(a, dict)]
    if not accepts:
        return None
    accept = next(
        (a for a in accepts if a.get("network") == network), accepts[0]
    )
    amount = accept.get("amount")
    if amount is None:
        return None
    try:
        return int(str(amount)) / (10 ** USDC_DECIMALS)
    except (TypeError, ValueError):
        return None
