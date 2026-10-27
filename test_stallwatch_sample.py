"""Stall Watch sample generator: crafted-snapshot tests for the
event math, the selector, and the counts-only honesty label, plus a
smoke run over the two real stored Index snapshots (2026-10-26)."""

import json
import os

from stallwatch_sample import build_sample, load_snapshot, render_markdown

RES = "https://a.example.com/v1/verdict"
RES2 = "https://a.example.com/v1/check"
PAY = "0x1111111111111111111111111111111111111111"


def _row(resource, amount="20000", pay_to=PAY, name="A Stall", calls=100):
    return {
        "resource": resource,
        "serviceName": name,
        "description": "d",
        "amount": amount,
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "network": "eip155:8453",
        "payTo": pay_to,
        "calls30d": calls,
        "payers30d": 3,
    }


def test_observed_price_change_and_removal():
    before = {RES: _row(RES), RES2: _row(RES2)}
    after = {RES: _row(RES, amount="25000")}
    s = build_sample(before, after, service_name="A Stall")
    assert s["observation_level"] == "observed_changes"
    kinds = {(e["resource"], e["kind"]) for e in s["events"]}
    assert (RES, "field_changed") in kinds and (RES2, "removed") in kinds
    assert s["target"]["resources_before"] == 2
    assert s["target"]["resources_after"] == 1


def test_counts_only_when_nothing_changed():
    rows = {RES: _row(RES)}
    s = build_sample(rows, dict(rows), origin="a.example.com")
    assert s["observation_level"] == "counts_only"
    assert s["events"] == []
    md = render_markdown(s, before_label="b", after_label="a")
    assert "Counts-only sample" in md


def test_selector_isolates_the_stall():
    before = {RES: _row(RES), RES2: _row(RES2, name="Other", pay_to="0x2222222222222222222222222222222222222222")}
    after = {RES: _row(RES, amount="1"), RES2: _row(RES2, name="Other", amount="1", pay_to="0x2222222222222222222222222222222222222222")}
    s = build_sample(before, after, pay_to=PAY)
    assert {e["resource"] for e in s["events"]} == {RES}


def test_real_snapshots_smoke():
    base = os.path.expanduser(
        "~/workspace/goals/x402-fleet-integration-into-repeat-monitoring-loops"
        "/hidden_files/new-ideas-2026-10-26"
    )
    p1, p2 = f"{base}/cdp-baseline-2026-10-26.jsonl", f"{base}/cdp-snapshot2-2026-10-26.jsonl"
    if not (os.path.exists(p1) and os.path.exists(p2)):
        return  # snapshot fixtures not present in this checkout
    before, after = load_snapshot(p1), load_snapshot(p2)
    assert len(before) > 70_000 and len(after) > 70_000
    s = build_sample(before, after, service_name="Pocket Network")
    assert s["target"]["resources_before"] > 50  # a real, large stall
    assert s["catalogue"]["resources_before"] == len(before)
    md = render_markdown(s, before_label="baseline", after_label="snapshot2")
    assert "Stall Watch sample" in md
    if s["observation_level"] == "counts_only":
        assert "Counts-only sample" in md
