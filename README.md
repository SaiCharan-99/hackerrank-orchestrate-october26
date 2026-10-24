# Ghost Data Still Exists — deletion-audit agent

HackerRank Orchestrate, October 2026. For each request in `dataset/deletion_requests.csv` the agent decides
whether deletion was actually requested, rebuilds the subject's current and historical identifiers, finds every
copy of their data in the supplied evidence as it stood at `audit_at`, applies `dataset/deletion_rules.csv`, and
writes `output.csv` (`case_id,deletion_status,steps_json`) with findings, ordered remediation and verification.

Challenge: https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

## Architecture (one line per module, all under `code/ghost/`)

| Module | Role |
|---|---|
| `load.py`, `config.py` | Read every participant-facing CSV as strings; paths relative to the repo root; `.env` config |
| `identity.py` | One subject per `user_id`: current + historical email/phone/hash from `user_audit_log.csv` |
| `evidence/` | Parsers for SQL snapshots (replica drift), JSON exports, logs, text, and cached PNG/PDF extraction |
| `discovery.py` | Ties each request to its account and footprint (evidence ownership, activity window, elimination) |
| `intent.py` | Does the request text authorize deletion? Keyword pre-filter, else an LLM classifier (cached) |
| `engine.py` | State at `audit_at` per resource, rule application, findings → remediation → verification |
| `output.py` | Writer + validator for the output contract; `--audit` harm signals |
| `llm.py`, `prompts/` | OpenAI-compatible gateway client, usage ledger, budget guard; prompts as Python strings |
| `grade.py`, `custom_cases.py` | Local grader for the 32 samples and the 9 custom/adversarial cases |

Models are used only for PNG/PDF extraction (two model families plus a reconciler) and for ambiguous request
intent. Everything else is deterministic Python. All model results are cached in `code/cache/`, so the default
run makes zero model calls and is byte-for-byte reproducible.

## How to run

Requirements: Python 3.11+. Run every command from the repository root (the folder holding `code/`).
`requirements.txt` and `.env.example` sit at the repository root; identical copies are in `code/` so an
unzipped `code.zip` has them too (use `code/requirements.txt` and `code/.env.example` there).

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

`.env` holds `LLM_BASE_URL`, `LLM_API_KEY` and the role → model settings. The key may be left **empty** for a
normal run: every model result is read from `code/cache/`. Place the participant `dataset/` folder at the
repository root (next to `code/`).

Full run (writes `output.csv` at the repository root, validates it, zero model calls):

```bash
python code/main.py
```

Evaluation wrapper (sample grader + custom cases + output audit; exit 0 when custom cases and audit pass):

```bash
python code/evaluation/main.py
```

Live re-extraction (needs `LLM_API_KEY`; ignores the caches and calls the gateway again, then re-run
`python code/main.py`). Estimate the cost first with `--dry-run-cost`:

```bash
python code/main.py --extract-vision --refresh-cache
```

```bash
python code/main.py --classify-intent --refresh-cache
```

```bash
python code/main.py --triage --refresh-cache
```

### Every debug command

| Command | What it prints |
|---|---|
| `python code/main.py --counts` | Row counts of every dataset table, email resolution split |
| `python code/main.py --subject <email>` | The resolved subject: identifiers, history, linked resources |
| `python code/main.py --identity-check` | Identity checks: all request emails resolve |
| `python code/main.py --evidence <resource_id>` | Every parsed evidence row for one resource |
| `python code/main.py --coverage` | Parser coverage and the sample citation check |
| `python code/main.py --discovery` | Account discovery per case: chosen account, ties, unchosen count |
| `python code/main.py --case <case_id>` | The full audit of one case (footprint, notes, steps) |
| `python code/main.py --grade [--analytics-hypothesis attempted_delete\|always_anonymize]` | Sample grader |
| `python code/main.py --grade-custom` | The 9 custom and adversarial cases in `code/evaluation/custom_cases/` |
| `python code/main.py --audit` | Re-validates `output.csv`, determinism check, harm signals, status mix |
| `python code/main.py --usage` | Usage ledger totals per model (source of `usage_report.md`) |
| `python code/main.py --dry-run-cost` | Estimated cost of uncached model work |
| `python code/tools/list_models.py` | Models offered by the configured gateway (needs the key) |

## Results and the commands behind them

Sample set (32 cases with public answers) — `python code/main.py --grade`:

| Metric | Value |
|---|---|
| Deletion-status accuracy | 1.000 (32/32) |
| Case exact (status + full ordered steps) | 26/32 |
| Step recall / precision | 0.969 / 0.979 |
| Field accuracy (phase / system_id / resource_id / operation / state / evidence_id) | 0.990 / 0.969 / 0.948 / 0.969 / 0.969 / 0.984 |
| Sequence exact / pairwise order agreement | 0.812 / 1.000 |

Custom and adversarial cases — `python code/main.py --grade-custom`: 9/9 pass (custom 5/5, adversarial 4/4).

Full evaluation run — `python code/main.py --audit`: validator PASS, 518 rows, output matches a fresh rebuild,
153 COMPLETE / 355 INCOMPLETE / 10 NOT_APPLICABLE, 0 citations of evidence captured after `audit_at`.

Model usage behind `output.csv` — `python code/main.py --usage`: 182 calls, 245,695 input / 50,875 output tokens,
estimated $0.9714 ($0.001875 per request over 518). Models: `claude-sonnet`
(`bedrock/global.anthropic.claude-sonnet-5-5`), `bedrock/qwen.qwen3-vl-235b-a22b`, `claude-haiku`
(`claude-haiku-5-5`). Costs are estimates from the price table in `ghost/llm.py`.

Full reports: [`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md),
[`code/evaluation/usage_report.md`](code/evaluation/usage_report.md).

## Known limits

- **Account ties.** In many evaluation cases several accounts were deleted in the same window with identical
  results and no identifier ties any of them to the subject. The agent makes a deterministic one-to-one choice
  and notes it as tentative; only the `account_service` step's `resource_id` can be wrong in those cases
  (samples case_23, case_28, case_29; case_03 is the same tie for an anonymized analytics record).
- **Missing audit records.** Some policy-retained security audit records appear in no participant file
  (samples case_18, case_20), so their `VERIFY_RECORD_PRESENT` step cannot be produced.
- One evaluation case has no account activity at all and is reported with the note "account unknown".
- Cost figures are estimates, not gateway invoices.

## Packaging

`code.zip` contains `README.md` and `code/` only (no `dataset/`, `.env`, `log.txt`, `__pycache__`).
After unzipping, copy `dataset/` next to `code/` and run `python code/main.py`.
