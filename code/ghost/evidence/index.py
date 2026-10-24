"""EvidenceIndex: parse every text evidence file in the manifest and index rows three ways."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..identity import norm_email, norm_phone
from .base import EvidenceRow, classify_identifier, system_for
from .json_exports import parse_json
from .logs import parse_log
from .sql import parse_sql
from .text import parse_text

PARSERS = {".sql": ("sql", parse_sql), ".json": ("json", parse_json), ".log": ("log", parse_log),
           ".txt": ("text", parse_text)}
DEFERRED = {".png": "image", ".pdf": "pdf"}  # Phase 4 vision extraction


def identifier_key(value: str) -> str:
    """Normalised lookup key for any identifier value (emails/hashes lower-case, phones digits)."""
    kind = classify_identifier(value)
    if kind == "phone":
        return "phone:" + norm_phone(value)
    if kind in ("email", "email_hash"):
        return norm_email(value).removeprefix("sha256:")
    return value.strip()


def _ts(row: EvidenceRow) -> datetime:
    return row.file_captured_at or row.captured_at


@dataclass
class EvidenceIndex:
    rows: list[EvidenceRow] = field(default_factory=list)
    by_resource: dict[str, list[EvidenceRow]] = field(default_factory=lambda: defaultdict(list))
    by_identifier: dict[str, list[EvidenceRow]] = field(default_factory=lambda: defaultdict(list))
    by_file: dict[str, list[EvidenceRow]] = field(default_factory=lambda: defaultdict(list))
    file_formats: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)  # file_id -> error message
    deferred: dict[str, str] = field(default_factory=dict)  # file_id -> image/pdf
    scopes: dict[str, set[str]] = field(default_factory=dict)  # file_id -> systems fully enumerated
    file_times: dict[str, datetime] = field(default_factory=dict)

    def add(self, row: EvidenceRow) -> None:
        self.rows.append(row)
        self.by_resource[row.resource_id].append(row)
        self.by_file[row.file_id].append(row)
        for v in row.all_identifier_values():
            self.by_identifier[identifier_key(v)].append(row)

    def finalize(self) -> None:
        key = lambda r: (_ts(r), r.captured_at or _ts(r), r.file_id, r.pointer)  # noqa: E731
        for table in (self.by_resource, self.by_identifier, self.by_file):
            for rows in table.values():
                rows.sort(key=key)

    def rows_for(self, resource_id: str, audit_at: datetime | None = None) -> list[EvidenceRow]:
        rows = self.by_resource.get(resource_id, [])
        return [r for r in rows if audit_at is None or _ts(r) <= audit_at]

    def latest_at(self, resource_id: str, audit_at: datetime) -> EvidenceRow | None:
        """Latest observation of a resource in a file captured at or before audit_at."""
        rows = self.rows_for(resource_id, audit_at)
        return rows[-1] if rows else None

    def absent_by_omission(self, file_id: str, resource_id: str) -> bool:
        """True if file_id enumerates resource_id's whole system and does not list the resource."""
        if system_for(resource_id)[0] not in self.scopes.get(file_id, set()):
            return False
        return not any(r.resource_id == resource_id for r in self.by_file.get(file_id, []))

    def omission_files(self, resource_id: str, audit_at: datetime | None = None) -> list[str]:
        """Files captured <= audit_at whose listing omits resource_id, oldest first. A hint only:
        snapshots are scoped extracts, so the state engine must tie the file to the subject first."""
        out = [f for f in self.scopes if self.absent_by_omission(f, resource_id)
               and (audit_at is None or self.file_times[f] <= audit_at)]
        return sorted(out, key=lambda f: (self.file_times[f], f))

    def find_identifier(self, value: str) -> list[EvidenceRow]:
        return self.by_identifier.get(identifier_key(value), [])


def build_evidence_index(data) -> EvidenceIndex:
    index = EvidenceIndex()
    root = Path(data.root) / "evidence"
    for m in data.evidence_manifest.sort_values("file_id").itertuples(index=False):
        path = Path(data.root) / m.file_path
        ext = path.suffix.lower()
        if ext in DEFERRED:
            index.deferred[m.file_id] = DEFERRED[ext]
            index.file_formats[m.file_id] = DEFERRED[ext]
            continue
        fmt, parser = PARSERS.get(ext, ("unknown", None))
        index.file_formats[m.file_id] = fmt
        index.file_times[m.file_id] = m.captured_at.to_pydatetime()
        if parser is None:
            index.errors[m.file_id] = f"no parser for {ext}"
            continue
        try:
            rows, scope = parser(path, m.file_id, m.captured_at.to_pydatetime())
        except Exception as exc:  # report per-file, keep going
            index.errors[m.file_id] = f"{type(exc).__name__}: {exc}"
            continue
        index.scopes[m.file_id] = scope
        for row in rows:
            index.add(row)
    assert root.exists()
    index.finalize()
    return index
