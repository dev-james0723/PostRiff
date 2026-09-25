# FINAL billing matrix — 2026-09-24

Scope: credits (FINAL-05), one-time top-ups (FINAL-06) and monthly subscription credits (FINAL-07) in the
candidate. Policy `credits-candidate-2026-09-23-v1`: 300 credits per US$1 of provider or paid-tool cost, a task
rounded up to 0.1 credit, stored as millicredits and micro-USD. **This is a candidate policy, not an approved
price.** Credits and credit purchases stay off unless `POSTRIFF_CREDITS_ENABLED=1` / `POSTRIFF_CREDIT_PURCHASES_ENABLED=1`
and plan terms carrying the policy are active; migrations 020–022 are not applied anywhere but disposable
PostgreSQL. Every row below was verified with synthetic signed events or synthetic providers only: no Stripe
account was touched and no money moved.

## Credits for a task

| Step | Behaviour | Evidence (disposable PostgreSQL unless noted) | Status |
|---|---|---|---|
| Estimate | Before approval the server returns a labelled typical estimate and a conservative ceiling from the same request the writer receives; the UI shows "Usually about Y · up to X held · Use X" | `postgres_final_credit_estimate.py` (4); browser on 4462: "Usually about 5.8 credits. Up to 34.4 is held…" | LOCAL_VERIFIED |
| Limit | A maximum below the ceiling is refused with the ceiling named (402) | same | LOCAL_VERIFIED |
| Deep ceiling | Bounded by 2 × `max_tokens` for the re-read draft (was the 1 MB transport cap: 657 credits → 30.7) | `test_final_deep_ceiling.py` (2) | LOCAL_VERIFIED |
| Reservation | Held before any provider call; replay of the same key + same request returns the original run before any new authorization; a different request with the same key → 409 `idempotency_conflict` | `postgres_final_idempotency.py` (5, incl. crash after reservation) | LOCAL_VERIFIED |
| Settlement | Actual cost (gateway cost when reported) rounded up exactly; charged within the approved maximum | `postgres_credits.py`, `postgres_final_unknown_usage.py` | LOCAL_VERIFIED |
| Failure before dispatch | Released, specific reason, nothing charged | `test_final_runtime_failures.py` | LOCAL_VERIFIED |
| Known-cost failure (4xx, 429, outside provider, truncated twice) | Not charged; provider cost booked | same + `test_final_gateway_routing.py` | LOCAL_VERIFIED |
| Unknown cost (5xx, timeout, crash after dispatch) | Hold kept; operator settles once with evidence (`scripts/reconcile_unknown_usage.py`, loopback unless `--confirm-host`); visible in `scripts/ops_health_report.py` | `postgres_final_unknown_usage.py` (6), `postgres_final_ops_report.py` | LOCAL_VERIFIED |
| Resend after a lost response | Client resends the identical keyed request (network error, 150 s timeout, 502/503/504 without an app code), never after an app answer | `web/tests/credit-turn.test.cjs` (11) | LOCAL_VERIFIED |
| Campaign occurrence | Worker uses its own credit authority; free routes run under credit terms | `postgres_final_campaign_destinations.py` (4) | LOCAL_VERIFIED |
| Images | Media credit reserved; image served outside the approved providers → credit returned, known cost booked | `postgres_final_image_routing.py` (2) | LOCAL_VERIFIED |
| Kill switch | `POSTRIFF_CREDITS_ENABLED=0` stops new paid tasks; settlement and history still work; the UI falls back to the legacy view without explaining (gap) | existing tests | IMPLEMENTED_UNVERIFIED |
| Gaps | voice analysis rounds with `ceil`; research unmetered; 10,000-row read cap; no Unknown-state UI; credit mode for voice/images/learning not reviewed end to end | — | open |

## One-time top-ups (Stripe Checkout)

