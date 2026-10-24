"""Log parser with dialect sniffing; joins *_started lookup keys to *_completed results by trace id."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import EvidenceRow, absorb, as_bool, classify_identifier, clean, make_row, parse_time
from .json_exports import ledger_row

KV_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S+)')
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(.*)$")
BRACKET_RE = re.compile(r"^\[(\w+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+(\w+):\s*(.*)$")
SYSLOG_RE = re.compile(r"^<\d+>\d+\s+(\S+)\s+(\S+)\s+(\S+)\s+-\s+-\s+(.*)$")
PIPE_SPLIT = re.compile(r"\s*\|\s*")

# Services that never describe customer data.
NOISE_SERVICES = {"log_router", "dns_cache", "secret_agent", "webhook_delivery", "thread_pool",
                  "feature_flags", "queue_consumer", "readback_collector", "timer", "cert_manager"}


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _kv(text: str) -> dict[str, str]:
    return {k: _unquote(v) for k, v in KV_RE.findall(text)}


def parse_line(line: str) -> tuple[str, dict[str, str]] | None:
    """Return (dialect, fields) where fields always carries ts/service/trace/event when known."""
    m = TS_RE.match(line.strip())
    if not m:
        return None
    ts, rest = m.groups()
    if rest.startswith("{"):
        f = {k: str(v) for k, v in json.loads(rest).items()}
        f.setdefault("trace", f.get("trace_id", ""))
        dialect = "jsonl"
    elif rest.startswith("["):
        b = BRACKET_RE.match(rest)
        if not b:
            return None
        level, service, trace, event, tail = b.groups()
        f = {"level": level, "service": service, "trace": trace, "event": event, **_kv(tail)}
        dialect = "bracket"
    elif rest.startswith("<"):
        s = SYSLOG_RE.match(rest)
        if not s:
            return None
        _node, service, trace, tail = s.groups()
        f = {"service": service, "trace": trace, **_kv(tail)}
        dialect = "syslog"
    elif rest.startswith(("DEBUG |", "INFO |", "WARN |", "ERROR |")) or rest.count(" | ") >= 4:
        parts = PIPE_SPLIT.split(rest.lstrip("| "), maxsplit=4)
        level, service, trace, event, tail = (parts + [""] * 5)[:5]
        f = {"level": level, "service": service, "trace": trace, "event": event, **_kv(tail)}
        dialect = "pipe"
    else:
        f = _kv(rest)
        if "message" in f and "requestId" in f:  # cloud runtime: nested kv inside message
            inner = _kv(f.pop("message"))
            f = {"service": f.get("function", ""), "trace": f.get("requestId", ""), **f, **inner}
            dialect = "cloud"
        else:
            f.setdefault("trace", f.get("trace_id", ""))
            dialect = "record_lookup" if f.get("event") == "record_lookup" else "kv"
        if "level" not in f:
            first = rest.split(" ", 1)[0]
            if first in ("DEBUG", "INFO", "WARN", "ERROR"):
                f["level"] = first
    f["ts"] = ts
    return dialect, f


def _state(row: EvidenceRow, f: dict[str, str]) -> None:
    """Fold one log line's fields into the row's present flag and state flags."""
    fl = row.flags
    if "http_status" in f:
        fl["http_status"] = int(f["http_status"])
        row.present = f["http_status"].startswith("2")
    if "rows" in f and f["rows"].isdigit() and "http_status" not in f:
        row.present = int(f["rows"]) > 0
    res = (f.get("result") or "").lower()
    if res in ("hit", "miss") and f.get("event", "").startswith("index_query"):
        fl["index_hit"] = res == "hit"
        row.present = res == "hit"
    if "total_hits" in f and f["total_hits"].isdigit():
        fl["index_hit"] = int(f["total_hits"]) > 0
        row.present = fl["index_hit"]
    for key in ("enabled", "restore_allowed"):
        if key in f and as_bool(f[key]) is not None:
            fl[key] = as_bool(f[key])
            row.present = True if row.present is None else row.present
    if "archive_present" in f:
        row.present = as_bool(f["archive_present"])
    if f.get("eligible") is not None and f.get("deletion_block") is not None:
        fl["restore_allowed"] = as_bool(f["eligible"]) and not as_bool(f["deletion_block"])
        row.present = True
    if f.get("decision"):
        fl["restore_allowed"] = f["decision"].lower() == "allow"
        row.present = True
    if "available" in f:
        fl["download_available"] = as_bool(f["available"])
        row.present = True
    if "marker_found" in f:
        fl["deletion_marker"] = as_bool(f["marker_found"])
        row.present = not fl["deletion_marker"]
    if f.get("detector") == "direct_identifier" or f.get("event", "").endswith("_pii_scan"):
        row.present = True
        fl["redacted"] = False
        kind = classify_identifier(f.get("matched_value"))
        if kind and not row.identifiers.get(kind):
            row.identifiers[kind] = f["matched_value"]  # the scanner found it in the record content
        if row.category == "ANALYTICS_PROFILE":
            fl["anonymized"] = False
    if "direct_identifiers" in f and f["direct_identifiers"].isdigit():
        row.present = True
        fl["anonymized"] = int(f["direct_identifiers"]) == 0
    if f.get("message_text") == "[REDACTED]":
        row.present = True
        fl["redacted"] = True
    if f.get("integrity_check"):
        fl["integrity_check"] = f["integrity_check"]
    if "email_opt_in" in f:
        row.present = True
    # A completed read that returned the record with no negative signal means the record exists.
    if row.present is None and f.get("event", "").endswith(("_read_completed", "_query_completed", "_loaded")):
        row.present = True


def parse_log(path: Path, file_id: str, file_captured_at) -> list[EvidenceRow]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        p = parse_line(line)
        if p is None:
            raise ValueError(f"line {n}: unrecognised log dialect: {line[:80]}")
        parsed.append((n, *p))

    rows: list[EvidenceRow] = []
    # Lookup keys announced by *_started lines, keyed by trace id.
    started: dict[str, dict[str, str]] = {}
    for n, dialect, f in parsed:
        if f.get("event", "").endswith("_started") and f.get("trace"):
            started.setdefault(f["trace"], {}).update(f)

    by_key: dict[tuple[str, str], EvidenceRow] = {}
    for n, dialect, f in parsed:
        rid = clean(f.get("resource_id"))
        if not rid or f.get("service") in NOISE_SERVICES:
            continue
        if dialect == "record_lookup":
            rows.append(ledger_row(file_id, file_captured_at, recorded_at=f["ts"], system=f.get("system", ""),
                                   resource_id=rid, record_type=f.get("record_type", ""),
                                   result=f.get("result", ""), reference=f.get("subject_reference", ""),
                                   fmt="log:record_lookup", pointer=f"line {n}"))
            continue
        trace = f.get("trace") or ""
        key = (trace or f"line{n}", rid)
        row = by_key.get(key)
        if row is None:
            row = make_row(file_id, f["ts"], rid, present=None, fmt=f"log:{dialect}",
                           pointer=f"line {n} trace={trace}", file_captured_at=file_captured_at)
            if "attachment" in f.get("event", "") or f.get("file", "").endswith(".pdf"):
                row.category = "SUPPORT_ATTACHMENT" if row.system_id == "support_platform" else row.category
            by_key[key] = row
            rows.append(row)
            if trace in started:
                absorb(row, {k: v for k, v in started[trace].items() if k in _LOOKUP_ONLY})
        else:
            row.captured_at = parse_time(f["ts"]) or row.captured_at
            row.pointer += f",{n}"
        content = {k: v for k, v in f.items() if k not in _LOOKUP_ONLY and k not in _META}
        absorb(row, content)
        absorb(row, {k: v for k, v in f.items() if k in _LOOKUP_ONLY})
        _state(row, f)
    return rows, set()


# Fields that name what was searched for, not what the record contains.
_LOOKUP_ONLY = {"lookup_key", "match_key", "subject_key", "scan_key", "correlation_key", "matched_value",
                "subject_ref"}
_META = {"ts", "service", "trace", "trace_id", "level", "severity", "logger", "instance", "pod", "region",
         "event", "requestId", "function", "attempt"}
