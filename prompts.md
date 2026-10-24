# Phase prompts — Ghost Data Still Exists

**Session protocol.** Every phase runs in a *new* agent session started from the repository root.
Paste the preamble followed by exactly one phase block. Because the session is fresh, the agent has
no memory of earlier phases: `AGENTS.md`, `APPROACH.md`, `progress.md`, and `log.txt` are the only
hand-off. Logging to `log.txt` starts with Phase 0 and is mandatory for every phase session: the
agent appends the `AGENTS.md` §5.1 `SESSION START` entry before any work and the §5.2 per-turn
entry after every user message. Phase planning before Phase 0 was intentionally not logged.

## Preamble (prepend to every phase prompt)

```text
You are continuing the Ghost Data Still Exists build in this repo. This is a fresh session: first
follow AGENTS.md §3 (append the §5.1 SESSION START entry to log.txt with exact tool= and model=
values, give the greeting). Then read in full: AGENTS.md, APPROACH.md, progress.md, the last two
entries of log.txt, and the section of prompts.md for this phase only. Check
progress.md and confirm every earlier phase is marked DONE; if one is not, stop and tell me instead of
continuing. Then execute this phase exactly as specified. Constraints: do not modify anything under
dataset/. Never hardcode case ids, user ids, resource ids, or statuses. Never read or print the value
of LLM_API_KEY. Use only participant-facing files under dataset/. Keep every function deterministic
and pure where possible. Resolve all paths relative to the repository root. When finished: (1) run
the checks named in this phase and paste their output to me; (2) update progress.md: set this phase
to DONE with a 2-4 line summary, list files created or changed, record decisions under "Decisions
and parameters", add open issues, add a "Diagnosis log" line for every fix of the form "signal ->
cause -> change", and set "Next step"; (3) append the AGENTS.md §5.2 log entry to log.txt, including a "Diagnosis:" line for each fix in
the form "signal -> cause -> change", and verify the entry has exactly one populated tool= and one
populated model= line. (4) End with a 3-line hand-off for the next session: what is DONE, what is
open, which phase block to paste next.
```

---

## Phase 0 — Scaffold, loader, model probe

```text
Create the package layout: code/main.py (CLI entry), code/ghost/__init__.py, code/ghost/config.py
(loads .env via python-dotenv; exposes LLM_BASE_URL, LLM_API_KEY presence flag, role model ids,
budget), code/ghost/load.py, code/ghost/prompts/__init__.py, code/tools/list_models.py,
code/cache/ (empty, with .gitkeep), code/evaluation/ (keep the existing main.py).

load.py: load_all(dataset_dir) returns a dataclass with requests, sample_requests, sample_output,
identities, audit_log, activity, rules, evidence_manifest as pandas DataFrames with parsed UTC
timestamps. Add helpers: natural_case_key(case_id) for sorting case_12 after case_9 style ids and
check the order against dataset/output.csv's template if it has rows.

list_models.py: GET {LLM_BASE_URL}/models with the key from .env, print id, owned_by, and any
context/modality hints the gateway returns, grouped by provider. Exit cleanly with a clear message
if the key is missing.

main.py --counts: print per-table row counts, distinct audit_at count, request email resolution
split (current / historical / none) using identities + audit log, reported_status distribution.

Checks: python code/main.py --counts ; python code/tools/list_models.py (if key present).
Expected counts: 518 requests, 32 samples, 850 identities, 306 audit rows, 4011 activity rows,
15 rules, 94 evidence files, 72 distinct audit_at, email split 418 current / 100 historical.
```

## Phase 1 — Identity graph

