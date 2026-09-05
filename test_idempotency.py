"""Verification for idempotent recovery execution.

1. Same event fired 5 times -> exactly one gateway action.
2. Hard-kill mid-execution, restart -> still one gateway action.
"""

import os
import sys
import subprocess
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from payguard_idempotency import process_event, get_db, DB_PATH  # noqa: E402


def reset_db():
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)


def gateway_execution_count(key):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM gateway_ledger WHERE idempotency_key = ?", (key,)
        ).fetchone()[0]


def case_status(key):
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT status FROM case_events WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return row[0] if row else None


def print_audit_trail():
    print("\n--- audit trail: case_events ---")
    with closing(get_db()) as conn:
        for row in conn.execute("SELECT * FROM case_events ORDER BY created_at"):
            print(" ", row)
        print("--- audit trail: gateway_ledger (source of truth) ---")
        for row in conn.execute("SELECT * FROM gateway_ledger ORDER BY executed_at"):
            print(" ", row)


def test_duplicate_webhook():
    print("TEST 1: same webhook event fired 5 times in a row")
    key, case_id, action = "evt_abc123", "case_PG-1001", "RETRY_PAYMENT"
    for i in range(5):
        out = process_event(key, case_id, action)
        print(f"  call {i + 1}: path={out['path']}  result={out['result']}")

    n = gateway_execution_count(key)
    print(f"  Gateway executions for {key}: {n}")
    assert n == 1, f"FAILED: expected exactly 1 execution, got {n}"
    print("  PASS: exactly one real execution despite 5 calls.\n")


def test_crash_mid_execution():
    print("TEST 2: process is hard-killed mid-execution, then restarted")
    key, case_id, action = "evt_crash001", "case_PG-1002", "RETRY_PAYMENT"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payguard_idempotency.py")

    p = subprocess.run([sys.executable, script, key, case_id, action, "--crash"])
    print(f"  first run exited with code {p.returncode} (simulated crash, non-zero expected)")

    status_after_crash = case_status(key)
    gw_after_crash = gateway_execution_count(key)
    print(f"  after crash -> case_events.status={status_after_crash}, "
          f"gateway executions so far={gw_after_crash}")
    assert status_after_crash == "IN_PROGRESS", "sanity check: crash should leave status IN_PROGRESS"
    assert gw_after_crash == 1, "sanity check: the real side effect should have landed before the crash"

    out = process_event(key, case_id, action)
    print(f"  restart call -> path={out['path']}, result={out['result']}")

    gw_after_restart = gateway_execution_count(key)
    print(f"  Gateway executions for {key} after restart: {gw_after_restart}")
    assert gw_after_restart == 1, f"FAILED: restart caused a duplicate execution ({gw_after_restart})"
    assert out["path"] == "RECOVERED_FROM_CRASH", "restart should take the crash-recovery path"
    print("  PASS: crash + restart resumed safely, exactly one real execution.\n")


if __name__ == "__main__":
    reset_db()
    test_duplicate_webhook()
    test_crash_mid_execution()
    print_audit_trail()
    print("\nALL TESTS PASSED.")
