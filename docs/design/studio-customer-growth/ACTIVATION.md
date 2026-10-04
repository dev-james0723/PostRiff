# Ordinary paid Studio activation candidate

Execution state: **reviewable candidate**, not a production activation, platform submission, payment or publication. The immutable historical baseline is139 rows (5 PASS /134 BLOCKED); current code, production and data receipts are separate. Canonical project is `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`). Production was rechecked on2026-10-04 at `fc29af29482fb28e1acbd42a62700b0db7e51829` including PR120. PR121 remains separate/open.

## Existing plans and ordinary principals

“Pro Studio” maps to existing `studio-v1` / `assist-v1` / `assist-bounded-v1`; no new tier. Migration007 currently defines proposed Studio USD19/month and Studio Assist USD39/month. Assist100 batches and bounded Assist8 batches are distinct immutable terms, not interchangeable. All define1 member,3 connections and1000MB. These proposal prices are not evidence of active live Stripe prices.

Before enabling customer admission, verify actual active terms, exact live Stripe price ID, current active subscription, matching subscription entitlement and a current paid live invoice with positive amount. Fixture/test invoices, trial/manual grants, Founder capacity and an expired subscription are rejected. Do not charge or change a price merely to make acceptance pass. The new switch is `POSTRIFF_CUSTOMER_STUDIO_ENABLED=1`, initially off; reads and worker enumeration use the same fresh policy.

Acceptance needs an ordinary paid principal with no Founder/ops exception and no Meta app role, plus a separately owned second workspace for isolation. Owner/editor/read can be tested sequentially within the existing one-member capacity using explicit temporary role changes and restoration; a simultaneous multi-seat scenario requires separately approved existing capacity. No silent free capacity expansion. Verify onboarding, actual invoice-to-entitlement reconciliation, role denial, expiry, fresh/populated states and workspace switch. Capture evidence IDs, not tokens/cookies/customer invoice contents.

## Access and schema prerequisite

The current Vercel connector denied `action=list, resource=projectEnvVars` with403. Do not retry through CLI/UI/another identity. An authorized project owner must restore the connector's access to this exact canonical project or provide a separately approved read-only database/schema access path. That action needs the account owner's approval; credentials alone do not grant authority.

Read-only checks first: migration registry/checksums through058; specifically036 native metrics,037 history,038 closed loop,040 Trend registries and057 invoices; actual table/column definitions, forced RLS/service-only privileges, purge tombstones, indexes and clock. Verify all existing role/source/model/cohort/receipt contracts and bounded budgets against rows, not env readiness. This change adds no migration. Missing `pr_invoices` fails closed. Apply only a concrete missing migration after a separately reviewed migration/rollback preview; never reseed plan/provider/method rows as qualified.

## Meta submission packet (prepare first; submit only with owner approval)

The visible Rafii dashboard is app `1401844428820097`. Its Published state does not establish public Advanced Access. Match this app and any linked Instagram client to canonical production's configured client ID before editing any permission. The currently connected `@jamesaucreates` grant contains four business permissions but `productionReviewed=false`; it cannot certify public customers. The dashboard's business-comments permission was still an Add action. A grant or API-call counter is not a completed review.

| Lane | Requested exact scopes | Justification and real demo |
|---|---|---|
| Instagram connection | `instagram_business_basic` | Identify the connecting professional account and show its own Channels entry. Ordinary external user completes OAuth and returns to that same workspace. |
| Owned publication | `instagram_business_content_publish` | Publish only an explicitly approved original draft to that account. Show exact content approval, durable job, provider ID and native verification. No comment reply or messaging scope is requested. |
| Owned analytics/history | `instagram_business_manage_insights` | Read authorized metrics on that user's owned posts. Show actual observations and definitions/unknowns; separate90-day History Import consent. A lifetime counter never reconstructs earlier1h/24h/7d windows. |
| Audience Miner | `instagram_business_manage_comments` | Read comments on verified owned posts after separate owner comment-analysis consent. Show provider/connection/post ownership, handle/contact redaction, privacy abstention, bounded insight and reviewed Ideas save. No automatic response is sent. |
| Threads counterparts | `threads_basic`, `threads_content_publish`, `threads_manage_insights`, `threads_read_replies` | Same connection/publication/analytics/owned-reply read demonstrations per lane. `threads_manage_replies` is excluded unless a separate reply-management feature/action is actually approved. |

