# Rafii Pricing + Credits v2 Worker Handoff — 2026-09-28

You are taking ownership of the Rafii app-wide Pricing + Credits v2 implementation.

This is an EXECUTION handoff. Do not stop after auditing or rewriting the plan. Implement the saved specification end-to-end through local/test verification, while respecting the explicit production activation boundary below.

## Authoritative repository

/Users/ouxianxing/Documents/James-Au-Studio

Canonical release branch observed during the research pass:
consumer-saas

Observed HEAD during research:
468811b73d28b4389f931519827c05d0e6c8abfb

This state may have moved. Re-check origin, default/release branch, HEAD, status, worktrees, and migrations yourself before editing.

IMPORTANT: the shared canonical checkout was already dirty with unrelated/in-progress work during the research pass. Do not reset, clean, stash, overwrite, or implement directly in that dirty checkout.

Use superpowers:using-git-worktrees and create/reuse an isolated worktree from the actual current canonical release base.

## Read these first and treat them as authoritative

1. docs/superpowers/specs/2026-09-28-rafii-pricing-credits-app-wide-design.md
2. docs/superpowers/plans/2026-09-28-rafii-pricing-credits-app-wide.md
3. AGENTS.md
4. CLAUDE.md

Artifact persistence note:
- During handoff creation these three new docs were intentionally left uncommitted in the already-dirty canonical checkout to avoid disturbing concurrent sessions.
- Before changing into a new worktree, read them from these absolute paths:
  - /Users/ouxianxing/Documents/James-Au-Studio/docs/superpowers/specs/2026-09-28-rafii-pricing-credits-app-wide-design.md
  - /Users/ouxianxing/Documents/James-Au-Studio/docs/superpowers/plans/2026-09-28-rafii-pricing-credits-app-wide.md
  - /Users/ouxianxing/Documents/James-Au-Studio/docs/superpowers/handoffs/2026-09-28-rafii-pricing-credits-v2-worker-handoff.md
- After creating the isolated implementation worktree, copy those three exact artifacts into the same relative docs/superpowers paths in the worktree and make them the first documentation commit on the implementation branch. Verify their hashes/content before deleting or replacing anything.

The three source research documents used to derive the spec are:

- /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/pricing-strategy.zh-Hant.md
- /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/growth-jev-analysis.zh-Hant.md
- /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/strategy.zh-Hant.md

If a commercial number conflicts, those latest three research documents + the saved spec win over legacy code/comments.

## Input contract

Authoritative inputs are:
- the saved spec and implementation plan;
- the verified current canonical repository/branch/HEAD at execution start;
- the current migration chain and legacy billing rows;
- verified Stripe test-mode configuration when available;
- real test output produced in the isolated worktree.

Reject as authority:
- stale branch/HEAD values from this handoff when the repository has moved;
- client-provided price amounts or provider Price ids;
- unverified cost estimates presented as actual cost;
- unrelated dirty changes from the shared canonical checkout;
- historical USD 19/USD 39 copy as a v2 commercial decision.

## Workflow / process

Execute in this order:
1. verify repository, canonical release base, migration sequence, and dirty/shared state;
2. create/reuse an isolated worktree;
3. establish baseline billing/Stripe/credit tests;
4. execute Tasks 1–6 sequentially from the saved plan to stabilize schema, credits, pricing, Free lifecycle, and API contracts;
5. execute independent UI work only after the API contract is stable;
6. integrate one branch/task at a time, rerunning affected tests after each integration;
7. complete top-up-disabled contract, beta telemetry, docs, and release runbook;
8. run the full verification matrix;
9. run a fresh whole-branch review and fix Critical/Important findings with RED→GREEN tests;
10. stop at the explicit production activation boundary and return the completion receipt.

Do not replace this process with a new audit-only document or a fresh proposal.

## Dry-run versus real-operation distinction

Local/disposable database work, fixture billing, and Stripe test mode are validation operations and may be executed.

