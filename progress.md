# Progress — Ghost Data Still Exists

Design reference: `APPROACH.md`. Output contract: `AGENTS.md` §6. Phase prompts: `prompts.md`.

## Session protocol

- One phase = one fresh agent session, started from the repository root so `AGENTS.md` is read.
- The session begins with the `AGENTS.md` §5.1 `SESSION START` log entry and the greeting, then
  reads `APPROACH.md`, this file, the last two `log.txt` entries, and its phase block in `prompts.md`.
- It confirms every earlier phase is DONE here, executes, runs the named checks, updates this file
  (status, files, decisions, open issues, diagnosis log, next step), and appends the §5.2 per-turn
  entry to `log.txt`.
- Logging starts at Phase 0 and is continuous from then on. The planning conversation that produced
  `APPROACH.md`, `prompts.md`, and this file was deliberately not logged.
- Hand-off between sessions is only through these files and `log.txt`; nothing lives in chat memory.

## Phase status

| Phase | Name | Status | Exit gate |
|---|---|---|---|
| 0 | Scaffold, loader, model probe | DONE | `python code/main.py --counts` prints table counts; `python code/tools/list_models.py` lists gateway models |
| 1 | Identity graph | DONE | all 518 request emails resolve to a `user_id`; `--subject` prints sample subjects with account ids |
| 2 | Text evidence parsers (SQL / JSON / logs / txt) | DONE | every sample finding and verification resource is found in the cited file at ≤ `audit_at` |
| 2b | Account discovery (`discovery.py`, `--discovery`; prompts.md Phase 2 "ACCOUNT DISCOVERY") | DONE | all 32 sample accounts contained, >= 28 exact |
| 3 | State engine + local grader | DONE | `--grade` reports 32/32 exact sample matches |
| 3b | Discovery fix: orphan accounts, unchosen cases (prompts.md Phase 3b) | DONE | --discovery chosen=None count is 1; --grade >= 25/32 |
| 4 | Vision extraction + intent classifier + triage | DONE | vision agreement pass clean; `NOT_APPLICABLE` set agrees with `CLASSIFY_REQUEST` activities |
| 5 | Full run + validator | DONE | `output.csv` 518 rows, validator PASS, zero future-evidence citations |
| 6 | Evaluation reports + custom/adversarial cases | DONE | `code/evaluation/evaluation_report.md` and `usage_report.md` filled from grader/ledger output |
| 7 | README, interview checklist, code.zip | DONE | zip = `README.md` + `code/`, no dataset/.env/log; clean run from a fresh unzip |

## Fixed facts (do not re-derive)

