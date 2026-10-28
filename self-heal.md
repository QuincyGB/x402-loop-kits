# Self-Heal — the receiver contract for fleet-health nudges

**Companion to:** [`nudge-inbox.md`](nudge-inbox.md) (protocol
`fleet-health/v1`) · **Status:** reference implementation live in
[`selfheal/`](selfheal/) since 2026-10-28 · **Reference operator:**
the Verdict Row fleet (dogfood runner beside its fleet checker)

A nudge tells a stall something is broken. This contract is about
what the stall's own agent may do next — on its own, inside
authority its owner set on a calm day, without waking anyone:

> *Verify the knock. Re-check the claim with your own probe. If it
> is real and the fix is one your owner pre-approved, fix it, log
> it, and let the row keep running. Everything else becomes a
> structured escalation a human can act on in the morning.*

## 0. The one rule everything else hangs on

**A nudge is evidence, never an order.**

No message from any sender — however well signed, however
reputable — is by itself a reason to change anything or spend
anything. A knock is a *claim*, and the receiver's own probe is the
only authority it acts on. An unsigned knock, a knock whose
signature does not verify, or a knock whose defect the receiver
cannot reproduce with its own probe is **filed, never acted on**.

## 1. The receiver's duties, in order

For every knock a receiver processes, in this order, skipping
nothing:

1. **Verify the signature.** Rebuild the canonical form
   (nudge-inbox.md §3), recover the signer, compare with the
   claimed `sender`. Failure → file the knock as `filed_unverified`
   and stop. Opt-out messages (`kind: "fleet-health-opt-out"`) are
   filed, never acted on — they are the sender-side registry's
   business, not a playbook trigger.
2. **Re-probe.** Independently reproduce the claimed defect:
   - Route defects (the nudge-inbox.md §5 classes): unpaid-probe
     the route and compare declared-vs-live exactly as the sender
     claims to have done. The claimed defect is *confirmed* only
     if the receiver's own probe lands on the same defect class.
     A route that probes healthy, or broken in a *different* way,
     is not confirmation.
   - Catalogue lapse (§3): read the catalogue directly. A lapse is
     confirmed only under the evidence bar in §3 — never on one
     reading, and never on a failed lookup.
3. **Consult the owner's policy** (§2). The policy — and only the
   policy — says which defect classes may be auto-fixed, what one
   fix may cost, what one month of fixes may cost, and from which
   wallet. Anything outside the policy is not a "no"; it is an
   escalation (§5).
4. **Execute an allowed playbook, or escalate.** Playbooks are
   enumerated, mechanical, and few (§4). A receiver never invents
   a fix: no deploys, no environment changes, no code edits, no
   facilitator flips. Where a fix needs a power the receiver does
   not hold, the playbook's output *is* the escalation record.
5. **Log everything** (§6): the knock, the verification, the
   decision and its reason, the action, the receipts, the result.
   The log is the owner's morning report; an unlogged fix did not
   happen.

