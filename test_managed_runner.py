"""Managed Loop runner: pass/report/alert behaviour with mock
recheckers — CHANGED endpoints alert (payTo = CRITICAL), failures
are reported per-endpoint, dry-run reports are labelled, and a
funding failure never reads as success."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "managed_runner", os.path.join(os.path.dirname(__file__), "managed-loop", "runner.py")
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

URL1 = "https://a.example.com/v1/verdict"
URL2 = "https://b.example.com/v1/check"
CONFIG = {
    "client": "Example Stall Co",
    "tier": "Row",
    "webhook_url": "https://93.184.216.35/hook",
    "endpoints": [
        {"url": URL1, "watch_id": "w1", "funding": {"kind": "pack", "pack_id": "pack_1"}},
        {"url": URL2, "watch_id": "w2", "funding": {"kind": "fleet_pass", "pass_id": "fpass_1"}},
    ],
}


class Rechecker:
    def __init__(self, results):
        self._results = results

    def recheck(self, endpoint):
        out = self._results[endpoint["url"]]
        if isinstance(out, Exception):
            raise out
        return out

    def balance(self, endpoint):
        if endpoint["funding"]["kind"] == "pack":
            return {"credits_remaining": 248, "credits_total": 250}
        return {"balance_usd": 19.9, "balance_units": 19_900_000}


def test_pass_report_and_critical_alert():
    results = {
        URL1: {"status": "CHANGED", "changes": [
            {"field": "payTo", "before": "0x1", "after": "0x2"},
            {"field": "description_hash", "before": "a", "after": "b"}]},
        URL2: {"status": "UNCHANGED", "changes": []},
    }
    pushed = []
    report, summary = runner.run_pass(CONFIG, Rechecker(results), deliver=pushed.append)
    assert summary["changed"] == 1 and summary["critical"] == 1 and summary["alerts"] == 1
    assert pushed[0]["event"] == "managed_loop_alert"
    assert pushed[0]["alerts"][0].startswith("CRITICAL payTo")
    assert "248 pack credits" in report and "$19.90 pass balance" in report
    assert URL1 in report and URL2 in report


def test_failed_endpoint_reported_not_silent():
    results = {URL1: RuntimeError("pack exhausted"), URL2: {"status": "BASELINE", "changes": []}}
    report, summary = runner.run_pass(CONFIG, Rechecker(results))
    assert summary["failed"] == 1 and summary["alerts"] == 0
    assert "FAILED" in report


def test_dry_run_is_labelled():
    report, summary = runner.run_pass(CONFIG, runner.DryRunRechecker())
    assert summary["dry_run"] is True
    assert "DRY RUN" in report
    assert summary["changed"] == 0
