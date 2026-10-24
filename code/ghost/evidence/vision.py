"""Vision / PDF extraction: PNG and PDF evidence -> EvidenceRow, two-model agreement, cached per file_id.

Policy if extraction cannot run (no gateway, budget reached, schema failure): the file yields no rows and
the result is marked `extraction_failed`; `affected_cases` lets the engine flag cases in notes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..config import CACHE_DIR
from ..prompts import vision as P
from .base import SYSTEM_FOR_CATEGORY, EvidenceRow, RESOURCE_RE, absorb, make_row, parse_time

VISION_CACHE = CACHE_DIR / "vision"
CACHE_VERSION = 2
CATEGORIES = set(SYSTEM_FOR_CATEGORY)


class VisionRow(BaseModel):
    resource_id: str
    category: str | None = None
    status_text: str = ""
    present: bool | None = None
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    email_hash: str | None = None
    customer_reference: str | None = None
    enabled: bool | None = None
    restore_allowed: bool | None = None
    anonymized: bool | None = None
    redacted: bool | None = None
    observed_at: str | None = None
    pointer: str = ""

    @field_validator("resource_id")
    @classmethod
    def _rid(cls, v: str) -> str:
        v = v.strip()
        if not RESOURCE_RE.fullmatch(v):
            raise ValueError(f"resource_id {v!r} is not a known record identifier")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        if v and v.strip().upper() not in CATEGORIES:
            raise ValueError(f"category {v!r} not in {sorted(CATEGORIES)}")
        return v.strip().upper() if v else None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", v.strip()):
            raise ValueError(f"email {v!r} is not an email address")
        return v.strip() if v else v


class VisionExtraction(BaseModel):
    rows: list[VisionRow] = Field(default_factory=list)
    detail_panel: dict[str, Any] = Field(default_factory=dict)


@dataclass
class VisionResult:
    file_id: str
    rows: list[dict] = field(default_factory=list)  # reconciled VisionRow dicts
    agreement: bool | None = None
    fallback_used: str = ""  # "", "pdf_text", "third_pass", "extraction_failed"
    disagreements: list[str] = field(default_factory=list)
    detail_panel: dict = field(default_factory=dict)
    error: str = ""


def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages).strip()


def _key(row: dict) -> tuple:
    norm = lambda v: re.sub(r"\s+", "", str(v)).lower() if v not in (None, "") else None  # noqa: E731
    return (row["resource_id"], row.get("present"), norm(row.get("email")), norm(row.get("phone")),
            norm(row.get("customer_reference")), norm(row.get("email_hash")),
            row.get("enabled"), row.get("restore_allowed"), row.get("anonymized"), row.get("redacted"))


def diff(a: VisionExtraction, b: VisionExtraction) -> list[str]:
    """Disagreements on resource ids, state, flags or identifiers (names are compared loosely: ignored)."""
    da = {r.resource_id: r.model_dump() for r in a.rows}
    db = {r.resource_id: r.model_dump() for r in b.rows}
    out = [f"{rid}: only in {'A' if rid in da else 'B'}" for rid in sorted(set(da) ^ set(db))]
    labels = ("resource_id", "present", "email", "phone", "customer_reference", "email_hash", "enabled",
              "restore_allowed", "anonymized", "redacted")
    for rid in sorted(set(da) & set(db)):
        ka, kb = _key(da[rid]), _key(db[rid])
        out += [f"{rid}.{labels[i]}: A={da[rid].get(labels[i])!r} B={db[rid].get(labels[i])!r}"
                for i in range(len(ka)) if ka[i] != kb[i]]
    return out


def _cache_path(file_id: str) -> Path:
    return VISION_CACHE / f"{file_id}.json"


def load_cached(file_id: str) -> VisionResult | None:
    p = _cache_path(file_id)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("version") != CACHE_VERSION:
        return None
    return VisionResult(d["file_id"], d["rows"], d["agreement"], d["fallback_used"], d["disagreements"],
                        d.get("detail_panel", {}), d.get("error", ""))


def _save(res: VisionResult, extra: dict) -> None:
    VISION_CACHE.mkdir(parents=True, exist_ok=True)
    d = {"version": CACHE_VERSION, **res.__dict__, **extra}
    _cache_path(res.file_id).write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n",
                                        encoding="utf-8", newline="\n")


def extract_file(llm, file_id: str, path: Path, model_a: str, model_b: str, *, refresh: bool = False) -> VisionResult:
    """Model A and B (different families); diff; third pass by model A with both outputs on disagreement."""
    from ..llm import BudgetExceeded, ExtractionFailed

    if not refresh:
        cached = load_cached(file_id)
        if cached is not None:
            return cached
    image, text = None, ""
    if path.suffix.lower() == ".pdf":
        text = pdf_text(path)
        if not text:
            raise_msg = "PDF has no text layer and PDF rasterisation is not installed"
            res = VisionResult(file_id, fallback_used="extraction_failed", error=raise_msg)
            _save(res, {})
            return res
    else:
        image = path
    prompt = P.TEXT_DOCUMENT.replace("{text}", text) if text else P.EXTRACT
    raw: dict[str, Any] = {"source": "pdf_text" if text else "image"}
    try:
        a = llm.structured(VisionExtraction, model_a, prompt, purpose="vision", item=file_id, image=image, max_tokens=6000)
        b = llm.structured(VisionExtraction, model_b, prompt, purpose="vision", item=file_id, image=image, max_tokens=6000)
        raw["model_a"], raw["model_b"] = a.model_dump(), b.model_dump()
        dis = diff(a, b)
        final, fallback = a, "pdf_text" if text else ""
        if dis:
            rp = (P.RECONCILE.replace("{a}", a.model_dump_json()).replace("{b}", b.model_dump_json())
                  .replace("{diff}", "\n".join(dis)))
            rp = rp + ("\n<document>\n" + text + "\n</document>\n" + P.EXTRACT.split("Reply with ONLY")[1]
                       if text else "\nReply with ONLY" + P.EXTRACT.split("Reply with ONLY")[1])
            final = llm.structured(VisionExtraction, model_a, rp, purpose="vision_reconcile", item=file_id,
                                   image=image, max_tokens=6000)
            raw["reconciled"] = final.model_dump()
            fallback = "third_pass"
        res = VisionResult(file_id, [r.model_dump() for r in final.rows], not dis, fallback, dis,
                           final.detail_panel)
    except (ExtractionFailed, BudgetExceeded) as exc:
        res = VisionResult(file_id, fallback_used="extraction_failed", error=str(exc)[:500])
        _save(res, raw)  # cached failure is retried only with --refresh-cache
        return res
    _save(res, {"raw": raw, "models": [model_a, model_b]})
    return res


def to_evidence_rows(res: VisionResult, file_captured_at, fmt: str) -> list[EvidenceRow]:
    """VisionRow dicts -> EvidenceRow; file_captured_at from the manifest so the index needs no special case."""
    merged: dict[str, dict] = {}  # one row per resource_id; non-null values from repeated rows win
    for r in res.rows:
        m = merged.setdefault(r["resource_id"], dict(r))
        for k, v in r.items():
            if m.get(k) in (None, "") and v not in (None, ""):
                m[k] = v
        if r.get("category") == "SUPPORT_ATTACHMENT":  # the more specific kind wins over SUPPORT_MESSAGE
            m["category"] = "SUPPORT_ATTACHMENT"
    out = []
    for i, r in enumerate(merged.values()):
        observed = parse_time(r.get("observed_at")) or file_captured_at
        present = r.get("present")
        row = make_row(res.file_id, observed, r["resource_id"], present=True if present is None else present, fmt=fmt,
                       category=r.get("category") or "",
                       pointer=r.get("pointer") or f"rows[{i}]", file_captured_at=file_captured_at)
        absorb(row, {k: r.get(k) for k in ("email", "name", "phone", "email_hash", "customer_reference")})
        if r.get("customer_reference") and r["customer_reference"] not in row.lookup_keys:
            row.lookup_keys.append(r["customer_reference"])
        for flag in ("enabled", "restore_allowed", "anonymized", "redacted"):
            if r.get(flag) is not None:
                row.flags[flag] = r[flag]
        if r.get("status_text"):
            row.flags["result"] = r["status_text"]
        out.append(row)
    return out


def extract_all(data, llm, cfg, *, refresh: bool = False, only_cached: bool = False) -> dict[str, VisionResult]:
    """Every PNG/PDF in the manifest. only_cached=True never calls the gateway (deterministic rebuild)."""
    results = {}
    for m in data.evidence_manifest.sort_values("file_id").itertuples(index=False):
        path = Path(data.root) / m.file_path
        if path.suffix.lower() not in (".png", ".pdf"):
            continue
        if only_cached:
            res = load_cached(m.file_id) or VisionResult(m.file_id, fallback_used="extraction_failed",
                                                         error="not extracted (run --extract-vision)")
        else:
            res = extract_file(llm, m.file_id, path, cfg.vision_model, cfg.vision_model_b, refresh=refresh)
        results[m.file_id] = res
    return results


def add_to_index(index, data, results: dict[str, VisionResult]) -> int:
    """Join vision rows into an EvidenceIndex exactly like text rows; returns rows added."""
    times = {m.file_id: m.captured_at.to_pydatetime() for m in data.evidence_manifest.itertuples(index=False)}
    n = 0
    for fid, res in sorted(results.items()):
        fmt = "vision:" + index.file_formats.get(fid, "image")
        index.file_times[fid] = times[fid]
        index.scopes.setdefault(fid, set())
        for row in to_evidence_rows(res, times[fid], fmt):
            index.add(row)
            n += 1
        if res.fallback_used == "extraction_failed":
            index.errors[fid] = f"extraction_failed: {res.error}"
        index.deferred.pop(fid, None)
    index.finalize()
    return n
