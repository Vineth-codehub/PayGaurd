# PayGuard — Agentic Revenue Recovery

**Track 03: AI Revenue Recovery**

An agent that finds revenue slipping away and wins it back under policy: detect → reconstruct context → choose an intervention → execute only what is allowed → verify → measure rupees recovered on a batch.

It is not Track 01 (growth / AI-buyer checkout), Track 02 (fraud detector), or Track 04 (books close).

## The loop

1. **Detect** revenue at risk: failed payment, checkout abandonment, or failed subscription.
2. **Reconstruct** gateway / order / webhook evidence when it conflicts (and refuse to refund a “duplicate” that is not actually two captures).
3. **Choose** a recovery action (retry delay, method update, reminder, escalate, or stop).
4. **Gate** with policy: `AUTO` / `APPROVAL_REQUIRED` / `BLOCKED`. Stopping rules cap retries, amount, and customer contacts.
5. **Execute** AUTO actions once. Duplicate webhooks and crash-restart cannot double-run at the gateway.
6. **Measure** ₹ recovered on a 200-case holdout vs do-nothing and naive retry-all, with an audit trail.

## Live dashboard

```
py -3 dashboard.py
```

Opens `http://127.0.0.1:8765`. Click **Live run · 80** to stream the real decide → gate → execute loop. **Full batch · 200** is the Track 03 scoreboard. **Evidence cases** runs the 10 conflicting-context checks. **Fire this webhook 5×** proves idempotency on the case on screen.

CLI proof (no UI):

```
py -3 run_demo.py
```

Or one piece at a time:

```
python test_idempotency.py
python run_hard_cases.py
python test_pipeline.py
python run_batch.py
```

Batch output is written to `data/audit_trail.json` (every case: action, verdict, reason, executed, recovered amount).

## Layout

| File | Role |
|---|---|
| `cases.py` | Holdout generator (3 loss types) |
| `decide.py` | Intervention chooser + recovery prior |
| `resolver.py` | Conflicting payment-context reconstruction |
| `policy.py` | Escalation, amount caps, stopping rules |
| `pipeline.py` | detect → gate → execute |
| `payguard_idempotency.py` | One real side effect per idempotency key |
| `run_batch.py` | Track 03 scoreboard: ₹ recovered across 200 cases |
| `hard_cases.py` | 10 conflicting-evidence cases |
| `dashboard.py` | Live demo UI at http://127.0.0.1:8765 |
| `web/index.html` | Dashboard front-end |

No third-party packages. Python 3.10+ is enough.

## Policy (stopping and escalation)

- Auto-retry only if `attempt_count < 2` and `amount ≤ 50,000`.
- Refunds and escalations always need a human.
- Customer outreach stops after 2 contacts, or after 1 contact if the customer is already unresponsive.
- Unrecognized actions default to human review, not auto-execute.

## Honest limits

- Outcomes on the batch are simulated from a hidden recovery model, not live Razorpay settlements.
- The gateway in `payguard_idempotency.py` is a ledger stand-in; the same idempotency key is what you would send to a real retry API.
- Intervention choice is rule-based (domain priors), not a live LLM. The bar here is closed-loop recovery with measured money and an audit trail, not a chatbot.
