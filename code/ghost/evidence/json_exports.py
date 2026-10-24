"""JSON evidence: service_resource_export, customer_data_snapshot_bundle, flat ledgers and collections."""
from __future__ import annotations

import json
from pathlib import Path

from .base import COLLECTION_CATEGORY, EvidenceRow, absorb, as_bool, clean, classify_identifier, make_row
from .sql import _apply_state

# Ledger "result" vocabulary -> (present, flag updates)
RESULTS = {
    "FOUND": (True, {}),
    "NOT_FOUND": (False, {}),
    "IDENTIFIABLE": (True, {"anonymized": False, "redacted": False}),
    "ANONYMIZED": (True, {"anonymized": True}),
    "REDACTED": (True, {"redacted": True}),
    "ACTIVE": (True, {}),  # enabled / restore_allowed set by category below
    "DISABLED": (True, {"enabled": False}),
    "BLOCKED": (True, {"restore_allowed": False}),
}


def ledger_row(file_id: str, file_captured_at, *, recorded_at, system: str, resource_id: str,
               record_type: str, result: str, reference: str, fmt: str, pointer: str) -> EvidenceRow:
    """A flat record-lookup row (JSON ledgers, record_lookup logs, handover text)."""
    result = (result or "").strip().upper()
    present, flags = RESULTS.get(result, (None, {}))
    row = make_row(file_id, recorded_at, resource_id, present=present, system_id=system,
                   category=record_type, fmt=fmt, pointer=pointer, file_captured_at=file_captured_at)
    row.flags["result"] = result
    row.flags.update(flags)
    if result == "ACTIVE":
        row.flags["enabled" if row.category == "DATA_FLOW" else "restore_allowed"] = True
    ref = clean(reference)
    if ref and ref.lower() != "no direct identifier":
        row.lookup_keys.append(ref)
        # Only an IDENTIFIABLE / FOUND support or analytics row shows the identifier as content.
        if result == "IDENTIFIABLE" and classify_identifier(ref) in ("email", "phone", "email_hash"):
            row.identifiers[classify_identifier(ref)] = ref
    return row


def _service_export(d: dict, file_id: str, fca) -> list[EvidenceRow]:
    rows = []
    for system, collections in sorted(d["service_exports"].items()):
        for collection, records in sorted(collections.items()):
            for i, rec in enumerate(records):
                rid = rec["resource_id"]
                present = True
                if "status_code" in rec:
                    present = int(rec["status_code"]) == 200 and rec.get("profile") is not None
                row = make_row(file_id, rec.get("observed_at"), rid, present=present, system_id=system,
                               category=COLLECTION_CATEGORY.get(collection, ""), fmt="json:service_export",
                               pointer=f"service_exports.{system}.{collection}[{i}]", file_captured_at=fca)
                if "status_code" in rec:
                    row.flags["http_status"] = int(rec["status_code"])
                if "hits" in rec:
                    docs = [doc for doc in rec["hits"].get("documents", []) if doc.get("resource_id") == rid]
                    row.present = bool(docs) or int(rec["hits"].get("total") or 0) > 0
                    row.flags["index_hit"] = row.present
                    for doc in docs:
                        absorb(row, doc)
                    if clean(rec.get("query")):
                        row.lookup_keys.append(rec["query"])
                else:
                    absorb(row, rec.get("profile") or {})
                    absorb(row, {k: v for k, v in rec.items() if k != "profile"})
                _apply_state(row, rec)
                rows.append(row)
    return rows


def _collection(records: list[dict], *, system: str, collection: str, captured_at, file_id: str, fca,
                fmt: str, pointer: str) -> list[EvidenceRow]:
    rows = []
    for i, rec in enumerate(records):
        if "record_type" in rec and "result" in rec:
            rows.append(ledger_row(file_id, fca, recorded_at=rec.get("recorded_at") or captured_at,
                                   system=rec["system"], resource_id=rec["resource_id"],
                                   record_type=rec["record_type"], result=rec["result"],
                                   reference=rec.get("subject_reference") or rec.get("lookup_value") or "",
                                   fmt=fmt, pointer=f"{pointer}[{i}]"))
            continue
        row = make_row(file_id, captured_at, rec["resource_id"], present=True, system_id=system,
                       category=COLLECTION_CATEGORY.get(collection, ""), fmt=fmt,
                       pointer=f"{pointer}[{i}]", file_captured_at=fca)
        absorb(row, rec)
        _apply_state(row, rec)
        if row.category == "ANALYTICS_PROFILE":
            row.flags["anonymized"] = not row.exposed() and not row.identifiers.get("customer_reference")
        rows.append(row)
    return rows


def parse_json(path: Path, file_id: str, file_captured_at) -> tuple[list[EvidenceRow], set[str]]:
    """Rows plus scope (systems whose full collection is listed in the file)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    fca = file_captured_at
    if "service_exports" in d:
        return _service_export(d, file_id, fca), set()
    if "snapshots" in d:
        rows, scope = [], set()
        for i, snap in enumerate(d["snapshots"]):
            if snap["collection"] in COLLECTION_CATEGORY:  # a full collection listing: omission = absence
                scope.add(snap["data_store"])
            rows += _collection(snap["records"], system=snap["data_store"], collection=snap["collection"],
                                captured_at=snap.get("captured_at"), file_id=file_id, fca=fca,
                                fmt="json:snapshot_bundle", pointer=f"snapshots[{i}].records")
        return rows, scope
    if "records" in d:
        collection = d.get("collection", "")
        system = {"customer_analytics_reports": "analytics_platform",
                  "customer_export_jobs": "export_service"}.get(collection, "")
        return _collection(d["records"], system=system, collection=collection,
                           captured_at=d.get("captured_at") or d.get("exported_at"), file_id=file_id, fca=fca,
                           fmt="json:ledger" if not collection else f"json:{collection}", pointer="records"), set()
    raise ValueError(f"unknown JSON shape: keys={sorted(d)[:8]}")
