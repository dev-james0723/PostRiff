# Telegram release status — 2026-10-11

**NOT LIVE. Mandatory real Rafii A–D acceptance is incomplete.** Synthetic tests do not establish production readiness.

## Owner directive and verified targets

Follow https://github.com/dev-james0723/PostRiff/issues/179. Integration branch: `consumer-saas`. Existing production Vercel service `postriff-phase2-private`: `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`. Intended Supabase project: `buoyhkbodnhzngaotoel`. Release destination: https://rafii.io.

Fresh production alias readback: READY deployment `dpl_6NGweKP5ytbqeiRrow8ALq5yTJSv`, deployed SHA `7e993563be9841f7f98758fb0c8c52f158ea7252`. Existing production auth/storage URLs match the intended Supabase ref; `NEXT_PUBLIC_APP_URL` is rafii.io. The server DSN is write-only in Vercel and cannot be pulled. Its binding remains UNKNOWN until the production build guard validates the real value before any backend access. Production OIDC Client ID is absent; existing owner-saved credentials remain outside the checkout.

All access to `rafii-consumer-staging` / `oxacvkhpfgytkepxcaqh` has stopped. The pending staging callback was never saved. Short-lived deployment share access was revoked. No staging records, secrets, identities or grants may be copied into production. Do not delete or pause those projects.

## Candidate changes

- Telegram identity linking uses official OIDC code flow, PKCE S256 and pinned RS256/JWKS/issuer/audience/time checks. Identity never grants chat access.
- Provider capabilities retain fresh actual destination rights and distinguish reviewed real release evidence from an explicitly authorized owner canary. Canary access is default-off, expires within 24 hours, and requires exact production project/backend, Rafii member, workspace, bot, destination, connection mode and Business connection ID. The retired staging QA grant is ignored.
- Draft approval, scheduled jobs, edit/delete/reply operations, outcome reconciliation, encryption and tenant checks reuse the existing application paths. Automation pause/revocation fencing is preserved.
- Issue #179 release/build/runtime guard blocks the forbidden project or DB ref, including URI-encoded/keyword DSNs, before backend access. Missing or mismatched production bindings block the release. Error output never echoes secret values.
- Telegram migrations are 116–117, leaving Mastodon 113–115 unmodified. Migration 103 was recovered byte-for-byte from Git and matches its applied production checksum. Other recorded production ledger entries matched the candidate source. New Telegram tables are absent in production; no production DDL has been executed.
- New tables use RLS, forced RLS, no PUBLIC/anon/authenticated access, and service-role policies. Application queries retain authenticated workspace boundaries.
- This branch disables automatic Git deployment. A reviewed source may be staged only in the real project with production environment and no automatic rafii.io promotion. Do not use a Preview backed by the forbidden database.

## Validation and real evidence

JCB/Depot CI `5z2n596lgb`, exit 0: 231 Python tests, 18 PostgreSQL checks, type generation/typecheck/lint/build, and Chromium UI checks at 1024px and 390px. Disposable CI DB only; no production or staging traffic. 1000 synthetic users/tasks verify tenant routing and concurrency, not Telegram throughput. Retained evidence: `evidence/cloud-production-policy-2026-10-11/`. Additional JCB `25wwt344m8`, exit 0, rebuilt the 60 source-verified production migration definitions in socket-only CI, applied only 116–117, preserved the existing synthetic workspace state, verified all 17 Telegram tables force RLS with no browser CRUD grants, and restored the synthetic pre-upgrade backup. This is not a hosted production backup or restore.

The CI snapshot precedes only the byte-exact recovery of migration 103, the branch deployment-disable setting and correction of a migration receipt label. Those edits do not alter the tested runtime behavior; final protected checks must run on the exact release commit.

Real Bot API component checks in the owner-authorized new private Rafii QA Channel and Rafii QA Group are recorded in `evidence/real-api-components-minimum-rights-2026-10-11.json`. They do not complete Rafii A–D. Fresh read-only webhook inspection confirms the existing bot points to `https://rafii.io/api/telegram/webhook`, has no pending updates or delivery error, and currently receives only channel_post/my_chat_member.

Production Rafii still shows QA Channel identity Direct, publishing Assisted, scheduling/replies Unsupported. Candidate code has not changed that live behavior. No customer posts have been sent by this candidate.

## Acceptance and remaining gates

A — existing James owner account OIDC signature/identity, permission selection, disconnect/reconnect: INCOMPLETE.

B — real Rafii draft, exact approved QA post, native delivery readback, scheduled delivery, edit/delete: INCOMPLETE.

C — real authorized AI draft, approval/action verification, pause and no further dispatch: INCOMPLETE.

D — Secretary selected-chat grant, real incoming message, contextual AI reply, approval/delivery and revoke/access removal: INCOMPLETE. Current Telegram Chat Automation is available to all users; Premium is not a prerequisite. Do not reuse existing private conversations. An independent authorized sender/test conversation is still unestablished.

Release Captain coordination, independent review, reviewed additive production migration/rollback receipt, runtime DSN binding and exact-commit protected checks remain required. No merge, migration, domain promotion or public release qualification is recorded. Stage and verify one production build, then promote that exact accepted build only through the controlled release workflow. Never fabricate A–D evidence.

Production backup dashboard was read-only inspected: this organization is on Free, scheduled project backups are unavailable, and its dashboard reports exceeded usage limits/grace period over. No upgrade, payment, export or restore was attempted. Keep this observation for the Release Captain; do not treat the migration ledger as a data backup.
