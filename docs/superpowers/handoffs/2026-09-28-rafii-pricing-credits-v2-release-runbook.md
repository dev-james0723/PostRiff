# Rafii Pricing & Credits v2 release runbook

Updated 2026-10-02. This is an operator candidate for the approved 2026-09-28
[design](../specs/2026-09-28-rafii-pricing-credits-app-wide-design.md) and
[implementation plan](../plans/2026-09-28-rafii-pricing-credits-app-wide.md).
It does not authorize or record commercial activation. Local code acceptance
remains pending Task 13's full matrix and independent whole-branch review.

## Source and schema admission

The protected canonical checkout is `/Users/ouxianxing/Documents/James-Au-Studio`
at `d91660b7936a5158b820914107306ad4a1e51c2d`. Its earlier WIP/index/Git backup is
`/Users/ouxianxing/Documents/James-Au-Studio-wip-before-d916`; retain it. The
isolated implementation branch is `codex/rafii-pricing-v2-recovery-20261002` in
`~/.codex/worktrees/rafii-pricing-v2-recovery/James-Au-Studio`, also based on d916.
Runbook preparation source: `1d8a9b7a389c68e3268c01312921538e7f1c1ab0`. The final Task 13 receipt must identify
the final reviewed Git commit and source hashes; a later commit invalidates an
earlier source-specific check if its inputs changed. No stash/reset/clean of
shared or surviving WIP is part of release preparation.

Apply the existing hosted migration chain in numeric order after reviewing the
target database's actual migration history. Credit scaffolding 020–022 and the
existing private events table from 025 must precede 048. Preserve migration 049
and all other existing migrations; 050 follows the current chain. Never substitute
the test `rls.sql` baseline for a production migration procedure.

| New migration | SHA-256 |
| --- | --- |
| `048_pricing_credit_catalog_v2.sql` | `a36357deb034fa32faac10ac9c893d5b09087f01c9689e072e8764adef792ba0` |
| `050_free_lifecycle_bootstrap.sql` | `f9aad0a010d8cb1205ed029112be5703c10631870ae3db09076e938b2fbb1e7d` |

There are 46 unique migration prefixes in this source inventory. These
hashes identify code only: no production database was inspected or migrated by
this implementation. Check the complete final inventory before execution.

## Launch catalog and customer behavior

New prospects see Free ($0, zero fungible managed credits) and Creator ($59/month,
3,500 monthly credits). The public display stays Free + Creator during OFF or
rollback, with Creator waitlist/unavailable until purchasing is qualified. A
pre-048 public endpoint is unavailable; it must not advertise legacy new sales.
No new Creator trial or annual sale is enabled.

Creator variants $49/$59/$79 use the identical 3,500-credit package. The experiment
is OFF by default. Assignments are immutable, server-side and restricted to an
explicit approved cohort; neither a URL, browser choice nor client-supplied amount
or Price ID selects the price. Do not describe $59 as empirically optimized.

Starter $29/1,000 and Studio $149/8,000 are hidden and non-purchasable. Prepared
top-ups $15/1,000 and $29/2,000 are inactive, with blank provider Price IDs. Purchase
expiry, refund and other legal terms are UNDEFINED pending a specific decision;
do not adopt the historical 12-month proposal. BYOK and CLI transport availability
does not activate a BYOK sale or authorize provider spend.

Existing paid $19/$39 customers retain their actual grandfathered subscription
terms, renewals and portal access. Existing trials finish at their existing expiry
and become v2 Free. History, drafts, exports and existing credit lots remain
accessible. Do not mass-convert subscriptions or rewrite old policy versions.
Canceled Creator reenrollment requires an explicit new owner checkout using the
verified actual customer/variant. Portal access alone does not restore it.

Managed work requires a current server quote and explicit MAX authorization, then
a committed reserve before every physical paid I/O. Convert at 300 credits/USD
and round once per task to 0.1 credit. Settle actual use and release unused holds;
known provider failure charges the customer zero while recording actual platform
cost. Unknown outcomes keep the hold and forbid a paid retry. Above-MAX cost is
absorbed by the platform. Monthly grants do not roll over; payment/grant/webhook
processing and concurrency remain idempotent. Gateway markup is applied once.

Free has at most one lifetime Post Doctor preview and one recent-20-post Genome
preview, each requiring its own finite, independently approved platform funding
policy. They default OFF and do not mint wallet credits. Paid base checks/Genome
also require their separate funded opt-in. Consent or the James UUID usage
exemption is not funding authority. Stored reads, manual paths and existing
BYOK/CLI behavior remain distinct from managed spending. Unqualified routes fail
closed; do not display a fabricated fixed price, quote or expiry to bypass them.