Per-permission submission text: “Rafii lets a creator or small business manage its own connected professional account within its private workspace. This permission is used only for the specific action demonstrated above, with current account scopes and workspace permissions checked again before execution and retention. We do not use this permission to collect arbitrary third-party accounts. Disconnect, withdrawal and account deletion stop collection and queue data cleanup. Derived comment excerpts are redacted before analysis.” Customize the permission-specific action; do not submit the same generic paragraph for all scopes.

Record a real screencast per permission: ordinary sign-in → workspace/plan → Channels OAuth → permission-specific action → retained result → disconnect/revoke → unavailable and cleanup evidence. If a real horizon is not yet collected, show its actual pending/due state and record that part later; do not film synthetic counters as a real review demo. Prepare reviewer sign-in instructions without placing passwords/MFA secrets in Git. Check Business Verification and exact Advanced Access state in the matching production app. Owner performs any required MFA. Adding scopes, changing app security/access, submitting the packet and publishing are separate approved actions.

Production URLs to verify before submission:

- Privacy: `https://postriff-phase2-private.vercel.app/privacy`
- Terms: `https://postriff-phase2-private.vercel.app/terms`
- Deletion: `https://postriff-phase2-private.vercel.app/data-deletion`
- Privacy controls: `/app/account/privacy`; disconnect in Channels.
- OAuth fixed callback: `https://postriff-phase2-private.vercel.app/api/oauth/{provider_id}/callback`; exact provider ID must match runtime configuration.

