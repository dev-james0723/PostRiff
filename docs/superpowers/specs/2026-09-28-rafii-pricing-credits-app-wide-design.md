# Rafii App-wide Pricing and Credit System v2 Engineering Specification

> Approved user amendment (2026-10-03): publicly include Starter US$29/month with 1,000 credits and Studio (`studio-v2`) US$149/month with 8,000 credits alongside Free and Creator. This supersedes the two-plan/hidden Starter and Studio visibility clauses below. Existing capacity quantities and legacy `studio-v1` US$19 terms remain unchanged. Visibility does not activate checkout, provider spend or production. All remaining Tasks 0–13 acceptance and funding restrictions continue to apply.

**Status:** Implementation-ready commercial-system specification. This document authorizes engineering design and implementation work only. It does not by itself authorize live Stripe price creation, activation of a paid plan in production, charging a customer, production database migration, or public launch.

**Date:** 2026-09-28

**Repository verified for this research pass:** /Users/ouxianxing/Documents/James-Au-Studio

**Verified branch / HEAD at inspection:** consumer-saas @ 468811b73d28b4389f931519827c05d0e6c8abfb

**Important workspace condition:** the canonical checkout was already dirty with unrelated in-progress work. Implementation must happen in an isolated worktree and must not overwrite or normalize the shared checkout.

## 1. Authority and source precedence

This specification is grounded in the following three launch-research documents, all read in full:

1. /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/pricing-strategy.zh-Hant.md
2. /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/growth-jev-analysis.zh-Hant.md
3. /Users/ouxianxing/Documents/Codex/2026-09-26/new-chat/outputs/rafii-launch-research/strategy.zh-Hant.md

The latest pricing research explicitly supersedes the old beta/core USD 29 / USD 39 model and the old USD 0.05-per-credit model. Earlier repository pricing is historical implementation context, not commercial authority.

The following installed local skills were applied to the design:
- product-brainstorming: separate user problem, business hypothesis, assumptions, and implementation decisions.
- product-quality-validator: require explicit target, contracts, evidence, failure recovery, and handoff readiness.
- improve-retention: minimize activation friction and avoid making users learn a billing abstraction before they see value.
- user-research: preserve the 15–20 paid-beta validation loop and renewal evidence.
- evidence-first-research-shortlist: separate sourced facts, calculations, assumptions, and recommendations.
- research / research-deep: preserve source traceability and uncertainty.
- artifact-readiness-and-handoff: define verification, rollback, external blockers, and handoff boundaries.
- stripe-best-practices: retain Stripe Billing + Checkout Sessions + verified webhooks; do not build a manual renewal system.
- superpowers brainstorming / writing-plans / TDD / worktrees / verification: treat this as an architectural migration, execute in isolation, test-first, and verify before completion.

## 2. Executive commercial decision

Rafii must stop presenting the current USD 19 Studio / USD 39 Studio Assist + writing-batches model as the future product.

The v2 commercial model is:

| Package | Monthly price | Managed credits | Launch visibility | Commercial role |
| --- | ---: | ---: | --- | --- |
| Free | USD 0 | 0 fungible managed credits | Public | First-value preview and evidence collection |
| Starter | USD 29 | 1,000 / month | Hidden at launch | Future lower-frequency tier if demand is proven |
| Creator | USD 59 default | 3,500 / month | Public launch paid plan | Primary paid-beta and launch package |
| Studio | USD 149 | 8,000 / month | Hidden at launch | Future multi-brand / small-team tier after validation |

Creator must support a paid-beta price experiment using the same package and the same 3,500-credit entitlement at USD 49, USD 59, and USD 79 per month. USD 59 is the default / center candidate. The experiment must vary price only, not features or credit quantity.

The mature four-tier catalog is a product model, not proof that all four tiers should be sold immediately. At initial v2 launch:
- Free and Creator are visible.
- Starter and Studio exist as hidden/proposed catalog entries.
- Starter and Studio cannot be checked out until explicitly activated later.
- No code or copy may claim that USD 59 is the proven optimal price.

## 3. What is sourced versus derived

### 3.1 Directly sourced commercial values