Customer credit and plan projections contain credits and truthful plan data.
Owner-only provider-cost diagnostics may appear in a separate advanced view, as
approved in design section 13 and Task 8; they are not credit balances or customer
prices. Non-owner users receive no private USD costs. Stripe secrets, raw provider
Price mappings, internal funding-policy data, cohort data and raw event payloads
stay server-side. An unknown or malformed current-period grant is `null`, not an
advertised-quota fallback. Use the verified linked period's gross granted quantity.

## Independent activation gates — instructions only

Defaults in source, not assertions about current production runtime:

```text
POSTRIFF_PRICING_V2_ENABLED=0
POSTRIFF_CREDITS_ENABLED=0
POSTRIFF_CREDIT_PURCHASES_ENABLED=0
POSTRIFF_CREATOR_PRICE_EXPERIMENT_ENABLED=0
POSTRIFF_CREATOR_PRICE_EXPERIMENT_COHORT=
```

1. Record the final approved commit, schema checksums, local matrix and review.
   Obtain approval for the actual staging target and test-account access before
   touching an external account or database. Credentials establish capability.
2. For separately authorized Stripe test preparation, map the default Creator
   variant to a unique monthly USD test Price for $59. Verify actual Product,
   Price, currency, recurring interval, mode and same-package entitlement. Leave
   $49/$79 unavailable unless an explicit experiment is approved; retain actual
   grandfathered Price mappings. Never reuse a live Price in a test fixture.
3. Catalog status, `new_checkout_enabled`, the selected variant's active status
   and unique provider Price mapping are separate gates. All must match server
   qualification, owner role and commercial policy. The v2 acquisition switch
   does not itself activate checkout. Credit spending and purchases are separate
   switches; packs additionally require active pack data, correct key/mode and
   approved purchase/legal policy. Keep inactive tiers inaccessible by direct API.
4. On the separately approved staging target, verify owner/member authorization,
   default and explicit-cohort assignment, checkout return, signed webhooks,
   correct single monthly grant and period expiry. Subscribe to
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.paid` and `invoice.payment_failed` as required by the actual parser.
   A return URL is not fulfillment proof. Completion alone lacks actual Price
   evidence in the current parser: retain the prior binding/no grant until a
   matching verified subscription-created or subscription-create paid invoice
   establishes the new binding. Exercise completion-first, replay, out-of-order,
   wrong customer/Price/variant, renewal, cancellation and reenrollment.
5. Live Price creation, production migrations, deployment and feature/commercial
   activation each require separate approval for the actual target and effects.
   Resolve merchant legal placeholders using supplied verified facts and obtain
   the required legal decision. No implementation worker may invent legal facts.
6. After approved activation, perform signed-in owner/member smoke checks of
   Billing, Overview, Ideas, Writing, Growth and Genome, manual/stored reads,
   free preview finite limits, MAX/hold/unknown/failure behavior and grandfathered
   customers. Observe actual ledger/provider outcomes before retrying uncertainty.

## Pause and rollback

Pause new v2 acquisition/checkout with `POSTRIFF_PRICING_V2_ENABLED=0` and disable
the persisted new-sale gate as appropriate to the approved target. Keep public
Free/Creator display and unavailable CTA; never reintroduce $19/$39 new-sale copy.
Set experiment OFF without deleting assignments. Disable new managed spending
and purchases with their respective switches. Preserve existing ledger/holds,
settlement reconciliation, signed renewal handling, grandfathered billing and
read-only history. Do not drop schema, delete lots, replay a failed paid call,
mutate historical policy or reset existing customer terms as a rollback.

## Beta evidence and local acceptance

Reuse the private `pr_product_events` table from 025. Record price assignment only
for an actual stored explicit-cohort assignment, checkout started only after a
valid session/return, and paid revenue only from verified paid invoice data.
Credit events track holds, actual settlement, unknown holds, platform failures,
over-MAX absorption and latest cumulative expiry without SUM double counting.
First value comes from actual Ideas apply; retention/adoption comes from actual
stored weekly work; cancellation is categorical, not free-text or private payload.
Observation failure must not retry a paid action or erase its successful return.

Focused recovery evidence and per-task reviews live in the private task ledger
`.superpowers/sdd/2026-09-28-rafii-pricing-credits-app-wide/`. They are not deployment
proof and must remain excluded from the function archive. Task 13 must record
exact final commands, identities, PASS/FAIL/SKIP counts, actual disposable PG17,
production build, browser widths/reduced motion, audits and whole-branch review.
Synthetic transport with real Next → API → PostgreSQL is local synthetic
acceptance, not a real Stripe checkout or real provider outcome.

At preparation: LOCAL CODE full verification pending; TEST STRIPE NOT_RUN;
PRODUCTION DB NOT_APPLIED; LIVE STRIPE PRICES NOT_CREATED/ACTIVATED;
PRODUCTION CHECKOUT not activated by this task (runtime not inspected);
LEGACY CUSTOMER MIGRATION NOT_PERFORMED. Update only the local evidence status
when fresh Task 13 acceptance actually completes.
