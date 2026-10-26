# Managed Loop — done-for-you x402 monitoring

**The offer in one line:** you hand us the endpoints (and, if you want
them, the tokens) you depend on; we run the monitoring loop for you —
change alerts pushed to your webhook the moment terms move, plus a
weekly report. You never write, host, or babysit a loop.

## Why this exists

The loop kits in this repo are free and they work — but somebody
still has to run them, fund the packs, read the diffs, and notice a
payTo rotation at 3 a.m. Managed Loop is that somebody. It runs on
the same production machinery the fleet uses on itself (StallRow
Recheck + Webhook Watch, the recheck packs, x402-guard), and our own
fleet is client #0: the demo pass in `DEMO-CLIENT0.md` is a real run
of exactly what a client receives.

## What you get

- **Change alerts (push):** amount, payTo, asset, network, or
  schema/description changes on any watched endpoint POSTed to your
  webhook within one check interval of the change. payTo and amount
  changes are flagged CRITICAL.
- **Weekly report:** every watched endpoint's status, every change
  with its diff, service health, and the pack/pass balances funding
  your watches — the format of `DEMO-CLIENT0.md`, extended per
  endpoint.
- **No integration work:** no wallet to fund per call, no code to
  host. You give us URLs and a webhook; we bring the packs.

## Pricing — and the math under it

Our delivery costs are the fleet's own listed prices, so the margin
is arithmetic, not a story:

| Cost input | Listed price |
|---|---|
| Recheck, per check (pack rate) | $0.004 ($1.00 pack = 250 checks) |
| Token Verdict batch screen (25 tokens) | $0.20 |
| Our time | the rest of the fee |

| Tier | Fee | Covers | Our monthly delivery cost |
|---|---|---|---|
| **Watch** | **$25/mo** | 1 endpoint, daily checks, webhook alerts, weekly report | 30 checks ≈ $0.12 |
| **Row** | **$79/mo** | up to 5 endpoints, checks every 6h, webhook alerts, weekly report, 1 weekly batch token screen | 600 checks ≈ $2.40 + $0.87 screens ≈ **$3.27** |
| **Fleet** | **$199/mo** | up to 25 endpoints, hourly checks, webhook alerts, weekly report, daily batch token screen | 18,000 checks ≈ $72.00 (36 packs' worth, bought as needed) + $6.00 screens ≈ **$78.00** |

Fees are monthly, cancel anytime; a month is paid up front (USDC on
Base to the fleet payTo, or by arrangement). Setup is $0 — the first
weekly report is the proof.

## Honest limits

- Alerts are as fast as the check interval you buy; a change that
  appears and reverts *between* checks is invisible to any poller,
  us included.
- We report what endpoints *advertise* (the unpaid 402 terms and
  page content) — the same evidence Settled-style inspectors grade
  on. We do not pay your endpoints on your behalf.
- Client count today: **one — our own fleet (client #0)**. No
  external client is claimed anywhere in this offer; the demo is our
  own infrastructure, run live, and labelled as such.

## Start

Open an issue on this repo or reply to any fleet listing with: the
endpoints to watch, your webhook URL, and a tier. First report
within 7 days of the first funded check.
