# Rafii Stripe sandbox integration — 2026-10-03

Execution state: sandbox provisioning begun; end-to-end acceptance has not passed.
Two test Products/Prices and a restricted-feature test Portal configuration were
created. No Preview deployment, database migration/mapping, webhook endpoint,
Checkout or Test Clock execution has occurred. Production remains untouched.

## Authority and target

Continue task `01a0eed5-21ae-7133-9130-582baa299489` from the reviewed pricing
checkpoint `f3a1135050f013652454f5fc7ae602016f7d03da`. Tasks 0–13 and their original
local evidence remain preserved in the pricing recovery worktree. They certify
their original inputs, not real Stripe behavior or this new integrated source.
This sandbox phase supersedes the older runbook's pending Task 13 status and its
Creator-first activation instructions. It does not reopen those tasks.

The sole Vercel target is `jamesau0723-6572s-projects/postriff-phase2-private`,
project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team
`team_PgXY5VdAYKcsv0RLoDPHscNq`. The production alias is
`https://postriff-phase2-private.vercel.app`. The resumed run used the authenticated Vercel CLI identity
`jamesau0723-6572` to resolve the alias to READY production deployment
`dpl_4kAyhPLDxLXnN9BfuwpgymMrVBoZ`, `consumer-saas` source
`72a2eef0c10facf98e63c68a5c84f898b5866071`. The preserved checkpoint
`c8165ec5ca0a9955db424d2a055152981dc612f5` first integrated production
`5c477be05e4712fca200c1c9f49ebc1d10393946` in `cfea24f7`, then incorporated
the subsequent `72a2eef0` production change. The latest project deployment can be a
Preview; use the production alias to resolve production lineage.

The Phone Call Repair receipt (2026-09-27), Growth Loop release receipt, launch
checklist and later Founder release receipts establish this canonical project
and the existing Supabase production reference `buoyhkbodnhzngaotoel`. Individual environment reads confirm that Production web/server Supabase URLs
bind to that production reference. The existing unbranched Preview URLs bind to
`oxacvkhpfgytkepxcaqh`, the excluded `rafii-consumer-staging` Supabase project.
Do not use that database for this activation.
The older Phone Mode setup receipt and `rafii-consumer-staging` are not deployment
authority for this task. Do not modify or deploy to that separate project.

The latest user instruction expressly authorizes authenticated Vercel CLI/API
as the fallback for the connector's continuing `projectEnvVars:list` 403. CLI
list/read checks pass against the exact canonical project/team IDs. Do not repair
or re-consent the connector again. Use explicit `--project` and `--scope` for CLI
actions; never blind-link this worktree. Production writes remain unauthorized.

The Stripe connector now exposes context `acct_1QYChoJZl100kP8e`, name
`d-festival.org`, with a separate selectable `livemode=false` context. All Stripe
calls in this activation use `livemode=false`; the live context is untouched.
Initial test Products, Prices, webhook endpoints and Portal configurations were
empty. James completed Chrome sign-in, and browser access recovered. An existing
standard test key was read without emitting its value. Direct Stripe API reads
verified the exact account, balance `livemode=false` and both approved Prices.
No restricted key exists in the sandbox; no new security grant was created.
Runtime key storage and isolated database cost approval remain pending.

## Integration and schema

The preserved isolated worktree first merged the reviewed pricing checkpoint
with production `7156703b`, producing `c8165ec5`. The resumed integration merges
production `5c477be0` into that checkpoint, preserving both parents and resolving
three conflicts explicitly. The subsequent production `72a2eef0` merge resolves
two conflicts by preserving both current Growth reading states and pricing Usage
integration, plus the isolated PostgreSQL fixture admission checks. No pricing
task is reimplemented. Conflicts preserve current
Founder Ops entitlement, spending telemetry, billing records, notification
cutover and current Next.js 16.3.8 alongside pricing/credit behavior. No reset,
clean, stash, blind cherry-pick or production database write is part of this work.

Production source already contains migrations through 088. The four undeployed
pricing migrations are appended after that chain, with byte-identical SQL bodies:

