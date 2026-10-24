"""Common evidence row schema and the single system/category mapping table.

Every parser (SQL, JSON, logs, text, and later vision) emits EvidenceRow objects so the state engine
never needs to know which file format a fact came from.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

# One table: resource-id prefix -> (system_id, default data category). Order matters (longest first).
SYSTEMS: list[tuple[str, str, str]] = [
    ("audit_record_", "security_service", "SECURITY_AUDIT_LOG"),
    ("data_flow_", "integration_service", "DATA_FLOW"),
    ("legal_hold_", "legal_service", "LEGAL_HOLD_RECORD"),
    ("tombstone_", "identity_service", "ACCOUNT_TOMBSTONE"),
    ("analytics_", "analytics_platform", "ANALYTICS_PROFILE"),
    ("marketing_", "marketing_platform", "MARKETING_PROFILE"),
    ("email_log_", "email_delivery_service", "EMAIL_DELIVERY_LOG"),
    ("account_", "account_service", "USER_PROFILE"),
    ("search_", "search_service", "SEARCH_INDEX_ENTRY"),
    ("support_", "support_platform", "SUPPORT_MESSAGE"),
    ("export_", "export_service", "USER_EXPORT"),
    ("backup_", "backup_service", "BACKUP_ARCHIVE"),
    ("cache_", "cache_service", "CACHE_ENTRY"),
]
SYSTEM_CATEGORY = {system: category for _, system, category in SYSTEMS}
SYSTEM_FOR_CATEGORY = {category: system for _, system, category in SYSTEMS} | {"SUPPORT_ATTACHMENT": "support_platform"}

# Collection / table base names seen in evidence -> data category (system follows the resource id).
COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE", "profile_lookups": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY", "search_documents": "SEARCH_INDEX_ENTRY",
    "index_queries": "SEARCH_INDEX_ENTRY",
    "customer_analytics_profiles": "ANALYTICS_PROFILE", "customer_analytics_reports": "ANALYTICS_PROFILE",
    "profiles": "ANALYTICS_PROFILE",
    "support_records": "SUPPORT_MESSAGE", "support_conversations": "SUPPORT_MESSAGE", "tickets": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "customer_exports": "USER_EXPORT", "customer_export_jobs": "USER_EXPORT", "exports": "USER_EXPORT",
    "connector_subscriptions": "DATA_FLOW", "connector_configurations": "DATA_FLOW", "connectors": "DATA_FLOW",
    "backup_restore_entries": "BACKUP_ARCHIVE", "backup_catalog": "BACKUP_ARCHIVE",
    "restore_entries": "BACKUP_ARCHIVE",
    "security_audit_records": "SECURITY_AUDIT_LOG", "security_audit_events": "SECURITY_AUDIT_LOG",
    "audit_records": "SECURITY_AUDIT_LOG",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "retained_order_records": "LEGAL_HOLD_RECORD",
}

IDENTIFIER_KEYS = ("email", "name", "phone", "email_hash", "customer_reference")
FLAG_KEYS = ("enabled", "restore_allowed", "anonymized", "redacted", "account_status", "index_hit",
             "http_status", "topology", "drift")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"^user_\d+$")
HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
PHONE_RE = re.compile(r"^\+?[\d\s().\-]{7,}$")
RESOURCE_RE = re.compile(r"\b(?:" + "|".join(p for p, _, _ in SYSTEMS) + r")\d+\b")


def system_for(resource_id: str) -> tuple[str, str]:
    """(system_id, default category) for a resource id, or ("", "") if the prefix is unknown."""
    for prefix, system, category in SYSTEMS:
        if resource_id.startswith(prefix):
            return system, category
    return "", ""


def clean(value: Any) -> Any:
    """Normalise empty / 'null' / 'none' strings to None; keep other values."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return None if v.lower() in ("", "null", "none") else v
    return value


def as_bool(value: Any) -> bool | None:
    v = clean(value)
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off"):
        return False
    return None


