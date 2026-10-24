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
| 0 | Scaffold, loader, model probe | TODO | `python code/main.py --counts` prints table counts; `python code/tools/list_models.py` lists gateway models |
| 1 | Identity graph | TODO | all 518 request emails resolve to a `user_id`; `--subject` prints sample subjects with account ids |
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

## Decisions and parameters

(append per phase)

## Open issues

(append per phase)

## Diagnosis log (signal → cause → change)

(append per tuning iteration; this is what the judges asked for)

## Next step

Phase 0.
