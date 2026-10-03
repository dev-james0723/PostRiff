# Rafii Pricing and Credits v2 App-wide Implementation Plan

> Latest direct user amendment (2026-10-03): Starter and Studio must be purchasable. This supersedes the visibility-only restriction in the prior amendment. Approve Starter US$29 / 1,000 credits and Studio v2 US$149 / 8,000 credits for qualified checkout. Reuse server-owned fixed Price bindings, owner-only checkout and verified signed invoice funding. Actual provider setup/unique verified Price binding and credits activation remain required. Production deployment remains outside this LOCAL task.

> Approved user amendment (2026-10-03): publicly include Starter US$29/month with 1,000 credits and Studio (`studio-v2`) US$149/month with 8,000 credits alongside Free and Creator. This supersedes the two-plan/hidden Starter and Studio visibility clauses below. Existing capacity quantities and legacy `studio-v1` US$19 terms remain unchanged. Visibility does not activate checkout, provider spend or production. All remaining Tasks 0–13 acceptance and funding restrictions continue to apply.

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use TDD and fresh verification. Do not work in the current dirty canonical checkout.

**Goal:** Replace Rafii's legacy new-sale USD 19 / USD 39 writing-batch pricing with the v2 Free + Creator launch model, implement stable Creator USD 49 / 59 / 79 price variants with identical entitlements, make managed credits the paid-usage model, preserve legacy subscribers, and update every customer-visible pricing/usage surface without activating production billing.

**Architecture:** Keep the existing Stripe Billing + Checkout + webhook + immutable usage-ledger architecture. Add a v2 catalog layer that separates package entitlements from price variants, keep legacy plans readable but unavailable to new buyers, reuse CreditBook for reserve/settle/release, and make frontend billing mode explicit: free_preview, managed_credits, or legacy_allowances.

**Tech Stack:** Python/PostgreSQL, Next.js/React/TypeScript, Stripe Checkout/Billing, existing Supabase/PostgreSQL migrations, current Rafii test harnesses.

**Spec:** docs/superpowers/specs/2026-09-28-rafii-pricing-credits-app-wide-design.md

## Input contract

Implementation consumes:
- the saved v2 pricing/credits spec above;
- the actual current canonical repository state at execution time;
- the current migration chain and existing legacy plan/subscription rows;
- configured Stripe test-mode Price ids only when available;
- existing billing, CreditBook, usage-ledger, lifecycle, and UI contracts.

Never treat stale remembered branch state, a client-provided amount, an unverified provider cost, or an uncommitted shared-worktree edit as authoritative input. When current repo state differs from the research snapshot, preserve the commercial values from the spec while adapting file/migration mechanics to the verified current base.

## Global constraints

- Re-read AGENTS.md and CLAUDE.md before implementation.
- Inspect current branch, HEAD, status, worktrees, and migration prefixes before editing.
- The research pass observed consumer-saas @ 468811b73d28b4389f931519827c05d0e6c8abfb with a dirty shared checkout. Do not implement there.
- Use superpowers:using-git-worktrees to create or reuse an isolated worktree from the current canonical release base.
- Never reset, clean, stash, or overwrite another session's work.
- New-sale launch surface is Free + Creator only.
- Starter USD 29 / 1,000 credits and Studio USD 149 / 8,000 credits are seeded hidden/proposed and non-purchasable.
- Creator default is USD 59 / 3,500 credits. Paid-beta variants USD 49 / 59 / 79 must have identical entitlements.
- 300 credits = USD 1 verified billable cost. Preserve task-level quote/reserve/settle/release.
- Free receives 0 fungible managed credits.
- Legacy USD 19 / USD 39 customers are grandfathered and must not be silently repriced.
- Existing trial workspaces finish their current trial; new v2 workspaces default to Free when the v2 feature is enabled.
- Credit top-ups remain disabled in initial rollout.
- Do not create or activate live Stripe Prices, apply production migrations, charge customers, deploy production, or turn on production checkout unless a later explicit operational authorization says to do so.
- Do not change OAuth scopes, publishing gates, auth enforcement, unrelated feature flags, or provider review states.
- Every production-code change follows RED → GREEN → REFACTOR.
- No completion claim without fresh test/build evidence.

