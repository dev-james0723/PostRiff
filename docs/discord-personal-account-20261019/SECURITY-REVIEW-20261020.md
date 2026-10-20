# Rafii Discord PR #216 — Independent Security Review and TDD Repair

**Date:** 2026-10-20, US Eastern / UTC. **Review basis:** stacked PR #216 (base PR #211 at `63864bd6654f62a165c398ce4c493528aee6f501`), independently reviewed source HEAD `ee47c136fcd5ddf1301f22e9919e2162e21e562d`. Follow-on source SHA and exact-source CI must be recorded after repairs.

**Reviewer:** separate current ChatGPT review from original engineering implementation, with firsthand source inspection, direct negative test reproductions, permission-projection/SQL audit and actual Linux provenance. This is **not** a separate human/security professional sign-off. No code model calls or live provider requests are claimed.

## Scope / threat model

- **OAuth:** per-member/workspace signed server state, one-use claim committed before Discord exchange, issuer verification for new webhook v2, callback scope/application/user verification, PKCE, token vault and reconnect generation.
- **Webhook:** authorized incoming-webhook resource/custody, target and current Discord permission witness, exact text-only digest, no author spoofing, no arbitrary execution URL, independent destination and message approval, permitted body `wait=true`, immutable signed transport ledger and known-ID readback.
- **User Install:** Ed25519 verifies original signed request bytes, timestamp, app/owner/context and exact command; PING; durable replay claim, scoped SQL mapping, ephemeral private draft link; no user publishing/token persistence.
- **Isolation:** tenant/actor/member checks on binding/review/grants; PostgreSQL FORCE RLS and least privilege; broadcaster/worker lease, one-use send permit, revoke/reconnect, no duplicate POST after unknown provider result.
- **Release:** defaults OFF, source and CI provenance, no deploy/merge, 131 migration additive/unapplied, preserved other worktrees and active agents.

## Confirmed findings — RED→GREEN

### P1-SEC-01: Selected Discord identity not recorded on new webhook

**Location:** `src/postriff_phase2/discord/oauth.py`, `DiscordConnections.save_webhook_callback`; `DiscordConnections.invalidate_dependents`.

**Mechanism:** Webhook creation verifies a selected `identityConnectionId` and generation, but the resulting `phase2.channels` card did not retain that link. On local identity disconnect, the dependency invalidator searches `discordIdentityConnectionId` and skipped this webhook. Unrelated webhook grants intentionally remain independent, so the fix is conditional on the user-selected identity.

**Before:** `SECURITY-REVIEW-RED-WEBHOOK-IDENTITY.txt` failed: expected a selected dependent identity, got `None`.

**Repair:** Persist `discordIdentityConnectionId` **only** when the original OAuth transaction pinned a selected identity. Existing disconnect/reconnect then revokes exactly that webhook card and encrypted credential/generation.

**After:** `SECURITY-REVIEW-GREEN-WEBHOOK-IDENTITY.txt` passes; separate callback test confirms standalone webhook still has no synthetic dependency. Synthetic transport performs no Discord message POST.

### P1-SEC-02: Removed/downgraded Rafii member retained Bot Installation identity eligibility

**Location:** `src/postriff_phase2/discord/oauth.py`, `DiscordConnections.validate_installation` and `installation_identity`.

**Mechanism:** A valid linked Discord OAuth credential was treated as proof of continued installation consent without first checking whether the original Rafii **workspace** authorizer remained an active member entitled to manage connections. A lost Rafii member could still have a working Discord token. A worker path also attempted to use that identity before the workspace-authority check.

**Before:** `SECURITY-REVIEW-RED-BOT-AUTHORIZER.txt` contained two expected failures: missing membership did not reject; identity refresh could begin before authority validation.

**Repair:** Require a live `pr_memberships` and `pr_profiles` join with `m.status='active'`, `p.deleted_at IS NULL`, `m.can_manage_connections`/role permission under row-share lock. Refuse worker identity read/refresh before this verification. No migration, no widened provider scopes and no relaxed policy.

