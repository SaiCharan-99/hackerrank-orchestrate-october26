"""Request-intent classifier: does request_text authorize deletion?

A deterministic keyword pre-filter decides unambiguous English deletion requests without a call; the text
model classifies the rest. Results are cached by sha256(text) in code/cache/intent.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from pydantic import BaseModel

from .config import CACHE_DIR
from .prompts import intent as P

INTENT_CACHE = CACHE_DIR / "intent.json"

STRONG_DELETION = re.compile(
    r"permanent(ly)?\s+(account[- ])?delet|request\w*\s+(for\s+)?(permanent\s+)?(account\s+)?deletion"
    r"|delete\s+this\s+account|\berase\b|\berased\b|deletion\s+process|remove\s+my\s+account"
    r"|personal-data\s+deletion|permanently\s+deleted|personal\s+data\s+deleted|close\s+this\s+account\s+permanently",
    re.I)
# Any of these sends the text to the model even if a deletion phrase is present.
NEGATIVE_CUES = re.compile(
    r"don't|don’t|do\s+not|without\s+(removing|deleting)|keep\s+the\s+account|leave\s+(the|my)\s|still\s+(use|want)"
    r"|continue\s+using|copy\s+of|download|portable|marketing|misspel|replace\s+it|reset|only\b|whether|\?",
    re.I)


class IntentLabel(BaseModel):
    authorizes_deletion: bool
    reason: str
    language: str = ""


@dataclass(frozen=True)
class Intent:
    authorizes_deletion: bool
    reason: str
    language: str
    source: str  # "keyword" | "model:<id>" | "fallback"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def prefilter(text: str) -> Intent | None:
    """Unambiguous English deletion request -> Intent; anything else -> None (needs the model)."""
    if text.isascii() and STRONG_DELETION.search(text) and not NEGATIVE_CUES.search(text):
        return Intent(True, "explicit deletion request; no limiting or contrary instruction", "en", "keyword")
    return None


def _load() -> dict:
    return json.loads(INTENT_CACHE.read_text(encoding="utf-8")) if INTENT_CACHE.exists() else {}


def _save(cache: dict) -> None:
    INTENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    INTENT_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                            encoding="utf-8", newline="\n")


def classify_texts(texts, llm=None, model: str = "", *, refresh: bool = False,
                   only_cached: bool = False) -> dict[str, Intent]:
    """text -> Intent for every distinct text. Without a model result the fallback is deletion=True with
    source 'fallback' (the activity cross-check then flags it), so a run never stops on a missing label."""
    from .llm import BudgetExceeded, ExtractionFailed

    cache = {} if refresh else _load()
    out: dict[str, Intent] = {}
    dirty = False
    for text in sorted(set(texts)):
        pre = prefilter(text)
        if pre is not None:
            out[text] = pre
            continue
        h = text_hash(text)
        if h in cache:
            c = cache[h]
            out[text] = Intent(c["authorizes_deletion"], c["reason"], c["language"], c["source"])
            continue
        if only_cached or llm is None:
            out[text] = Intent(True, "not classified (no cached label); defaulted to deletion", "", "fallback")
            continue
        try:
            lab = llm.structured(IntentLabel, model, P.CLASSIFY.format(text=text), purpose="intent", item=h[:12],
                                 max_tokens=300)
        except (ExtractionFailed, BudgetExceeded) as exc:
            out[text] = Intent(True, f"extraction_failed: {str(exc)[:120]}; defaulted to deletion", "", "fallback")
            continue
        cache[h] = {"authorizes_deletion": lab.authorizes_deletion, "reason": lab.reason,
                    "language": lab.language, "source": f"model:{model}", "text": text}
        out[text] = Intent(lab.authorizes_deletion, lab.reason, lab.language, f"model:{model}")
        dirty = True
    if dirty or refresh:
        _save(cache)
    return out


def classify_requests(requests, llm=None, model: str = "", **kw) -> dict[str, Intent]:
    """case_id -> Intent."""
    labels = classify_texts(list(requests["request_text"]), llm, model, **kw)
    return {r.case_id: labels[r.request_text] for r in requests.itertuples(index=False)}


def non_deletion_accounts(activity) -> dict[str, str]:
    """account_id -> activity_id for CLASSIFY_REQUEST activities that classified a request as non-deletion."""
    a = activity[(activity["event_type"] == "CLASSIFY_REQUEST")
                 & activity["details"].str.contains("non-deletion", case=False)]
    return dict(zip(a["resource_id"], a["activity_id"]))


def cross_check(intents: dict[str, Intent], discoveries, activity) -> list[str]:
    """Disagreements between the classifier and CLASSIFY_REQUEST non-deletion activities."""
    nd = non_deletion_accounts(activity)
    out = []
    for cid, it in sorted(intents.items()):
        d = discoveries.get(cid)
        acct = d.chosen_account if d else None
        cands = set(d.account_candidates) if d else set()
        hit = acct in nd
        if hit and it.authorizes_deletion:
            out.append(f"{cid}: classifier=DELETION but {nd[acct]} classified {acct} as non-deletion")
        if not it.authorizes_deletion and not hit:
            near = sorted(cands & set(nd))
            out.append(f"{cid}: classifier=NON_DELETION ({it.reason}); chosen account {acct} has no non-deletion "
                       f"activity" + (f" (candidate {near} does)" if near else ""))
    used = {d.chosen_account for d in discoveries.values() if d and d.chosen_account}
    out += [f"{nd[a]}: non-deletion activity for {a} matched by no case" for a in sorted(set(nd) - used)]
    return out
