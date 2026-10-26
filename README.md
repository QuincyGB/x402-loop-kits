# x402 Loop Kits

Runnable templates for putting [Verdict Row](https://github.com/QuincyGB)'s
x402 services inside a loop that calls them on a schedule — instead of
paying once, by hand, and never coming back. They mirror the discipline
of [verdict-loop](https://github.com/QuincyGB/verdict-loop), the public
reference buyer: honesty header, dry-run default, a daily spend cap
authorized **before** anything is signed, no invented verdicts, fail
loud on malformed payloads.

| Kit | File | Pattern | Paid calls per pass |
|---|---|---|---|
| Monitor | `monitor_loop.py` | Screen a feed + watch your dependencies; alert only on a flip | batch-verdict $0.20 per ≤25 tokens; recheck via pack credits |
| Pre-trade | `pretrade_loop.py` | Gate each intended trade with one combined check | pre-trade $0.05 per trade |
| Inspector | `inspector_loop.py` | Re-check endpoints on a schedule; diff; CRITICAL on money-term changes | recheck pack credits by default; $0.005/call in trial mode |

Shared rails (`loopkit_common.py`): file-backed UTC daily cap
(authorize-before-sign, refused payments are not recorded), pack
low-balance policy (warn ≤25 / ≤10 credits, ≤7 days to expiry; stop at
0/expired; never auto-buy, never fall back to per-call).

## The pack is the default

The inspector and monitor kits spend **StallRow recheck pack credits**
by default. One $1.00 payment to `POST /v1/recheck/pack` buys 250
change-checks on ONE endpoint for 90 days ($0.004/check vs $0.005
per-call). Spend with `pack_id` on `POST /v1/recheck`; read the
balance free at `POST /v1/recheck/pack-balance`. An exhausted pack
returns 402 and an expired pack 410 — neither silently falls back to
per-call billing. Renewal is a new pack purchase; there is no top-up.

## Run the tests / dry-runs ($0, offline, mock transports only)

```bash
python -m pytest test_loop_kits.py -q
# 9 passed (cap, dry-run $0, flip alert, cap-stop, ABORT, caution-skip,
# pack thresholds, exhausted-pack no-fallback, critical-field class)
python monitor_loop.py     # + pretrade_loop.py / inspector_loop.py: dry-run demos
```

## Run the inspector live (pack credits, $0 cash)

A pack id is a prepaid credential, so the inspector's live mode needs
no signer and settles nothing — it spends credits:

```bash
LOOPKIT_PACK_ID=<your pack id> python inspector_loop.py --live
```

First live run of these kits (2026-10-26): one inspector recheck of
Token Verdict `/v1/verdict` against a seeded pack — result and the
before/after pack balance are recorded in the fleet's status page
(link below). The pack was a disclosed seller seed, not a customer
purchase (see Honesty).

## What a real deployment still needs

- **Paid legs:** implement each kit's `*Client` protocol over
  [x402-guard](https://github.com/QuincyGB/x402-guard)'s `GuardedClient`,
  behind `--live` + a signer env var, exactly as verdict-loop does.
  Deliberately omitted so the templates can never spend by accident.
  (x402-guard ≥ 0.1.1 / 0.1.2 can itself spend recheck pack credits for
  its drift checks — config `recheck_pack_id` / `recheckPackId`.)
- A scheduler (cron/systemd) — the kits are single passes by design.
- Alert delivery (file/stdout only here; wire your own channel).
- For the monitor/inspector kits: a recheck pack per watched endpoint
  ($1.00 each).

## Honesty

- Seeds never count as traction. The fleet's external record, kept in
  two buckets that are never merged: **non-Settled external payers —
  19 calls / $0.445 across 4 wallets**; **Settled's scout/inspector —
  35 purchases / $2.625, all delivered**. The Settled number is an
  inspector's test traffic, not organic demand.
- The recheck pack has had **no organic stranger sale yet**. Pack
  purchases on record are the seller's own disclosed seeds plus
  Settled's seller-prompted re-test buy.
- No confirmed third-party loop runs on the fleet yet. These kits are
  the seller's own templates, published so a first one can start.

Fleet status: https://quincyGB.github.io/x402-loop-kits/

## License

MIT