The following are REAL external commercial operations and are explicitly outside this handoff: production database migration, live Stripe Price creation/activation, production checkout enablement, real customer charge, Starter/Studio activation, credit-pack launch, and production deployment. Preparing commands/runbooks for those actions is allowed; executing them is not.

Every completion report must label evidence as local, disposable DB, Stripe test, or production/live so test evidence is never presented as proof that a live commercial action happened.

## Required execution method

Use:
- superpowers:subagent-driven-development, preferred;
- or superpowers:executing-plans if subagents are unavailable.

Follow the saved implementation plan task-by-task.
Use TDD: RED → GREEN → REFACTOR.
Use fresh verification before any completion claim.
Make frequent focused commits in the isolated branch.

Do not ask James to reconfirm routine implementation choices that are already decided in the spec. If the plan is ambiguous, make the smallest safe ruling consistent with the spec, record it, and continue.

## Commercial target you must implement

Launch-facing catalog:
- Free: USD 0, 0 fungible managed credits.
- Creator: USD 59/month default, 3,500 managed credits/month.

Creator paid-beta price variants:
- USD 49
- USD 59
- USD 79

ALL THREE CREATOR PRICE VARIANTS MUST HAVE IDENTICAL ENTITLEMENTS AND IDENTICAL 3,500 MONTHLY CREDITS.

Future catalog, seeded but hidden/non-purchasable:
- Starter: USD 29, 1,000 credits/month.
- Studio: USD 149, 8,000 credits/month.

Top-up candidates, prepared but disabled:
- 1,000 credits: USD 15.
- 2,000 credits: USD 29.

Credit conversion:
- 300 credits = USD 1 verified billable provider/tool cost.
- round once per task, not per internal hop.
- reserve max before paid I/O.
- settle actual verified cost.
- failed run releases user credits.
- unknown cost stays pending.
- actual over approved max is platform-absorbed, never silently debited from user.

No monthly subscription credit rollover by default.

## Legacy behavior you MUST preserve

Current legacy new-sale code contains:
- studio-v1 / USD 19
- assist-v1 / USD 39
- trial-v1 / 14 days / writing batches / media credit

Do NOT silently reprice, auto-upgrade, or break existing active subscribers.

Required migration behavior:
- legacy paid subscribers remain valid and reconcile Stripe renewals/webhooks;
- legacy packages are hidden from new sale;
- existing trial workspaces finish the current trial;
- with pricing v2 enabled, new workspaces get Free instead of trial-v1;
- an expired grandfathered trial falls back to Free;
- cancelled/ended v2 paid subscriptions retain user data and fall back to Free.

## Free cost boundary

Free must NOT become unlimited managed AI.

Launch Free:
- zero fungible managed credits;
- one platform-funded first-value Post Doctor run;
- one one-time recent-20 Genome analysis/import;
- optional one connected account max as specified;
- platform-funded provider cost is still measured;
- second/unauthorized free paid-provider use is refused before external paid I/O;
- an unapproved platform budget blocks paid I/O.

Do not invent additional recurring free writer allowance.

## Architecture requirements

Reuse the existing systems:
- pr_usage_ledger
- CreditBook
- credit quotes
- reserve/settle/release
- invoice monthly-credit grants
- refund/dispute handling
- Stripe Checkout Sessions
- Billing Portal
- verified webhook processing

Do NOT build a parallel billing engine.

Separate plan entitlement from price:
- Creator entitlement is one package.
- USD 49/59/79 are price variants.
- stable workspace beta assignment.
- client cannot supply/override the actual amount or Stripe Price id.
- persist price_variant_id on subscription.
- Stripe verified metadata/provider price resolves the assignment.

Expose explicit billing modes:
- free_preview
- managed_credits
- legacy_allowances

Do not infer mode from a price or from writingBatchesRemaining.

## App-wide UI requirement

Audit and update all customer-visible pricing and usage surfaces.

Public:
- pricing page
- landing pricing section
- plan cards
- JSON-LD
- auth/signup copy
- terms/billing copy
- relevant FAQ/help

