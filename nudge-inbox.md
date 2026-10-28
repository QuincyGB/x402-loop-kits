# The Fleet-Health Nudge Inbox — an open convention

**Protocol:** `fleet-health/v1` · **Status:** live on StallRow since 2026-10-27 ·
**Reference implementation:** `app/services/nudge.py` in
[QuincyGB/stall-row](https://github.com/QuincyGB/stall-row)

Everything else in x402 is pull: a stall waits to be called, and a
broken stall that never asks for a check never gets one. A **nudge**
is the other direction — a signed knock on a stall's own door:

> *This route of yours is broken in this specific way. Here is the
> probe evidence. Here is the check that found it.*

Any stall can publish an inbox, any checker can knock, and the
stall's owner decides what a knock is worth. No accounts, no
payment: inbound mail is not a product.

## 1. Publishing an inbox

Add one top-level extension to your `/.well-known/x402` document
(it is an extension, **not** a resource — it must not change your
priced route count):

```json
{
  "extensions": {
    "nudge": {
      "endpoint": "https://your-stall.example.com/v1/nudge",
      "accepts": ["fleet-health/v1"],
      "spec": "https://github.com/QuincyGB/x402-loop-kits/blob/main/nudge-inbox.md"
    }
  }
}
```

The endpoint accepts `POST` with a JSON body (§2). Publishing the
extension is the entire integration — and the entire consent: an
origin that publishes no inbox is never nudged by a conforming
sender.

## 2. The nudge message

```json
{
  "kind": "fleet-health-nudge",
  "protocol": "fleet-health/v1",
  "stall": "https://stall.example.com",
  "route": "https://stall.example.com/v1/check",
  "defect": {
    "code": "amount_mismatch",
    "expected": "50000",
    "observed": "70000"
  },
  "evidence": {
    "probes": [
      {
        "at": "2026-10-27T22:40:00Z",
        "http_status": 402,
        "detail": "live challenge amount 70000 != declared 50000"
      }
    ],
    "source": "fleet-check"
  },
  "first_seen": "2026-10-27T22:40:00Z",
  "check_url": "https://stall-row-production.up.railway.app/v1/fleet-check",
  "sender": "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",
  "signature": "0x8c508f…"
}
```

| Field | Meaning |
|---|---|
| `kind` | `fleet-health-nudge` (or `fleet-health-opt-out`, §4) |
| `protocol` | `fleet-health/v1` |
| `stall` | The origin the nudge is about (scheme + host, no path) |
| `route` | The full resource URL, under `stall` |
| `defect.code` | Machine-readable defect class (§5) |
| `defect.expected` / `defect.observed` | What the stall's own sources promise vs what the probe met. Strings or integers; amounts in the asset's smallest units, as strings |
| `evidence` | Probe records: timestamps, HTTP statuses, details. The receiver should be able to re-run the probe and land on the same facts |
| `first_seen` | ISO-8601 time the sender first observed the defect |
| `check_url` | Where the receiver can buy or run the full check |
| `sender` | The sender's wallet address |
| `signature` | EIP-191 `personal_sign` over the canonical form (§3) |

Receivers answer `200 {"ok": true, "stored": true|false,
"duplicate": bool}`. A re-send of an identical
`(sender, route, defect.code, first_seen)` is a duplicate, not a
second entry.

## 3. The signature — canonical form

The signature proves who knocked and that the evidence was not
altered in transit. To sign:

1. Take the message object **without** the `signature` field.
2. Serialize it as canonical JSON: keys sorted (recursively), no
   insignificant whitespace (`","` / `":"` separators), UTF-8,
   non-ASCII characters unescaped.
3. Prefix the protocol line: `fleet-health-nudge/v1\n` + the JSON.
4. Sign that text with EIP-191 `personal_sign` from the `sender`
   wallet.

To verify: rebuild the same text from the received message,
recover the signer, and compare with `sender` (case-insensitive).

### Worked example (test vector)

Throwaway key `0x1111…1111` (never a real wallet) signs the message
in §2. The canonical text is exactly:

```
fleet-health-nudge/v1
{"check_url":"https://stall-row-production.up.railway.app/v1/fleet-check","defect":{"code":"amount_mismatch","expected":"50000","observed":"70000"},"evidence":{"probes":[{"at":"2026-10-27T22:40:00Z","detail":"live challenge amount 70000 != declared 50000","http_status":402}],"source":"fleet-check"},"first_seen":"2026-10-27T22:40:00Z","kind":"fleet-health-nudge","protocol":"fleet-health/v1","route":"https://stall.example.com/v1/check","sender":"0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A","stall":"https://stall.example.com"}
```

Signature (recovers to `0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A`):

```
0x8c508f6c1049bd01c50914549b146dff3f87975d4a0c9a046c777145a5e8f0863fde40170075939cb8678f78be02f4834be2fb3ae795441eb3e5b2c2e1aeb8cf1b
```

Both reference test suites (StallRow's and the sender engine's) pin
this vector, so independent implementations cannot drift apart.

## 4. Opting out

A stall stops nudges by POSTing, to the **sender's** inbox (the
inbox of whoever has been nudging it), a message of the same shape
with `kind: "fleet-health-opt-out"`, the `stall` it speaks for, and
`sender` + `signature` from **the wallet that stall's own discovery
doc publishes as `payTo`**:

