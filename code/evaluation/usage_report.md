# Usage report: final full-dataset run

Source: `code/cache/usage_log.jsonl`, the ledger that `ghost/llm.py` appends to on every gateway call.
Printed by `python code/main.py --usage`.

## How the run uses models

- `output.csv` is produced by `python code/main.py`. That command reads every LLM result from the caches
  (`code/cache/vision/*.json`, `intent.json`, `triage.json`) and makes **zero** calls itself.
- The calls below are the extraction and classification calls that filled those caches for the 518
  evaluation requests. The same passes also covered the 32 sample requests and all 15 PNG/PDF evidence
  files.
- Everything else (parsing, identity, discovery, the rule engine, the validator) is deterministic Python
  and uses no model.
- The one call made by `--grade-custom` (Spanish custom case c5) is reported separately. It is not part of
  the run.

## Models

| Role | Model (gateway alias) | Provider |
|---|---|---|
| Vision / PDF extraction, model A, and the third-pass reconciler | `claude-sonnet` → `bedrock/global.anthropic.claude-sonnet-5-5` | Anthropic (via Bedrock gateway) |
| Vision / PDF extraction, model B (different family) | `bedrock/qwen.qwen3-vl-235b-a22b` | Qwen (via Bedrock gateway) |
| Request-intent classifier | `claude-haiku` → `claude-haiku-5-5` | Anthropic |
| Evidence triage | `claude-sonnet` | Anthropic. 0 calls: no candidate rows in this dataset |

## Pipeline totals (all calls behind `output.csv`; averages over 518 requests)

| Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) | Tokens / request | Cost / request (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| bedrock/qwen.qwen3-vl-235b-a22b | 33 | 73,857 | 10,221 | 84,078 | 0.0663 | 162.3 | 0.000128 |
| claude-haiku | 106 | 37,187 | 14,587 | 51,774 | 0.1101 | 99.9 | 0.000213 |
| claude-sonnet | 43 | 134,651 | 26,067 | 160,718 | 0.7950 | 310.3 | 0.001535 |
| **Overall** | **182** | **245,695** | **50,875** | **296,570** | **0.9714** | **572.5** | **0.001875** |

Calls by purpose: intent = 106, vision = 63 (A + B first passes and schema re-asks), vision_reconcile = 13.
There were no triage calls.

- Average model calls per request: 182 / 518 = 0.35.
- 454 of the 550 requests (evaluation plus sample) were decided by the deterministic keyword pre-filter, so they needed no call.

## Separate: custom-case calls (not part of `output.csv`)

| Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|---:|
| claude-haiku | 1 | 436 | 70 | 506 | 0.0008 |

Whole ledger including that call: 183 calls, 246,131 input / 50,945 output tokens, est. $0.9722.

## Printed output

```text
Pipeline usage (all LLM calls behind output.csv; averages over 518 requests)
  model                                provider       calls  input_tok output_tok  total_tok  est_usd  tok/req   usd/req
  bedrock/qwen.qwen3-vl-235b-a22b      bedrock:qwen      33      73857      10221      84078   0.0663    162.3  0.000128
  claude-haiku                         anthropic        106      37187      14587      51774   0.1101     99.9  0.000213
  claude-sonnet                        anthropic         43     134651      26067     160718   0.7950    310.3  0.001535
  ALL                                  -                182     245695      50875     296570   0.9714    572.5  0.001875
Calls by purpose: intent=106, intent-custom=1, vision=63, vision_reconcile=13
Custom-case calls (--grade-custom; not part of output.csv)
  model                                provider       calls  input_tok output_tok  total_tok  est_usd
  claude-haiku                         anthropic          1        436         70        506   0.0008
  ALL                                  -                  1        436         70        506   0.0008
```

## Cost basis and caveats

- Costs are **estimates** from the price table in `ghost/llm.py` (`PRICES`, USD per 1M input/output tokens):
  - sonnet 3 / 15
  - haiku 1 / 5
  - qwen3-vl 0.53 / 2.66

  They are not gateway invoices. The `LLM_PRICES_JSON` environment variable overrides them.
- Token counts are the usage figures the gateway returned for each call.
- About 3 small probe or debugging calls were made outside the ledger during Phase 4 (roughly 40 tokens
  for the probe). They are not included.
- A cold re-run with `--refresh-cache` repeats roughly these calls. A normal run (`python code/main.py`)
  costs $0.