**After:** `SECURITY-REVIEW-GREEN-BOT-AUTHORIZER.txt` and `SECURITY-REVIEW-CUSTODY-FOCUSED.txt` demonstrate member removal, editor/viewer role downgrade, early worker denial, and selected-vs-independent webhook behavior. Existing happy-path fake SQL now explicitly returns a valid active manager instead of a malformed row; denial tests remain strict.

## Other security contracts checked (read-only)

1. Discord personal-account OAuth is identity-only: `canPublish=false`, `canSchedule=false`, `postAsPersonalUser=false`. Neither Webhook nor User Install may claim ordinary personal-user authorship.
2. Webhook transport uses the fixed official Discord API prefix with a validated webhook ID/token and no user-supplied URL; stored rate rows use templates and hashes, not secret-bearing paths. Exact sender, channel, payload, authorization and approval are frozen.
3. Denied/ambiguous sends retain durable intent and never mint an unapproved second POST. Six separate PostgreSQL 17 synthetic worker scenarios previously passed on exact source `ee47c136...`, including concurrent one-create/known-ID readback, cancel/revoke/permission loss, unknown result and 429.
4. User Install requires Ed25519, timestamp, exact app/command/user-install owner and bounded SQL replay; only an ephemeral, authenticated Rafii review URL is returned.
5. Read-only **canonical Rafii production** schema inspection found existing `pr_discord_request_admissions`, `pr_encrypted_credentials`, `pr_memberships`, `pr_profiles`, `pr_workspaces` all with RLS and FORCE RLS. Existing credential-kind constraint is named `pr_discord_request_admissions_credential_kind_check` and permits bot/user/oauth, consistent with additive migration 131, and encrypted credentials have PRIMARY KEY (workspace_id,connection_id). The two proposed `pr_discord_interaction_*` tables are absent, as expected. No records or credentials were read and no SQL DDL/DML was executed.
6. Migration 131 adds explicit `REVOKE ALL` from PUBLIC, anon and authenticated, then minimum `service_role` table grants and FORCE RLS; service role's bypass-RLS property makes exact grants and server custody critical. Privilege/isolation is covered by owned disposable PostgreSQL tests, not assumed from policies alone. Official read: https://supabase.com/docs/guides/database/postgres/row-level-security
7. Current GitHub exact-source CI run `39388351573` succeeded before these P1 fixes (5,775 full Python, 302 Discord, six isolated PostgreSQL, TS/Lint 0 errors with 37 warnings, 390px/1280px browser/axe, build, source unchanged). **That prior green run cannot qualify the changed source.**

## Acceptance and external boundaries

- **Now:** focused review regressions and complete Discord Python regression must pass on the repaired source; then fresh full GitHub Linux CI on the final SHA is mandatory.
- **Remaining external blockers:** one separately approved real OAuth reconnect; Discord Developer App/User Install command configuration and signed PING; a specifically approved single live webhook/bot message/readback; future-time unattended schedule/cancel; staging migration rehearsal; full PR #211 + #216 source/provenance integration; release captain sign-off.
- PR #211/#216 stay **draft/unmerged**. No Production promotion, no user communications, no paid providers, no real Discord message or Developer Portal mutation here.

## Rollback plan — no actual rollback executed

**Before public rollout:** leave Webhook/User Install and new P0/P4 flags OFF; do not apply migration 131, register commands or send messages. Revert isolated feature commits if a security gate fails. Keep worktree and full RED/GREEN/CI receipts.

**After any future expressly approved migration:** disable only the new Discord feature flags and admission; let existing bot/other-platform queues proceed. Preserve `pr_discord_interaction_links`, `pr_discord_interaction_replays`, authorization grants and immutable ambiguous-send records during forensic/reconciliation review. Do **not** blindly drop migration 131 tables, undo old bot credentials, clear rate-limit history, replay unknown publishes or roll back unrelated platform schema. Review actual in-flight leases and affected pending requests first. Rollback should be approval-specific and evidence-based.

**Overall:** two confirmed P1 security findings repaired in an isolated branch, no production effects. Engineering-review requalification is required; Public Production **NO-GO** until human/release gates and real provider acceptance.
