"""Conflicting-evidence cases for the context resolver."""

CASES = [
    {
        "id": "H1",
        "description": "Recent desync + weak, unconfirmed duplicate-charge claim.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "PENDING", "webhook_status": "FAILED",
            "time_since_capture_minutes": 10, "customer_claim": "double_charge",
            "duplicate_attempt_status": None, "customer_dispute_history": "prior_dispute_rejected",
        },
        "expected_state_action": "REPLAY_WEBHOOK",
        "expected_financial_action": "DO_NOT_REFUND_VERIFY_FIRST",
    },
    {
        "id": "H2",
        "description": "Desync, but a second capture confirms a real duplicate.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "PENDING", "webhook_status": "FAILED",
            "time_since_capture_minutes": 10, "customer_claim": "double_charge",
            "duplicate_attempt_status": "CAPTURED", "customer_dispute_history": "no_history",
        },
        "expected_state_action": "REPLAY_WEBHOOK",
        "expected_financial_action": "REFUND_DUPLICATE_CONFIRMED",
    },
    {
        "id": "H3",
        "description": "Original gateway call FAILED; later attempt captured. Not a double charge.",
        "case": {
            "gateway_status": "FAILED", "order_status": "PENDING", "webhook_status": "FAILED",
            "time_since_capture_minutes": 15, "customer_claim": "double_charge",
            "duplicate_attempt_status": "CAPTURED", "customer_dispute_history": "no_history",
        },
        "expected_state_action": "NO_STATE_ACTION_NEEDED",
        "expected_financial_action": "NOT_A_DUPLICATE_ONLY_ONE_CHARGE_SUCCEEDED",
    },
    {
        "id": "H4",
        "description": "Clean capture/confirm; unconfirmed claim; weak dispute history.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "CONFIRMED", "webhook_status": "DELIVERED",
            "time_since_capture_minutes": 120, "customer_claim": "double_charge",
            "duplicate_attempt_status": None, "customer_dispute_history": "prior_dispute_rejected",
        },
        "expected_state_action": "NO_STATE_ACTION_NEEDED",
        "expected_financial_action": "DO_NOT_REFUND_VERIFY_FIRST",
    },
    {
        "id": "H5",
        "description": "Order status the resolver does not explicitly name (CANCELLED).",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "CANCELLED", "webhook_status": "DELIVERED",
            "time_since_capture_minutes": 30, "customer_claim": None,
            "duplicate_attempt_status": None, "customer_dispute_history": "no_history",
        },
        "expected_state_action": "ESCALATE_STATE_DESYNC",
        "expected_financial_action": "NO_CLAIM_NO_ACTION",
    },
    {
        "id": "H6",
        "description": "Webhook delivered, order still pending a long time — merchant processing stuck.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "PENDING", "webhook_status": "DELIVERED",
            "time_since_capture_minutes": 200, "customer_claim": "not_received",
            "duplicate_attempt_status": None, "customer_dispute_history": "no_history",
        },
        "expected_state_action": "ESCALATE_MERCHANT_ORDER_PROCESSING_STUCK",
        "expected_financial_action": "HOLD_PENDING_STATE_FIX",
    },
    {
        "id": "H7",
        "description": "Duplicate attempt still PENDING — cannot refund yet.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "PENDING", "webhook_status": "FAILED",
            "time_since_capture_minutes": 5, "customer_claim": "double_charge",
            "duplicate_attempt_status": "PENDING", "customer_dispute_history": "no_history",
        },
        "expected_state_action": "REPLAY_WEBHOOK",
        "expected_financial_action": "HOLD_PENDING_DUPLICATE_RESOLUTION",
    },
    {
        "id": "H8",
        "description": "Unhandled claim type — escalate, do not invent a refund.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "CONFIRMED", "webhook_status": "DELIVERED",
            "time_since_capture_minutes": 60, "customer_claim": "wrong_amount_charged",
            "duplicate_attempt_status": None, "customer_dispute_history": "no_history",
        },
        "expected_state_action": "NO_STATE_ACTION_NEEDED",
        "expected_financial_action": "ESCALATE_UNHANDLED_CLAIM_TYPE",
    },
    {
        "id": "H9",
        "description": "Webhook delivered, order pending only 5 minutes — normal lag, wait.",
        "case": {
            "gateway_status": "CAPTURED", "order_status": "PENDING", "webhook_status": "DELIVERED",
            "time_since_capture_minutes": 5, "customer_claim": None,
            "duplicate_attempt_status": None, "customer_dispute_history": "no_history",
        },
        "expected_state_action": "WAIT_FOR_ORDER_PROCESSING",
        "expected_financial_action": "NO_CLAIM_NO_ACTION",
    },
    {
        "id": "H10",
        "description": "Original charge still PENDING while a later attempt captured — verify, don't refund.",
        "case": {
            "gateway_status": "PENDING", "order_status": "PENDING", "webhook_status": "FAILED",
            "time_since_capture_minutes": 10, "customer_claim": "double_charge",
            "duplicate_attempt_status": "CAPTURED", "customer_dispute_history": "no_history",
        },
        "expected_state_action": "WAIT_FOR_GATEWAY",
        "expected_financial_action": "VERIFY_BEFORE_REFUND",
    },
]
