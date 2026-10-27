# Verdict Row Verified — badge criteria

A stall earns the badge by passing three checks, all run against
public surfaces, all re-runnable by anyone. The badge is awarded per
**service** (a stall), never per route, and it expires: criteria are
re-checked on a rolling basis and a stall that stops passing comes
off the page.

## The three criteria

1. **Live 402 exact-match.** For every paid route the service lists
   in its `/.well-known/x402` manifest, an unpaid probe returns a
   402 whose `accepts` exactly match the manifest entry — amount,
   asset, network, payTo. A manifest that advertises one price and
   charges another is the failure this badge exists to catch.
2. **Delivery evidence within 7 days.** Either a Settled delivery
   stamp (`as_advertised`) covering the service's routes, or our own
   full battery within the last 7 days: health 200, manifest
   reachable and parseable, and documented paid deliveries against
   the service's mechanics. Seeds we pay ourselves are labelled as
   seeds wherever they're cited — they prove delivery, not demand.
3. **No unannounced payTo/price drift on record.** Across all
   Verdict Index catalog snapshots, the service's listed payTo and
   amounts never changed without the change appearing in the
   changelog. **Record-depth honesty:** the Index's snapshot history
   starts 2026-10-26. Until it is 30 days deep (2026-11-25), this
   criterion reads "no drift on record (N snapshots since
   2026-10-26)" — the badge page always prints the current depth. A
   stall that predates the record is not penalized for our late
   start; it is also not credited with history we never observed.

## What the badge does NOT claim

- Not a security audit (that is LockSmith's separate, narrower
  battery, and it says so on its own page).
- Not a quality or honesty grade of the service's *data* — the
  badge covers payment-surface integrity and delivery, nothing else.
- Not an endorsement. It is a dated measurement, and the badge page
  shows the date and the evidence for every awarded stall.

## Participation rule

No external stall is badged, listed, or named on the badge page
without its operator's participation. Criteria runs against external
stalls happen only when the operator asks. Our own five services
are dogfooded under exactly these criteria, pass or fail, in
public — including failures.

## Dogfood record — 2026-10-26 (first run)

Battery: `badge/run_battery.py` in this repo (health + manifest +
per-route unpaid 402 exact-match), Settled re-test record of
2026-10-26, Verdict Index snapshots #1–#2 (2026-10-26).

| Service | 402 exact-match | Delivery evidence ≤7d | Drift on record | Verdict |
|---|---|---|---|---|
| Token Verdict | PASS — 3/3 routes | Settled stamp 2026-10-26 (3 routes) | none (2 snapshots) | **AWARDED** |
| RouteVerdict | PASS — 1/1 routes | Settled stamp 2026-10-26 (1 route) | none (2 snapshots) | **AWARDED** |
| ListSmith | PASS — 2/2 routes | Settled stamp 2026-10-26 (2 routes) | none (2 snapshots) | **AWARDED** |
| LockSmith | PASS — 1/1 routes | Full battery 2026-10-25/26 (seed settlements labelled; dogfood audits 8/8) | none — not yet catalog-indexed | **AWARDED** |
| StallRow | PASS — 15/15 routes | Settled stamps on its original routes; Fleet Pass/Webhook Watch delivered live 2026-10-26 (client-#0 demo) | none (2 snapshots) | **FAIL — see below** |

Battery output: `badge/battery-2026-10-26.json` (22 routes probed
across the five services; every live 402 exact-matched its manifest).

**StallRow fails the first dogfood run**, on criterion 2's plain
reading: its newest route, `POST /v1/index/changes`, cannot yet
deliver its advertised function — the Verdict Index holds one
in-service snapshot and a changelog diff needs two. Rather than
carve an exception for our own stall, the badge waits. Re-check
after the second in-service snapshot lands (expected 2026-10-27);
the badge page carries this failure and its reason until then.

## Re-check — 2026-10-27

Battery re-run (`badge/battery-2026-10-27.json`): all five services
PASS criterion 1 — 23 routes probed, StallRow now 16/16 including
fleet-pass, index and orchestrate; every live 402 exact-matched its
manifest. The four awarded stalls are unchanged.

StallRow had two delivery blocks at the first run. One cleared:

- **`/v1/orchestrate` — CLEARED.** The fleet-internal secret is set
  in production on all five services; the internal round-trip
  passed on all four siblings (correct secret delivers, wrong
  secret 403s); and a paid dogfood seed call on 2026-10-27 settled
  ($0.75, Base tx
  `0x3cded2abdaa34379fe090055124db1b3d4c19709cc2e30090dcc58add2ace30d`)
  and delivered the full combined report — legs_ok: token_verdict
  (SOLID), route_verdict (TRUSTED), locksmith (SECURE), listsmith
  (grade payload delivered); legs_failed: none. Seed labelled as
  seed: it proves delivery, not demand.

One block stands:

- **`/v1/index/changes` — STILL BLOCKED.** A paid attempt on
  2026-10-27 again returned the route's charge-free 502: fewer
  than two catalog snapshots stored in-service, so there is no
  honest diff to sell yet. No payment settled on the attempt
  (balances verified unchanged).

**Verdict: StallRow remains NOT AWARDED** — criterion 2 is not
met while a listed route cannot deliver. Re-check after the
second in-service snapshot lands.
