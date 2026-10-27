"""Live clients for the loop kits.

`PackRecheckClient` is the one live client that needs no signer and no
payment machinery: a StallRow recheck pack id IS the credential. A pack
spend is a plain POST carrying `pack_id` — StallRow's middleware lets
it through unpaid and the handler spends one credit server-side.

It satisfies the `recheck` / `pack_balance` half of both the inspector
and monitor kit protocols. The paid legs (batch-verdict, pre-trade) are
deliberately NOT implemented here: paying for those should go through
x402-guard's GuardedClient (pre-flight + caps before signing), exactly
as verdict-loop does. `batch_verdict` therefore raises rather than
paying raw.
"""

from __future__ import annotations

RECHECK_URL = "https://stall-row-production.up.railway.app/v1/recheck"
PACK_BALANCE_URL = "https://stall-row-production.up.railway.app/v1/recheck/pack-balance"


def _default_http():
    """Build the default httpx client.

    Works around a real httpx parsing bug: a `no_proxy` env var
    containing bracketed IPv6 entries (e.g. `[::1]`, common in
    container/proxy setups) crashes Client construction with
    `Invalid port: ':1]'`. Drop the bracketed duplicates (the bare
    `::1` form is normally present too) before constructing.
    """
    import os

    import httpx

    for key in ("no_proxy", "NO_PROXY"):
        raw = os.environ.get(key)
        if raw and "[" in raw:
            os.environ[key] = ",".join(
                p for p in raw.split(",")
                if not (p.startswith("[") and p.endswith("]"))
            )
    return httpx.Client(timeout=30.0)


class PackRecheckClient:
    def __init__(self, recheck_url: str = RECHECK_URL, http=None):
        if http is None:
            http = _default_http()
        self.http = http
        self.recheck_url = recheck_url
        self.balance_url = recheck_url.rstrip("/") + "/pack-balance"

    def recheck(self, url: str, watch_id: str, pack_id: str | None) -> dict:
        if not pack_id:
            raise ValueError(
                "PackRecheckClient spends pack credits only; per-call "
                "payment belongs in x402-guard, not here"
            )
        response = self.http.post(
            self.recheck_url,
            json={"url": url, "watch_id": watch_id, "pack_id": pack_id},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"pack recheck failed: HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("recheck response was not an object")
        return data

    def pack_balance(self, pack_id: str) -> dict:
        response = self.http.post(self.balance_url, json={"pack_id": pack_id})
        if response.status_code != 200:
            raise RuntimeError(
                f"pack balance read failed: HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        return response.json()

    def batch_verdict(self, addresses: list[str]) -> dict:
        raise NotImplementedError(
            "batch-verdict is a paid leg: implement it over x402-guard's "
            "GuardedClient in your fork (see verdict-loop for the pattern)"
        )


STALLROW_BASE = "https://stall-row-production.up.railway.app"


class FleetPassClient:
    """Live-mode client that spends a Fleet Pass instead of paying
    per call. The pass id IS the credential: every call carries it
    as the X-Fleet-Pass header and StallRow debits that route's
    listed price server-side before the handler runs (refunding the
    debit when the service fails). Works with both denominations —
    the $5 pass (POST /v1/fleet-pass) and the $20 working pass for
    frameworks (POST /v1/fleet-pass-20); the denomination lives in
    the server-side ledger, not in this client.

    There are NO holder discounts: a pass call costs exactly the
    route's listed price, same as a per-call payment. An exhausted
    pass answers 402 and an expired one 410 — this client surfaces
    those plainly and NEVER falls back to a per-call payment:
    falling back silently is how a loop overspends its budget."""

    def __init__(self, pass_id: str, base_url: str = STALLROW_BASE, http=None):
        if not pass_id:
            raise ValueError("FleetPassClient needs a pass_id")
        if http is None:
            http = _default_http()
        self.http = http
        self.pass_id = pass_id
        self.base_url = base_url.rstrip("/")

    def balance(self) -> dict:
        response = self.http.post(
            self.base_url + "/v1/fleet-pass/balance",
            json={"pass_id": self.pass_id},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"fleet pass balance read failed: HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        return response.json()

    def call(self, path: str, payload: dict | None = None) -> dict:
        """One pass-funded POST to a fleet route on StallRow (the
        pass also spends on sibling services, which run the same
        header contract against their own base URLs — construct one
        client per base URL with the same pass id)."""
        response = self.http.post(
            self.base_url + path,
            json=payload or {},
            headers={"X-Fleet-Pass": self.pass_id},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"fleet pass call to {path} failed: HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"{path} response was not an object")
        return data