The following values come directly from the three research documents:
- Starter: USD 29, 1,000 managed credits.
- Creator: USD 59 center candidate, 3,500 managed credits.
- Creator price test: USD 49 / USD 59 / USD 79 for the same package.
- Studio: USD 149, 8,000 managed credits.
- Credit conversion: 300 credits = USD 1 of verified billable provider/tool cost.
- Top-up candidates: USD 15 for 1,000 credits; USD 29 for 2,000 credits.
- Annual pricing is deferred until renewal evidence; later candidate is approximately ten monthly payments: USD 290 / 590 / 1,490.
- Starter candidate limits: 1 brand, 1 seat, 3 connected accounts.
- Creator candidate limits: up to 2 brands, 1 seat, 6 connected accounts.
- Studio candidate limits: 3 brands, 3 seats, 10 connected accounts.
- No monthly-credit rollover by default.
- Quick research candidate ceiling: 120 credits only for a bounded, controlled retrieval path.
- Deep research candidate ceiling: 1,000 credits only when the requested data/tool route fits that ceiling.
- X standard read reference cost: USD 0.005 per resource, equivalent to 1.5 credits per new billable read before model/tool costs.
- Free should provide a strict preview rather than a broad recurring free writer allowance.
- Free Genome may analyze a recent 20-post set once; if metrics are unavailable, analyze writing only.
- Cheap base Post Doctor / Genome checks may be platform-funded instead of debiting user credits.
- Dedicated Radar retrieval and other expensive fresh-data operations must be quoted/capped.

### 3.2 Derived engineering decisions

These are implementation decisions made to turn the research into one coherent system. They are not claims that the research itself specified these exact mechanics:
- New v2 signups default to a persistent Free entitlement rather than simultaneously running a permanent Free tier and a full 14-day paid-plan trial.
- Existing 14-day trial workspaces are grandfathered until their current trial ends, then fall back to Free. A future 14-day Creator trial remains an experiment flag, off by default.
- Free gets one optional connected account maximum at launch, one brand/persona, and one seat. This is a conservative first-value default and must not be marketed as a validated willingness-to-pay boundary.
- Free has zero fungible managed credits. Its small number of free-value actions are platform-funded and separately rate-limited.
- The default Free first-value allowance is one platform-funded Post Doctor run plus one one-time recent-20 Genome import/analysis. Any recurring free allowance requires measured cost evidence before expansion.
- Storage is not a v2 pricing differentiator. Preserve current technical caps during migration rather than inventing a new storage price model: 200 MB for Free and 1 GB for paid tiers until storage economics are studied. Do not headline these values in pricing copy.
- Existing USD 19 / USD 39 subscribers remain grandfathered. They are removed from new-sale catalog visibility but their subscriptions are not silently repriced or upgraded.
- Creator price experimentation is separated from entitlements at the data-model level so a price test cannot accidentally change product capability.

## 4. Product promise and pricing UX

Pricing must sell the outcome first:
- turn the user's own material into usable content;
- review it in the user's voice;
- learn from accepted/rejected edits;
- help prepare next week's content;
- continuously improve decisions from real results.

Do not lead with “AI calls,” “writing batches,” model names, or abstract token consumption.

Credits are a cost-control layer, not the product story. The user should understand:
1. what the task will do;
2. the typical credit estimate where available;
3. the maximum credit amount being authorized;
4. that Rafii never silently exceeds the approved maximum;
5. the actual settled amount after completion;
6. that failed operations release the user reservation;
7. that unknown provider usage stays pending rather than being treated as zero.

## 5. Credit accounting contract

### 5.1 Conversion

Keep the verified-cost mapping:

credits = verified billable cost in USD × 300

Display resolution remains 0.1 credit. Round once at the task boundary, not once per provider hop.

Equivalent implementation formula for a completed managed task:

displayCredits = ceil(actualUsd × 300 × 10) / 10

Internally continue using millicredits for exact ledger accounting.

### 5.2 What counts toward a managed-credit task

A task-level cost may include:
- model input/output;
- paid search;
- paid data retrieval;
- billable provider tools;
- Gateway reporting or identity fees when the chosen route requires them;
- media generation;
- other explicitly policy-billable task components.

A task must not count the same provider cost twice. If upstream reports overlapping cost fields such as cost, marketCost, or gatewayCost, the adapter must normalize them into non-overlapping components before settlement.

### 5.3 Reserve / settle / release

Preserve the existing immutable ledger model:
- Quote: calculate an auditable typical estimate when possible and a conservative maximum.
- Authorize: bind the approved maximum to request digest, workspace revision, provider/model route, policy version, actor, and expiry.
- Reserve: atomically hold the maximum against available credits before external paid I/O.
- Settle completed: charge actual verified cost, rounded once at task level.
- Release failed: user credit charge is zero and the held amount is released. Actual provider loss still remains in the platform cost ledger.
- Unknown: keep the reservation pending until provider evidence is reconciled.
- Actual cost above the approved maximum: do not debit extra user credits. Record the excess as platform-absorbed cost and flag it for cost review.
- Concurrency: parallel reservations must not overspend one wallet.
- Idempotency: a retried request cannot reserve or settle twice.

