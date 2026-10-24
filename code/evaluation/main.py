"""Evaluation wrapper: sample grader, custom/adversarial cases, and output.csv audit.

Usage:  python code/evaluation/main.py

Equivalent to running, in order:
        python code/main.py --grade
        python code/main.py --grade-custom
        python code/main.py --audit
Each step runs in its own process (same as typing the commands). All three use the caches,
so this makes zero LLM calls. Exit code is 0 only if --grade-custom and --audit both pass;
--grade reports the 6 known sample mismatches and its exit code is shown, not enforced.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"
STEPS = [("--grade", False), ("--grade-custom", True), ("--audit", True)]


def main() -> int:
    failed = []
    for flag, required in STEPS:
        print(f"===== python code/main.py {flag}", flush=True)
        code = subprocess.call([sys.executable, str(MAIN), flag])
        print(f"===== {flag} exit {code}", flush=True)
        if required and code != 0:
            failed.append(flag)
    print("EVALUATION: " + ("PASS" if not failed else "FAIL " + " ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