## Review focus

1. Legacy active subscriptions: a migration or catalog filter must not make webhook reconciliation fail for existing studio-v1 / assist-v1 subscribers.
2. Price experiment stability: a workspace must not be able to change Creator price by retrying, clearing local state, or manipulating a client payload.
3. Credit overrun: actual provider cost above the approved max must never debit extra user credits.
4. Free cost tail: Free first-value actions must be separately budgeted/rate-limited and must not become an unlimited paid-provider path.
5. Dual-mode UI: legacy allowance users and v2 credit users must both render truthful usage without writing-batch language leaking into v2.

---

## Task 0: Create isolated worktree and freeze the baseline

**Files:** no product edits.

- [ ] Read AGENTS.md, CLAUDE.md, the spec, and this plan.
- [ ] Run worktree detection from superpowers:using-git-worktrees.
- [ ] Re-fetch / inspect origin state and confirm the actual canonical release branch before creating a worktree.
- [ ] Create an isolated branch such as codex/rafii-pricing-credits-v2 from the current canonical release commit.
- [ ] Verify the worktree is isolated and clean.
- [ ] List migrations/postriff and assert numeric prefixes are unique.
- [ ] Record the next free migration prefix. The research snapshot suggested 023, but current repository state wins.
- [ ] Run the smallest current billing baseline:
  - Python billing unit tests.
  - Stripe unit tests.
  - PostgreSQL billing/credits scripts.
  - web billing/model tests.
- [ ] If baseline tests fail before any edit, record the exact pre-existing failure and keep it separate from v2 work; do not “fix around” it silently.
- [ ] Commit nothing in this task unless worktree setup itself requires an ignored-directory change.

Expected result: isolated clean worktree with a known baseline and no change to the shared dirty checkout.

---

## Task 1: Add v2 catalog schema without breaking legacy plans

**Files:**
- Create: migrations/postriff/<next-free>_pricing_credit_catalog_v2.sql
- Modify only if verified necessary: migrations/postriff/hosted-004-008.sql
- Create or modify PostgreSQL migration tests under tests/phase2/

**Produces:**
- legacy + free + starter + creator + studio + assist plan identity support.
- catalog_state and new_checkout_enabled.
- pr_plan_price_variants.
- pr_price_experiment_assignments.
- pr_subscriptions.price_variant_id.
- seeded v2 plan terms and proposed Creator price variants.
- inactive proposed credit-pack rows if pack seeding belongs in this migration.

- [ ] Write a failing migration test that applies the current migration chain and asserts the v2 plan identities are rejected / absent before the new migration.
- [ ] Write failing assertions for catalog_state, new_checkout_enabled, price-variant tables, stable-assignment table, and subscription price_variant_id.
- [ ] Write failing assertions proving existing studio-v1 / assist-v1 rows survive and their price_cents values remain unchanged.
- [ ] Write failing assertions for exact seeded v2 values:
  - Free USD 0, 0 managed credits.
  - Starter USD 29, 1,000 credits, hidden/proposed.
  - Creator USD 59 base, 3,500 credits, public/proposed.
  - Studio USD 149, 8,000 credits, hidden/proposed.
  - Creator price variants 4,900 / 5,900 / 7,900 cents.
- [ ] Run the migration test and confirm RED is due to missing v2 schema.
- [ ] Implement an additive migration. Do not rewrite old migration files unless the project has a verified bootstrap mirror that must be kept in sync.
- [ ] Set legacy catalog rows to legacy/new_checkout_enabled=false without changing active subscription semantics.
- [ ] Seed v2 plan terms with credit-plan compatibility fields writingBatches=0 and mediaCredits=0.
- [ ] Seed Creator variants as proposed with no live Stripe Price ids.
- [ ] If top-up rows are seeded, set active=false and use:
  - 1,000 credits = 1,000,000 millicredits / USD 15.
  - 2,000 credits = 2,000,000 millicredits / USD 29.
