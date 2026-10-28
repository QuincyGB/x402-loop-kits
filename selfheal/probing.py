"""Unpaid probing: discovery reads and declared-vs-live route
probes, with the Fleet Check defect classification. Transport is
injected — an HttpFn is

    http(method, url, body=None, headers=None, attempts=1)
        -> (status|None, headers dict, body str, error|None)

matching the fleet checker's curl transport. The default here is
plain urllib (fine for most networks; the reference fleet runner
injects the checker's curl transport because this VM's egress
resets some urllib POSTs — see fleet-checker/check.py).
"""

import base64
import json
import urllib.error
import urllib.request

USER_AGENT = "selfheal-receiver/1.0"


def urllib_http(method, url, body=None, headers=None, attempts=1):
    last_err = None
    for _ in range(max(1, attempts)):
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", USER_AGENT)
        data = None
        if body is not None:
            data = body.encode() if isinstance(body, str) else body
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, data=data, timeout=40) as resp:
                return (
                    resp.status,
                    {k.lower(): v for k, v in resp.headers.items()},
                    resp.read().decode("utf-8", "replace"),
                    None,
                )
        except urllib.error.HTTPError as e:
            return (
                e.code,
                {k.lower(): v for k, v in (e.headers.items() if e.headers else [])},
                e.read().decode("utf-8", "replace") if e.fp else "",
                None,
            )
        except Exception as e:  # noqa: BLE001 — transport failure is a result, not a crash
            last_err = str(e)
    return None, {}, "", last_err


def decode_challenge(hdrs):
    """(challenge dict|None, error|None) from a 402's headers —
    the same semantics as the fleet checker's."""
    v = None
    for k, val in (hdrs or {}).items():
        if k.lower() == "payment-required":
            v = val
            break
    if not v:
        return None, "missing payment-required header"
    try:
        return json.loads(base64.b64decode(v)), None
    except Exception as e:  # noqa: BLE001
        return None, f"payment-required header not decodable: {e}"


def fetch_discovery(origin: str, http):
    """The stall's /.well-known/x402 document, or None."""
    status, _h, body, err = http(
        "GET", origin.rstrip("/") + "/.well-known/x402", attempts=2
    )
    if status != 200 or err:
        return None
    try:
        doc = json.loads(body)
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def declared_entry(doc, route: str):
    """The discovery-doc resource entry for a route URL, or None."""
    if not doc:
        return None
    for entry in doc.get("resources") or []:
        if isinstance(entry, dict) and (entry.get("resource") or entry.get("url")) == route:
            return entry
    return None


def probe_route(url: str, declared, http, at: str):
    """Unpaid probe of one resource. Returns (defect|None, probe
    record) — the Fleet Check classification, identical in shape
    and codes to the sender engine's probe, so a receiver's
    re-probe lands on the same facts a conforming sender's did."""
    status, hdrs, _body, err = http("POST", url, body="{}", attempts=2)
    probe = {"at": at, "http_status": status}
    if status is None:
        probe["detail"] = f"transport failure: {err}"
        return (
            {"code": "unreachable", "expected": "an HTTP response", "observed": "none"},
            probe,
        )
    if status >= 500:
        probe["detail"] = f"target returned HTTP {status}"
        return ({"code": "server_error", "expected": "402", "observed": str(status)}, probe)
    if status == 200:
        probe["detail"] = "answers HTTP 200 to an unpaid probe"
        return ({"code": "no_402", "expected": "402", "observed": "200"}, probe)
    if status != 402:
        probe["detail"] = f"answers HTTP {status}, not a 402 challenge"
        return (
            {"code": "unexpected_status", "expected": "402", "observed": str(status)},
            probe,
        )
    challenge, derr = decode_challenge(hdrs)
    if challenge is None or not challenge.get("accepts"):
        probe["detail"] = derr or "challenge carries no accepts"
        return (
            {
                "code": "challenge_undecodable",
                "expected": "a parseable x402 challenge with accepts",
                "observed": "undecodable",
            },
            probe,
        )
    live = next((a for a in challenge["accepts"] if isinstance(a, dict)), {})
    probe["detail"] = (
        f"live challenge: amount {live.get('amount')} to {live.get('payTo')} "
        f"on {live.get('network')}"
    )
    if declared:
        declared_accepts = [
            a for a in (declared.get("accepts") or []) if isinstance(a, dict)
        ]
        if declared_accepts:
            decl = next(
                (a for a in declared_accepts if a.get("network") == live.get("network")),
                declared_accepts[0],
            )
            if (
                decl.get("amount") is not None
                and live.get("amount") is not None
                and str(decl["amount"]) != str(live["amount"])
            ):
                return (
                    {
                        "code": "amount_mismatch",
                        "expected": str(decl["amount"]),
                        "observed": str(live["amount"]),
                    },
                    probe,
                )
            if (
                decl.get("payTo")
                and live.get("payTo")
                and str(decl["payTo"]).lower() != str(live["payTo"]).lower()
            ):
                return (
                    {
                        "code": "payto_mismatch",
                        "expected": str(decl["payTo"]),
                        "observed": str(live["payTo"]),
                    },
                    probe,
                )
    return None, probe
