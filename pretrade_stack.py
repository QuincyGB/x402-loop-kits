"""Pre-Trade Stack kit: the fleet's four before-you-pay checks as
ONE drop-in pass.

The checks already exist as separate StallRow routes; a router or
agent loop does not want to wire four paid calls with four failure
modes before every payment. This kit runs them as one stack and
folds them into a single PROCEED / CAUTION / ABORT decision:

  1. Bad-payTo feed      POST /v1/flagged-paytos        $0.005
     Is this payTo on the flagged registry (OFAC SDN snapshot,
     rotated-away, tied to vanished listings)?
  2. Pre-Trade Guard     POST /v1/pre-trade-guard       $0.005
     The combined screen: Index history, sanctions, wallet age —
     verdict + risk score. (x402-guard's guarded client mode runs
     this same guard as its pre-flight stage before signing; this
     kit is for loops that call the routes directly.)
  3. Counterparty Report POST /v1/counterparty-report   $1.00
     OPTIONAL leg (priced like a report, not a probe): the full
     seller file — wallet, sanctions, Index history, plus Token
     Verdict / LockSmith / ListSmith legs when you name a token,
     service URL, or listing URL. Included only when requested.
  4. Receipt Verifier    POST /v1/receipt-verify        $0.002
     OPTIONAL leg, for "they say they already paid / were paid":
     a claimed past settlement checked against the chain.

Decision rules (conservative, stated in the output):
  - Flagged feed hit on the payTo            -> ABORT
  - Sanctions matched in ANY leg             -> ABORT
  - Guard verdict ABORT                      -> ABORT
  - Guard verdict CAUTION                    -> at least CAUTION
  - A requested receipt that is not settled  -> at least CAUTION
  - A leg that FAILS to run                  -> at least CAUTION
    (never a silent PROCEED on missing evidence), and the failure
    is named in the output.

Stack cost: $0.010 for the two probe legs, +$1.00 with the
counterparty leg, +$0.002 with a receipt check. Every leg can be
paid per call or from a Fleet Pass (see live_clients.FleetPassClient)
— the kit only defines the client protocol; how the calls are paid
is the caller's x402-guard / pass wiring, exactly as in the other
kits. Dry-run default in the demo below: $0, mock client.
"""

from __future__ import annotations

from typing import Protocol


class PreTradeStackClient(Protocol):
    """The four stack legs. Implement over x402-guard's GuardedClient
    or live_clients.FleetPassClient in your fork."""

    def flagged_paytos(self) -> dict: ...
    def pre_trade_guard(self, pay_to: str, amount=None, resource=None) -> dict: ...
    def counterparty_report(self, pay_to: str, **kw) -> dict: ...
    def receipt_verify(self, tx_hash: str) -> dict: ...