- [ ] Run migration tests to GREEN.
- [ ] Run the full PostgreSQL migration integrity / prefix uniqueness checks.
- [ ] Commit: feat(billing): add pricing and credit catalog v2 schema

Acceptance:
- migration is additive;
- old subscribers remain representable;
- no new checkout becomes active merely by applying SQL.

---

## Task 2: Version the production credit policy and preserve wallet invariants

**Files:**
- Modify: src/postriff_phase2/credit_meter.py
- Modify: src/postriff_phase2/credit_wallet.py
- Modify: src/postriff_phase2/billing.py
- Test: tests/phase2/postgres_credits.py
- Test: tests/phase2/postgres_final_monthly_credits.py
- Add focused unit tests where needed.

**Produces:**
- explicit v2 credit policy id.
- 300 credits/USD conversion unchanged.
- v2 period-grant metadata for UI.
- legacy candidate policy remains auditable rather than silently renamed.

- [ ] Write failing tests for a new immutable v2 credit policy identifier.
- [ ] Write a failing test proving 1 USD settles to 300 credits and 0.013 USD settles to approximately 3.9 displayed credits using one task-level rounding step.
- [ ] Write failing tests for:
  - failed run releases user credits;
  - unknown usage stays held;
  - actual > approved max records absorbed cost instead of debiting extra;
  - duplicate settlement is idempotent;
  - parallel holds cannot overspend.
- [ ] Run focused tests and verify RED where behavior/API is not yet present.
- [ ] Add v2 policy version without mutating historical policy meaning.
- [ ] Preserve millicredit ledger and earliest-expiry lot allocation.
- [ ] Extend the wallet/API projection with evidence-backed current-period grant total and expiry. Do not fabricate a total when no grant exists.
- [ ] Keep monthly subscription grant expiry at currentPeriodEnd.
- [ ] Run focused credit tests to GREEN.
- [ ] Run existing credit-purchase/refund/dispute tests to ensure no regression.
- [ ] Commit: feat(billing): version managed credit policy

Acceptance:
- user debit remains actual-cost based;
- no silent over-max debit;
- old ledger history still projects.

---

## Task 3: Make plan pricing variants server-owned and stable

**Files:**
- Modify: src/postriff_phase2/billing.py
- Modify: src/postriff_phase2/hosted.py
- Modify: src/postriff_phase2/billing_stripe.py
- Modify: src/postriff_phase2/hosted_app.py if routing/config is required.
- Test: tests/test_postriff_billing.py
- Test: tests/test_postriff_stripe.py
- Test: tests/phase2/postgres_billing_stripe.py
- Add a PostgreSQL price-assignment test.

**Produces:**
- stable workspace Creator price assignment.
- Creator checkout resolves server-side Price id.
- Stripe metadata includes workspace_id, plan_terms_id, price_variant_id.
- subscription persists price_variant_id.
- client cannot choose an amount.

- [ ] Write a failing test: with experiment off, eligible Creator returns creator-59-v1.
- [ ] Write a failing test: with experiment on, a workspace gets one allowed 49/59/79 variant and repeated calls return the same row.
- [ ] Write a failing test: existing subscribed workspace is never re-assigned.
- [ ] Write a failing security test: client payload containing amount/price-id cannot override server assignment.
- [ ] Write a failing checkout test: hidden/proposed/non-new-checkout plans are refused.
- [ ] Write a failing checkout test: legacy active plan is not offered for a new checkout.
- [ ] Write a failing Stripe request test for price_variant_id metadata.
- [ ] Write failing webhook tests resolving variant by trusted metadata/provider price id and persisting it.
- [ ] Run tests and confirm RED.
- [ ] Implement a small price-assignment domain helper with transaction-safe get-or-create behavior.
- [ ] Keep public default Creator price at USD 59 when experiment is off.
- [ ] Change checkout to resolve allowed package + assigned price variant on the server.
- [ ] Keep Stripe Checkout Sessions, dynamic payment methods, verified webhooks, and current portal.
- [ ] Run all focused Stripe/billing tests to GREEN.
- [ ] Commit: feat(billing): separate creator price variants from entitlements

