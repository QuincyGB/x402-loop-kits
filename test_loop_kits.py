"""Offline tests for the loop kits — mock transports only, $0 spent.

Run:  python -m pytest test_loop_kits.py -q   (from this folder)
"""

import json

import pytest

from loopkit_common import DailyCap, SpendCapExceeded, pack_usable, pack_warnings
import monitor_loop as mon
import pretrade_loop as pre
import inspector_loop as insp


# ---------- cap discipline ----------

def test_cap_authorizes_before_signing_and_blocks_overage(tmp_path):
    cap = DailyCap(100_000, tmp_path / "b.json")
    cap.authorize(60_000)
    with pytest.raises(SpendCapExceeded):
        cap.authorize(50_000)  # 60k + 50k > 100k cap
    assert cap.spent_units == 60_000  # refused payment was NOT recorded


def test_dry_runs_plan_but_spend_zero():
    for mod, cfg in (
        (mon, mon.MonitorConfig(tokens=["0x" + "a" * 40])),
        (pre, pre.PreTradeConfig(trades=[pre.TradeIntent("0x" + "a" * 40)])),
        (insp, insp.InspectorConfig(endpoints=[
            {"url": "https://x.example/v1/y", "watch_id": "w", "pack_id": "p"}])),
    ):
        out = mod.run_pass(cfg, None)
        assert out.mode == "DRY-RUN"
        assert out.spent_units == 0
        assert out.planned_units >= 0 and out.lines


# ---------- monitor loop ----------

class StubMonitor:
    def __init__(self, labels):
        self.labels = labels
        self.balance = {"credits_remaining": 20, "credits_total": 250,
                        "expires_at": "2027-01-23T00:00:00Z", "expired": False}

    def batch_verdict(self, addresses):
        return {"results": [{"address": a, "verdict": self.labels[a], "score": 10}
                            for a in addresses], "summary": {}}

    def recheck(self, url, watch_id, pack_id):
        return {"status": "CHANGED", "url": url,
                "changes": [{"field": "amount", "before": "20000", "after": "25000"}]}

    def pack_balance(self, pack_id):
        return self.balance


def test_monitor_alerts_on_flip_and_change(tmp_path):
    addr = "0x" + "b" * 40
    cfg = mon.MonitorConfig(
        tokens=[addr],
        watched_endpoints=[{"url": "https://x.example/v1/y", "watch_id": "w",
                            "pack_id": "pack_1"}],
        state_path=str(tmp_path / "s.json"), budget_state=str(tmp_path / "b.json"))
    stub = StubMonitor({addr: "SOLID"})
    mon.run_pass(cfg, stub, dry_run=False)          # first pass: baseline
    stub.labels[addr] = "DANGER"
    out = mon.run_pass(cfg, stub, dry_run=False)    # second pass: flip
    assert any("FLIP" in a and "DANGER" in a for a in out.alerts)
    assert any("CHANGED" in a for a in out.alerts)
    assert any("Pack low" in a for a in out.alerts)  # 20 credits <= 25 warn
    assert out.spent_units == mon.BATCH_PRICE_UNITS


def test_monitor_stops_at_cap_without_calling(tmp_path):
    addr = "0x" + "c" * 40
    cfg = mon.MonitorConfig(tokens=[addr] * 26,  # 2 chunks = $0.40 planned
                            daily_cap_units=200_000,
                            state_path=str(tmp_path / "s.json"),
                            budget_state=str(tmp_path / "b.json"))
    stub = StubMonitor({addr: "SOLID"})
    out = mon.run_pass(cfg, stub, dry_run=False)
    assert out.spent_units == 200_000  # second chunk blocked pre-signing
    assert any("CAP STOP" in a for a in out.alerts)


# ---------- pre-trade loop ----------

class StubPreTrade:
    def __init__(self, payload):
        self.payload = payload

    def pre_trade(self, token, wallet, spender):
        return self.payload


def test_pretrade_abort_blocks_and_alerts(tmp_path):
    cfg = pre.PreTradeConfig(
        trades=[pre.TradeIntent("0x" + "d" * 40)],
        budget_state=str(tmp_path / "b.json"))
    out = pre.run_pass(cfg, StubPreTrade({"verdict": "ABORT", "worst_leg": "token"}),
                       dry_run=False)
    assert any("ABORT" in a for a in out.alerts)
    assert out.spent_units == pre.PRETRADE_PRICE_UNITS