### 5.4 Monthly credit grants

For credit-based paid plans:
- A verified paid subscription_create or subscription_cycle invoice grants the package monthly credits once per invoice.
- Subscription credits expire at the current paid period end.
- No automatic rollover at launch.
- Upgrades/downgrades must never double-grant the same paid period.
- Refund/dispute reversal uses the existing immutable credit-lot mechanics.
- Existing grandfathered legacy plans keep their current allowance behavior until intentionally migrated.

### 5.5 Purchased credit lots

Prepare but do not launch by default:
- 1,000 credits for USD 15.
- 2,000 credits for USD 29.

Rows may exist inactive in pr_credit_packs. POSTRIFF_CREDIT_PURCHASES_ENABLED remains off for initial v2 launch.

Purchased-credit expiry is not specified by the research. Therefore purchased packs must not be activated until a separate commercial decision defines expiry and refund behavior. Do not invent an expiry silently in code.

## 6. Credit allocation by activity

### 6.1 Platform-funded, zero user-credit activities

The following may be paid by a separately approved platform budget instead of user credits:
- the one Free first-value Post Doctor run;
- the Free one-time recent-20 Genome analysis;
- cheap base Post Doctor rubric checks on paid tiers when designated by policy;
- cheap scheduled Genome refreshes when designated by policy;
- deterministic/local calculations;
- operations whose verified provider cost is zero.

These still write cost telemetry when provider cost exists. “Free to the user” must never mean “unmeasured to Rafii.”

### 6.2 Managed writing / rewrite / edit

Do not create a flat “one writing batch” charge.

For managed writer operations:
- quote from the exact configured model/tool price basis;
- reserve a maximum;
- settle actual cost;
- charge 300 credits per verified USD, task-rounded once;
- show the user a task estimate / maximum in credits, not a fictional fixed number of posts.

If a typical rewrite costs USD 0.013 under a measured route, that example would settle around 3.9 credits. It is an example, not a contractual fixed price.

### 6.3 Quick research

Use 120 credits only as a default maximum candidate when:
- the request uses a controlled shared/public pool or otherwise bounded data retrieval;
- the projected billable components fit within 120;
- there is no silent paid expansion of sources.

If a requested route needs more, return a revised quote before paid I/O.

### 6.4 Deep research

Use 1,000 credits only as a default maximum candidate when the full source/tool plan fits.

The research already shows plausible Deep routes above 1,000 credits once reporting/ZDR/data fees are added. Therefore:
- calculate the route before execution;
- if estimated maximum > 1,000, show the real higher maximum and require explicit approval;
- never silently downgrade source quality or silently exceed the approved limit.

### 6.5 Dedicated Radar / fresh data

Dedicated fresh retrieval is not “included unlimited.”

For X standard reads, the reference retrieval component is:
- USD 0.005 per newly billable resource;
- 1.5 credits per newly billable X read;
- plus the task's model/tool/reporting components.

Respect provider de-duplication rules. Shared public-pool cost may only be allocated among actual beneficiaries. Personalized and dedicated scans are separate budget classes.

### 6.6 Images, video, and other media

Use the same quote/reserve/settle flow based on exact configured provider cost. Do not use the old separate “media credit” abstraction for v2 plans.

Legacy mediaCreditsRemaining remains only for grandfathered plans until removal is safe.

## 7. Package entitlement model

### 7.1 Free

Public:
- USD 0.
- 0 fungible managed credits.
- one brand/persona.
- one seat.
- up to one connected account as a conservative derived launch default.
- one platform-funded first-value Post Doctor run.
- one one-time recent-20 Genome import/analysis.
- no automatic paid model overage.
- export, privacy controls, edit/delete, and approved library/skill access remain available and are never premium-gated merely for safety/privacy reasons.

Operational compatibility:
- writingBatches = 0.
- mediaCredits = 0.
- storageMb = 200 until storage economics are revised.
- no creditPolicy field, because Free does not receive a spendable wallet.

### 7.2 Starter

Hidden/proposed at launch:
- USD 29 / month.
- 1,000 managed credits per paid period.
- 1 brand.
- 1 seat.
- 3 connected accounts candidate.
- current paid technical storage cap retained temporarily.
- outcome workflow stays complete, not a crippled BYOK/CLI shell.

### 7.3 Creator

Primary launch paid package:
- default USD 59 / month;
- same-entitlement beta price variants USD 49 / 59 / 79;
- 3,500 managed credits per paid period;
- up to 2 brands candidate;
- 1 seat;
- up to 6 connected accounts candidate;
- higher tracking/review frequency than Free;
- periodic review and approved learning;
- periodic Audience Miner when available;
- future Radar light/shared summary may be bundled, while dedicated fresh scans remain quoted.

