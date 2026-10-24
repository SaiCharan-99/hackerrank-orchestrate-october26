"""List the models exposed by the OpenAI-compatible LLM gateway configured in .env.

Usage:  python code/tools/list_models.py [--filter substring]

Reads LLM_BASE_URL and LLM_API_KEY from the repository-root .env. Never prints the key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="", help="only show ids containing this text")
    parser.add_argument("--json", action="store_true", help="dump raw response")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    if not base:
        print("LLM_BASE_URL is not set in .env", file=sys.stderr)
        return 2
    if not key:
        print("LLM_API_KEY is empty in .env; paste the key and re-run.", file=sys.stderr)
        return 2

    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} from gateway: {e.read().decode('utf-8', 'replace')[:500]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Could not reach gateway: {e.reason}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    models = payload.get("data", payload if isinstance(payload, list) else [])
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in models:
        mid = m.get("id", "")
        if args.filter and args.filter.lower() not in mid.lower():
            continue
        provider = m.get("owned_by") or mid.split("/")[0] if "/" in mid else m.get("owned_by", "unknown")
        groups[str(provider)].append(m)

    total = 0
    for provider in sorted(groups):
        print(f"\n== {provider} ({len(groups[provider])})")
        for m in sorted(groups[provider], key=lambda x: x.get("id", "")):
            total += 1
            extras = {k: v for k, v in m.items() if k not in {"id", "object", "owned_by", "created"}}
            hint = ""
            if extras:
                hint = "  " + json.dumps(extras, separators=(",", ":"))[:160]
            print(f"  {m.get('id')}{hint}")
    print(f"\n{total} models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
