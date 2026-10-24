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
| 2 | Text evidence parsers (SQL / JSON / logs / txt) | TODO | every sample finding and verification resource is found in the cited file at ≤ `audit_at` |
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

## Decisions and parameters

- P0: CSVs read with `dtype=str, keep_default_na=False` so empty identifiers stay `""` (never NaN) and ids are never coerced.
- P0: `dataset/output.csv` template has 0 rows, so row order falls back to `natural_case_key` (text/int runs).
- P0: `config.py` exposes only `has_api_key`; the raw key is reachable solely via `config.api_key()` for client construction.
- P0: role model defaults mirror `.env.example` (vision `claude-sonnet`, vision B `bedrock/qwen.qwen3-vl-235b-a22b`, text `claude-haiku`, triage `claude-sonnet`, budget $10).

## Open issues

- P1: 0/32 sample account ids linkable from activity; Phase 2 evidence parsers must call `Subject.add_resource`
  with `customer_reference` / `subject_reference` / `lookup_key=user_N` matches, then `IdentityIndex.reindex()`.
- P1: identity history is not yet time-filtered; LINK activity_4000 is dated 2026-09-26, so Phase 3 must
  ignore links and evidence after `audit_at` when choosing resources and citations.

- P0: first cold `--counts` run took 5.4 s (pandas import cold cache); warm runs 1.6 s. Not a blocker.

## Decisions and parameters (P1)

- P1: resolution requires a unique owner; an identifier shared by >1 user returns None (0 such emails today).
- P1: LINK_RESOURCE_IDENTITY attaches the activity `resource_id` only if the named user_N exists and every email in details belongs to that user.
- P1: `account_ids` is the `account_*` subset of `resource_ids`; `sources` maps each value to its origin refs (`identities`, `audit_log:<audit_id>`, `activity LINK_RESOURCE_IDENTITY:<activity_id>`, `sha256(<email>)`).
- P1: recorded email_hash equals sha256(lower(email)) (checked on samples), so computed hashes are safe to match.

## Diagnosis log (signal → cause → change)

- P1: none (no fixes; all checks matched first run).

(append per tuning iteration; this is what the judges asked for)

## Next step

Phase 2 (Text evidence parsers): feed account/resource links into `Subject.add_resource`.