Acceptance:
- same Creator package always has 3,500 credits regardless of 49/59/79 assignment;
- no client-authoritative pricing.

---

## Task 4: Introduce Free as the v2 default without deleting legacy trial behavior

**Files:**
- Modify: src/postriff_phase2/billing.py
- Modify the workspace/bootstrap path discovered during implementation.
- Add or modify lifecycle tests under tests/phase2/.

**Produces:**
- new v2 workspaces receive Free.
- old unexpired trial stays trial.
- expired grandfathered trial falls to Free.
- expired/cancelled v2 paid subscriber retains drafts/export and returns to Free capability.

- [ ] Write a failing test for POSTRIFF_PRICING_V2_ENABLED=1: a new workspace gets free-v1 and no trial subscription.
- [ ] Write a failing test with v2 flag off: old behavior remains unchanged for rollback.
- [ ] Write a failing test: an existing unexpired trial-v1 continues until expiry.
- [ ] Write a failing test: after expiry in v2 mode, entitlement becomes Free without auto-checkout.
- [ ] Write a failing test: Creator cancellation/end returns usable Free entitlement, preserving history.
- [ ] Write a failing test that Free has no creditPolicy/monthlyCredits wallet.
- [ ] Run and confirm RED.
- [ ] Implement feature-gated Free defaulting and legacy trial grandfather logic.
- [ ] Do not implement automatic Creator trial conversion.
- [ ] Run focused lifecycle tests to GREEN.
- [ ] Commit: feat(billing): add free fallback lifecycle

Acceptance:
- rollback flag can restore old acquisition path;
- no customer is auto-charged or auto-upgraded.

---

## Task 5: Put a strict cost boundary around Free first value

**Files:**
- Modify relevant Post Doctor / Genome service paths discovered from current Growth implementation.
- Modify src/postriff_phase2/billing.py / budget checks only where needed.
- Add focused unit/PostgreSQL tests.

**Produces:**
- Free platform-funded action policy.
- one first-value Post Doctor action.
- one recent-20 Genome analysis/import.
- no fungible Free managed-credit wallet.
- no uncontrolled paid provider path.

- [ ] Locate the actual current Post Doctor and Genome execution entry points before editing. Do not invent a parallel service if the Growth branch has already implemented them.
- [ ] Write failing tests that a Free workspace may run the designated first-value action only through the platform-funded route.
- [ ] Write a failing test for the one-run Post Doctor cap.
- [ ] Write a failing test for the one-time recent-20 Genome cap.
- [ ] Write a failing test that the second Free attempt is refused before external paid I/O.
- [ ] Write a failing test that an unapproved platform budget refuses before external I/O.
- [ ] Write a failing test that provider cost is still written to platform telemetry even when user credits charged = 0.
- [ ] Run RED.
- [ ] Implement the smallest policy/rate-limit layer that reuses existing usage ledger and budgets.
- [ ] Do not unlock general free managed writing.
- [ ] Run GREEN.
- [ ] Commit: feat(growth): bound free first-value usage

Acceptance:
- Free proves value without creating the free-writer cost tail identified by research.

---

## Task 6: Expose explicit billing modes and a sanitized catalog API

**Files:**
- Modify: src/postriff_phase2/billing.py
- Modify: src/postriff_phase2/hosted.py / hosted_app.py if an endpoint is needed.
- Modify: web/src/lib/api/types.ts
- Modify: web/src/lib/api/client.ts
- Test backend and web pure models.

**Produces:**
- billingMode: free_preview | managed_credits | legacy_allowances.
- sanitized package catalog.
- current period credit total/expiry.
- effective assigned Creator price for authenticated workspace.
- no secret/provider credentials.

