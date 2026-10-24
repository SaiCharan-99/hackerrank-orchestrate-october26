"""Deterministic state engine: one CaseAudit per request, built from evidence state at audit_at.

Every outward field is derived from the CaseAudit lists: deletion_status is computed from findings and
steps_json is serialized from findings + remediations + verifications (APPROACH.md section 3.5 / 8).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from .evidence.base import EvidenceRow, system_for

PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")
# Operation table order from AGENTS.md section 6.4; this is the second sort key.
OPERATIONS = {
    "REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED", "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT", "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}
OP_RANK = {op: i for i, op in enumerate(OPERATIONS)}
STEP_KEYS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")

# Treatment -> (finding op, remediation op, verification op) when violated (APPROACH.md section 2.5 table).
TREATMENT = {
    "DELETE": ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    "REDACT": ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    "ANONYMIZE": ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    "RETAIN": (None, None, "VERIFY_RECORD_PRESENT"),
    "DATA_FLOW": ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    "BACKUP": ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
}
# Categories whose rule action is not a plain record treatment.
SPECIAL = {"DATA_FLOW": "DATA_FLOW", "BACKUP_ARCHIVE": "BACKUP"}
RETAINED = {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}

# Analytics hypothesis for case_12 (APPROACH.md section 7). "attempted_delete": an analytics record that the
# deletion workflow tried to DELETE_RECORD before audit_at is under DELETE treatment (the remaining record is
# reported, not anonymized); "always_anonymize": rule_07 ANONYMIZE regardless of activity. Kept: see progress.md.
ANALYTICS_HYPOTHESES = ("attempted_delete", "always_anonymize")
ANALYTICS_HYPOTHESIS = "attempted_delete"


@dataclass(frozen=True)
class Step:
    phase: str
    system_id: str
    resource_id: str
    operation: str
    evidence_id: str = ""

    @property
    def state(self) -> str:
        return OPERATIONS[self.operation]

    def key(self) -> tuple:
        return (PHASES.index(self.phase), OP_RANK[self.operation], self.system_id, self.resource_id)


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    category: str
    treatment: str
    present: bool | None
    violated: bool
    evidence_id: str
    row: EvidenceRow | None
    why: str


@dataclass
class CaseAudit:
    case_id: str
    subject: str | None
    resources: list[ResourceState] = field(default_factory=list)
    findings: list[Step] = field(default_factory=list)
    remediations: list[Step] = field(default_factory=list)
    verifications: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    not_applicable: bool = False

    @property
    def status(self) -> str:
        if self.not_applicable:
            return "NOT_APPLICABLE"
        return "INCOMPLETE" if self.findings else "COMPLETE"

    def steps(self) -> list[dict]:
        if self.not_applicable:
            return []
        ordered = sorted(self.findings, key=Step.key) + sorted(self.remediations, key=Step.key) \
            + sorted(self.verifications, key=Step.key)
        return [dict(zip(STEP_KEYS, (i, s.phase, s.system_id, s.resource_id, s.operation, s.state, s.evidence_id)))
                for i, s in enumerate(ordered, 1)]

    def steps_json(self) -> str:
        return json.dumps(self.steps(), ensure_ascii=False, separators=(",", ":"))


def rule_actions(rules: pd.DataFrame) -> dict[str, str]:
    return dict(zip(rules["data_category"], rules["required_action"]))


def _deleted_by_workflow(activity: pd.DataFrame, resource_id: str, audit_at) -> bool:
    a = activity[(activity["resource_id"] == resource_id) & (activity["event_type"] == "DELETE_RECORD")
                 & (activity["event_time"] <= audit_at)]
    return not a.empty


def treatment_for(category: str, resource_id: str, actions: dict[str, str], activity, audit_at,
                  hypothesis: str, row: EvidenceRow | None = None) -> str:
    if row is not None and row.flags.get("deletion_marker") is False:
        # A deletion-marker check that finds no marker means the record was due for deletion, not redaction
        # (case_10: a legacy contact-index copy of a support record).
        return "DELETE"
    if category in SPECIAL:
        return SPECIAL[category]
    if category == "ANALYTICS_PROFILE" and hypothesis == "attempted_delete" \
            and _deleted_by_workflow(activity, resource_id, audit_at):
        return "DELETE"
    return actions.get(category, "DELETE")


def _violated(treatment: str, row: EvidenceRow) -> tuple[bool, str]:
    f = row.flags
    if treatment == "DATA_FLOW":
        return bool(row.present and f.get("enabled")), f"enabled={f.get('enabled')}"
    if treatment == "BACKUP":
        return bool(row.present and f.get("restore_allowed")), f"restore_allowed={f.get('restore_allowed')}"
    if treatment == "DELETE":
        return bool(row.present), f"present={row.present}"
    if treatment == "RETAIN":
        return False, f"present={row.present}"
    exposed = row.exposed()
    if treatment == "ANONYMIZE":
        attributable = bool(exposed) or f.get("anonymized") is False or (f.get("anonymized") is None and
                                                                          bool(row.lookup_keys))
        return bool(row.present and attributable), f"exposed={sorted(exposed)} anonymized={f.get('anonymized')}"
    # REDACT (support message, email log, tombstone): any direct identifier left is a violation
    flagged = f.get("redacted") is False and treatment == "REDACT" and row.category != "ACCOUNT_TOMBSTONE"
    return bool(row.present and (exposed or flagged)), f"exposed={sorted(exposed)} redacted={f.get('redacted')}"


def _absence_file(index, resource_id: str, audit_at, subject_files: set[str]) -> str:
    """Evidence proving absence by omission. A file that also holds the subject's other records wins; else
    the latest file that lists at least one other record of the system (an empty scoped extract lists
    nothing, so it cannot tell this record from any other)."""
    system = system_for(resource_id)[0]
    files = index.omission_files(resource_id, audit_at)
    tied = [f for f in files if f in subject_files]
    listing = [f for f in files if any(r.system_id == system for r in index.by_file.get(f, []))]
    return (tied or listing or [""])[-1]


def audit_case(request, subjects, evidence_index, rules, activity, *, authorizes_deletion: bool = True,
               analytics_hypothesis: str = ANALYTICS_HYPOTHESIS) -> CaseAudit:
    """Build the CaseAudit for one request. `subjects` maps case_id -> discovery.Discovery."""
    disc = subjects[request.case_id]
    audit_at = request.audit_at
    ca = CaseAudit(case_id=request.case_id, subject=disc.subject.user_id if disc.subject else None)
    if not authorizes_deletion:
        ca.not_applicable = True
        ca.notes.append("request does not authorize deletion")
        return ca
    if disc.subject is None:
        ca.notes.append("UNRESOLVED subject: no evidence can be attributed")
        return ca
    if disc.ambiguous:
        ca.notes.append(f"account choice tentative: {disc.reason}")
    if not disc.chosen_account:
        ca.notes.append("account unknown: no account activity or evidence ties an account to this request")
    ca.notes += [f"policy-linked record {part.strip()}" for part in disc.reason.split(";") if "tentatively linked" in part]
    actions = rule_actions(rules)

    states: list[tuple[str, EvidenceRow | None]] = []
    for rid in disc.resources:
        states.append((rid, evidence_index.latest_at(rid, audit_at)))
    subject_files = {row.file_id for _, row in states if row is not None}
    retained_later: list[ResourceState] = []

    for rid, row in states:
        system, default_cat = system_for(rid)
        is_account = rid == disc.chosen_account
        if row is None and not is_account:
            if default_cat in RETAINED and evidence_index.rows_for(rid):
                # Retained record linked to the subject but observed only after audit_at: it cannot prove a
                # COMPLETE state, but a remediation plan must still check it survives (future verification).
                retained_later.append(ResourceState(rid, system, default_cat, "RETAIN", None, False, "", None,
                                                    "retained; first observed after audit_at"))
                continue
            ca.notes.append(f"{rid}: no evidence at or before audit_at; skipped (unprovable)")
            continue
        category = row.category if row is not None else default_cat
        system = row.system_id if row is not None else system
        treatment = treatment_for(category, rid, actions, activity, audit_at, analytics_hypothesis, row)
        if row is None:
            eid = _absence_file(evidence_index, rid, audit_at, subject_files)
            rs = ResourceState(rid, system, category, treatment, False, False, eid, None,
                               f"no row <= audit_at; absent by omission in {eid or 'no file'}")
        else:
            violated, why = _violated(treatment, row)
            if treatment == "DELETE" and not row.present and row.present is not None:
                why += " (absent)"
            if treatment in ("REDACT", "ANONYMIZE", "RETAIN") and row.present is False:
                ca.notes.append(f"{rid}: {treatment} record absent at audit_at ({row.file_id}); not verifiable")
                continue
            rs = ResourceState(rid, system, category, treatment, row.present, violated, row.file_id, row, why)
        ca.resources.append(rs)

    for rs in ca.resources:
        find_op, fix_op, verify_op = TREATMENT[rs.treatment]
        if rs.violated:
            ca.findings.append(Step("FINDING", rs.system_id, rs.resource_id, find_op, rs.evidence_id))
            ca.remediations.append(Step("REMEDIATION", rs.system_id, rs.resource_id, fix_op))
        ca.verifications.append(Step("VERIFICATION", rs.system_id, rs.resource_id, verify_op, rs.evidence_id))
    if ca.findings:
        for rs in retained_later:
            ca.resources.append(rs)
            ca.verifications.append(Step("VERIFICATION", rs.system_id, rs.resource_id, "VERIFY_RECORD_PRESENT"))
    else:
        ca.notes += [f"{rs.resource_id}: retained record observed only after audit_at; not cited" for rs in retained_later]
    if ca.findings:  # INCOMPLETE: verification describes future work
        ca.verifications = [Step(s.phase, s.system_id, s.resource_id, s.operation) for s in ca.verifications]
    _check(ca)
    return ca


def _check(ca: CaseAudit) -> None:
    """Fail loudly on internal contradictions (APPROACH.md section 8, first row)."""
    found = {s.resource_id for s in ca.findings}
    fixed = {s.resource_id for s in ca.remediations}
    verified = {s.resource_id for s in ca.verifications}
    assert found == fixed, f"{ca.case_id}: findings {found} != remediations {fixed}"
    assert fixed <= verified, f"{ca.case_id}: remediated but unverified {fixed - verified}"


def audit_all(requests, discoveries, evidence_index, rules, activity, **kw) -> dict[str, CaseAudit]:
    return {r.case_id: audit_case(r, discoveries, evidence_index, rules, activity, **kw)
            for r in requests.itertuples(index=False)}


def describe(ca: CaseAudit, audit_at: datetime | None = None) -> str:
    lines = [f"{ca.case_id} subject={ca.subject} status={ca.status}"]
    for rs in ca.resources:
        ptr = f"{rs.row.file_id}:{rs.row.pointer} [{rs.row.fmt}]" if rs.row else f"{rs.evidence_id or '-'} (omission)"
        lines.append(f"  {rs.resource_id:<20} {rs.category:<20} {rs.treatment:<9} violated={rs.violated!s:<5} "
                     f"{rs.why} <- {ptr}")
    lines += [f"  note: {n}" for n in ca.notes]
    for s in ca.steps():
        lines.append(f"  {s['step_no']:>2} {s['phase']:<12} {s['operation']:<26} {s['system_id']:<20} "
                     f"{s['resource_id']:<20} {s['state']:<10} {s['evidence_id']}")
    return "\n".join(lines)