| Event / case | Behaviour | Evidence | Status |
|---|---|---|---|
| Key mode | Live/test from all four key prefixes (`sk_`/`rk_` × live/test); unknown formats refused (503); every webhook must carry matching `livemode` | `test_final_stripe_mode.py` | LOCAL_VERIFIED |
| Checkout | Owner only; server-priced; session expires after 1 h; a repeat never returns an ended or paid session URL (409 / `status: funded`) | `postgres_final_purchase_lifecycle.py` (7) | LOCAL_VERIFIED |
| `checkout.session.completed` (paid) | Credits granted once per payment; session workspace must match the order | same + `postgres_credit_purchases.py` | LOCAL_VERIFIED |
| Replay / concurrency | Duplicate events acknowledged, nothing granted twice | same | LOCAL_VERIFIED |
| `checkout.session.expired` / `async_payment_failed` | Order ends as `expired` / `failed`; a later verified payment still funds it (money wins) | same | LOCAL_VERIFIED |
| Refund | Takes back the refunded share; spent credits become debt repaid from the earliest-expiring usable credits | same | LOCAL_VERIFIED |
| Disputes (`charge.dispute.*`) | Withdrawn funds reverse; won/reinstated restores; inquiries reverse nothing; lost stays reversed | same | LOCAL_VERIFIED |
| Unappliable verified event | Durable inbox `needs_review` (PII-free), 2xx, replay → duplicate; operator `scripts/credit_payment_inbox.py`; outages still 5xx for retry | same + ops report | LOCAL_VERIFIED |
| Owner email | Sent after commit, never while rows are locked | `postgres_final_billing_notice_locks.py` | LOCAL_VERIFIED |
| Fixture provider | Refuses every webhook when `VERCEL=1` | `test_final_fixture_guard.py` | LOCAL_VERIFIED |
| Stripe Sandbox (test-mode account, real API) | not run | — | NOT_RUN (needs authorization) |
| Real payment | not run | — | NOT_RUN |
| Gaps | `charge.refund*` events not handled separately; Stripe API version not pinned; financial records cascade-deleted with a workspace | — | open |

## Monthly subscription credits

| Event / case | Behaviour | Evidence | Status |
|---|---|---|---|
| `invoice.paid` (`subscription_create` / `subscription_cycle`) on plan terms with `creditPolicy` + `monthlyCredits` | Grants that amount once per invoice id, expiring at the period end (no rollover); stored with subscription, period, amount, currency, payment intent, plan terms | `postgres_final_monthly_credits.py` (8) | LOCAL_VERIFIED |
| Checkout completion, subscription updates, failed payments, proration invoices | Grant nothing (proration recorded with a note: policy pending) | same | LOCAL_VERIFIED |
| Out-of-order delivery | Status update marked stale; credits still granted | same | LOCAL_VERIFIED |
| Spending order | Expiring monthly credits first; top-up lots never reset by a cycle | same | LOCAL_VERIFIED |
| Refund / dispute of a plan payment | That period's credits taken back proportionally | same | LOCAL_VERIFIED |
| Legacy plans | Unchanged (writing batches / media credits) | existing billing tests | LOCAL_VERIFIED |
| Invoice shapes | Older and 2025+ (`payments`) shapes parsed; the 2025+ shape is unverified against live Stripe | same | IMPLEMENTED_UNVERIFIED |
| Owner decisions needed | Upgrade/downgrade proration, trial credits, rollover, refund of consumed monthly credits (creates debt), plan resolution by stale metadata plan id | — | open |

## Estimated cost per task (formula, not measured)

From `evidence/final/r1/cost-estimates.json` (default price table `defaults-2026-09-23`, not checked against the
gateway price list; p50/p95 not measured because no real samples were run):

| Task | Sonnet 5 typical / ceiling | Haiku 4.5 typical / ceiling |
|---|---|---|
| Caption, 1 destination, quick | 1.8 / 18.3 credits | 0.9 / 9.2 |
| 4 destinations (multi-account, multi-language), standard | 5.6 / 19.1 | 2.8 / 9.6 |
| Deep, 2 destinations | 6.1 / 30.7 | 3.1 / 15.4 |
| Image (estimate) | $0.10 ≈ 30 credits | — |

Not included: hosting (Vercel active CPU), Supabase storage/database, Stripe fees, email, failed or unknown runs
the platform absorbs, support. No unlimited AI plan is offered.