- [ ] Write failing backend tests for each billingMode.
- [ ] Write a failing test that current legacy plan still appears to its subscriber even when hidden from new sale.
- [ ] Write a failing test that normal catalog excludes hidden Starter/Studio from new-sale choices.
- [ ] Write a failing test that owner vs non-owner still respects existing cost-visibility rules.
- [ ] Write TypeScript contract tests for new fields.
- [ ] Run RED.
- [ ] Implement server projection.
- [ ] Update TypeScript types/client without nullable guessing.
- [ ] Run GREEN.
- [ ] Commit: feat(billing): expose v2 usage and catalog contract

Acceptance:
- UI no longer infers billing mode from price or remaining batch counts.

---

## Task 7: Replace the public new-sale pricing experience

**Files:**
- Modify: web/src/config/plans.ts or replace it with a v2 public catalog module.
- Modify: web/src/app/(marketing)/pricing/page.tsx
- Modify: web/src/components/marketing/landing/sections.tsx
- Modify: web/src/components/marketing/plan-card.tsx
- Modify: web/src/components/marketing/json-ld.tsx
- Modify: web/src/app/(marketing)/terms/page.tsx
- Modify: web/src/components/auth/auth-form.tsx
- Update public pricing/marketing tests and browser scenes.

**Produces:**
- Free + Creator public launch page.
- default Creator USD 59.
- no USD 19 / USD 39 new-sale copy.
- no “Two plans” or writing-batch sales language.
- signup starts free, no card.
- truthful JSON-LD.

- [ ] Write failing render/model tests asserting only Free and Creator are public at launch.
- [ ] Write a failing repository/copy test that customer-facing new-sale surfaces no longer contain the legacy USD 19/39 plan copy or “AI writing batches” as v2 sales language.
- [ ] Write a failing test that default Creator display is USD 59 and 3,500 managed credits.
- [ ] Write a failing test that Starter/Studio do not render checkout buttons.
- [ ] Write a failing JSON-LD test for only truthful public/default offers.
- [ ] Run RED.
- [ ] Update pricing page to lead with outcomes, then explain managed credits.
- [ ] Update landing/auth/terms copy.
- [ ] Keep beta/validation wording clear; do not claim USD 59 is optimized.
- [ ] Run web tests, typecheck, lint for GREEN.
- [ ] Run targeted browser scenes at phone and desktop widths.
- [ ] Commit: feat(marketing): launch free and creator pricing

Acceptance:
- a new prospect sees one free path and one paid Creator path, not the legacy catalog.

---

## Task 8: Convert authenticated Usage & Plan UI to managed credits while preserving legacy mode

**Files:**
- Modify: web/src/features/billing/billing-model.ts
- Modify: web/src/features/billing/billing-copy.ts
- Modify: web/src/features/billing/plans.tsx
- Modify: web/src/features/billing/allowances.tsx
- Modify: web/src/features/billing/plan-card.tsx
- Modify: web/src/features/billing/billing-view.tsx
- Modify: web/src/features/billing/credit-packs.tsx
- Tests: existing billing model/render/browser tests.

**Produces:**
- managed credit meter.
- held state.
- reset/expiry date.
- Free preview state.
- legacy allowance renderer.
- credit packs hidden while flag/catalog unavailable.

- [ ] Write failing pure-model tests for managed credit meter states: measured, held, unknown total, debt, expiring.
- [ ] Write failing tests that v2 plan does not render AI writing batches/media credits.
- [ ] Write failing tests that a legacy subscriber still gets legacy allowance meters.
- [ ] Write failing Free test: no 0/0 credit progress bar.
- [ ] Write failing test: hidden/inactive credit packs do not render.
- [ ] Write failing plan-offer tests using effective assigned price.
- [ ] Run RED.
- [ ] Implement billing-mode-specific components or focused branches; avoid one giant conditional file.
- [ ] Copy must say no silent overage and distinguish “held” from “used.”
- [ ] Keep raw provider USD cost owner-only / advanced, separate from customer credits.
- [ ] Run GREEN plus targeted browser scene.
- [ ] Commit: feat(billing-ui): show managed credits and legacy allowances truthfully

