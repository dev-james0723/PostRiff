# Controlled release and operations — candidate, not executed

**Production NO-GO. Canonical production Supabase: postriff-phase2-private (`buoyhkbodnhzngaotoel`).** No replacement production project, database access or release is authorized.

## Existing-production pilot boundary (supersedes new staging)

Use only existing canonical Supabase `postriff-phase2-private` / `buoyhkbodnhzngaotoel` and existing Rafii Vercel project. Both new-DB proposals are canceled. The earlier Step A new-staging design is historical, not permission to run a shared-production pilot. [READONLY-PILOT-CANDIDATE](READONLY-PILOT-CANDIDATE.md) defines the exact tenant/operator/account/time-bound read-only lane and proposed configuration/migration/deployment effects. No new subscription or resource is needed.

Keep public/Agent gates closed. Two-scope profile/board consent, Sandbox-only identity/boards/token egress, daily100-call cap and disconnect are the proposed pilot scope. It now requires the reviewed quota table. No sections, Pin, analytics or Agent data action is included. Freeze actual actor/workspace/username/expiry, recheck current live source/schema/callback and obtain the specific external-operation/live-consent approval before executing. Standard and real-public-release acceptance remain separate.

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
