# Token Verdict — Accuracy Ledger: methodology

Written BEFORE the first scoring run (2026-10-26). The rules below are
fixed in advance; a snapshot that scores verdicts under rules invented
after seeing the outcomes would be marketing, not a track record.

## What is recorded

One record per Token Verdict call that returned a verdict:

- `ts` — when the verdict was served (UTC)
- `address`, `chain` — the token screened
- `verdict` — SOLID / CAUTION / DANGER
- `score` — the 0–100 risk score served with it
- `price_usd_at_verdict`, `liquidity_usd_at_verdict` — the market data
  the verdict itself was derived from (may be missing in older records;
  the field is recorded as null, never back-filled with later data)
- `pair_address`, `dex` — so scoring re-reads the SAME pair

Sources, in order of trust:

1. **The service's own ledger** (from 2026-10-26 on): Token Verdict
   appends one JSON line per served verdict (`app/ledger.py` in the
   token-verdict repo). This is the only complete source.
2. **verdict-loop's public live log** (2026-10-25 →): our own demo
   buyer's published runs. Parsed into records by `parse_live_log.py`.
   Prices/liquidity are parsed from the log's analyst "take" lines
   where present; where a run's entry has no take (one backfilled
   entry), the record carries nulls and is scored on liquidity
   survival only.
3. Anything else — seed calls, Settled scout purchases, external
   buyers' calls — produced verdicts that were **never recorded** in
   any store we can still read (the service kept no verdict log
   before 2026-10-26, and Railway's runtime logs are not an archive).
   Those verdicts are unrecoverable and are NOT estimated, sampled,
   or reconstructed here. The ledger starts from what exists.

## Scoring rules (fixed 2026-10-26, before any scoring)

A record becomes scoreable at **+7 days** after `ts`. A **+30 day**
evaluation repeats the same rules when the record reaches 30 days;
the two horizons are reported separately, never blended.

Outcome data comes from DEXScreener, the same source the verdicts are
derived from: the pair's current `priceUsd` and `liquidity.usd`.

- **Collapsed**: the pair no longer resolves on DEXScreener, or its
  liquidity is under **$1,000**.
- **Price move**: `(price_now − price_at_verdict) / price_at_verdict`,
  computed only when a baseline price was recorded.
- **SOLID is correct** when the token did NOT collapse and the price
  move is **> −30%**. SOLID is **incorrect** when it collapsed or the
  move is **≤ −30%**.
- **DANGER is correct** when the token collapsed or the price move is
  **≤ −30%**. DANGER is **incorrect** when the move is **≥ +30%**
  and it did not collapse. Between −30% and +30% a DANGER verdict is
  **inconclusive** — counted, but in neither the correct nor the
  incorrect bucket.
- **CAUTION is never scored for or against.** It is a hedge call; it
  is counted in coverage and excluded from hit-rate denominators.
- Records without a baseline price are scored on the collapse test
  only (survived / collapsed) and reported in a separate column.
- A record whose pair cannot be fetched at scoring time for a
  transient reason (API error, not a missing pair) is left
  **pending**, not collapsed. "Pair gone" requires DEXScreener to
  answer successfully with no pair for the token.

**Hit rate**, when published at all, is
`correct / (correct + incorrect)` over mature records at one horizon,
with the n printed next to it. No hit rate is published until at
least one record has matured — a percentage over zero (or over a
handful of same-token) records would say nothing, so early snapshots
report coverage only: records tracked, records mature, by verdict.

## Honesty rules for every snapshot

- Coverage numbers are exact counts of the records in
  `verdicts.jsonl`; nothing is extrapolated.
- Self-funded records (our own seeds, the demo buyer) are labelled
  as such; they are the only history that exists, and the snapshot
  says so.
- If a future snapshot's rules need to change, the change is dated
  here and old snapshots are re-scored under the new rules or left
  as-is and labelled — never silently re-based.