Acceptance:
- one user cannot mistake platform USD cost, credits, and legacy batches for the same concept.

---

## Task 9: Remove writing-batch assumptions from v2 work surfaces

**Files:**
- Modify: web/src/features/account/models/writing-now.tsx
- Modify: web/src/features/ideas/capture-card.tsx
- Modify: web/src/features/ideas/ideas-view.tsx
- Modify: web/src/features/overview/overview-view.tsx
- Modify any other customer-visible batch copy found by a fresh repository search.
- Add/modify tests for each affected surface.

**Produces:**
- v2 users see task credit quote / availability semantics.
- legacy users remain compatible.
- no stale “remaining batches” blocker for managed-credit plan.

- [ ] Re-run repository search for writingBatches, mediaCredits, USD 19/39, Studio Assist, “after trial,” and pricing.
- [ ] Classify every hit: database/history/test fixture, legacy-only runtime, or customer-visible stale v2 copy.
- [ ] Write failing tests for v2 surfaces currently driven by writingBatchesRemaining.
- [ ] Run RED.
- [ ] Switch v2 surfaces to billingMode/credit authority.
- [ ] Preserve legacy branch only where a grandfathered user still needs it.
- [ ] Re-run search and produce a residual-hit receipt explaining every intentional legacy occurrence.
- [ ] Run GREEN.
- [ ] Commit: refactor(billing): remove v2 writing batch assumptions

Acceptance:
- no v2 feature is accidentally blocked because writingBatchesRemaining=0 on a credit plan.

---

## Task 10: Keep top-ups prepared but safely disabled

**Files:**
- Modify only if needed: src/postriff_phase2/credit_purchases.py
- Modify only if needed: web/src/features/billing/credit-packs.tsx
- Migration/catalog rows from Task 1.
- Tests: tests/phase2/postgres_credit_purchases.py and purchase lifecycle tests.

**Produces:**
- exact candidate packs exist inactive.
- launch config does not expose them.
- future activation has working payment/refund/dispute mechanics.
- purchased-credit expiry remains an explicit commercial gate.

- [ ] Write a failing/contract test that candidate pack amounts are 1,000/$15 and 2,000/$29 when present.
- [ ] Assert active=false by default.
- [ ] Assert POSTRIFF_CREDIT_PURCHASES_ENABLED off returns no purchasable packs.
- [ ] Assert setting the environment flag alone cannot sell an inactive pack.
- [ ] Preserve current verified checkout/refund/dispute/reversal mechanics.
- [ ] Add a test/guard that no purchased-credit expiry is invented by default.
- [ ] Run purchase lifecycle suite.
- [ ] Commit only if code changes are required: test(billing): lock inactive top-up contract

Acceptance:
- no accidental top-up launch.

---

## Task 11: Instrument the beta economics and retention evidence

**Files:**
- Prefer existing analytics/observation infrastructure; add the smallest schema only if current tables cannot represent the events.
- Modify relevant billing/analytics event code and tests.
- Do not introduce external analytics vendors solely for this task.

**Produces measurable events for:**
- price variant assignment.
- checkout started.
- checkout completed.
- first value completed.
- weekly content pack adopted.
- credits granted/held/settled/expired.
- platform-funded cost.
- absorbed-over-max cost.
- renewal paid.
- cancellation reason when available.

- [ ] Inspect current analytics/event/audit tables and reuse them where semantics fit.
- [ ] Write failing tests for stable price-variant attribution through checkout and renewal.
- [ ] Write failing test that cost telemetry separates user-settled credits from platform-funded/absorbed cost.
- [ ] Write failing test that experiment analytics contain no raw secret/payment data.
- [ ] Implement minimal events.
- [ ] Run GREEN.
- [ ] Commit: feat(analytics): measure pricing beta economics

