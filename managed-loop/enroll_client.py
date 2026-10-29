#!/usr/bin/env python3
"""Managed Loop — enroll a client.

Writes (or updates in place) the per-client watch config that
run_client_watch.py consumes:

    managed-loop/clients/<slug>.json
    {
      "client": "<slug>",
      "enrolled_at": "<ISO-8601 UTC>",
      "origins": ["https://stall.example.com", ...],
      "routes": ["https://stall.example.com/v1/route", ...],
      "knock_channel": "email" | "nudge",
      "contact": "<email or null>",
      "cadence": "daily",
      "enabled": true
    }

Usage:
    python3 enroll_client.py --name <slug> --origins <url,url,...> \
        [--routes <url,url,...>] [--knock email|nudge] [--contact <email>]

Rules:
  * stdlib only; no network calls; nothing is sent anywhere.
  * Every origin (and every route, if given) must parse as an http(s)
    URL with a host — anything else is rejected and no file is written.
  * Idempotent: re-enrolling an existing slug updates the config in
    place, preserving the original enrolled_at.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
CLIENTS_DIR = HERE / "clients"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def parse_url_list(raw: str, field: str) -> list[str]:
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    if not urls:
        raise SystemExit(f"error: --{field} needs at least one URL")
    for u in urls:
        parts = urlsplit(u)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise SystemExit(
                f"error: --{field} value is not an http(s) URL: {u!r}"
            )
    return urls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="client slug, e.g. acme-stall")
    ap.add_argument("--origins", required=True,
                    help="comma-separated stall origins (http(s) URLs)")
    ap.add_argument("--routes", default="",
                    help="comma-separated full route URLs to watch "
                         "(defaults to none; the baseline sweep enumerates "
                         "routes from each origin's /.well-known/x402)")
    ap.add_argument("--knock", choices=["email", "nudge"], default="email",
                    help="knock channel: email, or a fleet-health nudge inbox")
    ap.add_argument("--contact", default=None, help="contact email")
    args = ap.parse_args()

    if not SLUG_RE.match(args.name):
        raise SystemExit(
            f"error: --name must be a slug ([a-z0-9-], starting alphanumeric): {args.name!r}"
        )
    origins = parse_url_list(args.origins, "origins")
    routes = parse_url_list(args.routes, "routes") if args.routes else []

    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIENTS_DIR / f"{args.name}.json"

    enrolled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("enrolled_at"):
                enrolled_at = existing["enrolled_at"]
        except Exception:
            pass  # unreadable config is replaced wholesale

    config = {
        "client": args.name,
        "enrolled_at": enrolled_at,
        "origins": origins,
        "routes": routes,
        "knock_channel": args.knock,
        "contact": args.contact,
        "cadence": "daily",
        "enabled": True,
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
