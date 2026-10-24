"""Hand-authored custom and adversarial cases run through the same pipeline as the real dataset.

Each case is a directory under code/evaluation/custom_cases/<name>/ with `case.json` (one request row, the
identity / audit-log / activity rows it needs, an evidence manifest and the expected answer) and the synthetic
evidence files it names under `evidence/`. The policy table is the real dataset/deletion_rules.csv, so the
cases exercise the shipped rules. `run_case` builds a `load.Dataset` for the directory and calls the same
functions as `main._audits`: evidence index -> identity graph -> discovery -> intent -> engine -> grader.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import DATASET_DIR, EVALUATION_DIR
from .discovery import discover
from .engine import audit_case
from .evidence import build_evidence_index
from .grade import grade
from .identity import build_index
from .intent import classify_requests
from .load import TIME_COLUMNS, Dataset

CUSTOM_DIR = EVALUATION_DIR / "custom_cases"
COLUMNS = {
    "requests": ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"],
    "identities": ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
    "audit_log": ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"],
    "activity": ["activity_id", "event_time", "event_type", "source_system", "target_system", "resource_id",
                 "reported_result", "details"],
    "evidence_manifest": ["file_id", "file_path", "origin", "captured_at"],
}


@dataclass
class CustomResult:
    name: str
    kind: str
    description: str
    expected_status: str
    got_status: str
    passed: bool
    grade: object
    notes: list[str]


def _frame(name: str, rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{c: str(r.get(c, "")) for c in COLUMNS[name]} for r in rows], columns=COLUMNS[name])
    df = df.astype(str)
    for col in TIME_COLUMNS.get(name, []):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def load_case(case_dir: Path) -> tuple[dict, Dataset]:
    spec = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    empty_req = _frame("requests", [])
    data = Dataset(
        root=case_dir,
        requests=_frame("requests", [spec["request"]]),
        sample_requests=empty_req,
        sample_output=pd.DataFrame(columns=["case_id", "deletion_status", "steps_json"]),
        identities=_frame("identities", spec.get("identities", [])),
        audit_log=_frame("audit_log", spec.get("audit_log", [])),
        activity=_frame("activity", spec.get("activity", [])),
        rules=pd.read_csv(DATASET_DIR / "deletion_rules.csv", dtype=str, keep_default_na=False),
        evidence_manifest=_frame("evidence_manifest", spec.get("evidence", [])),
        output_template=pd.DataFrame(columns=["case_id", "deletion_status", "steps_json"]),
    )
    return spec, data


def run_case(case_dir: Path, llm=None, model: str = "") -> CustomResult:
    spec, data = load_case(case_dir)
    index = build_evidence_index(data)
    ids = build_index(data)
    results = discover(data, ids, index)
    intents = classify_requests(data.requests, llm, model, only_cached=llm is None, purpose="intent-custom")
    req = next(data.requests.itertuples(index=False))
    ca = audit_case(req, results, index, data.rules, data.activity,
                    authorizes_deletion=intents[req.case_id].authorizes_deletion)
    exp = spec["expected"]
    summary, cases = grade([(req.case_id, exp["deletion_status"], json.dumps(exp["steps"]))],
                           {req.case_id: (ca.status, ca.steps())}, index.file_formats)
    notes = list(ca.notes) + [f"intent source: {intents[req.case_id].source}"]
    notes += [f"parse error {f}: {e}" for f, e in sorted(index.errors.items())]
    return CustomResult(case_dir.name, spec.get("kind", "custom"), spec.get("description", ""),
                        exp["deletion_status"], ca.status, cases[0].exact, cases[0], notes)


def run_all(llm=None, model: str = "") -> list[CustomResult]:
    dirs = sorted(p for p in CUSTOM_DIR.iterdir() if (p / "case.json").exists())
    return [run_case(d, llm, model) for d in dirs]
