# Managed Loop — client package

What a Managed Loop client sends us, what they receive, and the
config the runner consumes. Pricing lives in `OFFER.md` (Watch
$25/mo, Row $79/mo, Fleet $199/mo, each with its delivery-cost math
shown); this package is the operational companion, not a second
price list.

## The client sends (once, at setup)

1. The endpoint URLs to watch (x402 resources or web pages).
2. A webhook URL for change alerts (or an email — stored; the
   webhook is the live channel).
3. A tier (Watch / Row / Fleet — endpoint count and check interval
   per `OFFER.md`).
4. The month's fee, up front, per `OFFER.md`.

No wallet, no code, no per-call payments on the client's side —
funding the checks is the operator's job, out of the fee.

## The client receives

- **Change alerts (push):** one webhook POST per changed endpoint
  per pass — the diff, with payTo/amount/asset/network changes
  flagged CRITICAL.
- **A weekly report** in the format `runner.py` produces:
  per-endpoint status table, every change in full, and the funding
  balances (pack credits / pass balance) left after the pass.

## Runner config (operator-side, one JSON per client)

```json
{
  "client": "Example Stall Co",
  "tier": "Row",
  "webhook_url": "https://client.example/hook",
  "endpoints": [
    {"url": "https://a.example.com/v1/verdict", "watch_id": "w1",
     "funding": {"kind": "pack", "pack_id": "pack_…"}},
    {"url": "https://b.example.com/v1/check", "watch_id": "w2",
     "funding": {"kind": "fleet_pass", "pass_id": "fpass_…"}}
  ]
}
```

Run one pass:

```bash
python managed-loop/runner.py --config client.json --out report.md          # dry run, $0, labelled
python managed-loop/runner.py --config client.json --out report.md --live   # funded checks + webhook alerts
```

## Operator rules (fleet discipline, binding on us)

- A check that cannot be funded is reported FAILED for that
  endpoint — never silently skipped, never quietly run for free,
  and never switched to the other funding kind.
- A dry-run report is never sent to a client; it is labelled
  DRY RUN in its header.
- Client #0 is our own fleet (`DEMO-CLIENT0.md` is a real pass).
  No external client exists yet, and this package claims none.
- Terms (fee, tier changes, cancellation) are the owner's call —
  the runner implements the offer, it does not negotiate it.
