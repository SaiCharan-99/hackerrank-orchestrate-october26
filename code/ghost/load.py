"""Load every participant-facing table under dataset/ with parsed UTC timestamps."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

TIME_COLUMNS = {
    "requests": ["requested_at", "reported_at", "audit_at"],
    "sample_requests": ["requested_at", "reported_at", "audit_at"],
    "identities": ["updated_at"],
    "audit_log": ["event_time"],
    "activity": ["event_time"],
    "evidence_manifest": ["captured_at"],
}

FILES = {
    "requests": "deletion_requests.csv",
    "sample_requests": "sample_deletion_requests.csv",
    "sample_output": "sample_output.csv",
    "identities": "user_identities.csv",
    "audit_log": "user_audit_log.csv",
    "activity": "system_activity.csv",
    "rules": "deletion_rules.csv",
    "evidence_manifest": "evidence_files.csv",
    "output_template": "output.csv",
}


@dataclass(frozen=True)
class Dataset:
    root: Path
    requests: pd.DataFrame
    sample_requests: pd.DataFrame
    sample_output: pd.DataFrame
    identities: pd.DataFrame
    audit_log: pd.DataFrame
    activity: pd.DataFrame
    rules: pd.DataFrame
    evidence_manifest: pd.DataFrame
    output_template: pd.DataFrame


def natural_case_key(case_id: str) -> tuple:
    """Sort key so case_9 < case_12: split into text and integer runs."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(case_id)) if p != "")


def _read(path: Path, time_cols: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    for col in time_cols:
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def load_all(dataset_dir: Path) -> Dataset:
    dataset_dir = Path(dataset_dir)
    tables = {name: _read(dataset_dir / fname, TIME_COLUMNS.get(name, [])) for name, fname in FILES.items()}
    return Dataset(root=dataset_dir, **tables)


def check_case_order(data: Dataset) -> str:
    """Verify natural_case_key against the output template order when it has rows."""
    template = list(data.output_template["case_id"])
    if not template:
        return "output template has no rows; natural_case_key used"
    ok = template == sorted(template, key=natural_case_key)
    return "template order matches natural_case_key" if ok else "template order DIFFERS from natural_case_key"
