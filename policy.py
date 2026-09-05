"""
Policy gate: AUTO / APPROVAL_REQUIRED / BLOCKED.

Every money-moving or customer-facing action is bounded before the
executor runs. Stopping rules are explicit so the agent cannot chase
forever.
"""

POLICY = {
    "retry": {"max_attempts": 2, "max_amount": 50000},
    "customer_contact": {"max_contacts": 2},
    "refund": {"requires_approval": True},
    "escalate": {"always_human": True},
}


def evaluate_policy(action, case):
    """Returns (verdict, reason). verdict in {AUTO, APPROVAL_REQUIRED, BLOCKED}."""
    amount = case.get("amount", 0) or 0
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    attempt_count = case.get("attempt_count", 0) or 0
    try:
        attempt_count = int(attempt_count)
    except (TypeError, ValueError):
        attempt_count = 0
    contacts = case.get("contacts_already", 0) or 0
    try:
        contacts = int(contacts)
    except (TypeError, ValueError):
        contacts = 0
    history = case.get("customer_history") or "unknown"

    if action in ("DO_NOTHING", "NO_CLAIM_NO_ACTION", "NO_STATE_ACTION_NEEDED", "STOP_CONTACT"):
        if action == "STOP_CONTACT":
            return "BLOCKED", "stopping rule: do not contact this customer again"
        return "AUTO", "no-op, nothing to gate"

    if action.startswith("RETRY_AFTER"):
        if attempt_count >= POLICY["retry"]["max_attempts"]:
            return "BLOCKED", (
                f"stopping rule: attempt_count {attempt_count} >= "
                f"max {POLICY['retry']['max_attempts']}"
            )
        if amount > POLICY["retry"]["max_amount"]:
            return "APPROVAL_REQUIRED", (
                f"amount {amount} exceeds auto-retry ceiling "
                f"{POLICY['retry']['max_amount']}"
            )
        return "AUTO", "within retry policy"

    if action in ("SEND_CHECKOUT_REMINDER", "REQUEST_METHOD_UPDATE"):
        if contacts >= POLICY["customer_contact"]["max_contacts"]:
            return "BLOCKED", (
                f"stopping rule: contacts_already {contacts} >= "
                f"max {POLICY['customer_contact']['max_contacts']}"
            )
        if history == "unresponsive" and contacts >= 1:
            return "BLOCKED", "stopping rule: unresponsive customer, no further outreach"
        return "AUTO", "low-risk customer-facing request, no money moved"

    if action == "ESCALATE" or action.startswith("ESCALATE"):
        return "APPROVAL_REQUIRED", "escalation always routes to a human by design"

    if action.startswith("REFUND"):
        return "APPROVAL_REQUIRED", "refunds always require approval per policy"

    if action in (
        "REPLAY_WEBHOOK", "WAIT_FOR_WEBHOOK", "WAIT_FOR_GATEWAY",
        "WAIT_FOR_ORDER_PROCESSING", "VERIFY_BEFORE_REFUND",
        "HOLD_PENDING_DUPLICATE_RESOLUTION", "HOLD_PENDING_STATE_FIX",
        "NOT_A_DUPLICATE_ONLY_ONE_CHARGE_SUCCEEDED",
        "DO_NOT_REFUND_VERIFY_FIRST",
    ):
        return "AUTO", "state/verify action, no money moved"

    return "APPROVAL_REQUIRED", f"unrecognized action '{action}' -- default to human review"