Primary references: [Meta Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/), [Meta's Instagram collection](https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login), [Meta Threads authorization](https://www.postman.com/meta/threads/folder/34203612-e0373e84-de6b-46f1-b90d-3fea76ba6782). Meta's developer pages returned429 during this audit; confirm matching dashboard requirements before submission. Current runtime adapters/scope contracts and visible dashboard evidence are retained separately.

## Independent Trending admission

Do not wait for Meta to validate independent writing or qualified Bluesky/Mastodon sources. For each source separately, verify implemented provider operation and current reviewed contract/policy, acquisition rights, raw retention, derived/display rights, LLM eligibility, deletion/expiry, workspace source entitlement and current provider/workspace/global caps. Bind exact source versions, scopes and receipt provenance; do not mark a draft policy ready merely because its endpoint is public. Reddit/X/TikTok/Meta/YouTube require their own actual available rights; Unsupported remains unavailable. Selecting a source filter is a UI check, not acquisition proof.

Readiness of Exa/Jina keys does not authorize search spend or replace source licensing/review. Existing Cron planners now enumerate current paid workspaces independently of beta UUID allowlists. Every producer still validates its own lane flags, rights, budgets and current context. Production lists currently report unavailable coverage and empty stored data even though many UI flags are on.

Enrichment and Trend Genome need their own reviewed semantic task/model/cohort authority. Saturation needs its current crowding/cohort scope and expiry. Whitespace needs its reviewed gap method and provenance-bound comparison/disconfirming evidence, including existing retrieval coverage>=0.8; `executable_ready` remains distinct from empirical qualification. Forecast requires its immutable preregistration, chronological held-out outcomes, embargo, predeclared min_episodes/min_pairs, primary loss and coverage tolerance; do not choose the lowest allowed minimum for a demonstration. Basic Ideas/dismiss/handoffs do not require a new forecast or model attempt. An opportunity that actually cites an advanced method must carry that method's current qualification.

## Model and public-action previews

A **candidate cumulative model/provider allowance is USD20 for one named ordinary paid acceptance workspace**, not approved spend. Apply the lower of that total, existing daily global/workspace/provider/attempt caps and each confirmed customer quote. Approval must name workspace, exact routes, expiry and total. Current observed routes include Jev/Gemini Flash Lite, Anthropic Claude Haiku4.5 synthesis and OpenAI GPT6 Sol writing; verify runtime model IDs and active price contracts before using any. Stored-result inspection, accept/dismiss and Ideas handoffs need no new paid dispatch. Unknown outcomes retain reservations and stop further attempts until reconciled; do not retry ambiguous paid actions or borrow Founder unlimited/old budgets.

Exact **unpublished** text candidate, one post per approved destination only:

> Today's studio note: one small idea, written with care. What would you like to explore next?

For a text-capable qualified provider this is a concrete reviewable caption. Instagram additionally needs an exact approved media asset; no asset upload or publication is authorized by this packet. Approval must specify the ordinary professional account, provider, final text/media hash, audience and time. The existing `@jamesaucreates` account is not presumed eligible as a non-app-role acceptance account. Avoid generating replies/comments or engagement to satisfy sample minima. Existing real user comments/historical posts may qualify only with actual rights and consent. Public Content DNA shares and any external notifications need their own exact content/access/recipient opt-in; in-app watches and notification dedupe are separate flows.

## Durable collection, retries and earliest acceptance

Existing canonical Vercel cron is `/api/cron/worker` every minute with server-only cron authorization. Actual retrieved HTTP200 logs establish reachability only. Inspect durable job/lease/attempt/result rows to prove publication, metrics, imports and each trend producer. No browser tab/manual repeated command substitutes for durable workers. Keep bounded retries, idempotency, claimed lease fencing, completion payment/member/consent/provider rechecks and tombstones.

After an exact approved real publication is natively verified, persist its immutable anchor `t0`. Independently record1h at`t0+3600`,24h at`t0+86400`,7d at`t0+604800`, each within its existing inclusive600-second deadline. Earliest dates are unknown until that real anchor exists. `dueAt` is the horizon target, `deadlineAt=dueAt+600`, `nextAttemptAt` is retry timing. A missed window persists `unavailable/horizon_missed`; a later current counter can be retained as an untagged current observation, never labeled an old horizon. Do not replace genuinely observed zero with missing or vice versa.

History Import is separately consented, at most90days/12pages/300posts, exact account and consent digest, deduped and resumable; one import snapshot is not a historical horizon series. Creator Genome accepts **1–20** explicitly selected owned posts, the existing maximum rather than a20-post minimum; uploaded metric values remain user-supplied. Creator Calibration keeps its>=50-post cohort and at least three fitted dimensions with chronological held-out evidence. Their evidence and earliest qualification stay separate from one test publication or a forecast cohort. Do not recreate missing historical observations.

For each pending matrix row record its exact dependency, retained evidence IDs, required sample/method state and earliest defensible time. Fresh/empty/error controls can be verified before positive data but cannot complete a positive data row. Keep all139 IDs; do not collapse those gates into one platform blocker.

## Rollout, purge and rollback

After remote CI and review, take a canonical deployment/schema/config preview, enable only the separately qualified lanes, deploy the exact reviewed SHA and verify canonical alias. Ordinary customer production browser/API gates must cover desktop/mobile plus actual Safari/WebKit, role/second-tenant isolation, fresh/populated, expiry/revocation/failure, caps/unknown outcomes, purge and rollback. Safari currently reaches the real sign-in page; no ordinary authenticated Safari result was observed.

Rollback preview: disable each newly activated Growth/Trending/model/provider dispatch lane and customer switch, stop new jobs/reservations, cancel/fence claimed work at completion, preserve durable missing observations and unknown-cost accounting. Keep flag-independent pending purges and maintenance running; do not delete source/billing/method rows or enable legacy Founder lanes accidentally. Restore the last verified canonical SHA only through the same approved deployment scope. Verify new work is denied and cleanup completes. A READY deployment, Founder success or rollback command submission is not ordinary customer acceptance.