### 7.4 Studio

Hidden/proposed at launch:
- USD 149 / month.
- 8,000 managed credits.
- 3 brands.
- 3 seats.
- 10 connected accounts candidate.
- brand separation and higher operational capacity.
- dedicated always-on retrieval is not unlimited and remains separately controlled/quoted.

### 7.5 Not yet enforceable as commercial promises

Candidate tracking limits such as 12 / 60 / 180 active posts per month are not activated until real API/job cost evidence supports them.

Do not display or enforce them as final plan truth in v2 launch.

## 8. Legacy-to-v2 migration policy

### 8.1 Current legacy catalog

Current code was verified to expose:
- Studio, studio-v1, USD 19.
- Studio Assist, assist-v1, USD 39.
- legacy 14-day trial with 10 writing batches and 1 media credit.

These values appear across marketing, auth, terms, account billing, allowances, Ideas/Overview, API types, SQL plan terms, and tests.

### 8.2 Existing customers

No silent migration:
- Existing active legacy paid subscriptions keep their Stripe price and current legacy entitlement mechanics.
- They remain readable in billing and webhook reconciliation.
- They are hidden from new-sale surfaces.
- No renewal price is changed by the v2 migration.
- A later explicit migration offer may move them to v2; that is out of scope.

### 8.3 Existing trials

- Existing unexpired trial-v1 workspaces continue until current expiry.
- At expiry, when v2 is enabled, they fall back to Free rather than losing all draft/export access.
- Do not auto-convert to paid Creator.
- A Creator trial experiment may be implemented behind a separate disabled flag but is not part of default launch behavior.

### 8.4 New workspaces

With pricing v2 enabled:
- assign Free entitlement on first use;
- do not create a new trial-v1 subscription;
- preserve drafts/exports after any paid subscription later ends, with Free capability restored.

## 9. Data model changes

The current migration sequence on inspected HEAD ends at 022. The implementation worker should use the next free migration prefix after rechecking the actual integration base. At the inspected HEAD the candidate filename is:

migrations/postriff/023_pricing_credit_catalog_v2.sql

If another merged branch has already claimed 023, renumber this migration before writing it. Never create duplicate numeric migration prefixes.

### 9.1 Expand plan identities

Replace the old pr_plan_terms plan CHECK so existing and v2 values can coexist:
- trial
- free
- starter
- creator
- studio
- assist

Do not rewrite historical rows.

### 9.2 Separate catalog visibility from billing status

Add:
- catalog_state: public | hidden | legacy.
- new_checkout_enabled: boolean, default false.

Existing legacy Studio/Assist rows become catalog_state=legacy and new_checkout_enabled=false without changing their active subscription behavior.

New plan terms:
- free-v1, plan=free, active, public, price 0.
- starter-v1, plan=starter, proposed, hidden, price 2900.
- creator-v1, plan=creator, proposed until commercial activation, public, base display price 5900.
- studio-v2, plan=studio, proposed, hidden, price 14900.

Suggested entitlement JSON:
- free-v1: members 1, connectedAccounts 1, brands 1, writingBatches 0, mediaCredits 0, storageMb 200, overage stop.
- starter-v1: members 1, connectedAccounts 3, brands 1, writingBatches 0, mediaCredits 0, storageMb 1000, creditPolicy v2, monthlyCredits 1000, overage stop.
- creator-v1: members 1, connectedAccounts 6, brands 2, writingBatches 0, mediaCredits 0, storageMb 1000, creditPolicy v2, monthlyCredits 3500, overage stop.
- studio-v2: members 3, connectedAccounts 10, brands 3, writingBatches 0, mediaCredits 0, storageMb 1000, creditPolicy v2, monthlyCredits 8000, overage stop.

The legacy writing/media keys remain zero-valued compatibility fields until entitlement storage is generalized. Credit plans must spend through the credit wallet path, not these fields.

### 9.3 Price variants

Do not encode the Creator willingness-to-pay test as three different entitlement packages.

Add pr_plan_price_variants:
- id text primary key;
- plan_terms_id FK;
- variant_key;
- amount_cents;
- currency;
- provider_price_id nullable;
- status proposed | active | retired;
- experiment_key nullable;
- created_at;
- unique(plan_terms_id, variant_key).

Seed proposed variants:
- creator-49-v1 = 4900 cents.
- creator-59-v1 = 5900 cents, default.
- creator-79-v1 = 7900 cents.