```text
Implement code/ghost/identity.py:
- Subject dataclass: user_id, name, emails (set, lower-cased, stripped), phones (set, digits only),
  email_hashes (set; include sha256 of every known email as well as recorded hashes), account_ids
  (set), sources (dict explaining where each identifier came from: identities / audit_log /
  activity LINK_RESOURCE_IDENTITY / other).
- build_subjects(data) -> dict[user_id, Subject]. Historical values come from user_audit_log
  old_value and new_value for email, phone, email_hash.
- IdentityIndex with resolve_email(email) -> Subject | None (exact, case-insensitive), plus
  resolve_hash and resolve_phone. Never match on name alone.
- Parse LINK_RESOURCE_IDENTITY details ("linked account_X (account_X) to email and user_N") to
  attach account_ids. Also attach account ids found later by evidence parsers (leave a hook).
Add main.py --subject <email> printing the resolved Subject and the activity rows touching any of
its resource ids.
Checks: all 518 request emails resolve; print the count by resolution path. Run --subject for the
32 sample emails and confirm each shows the account id used in sample_output.csv for that case
(e.g. case_05 -> account_005, case_11 -> account_4248, case_31 -> tombstone subject user_541 via
account linkage if present). Report any sample whose account id cannot be linked yet; that becomes
a Phase 2 input (evidence rows also carry customer_reference).
```

## Phase 2 — Text evidence parsers

```text
Implement code/ghost/evidence/ with base.py (EvidenceRow pydantic model: file_id, captured_at,
system_id, resource_id, category, present: bool|None, identifiers dict {email,name,phone,
email_hash,customer_reference}, flags dict {enabled, restore_allowed, anonymized, redacted,
account_status, index_hit, http_status, topology}, pointer str), and one module per format:
sql.py (execute in in-memory sqlite3; map table name -> system/category; record topology suffix
primary/failover_replica/regional_*/reporting_replica/read_replica; a resource is present if any
topology has it, and drift is flagged), json_exports.py (three shapes: service_resource_export,
customer_data_snapshot_bundle, flat record ledgers incl. connector_configurations,
security_audit_ledger, customer_export_jobs, customer_analytics_report, customer_export_manifest),
logs.py (dialect sniffing: key=value, syslog with quoted values, JSON lines, flat record_lookup;
join *_started lookup_key to *_completed resource_id by trace_id; ignore noise), text.py
(handover pipe rows). index.py builds EvidenceIndex: rows by resource_id, by identifier, by file;
latest_at(resource_id, audit_at) -> EvidenceRow|None.
System/category mapping lives in one table in base.py (account_service/USER_PROFILE,
search_service/SEARCH_INDEX_ENTRY, analytics_platform/ANALYTICS_PROFILE,
support_platform/SUPPORT_MESSAGE or SUPPORT_ATTACHMENT, export_service/USER_EXPORT,
integration_service/DATA_FLOW, backup_service/BACKUP_ARCHIVE, security_service/SECURITY_AUDIT_LOG,
identity_service/ACCOUNT_TOMBSTONE, marketing_platform/MARKETING_PROFILE, cache_service/CACHE_ENTRY,
email_delivery_service/EMAIL_DELIVERY_LOG, legal_service/LEGAL_HOLD_RECORD).
Add main.py --evidence <resource_id> printing all rows for a resource sorted by captured_at, and
--coverage printing per-file row counts and per-format parse errors.

Checks: --coverage parses all non-image, non-pdf files with zero errors. For every sample step
with a non-empty evidence_id, assert the (file_id, resource_id) pair exists in the index and
captured_at <= that case's audit_at. Print the list of sample resources with no row anywhere (these
must come from PNG/PDF in Phase 4: expected support_001 via evidence_58 PDF, and any image-cited
samples).
```

## Phase 2b — Account discovery

