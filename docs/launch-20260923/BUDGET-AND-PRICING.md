# Budget policy and provisional pricing — 2026-09-24

Decided under the owner's full-speed delegation. These are provisional values, each versioned so it can be replaced.
Machine-readable pricing: `pricing-2026-09-24.json`. Cost basis: token counts measured on real gateway calls in
`LIVE-MODEL-QUALIFICATION.md`, priced at the gateway's public list (2026-09-24).

## 1. Spending limits (provider cost in USD, not customer prices)

An operator turns a policy on per deployment with `POSTRIFF_BUDGET_POLICY=<id>` (`billing.BUDGET_POLICIES`). Without a
policy, every budget stays `candidate` and every paid request is refused (402), as before.

| Limit | `launch-2026-09-24` (now: live charges off, no revenue) | `paid-2026-09-24` (after live charges open) |
|---|---|---|
| Whole service, per day (UTC): warn / stop | US$5 / US$10 | US$25 / US$50 |
| Whole service, per month: warn / stop | US$60 / **US$100** | US$300 / **US$500** |
| One workspace, per month: warn / stop | US$6 / US$10 | US$30 / US$40 |
| One person, rolling 24 h, across all workspaces | US$3 | US$5 |
| One request's worst case (the reservation) | US$1 | US$2 |

Why these numbers:

- Launch month: at most **US$100** of provider cost, whatever happens.
- A typical draft on the default writer costs about US$0.006–0.025, so the launch caps still allow roughly
  4,000–16,000 drafts a month.
- The paid workspace stop (US$40) sits above the largest plan's monthly credits: 3,500 credits ≈ US$11.7 of
  provider cost, and a full 10,000-credit pack ≈ US$33.
- The per-request ceiling refuses only extreme cases, for example Opus with a maximal 60 kB context and deep
  reasoning. The message tells the person how to fit: fewer sources, a lighter model or quicker reasoning.

How it works:

- Every reservation checks all limits **before** any provider call.
- A reservation records the budgets it held (`meta.budgetScopes`), and settlement releases exactly those.
- An unknown cost keeps its hold until reconciled (`scripts/reconcile_unknown_usage.py`).
- A budget an owner already approved with other caps keeps them.
- An unknown policy id refuses paid work (503) rather than guessing.

Tests: `tests/phase2/postgres_budget_policy.py`, 8 checks on disposable PostgreSQL.

### Runaway protection

| Risk | Protection |
|---|---|
| Runaway agent turn | 2 attempts at most (+1 revise pass on deep); 2,400 output tokens (up to 4,500 for models that reason when drafting, trimmed so the reservation fits `requestMax`); 45 s (90 s for thinking models); 60 kB context; interrupted runs are never retried |
| Retried requests | same idempotency key → same reservation, never a second charge |
| Automation runaway | per-run cost limit; paid-writer automations wait for the owner; ≤ 5 runs / 90 s per cron tick; runs > 24 h late are missed, not replayed; failed runs are held, not retried; plus the workspace, person and service stops above |
| Recursive calls | automation runs cannot read requests or create automations; creating an automation makes no model call |
| Request reading | one light-model call per message, only with a scheduling cue; deterministic fallback |
| Scripts with API tokens | 20 drafts per 60 s per token, plus every budget above |

### Kill switches

- `POSTRIFF_AI_PAUSED=1`: every request that costs provider money is refused with 503. Nothing is sent or charged;
  drafts, edits and publishing keep working.
- Removing `AI_GATEWAY_API_KEY` unmounts the managed writer.
- `POSTRIFF_CREDITS_ENABLED=0` / `POSTRIFF_CREDIT_PURCHASES_ENABLED=0` turn off the credit wallet and purchases.

### What people see (402 unless noted; the app shows the message as-is)

- Budget not approved: "Paid AI drafting is not switched on for this deployment yet: its spending budget has not been approved. Nothing was sent or charged."
- Workspace month: "This workspace has reached its AI spending limit for this month (US$10.00 of provider cost). Nothing was sent or charged. Drafts, edits and publishing still work; new AI drafts resume next month or when the limit is raised."
- Service day / month: "Rafii has reached its AI safety limit for today (UTC) / this month. Nothing was sent or charged; new AI drafts resume when the period ends."
- Person: "You have reached the AI spending limit for one person over 24 hours (US$3.00 of provider cost). …"
- Request: "This request could cost up to US$x of provider time, over the US$1.00 limit for one request. Nothing was sent; select fewer sources, a lighter model or quicker reasoning."
- Paused (503): "AI requests that cost money are paused by the operator. …"
- Credits (unchanged, credit mode): "Insufficient available credits; no model request was sent.", "This task exceeds your credit limit. Increase it or reduce the task.", "Confirm this task credit limit before generating."

### Admin visibility