### 9.4 Stable beta assignment

Add pr_price_experiment_assignments:
- workspace_id;
- experiment_key;
- price_variant_id;
- assigned_at;
- assignment_source;
- unique(workspace_id, experiment_key).

The assignment is immutable once checkout has been offered for that experiment. A workspace must not see USD 49 today and USD 79 tomorrow because of a cookie reset or deploy.

Default behavior when the experiment is off: Creator uses creator-59-v1.

Beta experiment behavior when enabled: eligible new paid-beta workspaces receive a stable 49/59/79 assignment. Existing subscribers are excluded.

### 9.5 Persist the paid price

Add nullable price_variant_id to pr_subscriptions.

Stripe metadata for new v2 subscriptions must include:
- workspace_id;
- plan_terms_id;
- price_variant_id.

Webhook reconciliation must recover the variant from verified metadata or the verified provider price id. Never trust a client-supplied amount.

## 10. Credit policy versioning

Do not silently repurpose the existing credits-candidate-2026-09-23-v1 label as “production.”

Introduce an explicit v2 policy identifier while preserving the old candidate constant for old fixtures/history, for example:
- credits-v2-2026-09-28

The exact identifier is internal, but it must be immutable once plan terms using it are activated.

Keep:
- CREDITS_PER_USD = 300.
- millicredit ledger.
- one task-level rounding boundary.
- quote binding.
- immutable grants/reservations/settlements.
- debt handling for reversed paid credit lots.

## 11. Billing backend changes

### 11.1 Current behavior to preserve

The existing backend already provides:
- immutable pr_usage_ledger;
- reserve / settle / release;
- budget stop lines;
- CreditBook wallet projection;
- quote authorization;
- paid invoice monthly-credit grants;
- one-time credit-purchase scaffolding;
- Stripe Checkout Sessions;
- verified webhook signatures;
- replay/out-of-order handling;
- billing portal;
- current subscription / entitlement lifecycle.

Reuse these systems.

### 11.2 Required changes

src/postriff_phase2/billing.py:
- support Free as the default v2 pre-subscription entitlement.
- return v2 credit balance and monthly total to the UI.
- stop describing credit-plan workspaces primarily through writingBatchesRemaining/mediaCreditsRemaining.
- grant monthly credits from paid verified invoices exactly once.
- preserve legacy allowance paths for legacy terms.
- restore Free after paid cancellation/expiry when v2 is enabled.
- include price variant in subscription view.
- expose only catalog-appropriate terms to normal plan selection while preserving historical current terms.

src/postriff_phase2/credit_meter.py:
- add explicit v2 policy version while retaining the 300/USD formula.
- keep task-level rounding and auditable price basis.

src/postriff_phase2/credit_wallet.py:
- preserve lots, holds, debt, quote binding, and idempotency.
- expose monthly grant total / expiry needed for the usage meter without fabricating totals.
- never spend beyond approved maximum.

src/postriff_phase2/hosted.py:
- checkout resolves a server-authorized plan + price variant.
- client sends plan intent, not amount.
- legacy checkout stays disabled for new sales.
- v2 price assignment is stable.
- credit packs remain unavailable when purchase flag is off.

src/postriff_phase2/billing_stripe.py:
- continue subscription Checkout Sessions and Billing Portal.
- include price_variant_id metadata.
- parse and reconcile verified price ids.
- keep dynamic payment methods; do not hardcode payment_method_types.
- use environment-appropriate restricted Stripe keys where operationally possible.

## 12. Public and authenticated API contracts

### 12.1 Plan catalog

The application needs a sanitized catalog projection that distinguishes:
- public package;
- hidden package;
- legacy current package;
- default price;
- effective assigned price for the current workspace;
- managed monthly credits;
- connected account / seat / brand limits;
- whether checkout is currently enabled.

Do not expose Stripe secret keys, webhook secrets, or internal raw cost budgets.

### 12.2 Usage response

For a v2 credit plan, Usage must expose:
- credit policy id;
- availableMilliCredits;
- heldMilliCredits;
- usedMilliCredits;
- debtMilliCredits;
- periodGrantMilliCredits or another evidence-backed total for the current subscription period;
- current subscription-credit expiry/reset time;
- current package id/label;
- effective price variant where relevant.

For legacy plans, keep the old writing/media allowance fields until the legacy UI path is retired.

The frontend must branch by billing mode:
- mode=legacy_allowances;
- mode=managed_credits;
- mode=free_preview.

Do not infer mode from a price number.

## 13. Frontend and copy migration

App-wide means every customer-visible pricing/allowance reference must be audited.

### 13.1 Public marketing