def classify_identifier(value: Any) -> str | None:
    """Which identifier kind a bare value is (email / customer_reference / email_hash / phone)."""
    v = clean(value)
    if not isinstance(v, str):
        return None
    if EMAIL_RE.fullmatch(v):
        return "email"
    if USER_RE.match(v):
        return "customer_reference"
    if HASH_RE.match(v.lower()):
        return "email_hash"
    if PHONE_RE.match(v) and sum(c.isdigit() for c in v) >= 7:
        return "phone"
    return None


def parse_time(value: Any) -> datetime | None:
    v = clean(value)
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class EvidenceRow(BaseModel):
    """One observation of one resource in one evidence file."""

    file_id: str
    captured_at: datetime | None  # observation time inside the file (falls back to file capture)
    file_captured_at: datetime | None = None  # manifest captured_at, used for citation cut-offs
    system_id: str
    resource_id: str
    category: str
    present: bool | None
    identifiers: dict[str, str | None] = Field(default_factory=lambda: {k: None for k in IDENTIFIER_KEYS})
    # identifiers used to look the record up (lookup_key, query, correlation_key...): ownership, not content
    lookup_keys: list[str] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=lambda: {k: None for k in FLAG_KEYS})
    pointer: str = ""
    fmt: str = ""

    def exposed(self) -> dict[str, str]:
        """Direct identifiers still present in the record content."""
        return {k: v for k, v in self.identifiers.items() if v and k != "customer_reference"}

    def all_identifier_values(self) -> list[str]:
        vals = [v for v in self.identifiers.values() if v]
        return sorted(set(vals) | set(self.lookup_keys))


def make_row(file_id: str, captured_at: Any, resource_id: str, *, present: bool | None,
             category: str = "", system_id: str = "", fmt: str = "", pointer: str = "",
             file_captured_at: Any = None) -> EvidenceRow:
    sys_default, cat_default = system_for(resource_id)
    return EvidenceRow(
        file_id=file_id,
        captured_at=captured_at if isinstance(captured_at, datetime) else parse_time(captured_at),
        file_captured_at=file_captured_at if isinstance(file_captured_at, datetime)
        else parse_time(file_captured_at),
        system_id=system_id or sys_default,
        resource_id=resource_id,
        category=category or cat_default,
        present=present,
        fmt=fmt,
        pointer=pointer,
    )


NAME_KEYS = {"full_name", "display_name", "requester_name", "name"}
EMAIL_KEYS = {"email", "customer_email", "owner_email", "requester_email", "uploaded_by"}
PHONE_KEYS = {"phone", "owner_phone", "requester_phone"}
REF_KEYS = {"customer_reference", "user_id", "subject_reference", "subject_ref", "subject_selector"}
LOOKUP_KEYS = {"lookup_key", "match_key", "subject_key", "scan_key", "correlation_key", "query",
               "lookup_value", "matched_value", "subject_reference", "subject_ref", "subject_selector",
               "customer_reference", "user_id"}
TEXT_KEYS = {"message_text", "message_excerpt"}


def absorb(row: EvidenceRow, record: dict[str, Any]) -> None:
    """Copy identifier fields from a flat-or-nested record into the row (non-null wins)."""
    ids = row.identifiers
    for key, raw in record.items():
        if isinstance(raw, dict):
            absorb(row, raw)
            continue
        val = clean(raw)
        if val is None or isinstance(val, (list, bool, int, float)):
            continue
        val = str(val)
        kind = None
        if key in NAME_KEYS:
            kind = "name"
        elif key in EMAIL_KEYS:
            kind = "email" if EMAIL_RE.fullmatch(val) else classify_identifier(val)
        elif key in PHONE_KEYS:
            kind = "phone"
        elif key == "email_hash":
            kind = "email_hash"
        elif key in REF_KEYS:
            kind = classify_identifier(val)
        elif key in TEXT_KEYS:
            m = EMAIL_RE.search(val)
            if m and not ids.get("email"):
                ids["email"] = m.group(0)
            continue
        if key in LOOKUP_KEYS and val not in row.lookup_keys and not RESOURCE_RE.fullmatch(val):
            row.lookup_keys.append(val)
        if kind and not ids.get(kind):
            ids[kind] = val
