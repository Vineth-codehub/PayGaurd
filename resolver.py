"""
Reconstruct payment/order/webhook context before any recovery money moves.

Conflicting evidence is resolved into a state action and a financial
action. Refunds are never auto-fired from here — policy still gates them.
"""


def resolve_evidence(case):
    """Returns {"state_action": str, "financial_action": str, "flags": [...]}."""
    flags = []
    gw = case.get("gateway_status")
    order = case.get("order_status")
    webhook = case.get("webhook_status")
    time_since_capture = case.get("time_since_capture_minutes", 9999)
    duplicate_attempt = case.get("duplicate_attempt_status")
    customer_claim = case.get("customer_claim")
    history = case.get("customer_dispute_history", "no_history")

    if gw == "CAPTURED" and order == "PENDING":
        if webhook == "FAILED" and time_since_capture < 30:
            state_action = "REPLAY_WEBHOOK"
        elif webhook == "FAILED":
            state_action = "ESCALATE_STATE_DESYNC"
        elif webhook == "DELAYED":
            state_action = "WAIT_FOR_WEBHOOK"
        elif webhook == "DELIVERED":
            if time_since_capture < 15:
                state_action = "WAIT_FOR_ORDER_PROCESSING"
                flags.append("webhook_delivered_order_pending_recent_likely_normal_lag")
            else:
                state_action = "ESCALATE_MERCHANT_ORDER_PROCESSING_STUCK"
                flags.append("webhook_delivered_but_order_still_pending_likely_merchant_side_fault")
        else:
            state_action = "ESCALATE_STATE_DESYNC"
            flags.append("captured_pending_webhook_status_unclear")
    elif gw == "CAPTURED" and order == "CONFIRMED":
        state_action = "NO_STATE_ACTION_NEEDED"
    elif gw == "FAILED":
        state_action = "NO_STATE_ACTION_NEEDED"
    elif gw == "PENDING":
        state_action = "WAIT_FOR_GATEWAY"
    else:
        state_action = "ESCALATE_STATE_DESYNC"
        flags.append("unrecognized_gateway_order_combo")

    if customer_claim == "double_charge":
        if duplicate_attempt == "CAPTURED":
            if gw == "CAPTURED":
                financial_action = "REFUND_DUPLICATE_CONFIRMED"
            elif gw == "FAILED":
                financial_action = "NOT_A_DUPLICATE_ONLY_ONE_CHARGE_SUCCEEDED"
                flags.append("original_charge_failed_no_duplicate_exists")
            else:
                financial_action = "VERIFY_BEFORE_REFUND"
                flags.append("original_charge_status_not_yet_resolved_cannot_confirm_duplicate")
        elif duplicate_attempt == "PENDING":
            financial_action = "HOLD_PENDING_DUPLICATE_RESOLUTION"
            flags.append("duplicate_attempt_still_pending_ambiguous")
        elif history == "prior_dispute_rejected":
            financial_action = "DO_NOT_REFUND_VERIFY_FIRST"
            flags.append("weak_claim_credibility_no_independent_confirmation")
        else:
            financial_action = "VERIFY_BEFORE_REFUND"
    elif customer_claim == "not_received" and gw == "CAPTURED" and order != "CONFIRMED":
        financial_action = "HOLD_PENDING_STATE_FIX"
    elif customer_claim is None:
        financial_action = "NO_CLAIM_NO_ACTION"
    else:
        financial_action = "ESCALATE_UNHANDLED_CLAIM_TYPE"
        flags.append("claim_type_not_explicitly_handled")

    return {"state_action": state_action, "financial_action": financial_action, "flags": flags}
