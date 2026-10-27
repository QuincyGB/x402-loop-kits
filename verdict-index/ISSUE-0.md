# Verdict Index — Issue #0 (2026-10-26)

*The changelog for the CDP Bazaar catalog. Data product: StallRow
`POST /v1/index/changes` ($0.10) — this issue is the free sample,
produced with the same diff code the route serves.*

## The baseline

First full snapshot of the public CDP discovery catalog, pulled
2026-10-26 (evening, Toronto) from
`api.cdp.coinbase.com/platform/v2/x402/discovery/resources`:

- **78,057 unique resources** (78,147 sightings; the catalog churns
  during a ~13-minute pull and repeats resources across pages — last
  sighting wins)
- **7,799 distinct service names**, 1,823 distinct payTos
- Networks: 77,111 on Base mainnet, 610 on Solana, the rest scattered
  (Base Sepolia 154, Arc 40, a long tail)
- The API's own `total` counter said 78,147 → 78,183 across the two
  pulls while the unique-resource census *fell* — the counter is not
  a census; normalized unique resources are. That is why this product
  exists.

## First diff: snapshot #1 → #2 (same evening, <1 hour apart)

| | |
|---|---|
| Resources before | 78,057 |
| Resources after | 78,018 (net −39) |
| Added | 166 |
| Removed | 205 |
| Field changes on surviving resources | **1** (a service-name change) |
| payTo changes | 0 |
| Price changes | 0 |

**The finding:** the catalog churns by birth and death, not by
edits. In under an hour, 371 resources entered or left while exactly
one surviving listing changed any tracked field. A router that syncs
weekly is navigating a materially different catalog than the one it
priced against — and almost none of the risk is price drift; it is
listings vanishing.

## Drift facts already on record (annotated)

- **Our own fleet, 2026-10-26:** two routes launched (StallRow Fleet
  Pass and Webhook Watch), five listing descriptions revised for the
  500-char catalog limit — and none of it is in the catalog yet,
  because new routes enter the index only after a settled seed call.
  The baseline counts exactly **19 fleet resources**, all pre-dating
  that evening.
- **LockSmith, live but uncounted:** settled on CDP and PayAI,
  x402scan-verified, health 200 — and absent from this baseline.
  The merchant count still reads 19 of 20 routes. Indexing lag is
  measured here at **≥1 day and counting**; any "is it listed?"
  check that trusts one snapshot will lie to you in both directions.
- **Settled re-tests, 2026-10-26:** the fleet's 19 catalogued
  endpoints were re-purchased and re-graded by Settled's scout —
  35/35 delivered, all stamped `as_advertised`. No price, payTo, or
  terms changes were found against the prior stamps: the re-test
  *was* the drift check, and the drift was zero.

## Get the feed

`POST /v1/index/changes` on StallRow ($0.10, Fleet Pass debitable)
returns the diff between the two newest in-service snapshots, with
filters (`resource_contains`, `pay_to`, `service_name`). In-service
snapshots accrue about every 6 hours from 2026-10-27; until the
second one lands the route returns 502 and charges nothing — a diff
that doesn't exist yet is not a product.

*Seeding note (for the record): the route itself is live and its 402
verified; its catalog seed call is queued on the fleet's top-up
list, so the route enters the Bazaar index with the next seed
batch.*
