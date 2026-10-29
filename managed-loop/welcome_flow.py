#!/usr/bin/env python3
"""Managed Loop — welcome flow (SEND SIDE DISARMED).

When a Managed Loop intake lands, this flow:
  1. enrolls the client (enroll_client.py — config only),
  2. runs a FREE welcome recheck of the submitter's own stall
     (run_client_watch.py — unpaid probes, the fleet's own
     classification; this is the welcome gift, it costs the
     submitter nothing and pays nobody),
  3. composes the welcome message carrying the recheck table,
  4. queues it in welcome-outbox/ as a draft record.

NOTHING IS SENT. There is no send code in this file at all. The
send side arms only when the verdictrow.com mailboxes are live
(a separate setup); arming means a future sender reads this
outbox and sends from WELCOME_FROM — the single config value
below, so the flip to support@verdictrow.com is one line / one
env var, never a code hunt.

Intake JSON (the published intake form's fields, saved to a file):
    {
      "name": "acme-stall",                  // slug
      "contact": "ops@acme.example",         // email
      "tier": "watch" | "row" | "fleet",
      "origins": ["https://acme.example"],
      "routes": ["https://acme.example/v1/route"]   // optional
    }

Usage:
    python3 welcome_flow.py --intake intake.json

Stdlib only. Exit 0 = enrolled + rechecked + welcome queued.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTBOX_DIR = HERE / "welcome-outbox"

# THE sender address — one config value. Arming the send side
# later means sending from exactly this address; today it is only
# written into queued drafts.
WELCOME_FROM = os.environ.get(
    "MANAGED_LOOP_WELCOME_FROM", "support@verdictrow.com"
)

TIERS = {
    "watch": ("Watch", "$25/mo", "1 endpoint, daily checks"),
    "row": ("Row", "$79/mo", "up to 5 endpoints, checks every 6 hours"),
    "fleet": ("Fleet", "$199/mo", "up to 25 endpoints, hourly checks"),
}

FIX_HINTS = {
    "unreachable": "check the deployment is up and DNS resolves publicly",
    "server_error": "read the server-side error — a buyer cannot get a payment challenge from a route that errors first",
    "no_402": "if the route is meant to be paid, put the x402 paywall in front of it",
    "unexpected_status": "check for a WAF/auth layer answering first, or a moved route — an unpaid buyer should meet the 402 directly",
    "challenge_undecodable": "return the challenge as base64 JSON in the PAYMENT-REQUIRED header (or a JSON body) with an accepts array",
    "amount_mismatch": "bring the live challenge amount and your /.well-known/x402 declaration back into agreement",
    "payto_mismatch": "align the payTo in the challenge and the discovery document",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_step(argv: list[str], accept: tuple[int, ...]) -> subprocess.CompletedProcess:
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode not in accept:
        raise SystemExit(
            f"step failed ({' '.join(argv)} -> exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    return proc


def compose_welcome(intake: dict, run: dict) -> tuple[str, str]:
    tier_name, tier_price, tier_shape = TIERS[intake["tier"]]
    lines = [
        f"Welcome to Managed Loop ({tier_name}, {tier_price}) — your stall is enrolled.",
        "",
        "As promised, here is the free first recheck of your own stall,",
        "run just now with the same unpaid probes and defect classes we",
        "run on our own fleet (the probe never pays, signs, or settles):",
        "",
    ]
    for v in run["verdicts"]:
        http = "no response" if v["http_status"] is None else f"HTTP {v['http_status']}"
        lines.append(f"  {v['route']}")
        if v["verdict"] == "OK":
            lines.append(f"    OK — {http}, parseable 402 challenge.")
        else:
            lines.append(f"    DEFECT {v['defect']} — {http}. {v['detail']}")
            hint = FIX_HINTS.get(v["defect"])
            if hint:
                lines.append(f"    Usual fix: {hint}.")
    lines += [
        "",
        f"Summary: {run['routes_checked']} route(s) checked, "
        f"{run['ok']} ok, {run['defects']} defect(s).",
        "",
        f"Your plan: {tier_shape}; webhook alerts on break/recover and a",
        "weekly report. If a route above shows a defect, it is also the",
        "first thing your watch is now tracking — you will hear about",
        "changes, not silence.",
        "",
        "Questions: just reply to this message.",
        "",
        "— Verdict Row (Managed Loop)",
    ]
    subject = (
        f"Managed Loop welcome — your stall's free recheck "
        f"({run['ok']}/{run['routes_checked']} routes ok)"
    )
    return subject, "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--intake", required=True, help="intake JSON file")
    args = ap.parse_args()

    intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    for field in ("name", "contact", "tier"):
        if not intake.get(field):
            raise SystemExit(f"intake is missing {field!r}")
    if intake["tier"] not in TIERS:
        raise SystemExit(f"unknown tier {intake['tier']!r} (watch | row | fleet)")
    origins = intake.get("origins") or []
    routes = intake.get("routes") or []
    if not origins and not routes:
        raise SystemExit("intake names no origins or routes to watch")
    if not origins and routes:
        origins = sorted({r.rsplit("/", 2)[0] for r in routes})
    slug = intake["name"]

    # 1. Enroll (config only — sends nothing).
    enroll = [sys.executable, str(HERE / "enroll_client.py"),
              "--name", slug,
              "--origins", ",".join(origins),
              "--knock", "email",
              "--contact", intake["contact"]]
    if routes:
        enroll += ["--routes", ",".join(routes)]
    run_step(enroll, accept=(0,))

    # 2. Free welcome recheck (unpaid probes; exit 2 = defects found,
    #    which is a result, not a failure of the flow).
    config = HERE / "clients" / f"{slug}.json"
    run_step([sys.executable, str(HERE / "run_client_watch.py"),
              "--config", str(config)], accept=(0, 2))
    run = json.loads(
        (HERE / "clients" / f"{slug}.last-run.json").read_text(encoding="utf-8")
    )

    # 3 + 4. Compose and QUEUE — the send side is disarmed; the
    #        record says so in plain fields.
    subject, body = compose_welcome(intake, run)
    OUTBOX_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "queued_at": now_iso(),
        "status": "queued_disarmed",
        "send_armed": False,
        "disarm_reason": (
            "verdictrow.com mailboxes not live yet — sending arms "
            "only when they are; this record is a draft in a queue, "
            "not a sent message"
        ),
        "from": WELCOME_FROM,
        "to": intake["contact"],
        "subject": subject,
        "body": body,
        "client": slug,
        "tier": intake["tier"],
        "recheck": {
            "ran_at": run["ran_at"],
            "routes_checked": run["routes_checked"],
            "ok": run["ok"],
            "defects": run["defects"],
        },
    }
    out_path = OUTBOX_DIR / f"{slug}-{stamp}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"enrolled: {slug} ({intake['tier']})")
    print(f"welcome recheck: {run['routes_checked']} routes, "
          f"{run['ok']} ok, {run['defects']} defect(s)")
    print(f"welcome QUEUED (not sent): {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
