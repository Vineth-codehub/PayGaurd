"""
Track 03 bar: measured money recovered across a holdout batch.

Compares three strategies on the SAME cases, same random seed:
  - do nothing
  - naive retry-everything (no policy, no stopping rules)
  - PayGuard (decide -> gate -> idempotent execute)

Writes data/audit_trail.json with every case's action, verdict, and outcome.
"""

import json
import os
import random

from cases import generate_holdout, recovery_probability, save_cases
from decide import parse_retry_hours
from pipeline import handle_case
from payguard_idempotency import DB_PATH


FRICTION = {
    "SEND_CHECKOUT_REMINDER": 1.0,
    "REQUEST_METHOD_UPDATE": 1.0,
    "RETRY": 0.5,
}


def reset_db():
    import time
    for _ in range(8):
        try:
            for suffix in ("", "-wal", "-shm"):
                p = DB_PATH + suffix
                if os.path.exists(p):
                    os.remove(p)
            return
        except OSError:
            time.sleep(0.05)
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)


def delay_for(action):
    hours = parse_retry_hours(action)
    if hours is not None:
        return hours
    if action in ("SEND_CHECKOUT_REMINDER", "REQUEST_METHOD_UPDATE"):
        return 1
    return 0


def is_recovery_action(action):
    if not action:
        return False
    if action.startswith("RETRY_AFTER"):
        return True
    return action in ("SEND_CHECKOUT_REMINDER", "REQUEST_METHOD_UPDATE")


def friction_of(action, executed):
    if not executed:
        return 0.0
    if action.startswith("RETRY_AFTER"):
        return FRICTION["RETRY"]
    return FRICTION.get(action, 0.0)


def simulate_recovery(case, action, executed, rng):
    if not executed or not is_recovery_action(action):
        return False, 0.0
    p = recovery_probability(case, delay_hours=delay_for(action))
    recovered = rng.random() < p
    amount = float(case.get("amount") or 0)
    return recovered, amount if recovered else 0.0


def build_row(case, rng):
    r = handle_case(case)
    recovered, rupees = simulate_recovery(
        case, r["decided_action"], r["executed"], rng
    )
    row = dict(r)
    row["recovered"] = recovered
    row["recovered_amount"] = round(rupees, 2)
    row["friction"] = friction_of(r["decided_action"], r["executed"])
    row["p_recovery_if_executed"] = round(
        recovery_probability(case, delay_hours=delay_for(r["decided_action"])), 3
    ) if is_recovery_action(r["decided_action"]) else None
    rec = row.pop("reconstruction", None)
    if rec:
        row["state_action"] = rec["state_action"]
        row["financial_action"] = rec["financial_action"]
        row["resolver_flags"] = rec["flags"]
    if row.get("execution_result"):
        row["execution_path"] = row["execution_result"].get("path")
    row.pop("execution_result", None)
    row["customer_history"] = case.get("customer_history")
    row["attempt_count"] = case.get("attempt_count")
    row["contacts_already"] = case.get("contacts_already")
    return row


def run_payguard(cases, rng):
    return [build_row(case, rng) for case in cases]


def run_naive_retry_all(cases, rng):
    """Always retry after 6h, no amount cap, no attempt cap, no human gate."""
    rows = []
    for case in cases:
        action = "RETRY_AFTER(6h)"
        recovered, rupees = simulate_recovery(case, action, True, rng)
        rows.append({
            "case_id": case["case_id"],
            "decided_action": action,
            "policy_verdict": "BYPASS",
            "executed": True,
            "recovered": recovered,
            "recovered_amount": round(rupees, 2),
            "friction": FRICTION["RETRY"],
        })
    return rows


