"""Runtime configuration loaded from the repository-root .env (never logs secret values)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
CODE_DIR = REPO_ROOT / "code"
CACHE_DIR = CODE_DIR / "cache"
EVALUATION_DIR = CODE_DIR / "evaluation"
OUTPUT_PATH = REPO_ROOT / "output.csv"

# Explicit path: bare load_dotenv() fails under stdin execution on the build machine.
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    llm_base_url: str
    has_api_key: bool
    vision_model: str
    vision_model_b: str
    text_model: str
    triage_model: str
    budget_usd: float


def load_config() -> Config:
    return Config(
        llm_base_url=os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        has_api_key=bool(os.environ.get("LLM_API_KEY")),
        vision_model=os.environ.get("LLM_VISION_MODEL", "claude-sonnet"),
        vision_model_b=os.environ.get("LLM_VISION_MODEL_B", "bedrock/qwen.qwen3-vl-235b-a22b"),
        text_model=os.environ.get("LLM_TEXT_MODEL", "claude-haiku"),
        triage_model=os.environ.get("LLM_TRIAGE_MODEL", "claude-sonnet"),
        budget_usd=float(os.environ.get("LLM_BUDGET_USD", "10")),
    )


def api_key() -> str:
    """Return the key for client construction only; callers must never print it."""
    return os.environ.get("LLM_API_KEY", "")
