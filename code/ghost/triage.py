"""Bounded evidence triage (APPROACH.md 3.9).

Per case, the candidates are evidence rows with partial or conflicting identifiers that discovery left
unattached: rows whose identifiers resolve to this subject AND another subject (contested), or rows whose
only tie to the subject is the display name. The model answers include | exclude | needs_recheck per row
and may request (resource_id, alternative_file_id) re-checks. It cannot add resources outside the
candidate list, change states, or touch policy. It is NOT asked to pick between tied accounts or tied
analytics records (those ties carry no information; progress.md P2b-verifier).
Deterministic fallback: every candidate is excluded and the case is flagged.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from pydantic import BaseModel, field_validator

from .config import CACHE_DIR
from .discovery import _owners
from .prompts import triage as P

TRIAGE_CACHE = CACHE_DIR / "triage.json"
DECISIONS = ("include", "exclude", "needs_recheck")


class TriageDecision(BaseModel):
    row_key: str
    decision: str
    reason: str = ""
    recheck_resource_id: str | None = None
    recheck_file_id: str | None = None

    @field_validator("decision")
    @classmethod
    def _d(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        return v


class TriageReply(BaseModel):
    decisions: list[TriageDecision]


@dataclass
class TriageResult:
    case_id: str
    candidates: list[dict] = field(default_factory=list)
    decisions: dict[str, TriageDecision] = field(default_factory=dict)
    included: list[str] = field(default_factory=list)  # resource ids
    rechecks: list[tuple[str, str]] = field(default_factory=list)
    flagged: str = ""


def candidates_for(disc, ids, evidence, audit_at) -> list[dict]:
    """Rows (<= audit_at) not in the footprint whose identifiers tie partially or conflictingly to the subject."""
    s = disc.subject
    if s is None:
        return []
    footprint = set(disc.resources) | set(disc.account_candidates)
    out, seen = [], set()
    for row in evidence.rows:
        if row.resource_id in footprint or row.resource_id.startswith(("account_", "analytics_")):
            continue
        ts = row.file_captured_at or row.captured_at
        if ts is None or ts > audit_at:
            continue
        values = [v for k, v in row.identifiers.items() if v and k != "name"] + list(row.lookup_keys)
        uids = set().union(*(_owners(v, ids) for v in values)) if values else set()
        name = (row.identifiers.get("name") or "").strip().lower()
        contested = s.user_id in uids and len(uids) > 1
        name_only = not uids and name and name == (s.name or "").strip().lower()
        if not (contested or name_only):
            continue
        key = f"{row.file_id}:{row.resource_id}"
        if key in seen:
            continue
        seen.add(key)
        alts = sorted({r.file_id for r in evidence.rows_for(row.resource_id, audit_at)} - {row.file_id})
        out.append({"row_key": key, "resource_id": row.resource_id, "file_id": row.file_id,
                    "kind": "contested" if contested else "name_only", "owners": sorted(uids),
                    "identifiers": {k: v for k, v in row.identifiers.items() if v},
                    "lookup_keys": row.lookup_keys, "present": row.present, "alternatives": alts})
    return out


def _subject_view(s) -> dict:
    return {"user_id": s.user_id, "name": s.name, "emails": sorted(s.emails), "phones": sorted(s.phones)}


def triage_case(disc, ids, evidence, audit_at, llm=None, model: str = "", *, cache: dict | None = None,
                only_cached: bool = False) -> TriageResult:
    from .llm import BudgetExceeded, ExtractionFailed

    res = TriageResult(disc.case_id, candidates_for(disc, ids, evidence, audit_at))
    if not res.candidates:
        return res
    payload = json.dumps({"subject": _subject_view(disc.subject), "audit_at": str(audit_at),
                          "rows": res.candidates}, sort_keys=True, default=str)
    h = hashlib.sha256(payload.encode()).hexdigest()
    reply = None
    if cache is not None and h in cache:
        reply = TriageReply.model_validate(cache[h])
    elif llm is not None and not only_cached:
        prompt = (P.TRIAGE.replace("{subject}", json.dumps(_subject_view(disc.subject)))
                  .replace("{audit_at}", str(audit_at))
                  .replace("{rows}", json.dumps(res.candidates, indent=1, default=str)))
        try:
            reply = llm.structured(TriageReply, model, prompt, purpose="triage", item=disc.case_id, max_tokens=1500)
            if cache is not None:
                cache[h] = reply.model_dump()
        except (ExtractionFailed, BudgetExceeded) as exc:
            res.flagged = f"triage unavailable ({str(exc)[:80]}); ambiguous rows excluded"
    if reply is None:
        res.flagged = res.flagged or "triage not run; ambiguous rows excluded (deterministic fallback)"
        return res
    valid = {c["row_key"]: c for c in res.candidates}
    for d in reply.decisions:
        if d.row_key not in valid:  # the model cannot add rows
            continue
        res.decisions[d.row_key] = d
        c = valid[d.row_key]
        if d.decision == "include":
            res.included.append(c["resource_id"])
        elif d.decision == "needs_recheck" and d.recheck_file_id in c["alternatives"]:
            res.rechecks.append((c["resource_id"], d.recheck_file_id))
    res.included = sorted(set(res.included))
    return res


def load_cache() -> dict:
    return json.loads(TRIAGE_CACHE.read_text(encoding="utf-8")) if TRIAGE_CACHE.exists() else {}


def save_cache(cache: dict) -> None:
    TRIAGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TRIAGE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
