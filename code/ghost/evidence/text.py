"""Plain-text handover notes: '- <time> | <system> | <resource_id> | <record_type> | <result> | <reference>'."""
from __future__ import annotations

from pathlib import Path

from .base import EvidenceRow, RESOURCE_RE
from .json_exports import ledger_row


def parse_text(path: Path, file_id: str, file_captured_at) -> list[EvidenceRow]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = [p.strip() for p in line.lstrip("-* ").split("|")]
        if len(parts) < 5 or not RESOURCE_RE.fullmatch(parts[2]):
            continue
        ts, system, rid, record_type, result = parts[:5]
        reference = parts[5] if len(parts) > 5 else ""
        rows.append(ledger_row(file_id, file_captured_at, recorded_at=ts, system=system, resource_id=rid,
                               record_type=record_type, result=result, reference=reference,
                               fmt="text:handover", pointer=f"line {n}"))
    return rows, set()