- Cron `operational_signals` (logged every run) counts `budgetStops` and the new `budgetWarnings`.
- A reservation that crosses a warning line logs one line: `{"event": "budget.warning_crossed", "scopes": [...], "policy": ...}`. It carries no workspace or person identifier, so a Vercel log drain can alert on it.
- `scripts/ops_health_report.py` lists budgets past stop, past warning and not approved, unknown costs, the payment inbox and publishing problems.
- Owners see an amber bar on Usage & plan (allowance mode).

Not yet built (follow-ups): outbound alerts (the signals are logged, not sent); a per-person rate limit on signed-in drafting (the spend caps bound the damage); an index on `pr_usage_ledger(member_id, at)` once volume grows; metering web research.

## 2. Provisional pricing (not active)

One credit = 1/300 US$ of provider cost (`credits-candidate-2026-09-23-v1`, 300 credits per US$1, rounded up to 0.1
credit per task). Customer prices:

| Credit pack (one-off) | Price | Per credit | Margin over provider cost |
|---|---|---|---|
| 1,000 credits | US$10 | US$0.0100 | 3.0× |
| 3,000 credits | US$27 | US$0.0090 | 2.7× |
| 10,000 credits | US$80 | US$0.0080 | 2.4× |

| Plan (monthly) | Price | Included credits / month | Other entitlements |
|---|---|---|---|
| Trial (unchanged) | US$0, 14 days | allowance model: 10 writing batches, 1 media credit | cannot buy packs |
| Studio `studio-v2` | US$19 | 1,000 | as `studio-v1` (1 member, 3 accounts, 1 GB) |
| Studio Assist `assist-v3` | US$49 | 3,500 | as `assist-v1` |

What a credit buys (measured tokens × list price, then 300 credits per US$):

| Task | Sonnet 5 (default) | Opus 5.5 |
|---|---|---|
| Typical 2-destination draft (≈ 900 input / 400 output tokens) | ≈ 1.8 credits | ≈ 3.5 credits |
| Same with a full voice profile and skills (≈ 10k input tokens) | ≈ 7.5 credits | ≈ 15 credits |
| Long context (16k input tokens) | ≈ 10.3 credits | ≈ 20.6 credits |
| Reading a chat request (Haiku 4.5) | ≈ 0.9 credit | — |

So 1,000 credits ≈ 130–550 drafts on the default writer.

Terms to put in the Terms of Service once counsel confirms them:

- Included monthly credits do not roll over.
- Purchased credits are valid 12 months.
- Unused purchased credits can be refunded within 14 days.
- A failed run charges nothing.
- A run whose cost is unknown holds credits until reconciled, never above the maximum the person approved.

A third tier (US$99 / 8,000 credits, from the 2026-09-23 proposal) needs a migration, because `pr_plan_terms.plan`
only allows `trial`, `studio` and `assist`. It is deferred.

### Real charges are blocked until the legal facts exist

The repository has no merchant legal entity, registered address or governing law. The legal pages carry
"[… to be confirmed by counsel]" placeholders (`web/src/config/legal.ts`), and none was invented.

`hosted_app.billing_from_environment` therefore refuses to mount a **live** Stripe key unless:

- `POSTRIFF_LEGAL_ENTITY`, `POSTRIFF_LEGAL_ADDRESS` and `POSTRIFF_GOVERNING_LAW` are set, with no `[` placeholder; and
- `POSTRIFF_LIVE_CHARGES_ENABLED=1` is set.

Until then, billing uses the disabled provider: nothing can be bought and every webhook is refused. Stripe
**test-mode** keys are not gated, because they cannot charge. Test: `tests/test_postriff_billing.py`.

### To activate (in this order)

1. Record the legal facts, have counsel review the Terms/Privacy, and flip `LEGAL_REVIEW_STATUS` to `reviewed`.
2. In Stripe **test mode**:
   - create the two monthly prices and three one-off prices;
   - set `STRIPE_SECRET_KEY` (`sk_test_…`) and `STRIPE_WEBHOOK_SECRET` on a staging deployment;
   - run the billing matrix (`FINAL-BILLING-MATRIX.md`).
3. Apply migrations 020–022 to the database, then insert:
   - `studio-v2` and `assist-v3` into `pr_plan_terms` with `status='active'` and `provider_price_id`;
   - the three packs into `pr_credit_packs` with `active=true`, `policy_id='credits-candidate-2026-09-23-v1'`, the Stripe `price_id` and `livemode` matching the key.
4. Set `POSTRIFF_CREDITS_ENABLED=1`, `POSTRIFF_CREDIT_PURCHASES_ENABLED=1` and `POSTRIFF_BUDGET_POLICY=paid-2026-09-24`.
5. Live mode: repeat step 2 with live prices, then set the legal facts and `POSTRIFF_LIVE_CHARGES_ENABLED=1`.
