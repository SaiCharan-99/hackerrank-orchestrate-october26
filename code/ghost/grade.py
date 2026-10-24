"""Local grader: predicted CaseAudits vs sample_output.csv (APPROACH.md section 3.7)."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def step_tuple(s: dict) -> tuple:
    return tuple(s[k] for k in FIELDS)


@dataclass
class CaseGrade:
    case_id: str
    status_ok: bool
    exact: bool
    expected: list[tuple]
    got: list[tuple]
    sequence_exact: bool
    pairwise: float
    formats: set[str] = field(default_factory=set)


def pairwise_agreement(expected: list[tuple], got: list[tuple]) -> float:
    """Share of expected step pairs (both predicted) that keep their relative order."""
    pos = {t: i for i, t in enumerate(got)}
    common = [t for t in expected if t in pos]
    pairs = list(combinations(common, 2))
    if not pairs:
        return 1.0 if common == expected else 0.0
    return sum(pos[a] < pos[b] for a, b in pairs) / len(pairs)


def grade(expected_rows, predicted: dict[str, tuple[str, list[dict]]], file_formats: dict[str, str]):
    """expected_rows: iterable of (case_id, status, steps_json). predicted: case_id -> (status, steps)."""
    cases = []
    field_hits, field_total = Counter(), 0
    for cid, status, sj in expected_rows:
        exp = [step_tuple(s) for s in json.loads(sj or "[]")]
        p_status, p_steps = predicted.get(cid, ("", []))
        got = [step_tuple(s) for s in p_steps]
        # Field accuracy over position-aligned steps (missing/extra steps count as misses on every field).
        n = max(len(exp), len(got))
        field_total += n
        for i in range(min(len(exp), len(got))):
            for j, f in enumerate(FIELDS):
                field_hits[f] += exp[i][j] == got[i][j]
        fmts = {file_formats.get(t[5], "?") for t in set(exp) ^ set(got) if t[5]}
        common = [t for t in got if t in set(exp)]
        cases.append(CaseGrade(cid, p_status == status, exp == got and p_status == status, exp, got,
                               [t for t in exp if t in set(got)] == common and set(exp) == set(got),
                               pairwise_agreement(exp, got), fmts))
    exp_steps = sum(len(c.expected) for c in cases)
    matched = sum(len(set(c.expected) & set(c.got)) for c in cases)
    got_steps = sum(len(c.got) for c in cases)
    summary = {
        "cases": len(cases),
        "status_accuracy": sum(c.status_ok for c in cases) / len(cases),
        "exact_cases": sum(c.exact for c in cases),
        "step_recall": matched / exp_steps if exp_steps else 1.0,
        "step_precision": matched / got_steps if got_steps else 1.0,
        "field_accuracy": {f: field_hits[f] / field_total if field_total else 1.0 for f in FIELDS},
        "sequence_exact": sum(c.sequence_exact for c in cases) / len(cases),
        "pairwise_order": sum(c.pairwise for c in cases) / len(cases),
        "errors_by_format": Counter(f for c in cases if not c.exact for f in (c.formats or {"(none)"})),
    }
    return summary, cases


def report(summary, cases) -> str:
    lines = [f"Cases: {summary['cases']}  exact: {summary['exact_cases']}/{summary['cases']}  "
             f"status accuracy: {summary['status_accuracy']:.3f}",
             f"Step recall: {summary['step_recall']:.3f}  step precision: {summary['step_precision']:.3f}",
             "Field accuracy (position-aligned): " + "  ".join(f"{k}={v:.3f}" for k, v in
                                                               summary["field_accuracy"].items()),
             f"Sequence exact: {summary['sequence_exact']:.3f}  pairwise order agreement: "
             f"{summary['pairwise_order']:.3f}",
             f"Errors by evidence format: {dict(sorted(summary['errors_by_format'].items()))}"]
    for c in cases:
        if c.exact:
            continue
        lines.append(f"--- {c.case_id} status_ok={c.status_ok} seq_exact={c.sequence_exact} "
                     f"pairwise={c.pairwise:.2f} formats={sorted(c.formats)}")
        for t in c.expected:
            if t not in c.got:
                lines.append(f"   expected-only {t}")
        for t in c.got:
            if t not in c.expected:
                lines.append(f"   got-only      {t}")
    return "\n".join(lines)
