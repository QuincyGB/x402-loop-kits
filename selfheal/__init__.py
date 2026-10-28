"""selfheal — the reference receiver for fleet-health nudges.

Implements the self-heal contract (../self-heal.md): verify the
knock, re-probe the claim yourself, consult the owner's policy,
run an allowed playbook or produce a structured escalation, and
log everything. A nudge is evidence, never an order.

Modules:
  signing   — the nudge canonical form + EIP-191 verification
              (identical to the sender engine's and the inbox's;
              the spec's worked vector pins all three).
  probing   — unpaid declared-vs-live route probes + discovery
              reads, transport injected.
  listings  — catalogue listing reads (CDP merchant read, PayAI
              listing-status), tri-state: listed/absent/unknown.
  policy    — the owner's policy file (caps default to 0).
  history   — settlement registry + receiver state (pending lapse
              readings, processed knocks).
  adapter   — consumes severity/impact/action when a knock carries
              them, derives equivalents when it does not.
  playbooks — catalogue-reseed (the one spending playbook) and the
              escalation builder for everything else.
  receiver  — the duties pipeline that ties it together.
  inbox     — the owner-read client for a stall's own inbox.

Money discipline: nothing in this package moves funds on its own.
The only spend path runs through an injected Settler, is checked
against the policy caps first, and the shipped default settler is
a dry run.
"""

from .receiver import Receiver  # noqa: F401
from .policy import Policy  # noqa: F401
