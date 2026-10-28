"""ADAPTER — severity / impact / action.

====================================================================
INTEGRATION NOTE (the one open seam, flagged 2026-10-28): the base
nudge spec (nudge-inbox.md §2) does not yet document `severity`,
`impact`, or `action` fields. The reference sender engine
(fleet-checker/nudge.py) ALREADY emits all three on every knock it
composes. This adapter is written against the engine's emitted
shape, and tolerates their absence:

  present -> taken as the sender's view (logged; the action block
             becomes the escalation's suggested_action)
  absent  -> derived from the base spec fields (severity from the
             defect-class mapping below — the same sets the engine
             uses; the action from check_url + route)

Playbook decisions NEVER depend on this module: severity and the
suggested action inform humans; every spend decision rests on the
receiver's own probe, the §3 evidence bar, and the policy. When
the spec lands the fields, this adapter becomes a thin reader and
nothing else in the receiver changes.
====================================================================
"""

# Same mapping the sender engine stamps by (fleet-checker/nudge.py):
# critical = the defect stops payment entirely; warning = drift.
CRITICAL_CODES = {
    "unreachable",
    "server_error",
    "no_402",
    "unexpected_status",
    "challenge_undecodable",
}
WARNING_CODES = {"amount_mismatch", "payto_mismatch", "listing_lapsed"}


def severity_for(code: str):
    if code in CRITICAL_CODES:
        return "critical"
    if code in WARNING_CODES:
        return "warning"
    return None  # unknown code: do not overclaim a severity


def adapt(message: dict) -> dict:
    """The sender's view of a knock, normalised:
    {severity, impact, action} where action is
    {method, url, body} or None."""
    defect = message.get("defect") or {}
    code = defect.get("code", "")
    severity = message.get("severity") or severity_for(code)
    impact = message.get("impact") if isinstance(message.get("impact"), str) else None

    action = None
    raw = message.get("action")
    if isinstance(raw, dict) and raw.get("url"):
        action = {
            "method": raw.get("method") or "POST",
            "url": raw["url"],
            "body": raw.get("body") or {"resources": [message.get("route")]},
        }
    elif message.get("check_url") and message.get("route"):
        # Base-spec fallback: the check the sender named, aimed at
        # the route the knock is about.
        action = {
            "method": "POST",
            "url": message["check_url"],
            "body": {"resources": [message["route"]]},
        }
    return {"severity": severity, "impact": impact, "action": action}