| Original reviewed filename | Integrated filename | SHA-256 |
| --- | --- | --- |
| 048_pricing_credit_catalog_v2.sql | 089_pricing_credit_catalog_v2.sql | a36357deb034fa32faac10ac9c893d5b09087f01c9689e072e8764adef792ba0 |
| 050_free_lifecycle_bootstrap.sql | 090_free_lifecycle_bootstrap.sql | f9aad0a010d8cb1205ed029112be5703c10631870ae3db09076e938b2fbb1e7d |
| 051_pricing_public_four_plans.sql | 091_pricing_public_four_plans.sql | aea8276b95b5edf6f280eea2234df63503e32ef46663421091e15a489e8ce2fb |
| 052_fixed_plan_checkout_approval.sql | 092_fixed_plan_checkout_approval.sql | 208071b872f5db5167f56839a2e8b7aac8be29d61b837feaf7e77b41ada5114a |

All canonical migration files remain byte-identical. A read-only production
query verified all 57 entries in `postriff_private.schema_migrations`, ending at
`088_founder_activation_integrity.sql`, against exact local SHA-256 values.
The Supabase native journal contains only 088 and does not represent the whole
application migration chain. The `5c477be0` to `72a2eef0` delta adds no migrations.
First verify the isolated target's
actual migration journal and checksums. Never replay historical production
migrations or replace them with the test baseline. Only an isolated Preview
database may receive sandbox migrations in this phase. Production migration
authority has not been granted by the sandbox request.

## Preview configuration and sandbox provisioning

Use Preview in the canonical Vercel project. Preserve Production credentials and
flags. Before any write, inspect variable names, target scopes, branch overrides
and the current database/auth binding without printing secret values. Preview
must use a distinct, verified Supabase test/branch reference for both database
and auth. It must not point to `buoyhkbodnhzngaotoel`; the existing secret-hash
isolation checks must pass. Record that relationship explicitly. Never infer
isolation from a Preview URL or healthy HTTP response alone.

Branch-scoped Preview settings remain pending isolated database identity and
secret-hash verification. No environment value has been changed by this phase.
Vercel rejected the initial branch-specific writes with HTTP 400 because the
branch was not yet present in the connected Git repository; this is not an
environment-variable permission denial. Before publishing the branch,
`vercel.json` disables automatic Git deployment for this exact sandbox branch.
Explicit canonical Preview deployment remains a later action after isolation
and credential checks pass. No shared project or Production setting is changed.
Use branch `codex/rafii-stripe-sandbox-20261003` and preserve shared Preview values:

Candidate Preview settings:

```text
POSTRIFF_ENVIRONMENT=staging
POSTRIFF_PRICING_V2_ENABLED=1
POSTRIFF_CREDITS_ENABLED=1
POSTRIFF_CREDIT_PURCHASES_ENABLED=0
POSTRIFF_CREATOR_PRICE_EXPERIMENT_ENABLED=0
POSTRIFF_CREATOR_PRICE_EXPERIMENT_COHORT=
POSTRIFF_STRIPE_API_VERSION=2026-08-26.dahlia
```

Set the approved Preview origin, distinct pinned Supabase references, matching
TLS database/auth URLs and `POSTRIFF_STAGING_SECRET_SHA256` only after inspecting
the actual configuration. Bind every configured staging credential to its real
SHA-256. Keep unrelated provider, notification, phone, research and model egress
off under the existing isolation policy. Do not reuse a Production key or hash.

Provision only two active sandbox monthly USD recurring Prices:

| Plan terms | Monthly amount | Monthly credit grant |
| --- | --- | --- |
| starter-v1 | USD 29.00 | 1,000 |
| studio-v2 | USD 149.00 | 8,000 |


Verified test resources created during the resumed run:

| Plan terms | Product ID | Price ID | Mode |
| --- | --- | --- | --- |
| starter-v1 | prod_VNQyTtOX80l3ib | price_1UMg6XJZl100kP8eIdHGr0US | livemode=false |
| studio-v2 | prod_VNQyJNeWhzGQmt | price_1UMg70JZl100kP8eR77h5tG8 | livemode=false |

Recurring currency/amount/interval/count/usage are verified as USD 2900/14900,
month, 1, licensed. Tax behavior remains unspecified; no tax/legal terms are added.
Test Portal `bpc_1UMgB5JZl100kP8eHeGbW10Q` enables payment methods, invoices and
end-of-period cancellation, with customer edits and subscription updates disabled.
Do not create duplicate resources on resume. Price mappings belong in
`public.pr_plan_terms.provider_price_id`, not fabricated Price env variables.
There are no database mapping changes yet.

Supabase reports no existing branch for `buoyhkbodnhzngaotoel`. A schema-only
branch in canonical Rafii organization `gztpsyvraqdcoklwpvdo` is quoted by the
provider at USD 0.01344/hour. Its tool requires cost confirmation. Approval is
pending; no branch or billable database resource has been created.

