"""
Live demo dashboard for Track 03.

Serves the ops console and streams the same decide -> gate -> execute
loop used by run_batch.py. No extra packages.

    py -3 dashboard.py
    open http://127.0.0.1:8765
"""

import json
import os
import random
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from cases import generate_holdout
from hard_cases import CASES as HARD_CASES
from payguard_idempotency import get_db, DB_PATH
from pipeline import handle_case
from resolver import resolve_evidence
from run_batch import (
    build_row,
    friction_of,
    reset_db,
    scenario_breakout,
    simulate_recovery,
    summarize,
    verdict_mix,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
HOST = "127.0.0.1"
PORT = 8765


class DemoState:
    def __init__(self):
        self.lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.running = False
        self.done = False
        self.error = None
        self.delay_ms = 90
        self.cases = []
        self.case_by_id = {}
        self.rows = []
        self.naive_rows = []
        self.cursor = 0
        self.pg_rng = random.Random(7)
        self.naive_rng = random.Random(7)
        self.seq = 0

    def snapshot(self):
        with self.lock:
            rows = list(self.rows)
            naive = list(self.naive_rows)
            cases = list(self.cases)
            processed = cases[: len(rows)]
            at_risk_all = sum(float(c.get("amount") or 0) for c in cases)
            scoreboard = []
            if processed:
                nothing = [{
                    "case_id": c["case_id"],
                    "policy_verdict": "AUTO",
                    "executed": False,
                    "recovered_amount": 0.0,
                    "friction": 0.0,
                } for c in processed]
                scoreboard = [
                    summarize("do_nothing", processed, nothing),
                    summarize("naive_retry_all", processed, naive),
                    summarize("payguard", processed, rows),
                ]
            latest = rows[-1] if rows else None
            return {
                "running": self.running,
                "done": self.done,
                "error": self.error,
                "seq": self.seq,
                "total": len(cases),
                "processed": len(rows),
                "amount_at_risk_batch": round(at_risk_all, 2),
                "verdict_mix": verdict_mix(rows) if rows else {},
                "by_scenario": scenario_breakout(processed, rows) if rows else {},
                "scoreboard": scoreboard,
                "latest": latest,
                "rows": list(reversed(rows[-80:])),
                "stopping_rules": {
                    "max_auto_retry_attempts": 2,
                    "max_auto_retry_amount": 50000,
                    "max_customer_contacts": 2,
                    "unresponsive_stop_after": 1,
                },
            }

    def start(self, n=80, delay_ms=90):
        with self.lock:
            if self.running:
                return False
            reset_db()
            self._reset()
            n = max(10, min(int(n), 200))
            self.delay_ms = max(0, min(int(delay_ms), 2000))
            self.cases = generate_holdout(n=200, seed=202)[:n]
            self.case_by_id = {c["case_id"]: c for c in self.cases}
            self.running = True
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()
        return True

    def _run_loop(self):
        try:
            while True:
                with self.lock:
                    if not self.running or self.cursor >= len(self.cases):
                        self.running = False
                        self.done = self.cursor >= len(self.cases) and len(self.cases) > 0
                        self.seq += 1
                        break
                    case = self.cases[self.cursor]
                    self.cursor += 1
                    pg_rng = self.pg_rng
                    naive_rng = self.naive_rng
                row = build_row(case, pg_rng)
                naive_recovered, naive_inr = simulate_recovery(
                    case, "RETRY_AFTER(6h)", True, naive_rng
                )
                naive_row = {
                    "case_id": case["case_id"],
                    "decided_action": "RETRY_AFTER(6h)",
                    "policy_verdict": "BYPASS",
                    "executed": True,
                    "recovered": naive_recovered,
                    "recovered_amount": round(naive_inr, 2),
                    "friction": friction_of("RETRY_AFTER(6h)", True),
                }
                with self.lock:
                    self.rows.append(row)
                    self.naive_rows.append(naive_row)
                    self.seq += 1
                    delay = self.delay_ms / 1000.0
                if delay:
                    time.sleep(delay)
        except Exception as exc:
            with self.lock:
                self.running = False
                self.error = str(exc)
                self.seq += 1

    def stop(self):
        with self.lock:
            self.running = False
            self.seq += 1

    def duplicate_fire(self, case_id, times=5):
        with self.lock:
            case = self.case_by_id.get(case_id)
        if not case:
            return {"error": "unknown case_id"}
        paths = []
        key = None
        for _ in range(times):
            r = handle_case(case)
            key = r["idempotency_key"]
            path = None
            if r.get("execution_result"):
                path = r["execution_result"].get("path")
            paths.append({
                "executed": r["executed"],
                "verdict": r["policy_verdict"],
                "path": path,
            })
        gw = 0
        try:
            from contextlib import closing
            with closing(get_db()) as conn:
                gw = conn.execute(
                    "SELECT COUNT(*) FROM gateway_ledger WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()[0]
        except Exception:
            gw = 0
        return {"case_id": case_id, "calls": paths, "gateway_executions": gw}


STATE = DemoState()


def json_bytes(obj, code=200):
    body = json.dumps(obj, default=str).encode("utf-8")
    return code, "application/json; charset=utf-8", body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} {fmt % args}")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            html_path = os.path.join(WEB, "index.html")
            with open(html_path, "rb") as f:
                self._send(200, "text/html; charset=utf-8", f.read())
            return
        if path == "/api/state":
            self._send(*json_bytes(STATE.snapshot()))
            return
        if path == "/api/hard-cases":
            out = []
            for spec in HARD_CASES:
                result = resolve_evidence(spec["case"])
                out.append({
                    "id": spec["id"],
                    "description": spec["description"],
                    "expected_state": spec["expected_state_action"],
                    "expected_financial": spec["expected_financial_action"],
                    "actual": result,
                    "match": (
                        result["state_action"] == spec["expected_state_action"]
                        and result["financial_action"] == spec["expected_financial_action"]
                    ),
                })
            self._send(*json_bytes({"cases": out, "passed": all(c["match"] for c in out)}))
            return
        self._send(*json_bytes({"error": "not found"}, 404))

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/start":
            n = payload.get("n") or qs.get("n", [80])[0]
            delay = payload.get("delay_ms") or qs.get("delay_ms", [90])[0]
            started = STATE.start(n=int(n), delay_ms=int(delay))
            self._send(*json_bytes({"ok": True, "started": started}))
            return
        if parsed.path == "/api/stop":
            STATE.stop()
            self._send(*json_bytes({"ok": True}))
            return
        if parsed.path == "/api/duplicate":
            case_id = payload.get("case_id")
            self._send(*json_bytes(STATE.duplicate_fire(case_id)))
            return
        self._send(*json_bytes({"error": "not found"}, 404))


def main():
    os.makedirs(WEB, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"PayGuard live dashboard -> {url}", flush=True)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
