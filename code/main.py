"""CLI entry point for the Ghost Data Still Exists deletion-audit agent.

Usage:  python code/main.py --counts
        python code/main.py --subject <email>
        python code/main.py --identity-check
        python code/main.py --evidence <resource_id>
        python code/main.py --coverage
        python code/main.py --discovery
        python code/main.py --grade [--analytics-hypothesis H]
        python code/main.py --case <case_id>
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


def cmd_evidence(resource_id: str) -> int:
    from ghost.evidence import build_evidence_index

    index = build_evidence_index(load_all(DATASET_DIR))
    rows = index.rows_for(resource_id)
    print(f"{resource_id}: {len(rows)} rows")
    for r in rows:
        flags = {k: v for k, v in r.flags.items() if v is not None}
        ids = {k: v for k, v in r.identifiers.items() if v}
        print(f"  {r.file_id:<12} file@{r.file_captured_at:%Y-%m-%dT%H:%M:%SZ} obs@{r.captured_at:%Y-%m-%dT%H:%M:%SZ} "
              f"{r.fmt:<22} {r.system_id}/{r.category} present={r.present}")
        print(f"      ids={ids} lookup={r.lookup_keys} flags={flags} at {r.pointer}")
    return 0 if rows else 1


def cmd_coverage() -> int:
    """Per-file row counts, per-format parse errors, and the sample citation check."""
    import json
    from collections import Counter

    from ghost.evidence import build_evidence_index

    data = load_all(DATASET_DIR)
    index = build_evidence_index(data)
    manifest = data.evidence_manifest.set_index("file_id")
    print("Per-file rows")
    for fid in sorted(index.file_formats):
        n = len(index.by_file.get(fid, []))
        state = "deferred (Phase 4)" if fid in index.deferred else index.errors.get(fid, "ok")
        print(f"  {fid:<12} {index.file_formats[fid]:<6} {n:>4}  {manifest.loc[fid, 'file_path']:<62} {state}")
    errs = Counter(index.file_formats[f] for f in index.errors)
    fmts = Counter(index.file_formats.values())
    print("Per-format files / parse errors")
    for fmt in sorted(fmts):
        print(f"  {fmt:<6} files={fmts[fmt]:>3} errors={errs.get(fmt, 0)}")
    print(f"Total rows: {len(index.rows)}  distinct resources: {len(index.by_resource)}")

    audit = dict(zip(data.sample_requests["case_id"], data.sample_requests["audit_at"]))
    cited_ok, cited_bad, nowhere, omitted = 0, [], set(), 0
    for r in data.sample_output.itertuples(index=False):
        for st in json.loads(r.steps_json or "[]"):
            rid, eid = st["resource_id"], st["evidence_id"]
            if not index.by_resource.get(rid):
                nowhere.add((rid, eid or "-", r.case_id))
            if not eid:
                continue
            hit = [x for x in index.by_file.get(eid, []) if x.resource_id == rid]
            if not hit and st["state"] == "ABSENT" and index.absent_by_omission(eid, rid):
                hit, omitted = ["absent by omission"], omitted + 1
            fca = manifest.loc[eid, "captured_at"] if eid in manifest.index else None
            if hit and fca is not None and fca <= audit[r.case_id]:
                cited_ok += 1
            else:
                why = "deferred image/pdf" if eid in index.deferred else "no row" if not hit else "after audit_at"
                cited_bad.append((r.case_id, st["step_no"], eid, rid, why))
    print(f"Sample cited steps: ok={cited_ok} (absent-by-omission {omitted}) failing={len(cited_bad)}")
    for c in cited_bad:
        print(f"  FAIL {c[0]} step {c[1]}: {c[2]} / {c[3]} ({c[4]})")
    print(f"Sample resources with no explicit row in any text file: {len(nowhere)}")
    for rid, eid, case in sorted(nowhere):
        how = ("absent by omission" if eid != "-" and index.absent_by_omission(eid, rid)
               else "Phase 4 image/pdf" if eid in index.deferred
               else "uncited (needs discovery link)" if eid == "-" else "?")
        print(f"  {rid:<20} cited={eid:<12} {case:<8} [{index.file_formats.get(eid, '-')}] {how}")
    text_errors = [f for f in index.errors if f not in index.deferred]
    unexpected = [c for c in cited_bad if c[4] != "deferred image/pdf"]
    return 0 if not text_errors and not unexpected else 1


def cmd_discovery() -> int:
    """Phase 2b: candidate-set histogram over the evaluation set and the sample account check."""
    import json

    from ghost.discovery import discover, histogram
    from ghost.evidence import build_evidence_index

    data = load_all(DATASET_DIR)
    results = discover(data, build_index(data), build_evidence_index(data))
    eval_ids = list(data.requests["case_id"])
    hist = histogram(results, eval_ids)
    print(f"Candidate-set size histogram over {len(eval_ids)} evaluation cases")
    for size in sorted(hist):
        print(f"  {size:>2} candidates: {hist[size]:>4}")
    amb = sum(results[c].ambiguous for c in eval_ids)
    print(f"Ambiguous (tentative choice, Phase 4 triage): {amb}  resolved: {sum(1 for c in eval_ids if results[c].chosen_account and not results[c].ambiguous)}")
    print(f"Mean non-account resources per subject: "
          f"{sum(len(results[c].resources) for c in eval_ids) / len(eval_ids):.1f}")
    out = dict(zip(data.sample_output["case_id"], data.sample_output["steps_json"]))
    tally = {"exact": 0, "contained": 0, "miss": 0, "n/a": 0}
    print("Sample accounts (expected vs discovered)")
    for cid in data.sample_requests["case_id"]:
        d = results[cid]
        steps = json.loads(out.get(cid, "[]") or "[]")
        exp = sorted({st["resource_id"] for st in steps if st["resource_id"].startswith("account_")})
        if not exp:
            verdict = "n/a"
        elif d.chosen_account in exp:
            verdict = "exact"
        elif set(exp) & set(d.account_candidates):
            verdict = "contained"
        else:
            verdict = "miss"
        tally[verdict] += 1
        print(f"  {cid:<8} expected={','.join(exp) or '-':<13} chosen={d.chosen_account or '-':<13} "
              f"cands={len(d.account_candidates)} {verdict:<9} {d.reason}")
    print(f"Samples: {tally}  (contained includes exact: {tally['exact'] + tally['contained']})")
    return 0 if tally["miss"] == 0 else 1


def _audits(hypothesis=None):
    import pandas as pd

    from ghost.discovery import discover
    from ghost.engine import ANALYTICS_HYPOTHESIS, audit_all
    from ghost.evidence import build_evidence_index

    data = load_all(DATASET_DIR)
    index = build_evidence_index(data)
    results = discover(data, build_index(data), index)
    reqs = pd.concat([data.requests, data.sample_requests], ignore_index=True)
    # Phase 3: intent is assumed DELETION for every case (the classifier arrives in Phase 4).
    audits = audit_all(reqs, results, index, data.rules, data.activity,
                       analytics_hypothesis=hypothesis or ANALYTICS_HYPOTHESIS)
    return data, index, audits


def cmd_grade(hypothesis=None) -> int:
    """Phase 3: grade the 32 samples against sample_output.csv."""
    from ghost.grade import grade, report

    data, index, audits = _audits(hypothesis)
    pred = {c: (audits[c].status, audits[c].steps()) for c in data.sample_requests["case_id"]}
    rows = list(data.sample_output[["case_id", "deletion_status", "steps_json"]].itertuples(index=False))
    summary, cases = grade(rows, pred, index.file_formats)
    print(report(summary, cases))
    failing = [c for c in cases if not c.exact]
    print(f"Failing: {[c.case_id for c in failing]}")
    print("Failure causes (text-only = every expected resource has a text row and no tie is involved):")
    text_only_fail = []
    for c in failing:
        causes = []
        if any(t[5] in index.deferred for t in c.expected):
            causes.append("cites PNG/PDF evidence (Phase 4)")
        missing = sorted({t[2] for t in c.expected if not index.by_resource.get(t[2])})
        if missing:
            causes.append(f"no row in any text file: {','.join(missing)} (Phase 4 vision)")
        a = audits[c.case_id]
        exp_acc = {t[2] for t in c.expected if t[2].startswith("account_")}
        got_acc = {t[2] for t in c.got if t[2].startswith("account_")}
        if exp_acc != got_acc and any("account choice tentative" in n for n in a.notes):
            causes.append(f"ambiguous account, tentative {','.join(sorted(got_acc))} vs {','.join(sorted(exp_acc))}")
        ties = [n for n in a.notes if "tentatively linked" in n]
        if ties and {t[2] for t in c.expected} ^ {t[2] for t in c.got} - exp_acc - got_acc:
            causes.append("tentative tie on a policy-linked record")
        if not causes:
            text_only_fail.append(c.case_id)
            causes.append("TEXT-ONLY FAILURE")
        print(f"  {c.case_id}: {'; '.join(causes)}")
    print(f"Text-only failures: {text_only_fail or 'none'}")
    return 0 if not text_only_fail else 1


def cmd_case(case_id: str) -> int:
    from ghost.engine import describe

    _, _, audits = _audits()
    if case_id not in audits:
        print(f"unknown case {case_id}")
        return 1
    print(describe(audits[case_id]))
    print(audits[case_id].steps_json())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists deletion-audit agent")
    parser.add_argument("--counts", action="store_true", help="print dataset table counts")
    parser.add_argument("--subject", metavar="EMAIL", help="print the resolved subject for an email")
    parser.add_argument("--identity-check", action="store_true", help="Phase 1 identity checks")
    parser.add_argument("--evidence", metavar="RESOURCE_ID", help="print all evidence rows for a resource")
    parser.add_argument("--coverage", action="store_true", help="Phase 2 parser coverage and sample citation check")
    parser.add_argument("--discovery", action="store_true", help="Phase 2b account discovery check")
    parser.add_argument("--grade", action="store_true", help="Phase 3 sample grader")
    parser.add_argument("--analytics-hypothesis", choices=["attempted_delete", "always_anonymize"])
    parser.add_argument("--case", metavar="CASE_ID", help="print the CaseAudit for one case")
    args = parser.parse_args()
    if args.counts:
        return cmd_counts()
    if args.subject:
        return cmd_subject(args.subject)
    if args.identity_check:
        return cmd_identity_check()
    if args.evidence:
        return cmd_evidence(args.evidence)
    if args.coverage:
        return cmd_coverage()
    if args.discovery:
        return cmd_discovery()
    if args.grade:
        return cmd_grade(args.analytics_hypothesis)
    if args.case:
        return cmd_case(args.case)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