- Reports live in `code/evaluation/` (README overrides the problem statement's `evaluation/`).
- `code.zip` contains `README.md` and `code/` only.
- Code judge ignores `.csv .tsv .json .jsonl .sql .log` files: prompts live in `code/ghost/prompts/*.py`
  (string constants) and caches are `.md`-documented but stored as `.json` only because they are data.
- LLM gateway is OpenAI-compatible: `LLM_BASE_URL` + `LLM_API_KEY` from `.env`.
- Python 3.13 on the build machine; `openai`, `pandas`, `pydantic`, `python-dotenv`, `pillow` already installed.
- Gateway facts verified 2026-10-25 (72 models, Bifrost over Bedrock):
  - Aliases `claude-sonnet` → `bedrock/global.anthropic.claude-sonnet-5-5`, `claude-haiku` → `claude-haiku-5-5`,
    `claude-opus` → `claude-opus-5-5`. Claude 5.x **rejects `temperature`**; omit it (determinism comes from
    caching and schema validation, not sampling params).
  - **Chat Completions drops images** on every model (prompt tokens stay ~27). Vision must use the
    **Responses API** (`client.responses.create` with `input_text` + `input_image` data URL) or the
    Anthropic-native `POST {base without /v1}/v1/messages`. Verified working for Claude, Qwen3-VL, Grok 4.7,
    Kimi K2.5, Gemma 3. MiniMax has no vision. `claude-fable-5-1` needs a data-retention header; not used.
  - Model roles: vision A `claude-sonnet`; vision B `bedrock/qwen.qwen3-vl-235b-a22b` (different family,
    read the sample console exactly); text/intent `claude-haiku`; triage `claude-sonnet`. Gemma 3 27B
    misread `backup_9291` as `backup_3291` and `areed1433` as `arreed143` in the probe: that is exactly the
    OCR risk the agreement pass exists for, and it becomes a documented adversarial example.
  - `python-dotenv`: call `load_dotenv(REPO_ROOT / ".env")` with an explicit path; bare `load_dotenv()`
    fails under heredoc/stdin execution on this machine.

## Phase 0 summary (DONE 2026-10-25)

Package scaffold built; `load_all()` returns a frozen `Dataset` of 9 DataFrames (all read as str,
timestamps parsed UTC). `--counts` matches every expected number (518/32/850/306/4011/15/94, 72
distinct audit_at, 418 current / 100 historical / 0 unresolved). Gateway probe lists 72 models.
Files created: `code/main.py` (was empty), `code/ghost/__init__.py`, `code/ghost/config.py`,
`code/ghost/load.py`, `code/ghost/prompts/__init__.py`, `code/cache/.gitkeep`. Unchanged:
`code/tools/list_models.py` (already met spec), `code/evaluation/main.py` (kept, empty).

## Phase 1 summary (DONE 2026-10-25)

`code/ghost/identity.py` builds one `Subject` per user_id from identities and audit_log history (email,
phone, email_hash old+new), plus sha256 of every known email; `IdentityIndex` resolves by exact
email / hash / phone digits only. All 518 request emails resolve (418 current, 100 historical, 0 ambiguous).
0/32 sample account ids are linkable from activity (only 12 LINK_RESOURCE_IDENTITY rows, 1 account): Phase 2 input.
Files: created `code/ghost/identity.py`; changed `code/main.py` (`--subject`, `--identity-check`).

## Phase 2 summary (DONE 2026-10-24, parsers only)

`code/ghost/evidence/` parses all 79 text evidence files (24 SQL, 28 JSON, 26 log, 1 txt) with zero errors into
2,517 `EvidenceRow`s over 2,040 resources; 15 PNG/PDF deferred to Phase 4. 74/75 cited sample steps found in the
cited file at <= audit_at (4 of them as absence-by-omission); the 1 failure is support_001 in evidence_58 (PDF).
Account discovery (block 2b) was not in the executed prompt and is still TODO.
Files: created `code/ghost/evidence/{__init__,base,sql,json_exports,logs,text,index}.py`; changed `code/main.py`
(`--evidence`, `--coverage`).

## Phase 2b summary (DONE 2026-10-24)

`code/ghost/discovery.py` ties each of the 550 requests to an account and footprint: evidence ownership (signal 1,
attaches every resource whose row identifiers/lookup keys resolve to exactly one subject), the confirmed story
numbering pattern, the DELETE_RECORD/CLASSIFY_REQUEST activity window, fixed-point elimination, then a tentative
one-to-one assignment. Samples: 32/32 contained, 29 exact. Evaluation: 297 unique, 221 ambiguous (sizes 2-6), 0 empty.
Files: created `code/ghost/discovery.py`; changed `code/main.py` (`--discovery`).

## Phase 3 summary (DONE 2026-10-24)

`code/ghost/engine.py` builds one `CaseAudit` per request from `latest_at(resource, audit_at)` state; status is a
property of the findings list and steps_json is serialized from the same lists. `code/ghost/grade.py` + `--grade`:
25/32 exact, status 0.969, step recall 0.948 / precision 0.973, sequence exact 0.781, pairwise order 0.969;
0 text-only failures (the 7 failures need PNG/PDF rows or are tentative ties, listed under Open issues).
Files: created `code/ghost/engine.py`, `code/ghost/grade.py`; changed `code/ghost/discovery.py` (signal 5
policy-action linkage), `code/main.py` (`--grade`, `--analytics-hypothesis`, `--case`).

## Phase 3b summary (DONE 2026-10-24)

NEAR_REPORT_MIN 90 -> 150 and a leftover pass (`leftover_pass`, signal 4b) assign orphan account activities to
cases left unchosen. Eval chosen=None 18 -> 1 (case_53 / user_22, no account activity; engine notes "account
unknown"); 17/18 previously unchosen now have an account; 6 previously chosen accounts changed (case_194/210/274/
287/493/506). Samples still 32 contained / 29 exact; --grade 25/32 with the same 7 failures.
Files: changed `code/ghost/discovery.py`, `code/ghost/engine.py` (account-unknown note), `code/main.py` (chosen=None count).

## Phase 4 summary (DONE 2026-10-24)

`llm.py` (retry/backoff, usage ledger, budget guard, pydantic re-ask), vision/PDF extraction (15 files, Sonnet + Qwen3-VL,
third pass on 7 disagreements, 26 rows after merge), intent classifier (454 keyword / 96 model; 10 NOT_APPLICABLE, 0
disagreements with the 10 CLASSIFY_REQUEST activities) and bounded triage (0 candidate rows in this dataset). --grade 26/32
(case_07 closed); vision rows resolved 0 ambiguous accounts. Ledger: 182 calls, 245,695 in / 50,875 out tokens, est. $0.97.
Files: created `code/ghost/llm.py`, `code/ghost/intent.py`, `code/ghost/triage.py`, `code/ghost/evidence/vision.py`,
`code/ghost/prompts/{vision,intent,triage}.py`, caches `code/cache/{intent.json,triage.json,usage_log.jsonl,vision/*.json}`;
changed `code/main.py` (`--dry-run-cost --extract-vision --classify-intent --triage --refresh-cache --usage`; `_audits`,
`--discovery`, `--coverage`, `--evidence` now use text + cached vision rows, intents and triage).

## Phase 5 summary (DONE 2026-10-25)

`code/ghost/output.py` writes `output.csv` (518 rows, natural case order, csv-quoted compact JSON) and validates it
(header, rows, order, JSON, seven keys, step_no, phase order, phase/op/state pairs, evidence per status, status vs findings,
remediation -> finding + verification, no citation after audit_at, NOT_APPLICABLE -> []). Default `python code/main.py`
runs the cached pipeline (0 LLM calls; ledger unchanged at 182) and validates: PASS. `--audit` re-reads the file: PASS,
determinism match, harm signals 0.000 / 0.012 / 0.467 / 0; status 153 C / 355 I / 10 NA vs samples 10 / 22 / 0.
Files: created `code/ghost/output.py`, `output.csv`; changed `code/main.py` (default run, `--audit`).

## Phase 7 summary (DONE 2026-10-25)

README.md rewritten for the solution (architecture, How to run, every debug command, sample metrics with the command
behind each, known limits). `code/evaluation/main.py` now runs --grade, --grade-custom, --audit (EVALUATION: PASS).
code.zip = README.md + code/ (72 files, 120,744 bytes); a fresh unzip + dataset/ + empty-key .env reproduces output.csv
byte-identically (sha256 f4efeed8...d221, ledger 183 -> 183 lines, 0 calls). Secret scan clean.
Files: changed `README.md`, `code/evaluation/main.py`; created `code/requirements.txt`, `code/.env.example` (copies), `code.zip`.

## Decisions and parameters (P7)

- P7: zip holds README.md + code/ only, so requirements.txt and .env.example are duplicated into code/ for a fresh unzip.
- P7: zip built by a Python zipfile script (skips __pycache__/.venv/.git/.env and nested archives), not Compress-Archive.
- P7: the wrapper enforces exit 0 only for --grade-custom and --audit; --grade has 6 known mismatches by design.
- P7: README names only model ids present in usage_report.md (checked by grep loop).

## Phase 6 summary (DONE 2026-10-25)

9 hand-authored cases in `code/evaluation/custom_cases/` (5 custom: historical email, replica drift, post-audit_at evidence,
tombstone exposed PII, Spanish access request; 4 adversarial: embedded instructions, padded upper-case email, one-char decoy,
OCR-damaged rows) run through the same loader/discovery/intent/engine/grader via `--grade-custom`: 9/9 pass, first run.
Reports written from printed output: samples 26/32 exact, status 1.000, recall 0.969, precision 0.979, sequence 0.812;
pipeline usage 182 calls, 245,695 in / 50,875 out, est. $0.9714 ($0.001875 / request over 518). output.csv unchanged.
Files: created `code/ghost/custom_cases.py`, `code/evaluation/custom_cases/build_cases.py` + 9 case dirs (case.json + evidence),
`code/evaluation/{evaluation_report,usage_report,interview_checklist}.md`; changed `code/main.py` (`--grade-custom`, `--usage`
pipeline/custom split with per-request averages), `code/ghost/intent.py` (`purpose` kwarg), `code/ghost/llm.py`
(`ledger_totals(keep=)`), caches `intent.json` + `usage_log.jsonl` (+1 intent-custom call).

## Decisions and parameters (P6)

- P6: a custom case is a mini `Dataset` (one request, its identities/audit_log/activity, manifest, synthetic evidence) built by
  `custom_cases.load_case`; rules are the real `dataset/deletion_rules.csv`; empty sample tables. Same functions as `main._audits`.
- P6: expected answers are hand-written in `build_cases.py` from the rules, never produced by the engine.
- P6: custom-case LLM calls use purpose `intent-custom`; `--usage` reports pipeline calls (what produced output.csv) separately,
  averages over the 518 evaluation requests.
- P6: reports quote command output verbatim; numbers were cross-checked line by line against `--grade`, `--grade-custom`,
  `--audit` and `--usage` output.

## Decisions and parameters (P5)

- P5: citable ids = manifest file_id (captured_at), activity_id (event_time), audit_id (event_time); unknown id = error.
- P5: COMPLETE with [] steps is a warning, not an error (none today: case_53 is now INCOMPLETE via support_1034).
- P5: remediation/finding/verification consistency is checked per resource_id; verification-only resources are allowed.
- P5: --audit exits 1 on any validator error, any drift between output.csv and a fresh cached rebuild, or any future
  citation. unresolved_subject_rate denominator = applicable (non-NOT_APPLICABLE) eval cases; unprovable_resource_rate =
  "unprovable" resource notes / (notes + audited resources); vision_disagreement_rate = files whose A/B first passes
  disagreed (before third-pass reconciliation) / PNG+PDF files.
- P5: validator self-test: gold sample_output.csv validates clean; flipping INCOMPLETE -> COMPLETE yields 140 errors.

## Decisions and parameters (P4)

- P4: gateway calls never send temperature; images only via responses.create (input_text + input_image data URL); text via
  chat.completions. Retry 429/5xx/connection, backoff 2s doubling, max 5. Other 4xx -> ExtractionFailed. An empty first
  reply is re-asked fresh (an empty assistant turn is a Bedrock 400).
- P4: budget guard = cumulative ledger cost >= LLM_BUDGET_USD. Prices in `llm.PRICES` are estimates (USD/1M in,out:
  sonnet 3/15, haiku 1/5, qwen3-vl 0.53/2.66), override with LLM_PRICES_JSON. Phase 6 should confirm against gateway pricing.
- P4: schema retries: failing top-level fields only, merged into the previous object, max 2, then extraction_failed.
- P4: PDFs: all 4 have a text layer (PyPDF2; pypdf not installed, import falls back), so they go through the same
  extraction prompt as text with A/B agreement; no rasterisation path (text-empty PDF -> extraction_failed, no rows).
- P4: vision rows: one row per resource_id (repeated rows merged, non-null wins, SUPPORT_ATTACHMENT beats SUPPORT_MESSAGE);
  present=None -> True (shown on screen); captured_at = shown timestamp else manifest time; file_captured_at = manifest
  time; no scope (no absence-by-omission from screenshots). Category from the model (validated enum) else prefix default.
- P4: diff ignores names; compares ids, present, email, phone, customer_reference, hash, flags. Third pass = model A with
  both transcriptions and the diff. Agreement rate is per file (8/15 after refresh).
- P4: intent pre-filter: ASCII text + strong deletion phrase + no negative cue (don't/do not/keep/leave/still use/copy of/
  download/marketing/only/whether/?...) -> deletion without a call. Prompt counts verify/finish/clean-up follow-ups on
  the person's own deletion as deletion (all 32 samples authorize deletion). Missing label -> deletion + note (fallback).
- P4: triage candidates = rows <= audit_at outside the footprint whose identifiers resolve to the subject and another
  subject (contested) or match only by name; accounts/analytics excluded by design. Dataset has 0 such rows, so 0 calls.

## Decisions and parameters (P3b)

- P3b: NEAR_REPORT_MIN=150 (clusters with account activity 2h05-2h15 before reported_at). Ambiguous eval cases 221 -> 224.
- P3b: leftover pass pool = WINDOW_EVENTS account hits in [requested_at, reported_at + REPORT_LAG] not chosen by any
  case; cost (result mismatch, |min from reported_at|); one-to-one, one account per subject; ambiguous=True,
  reason names the orphan pool. Unchosen cases keep their other footprint and get the note "account unknown".

## Decisions and parameters (P3)

- P3: analytics hypothesis kept = `attempted_delete` (an ANALYTICS_PROFILE the deletion_worker tried to
  DELETE_RECORD before audit_at is under DELETE treatment). It scores 25/32; `always_anonymize` scores 24/32 and
  breaks case_12 (analytics_9914 has a DELETE_RECORD FAILED activity and no anonymized flag). No sync activity exists
  for analytics_9914, so the "recreated by sync" variant reduces to the same test. Flag: `--analytics-hypothesis`.
- P3: verification covers the whole linked footprint: chosen account (ABSENT, cited by its row or by an omission
  file), every linked record with a row <= audit_at, and RETAIN records (security audit, legal hold) whose only rows
  are after audit_at - the latter only in INCOMPLETE cases (future check, evidence ""), never cited in COMPLETE cases.
- P3: violation tests: DELETE -> present; ANONYMIZE -> present and (direct identifier, anonymized=False, or found by
  an identifier lookup); REDACT -> any direct identifier other than customer_reference (tombstones keep it), or
  redacted=False; DATA_FLOW -> enabled; BACKUP -> restore_allowed. REDACT/ANONYMIZE/RETAIN rows that are absent at
  audit_at are skipped with a note.
- P3: a `deletion_marker` check that finds no marker forces DELETE treatment (case_10 support_002, a legacy
  contact-index copy, is a remaining record, not a conversation to redact).
- P3: absence-by-omission citation: an omission file that also holds the subject's other records wins, else the
  latest file listing at least one other record of that system (empty scoped extracts like evidence_90 never cite).
- P3: discovery signal 5 (policy-action linkage, `link_policy_actions`): unowned non-account records (anonymized
  analytics etc.) attach through deletion_worker policy actions in [reported_at - 90 min, reported_at + 150 min],
  same side of reported_at as the subject's other policy actions, STORY_MATCH 15 min preference, monotone user order
  along subject-ordered listings (`ordered_listings`: every listing with >=2 owned rows strictly increasing, one with
  >=3; evidence_02 qualifies), fixed-point uniqueness, then a tentative one-to-one choice for ties (noted).
  Records already linked to any subject (incl. LINK_RESOURCE_IDENTITY) are excluded.
- P3: sort key (phase rank, AGENTS.md 6.4 operation rank, system_id, resource_id); JSON compact, keys in the
  7-key order; eval steps hash stable across runs (108d15002fe29d91).

## Decisions and parameters

- P0: CSVs read with `dtype=str, keep_default_na=False` so empty identifiers stay `""` (never NaN) and ids are never coerced.
- P0: `dataset/output.csv` template has 0 rows, so row order falls back to `natural_case_key` (text/int runs).
- P0: `config.py` exposes only `has_api_key`; the raw key is reachable solely via `config.api_key()` for client construction.
- P0: role model defaults mirror `.env.example` (vision `claude-sonnet`, vision B `bedrock/qwen.qwen3-vl-235b-a22b`, text `claude-haiku`, triage `claude-sonnet`, budget $10).

## Open issues

- P7: log.txt has 11 SESSION START entries for 10 phase sessions: Phase 5 has two (21:48:15 and 21:48:23, retry after a
  failed printf), and Phase 4's start (21:24) is logged after Phase 3b's entries. Log is append-only, so left as is.
- P7: "[...]" elisions exist only in the Phase 1 and Phase 2 prompt entries (log lines 65-66, 119-120); none after Phase 2.

- P6: costs are estimates from `llm.PRICES`; gateway invoice pricing was not available to confirm them.
- P6: custom cases cover text/SQL formats only; image-side OCR risks are documented from Phase 4 probes, not as a custom case.

- P5: NOT_APPLICABLE share 1.9% eval vs 0% samples (samples contain no non-deletion requests; not a signal of error).
- P5: vision_disagreement_rate 0.467 is pre-reconciliation; all 7 resolved by third pass, 0 extraction_failed.

- P4: vision rows resolved 0 of 235 ambiguous accounts (screenshots show story users already owned by text evidence).
  Remaining sample failures are only the documented ties (case_03 analytics, case_23/28/29 accounts) and
  audit_record_6645 / 5569 (case_18 / case_20), which appear in no participant file (grep over dataset/ and vision cache).
- P4: Qwen3-VL often omits rows or identifiers (5 of 7 disagreements are "only in A" / B=None); the third pass then
  follows model A. evidence_09 search_1874 email g.silva76.jr vs g.silva76jr was reconciled to the dotted form (Phase 6
  adversarial example). No row in the ledger is an extraction_failed file today.
- P4: price table is an estimate; one unlogged probe call (~40 tokens) and two debugging calls were made outside the ledger.
- P4: full-run split now 355 INCOMPLETE / 153 COMPLETE / 10 NOT_APPLICABLE; 0 future-evidence citations; 16 steps cite PNG/PDF.

- P3b: case_53 (user_22) has no account at all; Phase 6 must list it as "account unknown". Its steps are still []
  as COMPLETE because its other records are unprovable at audit_at; Phase 5 validator should flag empty COMPLETE.
- P3b: the 6 changed eval choices are tentative; no ground truth to confirm them.

- P3: sample failures that need Phase 4: case_07 (support_001 only in evidence_58 PDF), case_18 / case_20
  (audit_record_6645 / audit_record_5569 appear in no text file), case_23 / case_28 / case_29 (ambiguous accounts,
  known from P2b). case_03: analytics_9406 vs analytics_5589 is a pure tie between user_42 and user_43 in text
  evidence (same cluster, both pre-report SUCCESS, listed only in a log); the tentative choice is wrong for the sample.
- P3: evaluation run notes: 183 tentative accounts, 112 tentative policy-linked ties, 31 unprovable resources
  (rows only after audit_at), 17 retained-later records. Eval status split 349 INCOMPLETE / 169 COMPLETE (intent not
  yet applied). Phase 4 should re-run discovery after vision rows and report how many ties remain.

- P2b: 221/518 evaluation cases keep 2-6 account candidates (tentative choice); Phase 4 triage must resolve them.
- P2b-verifier (2026-10-25): the residual ambiguity is informational, not a parsing gap. Tested on the 326 known
  case->account pairs: deletion-worker order within a reported_at cluster has coin-flip agreement (0.45-0.54) with
  requested_at, case number, user number, email order and account number, so processing order carries no signal.
  Intersecting candidates with accounts enumerated in the cluster's own evidence files resolves only 18 more cases;
  188 ambiguous cases have no candidate account named in any nearby file (their absence is proven by scoped
  extracts that enumerate account_service without naming accounts). Consequences: (a) Phase 3 uses the tentative
  one-to-one choice as-is; (b) Phase 4 triage must NOT ask an LLM to pick an account (no information to reason on),
  it should only re-run discovery after vision rows add account<->email links from the console screenshots;
  (c) Phase 6 must document this as a known limit: only the account_service verification step's resource_id is
  affected in those cases, every other step is unaffected.
  Samples case_23 (account_410 vs 9155, identical FAILED timing), case_28/case_29 (5482/7012 swapped, same
  reported_at, both FAILED) cannot be separated by activity: they need non-account evidence (search decoy in case_28,
  images/PDFs) in Phase 4.
- P2b: case_17's subject owns two accounts (account_4092 via evidence_01, account_6523 via evidence_67); chosen by
  window. Phase 3 must decide whether a second owned account belongs in the footprint.

- P2: account discovery (block 2b) not built: 15 sample account/audit/support resources have no explicit row in any
  text file (account_006/007/008/010/410/4163/4990/5037/5521/7012/8858, audit_record_5569/6645, support_001) and
  0/32 sample accounts are linked to subjects yet. `Subject.add_resource` hook is still unused by the evidence index.
- P2: support_001 (case_07) needs evidence_58 PDF extraction in Phase 4.
- P2: one row stays present=None (support_7731 `thumbnail_failed`, attachment_preview service); treated as unknown.

- P1: 0/32 sample account ids linkable from activity; Phase 2 evidence parsers must call `Subject.add_resource`
  with `customer_reference` / `subject_reference` / `lookup_key=user_N` matches, then `IdentityIndex.reindex()`.
- P1-verifier: account discovery is the critical path. Probe results: evidence identifiers tie an account to
  a subject for ~200/518 cases; the activity window alone gives 342 unique / 168 ambiguous / 9 none; the two
  combined with elimination are the Phase 2 design (see prompts.md Phase 2 "ACCOUNT DISCOVERY"). Samples
  case_01..case_10 rely on the account_00N pattern plus SQL rows; case_31/32 accounts (4857/8858) appear
  nowhere with an identifier and resolve only through the window + elimination.
- P1: identity history is not yet time-filtered; LINK activity_4000 is dated 2026-09-26, so Phase 3 must
  ignore links and evidence after `audit_at` when choosing resources and citations.

- P0: first cold `--counts` run took 5.4 s (pandas import cold cache); warm runs 1.6 s. Not a blocker.

## Decisions and parameters (P2b)

- P2b: signal 1 ignores `name` (too weak) and leaves a resource unattached when its rows resolve to >1 subject.
- P2b: story pattern user_0N <-> account_00N applies only to user numbers 1..`STORY_USERS`=10 and only when an
  evidence row confirms it (evidence_54 customer_reference user_05 on account_005); evidence ownership wins over it
  (case_03 account_7566, case_09 account_3960 break the pattern).
- P2b: window = [requested_at, reported_at + `REPORT_LAG` 15 min]; hits within `NEAR_REPORT_MIN`=90 min before
  reported_at are preferred when any exist (248 ownership-confirmed eval accounts land 44-75 min before; samples -8..74).
- P2b: elimination keyed by subject user_id (one user may file several requests); residual cases get a deterministic
  greedy one-to-one assignment by (result mismatch, |minutes from reported_at|, case_id, account_id); `ambiguous=True`
  and the reason string are the Phase 4 triage hook.

## Decisions and parameters (P2)

- P2: system_id comes from the resource-id prefix table in `base.py` (`SYSTEMS`); category from the collection/table
  name (`COLLECTION_CATEGORY`) or the ledger `record_type`, else the prefix default.
- P2: `EvidenceRow` adds `file_captured_at` (manifest time, used for the `<= audit_at` citation cut-off; `captured_at`
  is the in-file observation time), `lookup_keys` (what was searched: lookup_key/query/correlation_key/subject_ref,
  = ownership not content), `fmt`. `identifiers` holds only record content; `matched_value` of a PII scan counts as content.
- P2: absence by omission: a SQL table or a snapshot-bundle collection enumerates its system, so a resource not listed
  there is ABSENT in that file (`EvidenceIndex.absent_by_omission`, `omission_files`). Needed for case_01/02/04
  (evidence_54) and case_31 (evidence_51). Scoped extracts: Phase 3 must tie the file to the subject before using it.
- P2: SQL replicas: one merged row per (file, resource); `flags.topology` lists topologies holding it, `flags.drift`
  + `missing_in` when absent from another topology; non-null identifiers from any topology win (exposed anywhere = exposed).
- P2: logs: `*_started` lines' lookup keys join to the result line by trace id; lines with the same (trace, resource)
  merge into one row; noise services ignored; `*_read_completed/_query_completed/_loaded` with no negative signal = present.
- P2: ledger results: FOUND/IDENTIFIABLE/ANONYMIZED/REDACTED/ACTIVE/DISABLED/BLOCKED = present, NOT_FOUND = absent;
  ACTIVE sets enabled (DATA_FLOW) or restore_allowed (BACKUP).

## Decisions and parameters (P1)

- P1: resolution requires a unique owner; an identifier shared by >1 user returns None (0 such emails today).
- P1: LINK_RESOURCE_IDENTITY attaches the activity `resource_id` only if the named user_N exists and every email in details belongs to that user.
- P1: `account_ids` is the `account_*` subset of `resource_ids`; `sources` maps each value to its origin refs (`identities`, `audit_log:<audit_id>`, `activity LINK_RESOURCE_IDENTITY:<activity_id>`, `sha256(<email>)`).
- P1: recorded email_hash equals sha256(lower(email)) (checked on samples), so computed hashes are safe to match.

## Diagnosis log (signal → cause → change)

- P7: README "pip install -r requirements.txt" / "copy .env.example" would fail in a fresh unzip -> both files live at the
  repo root, outside the README.md + code/ zip -> copied them into code/ and documented the code/ paths.

- P6: SyntaxError (unterminated string) in main.py after a scripted edit -> the bash heredoc turned the Python source `\n`
  into a real newline -> rewrote those lines with the file editor (no escapes) and re-ran the commands.
- P6: ledger mixed one custom-case call with the 182 pipeline calls -> usage report must describe only the run behind
  output.csv -> `intent-custom` purpose plus `ledger_totals(keep=)` filter in `--usage`.

- P5: bash printf of SESSION START failed (`missing unicode digit for \U`) -> Windows path `C:\Users` read as a printf escape -> appended via heredoc instead.
- P5: step-count print used a nested-quote f-string (needs Python 3.12+) -> portability risk for graders on older Python -> precomputed `n_steps`.

- P1: none (no fixes; all checks matched first run).
- P2: 5 cited sample steps "no row" (account_001/002/004 in evidence_54, account_4857 in evidence_51) -> the cited
  files prove absence by omitting the account from a full table/collection -> added parser scopes + `absent_by_omission`.
- P2: pipe-dialect rows had trace=service and no state -> lines start with "| LEVEL |", leading pipe gave an empty
  first field -> strip leading "| " before splitting.
- P2: 74 log rows with present=None (analytics/support reads, legal `retained_order_loaded`) -> completed reads carry no
  http_status/rows -> treat `*_read_completed/_query_completed/_loaded` with no negative signal as present.

- P2b: case_02/04/06/07/08/10 missed or ambiguous -> story accounts have no identifier in text evidence and their
  DELETE_RECORD lands up to 5 min after reported_at (account_004 has no activity at all) -> added the evidence-confirmed
  story numbering signal and a 15 min REPORT_LAG on the window.
- P2b: case_28 and case_29 both tentatively chose account_7012 -> per-case choice ignored that each account has one
  owner -> one-to-one greedy assignment across all requests (still swaps 28/29: genuinely symmetric, left to Phase 4).
- P2b: 232 ambiguous eval cases with up to 8 candidates -> multi-day windows include other clusters' hits -> prefer
  hits within 90 min of reported_at (221 ambiguous, max 6; samples still 32/32 contained).

- P3: 7 analytics VERIFY_RECORD_ANONYMIZED steps missing (case_03/04/21/25-28) -> anonymized analytics carry no
  identifier, so no evidence row ties them to a subject -> discovery signal 5 links them through deletion_worker
  ANONYMIZE_RECORD activity in the case window plus subject-ordered listings in evidence_02 (16 -> 19 exact).
- P3: candidate pools of 4-9 users per analytics record -> multi-day [requested_at, reported_at] window spans other
  clusters -> window [reported_at - 90 min, + 150 min], same-side-of-report rule, 15 min story preference.
- P3: 7 security-audit VERIFY_RECORD_PRESENT steps missing (case_09/18/20/23/24/29/30) -> their only rows are in
  files captured after audit_at -> RETAIN records observed later still get a future verification in INCOMPLETE
  cases (19 -> 22 exact; 18/20 remain because their records are in no text file).
- P3: case_19 extra export_1260 finding -> policy linkage attached a record that LINK_RESOURCE_IDENTITY already
  ties to user_18 -> exclude records linked to any subject from signal 5.
- P3: case_10 support_002 got VERIFY_RECORD_REDACTED instead of a remaining-record finding -> support category
  defaults to REDACT but the row is a legacy contact-index copy with deletion_marker false -> marker-missing forces DELETE.
- P3: case_04 cited evidence_90 instead of evidence_54 for account_004 -> evidence_90 is an empty scoped extract
  that "omits" every account -> omission citation needs a file listing other records of the system; then case_31
  cited evidence_07 instead of evidence_51 -> files holding the subject's other records win first (22 -> 25 exact).

- P3b: 18 eval cases chosen_account=None, case_53 COMPLETE with [], 23 orphan account activities -> NEAR_REPORT_MIN=90
  filtered out true accounts logged 2h05-2h15 before reported_at, so cases competed for neighbours' accounts ->
  NEAR_REPORT_MIN=150 plus a one-to-one leftover pass over orphan account activities (chosen=None 18 -> 1).

- P4: crash on --classify-intent (Bedrock 400 "text content blocks must be non-empty") -> an empty first reply was
  re-sent as an empty assistant turn in the schema re-ask -> re-ask fresh when the previous reply is empty; 4xx -> ExtractionFailed.
- P4: 5 sample cases (case_06/21/25/27/28) classified NOT_APPLICABLE although every sample authorizes deletion -> prompt
  read "verify my deletion / remove the leftover search result" as a status question -> prompt states that follow-ups
  asking to finish, verify or clean up the person's own deletion authorize deletion (NA 15 -> 10, 0 activity disagreements).
- P4: case_07 support_001 graded REDACT instead of DELETE -> vision rows took the support_ prefix default SUPPORT_MESSAGE
  (rule_05 REDACT) though evidence_58 is the customer's uploaded attachment -> model emits a validated category and the
  merge prefers SUPPORT_ATTACHMENT (rule_06 DELETE) (25 -> 26/32).
- P4: support_9538 emitted 3 times by the reconcile pass -> no per-resource merge -> merge rows by resource_id.

(append per tuning iteration; this is what the judges asked for)

## Verifier findings after Phase 3 (2026-10-25)

- Full-run invariants hold: 0 future-evidence citations, 0 COMPLETE steps without evidence, 0 INCOMPLETE
  remediation/verification with evidence, step numbers consecutive, 3,235 steps (6.25 per case), 169 COMPLETE /
  349 INCOMPLETE before intent classification.
- (Fixed in P3b: chosen=None now 1, case_53.) Defect: 18 cases have no chosen account (NEAR_REPORT_MIN=90 too tight; 23 orphan account activities exist);
  case_53 is COMPLETE with []. Fix is Phase 3b in prompts.md. 101 cases have no security-audit step, mostly
  because their audit records never appear in participant data (e.g. audit_record_6645/5569 appear nowhere).
- The analytics tie in case_03 (analytics_9406 vs 5589, anonymized 15 s apart, no identifiers) is informational
  like the account ties; do not spend effort on it.

## Next step

All phases DONE. Submit: output.csv, code.zip, log.txt (chat_transcript) at
https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists
