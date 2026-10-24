"""CLI entry point for the Ghost Data Still Exists deletion-audit agent.

Usage:  python code/main.py --counts
        python code/main.py --subject <email>
        python code/main.py --identity-check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghost.config import DATASET_DIR, load_config  # noqa: E402
from ghost.identity import build_index  # noqa: E402
from ghost.load import check_case_order, load_all  # noqa: E402


def email_resolution_split(data) -> dict[str, int]:
    current = {e.strip().lower() for e in data.identities["email"]}
    hist_rows = data.audit_log[data.audit_log["field_name"] == "email"]
    historical = {v.strip().lower() for v in [*hist_rows["old_value"], *hist_rows["new_value"]] if v}
    split = {"current": 0, "historical": 0, "none": 0}
    for email in data.requests["email"]:
        e = email.strip().lower()
        split["current" if e in current else "historical" if e in historical else "none"] += 1
    return split


def cmd_counts() -> int:
    data = load_all(DATASET_DIR)
    print("Table row counts")
    for name in ["requests", "sample_requests", "sample_output", "identities", "audit_log",
                 "activity", "rules", "evidence_manifest", "output_template"]:
        print(f"  {name:<18} {len(getattr(data, name)):>5}")
    print(f"Distinct audit_at (requests): {data.requests['audit_at'].nunique()}")
    print(f"Request email resolution: {email_resolution_split(data)}")
    print("reported_status distribution:")
    for status, n in data.requests["reported_status"].value_counts().sort_index().items():
        print(f"  {status:<20} {n:>4}")
    print(f"Case order: {check_case_order(data)}")
    cfg = load_config()
    print(f"LLM gateway configured: {bool(cfg.llm_base_url)}; API key present: {cfg.has_api_key}")
    return 0


def cmd_subject(email: str) -> int:
    data = load_all(DATASET_DIR)
    index = build_index(data)
    s = index.resolve_email(email)
    if s is None:
        print(f"UNRESOLVED: {email}")
        return 1
    print(f"user_id: {s.user_id}  name: {s.name}  path: {index.resolution_path(email, s)}")
    for label, values in [("emails", s.emails), ("phones", s.phones), ("email_hashes", s.email_hashes),
                          ("account_ids", s.account_ids), ("resource_ids", s.resource_ids)]:
        print(f"{label}:")
        for v in sorted(values):
            print(f"  {v}  <- {', '.join(s.sources.get(v, []))}")
    act = data.activity
    rows = act[act["resource_id"].isin(s.resource_ids)].sort_values(["event_time", "activity_id"])
    print(f"activity rows touching resource ids: {len(rows)}")
    for r in rows.itertuples(index=False):
        print(f"  {r.activity_id} {r.event_time:%Y-%m-%dT%H:%M:%SZ} {r.event_type} {r.resource_id} "
              f"{r.reported_result} | {r.details}")
    return 0


def cmd_identity_check() -> int:
    """Resolve every request email; compare sample account ids against linked accounts."""
    import json
    from collections import Counter

    data = load_all(DATASET_DIR)
    index = build_index(data)
    paths, unresolved = Counter(), []
    for email in data.requests["email"]:
        s = index.resolve_email(email)
        if s is None:
            unresolved.append(email)
        else:
            paths[index.resolution_path(email, s)] += 1
    print(f"Requests: {len(data.requests)}  resolved: {sum(paths.values())}  unresolved: {len(unresolved)}")
    print(f"Resolution path: {dict(sorted(paths.items()))}")
    print(f"Ambiguous emails (shared by >1 user): {len(index.ambiguous_emails())}")
    out = dict(zip(data.sample_output["case_id"], data.sample_output["steps_json"]))
    linked = missing = 0
    print("Sample account linkage:")
    for r in data.sample_requests.itertuples(index=False):
        s = index.resolve_email(r.email)
        steps = json.loads(out.get(r.case_id, "[]") or "[]")
        accts = sorted({st["resource_id"] for st in steps if st["resource_id"].startswith("account_")})
        uid = s.user_id if s else "UNRESOLVED"
        have = sorted(set(accts) & (s.account_ids if s else set()))
        status = "n/a (no account step)" if not accts else "LINKED" if have == accts else "NOT LINKED YET"
        linked += status == "LINKED"
        missing += status == "NOT LINKED YET"
        print(f"  {r.case_id:<8} {uid:<10} expected={','.join(accts) or '-':<14} {status}")
    print(f"Samples linked: {linked}  not linked yet (Phase 2 input): {missing}")
    return 0 if not unresolved else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion-audit agent")
    parser.add_argument("--counts", action="store_true", help="print dataset table counts")
    parser.add_argument("--subject", metavar="EMAIL", help="print the resolved subject for an email")
    parser.add_argument("--identity-check", action="store_true", help="Phase 1 identity checks")
    args = parser.parse_args()
    if args.counts:
        return cmd_counts()
    if args.subject:
        return cmd_subject(args.subject)
    if args.identity_check:
        return cmd_identity_check()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
