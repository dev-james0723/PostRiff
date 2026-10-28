# Kynlo Hybrid acceptance continuation — 2026-10-19

Status: engineering candidate, not public production ready. Correct paired device: Kynlo Hybrid. Existing work and other agents preserved.

## Repairs in this candidate

1. The new multi-mode PostgreSQL fixture was incorrectly selected by the generic cluster runner and had no invoked dedicated CI. It now has an explicit owned route and an exact-branch, exact-SHA standard Ubuntu qualification workflow. The wrapper records independent failing gates and fails the aggregate if any required check fails. No deployment, retained artifacts, cache saves, paid runner or provider credentials.
2. A retained webhook token did not prove the original Discord author's current membership or channel permission. Custody now proves only the exact application/webhook; channel authorization, re-verification and pre-send require fresh app-verified server membership, current channel overwrites and the author's VIEW_CHANNEL/SEND_MESSAGES. Missing app read access fails closed. The already authorized app is a read-only witness; actual posts still use the webhook. No hidden bot publishing fallback. The three UI language packs disclose this dependency.
3. Every committed webhook verification now advances discordVerificationGeneration, including denial. An older success cannot erase a newer denial even when both began with capabilityVerified=false.
4. An unlinked/ambiguous User Install interaction now links to the real authenticated /app/channels route.
5. Local private-link removal is separated from permission to create a new User Install mapping. A separate stored-mapping flag keeps removal available when the live identity needs reconnecting. No provider action or scope escalation is required to remove the local mapping.
6. The owned PostgreSQL fixture now includes actual service_role PostgresWorker plus SharedPostgresBudget scenarios for concurrent claims, cancellation, local revoke, Discord permission loss, unknown create and provider 429. These are prepared tests, not an executed SQL pass.
7. New interaction tables explicitly revoke inherited service_role ALL grants, use FORCE RLS and grant only runtime SELECT/INSERT or SELECT/INSERT/UPDATE. Replay removal/truncation is not an ordinary runtime grant.

## Evidence boundaries

The first independent source review completed. Its concrete findings led to the repairs above. Four backend regressions were observed failing on the reviewed candidate, then passed after repair. The combined focused run reported 36 Python tests OK. The CI routing regression also ran on the Mac: 3 tests OK. Later source changes (mapping projection, UI, SQL fixture and grants) still require the final exact-source workflow; these counts do not qualify subsequent changes or the full application.

Local Node and subsequent aggregate test requests were denied by host resource admission before execution. No agents were stopped and no resource guard was bypassed. One additional synthetic browser-test write was refused by the tool; no equivalent write was replayed through another path. The existing running-app browser candidate remains intact apart from an unused test counter. Private-unlink helper/wiring checks are prepared, not a browser pass.

The new candidate must not inherit old 261/990 results or base PR211 successes. Linux/PostgreSQL/browser/Next build gates remain unverified until the exact new commit returns terminal results. Actual Discord OAuth, command setup/PING/registration, future scheduled sends/readback and public-customer deployment remain separate external gates. No real message, active job, new provider authorization, SQL migration, production flag, public alias or shared cron is changed here.

Official basis: Discord Webhook Resource (GET with token does not require user authentication) and Discord Permissions (effective channel permissions), reviewed 2026-10-19. https://docs.discord.com/developers/resources/webhook ; https://docs.discord.com/developers/topics/permissions . Public standard GitHub-hosted runners are used; total pre-existing tool/model costs remain unknown.