Update:
- web/src/app/(marketing)/pricing/page.tsx
- web/src/components/marketing/landing/sections.tsx
- web/src/components/marketing/plan-card.tsx
- web/src/components/marketing/json-ld.tsx
- web/src/config/plans.ts or its replacement
- web/src/app/(marketing)/terms/page.tsx
- web/src/components/auth/auth-form.tsx
- any docs / FAQ / email copy that claims the old trial or writing-batch system.

Launch pricing page:
- Free and Creator cards only.
- Creator default public reference price USD 59/month.
- Copy must say pricing is being validated / beta where appropriate, not “proven.”
- Do not display Starter/Studio as purchasable at launch.
- A separate “future / teams” explanation may mention that larger plans are being validated only if product wants it; no dead checkout buttons.
- Remove “Two plans” legacy copy.
- Remove “AI writing batches/month” as the v2 headline metric.
- Explain managed credits in one compact FAQ after outcomes, not before them.

### 13.2 Signup and onboarding

Remove automatic “USD X/mo after trial” assumptions for new v2 Free users.

Signup should promise:
- start free;
- no card;
- see value before connecting everything;
- choose Creator when ongoing managed usage is valuable.

### 13.3 Account Billing / Usage

Update:
- web/src/features/billing/billing-model.ts
- web/src/features/billing/billing-copy.ts
- web/src/features/billing/plans.tsx
- web/src/features/billing/allowances.tsx
- web/src/features/billing/plan-card.tsx
- web/src/features/billing/credit-packs.tsx
- web/src/features/billing/billing-view.tsx
- web/src/lib/api/types.ts
- web/src/lib/api/client.ts

For v2 Creator:
- show Creator and the workspace's exact monthly price;
- show managed credits left of period grant;
- show held credits separately when nonzero;
- show reset/expiry date;
- state “No silent overage”;
- keep owner-only provider-cost diagnostics separate from customer credit balances;
- hide old writing-batch and media-credit meters.

For Free:
- show “Free preview” and the remaining preview actions where measurable;
- do not show 0 / 0 credits as a broken meter;
- offer Creator at the effective assigned beta price only after assignment.

For legacy:
- retain current allowance meters and current-price receipt;
- label as legacy/grandfathered when appropriate;
- no new purchase button for a legacy package.

### 13.4 Ideas / Overview / Writing surfaces

Audit and update current references found in:
- web/src/features/account/models/writing-now.tsx
- web/src/features/ideas/capture-card.tsx
- web/src/features/ideas/ideas-view.tsx
- web/src/features/overview/overview-view.tsx

V2 users should see task credit status/quote, not “writing batches remaining.”

Legacy users may continue to see legacy batch language until migrated.

## 14. Free first-value path

The product strategy says first value should arrive quickly and should not require full network setup.

When v2 is enabled, Free onboarding should support:
1. choose monthly promotion/content goal;
2. paste or upload own source material / examples;
3. confirm a small number of voice/preferences;
4. run one platform-funded Post Doctor first-value analysis;
5. optionally import/analyze up to a recent-20 set once;
6. create/revise/save a first useful content result;
7. only then ask for broader connection / Creator upgrade where valuable.

The Free route must have a separate server-side budget and rate-limit boundary. If the platform-funded budget is not approved, refuse before paid provider I/O rather than silently shifting cost to user credits.

## 15. Price experiment design

The pricing research calls for one package tested at USD 49 / 59 / 79.

The experiment must therefore hold constant:
- Creator feature set;
- monthly credits = 3,500;
- account/brand/seat limits;
- onboarding;
- support promise;
- billing interval.

Measure:
- qualified prospect → paid beta conversion;
- activation to first value;
- second-week core workflow usage;
- week-4 retained core use;
- credit burn distribution;
- support minutes per active customer;
- gross contribution after actual managed cost;
- first renewal;
- second renewal;
- cancellation reason.

Do not use tiny sample differences as proof. The 15–20 paid beta is an evidence-gathering cohort, not a statistically conclusive broad-market experiment.

Once a customer subscribes, preserve their billed price until an explicit price-change policy applies. Never re-randomize on renewal.

## 16. Unit economics telemetry

Track per workspace / plan / price variant:
- subscription revenue;
- granted credits;
- held credits;
- settled credits;
- expired subscription credits;
- purchased credits separately;
- actual provider/tool USD;
- platform-funded Free/Post Doctor/Genome cost;
- absorbed-over-max cost;
- failed-provider cost;
- unknown/unreconciled reservations;
- support time if operational system can record it;
- payment processing fees where available;
- data retrieval volume by provider/pool class.

