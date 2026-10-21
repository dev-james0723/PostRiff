# Controlled release and operations — old pilot expired, new candidate gated

**Production NO-GO. Canonical production Supabase: postriff-phase2-private (`buoyhkbodnhzngaotoel`).** One exact quota/config/deployment private pilot was separately approved and executed; this does not authorize a public release or further new-source deployment.

## Existing-production pilot boundary (supersedes new staging)

Use only existing canonical Supabase `postriff-phase2-private` / `buoyhkbodnhzngaotoel` and existing Rafii Vercel project. Both new-DB proposals are canceled. The earlier Step A new-staging design is historical, not permission to run a shared-production pilot. [READONLY-PILOT-CANDIDATE](READONLY-PILOT-CANDIDATE.md) defines the exact tenant/operator/account/time-bound read-only lane and approved configuration/migration/deployment effects. No new subscription or resource is needed.

Keep public/Agent gates closed. Two-scope profile/board consent, explicitly selected official API identity/boards/token egress, daily100-call cap and disconnect are the approved pilot scope. The reviewed quota table is now applied. No sections, Pin, analytics or Agent data action is included. The exact actor/workspace/username and expiry are recorded in the real receipts. Any next deployment must recheck current live source/schema/callback and obtain the specific new-source release approval. Standard and real-public-release acceptance remain separate.

## Migration and rollback

Existing hosted tables/services are reused. New candidate SQL: `migrations/postriff/20261014_pinterest_rate_budgets.sql`. It contains only hashed budget keys/window counters, server privileges and RLS. Resolve the final migration ordering/name during approved branch integration; do not run an unreviewed glob against production. First apply on an approved disposable/staging database, verify schema/privileges and quota concurrency, and record exact checksum.

Before approved production application: take the normal approved database backup, confirm canonical project identity and TLS, inspect schema compatibility, keep Pinterest public flags off, and apply only the reviewed SQL. This document authorizes none of those external actions.

Rollback order: set `POSTRIFF_OAUTH_PINTEREST_DISABLED=true`, disable public/agent flags, pause Pinterest jobs and preserve in-flight IDs/uncertainty, deploy the previously approved source/config only with approval. Never roll back to a legacy candidate that permits stale-token dispatch or public onboarding without approval. After provider requests stop, the new rate table may be dropped using the SQL's reviewed rollback. Existing encrypted grants/jobs/reviews must not be bulk deleted. A database rollback cannot delete or unpublish a provider Pin.

## Controlled production gates

Require official Standard approval; two-account real OAuth/isolation; refresh/reconnect/disconnect; frozen approved image Pin and provider read-back; separate visibility observation; actual scheduled execution/edit/cancel; security review; provider data-retention/AI-sharing clarification; exact-source CI; rollback rehearsal; release approval.

Then qualify production config and secure secrets without logging values, deploy exact tested SHA, confirm deployment SHA/flags, enable only named canary users, obtain exact production canary Pin approval, publish/read back/check board/account/visibility, observe failures/support, and obtain expansion approval. Ordinary eligible-customer acceptance is mandatory before public readiness.

## Operation and monitoring plan

Use existing audit/job events and redacted request journal. Monitor OAuth state failures, reconnect-required rates, refresh success/failure/lock delay, board/section denials, pinner-data denial, 429s and remaining headers, rate reservations, job lag, lease expiration, provider_accepted awaiting read-back, uncertain IDs, account drift, canceled jobs and dispatch denials. Alert channels/recipients are not configured or authorized by this mission.

Emergency pause uses existing `POSTRIFF_OAUTH_PINTEREST_DISABLED=true`; this is a proposed external config action, not executed. The runtime rechecks paused adapters on grant use. No unattended publishing policy is enabled. Reconnect does not reapprove canceled work.

Support: offer eligible business-account/review guidance for PINNER_DATA_ACCESS_DENIED; re-consent for expiry/revocation/mismatched environment; choose a fresh public board/section for denied destinations; preserve an uncertain create with no ID and require manual provider inspection; never create a second Pin solely to test whether the first succeeded.

Retention: disconnect erases local token ciphertext immediately. Existing history purge path is reused. Budget windows contain hashes only; propose deletion older than 48h via reviewed maintenance. No production retention job or external notification was installed. Validate contractual retention/deletion periods and authorized model handling before publishing policy changes or submitting Standard.

## Current operational state — 2026-10-17

Approved private pilot remediation sFLeor/productc8ff84fa is live on rafii.io; C4Aqh is its prior immutable deployment, BLY earlier. Exact quota migration and deployment-only credentials/config are recorded. Project-wide environment is unchanged. Active deadline **20:40:56Z /16:40:56 EDT**, with no automatic extension. Expiry fails closed for provider custody/actions; local disconnect remains available afterward.

Real OAuth exchange and business identity PASS. Actual disconnect PASS after ordinary human MFA; revoked/access erased/refresh erased alltrue.0real jobs. Real reconnect19:12Z, boards200/empty, refresh_token20019:33Z and final human-completed local disconnect19:43Z are verified. Both credential ciphertexts are erased;0connection jobs remain. No publishing destination was returned. The separately approved boards/refresh source is deployed. Preserve existing fresh-sign-in and independent-proof controls. [Next candidate](NEXT-ACTION-BOARDS-REFRESH.md).

Approved pilot-only emergency pause/restore may change only its reviewed flags; it never authorizes broad rollback, new costs or data deletion. Keep the quota table during pause. Existing grants must be disconnected through the authenticated account flow; do not mutate credential rows to simulate revocation. Restoring BLY would remove this pilot but also restore its older source/config, so reconcile current source/other deployments and obtain exact rollback approval before promotion. No rollback rehearsal has been executed.