Authenticated:
- Usage & plan
- plans
- allowances
- credit balance
- credit packs
- overview
- Ideas/capture
- writing-now
- any remaining legacy batch language

For v2 users:
- no “AI writing batches” as the main allowance;
- show managed credits, held state, period reset/expiry, and no-silent-overage copy.

For legacy users:
- preserve truthful legacy allowance display.

Launch public page shows Free + Creator only.
Starter and Studio must not have active checkout CTAs.

## Stripe guardrails

Use existing Stripe Billing + Checkout Sessions.
Keep webhook signature verification.
Keep dynamic payment methods; do not add payment_method_types.
Use server-owned Price ids.
Keep test/live separation.
Never commit/log keys.
Prefer restricted keys where supported.

## PRODUCTION BOUNDARY — DO NOT CROSS WITHOUT A NEW EXPLICIT AUTHORIZATION

You MAY:
- change code;
- add additive migrations to source;
- run disposable/local PostgreSQL migrations;
- use Stripe test mode if configured;
- run unit/integration/browser/build tests;
- commit the implementation branch;
- prepare a release/activation runbook.

You MUST NOT, as part of this handoff:
- apply the new migration to production;
- create or activate live Stripe Prices;
- enable production Creator checkout;
- enable production credit-pack purchases;
- charge a real customer;
- activate Starter or Studio;
- deploy production merely because local tests pass;
- alter OAuth/publishing/auth enforcement unrelated to billing.

Stop only if a genuinely human-only external production action is required. Local implementation/test work is not such a blocker.

## Worker decomposition

Do the billing/data foundation sequentially first:
1. isolated worktree + baseline;
2. migration/catalog;
3. v2 credit policy/wallet;
4. Creator price variants + Stripe;
5. Free lifecycle + free cost boundary;
6. stable API contract.

After the API contract is stable, you may use independent workers for:
A. public pricing/marketing;
B. authenticated billing/credit UI;
C. Ideas/Overview/writing legacy-batch cleanup;
provided they work in isolated contexts and do not concurrently edit the same files.

Then integrate:
7. top-up-disabled contract;
8. beta economics instrumentation;
9. docs/release runbook;
10. full branch verification + fresh whole-branch code review.

## Required verification before declaring implementation complete

Run fresh:
- Python unit suite required by repo;
- full PostgreSQL suite;
- billing + Stripe focused tests;
- web unit/contract tests;
- TypeScript typecheck;
- lint;
- production web build;
- pricing/billing browser tests at desktop + mobile;
- secret scan;
- migration prefix uniqueness;
- residual repo search for stale USD 19/39 new-sale copy and v2 writing-batch copy.

Specifically prove:
- Free + Creator are the only launch-visible plans.
- default Creator is USD 59.
- USD 49/59/79 all map to the same Creator 3,500-credit entitlement.
- hidden Starter/Studio cannot checkout.
- Free has zero fungible credits.
- Creator invoice grants 3,500 credits once.
- 300 credits/USD settlement works.
- failed/unknown/over-max credit states behave correctly.
- legacy active subscription still reconciles.
- new v2 workspace defaults Free.
- client cannot choose arbitrary price.
- credit packs remain disabled.

## Completion report format

Return:
1. Branch/worktree and exact HEAD.
2. Commits made, grouped by task.
3. Files changed.
4. Migration created and its exact prefix/checksum.
5. Test commands + exact pass/fail counts.
6. Stripe test-mode evidence, if available.
7. Residual legacy-reference audit and why each remaining hit is intentional.
8. Rulings made.
9. Deferred minor findings.
10. Explicit state matrix:
   - Local implementation
   - Local/disposable DB migration
   - Stripe test mode
   - Production DB
   - Live Stripe Prices
   - Production checkout
   - Production deployment
11. Exact next human-only production activation steps, if local implementation is fully verified.

Do not summarize this handoff and stop. Read the spec and plan, then execute the implementation through the allowed boundary.
