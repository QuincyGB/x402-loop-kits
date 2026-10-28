"""Playbooks v1 (self-heal.md §4) and the escalation builder (§5).

Exactly one playbook spends money: catalogue-reseed. Everything
else escalates. The spend itself runs through an injected Settler
— this module ships only a dry-run settler, so the reference
receiver can be exercised end-to-end with no wallet at all.
"""

import hashlib

LAPSE_CODE = "listing_lapsed"
RESEED_PLAYBOOK = "catalogue-reseed"

FACILITATOR_URLS = {
    "cdp": "https://api.cdp.coinbase.com/platform/v2/x402",
    "payai": "https://facilitator.payai.network",
}


class SettleRefused(Exception):
    """A settler declining to settle. `etype` names the escalation
    type the refusal should be logged under."""

    def __init__(self, reason: str, etype: str = "policy_refusal"):
        super().__init__(reason)
        self.reason = reason
        self.etype = etype


class DryRunSettler:
    """Simulates a settlement: returns a receipt marked dry-run,
    spends nothing, touches nothing. The fixture settler."""

    def settle(self, stall: str, route: str, rail: str, price_usd: float) -> dict:
        digest = hashlib.sha256(f"{route}|{rail}".encode()).hexdigest()[:24]
        return {
            "rail": rail,
            "tx": f"dryrun-{digest}",
            "cost_usd": price_usd,
            "dry_run": True,
        }


def flip_steps(stall: str, route: str, rail: str) -> list[str]:
    """The exact human steps for a cross-rail re-seed — the
    operator-run flip dance the reference fleet already uses. The
    receiver never performs these itself: a facilitator flip is an
    environment change, a power this contract does not grant."""
    target = FACILITATOR_URLS.get(rail, f"the {rail} facilitator")
    return [
        f"On the service behind {stall}: set X402_FACILITATOR_URL to {target} "
        "and redeploy; verify the deploy is ACTIVE and /health answers.",
        f"Make ONE genuine paid call to {route} at its declared price — it "
        f"settles through {rail}, and that settlement re-admits the listing.",
        f"Verify the {rail} listing read flips to listed for the canonical "
        "resource URL (the https form the discovery doc declares).",
        "Flip X402_FACILITATOR_URL back to the service's normal facilitator "
        "and verify the redeploy.",
    ]


def build_escalation(
    etype: str,
    *,
    stall: str,
    route,
    defect: dict,
    evidence: list,
    view: dict,
    at: str,
    human_steps=None,
) -> dict:
    """The §5 escalation record: everything a human (or a future
    playbook) needs, and nothing they don't."""
    return {
        "type": etype,
        "stall": stall,
        "route": route,
        "defect": defect,
        "verified_evidence": evidence,
        "severity": (view or {}).get("severity"),
        "impact": (view or {}).get("impact"),
        "suggested_action": (view or {}).get("action"),
        "human_steps": human_steps or [],
        "at": at,
    }