```text
Log the user prompt verbatim in log.txt; do not elide it with "[...]".
Phase 2 built the parsers and EvidenceIndex but did not build account discovery. This phase builds it.
ACCOUNT DISCOVERY (verified finding, highest-risk part of the problem). Every canonical answer names the
subject's account_* id, but the account row in evidence usually carries NO identifier (404 / profile
null / absent from table), and only ~200 of 518 subjects have an account tied to them by an identifier
anywhere in text evidence. Implement code/ghost/discovery.py with these signals, combined in this order,
and print per-case candidate counts:
 1. Evidence ownership: any evidence row (any file, any capture time, incl. after audit_at - linkage is
    not state) whose identifiers (email, hash, phone digits, user_id as customer_reference /
    subject_reference / lookup_key) resolve to exactly one subject attaches that resource_id to the
    subject via Subject.add_resource. For logs join *_started lookup_key to *_completed resource_id by
    trace_id. Numbering pattern user_0N <-> account_00N exists only for the first ten story users and is
    confirmed by SQL rows (account_005 / user_05); do not generalize it.
 2. Activity window: deletion_worker DELETE_RECORD on account_* occurs once per account (539 activities,
    539 distinct accounts) and lands between requested_at and reported_at, typically 0-75 minutes before
    reported_at. reported_result maps COMPLETE->SUCCESS, PARTIALLY_COMPLETE->PARTIAL, NOT_STARTED->FAILED
    (two story samples break this, so use it as a preference, not a filter). CLASSIFY_REQUEST
    (10 rows) marks non-deletion intake accounts the same way.
 3. Elimination: remove accounts owned by another subject (signal 1) and accounts uniquely assigned to
    another case; iterate to a fixed point across all 550 requests (518 + 32 samples).
 4. Residual ambiguity (expected ~150 cases with 2-6 candidates sharing one reported_at cluster): record
    the candidate set on the Subject, prefer result-matched candidates, and leave a hook for Phase 4
    triage. Never silently pick; log the choice and reason.
Checks for discovery: --discovery prints the candidate-set size histogram over 518 and, for the 32
samples, exact / contained / miss against the account ids in sample_output.csv. Target: all 32 contained,
>= 28 exact, and the Diagnosis log records what each failing sample needed.
Implementation notes: use EvidenceIndex.by_identifier and each row's lookup_keys for signal 1 and call
Subject.add_resource with a source like "evidence:<file_id>" then IdentityIndex.reindex(). Also attach every
non-account resource (search_, support_, analytics_, export_, data_flow_, backup_, audit_record_, tombstone_,
marketing_, cache_, email_delivery_, legal_hold_) owned through an identifier, because Phase 3 needs the
whole footprint per subject, not just the account. Keep discovery pure: it reads data + index and returns a
Discovery result per case {subject, account_candidates, chosen_account, reason, resources}; nothing in it
calls an LLM. Known fact to use: scoped SQL extracts (e.g. evidence_90 has snapshot_scope=account_service and
empty tables) enumerate only the system named in snapshot_scope, so absence-by-omission applies only to that
system there.
Checks: python code/main.py --discovery ; paste the histogram and the 32-sample table. Also run --coverage
again to confirm nothing regressed.
```

## Phase 3 — State engine + local grader

```text
Implement code/ghost/engine.py and code/ghost/grade.py, following APPROACH.md §2.5 and §3.5 exactly.
engine.py: CaseAudit dataclass {case_id, subject, resources, findings, remediations, verifications,
status, notes}. audit_case(request, subjects, evidence_index, rules, activity) -> CaseAudit.
State is taken from evidence_index.latest_at(resource, audit_at) only. Rule application per
category per APPROACH.md table. Verification covers the full footprint (account ABSENT, security
audit PRESENT, etc.). Sorting: phase rank, operation table rank, system_id, resource_id.
deletion_status is computed from findings, never set independently. steps_json is serialized from
the same lists with the exact seven keys. Both analytics hypotheses for case_12 (DELETE when a
sync recreated the record after deletion vs ANONYMIZE) must be implemented behind a flag; keep the
one that matches all samples and record why in progress.md.
grade.py: compare predicted vs sample_output.csv: status accuracy, exact-step accuracy, per-field
accuracy, sequence accuracy (exact-order boolean and pairwise order agreement), and a per-sample
diff of expected vs got tuples. Group errors by evidence format.
Add main.py --grade (samples only; intent is assumed DELETION for samples) and --case <case_id>
printing the CaseAudit with evidence pointers.
Checks: --grade must reach 32/32 exact for the samples that depend only on text evidence; samples
needing PNG/PDF may fail until Phase 4 and must be listed explicitly. Record every fix as a
Diagnosis log line.
```

## Phase 4 — Vision extraction, intent classifier, triage