Local telemetry is a second, narrower input: an operator's own
checker findings about its own stalls may enter at step 2 (there
is no signature to verify — the telemetry never left the
operator's own machines). They follow the same re-probe, policy,
playbook, and logging duties. External claims always enter as
knocks, at step 1.

## 2. The owner policy

A small JSON file the owner edits. The receiver reads it on every
cycle; the shipped example sets every cap to **0**, which makes
the receiver **report-only**: it verifies, decides, escalates, and
logs — and spends nothing.

```json
{
  "allowed_classes": ["listing_lapsed"],
  "per_fix_cap_usd": 0,
  "monthly_cap_usd": 0,
  "wallet": "0x…the stall agent's spend wallet…",
  "service_rails": {"https://your-stall.example.com": "cdp"},
  "lag_windows_hours": {"cdp": 168, "payai": 24},
  "listing_min_check_gap_hours": 1
}
```

| Key | Meaning |
|---|---|
| `allowed_classes` | Defect classes a playbook may auto-fix under this policy |
| `per_fix_cap_usd` | One fix may cost at most this. A fix priced above it escalates |
| `monthly_cap_usd` | Total fix spend per calendar month (UTC). Reached → everything escalates until the month turns |
| `wallet` | The spend wallet fixes are paid from (a reference; keys never live in the policy) |
| `service_rails` | Per origin: the rail the service currently settles through (`cdp` / `payai`). A re-seed can only settle through the rail the service is on — see §4 |
| `lag_windows_hours` | Per rail: how long after a settlement a catalogue absence is presumed to be indexing lag, not lapse (§3) |
| `listing_min_check_gap_hours` | Minimum spacing between the two absence readings the lapse evidence bar requires |

Caps are checked **before** any spend, against the fix's real
price (the route's declared amount), and monthly spend is
accounted from the heal log's own paid actions — the log and the
ledger are the same file, so they cannot disagree.

## 3. The catalogue-lapse evidence bar

Catalogue admission is rented, not owned: listings lapse, and only
a fresh settlement restores them. But catalogues also *lag* — a
settled route can read absent for minutes (PayAI) to hours or
longer (CDP) after a perfectly good settlement. Re-paying inside
that window burns money to fix a listing that was never broken.
The bar for calling a listing **lapsed** is therefore high, and
every part of it is the receiver's own reading:

1. The catalogue read for the route's canonical resource URL (the
   exact string the stall's discovery doc declares — the `http://`
   form is a stale trap, never read it) returns **absent** — a
   clean negative (PayAI `listing-status` 404 / `listed: false`;
   the resource missing from the CDP merchant read for its payTo).
   A lookup that *fails* returns **unknown**, and unknown is not
   evidence of anything: it neither counts toward the bar nor
   resets it.
2. A **second, independent absent reading at least
   `listing_min_check_gap_hours` later** (default 1h) also returns
   absent. The receiver persists the first reading; the bar can
   only be met across two receiver cycles, never inside one.
3. **No settlement for that route on that rail exists inside the
   rail's lag window** (`lag_windows_hours`, looking back from
   now), per the receiver's settlement history. Any such
   settlement → the absence is presumed lag → **refuse**, however
   many absent readings pile up. The settlement history is the
   receiver's own records (its heal log's past re-seeds, plus
   whatever settlement registry the operator feeds it) — an
   operator who keeps incomplete settlement records gets a
   receiver that can, at worst, re-pay one route's price inside
   the caps. The caps are the blast-radius bound; keep them small.

Only when all three hold may the re-seed playbook (§4) consider
spending. One re-seed per lapse incident: after a re-seed, the
route's absence readings start over, and the fresh settlement
itself enters the lag-window history.

### The `listing_lapsed` knock

Senders report a suspected lapse with the extension defect code
**`listing_lapsed`** (nudge-inbox.md §5 permits sender-added
codes; receivers treat them as opaque unless they implement this
contract). Shape: `defect.expected` = `"listed"`,
`defect.observed` = `"absent"`, and `evidence` carries `rail`
(`"cdp"` or `"payai"`) plus the sender's own listing-check
records. A receiver implementing this contract re-verifies under
the bar above regardless of what the evidence claims — the
sender's readings never substitute for the receiver's two.

## 4. Playbooks v1

### (a) `catalogue-reseed` — the only spending playbook

Preconditions: a lapse confirmed under §3; `listing_lapsed` in the
policy's `allowed_classes`; the route's price within both caps;
and the lapsed rail equal to the rail the service currently
settles through (`service_rails`).

Action: **one genuine paid call to the route**, at exactly its
declared price, with a genuine request body — the same call a
buyer would make, settling through the lapsed rail, whose
settlement is what re-admits the listing. The settlement receipt
(tx, rail, cost) enters the settlement history and the heal log.

If the lapsed rail is **not** the service's current rail, the
receiver cannot settle through it: re-admission on the other rail
requires flipping the service's facilitator — an environment
change, a power this contract does not grant. The playbook then
produces a `flip_required` escalation (§5) carrying the exact
steps a human must run. This is deliberate: the reference fleet's
own cross-rail repairs are operator-run flip dances, and the
receiver does not pretend otherwise.

