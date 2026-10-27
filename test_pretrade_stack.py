"""Pre-Trade Stack kit: decision folding rules — flagged hit,
guard verdicts, sanctions anywhere, unsettled receipts, and failed
legs (which must never read as PROCEED). Mock clients only, $0."""

from pretrade_stack import StallRowStackClient, run_stack

PAY = "0x1111111111111111111111111111111111111111"


class Client:
    def __init__(self, feed=None, guard=None, report=None, receipt=None, fail=()):
        self._feed = feed if feed is not None else {"entries": []}
        self._guard = guard or {"verdict": "PROCEED", "risk_score": 3}
        self._report = report or {"pay_to": PAY, "legs": {}}
        self._receipt = receipt or {"settled": True}
        self._fail = set(fail)

    def _maybe(self, name):
        if name in self._fail:
            raise RuntimeError("boom")

    def flagged_paytos(self):
        self._maybe("feed")
        return self._feed

    def pre_trade_guard(self, pay_to, amount=None, resource=None):
        self._maybe("guard")
        return self._guard

    def counterparty_report(self, pay_to, **kw):
        self._maybe("report")
        return self._report

    def receipt_verify(self, tx_hash):
        self._maybe("receipt")
        return self._receipt


def test_clean_stack_proceeds():
    out = run_stack(Client(), pay_to=PAY)
    assert out["decision"] == "PROCEED"
    assert out["stack_cost_usd"] == 0.01
    assert out["legs_run"] == ["flagged_paytos", "pre_trade_guard"]


def test_flagged_hit_aborts():
    feed = {"entries": [{"pay_to": PAY.upper().replace("0X", "0x"), "reasons": ["ofac_sdn"]}]}
    out = run_stack(Client(feed=feed), pay_to=PAY)
    assert out["decision"] == "ABORT"


def test_guard_caution_and_abort_fold():
    assert run_stack(Client(guard={"verdict": "CAUTION", "risk_score": 40}), pay_to=PAY)["decision"] == "CAUTION"
    assert run_stack(Client(guard={"verdict": "ABORT", "risk_score": 90}), pay_to=PAY)["decision"] == "ABORT"


def test_sanctions_in_counterparty_leg_aborts():
    report = {"legs": {"sanctions": {"status": "ok", "result": {"status": "matched", "matched": True}}}}
    out = run_stack(Client(report=report), pay_to=PAY, counterparty=True)
    assert out["decision"] == "ABORT"
    assert out["stack_cost_usd"] == 1.01


def test_unsettled_receipt_and_failed_legs_caution():
    out = run_stack(Client(receipt={"settled": False}), pay_to=PAY, tx_hash="0x" + "1" * 64)
    assert out["decision"] == "CAUTION"
    assert out["stack_cost_usd"] == 0.012
    out = run_stack(Client(fail={"feed"}), pay_to=PAY)
    assert out["decision"] == "CAUTION"
    assert out["legs"]["flagged_paytos"]["status"] == "failed"
    out = run_stack(Client(fail={"guard", "feed", "report"}), pay_to=PAY, counterparty=True)
    assert out["decision"] == "CAUTION"  # total failure is never PROCEED


def test_stallrow_stack_client_paths():
    calls = []

    def call(path, payload):
        calls.append((path, payload))
        return {"ok": True}

    c = StallRowStackClient(call)
    c.flagged_paytos()
    c.pre_trade_guard(PAY, amount=20000)
    c.counterparty_report(PAY, service_url="https://x.example")
    c.receipt_verify("0x" + "2" * 64)
    assert [p for p, _ in calls] == [
        "/v1/flagged-paytos",
        "/v1/pre-trade-guard",
        "/v1/counterparty-report",
        "/v1/receipt-verify",
    ]
    assert calls[1][1]["amount"] == 20000
