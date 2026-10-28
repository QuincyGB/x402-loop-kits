"""Persistence for the receiver: the settlement registry (the
lag-window guard's memory) and the receiver state (processed
knocks, banked lapse readings). Both are plain files the operator
owns — JSONL for the registry, one JSON document for the state.
"""

import json
from pathlib import Path


class SettlementHistory:
    """Every settlement the operator knows about for a route+rail:
    the receiver's own past re-seeds plus whatever registry the
    operator feeds it (the fleet runner imports the fleet's seed
    receipts). Append-only JSONL: {route, rail, tx, at, source}.
    """

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.records: list[dict] = []
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("route") and rec.get("rail"):
                    self.records.append(rec)

    def settlements_for(self, route: str, rail: str) -> list[dict]:
        return [
            r
            for r in self.records
            if r.get("route") == route and r.get("rail") == rail
        ]

    def latest_within(self, route: str, rail: str, since_iso: str):
        """The most recent settlement at or after `since_iso`
        (ISO strings compare lexicographically), or None."""
        hits = [
            r
            for r in self.settlements_for(route, rail)
            if str(r.get("at", "")) >= since_iso
        ]
        if not hits:
            return None
        return max(hits, key=lambda r: str(r.get("at", "")))

    def record(self, route: str, rail: str, tx: str, at: str, source: str) -> dict:
        rec = {"route": route, "rail": rail, "tx": tx, "at": at, "source": source}
        if any(
            r.get("route") == route and r.get("rail") == rail and r.get("tx") == tx
            for r in self.records
        ):
            return rec  # already known — the registry is a set, not a diary
        self.records.append(rec)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec


class ReceiverState:
    """{processed: {dedupe_key: {decision, at}},
        pending_lapses: {"<route>|<rail>": {route, rail, stall,
            checks: [{at, result}], first_absent_at}}}
    Persisted by save() after each cycle."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.data = {"processed": {}, "pending_lapses": {}}
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text())
                if isinstance(loaded, dict):
                    self.data["processed"] = loaded.get("processed") or {}
                    self.data["pending_lapses"] = loaded.get("pending_lapses") or {}
            except ValueError:
                pass

    # -- processed knocks -------------------------------------------------
    def is_processed(self, key: str) -> bool:
        return key in self.data["processed"]

    def mark_processed(self, key: str, decision: str, at: str) -> None:
        self.data["processed"][key] = {"decision": decision, "at": at}

    # -- pending lapse readings -------------------------------------------
    def pending(self, route: str, rail: str):
        return self.data["pending_lapses"].get(f"{route}|{rail}")

    def bank_check(self, stall: str, route: str, rail: str, at: str, result: str):
        key = f"{route}|{rail}"
        entry = self.data["pending_lapses"].get(key)
        if entry is None:
            entry = {
                "stall": stall,
                "route": route,
                "rail": rail,
                "checks": [],
                "first_absent_at": None,
            }
            self.data["pending_lapses"][key] = entry
        entry["checks"].append({"at": at, "result": result})
        if result == "absent" and entry["first_absent_at"] is None:
            entry["first_absent_at"] = at
        return entry

    def close_pending(self, route: str, rail: str) -> None:
        self.data["pending_lapses"].pop(f"{route}|{rail}", None)

    def pending_items(self) -> list[dict]:
        return list(self.data["pending_lapses"].values())

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True))


class HealLog:
    """The append-only JSONL heal log (self-heal.md §6) — and the
    spend ledger: monthly spend is summed from its own paid
    actions, so the log and the accounting can never disagree."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.entries: list[dict] = []

    def append(self, entry: dict) -> dict:
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def spend_in_month(self, yyyymm: str) -> float:
        total = 0.0
        sources = list(self.entries)
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    sources.append(json.loads(line))
                except ValueError:
                    continue
        seen = set()
        for entry in sources:
            if not isinstance(entry, dict):
                continue
            marker = json.dumps(entry, sort_keys=True)
            if marker in seen:
                continue  # in-memory copies of lines already on disk
            seen.add(marker)
            if entry.get("decision") == "acted" and str(entry.get("at", "")).startswith(yyyymm):
                try:
                    total += float(entry.get("cost_usd") or 0)
                except (TypeError, ValueError):
                    continue
        return round(total, 6)