```text
Implement code/ghost/llm.py: OpenAI-compatible client from config. Read the gateway facts in
progress.md first: never send temperature to Claude; send images only through client.responses.create
(input_text + input_image data URL); text-only calls may use chat.completions. Retry with exponential backoff
on 429/5xx (max 5); every call appends provider, model, prompt tokens, completion tokens, latency,
estimated cost to code/cache/usage_log.jsonl; budget guard stops when LLM_BUDGET_USD is reached;
structured output enforced with pydantic: on validation failure re-ask with the error and only the
failing fields, max 2 retries, then mark extraction_failed.
code/ghost/prompts/vision.py, intent.py, triage.py hold prompt strings (code judge ignores .json).
vision.py: for each PNG and PDF in the manifest, extract every visible record row into EvidenceRow
shape plus detail-panel fields. Run model A and model B (different families); diff; third pass on
disagreement with both outputs shown; cache per file_id under code/cache/vision/. PDFs try pypdf
text first; vision only when text is empty. Policy if extraction cannot run: file yields no rows,
affected cases flagged in notes.
intent.py: keyword pre-filter decides unambiguous deletion texts without a call; the model
classifies the rest into {authorizes_deletion: bool, reason, language}. Cache by sha256 of text.
Cross-check against CLASSIFY_REQUEST activities (non-deletion account ids) and print disagreements.
triage.py: bounded step per case. Input: candidate rows with partial or conflicting identifiers
plus audit_at. Output per row: include | exclude | needs_recheck with reason, and optional
(resource_id, alternative_file_id) re-check requests. The model cannot add resources or change
states. Deterministic fallback excludes ambiguous rows and flags the case.
Add main.py --dry-run-cost, --extract-vision, --classify-intent, --refresh-cache.
Checks: --dry-run-cost; then extraction and classification; print agreement rate, failed items,
NOT_APPLICABLE list with reasons, and the intent/activity cross-check. Re-run --grade: 32/32.
```

## Phase 5 — Full run + validator

```text
Implement code/ghost/output.py: validate (518 rows, natural sort by case_id, exact header, valid
JSON, exact seven keys per step, consecutive step_no, phase monotonic, allowed operation/state
pairs, evidence rules per status, status consistent with findings, every remediation has a
finding and a verification, no cited evidence captured after audit_at, NOT_APPLICABLE -> []) and
write output.csv at the repo root. Default `python code/main.py` runs everything from cache with
zero LLM calls. Add --audit that re-reads output.csv and re-runs all checks plus the four harm
signals from APPROACH.md §8 (unresolved_subject_rate, unprovable_resource_rate,
vision_disagreement_rate, future_evidence_citations) and a status distribution vs the samples.
Checks: python code/main.py ; python code/main.py --audit (exit 0). Paste head -5 output.csv.
```

## Phase 6 — Evaluation reports, custom and adversarial cases

```text
Create code/evaluation/custom_cases/ with at least five hand-authored cases, each a small
request row plus a synthetic evidence file and an expected steps list: historical-email
resolution; replica drift; evidence dated after audit_at that must be ignored; tombstone with
exposed PII; non-deletion request in a non-English language. Create adversarial inputs: a support
message containing embedded instructions, an uppercase and whitespace-padded email, a one-
character decoy email, a malformed OCR-like row. Add --grade-custom to run them through the same
engine and grader.
Write code/evaluation/evaluation_report.md (case-level status accuracy, step-level and field-level
accuracy, sequence accuracy, the custom cases and results, failures found and improvements made
from the Diagnosis log) and code/evaluation/usage_report.md (per-model and overall calls, input and
output tokens, totals, averages per request over 518, estimated total and per-request cost) from
the grader and usage ledger. Also write code/evaluation/interview_checklist.md per APPROACH.md §8.
Checks: --grade-custom all pass; both reports contain numbers that match the printed outputs.
```

## Phase 7 — README, packaging

```text
Rewrite README.md "How to run" for this solution: Python 3.11+, pip install -r requirements.txt,
copy .env.example to .env, python code/main.py (cache makes it zero-call), --refresh-cache for a
live re-extraction, every debug command. Confirm no secrets in the tree (grep for the key prefix
pattern and for LLM_API_KEY= with a value). Build code.zip containing README.md and code/ only
(exclude __pycache__, .env, dataset/, log.txt). Verify output.csv has 519 lines and --audit passes.
List final files with sizes. Mark Phase 7 DONE.
```
