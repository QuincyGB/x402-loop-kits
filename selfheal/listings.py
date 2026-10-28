"""Catalogue listing reads — the receiver's own eyes on whether a
route's listing exists. Tri-state, always:

  "listed"  — the catalogue affirmatively carries the route
  "absent"  — the catalogue affirmatively does not (a clean 404 /
              listed:false / missing from the merchant read)
  "unknown" — the lookup itself failed. Unknown is NOT evidence:
              it never counts toward the lapse bar (self-heal.md
              §3) and never resets it either.

The two reads are the fleet's documented ones (the same lookups
RouteVerdict's /v1/check performs):

  PayAI — GET https://facilitator.payai.network/discovery/
          listing-status?resource=<canonical https resource URL>
          200 listed:true -> listed; 200 listed:false or 404 ->
          absent; anything else -> unknown.
  CDP   — GET https://api.cdp.coinbase.com/platform/v2/x402/
          discovery/merchant?payTo=<payTo>; the route is listed
          iff its canonical resource URL appears in resources[].
          (The /discovery/resources and /search filters are
          known-broken; the merchant read is the reliable one.)

Canonical means the exact resource string the stall's own
discovery doc declares. The http:// form of a resource is a stale
trap row on PayAI — never query it.
"""

import json
from urllib.parse import quote

PAYAI_LISTING_STATUS = "https://facilitator.payai.network/discovery/listing-status"
CDP_MERCHANT = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant"

LISTED = "listed"
ABSENT = "absent"
UNKNOWN = "unknown"


class ListingChecker:
    def __init__(self, http):
        self.http = http
        self._cdp_cache: dict[str, object] = {}  # payTo(lower) -> resources list | None

    def payai_status(self, resource: str) -> str:
        url = PAYAI_LISTING_STATUS + "?resource=" + quote(resource, safe="")
        status, _h, body, err = self.http("GET", url, attempts=2)
        if err or status is None:
            return UNKNOWN
        if status == 404:
            return ABSENT
        if status != 200:
            return UNKNOWN
        try:
            doc = json.loads(body)
        except Exception:  # noqa: BLE001
            return UNKNOWN
        if isinstance(doc, dict) and "listed" in doc:
            return LISTED if doc["listed"] else ABSENT
        return UNKNOWN

    def _cdp_resources(self, pay_to: str):
        key = pay_to.lower()
        if key in self._cdp_cache:
            return self._cdp_cache[key]
        url = CDP_MERCHANT + "?payTo=" + quote(pay_to, safe="")
        status, _h, body, err = self.http("GET", url, attempts=2)
        resources = None
        if not err and status == 200:
            try:
                doc = json.loads(body)
                if isinstance(doc, dict) and isinstance(doc.get("resources"), list):
                    resources = doc["resources"]
            except Exception:  # noqa: BLE001
                resources = None
        self._cdp_cache[key] = resources
        return resources

    def cdp_status(self, resource: str, pay_to: str) -> str:
        if not pay_to:
            return UNKNOWN
        resources = self._cdp_resources(pay_to)
        if resources is None:
            return UNKNOWN
        for entry in resources:
            if isinstance(entry, dict) and (entry.get("resource") or entry.get("url")) == resource:
                return LISTED
        return ABSENT

    def status(self, rail: str, resource: str, pay_to: str = "") -> str:
        """Dispatch on the rail the lapse is claimed on."""
        if rail == "payai":
            return self.payai_status(resource)
        if rail == "cdp":
            return self.cdp_status(resource, pay_to)
        return UNKNOWN
