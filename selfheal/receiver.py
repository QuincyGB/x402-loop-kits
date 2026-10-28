"""The receiver: the self-heal contract's duties pipeline
(self-heal.md §1), in order, skipping nothing —

  1. verify the knock's signature (a failure is filed, never
     acted on);
  2. re-probe the claim with the receiver's own probes (route
     defects) or its own catalogue reads (listing lapses, under
     the §3 evidence bar);
  3. consult the owner policy;
  4. run the one allowed playbook, or produce a §5 escalation;
  5. log everything to the heal log.

Local findings (the operator's own checker telemetry about its
own stalls) enter at step 2 and follow the same tail. Knocks are
deduped through receiver state, so re-polling an inbox never
double-processes; pending lapse readings persist across cycles,
because the §3 bar can only be met across cycles.
"""

from datetime import datetime, timedelta, timezone

from . import adapter, probing
from .history import HealLog, ReceiverState, SettlementHistory
from .listings import ABSENT, LISTED, UNKNOWN, ListingChecker
from .playbooks import (
    LAPSE_CODE,
    RESEED_PLAYBOOK,
    DryRunSettler,
    SettleRefused,
    build_escalation,
    flip_steps,
)
from .policy import Policy, declared_price_usd
from .signing import dedupe_key, verify_message

OPT_OUT_KIND = "fleet-health-opt-out"
NUDGE_KIND = "fleet-health-nudge"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:  # noqa: BLE001
        return None