def _sanctions_matched(obj) -> bool:
    """True when any nested sanctions record reports a match. Legs
    report sanctions in slightly different envelopes; the match
    status string is the same fleet-wide ('matched')."""
    if isinstance(obj, dict):
        if obj.get("status") == "matched" and "matched" in obj:
            return True
        return any(_sanctions_matched(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_sanctions_matched(v) for v in obj)
    return False


_RANK = {"PROCEED": 0, "CAUTION": 1, "ABORT": 2}


def _raise(current: str, floor: str) -> str:
    return floor if _RANK[floor] > _RANK[current] else current


def run_stack(
    client: PreTradeStackClient,
    *,
    pay_to: str,
    amount=None,
    resource: str | None = None,
    tx_hash: str | None = None,
    counterparty: bool = False,
    counterparty_kw: dict | None = None,
) -> dict:
    """One pre-trade pass over one payTo. Returns the folded
    decision plus every leg's raw output (evidence is never
    summarized away)."""
    decision = "PROCEED"
    reasons: list[str] = []
    legs: dict[str, dict] = {}

    def leg(name, fn):
        try:
            out = fn()
            legs[name] = out
            return out
        except Exception as e:  # noqa: BLE001 — a failed leg is evidence too
            legs[name] = {"status": "failed", "error": f"{type(e).__name__}: {e}"[:200]}
            return None

    feed = leg("flagged_paytos", client.flagged_paytos)
    if feed is not None:
        hit = next(
            (e for e in feed.get("entries", []) if (e.get("pay_to") or "").lower() == pay_to.lower()),
            None,
        )
        if hit is not None:
            decision = _raise(decision, "ABORT")
            reasons.append(f"payTo is on the flagged feed: {hit.get('reasons')}")
    else:
        decision = _raise(decision, "CAUTION")
        reasons.append("flagged-paytos leg failed — flagged status unknown")

    guard = leg("pre_trade_guard", lambda: client.pre_trade_guard(pay_to, amount, resource))
    if guard is not None:
        verdict = guard.get("verdict")
        if verdict in _RANK:
            decision = _raise(decision, verdict)
            if verdict != "PROCEED":
                reasons.append(f"pre-trade guard: {verdict} (risk {guard.get('risk_score')})")
        else:
            decision = _raise(decision, "CAUTION")
            reasons.append("pre-trade guard returned no verdict")
    else:
        decision = _raise(decision, "CAUTION")
        reasons.append("pre-trade guard leg failed — verdict unknown")

    if counterparty:
        report = leg(
            "counterparty_report",
            lambda: client.counterparty_report(pay_to, **(counterparty_kw or {})),
        )
        if report is None:
            decision = _raise(decision, "CAUTION")
            reasons.append("counterparty leg failed — seller file unknown")

    if tx_hash:
        receipt = leg("receipt_verify", lambda: client.receipt_verify(tx_hash))
        if receipt is not None:
            if receipt.get("settled") is not True:
                decision = _raise(decision, "CAUTION")
                reasons.append("claimed receipt is not settled on-chain")
        else:
            decision = _raise(decision, "CAUTION")
            reasons.append("receipt leg failed — claimed payment unverified")

    if _sanctions_matched(legs):
        decision = "ABORT"
        reasons.append("sanctions match found in a stack leg")

    return {
        "pay_to": pay_to,
        "decision": decision,
        "reasons": reasons,
        "legs_run": sorted(legs),
        "legs": legs,
        "stack_cost_usd": round(
            0.005 + 0.005 + (1.00 if counterparty else 0.0) + (0.002 if tx_hash else 0.0), 3
        ),
        "limits": (
            "Flags and verdicts are evidence for the caller's own "
            "decision, not a guarantee about a counterparty."
        ),
    }


class StallRowStackClient:
    """The stack legs over any object with .call(path, payload)
    (live_clients.FleetPassClient) or a compatible callable seam.
    Kept thin on purpose: payment mechanics live in the transport."""

    def __init__(self, call):
        self._call = call

    def flagged_paytos(self) -> dict:
        return self._call("/v1/flagged-paytos", {})

    def pre_trade_guard(self, pay_to: str, amount=None, resource=None) -> dict:
        body = {"pay_to": pay_to}
        if amount is not None:
            body["amount"] = amount
        if resource is not None:
            body["resource"] = resource
        return self._call("/v1/pre-trade-guard", body)

    def counterparty_report(self, pay_to: str, **kw) -> dict:
        return self._call("/v1/counterparty-report", {"pay_to": pay_to, **kw})

    def receipt_verify(self, tx_hash: str) -> dict:
        return self._call("/v1/receipt-verify", {"tx_hash": tx_hash})


# --- dry-run demo ($0, mock client) --------------------------------------------


class _MockClient:
    def flagged_paytos(self):
        return {"entries": [{"pay_to": "0xdead", "reasons": ["ofac_sdn"]}]}

    def pre_trade_guard(self, pay_to, amount=None, resource=None):
        return {"verdict": "PROCEED", "risk_score": 4, "sanctions": {"status": "no_match", "matched": False}}

    def counterparty_report(self, pay_to, **kw):
        return {"pay_to": pay_to, "legs": {}}

    def receipt_verify(self, tx_hash):
        return {"settled": True, "confirmations": 42}


if __name__ == "__main__":
    import json

    out = run_stack(_MockClient(), pay_to="0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F",
                    tx_hash="0x" + "0" * 64, counterparty=True)
    print(json.dumps({k: out[k] for k in ("pay_to", "decision", "reasons", "stack_cost_usd")}, indent=2))
    print("dry-run demo — mock client, $0 spent")
