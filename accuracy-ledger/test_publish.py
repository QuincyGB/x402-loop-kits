"""Publish automation: the Nov 1 gate (refusal before maturity,
with nothing written), the dry-run accounting, and the maturity
math itself — records mature at exactly ts + 7 days."""

import subprocess
import sys
from datetime import datetime, timezone

import publish


def _run(*extra):
    return subprocess.run(
        [sys.executable, "publish.py", *extra],
        capture_output=True, text=True, cwd=publish.HERE,
    )


def test_maturity_accounting_today():
    acct = publish.maturity_accounting(datetime(2026, 10, 27, tzinfo=timezone.utc))
    assert acct["records"] == 6
    assert acct["mature_7d"] == 0  # nothing matures before Nov 1
    assert acct["first_maturity"] == "2026-11-01"


def test_maturity_accounting_on_nov1():
    acct = publish.maturity_accounting(datetime(2026, 11, 1, tzinfo=timezone.utc))
    # The 2026-10-25 records (x2 by day-precision) mature; accounting
    # counts whatever the ledger holds — assert at least those.
    assert acct["mature_7d"] >= 2


def test_gate_refuses_before_nov1():
    proc = _run("--now", "2026-10-27")
    assert proc.returncode == 2
    assert "REFUSED" in proc.stderr


def test_dry_run_writes_nothing_and_reports():
    import json as _json
    import os

    before = os.path.exists(publish.PUBLIC_OUT) and os.path.getmtime(publish.PUBLIC_OUT)
    proc = _run("--dry-run", "--now", "2026-10-27")
    assert proc.returncode == 0
    out = _json.loads(proc.stdout)
    assert out["mode"] == "dry-run" and out["mature_7d"] == 0
    after = os.path.exists(publish.PUBLIC_OUT) and os.path.getmtime(publish.PUBLIC_OUT)
    assert before == after
