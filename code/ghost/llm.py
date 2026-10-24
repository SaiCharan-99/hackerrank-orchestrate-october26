"""OpenAI-compatible LLM client: retries, usage ledger, budget guard, pydantic-enforced structured output.

Gateway rules (progress.md "Fixed facts"):
- never send `temperature` (Claude 5.x rejects it; determinism comes from caching + schema validation);
- images go only through `client.responses.create` with input_text + input_image data URL
  (chat.completions silently drops images); text-only calls use chat.completions.
On HTTP 400, check those two rules first.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .config import CACHE_DIR, api_key, load_config

USAGE_LOG = CACHE_DIR / "usage_log.jsonl"
MAX_RETRIES = 5
MAX_SCHEMA_RETRIES = 2

# USD per 1M tokens (input, output). Estimates for the usage report; override with LLM_PRICES_JSON
# ('{"model": [in, out]}'). Unknown models fall back to DEFAULT_PRICE.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
    "claude-opus": (5.0, 25.0),
    "bedrock/qwen.qwen3-vl-235b-a22b": (0.53, 2.66),
}
DEFAULT_PRICE = (3.0, 15.0)

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


class ExtractionFailed(RuntimeError):
    def __init__(self, message: str, raw: Any = None):
        super().__init__(message)
        self.raw = raw


def price_for(model: str) -> tuple[float, float]:
    override = os.environ.get("LLM_PRICES_JSON")
    if override:
        table = {k: tuple(v) for k, v in json.loads(override).items()}
        if model in table:
            return table[model]  # type: ignore[return-value]
    return PRICES.get(model, DEFAULT_PRICE)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = price_for(model)
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


def provider_for(model: str) -> str:
    if model.startswith("bedrock/"):
        return "bedrock:" + model.split("/", 1)[1].split(".", 1)[0]
    if model.startswith("claude"):
        return "anthropic"
    return model.split("/", 1)[0] if "/" in model else "gateway"


def ledger_entries(path: Path = USAGE_LOG) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ledger_totals(path: Path = USAGE_LOG) -> dict[str, dict[str, float]]:
    """Per-model and overall totals (calls, prompt/completion tokens, estimated cost)."""
    out: dict[str, dict[str, float]] = {}
    for e in ledger_entries(path):
        for key in (e["model"], "ALL"):
            t = out.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
            t["calls"] += 1
            t["prompt_tokens"] += e["prompt_tokens"]
            t["completion_tokens"] += e["completion_tokens"]
            t["cost_usd"] += e["cost_usd"]
    return out


def image_data_url(path: Path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def extract_json(text: str) -> Any:
    """First JSON object in a model reply (tolerates ```json fences and prose around it)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


@dataclass
class LLM:
    """Thin client. `purpose` tags each ledger line (vision/intent/triage) for the usage report."""

    ledger: Path = USAGE_LOG

    def __post_init__(self) -> None:
        self.cfg = load_config()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            if not self.cfg.has_api_key or not self.cfg.llm_base_url:
                raise ExtractionFailed("LLM gateway not configured (LLM_BASE_URL / LLM_API_KEY)")
            self._client = OpenAI(base_url=self.cfg.llm_base_url, api_key=api_key(), max_retries=0)
        return self._client

    def spent(self) -> float:
        return sum(e["cost_usd"] for e in ledger_entries(self.ledger))

    def _guard(self) -> None:
        if self.spent() >= self.cfg.budget_usd:
            raise BudgetExceeded(f"LLM_BUDGET_USD={self.cfg.budget_usd} reached; no further calls")

    def _log(self, model: str, purpose: str, prompt_tokens: int, completion_tokens: int, latency: float,
             item: str) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "provider": provider_for(model),
                 "model": model, "purpose": purpose, "item": item, "prompt_tokens": prompt_tokens,
                 "completion_tokens": completion_tokens, "latency_s": round(latency, 3),
                 "cost_usd": round(estimate_cost(model, prompt_tokens, completion_tokens), 6)}
        with self.ledger.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def _retry(self, fn):
        delay = 2.0
        for attempt in range(MAX_RETRIES + 1):
            try:
                return fn()
            except Exception as exc:  # openai raises typed errors; only 429/5xx/connection are retried
                code = _status(exc)
                retryable = code is None and "Connection" in type(exc).__name__ or code == 429 or (code or 0) >= 500
                if not retryable or attempt == MAX_RETRIES:
                    raise
                time.sleep(delay)
                delay *= 2

    def complete(self, model: str, messages: list[dict], *, purpose: str, item: str = "",
                 max_tokens: int = 2048) -> str:
        """Text-only call through chat.completions. No temperature (gateway rule)."""
        self._guard()
        t0 = time.monotonic()
        resp = self._retry(lambda: self.client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens))
        u = resp.usage
        self._log(model, purpose, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0,
                  time.monotonic() - t0, item)
        return resp.choices[0].message.content or ""

    def complete_image(self, model: str, prompt: str, image: Path, *, purpose: str, item: str = "",
                       history: list[dict] | None = None, max_tokens: int = 6000) -> str:
        """Image call through the Responses API (input_text + input_image data URL)."""
        self._guard()
        content = [{"type": "input_text", "text": prompt},
                   {"type": "input_image", "image_url": image_data_url(image)}]
        inputs = [{"role": "user", "content": content}] + (history or [])
        t0 = time.monotonic()
        resp = self._retry(lambda: self.client.responses.create(
            model=model, input=inputs, max_output_tokens=max_tokens))
        u = resp.usage
        self._log(model, purpose, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0,
                  time.monotonic() - t0, item)
        return resp.output_text or ""

    def structured(self, schema: type[T], model: str, prompt: str, *, purpose: str, item: str = "",
                   image: Path | None = None, system: str | None = None, max_tokens: int = 4096) -> T:
        """Call, parse JSON, validate with pydantic. On failure re-ask with the error and only the failing
        top-level fields (max MAX_SCHEMA_RETRIES), merging the corrections; then raise ExtractionFailed."""
        def ask(followup: str | None, prev: str | None) -> str:
            if not (prev or "").strip():  # an empty assistant turn is a 400 on Bedrock: ask afresh
                followup = None
            try:
                return _ask(followup, prev)
            except Exception as exc:  # non-retryable gateway error (4xx) -> extraction_failed, not a crash
                if _status(exc) and _status(exc) < 500 and _status(exc) != 429:
                    raise ExtractionFailed(f"gateway {_status(exc)}: {str(exc)[:300]}") from exc
                raise

        def _ask(followup: str | None, prev: str | None) -> str:
            if image is not None:
                hist = ([{"role": "assistant", "content": prev}, {"role": "user", "content": followup}]
                        if followup else None)
                return self.complete_image(model, prompt, image, purpose=purpose, item=item, history=hist,
                                           max_tokens=max_tokens)
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            if followup:
                msgs += [{"role": "assistant", "content": prev}, {"role": "user", "content": followup}]
            return self.complete(model, msgs, purpose=purpose, item=item, max_tokens=max_tokens)

        reply = ask(None, None)
        obj: Any = None
        for attempt in range(MAX_SCHEMA_RETRIES + 1):
            try:
                if obj is None:
                    obj = extract_json(reply)
                return schema.model_validate(obj)
            except (ValueError, ValidationError) as exc:
                if attempt == MAX_SCHEMA_RETRIES:
                    raise ExtractionFailed(f"schema validation failed: {exc}", raw=reply) from exc
                if isinstance(exc, ValidationError) and isinstance(obj, dict):
                    fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
                    followup = (f"Your JSON failed validation:\n{exc}\nReturn ONLY a JSON object with the corrected "
                                f"top-level fields {fields}; keep every other field as it was.")
                    fix = ask(followup, reply)
                    try:
                        obj = {**obj, **extract_json(fix)}
                    except ValueError:
                        pass
                else:
                    followup = f"Your reply was not valid JSON ({exc}). Return ONLY the JSON object."
                    reply = ask(followup, reply)
                    obj = None
        raise ExtractionFailed("unreachable")
