#!/usr/bin/env python3
"""Verdict Row Verified — dogfood battery (CRITERIA.md criterion 1).

For each fleet service: health 200, manifest reachable, and for every
paid route in the manifest an unpaid POST whose 402 accepts must
EXACTLY match the manifest entry (amount, asset, network, payTo).
Read-only: unpaid probes only, nothing settles.

Usage: run_battery.py [out.json]
"""

import base64
import json
import sys
import urllib.request
from urllib.parse import urlparse

SERVICES = {
    "Token Verdict": "https://token-verdict-production.up.railway.app",
    "RouteVerdict": "https://route-verdict-production.up.railway.app",
    "ListSmith": "https://list-smith-production.up.railway.app",
    "StallRow": "https://stall-row-production.up.railway.app",
    "LockSmith": "https://lock-smith-production.up.railway.app",
}

# Minimal plausible bodies so app-level validation order can never be
# the reason a probe fails to reach the paywall.
BODIES = {
    "/v1/verdict": {"address": "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "chain": "base"},
    "/v1/batch-verdict": {"addresses": ["0x940181a94A35A4569E4529A3CDfB74e38FD98631"]},
    "/v1/pre-trade": {"address": "0x940181a94A35A4569E4529A3CDfB74e38FD98631"},
    "/v1/check": {"resource_url": "https://www.x402.org/"},
    "/v1/grade": {"resource_url": "https://www.x402.org/"},
    "/v1/fix": {"resource_url": "https://www.x402.org/"},
    "/v1/audit": {"endpoint_url": "https://www.x402.org/"},
}


def fetch(url, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def accepts_of_manifest(entry):
    accs = entry.get("accepts") or []
    return accs[0] if accs else {}


def main():
    report = {}
    all_pass = True
    for name, base in SERVICES.items():
        svc = {"base": base}
        status, _, raw = fetch(base + "/health")
        svc["health_status"] = status
        status_m, _, raw_m = fetch(base + "/.well-known/x402")
        svc["manifest_status"] = status_m
        routes = []
        if status_m == 200:
            manifest = json.loads(raw_m)
            for entry in manifest.get("resources", []):
                if entry.get("method") != "POST":
                    continue
                rurl = entry["resource"]
                path = urlparse(rurl).path
                want = accepts_of_manifest(entry)
                st, headers, _ = fetch(rurl, method="POST", body=BODIES.get(path, {}))
                got = {}
                hdr = headers.get("payment-required") or headers.get("Payment-Required")
                if st == 402 and hdr:
                    chal = json.loads(base64.b64decode(hdr))
                    accs = chal.get("accepts") or []
                    got = accs[0] if accs else {}
                match = all(
                    str(got.get(k)) == str(want.get(k))
                    for k in ("amount", "asset", "network", "payTo")
                ) and st == 402
                routes.append(
                    {"path": path, "probe_status": st, "exact_match": bool(match),
                     "amount": want.get("amount")}
                )
                all_pass = all_pass and match
        svc["routes"] = routes
        svc["criterion1_pass"] = (
            svc["health_status"] == 200
            and svc["manifest_status"] == 200
            and bool(routes)
            and all(r["exact_match"] for r in routes)
        )
        report[name] = svc
        print(f"{name}: health={svc['health_status']} manifest={svc['manifest_status']} "
              f"routes={len(routes)} criterion1={'PASS' if svc['criterion1_pass'] else 'FAIL'}")
        for r in routes:
            if not r["exact_match"]:
                print(f"  MISMATCH {r['path']}: probe={r['probe_status']}")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            json.dump(report, f, indent=2)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
