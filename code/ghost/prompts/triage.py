"""Prompt for the bounded evidence-triage step (code/ghost/triage.py)."""

TRIAGE = """You gate evidence rows for one data-deletion audit case. The subject's known identifiers and
the audit cutoff are given. Each candidate row has partial or conflicting identifiers. For every row decide:
- include: the row is about this subject (its identifiers match the subject and nothing contradicts that);
- exclude: the row is about someone else, or nothing ties it to this subject;
- needs_recheck: undecidable from this row; optionally name ONE alternative file from the row's
  alternatives list that should be re-checked for the same resource.
You cannot add resources, change record states, or apply policy. Use only the data below.

Subject: {subject}
Audit cutoff (audit_at): {audit_at}

Candidate rows:
{rows}

Reply with ONLY a JSON object:
{{"decisions": [{{"row_key": "<row_key>", "decision": "include|exclude|needs_recheck",
"reason": "<short>", "recheck_resource_id": null, "recheck_file_id": null}}]}}
"""
