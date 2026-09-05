"""
Idempotent recovery-action executor.

Same event N times → one gateway side effect. Crash after the gateway
call but before our bookkeeping is marked DONE → restart re-asks the
gateway with the same key and does not double-run.

case_events is our view (can go stale). gateway_ledger is the source of
truth and dedupes on the idempotency key — the same pattern a real
retry/refund API expects.
"""

import sqlite3
import sys
import os
import json
import tempfile
from contextlib import closing

# Keep the ledger off OneDrive/Downloads; synced folders make SQLite
# raise "readonly database" under concurrent Windows file-lock.
DB_PATH = os.environ.get(
    "PAYGUARD_DB",
    os.path.join(tempfile.gettempdir(), "payguard.db"),
)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    # DELETE journal avoids leftover WAL files locking the next process on Windows.
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def init_db():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS case_events (
                idempotency_key TEXT PRIMARY KEY,
                case_id         TEXT NOT NULL,
                action          TEXT NOT NULL,
                status          TEXT NOT NULL,  -- IN_PROGRESS, DONE
                result          TEXT,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gateway_ledger (
                idempotency_key TEXT PRIMARY KEY,
                case_id         TEXT NOT NULL,
                action          TEXT NOT NULL,
                executed_at     TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def simulate_gateway_call(idempotency_key, case_id, action):
    """Stand-in for a real payment-gateway call (e.g. Razorpay retry/refund
    API), which itself dedupes on an idempotency key. INSERT fails if this
    key already executed -> that failure IS the dedup mechanism."""
    with closing(get_db()) as conn:
        try:
            conn.execute(
                "INSERT INTO gateway_ledger (idempotency_key, case_id, action) VALUES (?, ?, ?)",
                (idempotency_key, case_id, action),
            )
            conn.commit()
            return {"status": "EXECUTED", "action": action}
        except sqlite3.IntegrityError:
            return {"status": "ALREADY_EXECUTED_GATEWAY_SIDE", "action": action}


def process_event(idempotency_key, case_id, action, crash_after_gateway_call=False):
    """Core idempotent orchestration loop. Returns a dict describing what
    happened and which path was taken (for audit/demo purposes)."""
    init_db()

    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT status, result FROM case_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()

        if row is not None:
            status, result = row
            if status == "DONE":
                # Fast path: we already know the outcome. No gateway call at all.
                return {"path": "CACHED_NO_OP", "status": status, "result": json.loads(result)}
            if status == "IN_PROGRESS":
                # Crash-recovery path: we don't know if the last attempt's
                # gateway call landed before we died. Re-ask the gateway
                # with the SAME key and let its dedup decide the truth.
                result = simulate_gateway_call(idempotency_key, case_id, action)
                conn.execute(
                    "UPDATE case_events SET status='DONE', result=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE idempotency_key=?",
                    (json.dumps(result), idempotency_key),
                )
                conn.commit()
                return {"path": "RECOVERED_FROM_CRASH", "status": "DONE", "result": result}
        else:
            conn.execute(
                "INSERT INTO case_events (idempotency_key, case_id, action, status) "
                "VALUES (?, ?, ?, 'IN_PROGRESS')",
                (idempotency_key, case_id, action),
            )
            conn.commit()

    # --- Past this point we are "in flight". A real crash can land here. ---
    if crash_after_gateway_call:
        result = simulate_gateway_call(idempotency_key, case_id, action)  # real side effect happens
        sys.stdout.flush()
        os._exit(137)  # hard kill: no except/finally runs, nothing marks DONE

    result = simulate_gateway_call(idempotency_key, case_id, action)
    with closing(get_db()) as conn:
        conn.execute(
            "UPDATE case_events SET status='DONE', result=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE idempotency_key=?",
            (json.dumps(result), idempotency_key),
        )
        conn.commit()
    return {"path": "EXECUTED_FRESH", "status": "DONE", "result": result}


if __name__ == "__main__":
    # CLI form, used by the test harness to spawn a real separate process
    # so the "crash" is an actual process death, not just a Python exception.
    key, case_id, action = sys.argv[1], sys.argv[2], sys.argv[3]
    crash = "--crash" in sys.argv
    out = process_event(key, case_id, action, crash_after_gateway_call=crash)
    print(json.dumps(out))