def test_pretrade_caution_skips_by_default_and_unknown_legs_explained():
    action, reason = pre.decide_pretrade(
        {"verdict": "CAUTION", "worst_leg": "wallet", "unknown_legs": ["wallet"]})
    assert action == "SKIP" and "could not be evaluated" in reason
    with pytest.raises(ValueError):
        pre.decide_pretrade({"nope": 1})  # fail loud, never invent


# ---------- inspector loop + pack warnings ----------

def test_pack_warning_thresholds():
    base = {"credits_total": 250, "expires_at": "2027-01-23T00:00:00Z", "expired": False}
    assert pack_warnings({**base, "credits_remaining": 100}) == []
    assert any("Pack low" in w for w in pack_warnings({**base, "credits_remaining": 25}))
    assert any("PACK LOW" in w for w in pack_warnings({**base, "credits_remaining": 3}))
    assert any("EXHAUSTED" in w for w in pack_warnings({**base, "credits_remaining": 0}))
    assert any("EXPIRED" in w for w in pack_warnings({**base, "credits_remaining": 9,
                                                      "expired": True}))
    assert not pack_usable({**base, "credits_remaining": 0})


class StubInspector:
    def recheck(self, url, watch_id, pack_id):
        return {"status": "CHANGED", "url": url, "changes": [
            {"field": "payTo", "before": "0x1", "after": "0x2"},
            {"field": "description_hash", "before": "a", "after": "b"}]}

    def pack_balance(self, pack_id):
        return {"credits_remaining": 0, "credits_total": 250,
                "expires_at": "2027-01-23T00:00:00Z", "expired": False}


def test_inspector_exhausted_pack_skips_without_fallback(tmp_path):
    cfg = insp.InspectorConfig(
        endpoints=[{"url": "https://x.example/v1/y", "watch_id": "w",
                    "pack_id": "pack_1"}],
        budget_state=str(tmp_path / "b.json"))
    out = insp.run_pass(cfg, StubInspector(), dry_run=False)
    assert out.spent_units == 0                      # no per-call fallback charge
    assert any("no per-call fallback" in line for line in out.lines)


def test_inspector_critical_field_classification():
    status, alerts = insp.classify_changes(
        {"status": "CHANGED", "url": "u", "changes": [
            {"field": "payTo", "before": "0x1", "after": "0x2"}]})
    assert status == "CHANGED" and alerts[0].startswith("CRITICAL")


# --- live pack client (mock transport, $0) -------------------------------------

def test_pack_recheck_client_posts_pack_id():
    httpx = pytest.importorskip("httpx")
    from live_clients import PackRecheckClient

    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        if request.url.path.endswith("/pack-balance"):
            return httpx.Response(200, json={
                "credits_remaining": 249, "credits_total": 250,
                "expires_at": "2027-01-23T00:00:00Z", "expired": False})
        return httpx.Response(200, json={"status": "BASELINE"})

    client = PackRecheckClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    out = client.recheck("https://example.com/v1/x", "w1", "pack_abc")
    assert out["status"] == "BASELINE"
    assert seen["body"]["pack_id"] == "pack_abc"
    bal = client.pack_balance("pack_abc")
    assert bal["credits_remaining"] == 249
    with pytest.raises(ValueError):
        client.recheck("https://example.com/v1/x", "w1", None)


# --- fleet pass live client (mock transport, $0) --------------------------------

def test_fleet_pass_client_sends_header_and_reads_balance():
    httpx = pytest.importorskip("httpx")
    from live_clients import FleetPassClient

    seen = {}

    def handler(request):
        seen.setdefault("headers", []).append(request.headers.get("x-fleet-pass"))
        if request.url.path.endswith("/fleet-pass/balance"):
            return httpx.Response(200, json={
                "pass_id": "fpass_x", "balance_units": 19_900_000,
                "balance_usd": 19.9, "expired": False})
        return httpx.Response(200, json={"summary": {"resources_after": 84441}})

    client = FleetPassClient(
        "fpass_x", http=httpx.Client(transport=httpx.MockTransport(handler)))
    out = client.call("/v1/index/changes", {})
    assert out["summary"]["resources_after"] == 84441
    bal = client.balance()
    assert bal["balance_usd"] == 19.9
    assert seen["headers"] == ["fpass_x", None]  # call carries it; balance names it in body


def test_fleet_pass_client_surfaces_exhaustion_without_fallback():
    httpx = pytest.importorskip("httpx")
    from live_clients import FleetPassClient

    def handler(request):
        return httpx.Response(402, json={"error": "pass balance below price", "code": "pass_insufficient"})

    client = FleetPassClient(
        "fpass_x", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError, match="402"):
        client.call("/v1/index/changes", {})
