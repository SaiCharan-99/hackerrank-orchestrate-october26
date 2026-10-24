"""SQLite snapshot parser: inventory tables and primary/replica record_json topologies."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .base import COLLECTION_CATEGORY, SYSTEM_FOR_CATEGORY,EvidenceRow, absorb, as_bool, clean, make_row, parse_time

TOPOLOGY_RE = re.compile(r"_(primary|failover_replica|reporting_replica|read_replica|replica_[a-z_]+)$")
HEADER_TIME_RE = re.compile(r"Captured at:\s*(\S+)")


def _topology(table: str) -> tuple[str, str]:
    """(base table name, topology) — inventory tables have topology 'inventory'."""
    m = TOPOLOGY_RE.search(table)
    if not m:
        return table, "inventory"
    topo = m.group(1)
    if topo.startswith("replica_"):
        topo = "regional_" + topo[len("replica_"):]
    return table[: m.start()], topo


def _apply_state(row: EvidenceRow, rec: dict) -> None:
    f = row.flags
    if "enabled" in rec:
        f["enabled"] = as_bool(rec["enabled"])
    if "restore_allowed" in rec:
        f["restore_allowed"] = as_bool(rec["restore_allowed"])
    if "download_available" in rec:
        f["download_available"] = as_bool(rec["download_available"])
    if clean(rec.get("account_status")):
        f["account_status"] = rec["account_status"]
    for key in ("message_text", "message_excerpt"):
        if "[REDACTED]" in str(rec.get(key) or ""):
            f["redacted"] = True


def parse_sql(path: Path, file_id: str, file_captured_at) -> tuple[list[EvidenceRow], set[str]]:
    """Rows plus scope: systems whose tables this snapshot enumerates (absence by omission)."""
    text = path.read_text(encoding="utf-8")
    con = sqlite3.connect(":memory:")
    con.executescript(text)
    m = HEADER_TIME_RE.search(text)
    file_time = parse_time(m.group(1)) if m else file_captured_at
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    scope: set[str] = set()
    origin_time = {}
    if "snapshot_scope" in tables:
        origin_time = {o: parse_time(t) for o, t in
                       con.execute("SELECT origin_system, captured_at FROM snapshot_scope")}
        scope.update(origin_time)

    # (resource_id) -> {topology: (record dict, origin_system, collection)}
    seen: dict[str, dict[str, tuple[dict, str, str]]] = {}
    topologies: set[str] = set()
    for table in tables:
        if table == "snapshot_scope":
            continue
        base, topo = _topology(table)
        topologies.add(topo)
        if base in COLLECTION_CATEGORY:
            scope.add(SYSTEM_FOR_CATEGORY[COLLECTION_CATEGORY[base]])
        cur = con.execute(f'SELECT * FROM "{table}"')
        cols = [d[0] for d in cur.description]
        for values in cur.fetchall():
            rec = dict(zip(cols, values))
            if "record_json" in rec:
                origin, collection = rec["origin_system"], rec["collection_name"]
                body = json.loads(rec["record_json"])
            else:
                origin, collection, body = "", base, rec
            seen.setdefault(rec["resource_id"], {})[topo] = (body, origin, collection)
            if origin:
                scope.add(origin)

    rows = []
    for rid in sorted(seen):
        by_topo = seen[rid]
        any_body, origin, collection = next(iter(by_topo.values()))
        row = make_row(file_id, None, rid, present=True, system_id=origin,
                       category=COLLECTION_CATEGORY.get(collection, ""), fmt="sql",
                       file_captured_at=file_captured_at,
                       pointer=f"{collection}@{','.join(sorted(by_topo))}")
        row.captured_at = origin_time.get(row.system_id) or file_time or file_captured_at
        for topo in sorted(by_topo):  # primary sorts before replicas; non-null identifiers win
            body = by_topo[topo][0]
            absorb(row, body)
            _apply_state(row, body)
            if body.get("source_resource_id"):
                row.flags["source_resource_id"] = body["source_resource_id"]
        row.flags["topology"] = ",".join(sorted(by_topo))
        missing = sorted(topologies - set(by_topo))
        row.flags["drift"] = bool(missing) and len(topologies) > 1
        if row.flags["drift"]:
            row.flags["missing_in"] = ",".join(missing)
        rows.append(row)
    con.close()
    return rows, scope