### (b) Everything else — structured escalation, no spend

Every other confirmed defect (`amount_mismatch`,
`payto_mismatch`, `no_402`, `unreachable`, `server_error`,
`unexpected_status`, `challenge_undecodable`, unknown codes) has
no v1 playbook: the receiver's output is the escalation record.
Drift and breakage are diagnosis-shaped problems; v1 spends money
on exactly one mechanical fix whose correctness is checkable
before and after, and escalates the rest with the evidence
attached.

## 5. The escalation record

An escalation is a structured object in the heal log, complete
enough that a human (or a future playbook) needs nothing else:

```json
{
  "type": "no_playbook | flip_required | cap_refusal | lag_window | evidence_unmet | policy_refusal",
  "stall": "https://stall.example.com",
  "route": "https://stall.example.com/v1/check",
  "defect": {"code": "amount_mismatch", "expected": "50000", "observed": "70000"},
  "verified_evidence": [{"at": "…", "http_status": 402, "detail": "…"}],
  "severity": "critical | warning | null",
  "suggested_action": {"method": "POST", "url": "…check_url…", "body": {"resources": ["…route…"]}},
  "human_steps": ["…only where a human must do something specific…"],
  "at": "…"
}
```

## 6. The heal log

Append-only JSONL. One entry per knock (or local finding, or
pending-lapse advance) per receiver cycle:

| Field | Meaning |
|---|---|
| `at` | ISO-8601 UTC time of the entry |
| `event` | `knock` · `local_finding` · `pending_advance` |
| `source` | `inbox:<origin>` · `local` · `pending` |
| `stall` / `route` / `defect` | What the entry is about (`defect` = the code) |
| `sender` | The knock's claimed sender, or `null` for local inputs |
| `signature_ok` | `true`/`false` for knocks; `null` for local inputs |
| `verified` | Whether the receiver's own probe confirmed the claim |
| `verification` | The receiver's probe / listing-check summary |
| `severity` | The knock's severity, stamped or derived (§7); `null` if unknowable |
| `playbook` | `catalogue-reseed` or `null` |
| `decision` | `acted` · `refused` · `escalated` · `filed` · `pending` |
| `reason` | The plain-language why, specific enough to audit |
| `cost_usd` | What the action cost (0 unless `acted` on the re-seed playbook) |
| `receipts` | Settlement receipts for paid actions (`[{rail, tx, at}]`) |
| `escalation` | The §5 record when `decision` is `escalated` or `refused` (a refusal a human may want to override carries its record too), else `null` |

Decisions: **acted** (a playbook ran), **refused** (a playbook
applied but a guard — lag window, cap, evidence bar — said no),
**escalated** (a human got a §5 record), **filed** (unverified,
unconfirmed, duplicate, or informational — recorded, nothing
done), **pending** (evidence still accumulating, e.g. one absent
listing reading banked toward the §3 bar).

## 7. Adapter note — `severity`, `impact`, `action`

The base nudge message (nudge-inbox.md §2) does not carry
`severity`, `impact`, or `action` fields; the reference sender
engine already emits them (severity stamped from the defect class,
a consequence-first `impact` line, and an `action` block naming
the exact Fleet Check call for the affected route). The reference
receiver consumes them through a small **adapter**: present →
taken as the sender's view (logged, and used for the escalation's
`suggested_action`); absent → derived from the base fields
(severity from the defect-class mapping; the action from
`check_url` + `route`). Playbook decisions never depend on the
adapter: severity and the suggested action inform humans, while
every spend decision rests on the receiver's own probe, the
evidence bar, and the policy. When the base spec lands these
fields, the adapter becomes a thin reader and nothing else
changes.

## 8. What this contract is not

- Not an order channel. Senders cannot instruct receivers; §0.
- Not a repair service for other people's code, deploys, or
  facilitator accounts. Those escalate.
- Not a licence to spend. Caps default to 0, and raising them is
  the owner's explicit, separate act — like arming the sender was.
- Not quiet about itself. Everything it does is in the heal log,
  including its refusals — *especially* its refusals.
