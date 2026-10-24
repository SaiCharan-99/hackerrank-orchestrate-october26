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
| 3 | State engine + local grader | TODO | `--grade` reports 32/32 exact sample matches |
| 4 | Vision extraction + intent classifier + triage | TODO | vision agreement pass clean; `NOT_APPLICABLE` set agrees with `CLASSIFY_REQUEST` activities |
| 5 | Full run + validator | TODO | `output.csv` 518 rows, validator PASS, zero future-evidence citations |
| 6 | Evaluation reports + custom/adversarial cases | TODO | `code/evaluation/evaluation_report.md` and `usage_report.md` filled from grader/ledger output |
| 7 | README, interview checklist, code.zip | TODO | zip = `README.md` + `code/`, no dataset/.env/log; clean run from a fresh unzip |

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

## Decisions and parameters

- P0: CSVs read with `dtype=str, keep_default_na=False` so empty identifiers stay `""` (never NaN) and ids are never coerced.
- P0: `dataset/output.csv` template has 0 rows, so row order falls back to `natural_case_key` (text/int runs).
- P0: `config.py` exposes only `has_api_key`; the raw key is reachable solely via `config.api_key()` for client construction.
- P0: role model defaults mirror `.env.example` (vision `claude-sonnet`, vision B `bedrock/qwen.qwen3-vl-235b-a22b`, text `claude-haiku`, triage `claude-sonnet`, budget $10).

## Open issues

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

(append per tuning iteration; this is what the judges asked for)

## Next step

Phase 3 (State engine + local grader): consume `discover()` results (chosen_account + resources per case) and
build steps; paste the prompts.md "Phase 3" block.