The research's margin figures are planning calculations, not product guarantees. Engineering must produce the measurements needed to replace assumptions with real cohort economics.

## 17. Safety and failure behavior

Required:
- no paid provider call before budget/credit authority.
- no silent overage.
- no silent model/provider swap that changes cost basis.
- no treating unknown usage as zero.
- no double charge on retries/webhook replay.
- no customer debit for failed provider operation.
- no cross-workspace credit allocation.
- no exposure of raw Stripe secrets or private cost internals to non-owner users.
- no client-authoritative price or credit grant.
- no hidden activation of Starter/Studio/top-ups.
- no automatic repricing of legacy subscribers.
- no production activation just because the migration exists.

A migration can create proposed rows safely; activation requires an explicit operational step with provider price ids and production verification.

## 18. Stripe operational design

Keep:
- Billing APIs for recurring subscriptions.
- Checkout Sessions for subscription purchase and one-time credit packs.
- Billing Portal for payment method / cancellation / supported changes.
- verified webhook signatures.
- idempotent event handling.

Operational hardening:
- use restricted API keys with least privilege where possible.
- separate test/live keys.
- never commit keys.
- never log secrets.
- preserve live/test environment matching.
- keep payment methods dynamic; do not hardcode payment_method_types.
- activate Creator only after its live Stripe Price mapping is verified.
- top-up Price ids may be provisioned later but pr_credit_packs.active remains false until the separate pack-activation gate.

## 19. Rollout gates

### Phase A — code and data model, all commercial activation off
- additive migration;
- v2 plan terms proposed/hidden as required;
- Free assignment logic behind POSTRIFF_PRICING_V2_ENABLED;
- v2 credit policy;
- price variant tables;
- frontend dual-mode support;
- tests.

### Phase B — staging / test Stripe
- enable pricing v2 in staging;
- keep purchase packs off;
- Creator test prices mapped to Stripe test Price ids;
- exercise 49/59/79 assignment;
- verify invoice monthly-credit grant;
- verify cancellation returns to Free;
- verify legacy subscription remains intact.

### Phase C — paid beta
Requires explicit founder/commercial activation:
- create/verify live Creator Stripe Prices;
- activate creator-v1 and allowed variants;
- set new_checkout_enabled only for Creator;
- enable invited beta experiment;
- keep Starter/Studio hidden;
- keep top-ups off initially;
- monitor costs and support.

### Phase D — evidence-driven expansion
Only after measured use:
- decide whether Starter is needed;
- decide whether Studio is needed;
- decide top-up activation and purchased-credit expiry;
- decide annual billing after at least two renewal cycles;
- decide any tracking limits;
- decide Radar bundles.

## 20. Rollback

Rollback must be operational, not destructive:
- turn POSTRIFF_PRICING_V2_ENABLED off for new assignment/checkout;
- turn Creator new checkout off;
- retain all v2 rows and ledger events for audit;
- do not drop migrations or delete paid subscription history;
- existing v2 subscribers continue to reconcile verified Stripe events even if new sales are disabled;
- Free fallback and exports remain available;
- restore public marketing to a non-purchasable waitlist state if checkout is disabled.

## 21. Test matrix

Minimum automated coverage:

Data / migration:
- migration applies on fresh database;
- migration applies after legacy rows;
- migration is replay-safe according to project convention;
- plan CHECK accepts legacy + v2 values;
- legacy rows remain unchanged except catalog visibility/new-sale flag;
- v2 values exactly match this specification.

Credits:
- 300 credits/USD conversion;
- one rounding per task;
- parallel reserve cannot overspend;
- failed run releases user credits;
- unknown stays held;
- actual > max is absorbed, not debited;
- invoice grants once;
- duplicate invoice does not double-grant;
- monthly grant expires at period end;
- cancellation does not destroy history;
- credit-policy mismatch refuses before provider call.

Pricing:
- Creator price variants all share creator-v1 entitlements;
- stable assignment across requests;
- default is USD 59 when experiment off;
- client cannot choose a different amount;
- legacy price is not offered to new customer;
- hidden Starter/Studio cannot checkout;
- price variant stored on subscription.

Free:
- new v2 workspace gets Free, not trial-v1;
- Free paid-provider call requires platform-funded policy/budget;
- one first-value Post Doctor cap;
- one recent-20 Genome cap;
- no fungible Free credits;
- expired grandfathered trial falls to Free.

Stripe:
- test-mode Checkout uses assigned variant price id;
- metadata includes workspace/terms/variant;
- webhook signature/livemode checks remain;
- price-id resolution cannot cross package;
- invoice grants 3,500 Creator credits once;
- portal still works.

