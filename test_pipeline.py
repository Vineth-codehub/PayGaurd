"""
Decide -> gate -> idempotent execute.

Proves: mixed AUTO / APPROVAL_REQUIRED / BLOCKED verdicts; duplicate
webhooks execute once; gated cases never hit the gateway.
"""

import os
from contextlib import closing

from pipeline import handle_case, idempotency_key_for
from payguard_idempotency import get_db, DB_PATH


def reset_db():
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)


def gateway_count(key):
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM gateway_ledger WHERE idempotency_key = ?", (key,)
        ).fetchone()[0]


CASES = [
    {"case_id": "PG-2001", "scenario": "payment_failure", "failure_reason": "BANK_TIMEOUT",
     "attempt_count": 0, "amount": 8500},
    {"case_id": "PG-2002", "scenario": "payment_failure", "failure_reason": "UPI_TIMEOUT",
     "attempt_count": 1, "amount": 3200},
    {"case_id": "PG-2003", "scenario": "payment_failure", "failure_reason": "INSUFFICIENT_FUNDS",
     "attempt_count": 0, "amount": 62000},
    {"case_id": "PG-2004", "scenario": "payment_failure", "failure_reason": "ISSUER_DECLINE",
     "attempt_count": 0, "amount": 4100},
    {"case_id": "PG-2005", "scenario": "payment_failure", "failure_reason": "PAYMENT_GATEWAY_ERROR",
     "attempt_count": 2, "amount": 900},
    {"case_id": "PG-2006", "scenario": "payment_failure", "failure_reason": "UNKNOWN_PAYMENT_FAILURE",
     "attempt_count": 0, "amount": 1500},
    {"case_id": "PG-2007", "scenario": "checkout_abandonment", "failure_reason": "CART_ABANDONED",
     "attempt_count": 0, "amount": 2200, "customer_history": "unresponsive", "contacts_already": 1},
    {"case_id": "PG-2008", "scenario": "subscription_failure", "failure_reason": "MANDATE_FAILED",
     "attempt_count": 0, "amount": 499},
]


def main():
    reset_db()

    print("=" * 74)
    print("Pipeline: decide -> policy gate -> idempotent execute")
    print("=" * 74)

    print("\n-- Part 1: verdict mix --")
    verdict_counts = {}
    for case in CASES:
        r = handle_case(case)
        verdict_counts[r["policy_verdict"]] = verdict_counts.get(r["policy_verdict"], 0) + 1
        print(
            f"  {r['case_id']}: {r['scenario']:22s} action={r['decided_action']:24s} "
            f"verdict={r['policy_verdict']:17s} executed={r['executed']}"
        )
    print(f"\n  Verdict mix: {verdict_counts}")
    assert "AUTO" in verdict_counts and verdict_counts["AUTO"] < len(CASES)
    assert "BLOCKED" in verdict_counts or "APPROVAL_REQUIRED" in verdict_counts
    print("  PASS: gating produced a mix, not all-auto.\n")

    print("-- Part 2: duplicate webhook on an AUTO retry --")
    auto_case = CASES[0]
    action_for_key = handle_case(auto_case)["decided_action"]
    key = idempotency_key_for(auto_case, action_for_key)
    for i in range(5):
        r = handle_case(auto_case)
        path = r["execution_result"]["path"] if r["execution_result"] else None
        print(f"  call {i + 1}: executed={r['executed']}  path={path}")
    n = gateway_count(key)
    print(f"  Gateway executions: {n}")
    assert n == 1
    print("  PASS: exactly one real execution.\n")

    print("-- Part 3: gated case never reaches the gateway --")
    gated_case = CASES[4]
    r = handle_case(gated_case)
    key2 = idempotency_key_for(gated_case, r["decided_action"])
    n2 = gateway_count(key2)
    print(f"  {gated_case['case_id']}: verdict={r['policy_verdict']}, executed={r['executed']}, gateway={n2}")
    assert r["executed"] is False
    assert n2 == 0
    print("  PASS: gated case never touched the executor.\n")

    print("-- Audit trail --")
    with closing(get_db()) as conn:
        print("  case_events:")
        for row in conn.execute(
            "SELECT idempotency_key, case_id, action, status FROM case_events ORDER BY created_at"
        ):
            print("   ", row)
        print("  gateway_ledger:")
        for row in conn.execute(
            "SELECT idempotency_key, case_id, action FROM gateway_ledger ORDER BY executed_at"
        ):
            print("   ", row)

    print("\nALL PIPELINE CHECKS PASSED.")


if __name__ == "__main__":
    main()
