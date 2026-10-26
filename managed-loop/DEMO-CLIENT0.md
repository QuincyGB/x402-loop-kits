# Managed Loop — demo output, client #0 (our own fleet)

A real run of `demo_client0.py` on 2026-10-26 (~21:05 UTC) — the
fleet monitoring itself, in exactly the shape a managed client's
weekly report uses. $0.00 cash spent (one pack credit).

## Fleet self-monitoring pass (client #0 demo)

| Service | /health | Detail |
|---|---|---|
| token-verdict | 200 | {"ok":true,"service":"token-verdict"} |
| route-verdict | 200 | {"ok":true,"service":"route-verdict"} |
| list-smith | 200 | {"ok":true,"service":"list-smith"} |
| stall-row | 200 | {"ok":true,"service":"stall-row","routes":14,"storage":{"recheck_store":"persistent", …}} |
| lock-smith | 200 | {"ok":true,"service":"lock-smith"} |

Funded recheck — Token Verdict /v1/verdict: **BASELINE**
(changes: []); pack credits 248 → 247, $0.00 cash.

Notes on this run: the recheck is a BASELINE because the demo uses
its own watch id (`managed-loop-client0`) — the same endpoint under
the Webhook Watch registration (`watch_3b4cc8ecbe77798f`) separately
recorded BASELINE then UNCHANGED earlier the same day, with the
BASELINE event delivered to the test webhook (HTTP 200, payload
verified at the receiver). Client #0 is us; no external client
exists yet and none is claimed.
