"""Badge v2 evaluator: TRACKING before maturity, PASS only when
mature outcomes are published with their accounting, NOT_APPLICABLE
for services with no scored route."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "evaluate_v2", os.path.join(os.path.dirname(__file__), "evaluate_v2.py")
)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def _snapshot(status, mature7, hit_rate=None):
    return {
        "generated_at": "2026-10-27T00:00:00Z",
        "status": status,
        "coverage": {"records": 6},
        "horizons": {"7": {"records_mature": mature7, "hit_rate": hit_rate, "hit_rate_n": mature7},
                     "30": {"records_mature": 0}},
    }


def test_tracking_before_maturity():
    out = ev.evaluate(_snapshot("tracking_started_no_mature_records", 0), "2026-10-27")
    assert out["services"]["token-verdict"]["v2_status"].startswith("TRACKING")
    assert out["services"]["stall-row"]["v2_status"].startswith("NOT_APPLICABLE")


def test_pass_when_outcomes_published():
    out = ev.evaluate(_snapshot("scored", 5, hit_rate=0.8), "2026-11-02")
    assert out["services"]["token-verdict"]["v2_status"].startswith("PASS")


def test_no_fake_pass_without_hit_rate_or_records():
    out = ev.evaluate(_snapshot("scored", 0), "2026-11-02")
    assert not out["services"]["token-verdict"]["v2_status"].startswith("PASS")
