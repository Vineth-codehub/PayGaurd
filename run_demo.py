"""
PayGuard — Agentic Revenue Recovery
Track 03: AI Revenue Recovery

Detects revenue at risk (failed payments, checkout drop-off, failed
subscriptions), reconstructs conflicting payment context, chooses a
bounded intervention, executes only AUTO actions exactly once, and
reports rupees recovered vs naive retry-all and do-nothing.
"""

import os
import subprocess
import sys

STEPS = [
    ("Idempotent execution", "test_idempotency.py"),
    ("Context resolver (10 hard cases)", "run_hard_cases.py"),
    ("Policy-gated pipeline", "test_pipeline.py"),
    ("Batch money recovered (n=200)", "run_batch.py"),
]


def main():
    for title, script in STEPS:
        print("", flush=True)
        print("#" * 72, flush=True)
        print(f"# {title}", flush=True)
        print("#" * 72, flush=True)
        env = dict(**os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, script], env=env)
        if r.returncode != 0:
            raise SystemExit(r.returncode)
    print()
    print("ALL TRACK 03 CHECKS PASSED.")


if __name__ == "__main__":
    main()
