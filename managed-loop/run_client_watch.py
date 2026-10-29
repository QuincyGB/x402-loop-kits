#!/usr/bin/env python3
"""Managed Loop — per-client watch runner (fleet-side consumer).

Takes a client config written by enroll_client.py and probes each of
its routes unpaid, with the same semantics as the fleet's patrol /
Fleet Check classification (hidden_files/fleet-checker/check.py +
nudge.py probe_route, and StallRow POST /v1/probe):

  * expected response to an unpaid POST {} is HTTP 402 with a
    parseable x402 challenge carrying accepts;
  * where the route's origin publishes /.well-known/x402, the live
    challenge's amount and payTo are compared against the declared
    accepts for that resource (amount_mismatch / payto_mismatch);
  * defect classes: ok, unreachable, server_error, no_402,
    unexpected_status, challenge_undecodable, amount_mismatch,
    payto_mismatch — the nudge spec's table
    (https://quincygb.github.io/x402-loop-kits/nudge-inbox.html §5).
    critical = unreachable / server_error / no_402 /
    unexpected_status / challenge_undecodable; warning = the two
    mismatch classes; ok carries no severity.

The probe NEVER pays, signs, or settles anything. stdlib only.

Usage:
    python3 run_client_watch.py --config managed-loop/clients/<slug>.json
    python3 run_client_watch.py managed-loop/clients/<slug>.json

Prints a per-route verdict table to stdout and writes a last-run JSON
beside the config: <slug>.last-run.json.
Exit code: 0 = every route ok, 2 = at least one defect.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

TIMEOUT = 20
USER_AGENT = "managed-loop-watch/1.0"
CRITICAL = {"unreachable", "server_error", "no_402",
            "unexpected_status", "challenge_undecodable"}
CURL = shutil.which("curl")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _curl(method: str, url: str, body: bytes | None = None):
    """HTTP via the curl binary — check.py's transport pattern
    (stdlib-only Python; urllib POSTs are reset by some egress paths
    and time out to many hosts, curl is clean). Returns
    (status|None, headers dict, body bytes, err|None)."""
    cmd = ["curl", "-sS", "-i", "-m", str(TIMEOUT), "-X", method,
           "-A", USER_AGENT, url]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json",
                "--data-binary", "@-"]
    try:
        p = subprocess.run(cmd, input=body, capture_output=True,
                           timeout=TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return None, {}, b"", "curl timeout"
    raw = p.stdout or b""
    if p.returncode != 0 and not raw:
        err = p.stderr.decode("utf-8", "replace")[:160].strip()
        return None, {}, b"", f"curl exit {p.returncode}: {err}"
    # With -i, curl may print multiple header blocks (proxy CONNECT +
    # response); the response block is the LAST HTTP status block.
    text = raw.decode("utf-8", "replace")
    blocks = text.split("\r\n\r\n")
    status, hdrs, resp_body = None, {}, ""
    for j, block in enumerate(blocks):
        first = block.split("\r\n", 1)[0] if block else ""
        if first.startswith("HTTP/"):
            try:
                status = int(first.split()[1])
            except (IndexError, ValueError):
                status = None
            hdrs = {}
            for line in block.split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    hdrs[k.strip().lower()] = v.strip()
            resp_body = "\r\n\r\n".join(blocks[j + 1:])
    if status is None:
        return None, {}, b"", "no HTTP status in curl output"
    return status, hdrs, resp_body.encode(), None


def _urllib(method: str, url: str, body: bytes | None = None):
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"User-Agent": USER_AGENT,
                 **({"Content-Type": "application/json"}
                    if body is not None else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return (resp.status,
                    {k.lower(): v for k, v in resp.headers.items()},
                    resp.read(), None)
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        try:
            data = e.read()
        except Exception:
            data = b""
        return e.code, hdrs, data, None
    except Exception as e:  # transport failure: no HTTP response at all
        return None, {}, b"", f"{type(e).__name__}: {e}"


def http_post(url: str, body: bytes = b"{}"):
    """Unpaid POST. Returns (status|None, headers dict, body bytes, err|None)."""
    if CURL:
        return _curl("POST", url, body)
    return _urllib("POST", url, body)


def http_get_json(url: str):
    if CURL:
        status, _h, body, _e = _curl("GET", url)
        if status != 200:
            return None
    else:
        status, _h, body, _e = _urllib("GET", url)
        if status != 200:
            return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None


def decode_challenge(headers: dict, body: bytes):
    """(challenge dict|None, error|None) from the PAYMENT-REQUIRED
    header (base64 JSON) or a JSON body in the same shape."""
    raw = headers.get("payment-required")
    if raw:
        try:
            return json.loads(base64.b64decode(raw)), None
        except Exception as e:
            return None, f"payment-required header not decodable: {e}"
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
        if isinstance(doc, dict) and doc.get("accepts"):
            return doc, None
    except Exception:
        pass
    return None, "no decodable payment-required challenge"


def declared_accepts(discovery: dict | None, route_url: str):
    """The declared accepts for one resource from /.well-known/x402."""
    if not discovery:
        return None
    for res in discovery.get("resources", []) or []:
        if isinstance(res, dict) and res.get("resource") == route_url:
            accepts = res.get("accepts")
            if isinstance(accepts, list) and accepts:
                return accepts
    return None


def probe_route(url: str, declared: list | None):
    """One unpaid probe. Returns a verdict dict mirroring the patrol's
    probe_route: {route, http_status, verdict, defect, severity, detail}."""
    at = now_iso()
    status, hdrs, body, err = http_post(url)
    base = {"route": url, "checked_at": at, "http_status": status}

    def defect(code, expected, observed, detail):
        return {**base, "verdict": "DEFECT", "defect": code,
                "severity": "critical" if code in CRITICAL else "warning",
                "expected": expected, "observed": observed, "detail": detail}

    if status is None:
        return defect("unreachable", "an HTTP response", "none",
                      f"transport failure: {err}")
    if status >= 500:
        return defect("server_error", "402", str(status),
                      f"target returned HTTP {status}")
    if status == 200:
        return defect("no_402", "402", "200",
                      "answers HTTP 200 to an unpaid probe — no payment gate")
    if status != 402:
        return defect("unexpected_status", "402", str(status),
                      f"answers HTTP {status}, not a 402 challenge")
    challenge, derr = decode_challenge(hdrs, body)
    if challenge is None or not challenge.get("accepts"):
        return defect("challenge_undecodable",
                      "a parseable x402 challenge with accepts",
                      "undecodable", derr or "challenge carries no accepts")
    accepts = [a for a in challenge["accepts"] if isinstance(a, dict)]
    live = accepts[0] if accepts else {}
    detail = (f"live challenge: amount {live.get('amount')} to "
              f"{live.get('payTo')} on {live.get('network')}")
    if declared:
        decl = next((a for a in declared
                     if isinstance(a, dict)
                     and a.get("network") == live.get("network")),
                    declared[0] if isinstance(declared[0], dict) else {})
        if (decl.get("amount") is not None and live.get("amount") is not None
                and str(decl["amount"]) != str(live["amount"])):
            return defect("amount_mismatch", str(decl["amount"]),
                          str(live["amount"]),
                          f"live challenge amount {live['amount']} != declared {decl['amount']}")
        if (decl.get("payTo") and live.get("payTo")
                and str(decl["payTo"]).lower() != str(live["payTo"]).lower()):
            return defect("payto_mismatch", str(decl["payTo"]),
                          str(live["payTo"]),
                          f"live challenge payTo {live['payTo']} != declared {decl['payTo']}")
    return {**base, "verdict": "OK", "defect": None, "severity": None,
            "expected": "402", "observed": "402", "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", nargs="?", help="client config JSON path")
    ap.add_argument("--config", dest="config_flag",
                    help="client config JSON path (same as positional)")
    args = ap.parse_args()
    cfg_path = Path(args.config_flag or args.config or "")
    if not args.config_flag and not args.config:
        ap.error("a client config path is required")
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not config.get("enabled", True):
        print(f"client {config.get('client')}: enabled=false — watch skipped")
        return 0

    routes = list(config.get("routes") or [])
    discovery_cache: dict[str, dict | None] = {}
    if not routes:
        # No explicit routes: enumerate priced resources from each
        # origin's discovery document, the baseline-sweep behaviour.
        for origin in config.get("origins", []):
            doc = http_get_json(origin.rstrip("/") + "/.well-known/x402")
            discovery_cache[origin] = doc
            for res in (doc or {}).get("resources", []) or []:
                if isinstance(res, dict) and res.get("resource"):
                    price = res.get("price")
                    if price and price != "$0.00":
                        routes.append(res["resource"])

    verdicts = []
    for url in routes:
        origin = origin_of(url)
        if origin not in discovery_cache:
            discovery_cache[origin] = http_get_json(
                origin + "/.well-known/x402")
        verdicts.append(
            probe_route(url, declared_accepts(discovery_cache[origin], url)))

    run = {
        "client": config.get("client"),
        "ran_at": now_iso(),
        "cadence": config.get("cadence"),
        "knock_channel": config.get("knock_channel"),
        "routes_checked": len(verdicts),
        "ok": sum(1 for v in verdicts if v["verdict"] == "OK"),
        "defects": sum(1 for v in verdicts if v["verdict"] != "OK"),
        "verdicts": verdicts,
    }
    # <slug>.json -> <slug>.last-run.json, beside the config
    out_path = cfg_path.parent / (cfg_path.stem + ".last-run.json")
    out_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    print(f"Managed Loop watch — {run['client']} — {run['ran_at']}")
    print(f"{'Route':<58} {'HTTP':<6} {'Verdict':<8} Defect / detail")
    print("-" * 110)
    for v in verdicts:
        http = "none" if v["http_status"] is None else str(v["http_status"])
        defect = v["defect"] or "—"
        print(f"{v['route']:<58} {http:<6} {v['verdict']:<8} "
              f"{defect} — {v['detail']}")
    print("-" * 110)
    print(f"{run['routes_checked']} routes checked: {run['ok']} ok, "
          f"{run['defects']} defect(s). Last-run JSON: {out_path}")
    return 0 if run["defects"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