Frontend:
- public page shows Free + Creator only;
- USD 19 / USD 39 absent from new-sale pages;
- “writing batches” absent for v2;
- legacy account still renders its legacy allowance;
- Creator shows credit meter/reset/held state;
- Free does not render 0/0 broken credit bar;
- hidden plans have no checkout CTA;
- signup no longer promises automatic “after trial” pricing;
- JSON-LD reflects only currently public sellable/default offer truthfully.

Regression:
- auth, OAuth, publishing permissions, export/delete, billing portal, subscription webhook and existing ledger behavior remain intact.

## 22. Acceptance criteria

Engineering work is complete only when fresh evidence proves all of the following:
1. One canonical v2 package/price/credit contract exists in code and database tests.
2. New-sale UI no longer presents USD 19 / USD 39 legacy pricing.
3. Launch UI presents Free + Creator; Starter/Studio are hidden and non-purchasable.
4. Creator defaults to USD 59 and supports stable USD 49/59/79 paid-beta variants without changing entitlements.
5. Creator monthly grant is exactly 3,500 credits on one verified paid period invoice.
6. 300 credits/USD remains the cost conversion and settlement is actual-cost based.
7. Free has zero fungible credits and cannot create an uncontrolled recurring model-cost tail.
8. Existing legacy subscriptions continue to reconcile and are not silently repriced.
9. New v2 workspaces use Free instead of legacy trial by default.
10. Every old writing-batch customer-facing surface is either migrated for v2 or intentionally preserved only for legacy mode.
11. Stripe test checkout/webhook/portal flows pass.
12. Backend unit/PostgreSQL tests, web tests, typecheck, lint, build, and targeted browser billing/pricing scenes pass.
13. No production Price, plan activation, migration, or real charge occurs without the explicit operational go-live gate.

## 23. File map for implementation

Expected high-impact files include, but are not limited to:

Database:
- migrations/postriff/023_pricing_credit_catalog_v2.sql or next-free renumbered equivalent.
- migrations/postriff/hosted-004-008.sql only if the worker verifies this bundled bootstrap snapshot must mirror the new schema; do not edit it mechanically without understanding its deployment role.

Backend:
- src/postriff_phase2/billing.py
- src/postriff_phase2/billing_stripe.py
- src/postriff_phase2/credit_meter.py
- src/postriff_phase2/credit_wallet.py
- src/postriff_phase2/credit_purchases.py
- src/postriff_phase2/hosted.py
- src/postriff_phase2/hosted_app.py
- relevant workspace creation/lifecycle code discovered during implementation.

Frontend:
- web/src/config/plans.ts or its v2 replacement.
- web/src/app/(marketing)/pricing/page.tsx
- web/src/app/(marketing)/terms/page.tsx
- web/src/components/marketing/landing/sections.tsx
- web/src/components/marketing/plan-card.tsx
- web/src/components/marketing/json-ld.tsx
- web/src/components/auth/auth-form.tsx
- web/src/features/billing/*
- web/src/features/account/models/writing-now.tsx
- web/src/features/ideas/capture-card.tsx
- web/src/features/ideas/ideas-view.tsx
- web/src/features/overview/overview-view.tsx
- web/src/lib/api/types.ts
- web/src/lib/api/client.ts

Tests:
- tests/test_postriff_billing.py
- tests/test_postriff_stripe.py
- tests/phase2/postgres_billing.py
- tests/phase2/postgres_billing_stripe.py
- tests/phase2/postgres_credits.py
- tests/phase2/postgres_final_monthly_credits.py
- tests/phase2/postgres_credit_purchases.py
- targeted web billing/pricing/model tests and browser scenes.

## 24. Out of scope

This pricing migration does not authorize:
- turning every Growth v3 module on;
- promising follower/view growth;
- selling Radar as unlimited;
- enabling unsupported social provider capabilities;
- changing publishing/OAuth policy gates;
- annual billing launch;
- lifetime plans;
- automatic unlimited top-up;
- BYOK commercial launch;
- a new support SLA;
- a new tax/legal policy;
- live production charging merely because code is ready.

## 25. Final engineering principle

The v2 system must make one distinction very clear:

**Package price answers “what ongoing Rafii relationship am I buying?”  
Credits answer “how much managed paid-compute/data work may Rafii spend for me this period?”**

Those two concepts must remain separate in the data model, Stripe mapping, UI, analytics, and experiments. That separation is what allows Rafii to test USD 49 / 59 / 79 fairly, preserve 3,500 Creator credits, and learn whether the market values the workflow without corrupting the result with different feature bundles.