No unattended notification/retention task was installed. No local-heavy tests/build/browser/PostgreSQL are permitted. All substantial validation runs remotely through the existing sanitized JCB lane. No push, remote merge, billing/payment or Standard submission occurred.

## Analytics candidate migration and rollback — not approved or executed on hosted infrastructure

The local candidate adds `20261017_pinterest_metric_reads.sql`: expand migration035's known provider CHECK to include Pinterest and add four native metric definitions. It changes no privileges/customer rows. Both forward and rollback reject unknown schema drift and use5s lock timeout. Validate on disposable PostgreSQL first. Production application requires its own exact-project/source/checksum approval.

Keep `POSTRIFF_PINTEREST_ANALYTICS_ENABLED` absent/0. Enabling it also requires provider review/execution, non-read-only custody, exactly the native read scopes, global metric reads, explicit workspace admission and actual validated CHECK/definition readiness. Identity is rechecked through the same bound adapter and quota transport; no generic transport or raw token export. Missing/nonfinite/negative/bool metrics remain unavailable; explicit0 is preserved. Metrics use `pinterest-pin-utc-window-v1` and UTC date windows, not a fabricated lifetime or exact24h count.

Pause new reads before rollback. The rollback refuses to remove Pinterest from the CHECK while any Pinterest read row exists; preserve historical observations and global definitions. Do not delete customer data to force rollback. Deployment/config, SQL application, extra consent and live analytics are distinct approvals. No analytics activation is covered by the original two-read-scope pilot.

## Current deployed code — 2026-10-17T20:28Z

Producte2e5169f/receipt10486d8b,2tFM READY and rafii.io/production-target verified;2217source hashes,health,actual private-readonly Channels UI PASS. Shared Discord-setting drift was separately accepted explicitly before one promotion. No second build or secret edit. c8/sF is prior immutable release. No metric SQL or Pinterest analytics/public/Agent/write activation; expiry20:40:56Z unchanged. Account remains disconnected. [Final receipt](FINAL-RECEIPT.md).


## Current continuation / independent feature rollout

Canonical production stays postriff-phase2-private/buoyhkbodnhzngaotoel. No staging substitution or resource purchase. Existing e2e5169f/2tFM is the rollback baseline for a future separately approved delta deployment, subject to fresh shared-config drift review and exact source qualification. Do not roll the whole shared application backward blindly if another integration has since changed; reconcile current tested baseline first.

1. Recover existing cloud auth and confirm a zero-incremental-cost route or obtain a specific cost approval. Run the prepared sanitized delta script from this actual worktree; preserve hashes/runID/exitcode. No push is needed for JCB dirty-tree transport. Node/build/browser/PG stay remote; no local heavy fallback.
2. Qualify repaired source before proposing any new code deployment. Exact production promotion and flags remain separate approvals. Preserve the shared web/API/phone services, timeouts, worker cron and accepted configuration; stop on new drift.
3. For an OAuth-only review recording, an optional fresh **one60minute private read-only** window can be proposed on the already tested e2e baseline. Same actor/workspace/account and scopes only, no new app/secret/callback, no API writes, no Standard/public flags. Activation must be separately approved; it cannot reuse the expired pilot. A fresh deployment/build has unknown metered cost and must not run under the user’s free-testing constraint without an approved no-charge route or budget.
4. Build and review the actual20–60fps OAuth/API video and correct app/policy fields. Submit only after the user reviews the final assets and separately authorizes submission. Recheck pending status first. The current partial recording is not compliant submission footage.
5. Standard plus eligible non-owner A/B acceptance, tested rollback and exact canary approval are prerequisites to public Connect/Publish. Start with two explicitly authorized eligible business-customer workspaces,1account/customer and at most1approved Pin/customer/day for a24hour observation window. These are proposed limits only; enforce in reviewed server admission before activation. No automatic access expansion.
6. Schedule and Analytics have independent feature flags/admission. Keep them off while a qualified Connect+Publish canary proceeds if those two gates eventually pass. Schedule needs actual>1h stale/refresh due execution, edits/cancel/pause/reconciliation; Analytics needs schema/consent/retention and real own-Pin metrics/no-data/failure evidence. Do not label partial GO as complete production readiness.
7. Emergency stop: disable Pinterest provider/execution admission and its metric reads, cancel pending exact-account jobs, preserve receipts, revoke local authority/erase credentials through normal authenticated disconnect. Reconciliation of an already accepted Pin continues only within its approved read authority; never retry create on uncertainty. Provider deletion is a separately approved operation targeting exact ID.
8. Rollback after a future delta: turn feature admission off before reverting qualified source/config to the recorded compatible immutable predecessor. Analytics migration rollback refuses nonempty Pinterest readings; retain data instead of destructive rollback. Validate backup/restore and rollback on disposable infrastructure before claiming release readiness.

## New bounded private execution candidate

PRIVATE-TRIAL-RUNBOOK.md supersedes the historical read-only-next-step proposal. Original grant revoked/ciphertexts erased; no authority extension. New journal and metric migrations require separate exact production approval and qualified source. Journal rollback refuses prepared/known rows; leave additive evidence in place when rolling code/config back. Four-scope consent and two real Pin approvals remain pending. First complete the one-run paid delta qualification; do not ask the user to deploy an unqualified source. New recorder helper is only source; actual compliant video not supplied.
