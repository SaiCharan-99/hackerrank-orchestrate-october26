"""Write output.csv and validate it against the AGENTS.md section 6.3-6.6 contract.

`validate` works on the serialized rows (case_id, deletion_status, steps_json strings) so the same checks run
right after writing and again in `--audit` on the file re-read from disk.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .engine import OPERATIONS, PHASES, STEP_KEYS
from .load import natural_case_key

HEADER = ["case_id", "deletion_status", "steps_json"]
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
PHASE_OPS = {
    "FINDING": {"REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"},
    "REMEDIATION": {"DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"},
    "VERIFICATION": {op for op in OPERATIONS if op.startswith("VERIFY_")},
}


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    future_citations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def evidence_times(data) -> dict:
    """Every participant-visible citable id -> the time it became visible (file manifest, activity, audit log)."""
    times = dict(zip(data.evidence_manifest["file_id"], data.evidence_manifest["captured_at"]))
    times.update(zip(data.activity["activity_id"], data.activity["event_time"]))
    times.update(zip(data.audit_log["audit_id"], data.audit_log["event_time"]))
    return times


def rows_from_audits(audits: dict, case_ids) -> list[tuple[str, str, str]]:
    return [(c, audits[c].status, audits[c].steps_json()) for c in sorted(case_ids, key=natural_case_key)]


def write_output(rows: list[tuple[str, str, str]], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(rows)


def read_output(path: Path) -> tuple[list[str], list[tuple[str, str, str]]]:
    with open(path, encoding="utf-8", newline="") as fh:
        r = csv.reader(fh)
        header = next(r, [])
        return header, [tuple(row) for row in r]


def _check_case(case_id: str, status: str, raw: str, audit_at, times: dict, v: Validation) -> None:
    err = lambda msg: v.errors.append(f"{case_id}: {msg}")  # noqa: E731
    if status not in STATUSES:
        err(f"bad status {status!r}")
        return
    try:
        steps = json.loads(raw)
    except json.JSONDecodeError as exc:
        err(f"steps_json is not valid JSON ({exc})")
        return
    if not isinstance(steps, list):
        err("steps_json is not an array")
        return
    if status == "NOT_APPLICABLE":
        if steps:
            err("NOT_APPLICABLE must have steps_json=[]")
        return
    if not steps:
        (v.warnings if status == "COMPLETE" else v.errors).append(f"{case_id}: {status} with no steps")
        return
    last_phase = -1
    by_phase: dict[str, set[str]] = {p: set() for p in PHASES}
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or set(s) != set(STEP_KEYS):
            err(f"step {i} keys {sorted(s) if isinstance(s, dict) else type(s).__name__} != the seven step keys")
            continue
        if s["step_no"] != i or isinstance(s["step_no"], bool):
            err(f"step {i} has step_no {s['step_no']!r}")
        phase, op, eid = s["phase"], s["operation"], s["evidence_id"]
        if phase not in PHASES:
            err(f"step {i} bad phase {phase!r}")
            continue
        if PHASES.index(phase) < last_phase:
            err(f"step {i} phase {phase} after a later phase")
        last_phase = max(last_phase, PHASES.index(phase))
        if op not in PHASE_OPS[phase] or OPERATIONS.get(op) != s["state"]:
            err(f"step {i} {phase}/{op}/{s['state']} is not an allowed phase/operation/state")
        if not all(isinstance(s[k], str) for k in ("system_id", "resource_id", "evidence_id")) \
                or not s["system_id"] or not s["resource_id"]:
            err(f"step {i} empty or non-string system_id/resource_id/evidence_id")
            continue
        by_phase[phase].add(s["resource_id"])
        cited = phase == "FINDING" or status == "COMPLETE"
        if cited and not eid:
            err(f"step {i} {phase} in a {status} case must cite evidence")
        if not cited and eid:
            err(f"step {i} {phase} in an INCOMPLETE case is future work; evidence_id must be empty")
        if eid:
            t = times.get(eid)
            if t is None:
                err(f"step {i} cites unknown evidence {eid}")
            elif t > audit_at:
                v.future_citations.append(f"{case_id}:{eid}")
                err(f"step {i} cites {eid} captured {t:%Y-%m-%dT%H:%M:%SZ} after audit_at")
    if status == "COMPLETE" and (by_phase["FINDING"] or by_phase["REMEDIATION"]):
        err("COMPLETE case has findings or remediation")
    if status == "INCOMPLETE" and not by_phase["FINDING"]:
        err("INCOMPLETE case has no findings")
    if by_phase["FINDING"] != by_phase["REMEDIATION"]:
        err(f"findings/remediation mismatch {sorted(by_phase['FINDING'] ^ by_phase['REMEDIATION'])}")
    if not by_phase["REMEDIATION"] <= by_phase["VERIFICATION"]:
        err(f"remediated but unverified {sorted(by_phase['REMEDIATION'] - by_phase['VERIFICATION'])}")


def validate(header, rows, requests, times: dict) -> Validation:
    v = Validation()
    if list(header) != HEADER:
        v.errors.append(f"header {header} != {HEADER}")
    expected = list(requests["case_id"])
    ids = [r[0] for r in rows]
    if len(rows) != len(expected):
        v.errors.append(f"{len(rows)} rows, expected {len(expected)}")
    if ids != sorted(ids, key=natural_case_key):
        v.errors.append("rows are not in natural case_id order")
    dup = [c for c, n in Counter(ids).items() if n > 1]
    if dup:
        v.errors.append(f"duplicate case_ids {dup[:5]}")
    missing, extra = set(expected) - set(ids), set(ids) - set(expected)
    if missing or extra:
        v.errors.append(f"missing {sorted(missing)[:5]} extra {sorted(extra)[:5]}")
    audit_at = dict(zip(requests["case_id"], requests["audit_at"]))
    for row in rows:
        if len(row) != 3:
            v.errors.append(f"row {row[:1]} has {len(row)} fields")
            continue
        if row[0] in audit_at:
            _check_case(row[0], row[1], row[2], audit_at[row[0]], times, v)
    return v


def status_distribution(statuses) -> dict[str, tuple[int, float]]:
    c = Counter(statuses)
    n = sum(c.values()) or 1
    return {s: (c[s], c[s] / n) for s in STATUSES}


def harm_signals(audits: dict, case_ids, vision_results: dict, validation: Validation) -> dict[str, tuple]:
    """APPROACH.md section 8 monitoring signals: (value, numerator, denominator)."""
    cases = [audits[c] for c in case_ids]
    applicable = [a for a in cases if not a.not_applicable]
    unresolved = sum(a.subject is None for a in applicable)
    unprov = sum(sum("unprovable" in n for n in a.notes) for a in applicable)
    linked = unprov + sum(len(a.resources) for a in applicable)
    disagreed = sum(r.agreement is False for r in vision_results.values())
    rate = lambda num, den: (num / den if den else 0.0, num, den)  # noqa: E731
    return {
        "unresolved_subject_rate": rate(unresolved, len(applicable)),
        "unprovable_resource_rate": rate(unprov, linked),
        "vision_disagreement_rate": rate(disagreed, len(vision_results)),
        "future_evidence_citations": (len(validation.future_citations), len(validation.future_citations), None),
    }


HARM_ACTIONS = {
    "unresolved_subject_rate": "block the row, route to manual review",
    "unprovable_resource_rate": "flag the case low-confidence, surface in the report",
    "vision_disagreement_rate": "third-pass reconciliation, else exclude the row and record it",
    "future_evidence_citations": "must be 0: hard fail",
}
