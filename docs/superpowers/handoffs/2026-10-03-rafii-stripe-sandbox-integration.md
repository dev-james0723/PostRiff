# Rafii Stripe sandbox integration — 2026-10-03

Execution state: local integration candidate. Stripe sandbox acceptance has not
passed. No remote configuration, migration, deployment, Product, Price, Checkout,
Portal or Test Clock operation has been performed by this phase.

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
`https://postriff-phase2-private.vercel.app`. Read-only Vercel verification on this
run resolved that alias to READY production deployment
`dpl_4wrwibdSSy9wd5VrDrWnFHBt7eN5`, `consumer-saas` source
`7156703b3725156c6041b059040007ab2ea63fab`. The latest project deployment can be a
Preview; use the production alias to resolve production lineage.

The Phone Call Repair receipt (2026-09-27), Growth Loop release receipt, launch
checklist and later Founder release receipts establish this canonical project
and the existing Supabase production reference `buoyhkbodnhzngaotoel`. This is
documented lineage; current environment/database bindings remain unverified.
The older Phone Mode setup receipt and `rafii-consumer-staging` are not deployment
authority for this task. Do not modify or deploy to that separate project.

Current permission boundary: the Vercel connector returns HTTP 403 for action
`list`, resource `projectEnvVars` on the canonical project. Preview/Production
variable names and scopes cannot be read. Write permission is unverified. Do not
use another credential path to bypass that denial. Obtain environment list/read
access and the scoped Preview configuration write access before proceeding.
The Stripe connector currently exposes only a live account, with no selectable
test context. Obtain the intended sandbox context before any Stripe mutation.

## Integration and schema

A fresh isolated worktree starts at the exact deployed source above and performs
a three-way merge of the approved pricing checkpoint. Conflicts preserve current
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

All canonical migration files remain byte-identical. First verify the target's
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

Candidate Preview settings, pending actual identity and secret-hash verification:

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