def summarize(name, cases, rows):
    at_risk = sum(float(c.get("amount") or 0) for c in cases)
    recovered = sum(r["recovered_amount"] for r in rows)
    friction = sum(r["friction"] for r in rows)
    auto = sum(1 for r in rows if r.get("policy_verdict") == "AUTO" and r.get("executed"))
    gated = sum(1 for r in rows if r.get("policy_verdict") == "APPROVAL_REQUIRED")
    stopped = sum(1 for r in rows if r.get("policy_verdict") == "BLOCKED")
    return {
        "strategy": name,
        "n": len(cases),
        "amount_at_risk": round(at_risk, 2),
        "amount_recovered": round(recovered, 2),
        "recovery_rate_inr": round(recovered / at_risk, 4) if at_risk else 0,
        "customer_friction_units": round(friction, 2),
        "inr_per_friction": round(recovered / friction, 2) if friction else None,
        "auto_executed": auto,
        "approval_required": gated,
        "stopped": stopped,
    }


def verdict_mix(rows):
    mix = {}
    for r in rows:
        v = r.get("policy_verdict", "UNKNOWN")
        mix[v] = mix.get(v, 0) + 1
    return mix


def scenario_breakout(cases, rows):
    by = {}
    case_map = {c["case_id"]: c for c in cases}
    for r in rows:
        sc = case_map[r["case_id"]].get("scenario", "payment_failure")
        bucket = by.setdefault(sc, {"n": 0, "at_risk": 0.0, "recovered": 0.0})
        bucket["n"] += 1
        bucket["at_risk"] += float(case_map[r["case_id"]].get("amount") or 0)
        bucket["recovered"] += r["recovered_amount"]
    for sc, b in by.items():
        b["at_risk"] = round(b["at_risk"], 2)
        b["recovered"] = round(b["recovered"], 2)
    return by


def main():
    os.makedirs("data", exist_ok=True)
    reset_db()
    cases = generate_holdout(n=200, seed=202)
    save_cases(cases, "data/holdout.json", "data/holdout.csv")

    pg = run_payguard(cases, random.Random(7))
    naive = run_naive_retry_all(cases, random.Random(7))
    nothing = [{
        "case_id": c["case_id"],
        "decided_action": "DO_NOTHING",
        "policy_verdict": "AUTO",
        "executed": False,
        "recovered": False,
        "recovered_amount": 0.0,
        "friction": 0.0,
    } for c in cases]

    scoreboard = [
        summarize("do_nothing", cases, nothing),
        summarize("naive_retry_all", cases, naive),
        summarize("payguard", cases, pg),
    ]

    report = {
        "track": "03_AI_Revenue_Recovery",
        "scoreboard": scoreboard,
        "payguard_verdict_mix": verdict_mix(pg),
        "payguard_by_scenario": scenario_breakout(cases, pg),
        "stopping_rules": {
            "max_auto_retry_attempts": 2,
            "max_auto_retry_amount": 50000,
            "max_customer_contacts": 2,
            "unresponsive_no_further_outreach_after": 1,
            "refunds_and_escalations": "APPROVAL_REQUIRED",
        },
        "audit_cases": pg,
    }

    with open("data/audit_trail.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 72)
    print("TRACK 03 - batch revenue recovery (n=200 holdout)")
    print("=" * 72)
    print(f"{'strategy':22s}  {'at risk':>12s}  {'recovered':>12s}  {'rate':>8s}  friction")
    for s in scoreboard:
        print(
            f"{s['strategy']:22s}  INR {s['amount_at_risk']:>10,.0f}  "
            f"INR {s['amount_recovered']:>10,.0f}  {100 * s['recovery_rate_inr']:6.1f}%  "
            f"{s['customer_friction_units']:.1f}"
        )
    pg_s = scoreboard[2]
    print()
    print(f"PayGuard verdict mix: {verdict_mix(pg)}")
    print(f"Auto-executed: {pg_s['auto_executed']}  "
          f"human-gated: {pg_s['approval_required']}  "
          f"stopped: {pg_s['stopped']}")
    print("By scenario:")
    for sc, b in scenario_breakout(cases, pg).items():
        print(f"  {sc:24s}  n={b['n']:3d}  at risk INR {b['at_risk']:,.0f}  "
              f"recovered INR {b['recovered']:,.0f}")
    print()
    print("Audit trail: data/audit_trail.json")
    print("Idempotency: AUTO retries still go through payguard_idempotency.py")


if __name__ == "__main__":
    main()