```json
{
  "kind": "fleet-health-opt-out",
  "protocol": "fleet-health/v1",
  "stall": "https://stall.example.com",
  "sender": "0x…the stall's payTo…",
  "signature": "0x…"
}
```

Control of the payTo is control of the stall's mail: an opt-out
signed by anyone else is refused. A conforming sender checks the
opt-out registry **before every send** and never nudges an opted-
out stall again. Opt-outs are not rate-limited — leaving is a
right, not mail.

## 5. Defect classes

The classes the reference checker (Fleet Check) emits; senders may
add their own, receivers should treat unknown codes as opaque:

| Code | Meaning |
|---|---|
| `amount_mismatch` | Live challenge amount ≠ the amount the stall's own discovery doc declares |
| `payto_mismatch` | Live challenge payTo ≠ the declared payTo |
| `unreachable` | No HTTP response could be had at all |
| `server_error` | The route answers 5xx to an unpaid probe |
| `no_402` | The route answers 200 unpaid — no payment gate |
| `unexpected_status` | The route answers a non-402, non-5xx status |
| `challenge_undecodable` | 402 answered, but the challenge does not parse or carries no accepts |

## 6. Sender discipline (normative)

A nudge is a knock, not a battering ram. Conforming senders:

- **One nudge per (stall, route, defect) per incident.** An
  incident ends when a later probe shows the route healthy again.
- **Honour opt-outs before every send**, including opt-outs
  learned since the last send.
- **Cap the volume** — the reference engine sends at most 10
  nudges per day, total.
- **Only knock where an inbox is published** (§1 is the consent).
- **Carry evidence, not vibes** — every claim in a nudge must be
  reproducible from the probe records it carries.
- **Sign everything.** An unsigned knock is indistinguishable from
  spam and should be refused as such.

Receivers, for their part, verify the signature, rate-limit per
sender (the reference inbox allows 30 verified knocks per sender
per hour), dedupe (§2), and answer malformed or forged mail with a
clean 4xx — never a 5xx.

## 7. Status of this convention

Live, and deliberately small. StallRow's inbox is open (see its
discovery doc) and the reference engine dogfoods the full loop on
the fleet's own stalls. Outbound nudges to *other* stalls were
enabled by the operator's explicit order on 2026-10-27: the
reference sender now patrols the public catalogue in rotating
slices and knocks only on stalls that publish an inbox, only for
defects it has re-verified with its own probes. The engine's code
default still ships off — the patrol is the armed runtime, and
arming it remains the operator's explicit, separate decision.
