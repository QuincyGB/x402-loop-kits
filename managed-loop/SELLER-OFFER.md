# Stall Watch — done-for-you monitoring for x402 sellers

**The offer in one line:** you run a stall; we watch it the way a
buyer's inspector would — and we tell you the moment your listing
delists, drifts, or breaks, before your payers find out from a
failed call.

This is the seller-side twin of Managed Loop (`OFFER.md`, which
watches endpoints a *buyer* depends on). Same machinery, pointed the
other way.

## What we watch on your stall

- **Delisting.** Your resources' presence in the CDP Bazaar catalog,
  diffed snapshot-to-snapshot by our Verdict Index (StallRow
  `POST /v1/index/changes`). Absence in **two consecutive snapshots**
  raises the alert — never one: indexing lag is real (our own
  LockSmith was live, settled, and verified while the catalog still
  showed 19 of our 20 routes), and we will not cry wolf with your
  name on it.
- **Drift.** Price, payTo, asset, network, or description changes on
  your own listings that you didn't announce — the classic case is a
  redeploy that quietly changes the 402 your manifest advertises.
  payTo and amount changes are flagged CRITICAL.
- **Breakage.** Your live unpaid 402 checked against your published
  manifest (exact amount/asset/network/payTo match) and your service
  health, on the fleet's own RouteVerdict/Recheck rails.
- **Weekly health report.** One page per stall: catalog presence,
  402-vs-manifest match status, every change with its diff, and —
  where a public inspector record exists — what it says. The format
  is the seller mirror of `DEMO-CLIENT0.md`.

## Pricing — and the math under it

Delivery costs are the fleet's own listed prices:

| Cost input | Listed price |
|---|---|
| Recheck, per check (pack rate) | $0.004 ($1.00 pack = 250 checks) |
| RouteVerdict delivery check | $0.01 |
| Verdict Index diff (per snapshot pair) | $0.10 |
| Our time | the rest of the fee |

| Tier | Fee | Covers | Our monthly delivery cost |
|---|---|---|---|
| **Stall** | **$25/mo** | 1 stall (up to 5 routes), daily checks, delist/drift alerts, weekly report | ~35 checks ≈ $0.14 + 4 route checks $0.04 + index share ≈ **$0.20** |
| **Row** | **$79/mo** | up to 5 stalls (25 routes), checks every 6h, alerts, weekly report | ~3,000 checks ≈ $12.00 + route checks ≈ **$13** |
| **Fleet** | **$199/mo** | up to 25 stalls, hourly checks, alerts, weekly report, monthly 402-vs-manifest audit per route | ~18,000 checks ≈ $72 + audits ≈ **$75** |

Fees monthly, cancel anytime, a month paid up front (USDC on Base to
the fleet payTo, or by arrangement). Setup $0 — the first weekly
report is the proof.

## Honest limits

- Catalog snapshots refresh about every 6 hours; a delist-and-relist
  entirely between snapshots is invisible to any snapshotter, us
  included.
- "Delisted" always means *absent from the catalog in two
  consecutive snapshots* — the catalog is an index, not your service;
  we report the index's state and your service's state separately
  and never merge them.
- We watch public surfaces only: your catalog metadata, your
  manifest, your unpaid 402, your health endpoint. No logins, no
  private data, nothing behind your paywall.
- Client count today: **one — our own fleet (client #0)**. No
  external seller client is claimed anywhere in this offer.

## Start

Open an issue on this repo or reply to any fleet listing with: your
stall's base URL (or your payTo), a webhook or email for alerts, and
a tier. First report within 7 days of the first funded check.
