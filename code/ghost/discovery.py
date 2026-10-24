"""Account discovery: tie every request to its subject's account_* id and resource footprint.

Signals, applied in order (no LLM anywhere in this module):
 1. Evidence ownership - an evidence row whose identifiers / lookup keys resolve to exactly one subject
    attaches its resource to that subject (any capture time: linkage is not state).
 2. Activity window - the deletion_worker DELETE_RECORD (or privacy_intake CLASSIFY_REQUEST) on an
    account_* between requested_at and reported_at; the reported_result matching reported_status is a
    preference, never a filter.
 3. Elimination - drop accounts owned by another subject and accounts uniquely assigned to another
    subject's case; iterate to a fixed point over all requests (evaluation + samples).
 4. Residual ambiguity - keep the candidate set, choose tentatively by preference, and record why.
 5. Policy-action linkage - records with no identifier left (an anonymized analytics profile) are tied to a
    case when the deletion_worker acted on them inside the case window and a subject-ordered listing places
    them between the records of known owners (see link_policy_actions).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from .evidence.base import USER_RE, classify_identifier
from .identity import IdentityIndex, Subject

RESULT_FOR_STATUS = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
WINDOW_EVENTS = {("DELETE_RECORD", "deletion_worker"), ("CLASSIFY_REQUEST", "privacy_intake")}
SOURCE_EVIDENCE = "evidence"
SOURCE_PATTERN = "story numbering"
# The user_0N <-> account_00N numbering holds only for the first ten hand-written story users
# (prompts.md Phase 2b); it is used only when an evidence row confirms it and nothing else owns the user.
STORY_USERS = 10
# Story workflows log the DELETE_RECORD a few minutes after the status report (case_02 +5 min, case_10 +1 min).
REPORT_LAG = pd.Timedelta(minutes=15)
# Owned accounts land 44-75 min before reported_at (248 ownership-confirmed evaluation cases, all 32 samples
# within -8..74), but some clusters log the account activity 2h05-2h15 before reported_at; hits in this band
# are preferred over older hits from other clusters in a multi-day window.
NEAR_REPORT_MIN = 150
# Policy actions on dependent records land between 29 min before and 114 min after reported_at (samples).
POLICY_BEFORE = pd.Timedelta(minutes=90)
POLICY_AFTER = pd.Timedelta(minutes=150)
# Story workflows log their policy actions within minutes of the status report (samples: -6..+10 min).
STORY_MATCH = 15
POLICY_EVENTS = {"ANONYMIZE_RECORD", "REDACT_RECORD", "DELETE_RECORD", "DISABLE_DATA_FLOW", "BLOCK_RESTORE",
                 "CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS", "RETAIN_RECORD"}
SOURCE_POLICY = "policy action"


@dataclass(frozen=True)
class WindowHit:
    account_id: str
    activity_id: str
    event_type: str
    event_time: datetime
    reported_result: str
    result_match: bool
    minutes_before_report: float


@dataclass
class Discovery:
    case_id: str
    subject: Subject | None
    account_candidates: list[str] = field(default_factory=list)
    chosen_account: str | None = None
    reason: str = ""
    ambiguous: bool = False  # hook for Phase 4 triage
    resources: list[str] = field(default_factory=list)
    window: list[WindowHit] = field(default_factory=list)


def _owners(value: str, ids: IdentityIndex) -> set[str]:
    kind = classify_identifier(value)
    if kind == "customer_reference" and USER_RE.match(value.strip()):
        return {value.strip()} if value.strip() in ids.subjects else set()
    s = (ids.resolve_email(value) if kind == "email" else ids.resolve_hash(value.removeprefix("sha256:"))
         if kind == "email_hash" else ids.resolve_phone(value) if kind == "phone" else None)
    return {s.user_id} if s else set()


def attach_evidence_ownership(ids: IdentityIndex, evidence) -> dict[str, set[str]]:
    """Signal 1. Returns resource_id -> owning user_ids (len > 1 = contested, attached to nobody)."""
    owners: dict[str, set[str]] = {}
    via: dict[tuple[str, str], str] = {}
    for row in evidence.rows:
        values = [v for k, v in row.identifiers.items() if v and k != "name"] + list(row.lookup_keys)
        uids = set().union(*(_owners(v, ids) for v in values)) if values else set()
        if len(uids) != 1:
            if len(uids) > 1:
                owners.setdefault(row.resource_id, set()).update(uids)
            continue
        uid = next(iter(uids))
        owners.setdefault(row.resource_id, set()).add(uid)
        via.setdefault((row.resource_id, uid), row.file_id)
    for rid, uids in sorted(owners.items()):
        if len(uids) == 1:
            uid = next(iter(uids))
            ids.subjects[uid].add_resource(rid, f"{SOURCE_EVIDENCE}:{via[(rid, uid)]}")
    ids.reindex()
    return owners


def window_hits(activity, requested_at, reported_at, reported_status: str) -> list[WindowHit]:
    """Signal 2: account activities inside [requested_at, reported_at]."""
    want = RESULT_FOR_STATUS.get(reported_status, "")
    a = activity[(activity["event_time"] >= requested_at) & (activity["event_time"] <= reported_at + REPORT_LAG)
                 & activity["resource_id"].str.startswith("account_")]
    hits = []
    for r in a.sort_values(["event_time", "activity_id"]).itertuples(index=False):
        if (r.event_type, r.source_system) not in WINDOW_EVENTS:
            continue
        hits.append(WindowHit(r.resource_id, r.activity_id, r.event_type, r.event_time.to_pydatetime(),
                              r.reported_result, r.reported_result == want,
                              (reported_at - r.event_time).total_seconds() / 60))
    return hits


def story_pattern(ids: IdentityIndex, owners: dict[str, set[str]], evidence) -> dict[str, tuple[str, str]]:
    """user_id -> (account_id, confirming file) for story users, if any evidence row confirms the pattern."""
    confirm = ""
    for rid, uids in sorted(owners.items()):
        num = rid.removeprefix("account_")
        if rid.startswith("account_") and len(uids) == 1 and num.isdigit() and int(num) <= STORY_USERS:
            uid = next(iter(uids))
            if uid.removeprefix("user_").isdigit() and int(uid.removeprefix("user_")) == int(num):
                confirm = ids.subjects[uid].sources.get(rid, [""])[0]
                break
    if not confirm:
        return {}
    out = {}
    for uid in ids.subjects:
        n = uid.removeprefix("user_")
        if n.isdigit() and 1 <= int(n) <= STORY_USERS:
            out[uid] = (f"account_{int(n):03d}", confirm)
    return out


def discover(data, ids: IdentityIndex, evidence) -> dict[str, Discovery]:
    """Run signals 1-4 over evaluation + sample requests; returns case_id -> Discovery."""
    owners = attach_evidence_ownership(ids, evidence)
    owned_by = {rid: next(iter(u)) for rid, u in owners.items() if len(u) == 1 and rid.startswith("account_")}
    pattern = story_pattern(ids, owners, evidence)

    reqs = pd.concat([data.requests, data.sample_requests], ignore_index=True)
    out: dict[str, Discovery] = {}
    for r in reqs.itertuples(index=False):
        s = ids.resolve_email(r.email)
        d = Discovery(case_id=r.case_id, subject=s)
        d.window = window_hits(data.activity, r.requested_at, r.reported_at, r.reported_status)
        own = sorted(s.account_ids) if s else []
        pat = pattern.get(s.user_id) if s else None
        if own:
            d.account_candidates = own
            d.reason = "evidence ownership: " + ", ".join(f"{a}<-{'|'.join(s.sources.get(a, []))}" for a in own)
        elif pat and owned_by.get(pat[0]) in (None, s.user_id):
            d.account_candidates = [pat[0]]
            d.reason = f"{SOURCE_PATTERN} {s.user_id}->{pat[0]} (pattern confirmed by {pat[1]})"
        else:
            uid = s.user_id if s else None
            free = [h for h in d.window if owned_by.get(h.account_id) in (None, uid)]
            near = [h for h in free if h.minutes_before_report <= NEAR_REPORT_MIN]
            d.account_candidates = sorted({h.account_id for h in (near or free)})
            d.reason = (f"activity window ({len(near)} of {len(free)} unowned hits within {NEAR_REPORT_MIN} min "
                        f"of reported_at)" if near else f"activity window ({len(free)} unowned hits, none near report)")
        out[r.case_id] = d

    # Signal 3: fixed-point elimination keyed by subject (one user may file several requests).
    changed = True
    while changed:
        changed = False
        assigned: dict[str, set[str]] = {}
        for d in out.values():
            if len(d.account_candidates) == 1:
                assigned.setdefault(d.account_candidates[0], set()).add(d.subject.user_id if d.subject else d.case_id)
        for d in out.values():
            if len(d.account_candidates) < 2:
                continue
            me = d.subject.user_id if d.subject else d.case_id
            keep = [a for a in d.account_candidates if assigned.get(a, {me}) == {me}]
            if keep and keep != d.account_candidates:
                dropped = sorted(set(d.account_candidates) - set(keep))
                d.account_candidates = keep
                d.reason += f"; eliminated {','.join(dropped)} (assigned elsewhere)"
                changed = True

    # Signal 4: residual ambiguity. Unique sets are final; the rest get a tentative one-to-one assignment
    # (one account per subject, cheapest first: result-matched, then nearest to reported_at).
    taken = {d.account_candidates[0]: (d.subject.user_id if d.subject else d.case_id)
             for d in out.values() if len(d.account_candidates) == 1}
    pairs = []
    for d in out.values():
        if len(d.account_candidates) == 1:
            d.chosen_account = d.account_candidates[0]
        elif d.account_candidates:
            d.ambiguous = True
            hits = {h.account_id: h for h in d.window}
            for a in d.account_candidates:
                h = hits.get(a)
                cost = (0 if h and h.result_match else 1, abs(h.minutes_before_report) if h else 1e9)
                pairs.append((cost, d.case_id, a))
        else:
            d.reason += "; no candidate"
    by_subject: dict[str, str] = {}
    for cost, cid, a in sorted(pairs):
        d = out[cid]
        me = d.subject.user_id if d.subject else cid
        if d.chosen_account or taken.get(a, me) != me:
            continue
        if me in by_subject and by_subject[me] != a:
            continue
        d.chosen_account, taken[a], by_subject[me] = a, me, a
        d.reason += (f"; AMBIGUOUS {len(d.account_candidates)} candidates, tentatively chose {a} "
                     f"({'result-matched' if cost[0] == 0 else 'no result match'}, "
                     f"{cost[1]:.0f} min from reported_at, one-to-one assignment)")
    leftover_pass(data, out, taken, by_subject)
    for d in out.values():
        if not d.chosen_account:
            d.reason += "; account unknown (no orphan account activity in the request window)"
        if d.subject:
            d.resources = sorted((d.subject.resource_ids - d.subject.account_ids)
                                 | ({d.chosen_account} if d.chosen_account else set()))
    link_policy_actions(data, out, owners, evidence)
    return out


def leftover_pass(data, out: dict[str, Discovery], taken: dict[str, str], by_subject: dict[str, str]) -> None:
    """Signal 4b: unchosen cases take orphan account activities (window events on accounts chosen by no case)
    inside [requested_at, reported_at + REPORT_LAG]; result-matched first, then nearest to reported_at,
    assigned one-to-one across the leftover cases."""
    left = [d for d in out.values() if not d.chosen_account and d.subject and d.subject.user_id not in by_subject]
    if not left:
        return
    chosen = {d.chosen_account for d in out.values() if d.chosen_account}
    reqs = pd.concat([data.requests, data.sample_requests], ignore_index=True).set_index("case_id")
    pairs, pools = [], {}
    for d in left:
        r = reqs.loc[d.case_id]
        hits = [h for h in window_hits(data.activity, r.requested_at, r.reported_at, r.reported_status)
                if h.account_id not in chosen and h.account_id not in taken]
        pools[d.case_id] = sorted({h.account_id for h in hits})
        for h in hits:
            pairs.append(((0 if h.result_match else 1, abs(h.minutes_before_report)), d.case_id, h.account_id))
    used: set[str] = set()
    for cost, cid, a in sorted(pairs):
        d = out[cid]
        if d.chosen_account or a in used or d.subject.user_id in by_subject:
            continue
        d.chosen_account, d.ambiguous = a, True
        used.add(a)
        taken[a], by_subject[d.subject.user_id] = d.subject.user_id, a
        d.reason += (f"; AMBIGUOUS leftover pass: orphan pool {','.join(pools[cid])}, chose {a} "
                     f"({'result-matched' if cost[0] == 0 else 'no result match'}, "
                     f"{cost[1]:.0f} min from reported_at)")


def _user_no(uid: str) -> int:
    n = uid.removeprefix("user_")
    return int(n) if n.isdigit() else -1


def ordered_listings(evidence, owned: dict[str, str]) -> dict[str, list[tuple[str, int]]]:
    """listing key -> [(resource_id, position)] for files whose listings are ordered by subject.

    A file qualifies when every listing with >= 2 owned rows is strictly increasing in owner user number and
    at least one listing has >= 3 owned rows (evidence_02 lists every collection in user order)."""
    by_listing: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for row in evidence.rows:
        head, sep, tail = row.pointer.rpartition("[")
        if not sep or not tail.rstrip("]").isdigit():
            continue
        by_listing.setdefault((row.file_id, head), []).append((int(tail.rstrip("]")), row.resource_id))
    files: dict[str, list[bool]] = {}
    for (fid, _), items in by_listing.items():
        nums = [_user_no(owned[r]) for _, r in sorted(items) if r in owned]
        if len(nums) >= 2:
            files.setdefault(fid, []).append(len(nums) >= 3 and nums == sorted(set(nums)))
            if nums != sorted(set(nums)):
                files[fid].append(None)
    good = {f for f, v in files.items() if None not in v and any(v)}
    return {f"{fid}:{head}": [(r, i) for i, r in sorted(items)]
            for (fid, head), items in by_listing.items() if fid in good}


def link_policy_actions(data, out: dict[str, "Discovery"], owners: dict[str, set[str]], evidence) -> None:
    """Signal 5: attach unowned non-account records to subjects through deletion_worker policy actions.

    Candidates for a record = subjects of cases whose window [reported_at - POLICY_BEFORE,
    reported_at + POLICY_AFTER] holds a policy action on it, who own no other record of that system, and
    whose own policy actions fall on the same side of reported_at (a workflow either finishes its policy
    actions before the status report or runs them all afterwards). Then, to a fixed point:
     - a candidate within STORY_MATCH of its reported_at beats candidates further away;
     - in a subject-ordered listing (ordered_listings) user numbers must increase along the listing, so
       each record's candidates are bounded by its neighbours' candidates (owned rows are fixed points);
     - a record with one candidate is attached and that subject leaves the other records of the system.
    Records still tied get a tentative one-to-one choice (activity order follows user order) and a note."""
    owned = {rid: next(iter(u)) for rid, u in owners.items() if len(u) == 1}
    pol = data.activity[(data.activity["source_system"] == "deletion_worker")
                        & data.activity["event_type"].isin(POLICY_EVENTS)
                        & ~data.activity["resource_id"].str.startswith("account_")]
    times = pol.groupby("resource_id")["event_time"].apply(list).to_dict()
    linked = set(owners) | {r for d in out.values() if d.subject for r in d.subject.resource_ids}
    act = pol[~pol["resource_id"].isin(linked)].sort_values(["event_time", "activity_id"])
    reqs = pd.concat([data.requests, data.sample_requests], ignore_index=True).set_index("case_id")
    subj = {d.subject.user_id: d for d in out.values() if d.subject}
    prefix = lambda rid: rid.rsplit("_", 1)[0]  # noqa: E731

    cands: dict[str, dict[str, float]] = {}  # rid -> {user_id: |minutes from reported_at|}
    first_seen: dict[str, tuple] = {}
    for r in act.itertuples(index=False):
        first_seen.setdefault(r.resource_id, (r.event_time, r.activity_id))
        for cid, d in out.items():
            if not d.subject:
                continue
            rep = reqs.loc[cid].reported_at
            if not (rep - POLICY_BEFORE <= r.event_time <= rep + POLICY_AFTER):
                continue
            if any(prefix(x) == prefix(r.resource_id) for x in d.subject.resource_ids if x != r.resource_id):
                continue
            mine = [t for x in d.subject.resource_ids - d.subject.account_ids for t in times.get(x, [])
                    if abs(t - rep) <= POLICY_AFTER]
            if any((t < rep) != (r.event_time < rep) for t in mine):
                continue
            off = abs((r.event_time - rep).total_seconds()) / 60
            c = cands.setdefault(r.resource_id, {})
            c[d.subject.user_id] = min(off, c.get(d.subject.user_id, 1e9))
    for rid, c in cands.items():
        if any(v <= STORY_MATCH for v in c.values()):
            cands[rid] = {u: v for u, v in c.items() if v <= STORY_MATCH}

    listings = [items for items in ordered_listings(evidence, owned).values()
                if any(rid in cands for rid, _ in items)]
    attached: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for items in listings:  # monotone user order along the listing, forward then backward
            seq = [(rid, {_user_no(owned[rid])} if rid in owned else {_user_no(u) for u in cands.get(rid, {})})
                   for rid, _ in items]
            seq = [(rid, nums) for rid, nums in seq if nums]
            lo = -1
            for rid, nums in seq:
                if rid not in owned:
                    drop = [u for u in cands[rid] if _user_no(u) <= lo]
                    for u in drop:
                        del cands[rid][u]
                        changed = True
                lo = min((_user_no(u) for u in cands.get(rid, {})), default=lo) if rid not in owned                     else _user_no(owned[rid])
            hi = 10 ** 9
            for rid, nums in reversed(seq):
                if rid not in owned:
                    drop = [u for u in cands[rid] if _user_no(u) >= hi]
                    for u in drop:
                        del cands[rid][u]
                        changed = True
                hi = max((_user_no(u) for u in cands.get(rid, {})), default=hi) if rid not in owned                     else _user_no(owned[rid])
        for rid in sorted(cands):
            if rid in attached or len(cands[rid]) != 1:
                continue
            uid = next(iter(cands[rid]))
            attached[rid] = uid
            for other, c in cands.items():
                if other not in attached and prefix(other) == prefix(rid) and uid in c:
                    del c[uid]
                    changed = True
    # Residual ties: one record per subject per system, activity order follows user-number order.
    tentative: dict[str, str] = {}
    taken = {(prefix(r), u) for r, u in attached.items()}
    for rid in sorted((r for r in cands if r not in attached and cands[r]), key=lambda r: first_seen[r]):
        for uid in sorted(cands[rid], key=lambda u: (cands[rid][u], _user_no(u))):
            if (prefix(rid), uid) not in taken:
                tentative[rid] = uid
                taken.add((prefix(rid), uid))
                break
    for rid, uid in sorted(attached.items()) + sorted(tentative.items()):
        d = subj[uid]
        ids_ = ",".join(sorted(act[act["resource_id"] == rid]["activity_id"]))
        d.subject.add_resource(rid, f"{SOURCE_POLICY}:{ids_}" + (" (tentative tie)" if rid in tentative else ""))
        if rid in tentative:
            d.reason += f"; {rid} tentatively linked (tie with {','.join(sorted(set(cands[rid]) - {uid}))})"
    for d in out.values():
        if d.subject:
            d.resources = sorted((d.subject.resource_ids - d.subject.account_ids)
                                 | ({d.chosen_account} if d.chosen_account else set()))

def histogram(results: dict[str, Discovery], case_ids) -> Counter:
    return Counter(len(results[c].account_candidates) for c in case_ids)
