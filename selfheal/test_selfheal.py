#!/usr/bin/env python3
"""
test_selfheal.py — the self-heal receiver's discipline, proven
offline with a fake transport and mocked settlement.

Run with the EVM wallet venv python (eth_account lives there):
    ~/.evm-wallet/.venv/bin/python -m pytest selfheal/test_selfheal.py
or plain unittest:
    ~/.evm-wallet/.venv/bin/python -m unittest selfheal.test_selfheal -v
(run from the x402-loop-kits repo root.)

Pinned here:
  * the canonical form + signature match the spec's worked vector;
  * a knock whose signature does not verify is filed, never probed,
    never acted on;
  * a knock whose defect the receiver's own probe cannot reproduce
    is filed, nothing done;
  * the catalogue-lapse evidence bar: ONE absent reading is never
    enough; unknown readings never count; a settlement inside the
    rail's lag window refuses the re-pay outright;
  * per-fix and monthly caps refuse before any settlement, and the
    monthly accounting accumulates from the heal log itself;
  * a cross-rail lapse escalates as flip_required — the receiver
    never touches a facilitator variable;
  * the adapter consumes severity/action when present and derives
    them when absent.
"""

import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from eth_account import Account
from eth_account.messages import encode_defunct

from selfheal import adapter
from selfheal.history import HealLog, ReceiverState, SettlementHistory
from selfheal.listings import ListingChecker
from selfheal.playbooks import DryRunSettler
from selfheal.policy import Policy
from selfheal.receiver import Receiver
from selfheal.signing import canonical_text, verify_message

STALL = "https://stall.example.com"
ROUTE = STALL + "/v1/check"
ROUTE2 = STALL + "/v1/other"
PAYTO = "0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F"
CHECK_URL = "https://stall-row-production.up.railway.app/v1/fleet-check"

SIGNER = Account.from_key("0x" + "44" * 32)

VECTOR_MESSAGE = {
    "kind": "fleet-health-nudge",
    "protocol": "fleet-health/v1",
    "stall": "https://stall.example.com",
    "route": "https://stall.example.com/v1/check",
    "defect": {"code": "amount_mismatch", "expected": "50000", "observed": "70000"},
    "evidence": {
        "probes": [
            {
                "at": "2026-10-27T22:40:00Z",
                "detail": "live challenge amount 70000 != declared 50000",
                "http_status": 402,
            }
        ],
        "source": "fleet-check",
    },
    "first_seen": "2026-10-27T22:40:00Z",
    "check_url": CHECK_URL,
    "sender": "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",
    "signature": "0x8c508f6c1049bd01c50914549b146dff3f87975d4a0c9a046c777145a5e8f0863fde40170075939cb8678f78be02f4834be2fb3ae795441eb3e5b2c2e1aeb8cf1b",
}
VECTOR_CANONICAL = (
    "fleet-health-nudge/v1\n"
    '{"check_url":"https://stall-row-production.up.railway.app/v1/fleet-check",'
    '"defect":{"code":"amount_mismatch","expected":"50000","observed":"70000"},'
    '"evidence":{"probes":[{"at":"2026-10-27T22:40:00Z","detail":"live challenge '
    'amount 70000 != declared 50000","http_status":402}],"source":"fleet-check"},'
    '"first_seen":"2026-10-27T22:40:00Z","kind":"fleet-health-nudge",'
    '"protocol":"fleet-health/v1","route":"https://stall.example.com/v1/check",'
    '"sender":"0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",'
    '"stall":"https://stall.example.com"}'
)


