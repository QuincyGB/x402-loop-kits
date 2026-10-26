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


class PackRecheckClient:
    def __init__(self, recheck_url: str = RECHECK_URL, http=None):
        if http is None:
            import httpx

            http = httpx.Client(timeout=30.0)
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
