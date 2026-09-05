"""
Intervention chooser for revenue at risk.

Picks the recovery action. Policy still has to approve it before any
money or customer-facing step runs. Recovery probability is estimated
separately so we can compare interventions without executing them all.
"""

KNOWN_REASONS = {
    "BANK_TIMEOUT", "UPI_TIMEOUT", "INSUFFICIENT_FUNDS",
    "ISSUER_DECLINE", "PAYMENT_GATEWAY_ERROR", "UNKNOWN_PAYMENT_FAILURE",
    "CART_ABANDONED", "CHECKOUT_TIMEOUT", "OTP_DROP", "MANDATE_FAILED",
}
KNOWN_HISTORY = {"responsive", "unresponsive", "unknown"}
MAX_REASONABLE_DELAY = 48


def clamp(x, lo=0.03, hi=0.90):
    return max(lo, min(hi, x))


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def predict_recovery(case, delay_hours=None):
    """Domain-prior P(recover | retry after delay). Amount is not used as
    a probability signal (it is a policy/approval signal instead)."""
    flags = []
    reason = case.get("failure_reason")
    if reason not in KNOWN_REASONS:
        flags.append("UNKNOWN_REASON_FALLBACK")
        reason = "UNKNOWN_PAYMENT_FAILURE"

    attempt_count = case.get("attempt_count", 0)
    if not isinstance(attempt_count, (int, float)) or attempt_count < 0:
        flags.append("INVALID_ATTEMPT_COUNT_DEFAULTED")
        attempt_count = 0
    if attempt_count > 5:
        flags.append("ATTEMPT_COUNT_BEYOND_NORMAL_RANGE")

    delay = case.get("delay_hours", 0) if delay_hours is None else delay_hours
    if not isinstance(delay, (int, float)) or delay < 0:
        flags.append("INVALID_DELAY_DEFAULTED")
        delay = 0
    if delay > MAX_REASONABLE_DELAY:
        flags.append("DELAY_BEYOND_KNOWN_RANGE_CLAMPED")
        delay = MAX_REASONABLE_DELAY

    history = case.get("customer_history")
    if history not in KNOWN_HISTORY:
        flags.append("MISSING_FIELD_DEFAULTED(customer_history->unknown)")
        history = "unknown"

    base = {
        "BANK_TIMEOUT": 0.55,
        "UPI_TIMEOUT": 0.50,
        "PAYMENT_GATEWAY_ERROR": 0.45,
        "INSUFFICIENT_FUNDS": 0.35,
        "ISSUER_DECLINE": 0.25,
        "UNKNOWN_PAYMENT_FAILURE": 0.25,
        "CART_ABANDONED": 0.30,
        "CHECKOUT_TIMEOUT": 0.40,
        "OTP_DROP": 0.36,
        "MANDATE_FAILED": 0.40,
    }[reason]

    p = base - 0.10 * min(attempt_count, 3)

    if reason in ("BANK_TIMEOUT", "UPI_TIMEOUT", "MANDATE_FAILED", "CHECKOUT_TIMEOUT"):
        if delay <= 0:
            p += 0.0
        elif delay <= 1:
            p += 0.04
        elif delay <= 6:
            p += 0.12
        else:
            p += 0.03
    if reason == "INSUFFICIENT_FUNDS":
        if delay >= 24:
            p += 0.15
        elif delay >= 6:
            p += 0.05
    if reason in ("CART_ABANDONED", "OTP_DROP"):
        if delay <= 1:
            p += 0.10
        elif delay <= 6:
            p += 0.04

    if history == "responsive":
        p += 0.08
    elif history == "unresponsive":
        p -= 0.10

    return clamp(p), flags


def parse_retry_hours(action):
    if not action or not action.startswith("RETRY_AFTER("):
        return None
    inner = action[len("RETRY_AFTER("):].rstrip(")")
    try:
        return int(inner.replace("h", ""))
    except ValueError:
        return None


def decide_action(case):
    """Choose one recovery intervention. Does not execute anything."""
    scenario = case.get("scenario", "payment_failure")
    reason = case.get("failure_reason", "UNKNOWN_PAYMENT_FAILURE")
    attempt_count = _int(case.get("attempt_count", 0))
    contacts = _int(case.get("contacts_already", 0))
    history = case.get("customer_history") or "unknown"

    # Stopping rule lives in policy too; chooser should not keep proposing
    # retries after the attempt cap.
    if attempt_count >= 2:
        return "ESCALATE"

    if scenario == "checkout_abandonment":
        if history == "unresponsive" and contacts >= 1:
            return "STOP_CONTACT"
        if reason == "OTP_DROP":
            return "RETRY_AFTER(1h)"
        return "SEND_CHECKOUT_REMINDER"

    if scenario == "subscription_failure":
        if reason == "INSUFFICIENT_FUNDS":
            return "RETRY_AFTER(24h)"
        if reason == "ISSUER_DECLINE":
            return "REQUEST_METHOD_UPDATE"
        if reason in ("MANDATE_FAILED", "BANK_TIMEOUT"):
            delay = [1, 6][min(attempt_count, 1)]
            return f"RETRY_AFTER({delay}h)"
        return "ESCALATE"

    # payment_failure
    if reason in ("BANK_TIMEOUT", "UPI_TIMEOUT"):
        delay = [1, 6, 6][min(attempt_count, 2)]
        return f"RETRY_AFTER({delay}h)"
    if reason == "INSUFFICIENT_FUNDS":
        return "RETRY_AFTER(24h)"
    if reason == "ISSUER_DECLINE":
        return "REQUEST_METHOD_UPDATE"
    if reason == "PAYMENT_GATEWAY_ERROR":
        return "RETRY_AFTER(1h)"
    return "ESCALATE"


def counterfactual_actions(case):
    """Candidate interventions for the same case (never executed in bulk)."""
    reason = case.get("failure_reason", "")
    scenario = case.get("scenario", "payment_failure")
    options = ["DO_NOTHING"]
    if scenario == "checkout_abandonment":
        options += ["SEND_CHECKOUT_REMINDER", "RETRY_AFTER(1h)", "STOP_CONTACT"]
    elif scenario == "subscription_failure":
        options += ["RETRY_AFTER(1h)", "RETRY_AFTER(6h)", "RETRY_AFTER(24h)", "REQUEST_METHOD_UPDATE"]
    else:
        options += ["RETRY_AFTER(1h)", "RETRY_AFTER(6h)", "RETRY_AFTER(24h)", "REQUEST_METHOD_UPDATE"]
    if reason == "ISSUER_DECLINE" and "REQUEST_METHOD_UPDATE" not in options:
        options.append("REQUEST_METHOD_UPDATE")
    chosen = decide_action(case)
    if chosen not in options:
        options.append(chosen)
    return options
