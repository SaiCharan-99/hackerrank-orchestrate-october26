"""Prompts for PNG/PDF evidence extraction (code/ghost/evidence/vision.py)."""

EXTRACT = """You are transcribing one internal business artifact (an application screenshot or a document)
for a data-deletion audit. Transcribe facts exactly as shown; never guess or complete partially visible text.

Emit one row for EVERY record identifier visible anywhere: table rows, page headers/subtitles, the
detail/side panel, activity timelines and metadata lines. A record identifier looks like
account_<n>, support_<n>, search_<n>, analytics_<n>, export_<n>, backup_<n>, cache_<n>, marketing_<n>,
email_log_<n>, data_flow_<n>, audit_record_<n>, legal_hold_<n>, tombstone_<n>. Copy digits exactly.
If one identifier appears in several places, emit one row and merge what is shown about it.

For each row give, using null when not shown for that record:
- resource_id: the record identifier.
- category: the record's data category, one of USER_PROFILE, SEARCH_INDEX_ENTRY, CACHE_ENTRY,
  SUPPORT_MESSAGE (a ticket / conversation), SUPPORT_ATTACHMENT (an uploaded file or attachment, e.g. a
  document the customer sent), ANALYTICS_PROFILE, USER_EXPORT, MARKETING_PROFILE, EMAIL_DELIVERY_LOG,
  SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD, BACKUP_ARCHIVE, DATA_FLOW, ACCOUNT_TOMBSTONE; null if unclear.
- status_text: the status / state / result words shown for the record (e.g. "Active", "Deleted",
  "Restore allowed", "Anonymized", "Valid"), else "".
- present: true if the screen shows the record as existing; false only if it explicitly says the record
  is deleted / purged / not found; null if unclear.
- email, name, phone, email_hash: direct identifiers displayed for THIS record (the header customer of a
  single-customer page belongs to the account and records shown on that page).
- customer_reference: a user_<n> reference shown for this record (e.g. "Subject: user_03").
- enabled: data flows / connectors / syncs: true if active/enabled, false if disabled/paused.
- restore_allowed: backups: true if restore is allowed/available, false if blocked.
- anonymized / redacted: true/false only if the screen says so (e.g. "Anonymized", "PII removed").
- observed_at: the timestamp shown for the record in ISO-8601 UTC if a full date and time is shown, else null.
- pointer: where it appears, e.g. "table row 2", "header", "detail panel", "activity timeline".

Also return detail_panel: a flat object of every label -> value pair in the detail/side panel (strings).

Reply with ONLY a JSON object:
{"rows": [{"resource_id": "...", "category": null, "status_text": "", "present": true, "email": null, "name": null,
"phone": null, "email_hash": null, "customer_reference": null, "enabled": null, "restore_allowed": null,
"anonymized": null, "redacted": null, "observed_at": null, "pointer": ""}], "detail_panel": {}}
"""

TEXT_DOCUMENT = EXTRACT + """
The artifact is a PDF whose text layer is reproduced below between <document> tags (line breaks may
split a value; rejoin them).
<document>
{text}
</document>
"""

RECONCILE = """Two independent transcriptions of the same artifact disagree. Look at the artifact again and
return the single correct transcription in the same JSON format. For each disagreeing value, keep the
one that matches the artifact character-for-character; drop rows whose resource_id is not visible.

Transcription A:
{a}

Transcription B:
{b}

Disagreements:
{diff}
"""
