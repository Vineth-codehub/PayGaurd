"""
Holdout batch of revenue-at-risk cases for Track 03.

Three loss types in one batch (the track's core examples):
  - payment_failure
  - checkout_abandonment
  - subscription_failure

Ground-truth recovery probability is hidden from the agent. The batch
runner uses it only to score rupees recovered — never to pick an action.
"""

import csv
import json
import os
import random

DELAY_BUCKETS = [0, 1, 6, 24]
PAYMENT_METHODS = ["card", "upi", "netbanking", "wallet"]
CUSTOMER_HISTORY = ["responsive", "unresponsive", "unknown"]

SCENARIO_WEIGHTS = {
    "payment_failure": 0.55,
    "checkout_abandonment": 0.25,
    "subscription_failure": 0.20,
}

PAYMENT_REASONS = {
    "BANK_TIMEOUT": 0.18,
    "UPI_TIMEOUT": 0.20,
    "INSUFFICIENT_FUNDS": 0.20,
    "ISSUER_DECLINE": 0.18,
    "PAYMENT_GATEWAY_ERROR": 0.12,
    "UNKNOWN_PAYMENT_FAILURE": 0.12,
}

CHECKOUT_REASONS = {
    "CART_ABANDONED": 0.55,
    "CHECKOUT_TIMEOUT": 0.30,
    "OTP_DROP": 0.15,
}

SUBSCRIPTION_REASONS = {
    "MANDATE_FAILED": 0.35,
    "INSUFFICIENT_FUNDS": 0.35,
    "BANK_TIMEOUT": 0.15,
    "ISSUER_DECLINE": 0.15,
}


def clamp(x, lo=0.02, hi=0.95):
    return max(lo, min(hi, x))


def recovery_probability(case, delay_hours=None):
    """Hidden ground truth. delay_hours overrides the case field when the
    agent chose a different wait than the one sitting on the record."""
    delay = DELAY_BUCKETS[0] if delay_hours is None else delay_hours
    if delay not in DELAY_BUCKETS:
        delay = min(DELAY_BUCKETS, key=lambda d: abs(d - delay))

    reason = case.get("failure_reason", "UNKNOWN_PAYMENT_FAILURE")
    scenario = case.get("scenario", "payment_failure")
    history = case.get("customer_history") or "unknown"
    attempts = case.get("attempt_count") or 0
    try:
        attempts = max(0, int(attempts))
    except (TypeError, ValueError):
        attempts = 0
    amount = case.get("amount") or 0
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0

    if reason not in (
        "BANK_TIMEOUT", "UPI_TIMEOUT", "INSUFFICIENT_FUNDS", "ISSUER_DECLINE",
        "PAYMENT_GATEWAY_ERROR", "UNKNOWN_PAYMENT_FAILURE", "CART_ABANDONED",
        "CHECKOUT_TIMEOUT", "OTP_DROP", "MANDATE_FAILED",
    ):
        reason = "UNKNOWN_PAYMENT_FAILURE"

    base = {
        "BANK_TIMEOUT": 0.55,
        "UPI_TIMEOUT": 0.50,
        "INSUFFICIENT_FUNDS": 0.30,
        "ISSUER_DECLINE": 0.22,
        "PAYMENT_GATEWAY_ERROR": 0.45,
        "UNKNOWN_PAYMENT_FAILURE": 0.28,
        "CART_ABANDONED": 0.32,
        "CHECKOUT_TIMEOUT": 0.40,
        "OTP_DROP": 0.38,
        "MANDATE_FAILED": 0.42,
    }[reason]

    p = base
    p -= 0.10 * min(attempts, 3)

    if reason in ("BANK_TIMEOUT", "UPI_TIMEOUT", "MANDATE_FAILED", "CHECKOUT_TIMEOUT"):
        p += {0: 0.0, 1: 0.05, 6: 0.10, 24: -0.05}[delay]
    if reason == "INSUFFICIENT_FUNDS":
        p += {0: 0.0, 1: 0.02, 6: 0.05, 24: 0.15}[delay]
    if reason in ("CART_ABANDONED", "OTP_DROP"):
        p += {0: 0.08, 1: 0.12, 6: 0.06, 24: -0.04}[delay]

    if history == "responsive":
        p += 0.08
    elif history == "unresponsive":
        p -= 0.12
    else:
        p -= 0.03

    if amount > 50000 and scenario != "checkout_abandonment":
        p += 0.06  # B2B chase effect on this holdout world

    if scenario == "checkout_abandonment" and history == "unresponsive":
        p -= 0.08

    return clamp(p)


def _pick(rng, weights):
    keys = list(weights.keys())
    return rng.choices(keys, weights=list(weights.values()), k=1)[0]


def generate_holdout(n=200, seed=202):
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        scenario = _pick(rng, SCENARIO_WEIGHTS)
        if scenario == "checkout_abandonment":
            reason = _pick(rng, CHECKOUT_REASONS)
        elif scenario == "subscription_failure":
            reason = _pick(rng, SUBSCRIPTION_REASONS)
        else:
            reason = _pick(rng, PAYMENT_REASONS)
        case = {
            "case_id": f"B-{i:04d}",
            "scenario": scenario,
            "amount": round(rng.lognormvariate(8.9, 1.0), 2),
            "failure_reason": reason,
            "attempt_count": rng.choices([0, 1, 2], weights=[0.45, 0.35, 0.20])[0],
            "delay_hours": rng.choice(DELAY_BUCKETS),
            "customer_history": rng.choices(CUSTOMER_HISTORY, weights=[0.40, 0.35, 0.25])[0],
            "payment_method": rng.choice(PAYMENT_METHODS),
            "contacts_already": rng.choices([0, 1, 2], weights=[0.60, 0.30, 0.10])[0],
        }
        cases.append(case)
    return cases


def save_cases(cases, json_path, csv_path):
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2)
    keys = list(cases[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(cases)


if __name__ == "__main__":
    batch = generate_holdout()
    save_cases(batch, "data/holdout.json", "data/holdout.csv")
    at_risk = sum(c["amount"] for c in batch)
    print(f"Holdout: {len(batch)} cases, INR {at_risk:,.0f} at risk")
