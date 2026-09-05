"""
Track 03 loop: reconstruct (if evidence exists) -> decide intervention ->
policy gate -> execute only AUTO actions, once.

Gated actions never touch the gateway. Duplicate events share an
idempotency key so retries cannot double-charge.
"""

import hashlib
from decide import decide_action
from policy import evaluate_policy
from resolver import resolve_evidence
from payguard_idempotency import process_event


def idempotency_key_for(case, action):
    raw = f"{case['case_id']}:{action}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def propose_action(case):
    reconstruction = None
    if case.get("gateway_status"):
        reconstruction = resolve_evidence(case)
        financial = reconstruction["financial_action"]
        state = reconstruction["state_action"]
        if financial.startswith("REFUND"):
            action = financial
        elif financial.startswith("ESCALATE"):
            action = financial
        elif state not in ("NO_STATE_ACTION_NEEDED",):
            action = state
        else:
            action = decide_action(case)
    else:
        action = decide_action(case)
    return action, reconstruction


def handle_case(case):
    action, reconstruction = propose_action(case)
    verdict, reason = evaluate_policy(action, case)

    result = {
        "case_id": case["case_id"],
        "scenario": case.get("scenario", "payment_failure"),
        "amount_at_risk": case.get("amount", 0),
        "failure_reason": case.get("failure_reason"),
        "decided_action": action,
        "policy_verdict": verdict,
        "policy_reason": reason,
        "reconstruction": reconstruction,
        "executed": False,
        "execution_result": None,
        "idempotency_key": idempotency_key_for(case, action),
    }

    if verdict != "AUTO":
        return result

    if action in ("DO_NOTHING", "NO_CLAIM_NO_ACTION", "NO_STATE_ACTION_NEEDED"):
        result["execution_result"] = {"path": "NO_OP", "status": "DONE", "result": None}
        return result

    exec_out = process_event(result["idempotency_key"], case["case_id"], action)
    result["executed"] = True
    result["execution_result"] = exec_out
    return result
