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

## Re-check — 2026-10-27 (index fix): StallRow AWARDED — fleet 5/5

The index block is cleared, and the root cause is on the record
(from stall-row's Railway logs, Oct 26 21:00 UTC → Oct 27 01:40
EDT): the catalog pull ran exactly **once** — at the startup of
the Oct 26 22:50 EDT Verdict Index deployment (all 80 pages 200,
snapshot stored 22:54:15 EDT). The four later deployments started
cleanly (store reopened at `/data/recheck.db`, durability
persistent) but never pulled again: `refresh_if_stale` skips
while the newest snapshot is younger than the 6h window, snapshot
#2 was therefore not due until ~04:54 EDT, and no deployment in
the window lived that long. Zero errors, zero tracebacks — the
gate simply never opened inside any deployment's lifetime, and
every paid attempt landed inside the window. It was a
cold-start design flaw (refresh cadence keyed to a 6h window
with no bootstrap path to a first pair), not a storage, write,
or fetch failure: storage was verified persistent at
`/data/recheck.db`, the store held exactly one snapshot, and the
identical pull code succeeds against the live catalog.

**Fix** (stall-row `13eeaf8`, suite 212 passed): while fewer
than two snapshots are held, the ticker refreshes on a bootstrap
interval (`STALLROW_INDEX_BOOTSTRAP_MIN_S`, default 900s)
instead of the 6h window — so any redeploy sequence reaches a
sellable pair in about one tick once the held snapshot is
>15 min old, and a store wiped to zero rebuilds its pair the
same way (immediate first pull + bootstrap second pull). Steady
state is unchanged (~4 pulls/day). The pull also now identifies
itself (`verdict-row-index/1.0`) with a 60s per-page timeout,
matching the proven baseline pull.

**Production proof:** on the fix's deploy (2026-10-27 01:36
EDT) the ticker stored snapshot #2 at 05:38:08Z ("catalog
snapshot stored (2 held)"). A paid dogfood seed call then
**settled and delivered**: $0.10, Base tx
`0xe45a933c2d23928e34438bbb904c376c1804e28159cfd03f76a19b402b921a58`,
diff of snapshot #1 (2026-10-27T02:54:13Z, 77,945 resources) →
snapshot #2 (80,462): 80 field changes, 2,766 added, 249
removed. That settled call is the route's CDP seed (disclosed
self-seed; it proves delivery, not demand).

Battery re-run the same night (`badge/battery-2026-10-27.json`,
refreshed): 23/23 routes across all five services exact-match —
StallRow 16/16, criterion 1 PASS. Criterion 3: no drift on
record (2 in-service snapshots since 2026-10-26).

| Service | 402 exact-match | Delivery evidence ≤7d | Drift on record | Verdict |
|---|---|---|---|---|
| StallRow | PASS — 16/16 routes | Index + orchestrate delivered live 2026-10-27 (paid dogfood seeds, labelled); Settled stamps; Fleet Pass seeds CDP & PayAI | none (2 in-service snapshots) | **AWARDED** |

**All five fleet services now hold the badge (5/5).**

## Badge v2 — outcome scoring (added 2026-10-27)

V1 certifies the payment surface. V2 adds a fourth criterion, which
applies **only to services with routes whose claims we score**:

4. **Published outcome record.** The service's scored claims are
   tracked in a public accuracy ledger whose scoring rules were
   fixed in writing BEFORE the first scoring run, and the ledger
   publishes its outcomes — hit rate **with its n**, the
   inconclusive and excluded counts, and the inconclusive/caution
   handling — at the horizons the rules name (+7d, +30d). V2 grades
   the existence and honesty of the record, not the hit rate: a low
   rate published with its n passes; mature outcomes that exist but
   are not published fail. While a ledger has records but none are
   mature yet, the status is **TRACKING** — v2 cannot pass on a
   record that has not had time to be wrong.

**Scored routes today:** Token Verdict's verdicts only, scored by
`accuracy-ledger/` (rules: `accuracy-ledger/METHODOLOGY.md`, fixed
2026-10-26; snapshot: `accuracy-ledger/snapshot.json`). The other
four fleet services have no outcome-scored route; their v2 status
is NOT_APPLICABLE — stated, never silently passed, never failed
for lacking a claim nobody scored.

**Dogfood evaluation — 2026-10-27** (`badge/evaluate_v2.py`,
output `badge/badge-v2-2026-10-27.json`): Token Verdict —
TRACKING (6 records, all self-funded and labelled as such, 0
mature until 2026-11-01, hit rate null and published as null).
RouteVerdict, ListSmith, StallRow, LockSmith — NOT_APPLICABLE.
No external stall has been evaluated under v2 (the participation
rule above is unchanged).