class Receiver:
    def __init__(
        self,
        *,
        policy: Policy,
        http,
        listings: ListingChecker | None = None,
        history: SettlementHistory | None = None,
        state: ReceiverState | None = None,
        heal_log: HealLog | None = None,
        settler=None,
        now_fn=None,
    ):
        self.policy = policy
        self.http = http
        self.listings = listings or ListingChecker(http)
        self.history = history or SettlementHistory(None)
        self.state = state or ReceiverState(None)
        self.log = heal_log or HealLog(None)
        self.settler = settler or DryRunSettler()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._docs: dict[str, object] = {}

    # -- plumbing ----------------------------------------------------------

    def _now(self) -> datetime:
        return self.now_fn()

    def _now_iso(self) -> str:
        return _iso(self._now())

    def _discovery(self, stall: str):
        if stall not in self._docs:
            self._docs[stall] = probing.fetch_discovery(stall, self.http)
        return self._docs[stall]

    def _entry(self, event, source, stall, route, defect_code, **kw) -> dict:
        entry = {
            "at": self._now_iso(),
            "event": event,
            "source": source,
            "stall": stall,
            "route": route,
            "defect": defect_code,
            "sender": None,
            "signature_ok": None,
            "verified": None,
            "verification": None,
            "severity": None,
            "playbook": None,
            "decision": "filed",
            "reason": "",
            "cost_usd": 0,
            "receipts": [],
            "escalation": None,
        }
        entry.update(kw)
        return self.log.append(entry)

    # -- the cycle -----------------------------------------------------------

    def run_cycle(self, knocks=(), findings=()) -> dict:
        """One receiver cycle. `knocks` is an iterable of
        (message, source) pairs; `findings` an iterable of
        {"stall": origin, "route": url} local-telemetry pointers.
        Returns a summary with per-decision counts and this cycle's
        heal-log entries."""
        before = len(self.log.entries)
        summary = {
            "acted": 0,
            "refused": 0,
            "escalated": 0,
            "filed": 0,
            "pending": 0,
            "duplicates": 0,
        }
        for message, source in knocks:
            entry = self.process_knock(message, source)
            if entry is None:
                summary["duplicates"] += 1
            else:
                summary[entry["decision"]] = summary.get(entry["decision"], 0) + 1
        for finding in findings:
            entry = self.process_finding(finding)
            if entry is not None:
                summary[entry["decision"]] = summary.get(entry["decision"], 0) + 1
        for entry in self.process_pending():
            summary[entry["decision"]] = summary.get(entry["decision"], 0) + 1
        self.state.save()
        summary["entries"] = self.log.entries[before:]
        return summary

    # -- knocks --------------------------------------------------------------

    def process_knock(self, message, source: str = "inbox"):
        """Process one knock. Returns the heal-log entry, or None
        if this exact knock was already processed in an earlier
        cycle (the inbox is re-polled; the receiver must not
        double-act)."""
        if not isinstance(message, dict):
            return self._entry(
                "knock", source, None, None, None,
                reason="malformed knock (not a JSON object) — filed, never acted on",
            )
        stall = str(message.get("stall") or "").rstrip("/") or None
        route = message.get("route")
        defect = message.get("defect") or {}
        code = defect.get("code") if isinstance(defect, dict) else None
        sender = message.get("sender")
        view = adapter.adapt(message)

        key = None
        try:
            key = dedupe_key(message)
        except Exception:  # noqa: BLE001 — a knock too malformed to key is filed below
            key = None
        if key and self.state.is_processed(key):
            return None

        if message.get("kind") == OPT_OUT_KIND:
            entry = self._entry(
                "knock", source, stall, route, code,
                sender=sender, severity=view["severity"],
                reason="opt-out notice — filed; opt-outs are honoured by the "
                       "sender-side registry, never a playbook trigger",
            )
            if key:
                self.state.mark_processed(key, entry["decision"], self._now_iso())
            return entry
        if message.get("kind") != NUDGE_KIND:
            entry = self._entry(
                "knock", source, stall, route, code,
                sender=sender, severity=view["severity"],
                reason=f"unknown kind {message.get('kind')!r} — filed, never acted on",
            )
            if key:
                self.state.mark_processed(key, entry["decision"], self._now_iso())
            return entry

        # Duty 1 — verify the signature.
        if not verify_message(message):
            entry = self._entry(
                "knock", source, stall, route, code,
                sender=sender, signature_ok=False, severity=view["severity"],
                reason="signature does not verify against the claimed sender — "
                       "filed, never acted on",
            )
            if key:
                self.state.mark_processed(key, entry["decision"], self._now_iso())
            return entry

        # Duties 2–5 dispatch on the defect class.
        if not stall or not route:
            entry = self._entry(
                "knock", source, stall, route, code,
                sender=sender, signature_ok=True, severity=view["severity"],
                reason="knock carries no usable stall/route — filed, never acted on",
            )
            if key:
                self.state.mark_processed(key, entry["decision"], self._now_iso())
            return entry
        if code == LAPSE_CODE:
            evidence = message.get("evidence")
            rail = evidence.get("rail") if isinstance(evidence, dict) else None
            entry = self._lapse_pass(
                stall, route, rail,
                event="knock", source=source, view=view, sender=sender,
                signature_ok=True, claimed_defect=defect,
            )
        else:
            entry = self._route_defect_pass(
                stall, route, defect,
                event="knock", source=source, view=view, sender=sender,
                signature_ok=True,
            )
        if key:
            self.state.mark_processed(key, entry["decision"], self._now_iso())
        return entry

    # -- local findings --------------------------------------------------------

    def process_finding(self, finding: dict):
        """A local-telemetry pointer (the operator's own checker
        says this route of ours looks wrong). Enters at duty 2 —
        there is no signature; the pointer only selects what to
        re-probe, and the probe decides."""
        stall = str(finding.get("stall") or "").rstrip("/")
        route = finding.get("route")
        if not stall or not route:
            return None
        return self._route_defect_pass(
            stall, route, None,
            event="local_finding", source="local", view=None, sender=None,
            signature_ok=None,
        )

    # -- duty 2–5 for route defects ---------------------------------------------

    def _route_defect_pass(self, stall, route, claimed_defect, *, event, source,
                           view, sender, signature_ok):
        view = view or {"severity": None, "impact": None, "action": None}
        doc = self._discovery(stall) if stall else None
        declared = probing.declared_entry(doc, route) if doc else None
        defect, probe = probing.probe_route(route, declared, self.http, self._now_iso())
        claimed_code = (claimed_defect or {}).get("code")
        base = dict(
            sender=sender, signature_ok=signature_ok,
            verification={"probe": probe, "own_defect": defect},
        )
        if defect is None:
            return self._entry(
                event, source, stall, route, claimed_code, **base,
                severity=view["severity"], verified=False,
                reason="own probe finds the route healthy — the claim does not "
                       "reproduce; filed, nothing done",
            )
        if claimed_code is not None and defect["code"] != claimed_code:
            return self._entry(
                event, source, stall, route, claimed_code, **base,
                severity=view["severity"], verified=False,
                reason=f"own probe finds {defect['code']}, not the claimed "
                       f"{claimed_code} — a different breakage is not "
                       "confirmation; filed, nothing done",
            )
        # Confirmed. V1 has no playbook for route defects — the
        # output is the escalation record (self-heal.md §4b).
        if view["severity"] is None:
            view = {**view, "severity": adapter.severity_for(defect["code"])}
        escalation = build_escalation(
            "no_playbook",
            stall=stall, route=route, defect=defect, evidence=[probe],
            view=view, at=self._now_iso(),
            human_steps=[
                "Diagnose the route from the verified evidence; the "
                "suggested action runs the full Fleet Check diagnosis on it."
            ],
        )
        return self._entry(
            event, source, stall, route, defect["code"], **base,
            severity=view["severity"], verified=True, escalation=escalation,
            decision="escalated",
            reason=f"defect {defect['code']} confirmed by own probe; no v1 "
                   "playbook covers route defects — escalated with evidence",
        )

    # -- duty 2–5 for catalogue lapses -------------------------------------------

    def process_pending(self) -> list[dict]:
        """Advance every banked lapse: one fresh catalogue reading
        per pending route+rail, then the same evaluation the knock
        path runs."""
        entries = []
        for item in self.state.pending_items():
            entries.append(
                self._lapse_pass(
                    item["stall"], item["route"], item["rail"],
                    event="pending_advance", source="pending", view=None,
                    sender=None, signature_ok=None, claimed_defect=None,
                )
            )
        return entries

    def _lapse_pass(self, stall, route, rail, *, event, source, view, sender,
                    signature_ok, claimed_defect):
        view = view or {"severity": "warning", "impact": None, "action": None}
        base = dict(sender=sender, signature_ok=signature_ok,
                    severity=view["severity"], playbook=RESEED_PLAYBOOK)
        if rail not in ("cdp", "payai"):
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                reason="listing_lapsed claim carries no usable rail in its "
                       "evidence — cannot re-verify; filed, never acted on",
            )
        doc = self._discovery(stall) if stall else None
        pay_to = (doc or {}).get("payTo") or ""
        result = self.listings.status(rail, route, pay_to)
        now = self._now()
        verification = {"rail": rail, "listing_read": result, "at": self._now_iso()}

        if result == LISTED:
            self.state.close_pending(route, rail)
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                verified=False, verification=verification, decision="filed",
                reason=f"own catalogue read: the route IS listed on {rail} — "
                       "lapse not confirmed; any banked readings are cleared",
            )
        if result == UNKNOWN:
            self.state.bank_check(stall, route, rail, self._now_iso(), UNKNOWN)
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                verified=None, verification=verification, decision="pending",
                reason="catalogue lookup failed (unknown) — unknown is not "
                       "evidence; it neither advances nor resets the §3 bar",
            )

        # ABSENT — bank the reading and test the bar.
        pending = self.state.bank_check(stall, route, rail, self._now_iso(), ABSENT)
        absent = [c for c in pending["checks"] if c["result"] == ABSENT]
        verification["absent_readings"] = [c["at"] for c in absent]
        gap = timedelta(hours=self.policy.listing_min_check_gap_hours)
        bar_met = False
        if len(absent) >= 2:
            first = _parse_iso(absent[0]["at"])
            last = _parse_iso(absent[-1]["at"])
            bar_met = bool(first and last and (last - first) >= gap)
        if not bar_met:
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                verified=None, verification=verification, decision="pending",
                reason=f"absent reading banked ({len(absent)} so far); the §3 "
                       f"bar needs two absent readings at least "
                       f"{self.policy.listing_min_check_gap_hours}h apart",
            )

        # The bar is met: the lapse is verified. Guards, in order.
        defect = {"code": LAPSE_CODE, "expected": "listed", "observed": "absent"}

        def refused(etype, reason):
            escalation = build_escalation(
                etype, stall=stall, route=route, defect=defect,
                evidence=[verification], view=view, at=self._now_iso(),
            )
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                verified=True, verification=verification, decision="refused",
                reason=reason, escalation=escalation,
            )

        window_h = self.policy.lag_window_hours(rail)
        since = _iso(now - timedelta(hours=window_h))
        hit = self.history.latest_within(route, rail, since)
        if hit:
            return refused(
                "lag_window",
                f"settlement {hit.get('tx')} at {hit.get('at')} for this route "
                f"on {rail} is inside the {window_h}h lag window — the absence "
                "is presumed indexing lag, not lapse; re-pay refused",
            )
        if not self.policy.allows(LAPSE_CODE):
            return refused(
                "policy_refusal",
                "listing_lapsed is not in the policy's allowed_classes — "
                "the owner has not authorised auto re-seeds",
            )
        declared = probing.declared_entry(doc, route) if doc else None
        price = declared_price_usd(declared)
        if price is None:
            return refused(
                "evidence_unmet",
                "the route's declared Base price cannot be determined — an "
                "unpriceable fix is never bought",
            )
        if price > self.policy.per_fix_cap_usd:
            note = " (policy is report-only: caps are 0)" if self.policy.report_only else ""
            return refused(
                "cap_refusal",
                f"route price ${price:.2f} exceeds the per-fix cap "
                f"${self.policy.per_fix_cap_usd:.2f}{note}",
            )
        month = now.strftime("%Y-%m")
        spent = self.log.spend_in_month(month)
        if spent + price > self.policy.monthly_cap_usd:
            return refused(
                "cap_refusal",
                f"monthly spend ${spent:.2f} + this fix ${price:.2f} would "
                f"exceed the monthly cap ${self.policy.monthly_cap_usd:.2f}",
            )
        current = self.policy.current_rail(stall)
        if current != rail:
            escalation = build_escalation(
                "flip_required",
                stall=stall, route=route, defect=defect,
                evidence=[verification], view=view, at=self._now_iso(),
                human_steps=flip_steps(stall, route, rail),
            )
            return self._entry(
                event, source, stall, route, LAPSE_CODE, **base,
                verified=True, verification=verification, decision="escalated",
                reason=f"lapse verified on {rail}, but the service currently "
                       f"settles through {current!r} — re-admission on {rail} "
                       "needs a facilitator flip, an environment change this "
                       "receiver never performs; escalated with the flip steps",
                escalation=escalation,
            )
        try:
            receipt = self.settler.settle(stall, route, rail, price)
        except SettleRefused as refusal_exc:
            return refused(refusal_exc.etype, f"settler refused: {refusal_exc.reason}")
        receipt = dict(receipt or {})
        receipt.setdefault("rail", rail)
        receipt.setdefault("at", self._now_iso())
        cost = float(receipt.get("cost_usd", price))
        self.history.record(route, rail, str(receipt.get("tx", "")), receipt["at"],
                            source="selfheal-reseed")
        self.state.close_pending(route, rail)
        return self._entry(
            event, source, stall, route, LAPSE_CODE, **base,
            verified=True, verification=verification, decision="acted",
            cost_usd=cost,
            receipts=[{"rail": rail, "tx": receipt.get("tx"), "at": receipt["at"]}],
            reason=f"lapse confirmed under the §3 bar (two absent readings, no "
                   f"settlement inside the {window_h}h lag window); re-seeded "
                   f"with one genuine call at ${price:.2f} through {rail}"
                   + (" [dry-run settler — simulated receipt, no funds moved]"
                      if receipt.get("dry_run") else ""),
        )