WAKEUP_VECTOR_MESSAGE = {
    **VECTOR_MESSAGE,
    "severity": "warning",
    "impact": "Your route charges 70000 but advertises 50000 (amounts in the asset's smallest units) — routers that verify declared prices will skip or flag it.",
    "action": {
        "summary": "Run the full Fleet Check diagnosis on this route now",
        "method": "POST",
        "url": CHECK_URL,
        "body": {"resources": ["https://stall.example.com/v1/check"]},
        "spec": "https://github.com/QuincyGB/x402-loop-kits/blob/main/nudge-inbox.md",
    },
    "signature": "0x172075899b7ec09b546e6a51bad774b5b896cdec8fb5138d2934a127455f04c278fe7f7d4b0b36f6594727bad81dadc88927721bffd599148b5b52d6fbae3bbf1b",
}
WAKEUP_CANONICAL = (
    "fleet-health-nudge/v1\n"
    '{"action":{"body":{"resources":["https://stall.example.com/v1/check"]},'
    '"method":"POST","spec":"https://github.com/QuincyGB/x402-loop-kits/blob/'
    'main/nudge-inbox.md","summary":"Run the full Fleet Check diagnosis on '
    'this route now","url":"https://stall-row-production.up.railway.app/v1/'
    'fleet-check"},"check_url":"https://stall-row-production.up.railway.app/'
    'v1/fleet-check","defect":{"code":"amount_mismatch","expected":"50000",'
    '"observed":"70000"},"evidence":{"probes":[{"at":"2026-10-27T22:40:00Z",'
    '"detail":"live challenge amount 70000 != declared 50000","http_status":'
    '402}],"source":"fleet-check"},"first_seen":"2026-10-27T22:40:00Z",'
    '"impact":"Your route charges 70000 but advertises 50000 (amounts in the '
    'asset\'s smallest units) — routers that verify declared prices will '
    'skip or flag it.","kind":"fleet-health-nudge","protocol":"fleet-health/'
    'v1","route":"https://stall.example.com/v1/check","sender":"0x19E7E376'
    'E7C213B7E7e7e46cc70A5dD086DAff2A","severity":"warning","stall":"https://'
    'stall.example.com"}'
)


def challenge_headers(amount, payto=PAYTO):
    challenge = {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": str(amount),
                "payTo": payto,
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            }
        ],
    }
    return {
        "payment-required": base64.b64encode(json.dumps(challenge).encode()).decode()
    }


def discovery_doc(price_units="50000", routes=(ROUTE,)):
    return {
        "payTo": PAYTO,
        "resources": [
            {
                "resource": r,
                "method": "POST",
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "amount": price_units,
                        "payTo": PAYTO,
                    }
                ],
            }
            for r in routes
        ],
    }


class FakeHttp:
    """Routes by URL shape; records every call."""

    def __init__(self):
        self.calls = []
        self.discovery = {}  # origin -> doc
        self.probes = {}     # url -> (status, headers, body)
        self.payai = {}      # resource -> (status, body)
        self.cdp = {}        # payTo -> (status, body)

    def __call__(self, method, url, body=None, headers=None, attempts=1):
        self.calls.append((method, url))
        if url.endswith("/.well-known/x402"):
            doc = self.discovery.get(url[: -len("/.well-known/x402")])
            if doc is None:
                return None, {}, "", "no discovery doc"
            return 200, {}, json.dumps(doc), None
        if "facilitator.payai.network/discovery/listing-status" in url:
            resource = unquote(url.split("resource=", 1)[1])
            status, resp = self.payai.get(resource, (404, ""))
            return status, {}, resp, None
        if "api.cdp.coinbase.com" in url:
            payto = unquote(url.split("payTo=", 1)[1])
            status, resp = self.cdp.get(
                payto, (200, json.dumps({"resources": [], "pagination": {"total": 0}}))
            )
            return status, {}, resp, None
        if url in self.probes:
            status, hdrs, resp = self.probes[url]
            return status, hdrs, resp, None
        return None, {}, "", "unrouted"

    def probed(self, url):
        return ("POST", url) in self.calls


class RecordingSettler(DryRunSettler):
    def __init__(self):
        self.calls = []

    def settle(self, stall, route, rail, price_usd):
        self.calls.append((stall, route, rail, price_usd))
        return super().settle(stall, route, rail, price_usd)


class Clock:
    def __init__(self, start="2026-10-28T00:00:00Z"):
        self.t = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )

    def __call__(self):
        return self.t

    def advance(self, hours):
        self.t += timedelta(hours=hours)


def make_knock(defect, evidence=None, route=ROUTE, account=SIGNER, **extra):
    message = {
        "kind": "fleet-health-nudge",
        "protocol": "fleet-health/v1",
        "stall": STALL,
        "route": route,
        "defect": defect,
        "evidence": evidence if evidence is not None else {"probes": [], "source": "test"},
        "first_seen": "2026-10-28T00:00:00Z",
        "check_url": CHECK_URL,
        "sender": account.address,
    }
    message.update(extra)
    sig = account.sign_message(
        encode_defunct(text=canonical_text(message))
    ).signature.hex()
    message["signature"] = sig if sig.startswith("0x") else "0x" + sig
    return message


