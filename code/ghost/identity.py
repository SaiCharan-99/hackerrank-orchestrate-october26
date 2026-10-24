"""Identity graph: one Subject per user_id with current and historical identifiers.

Resolution is by exact identifier only (email, email hash, phone digits). Names are kept for
corroboration by later evidence matching but are never used to resolve a subject on their own.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"\buser_\d+\b")

SOURCE_IDENTITIES = "identities"
SOURCE_AUDIT_LOG = "audit_log"
SOURCE_LINK = "activity LINK_RESOURCE_IDENTITY"
SOURCE_OTHER = "other"


def norm_email(value: str) -> str:
    return (value or "").strip().lower()


def norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def norm_hash(value: str) -> str:
    return (value or "").strip().lower()


def sha256_email(email: str) -> str:
    return hashlib.sha256(norm_email(email).encode("utf-8")).hexdigest()


@dataclass
class Subject:
    user_id: str
    name: str
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    email_hashes: set[str] = field(default_factory=set)
    account_ids: set[str] = field(default_factory=set)
    resource_ids: set[str] = field(default_factory=set)
    # identifier value -> sorted list of "source:ref" strings explaining where it came from
    sources: dict[str, list[str]] = field(default_factory=dict)

    def _note(self, value: str, source: str) -> None:
        refs = self.sources.setdefault(value, [])
        if source not in refs:
            refs.append(source)
            refs.sort()

    def add_email(self, value: str, source: str) -> None:
        e = norm_email(value)
        if e:
            self.emails.add(e)
            self._note(e, source)
            h = sha256_email(e)
            self.email_hashes.add(h)
            self._note(h, f"sha256({e})")

    def add_phone(self, value: str, source: str) -> None:
        p = norm_phone(value)
        if p:
            self.phones.add(p)
            self._note(p, source)

    def add_hash(self, value: str, source: str) -> None:
        h = norm_hash(value)
        if h:
            self.email_hashes.add(h)
            self._note(h, source)

    def add_resource(self, resource_id: str, source: str) -> None:
        """Hook for activity links and, later, evidence parsers (customer_reference etc.)."""
        r = (resource_id or "").strip()
        if not r:
            return
        self.resource_ids.add(r)
        if r.startswith("account_"):
            self.account_ids.add(r)
        self._note(r, source)


_ADDERS = {"email": Subject.add_email, "phone": Subject.add_phone, "email_hash": Subject.add_hash}


def build_subjects(data) -> dict[str, Subject]:
    subjects: dict[str, Subject] = {}
    for row in data.identities.itertuples(index=False):
        s = Subject(user_id=row.user_id, name=row.name)
        s.add_email(row.email, SOURCE_IDENTITIES)
        s.add_phone(row.phone, SOURCE_IDENTITIES)
        s.add_hash(row.email_hash, SOURCE_IDENTITIES)
        subjects[row.user_id] = s
    for row in data.audit_log.sort_values("audit_id", kind="stable").itertuples(index=False):
        adder = _ADDERS.get(row.field_name)
        s = subjects.get(row.user_id)
        if adder is None or s is None:
            continue
        src = f"{SOURCE_AUDIT_LOG}:{row.audit_id}"
        adder(s, row.old_value, src)
        adder(s, row.new_value, src)
    attach_activity_links(subjects, data.activity)
    return subjects


def attach_activity_links(subjects: dict[str, Subject], activity) -> None:
    """LINK_RESOURCE_IDENTITY: 'linked <res> (<alias>) to <email> and user_N'.

    The resource is attached only when the named user exists and the email (if any) is one of
    that user's known emails, so a mismatched link cannot pull in another person's data.
    """
    links = activity[activity["event_type"] == "LINK_RESOURCE_IDENTITY"]
    for row in links.itertuples(index=False):
        users = USER_RE.findall(row.details)
        emails = [norm_email(e) for e in EMAIL_RE.findall(row.details)]
        if len(users) != 1 or users[0] not in subjects:
            continue
        s = subjects[users[0]]
        if emails and not all(e in s.emails for e in emails):
            continue
        s.add_resource(row.resource_id, f"{SOURCE_LINK}:{row.activity_id}")


class IdentityIndex:
    def __init__(self, subjects: dict[str, Subject]):
        self.subjects = subjects
        self._by_email: dict[str, set[str]] = {}
        self._by_hash: dict[str, set[str]] = {}
        self._by_phone: dict[str, set[str]] = {}
        self.reindex()

    def reindex(self) -> None:
        self._by_email.clear(), self._by_hash.clear(), self._by_phone.clear()
        for uid, s in self.subjects.items():
            for e in s.emails:
                self._by_email.setdefault(e, set()).add(uid)
            for h in s.email_hashes:
                self._by_hash.setdefault(h, set()).add(uid)
            for p in s.phones:
                self._by_phone.setdefault(p, set()).add(uid)

    def _one(self, table: dict[str, set[str]], key: str) -> Subject | None:
        uids = table.get(key, set())
        return self.subjects[next(iter(uids))] if len(uids) == 1 else None

    def resolve_email(self, email: str) -> Subject | None:
        return self._one(self._by_email, norm_email(email))

    def resolve_hash(self, value: str) -> Subject | None:
        return self._one(self._by_hash, norm_hash(value))

    def resolve_phone(self, value: str) -> Subject | None:
        p = norm_phone(value)
        return self._one(self._by_phone, p) if p else None

    def ambiguous_emails(self) -> list[str]:
        return sorted(e for e, u in self._by_email.items() if len(u) > 1)

    def resolution_path(self, email: str, subject: Subject) -> str:
        refs = subject.sources.get(norm_email(email), [])
        if SOURCE_IDENTITIES in refs:
            return "current"
        if any(r.startswith(SOURCE_AUDIT_LOG) for r in refs):
            return "historical"
        return SOURCE_OTHER


def build_index(data) -> IdentityIndex:
    return IdentityIndex(build_subjects(data))