Acceptance:
- the next pricing decision can be made from observed revenue, burn, use, retention, and support evidence rather than another guessed price.

---

## Task 12: Documentation, legal-copy consistency, and activation runbook

**Files:**
- Update usage/billing docs discovered in the current repo.
- Update relevant changelog/help copy.
- Create: docs/superpowers/handoffs/2026-09-28-rafii-pricing-credits-v2-release-runbook.md or equivalent release receipt path if project convention prefers another location.

**Produces:**
- operator runbook that separates code readiness from live commercial activation.
- Stripe test/live mapping checklist.
- migration order.
- rollback.
- smoke checks.

- [ ] Document the launch catalog and credit behavior.
- [ ] Document legacy grandfather behavior.
- [ ] Document that top-ups, Starter, Studio, annual, BYOK, and Creator trial are not launch-active.
- [ ] Run a copy search for contradictions across pricing/terms/help/auth.
- [ ] Write a release runbook with explicit gates:
  1. current canonical commit;
  2. migration checksum;
  3. Stripe test Price mapping;
  4. staging checkout/webhook smoke;
  5. live Price creation only after explicit authorization;
  6. production migration only after explicit authorization;
  7. feature flag activation;
  8. signed-in smoke;
  9. rollback switches.
- [ ] Do not execute live steps as part of this implementation plan.
- [ ] Commit: docs(billing): add pricing v2 activation runbook

---

## Task 13: Full verification and whole-branch review

**Files:** no new product scope.

- [ ] Run all Python unit tests required by the repo.
- [ ] Run the complete PostgreSQL test suite.
- [ ] Run web unit/contract tests.
- [ ] Run TypeScript no-emit/typecheck.
- [ ] Run lint.
- [ ] Run production web build.
- [ ] Run targeted pricing/billing browser scenes at mobile and desktop widths.
- [ ] Run secret scan according to repository release gate.
- [ ] Run migration prefix uniqueness check.
- [ ] Run a residual repository search for:
  - USD 19 / 39 new-sale copy;
  - Studio Assist new-sale copy;
  - writing batches/media credits in v2 customer surfaces;
  - inactive Starter/Studio checkout path;
  - client-controlled amount/price id.
- [ ] Use superpowers:verification-before-completion and record exact commands/results.
- [ ] Use superpowers:requesting-code-review / final whole-branch reviewer on the most capable available model.
- [ ] Fix Critical/Important findings with RED→GREEN tests.
- [ ] Record any deferred Minor findings explicitly.
- [ ] Do not merge/deploy merely because tests pass.

Final acceptance report must distinguish:
- LOCAL CODE: verified / failed.
- TEST STRIPE: verified / not run.
- PRODUCTION DB: not applied unless separately authorized.
- LIVE STRIPE PRICES: not created/activated unless separately authorized.
- PRODUCTION CHECKOUT: off unless separately authorized.
- LEGACY CUSTOMER MIGRATION: not performed.

## Execution ordering

Tasks 1–4 are sequential because they share billing schema and lifecycle interfaces.

After Task 6 establishes the stable API contract:
- Task 7 public marketing,
- Task 8 authenticated billing UI,
- Task 9 work-surface cleanup,
may be assigned to separate workers only if they use isolated branches/worktrees and do not edit the same shared files. Integrate them one at a time with fresh tests.

Task 10 can run after Task 2/6 because it is mostly isolated.

Task 11 depends on stable price assignment and credit settlement semantics.

Task 12/13 are last.

## Definition of done

This plan is done only when code and tests make the v2 model coherent across database, backend, Stripe test mode, frontend, and copy, while production commercial activation remains an explicit separate gate.

The target state is not “four plan cards are visible.” The target state is:
- Free proves first value safely;
- Creator is the only paid launch package;
- Creator has 3,500 credits regardless of beta price;
- credit settlement reflects real cost;
- legacy users keep working;
- every app surface tells the same pricing story;
- Rafii has telemetry to decide what to do next from evidence.