def lapse_knock(rail="payai", route=ROUTE):
    return make_knock(
        {"code": "listing_lapsed", "expected": "listed", "observed": "absent"},
        evidence={"rail": rail, "listing_checks": [], "source": "test"},
        route=route,
    )


def generous_policy(**overrides):
    data = {
        "allowed_classes": ["listing_lapsed"],
        "per_fix_cap_usd": 5.0,
        "monthly_cap_usd": 5.0,
        "wallet": SIGNER.address,
        "service_rails": {STALL: "payai"},
    }
    data.update(overrides)
    return Policy(data)


class ReceiverCase(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp()
        self.http.discovery[STALL] = discovery_doc()
        self.clock = Clock()
        self.settler = RecordingSettler()
        self.history = SettlementHistory(None)
        self.state = ReceiverState(None)
        self.heal_log = HealLog(None)

    def receiver(self, policy):
        return Receiver(
            policy=policy,
            http=self.http,
            history=self.history,
            state=self.state,
            heal_log=self.heal_log,
            settler=self.settler,
            now_fn=self.clock,
        )


class TestSigning(unittest.TestCase):
    def test_spec_vector_canonical_and_verify(self):
        self.assertEqual(canonical_text(VECTOR_MESSAGE), VECTOR_CANONICAL)
        self.assertTrue(verify_message(VECTOR_MESSAGE))

    def test_wake_up_vector_canonical_and_verify(self):
        # The updated spec's worked vector: the same message WITH
        # severity/impact/action. The receiver's canonical form is
        # field-agnostic and must reproduce it byte-exactly.
        self.assertEqual(canonical_text(WAKEUP_VECTOR_MESSAGE), WAKEUP_CANONICAL)
        self.assertTrue(verify_message(WAKEUP_VECTOR_MESSAGE))

    def test_tampered_message_fails(self):
        forged = json.loads(json.dumps(VECTOR_MESSAGE))
        forged["defect"]["observed"] = "99999"
        self.assertFalse(verify_message(forged))


class TestAdapter(unittest.TestCase):
    def test_engine_fields_consumed(self):
        msg = make_knock(
            {"code": "no_402", "expected": "402", "observed": "200"},
            severity="critical",
            impact="Buyer agents cannot obtain a payment challenge.",
            action={"summary": "x", "method": "POST", "url": CHECK_URL,
                    "body": {"resources": [ROUTE]}, "spec": "s"},
        )
        view = adapter.adapt(msg)
        self.assertEqual(view["severity"], "critical")
        self.assertEqual(view["impact"], "Buyer agents cannot obtain a payment challenge.")
        self.assertEqual(view["action"]["url"], CHECK_URL)

    def test_base_fields_derived(self):
        msg = make_knock({"code": "amount_mismatch", "expected": "1", "observed": "2"})
        view = adapter.adapt(msg)
        self.assertEqual(view["severity"], "warning")
        self.assertIsNone(view["impact"])
        self.assertEqual(view["action"]["body"], {"resources": [ROUTE]})


class TestKnockDuties(ReceiverCase):
    def test_signature_refusal_filed_never_probed(self):
        knock = make_knock({"code": "amount_mismatch", "expected": "50000", "observed": "70000"})
        knock["signature"] = "0x" + "00" * 65  # validly shaped, wrong
        entry = self.receiver(generous_policy()).process_knock(knock, "inbox:test")
        self.assertEqual(entry["decision"], "filed")
        self.assertFalse(entry["signature_ok"])
        self.assertFalse(self.http.probed(ROUTE))
        self.assertEqual(self.settler.calls, [])

    def test_unverified_defect_filed(self):
        # Probe answers a healthy challenge at the declared amount.
        self.http.probes[ROUTE] = (402, challenge_headers("50000"), "")
        knock = make_knock({"code": "amount_mismatch", "expected": "50000", "observed": "70000"})
        entry = self.receiver(generous_policy()).process_knock(knock, "inbox:test")
        self.assertEqual(entry["decision"], "filed")
        self.assertFalse(entry["verified"])
        self.assertEqual(self.settler.calls, [])

    def test_confirmed_route_defect_escalates_with_evidence(self):
        self.http.probes[ROUTE] = (402, challenge_headers("70000"), "")
        knock = make_knock(
            {"code": "amount_mismatch", "expected": "50000", "observed": "70000"},
            severity="warning",
            action={"method": "POST", "url": CHECK_URL, "body": {"resources": [ROUTE]}},
        )
        entry = self.receiver(generous_policy()).process_knock(knock, "inbox:test")
        self.assertEqual(entry["decision"], "escalated")
        self.assertTrue(entry["verified"])
        esc = entry["escalation"]
        self.assertEqual(esc["type"], "no_playbook")
        self.assertEqual(esc["defect"]["observed"], "70000")
        self.assertEqual(esc["suggested_action"]["url"], CHECK_URL)
        self.assertTrue(esc["verified_evidence"])
        self.assertEqual(self.settler.calls, [])

    def test_duplicate_knock_processed_once(self):
        self.http.probes[ROUTE] = (402, challenge_headers("70000"), "")
        knock = make_knock({"code": "amount_mismatch", "expected": "50000", "observed": "70000"})
        receiver = self.receiver(generous_policy())
        first = receiver.process_knock(knock, "inbox:test")
        second = receiver.process_knock(knock, "inbox:test")
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_opt_out_filed_only(self):
        msg = {
            "kind": "fleet-health-opt-out",
            "protocol": "fleet-health/v1",
            "stall": STALL,
            "sender": PAYTO,
            "signature": "0x" + "11" * 65,
        }
        entry = self.receiver(generous_policy()).process_knock(msg, "inbox:test")
        self.assertEqual(entry["decision"], "filed")
        self.assertEqual(self.settler.calls, [])


class TestLapseBar(ReceiverCase):
    def test_first_absent_reading_is_only_pending(self):
        self.http.payai[ROUTE] = (404, "")
        entry = self.receiver(generous_policy()).process_knock(lapse_knock(), "inbox:test")
        self.assertEqual(entry["decision"], "pending")
        self.assertEqual(self.settler.calls, [])

    def test_second_absent_reading_after_gap_settles(self):
        self.http.payai[ROUTE] = (404, "")
        receiver = self.receiver(generous_policy())
        receiver.process_knock(lapse_knock(), "inbox:test")
        self.clock.advance(2)
        summary = receiver.run_cycle()
        acted = [e for e in summary["entries"] if e["decision"] == "acted"]
        self.assertEqual(len(acted), 1)
        self.assertEqual(acted[0]["playbook"], "catalogue-reseed")
        self.assertAlmostEqual(acted[0]["cost_usd"], 0.05)
        self.assertEqual(len(self.settler.calls), 1)
        self.assertTrue(self.history.settlements_for(ROUTE, "payai"))
        self.assertIsNone(self.state.pending(ROUTE, "payai"))

    def test_two_readings_too_close_together_do_not_meet_the_bar(self):
        self.http.payai[ROUTE] = (404, "")
        receiver = self.receiver(generous_policy())
        receiver.process_knock(lapse_knock(), "inbox:test")
        self.clock.advance(0.5)  # less than the 1h minimum gap
        entries = receiver.process_pending()
        self.assertTrue(all(e["decision"] == "pending" for e in entries))
        self.assertEqual(self.settler.calls, [])

    def test_unknown_readings_never_count(self):
        self.http.payai[ROUTE] = (500, "boom")
        receiver = self.receiver(generous_policy())
        entry = receiver.process_knock(lapse_knock(), "inbox:test")
        self.assertEqual(entry["decision"], "pending")
        self.clock.advance(3)
        entries = receiver.process_pending()
        self.assertTrue(all(e["decision"] == "pending" for e in entries))
        self.assertEqual(self.settler.calls, [])
        # Now genuinely absent readings still need their own pair.
        self.http.payai[ROUTE] = (404, "")
        self.clock.advance(2)
        entries = receiver.process_pending()
        self.assertTrue(all(e["decision"] == "pending" for e in entries))
        self.assertEqual(self.settler.calls, [])

    def test_listed_reading_clears_pending(self):
        self.http.payai[ROUTE] = (404, "")
        receiver = self.receiver(generous_policy())
        receiver.process_knock(lapse_knock(), "inbox:test")
        self.http.payai[ROUTE] = (200, json.dumps({"listed": True}))
        self.clock.advance(2)
        entries = receiver.process_pending()
        self.assertEqual(entries[0]["decision"], "filed")
        self.assertIsNone(self.state.pending(ROUTE, "payai"))
        self.assertEqual(self.settler.calls, [])

    def test_settlement_inside_lag_window_refuses_repay(self):
        self.http.payai[ROUTE] = (404, "")
        self.history.record(ROUTE, "payai", "0xdeadbeef", "2026-10-27T23:00:00Z",
                            source="test-seed")
        receiver = self.receiver(generous_policy())
        receiver.process_knock(lapse_knock(), "inbox:test")
        self.clock.advance(2)  # settlement is now 3h old — inside payai's 24h window
        entries = receiver.process_pending()
        refused = [e for e in entries if e["decision"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["escalation"]["type"], "lag_window")
        self.assertEqual(self.settler.calls, [])

    def test_cross_rail_lapse_escalates_flip_required(self):
        self.http.cdp[PAYTO] = (200, json.dumps({"resources": [], "pagination": {"total": 0}}))
        receiver = self.receiver(generous_policy())  # service settles via payai
        receiver.process_knock(lapse_knock(rail="cdp"), "inbox:test")
        self.clock.advance(2)
        entries = receiver.process_pending()
        escalated = [e for e in entries if e["decision"] == "escalated"]
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["escalation"]["type"], "flip_required")
        steps = " ".join(escalated[0]["escalation"]["human_steps"])
        self.assertIn("X402_FACILITATOR_URL", steps)
        self.assertEqual(self.settler.calls, [])


class TestCaps(ReceiverCase):
    def _drive_bar(self, receiver):
        receiver.process_knock(lapse_knock(), "inbox:test")
        self.clock.advance(2)
        return receiver.process_pending()

    def test_per_fix_cap_refusal(self):
        self.http.payai[ROUTE] = (404, "")
        entries = self._drive_bar(self.receiver(generous_policy(per_fix_cap_usd=0.01)))
        refused = [e for e in entries if e["decision"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["escalation"]["type"], "cap_refusal")
        self.assertIn("per-fix cap", refused[0]["reason"])
        self.assertEqual(self.settler.calls, [])

    def test_report_only_caps_refuse(self):
        self.http.payai[ROUTE] = (404, "")
        policy = generous_policy(per_fix_cap_usd=0, monthly_cap_usd=0)
        entries = self._drive_bar(self.receiver(policy))
        refused = [e for e in entries if e["decision"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertIn("report-only", refused[0]["reason"])
        self.assertEqual(self.settler.calls, [])

    def test_monthly_cap_accounting_accumulates_and_blocks(self):
        self.http.discovery[STALL] = discovery_doc(routes=(ROUTE, ROUTE2))
        self.http.payai[ROUTE] = (404, "")
        self.http.payai[ROUTE2] = (404, "")
        policy = generous_policy(monthly_cap_usd=0.07)
        receiver = self.receiver(policy)
        self._drive_bar(receiver)
        self.assertEqual(len(self.settler.calls), 1)  # first fix: $0.05 of $0.07
        # Second route's lapse: bar met on its own pair of readings.
        receiver.process_knock(lapse_knock(route=ROUTE2), "inbox:test")
        self.clock.advance(2)
        entries = receiver.process_pending()
        refused = [e for e in entries if e["decision"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["escalation"]["type"], "cap_refusal")
        self.assertIn("monthly cap", refused[0]["reason"])
        self.assertEqual(len(self.settler.calls), 1)  # still just the one fix


class TestListingChecker(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp()
        self.checker = ListingChecker(self.http)

    def test_payai_states(self):
        self.http.payai[ROUTE] = (404, "")
        self.assertEqual(self.checker.payai_status(ROUTE), "absent")
        self.http.payai[ROUTE] = (200, json.dumps({"listed": False}))
        self.assertEqual(self.checker.payai_status(ROUTE), "absent")
        self.http.payai[ROUTE] = (200, json.dumps({"listed": True}))
        self.assertEqual(self.checker.payai_status(ROUTE), "listed")
        self.http.payai[ROUTE] = (500, "")
        self.assertEqual(self.checker.payai_status(ROUTE), "unknown")

    def test_cdp_states(self):
        self.http.cdp[PAYTO] = (200, json.dumps({"resources": [{"resource": ROUTE}]}))
        self.assertEqual(self.checker.cdp_status(ROUTE, PAYTO), "listed")
        self.assertEqual(self.checker.cdp_status(ROUTE2, PAYTO), "absent")
        self.http.cdp[PAYTO] = (503, "")
        checker2 = ListingChecker(self.http)  # fresh cache
        self.assertEqual(checker2.cdp_status(ROUTE, PAYTO), "unknown")


if __name__ == "__main__":
    unittest.main()
