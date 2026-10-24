"""CLI entry point for the Ghost Data Still Exists deletion-audit agent.

Usage:  python code/main.py --counts
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghost.config import DATASET_DIR, load_config  # noqa: E402
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion-audit agent")
    parser.add_argument("--counts", action="store_true", help="print dataset table counts")
    args = parser.parse_args()
    if args.counts:
        return cmd_counts()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