Free has no Stripe Price. Do not provision or map Creator, $49/$59/$79 experiments
or top-ups. Preserve Creator's proposed/new-checkout-disabled state. Retrieve
actual Product/Price facts before persisting server-side mappings. Require one
distinct real Price per active purchasable plan, test mode, USD, month/count 1,
quantity 1 and the exact approved amount/package. Never substitute a fixture ID.

Prefer a restricted test key; qualify its actual permissions with the required
Checkout and Portal calls. Keep provisioning and runtime access scoped to the
intended sandbox. Store keys and the sandbox webhook signing secret only through
the authorized secret channel; receipts contain fingerprints, not values.

Create the sandbox endpoint on the approved canonical Preview origin at
`/api/billing/webhook`, with exactly these enabled events:

```text
checkout.session.completed
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
invoice.paid
invoice.payment_failed
```

Pin endpoint events and outgoing requests to `2026-08-26.dahlia`, then record the
actual endpoint ID/version. The provider rejects signed events with a mismatched
configured API version. Checkout now sets `allow_promotion_codes=false`; discount
authority remains unresolved. Configure a sandbox Customer Portal with payment
method management, invoice history and cancellation. Keep subscription updates
and arbitrary plan switching off. Persist its actual `bpc_` configuration ID in
`POSTRIFF_STRIPE_PORTAL_CONFIGURATION` so runtime sessions use that configuration.

Billing webhook fulfillment and notification outbox planning commit before the
response. Owner-address lookup and email delivery run in the existing leased
notification worker, with the same detector dedupe keys. No notification send is
performed on the Stripe request path. Preview email flags remain off; the local
synthetic-worker check proves the async path without customer messages.

## Required real sandbox receipt

Fresh local validation of the integrated production delta uses Python 3.12.13
and Node 24.15.0: 425 Python tests (411 pass, 14 PostgreSQL-dependent skips),
149 web tests pass, 11 selected disposable PostgreSQL groups pass, typecheck and
build pass, and lint passes with three existing warnings. The offline source
scan passes with 2,604 inputs, 508 reviewed findings and zero unexpected findings.
These are local checks with synthetic transports, not real Stripe acceptance.
Detailed logs remain in the ignored continuation receipt directory; prior
checkpoint evidence is retained under its original source identity.

Deploy the exact integrated SHA to canonical Preview only after the target,
lineage, scopes and isolation checks pass. Complete real Stripe-hosted sandbox
Checkout for both plans and retrieve Stripe objects plus database evidence for:

- Signed webhook activation and exact workspace/plan/customer/subscription/Price
  binding; one monthly grant for the paid invoice and no duplicate grant.
- Duplicate/replayed events and completion/subscription/invoice ordering;
  old events cannot undo the current valid binding.
- Wrong Price, customer, metadata, package and API version rejection.
- Payment failure, cancellation, owner-initiated reenrollment and old-subscription
  events arriving after reenrollment.
- Test Clock renewal, paid-cycle single grants, non-rollover expiry and failure/
  cancellation periods. Advance a distinct test fixture clock and reconcile its
  events before advancing again.
- Signed-in owner/member Billing and credits checks, fast webhook response and
  verified durable notification planning; no real email/model/phone dispatch.
- Portal payment method, invoice and cancellation behavior; no plan switching.

The final acceptance receipt must bind the exact Git SHA, sandbox account and
Product/Price IDs, endpoint/event version, Portal configuration, canonical Preview
deployment, isolated database reference and plan/ledger mappings. Record actual
provider and database evidence, latency, replay IDs and clock periods. A simulated
event, return page, local unit test or Checkout URL alone cannot pass these gates.

Live commercial activation remains unauthorized. It requires a passed sandbox
receipt, James's separate explicit authorization, separate live Price IDs and
webhook secret, plus the existing verified legal entity/address/governing-law
gates. Do not invent tax, refund, legal terms or plan-transition policy.

References: [Stripe webhook delivery](https://docs.stripe.com/webhooks),
[endpoint configuration](https://docs.stripe.com/api/webhook_endpoints/create),
[Portal configuration](https://docs.stripe.com/api/customer_portal/configurations/create),
[Test Clocks](https://docs.stripe.com/billing/testing/test-clocks),
[Dahlia API version](https://docs.stripe.com/changelog/dahlia).
