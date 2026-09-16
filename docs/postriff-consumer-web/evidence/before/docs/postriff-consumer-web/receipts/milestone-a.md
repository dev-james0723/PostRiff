# Milestone A receipt — Secure SaaS foundation

**Date:** 2026-09-15 · **State:** implemented and locally verified · **External state:** unchanged (nothing deployed, no hosted migration applied)

## What changed (code/artifacts)

| Path | Change |
|---|---|
| `migrations/postriff/004_consumer_web_tenancy.sql` | **new, additive.** Roles owner/admin/editor/approver/viewer; `can_publish/can_reply/can_moderate/can_manage_connections` on `pr_memberships` (owners backfilled true); `team_membership` read policy; `pr_invitations` (hash-only tokens, service_role-only); `pr_audit_events` (append-only, tenant-read, no update/delete grants); `pr_sessions`; `pr_auth_throttle`; `pr_bootstrap` replaced to grant the owner all flags. |
| `src/postriff_phase2/permissions.py` | **new.** Role × requirement matrix (`read/edit/approve/reply/moderate/manage_connections/manage_members/owner`), action classification (unknown → `edit`), `STEP_UP_ACTIONS` with 600 s window, grant validation (no escalation beyond the granter; flags never elevate a viewer). |
| `src/postriff_phase2/hosted.py` | `transaction` now loads role + flags; `command()` takes `requirement`/`step_up`; `mutate()` classifies the action; uniform "Workspace unavailable." 403 for foreign and nonexistent workspaces; new `workspaces/members/update_member/remove_member/invite/invitations/revoke_invitation/accept_invitation/sessions/revoke_session/audit_events`; `bootstrap` throttles per client and per user, records the session, audits creation; `delete_account` requires step-up. |
| `src/postriff_phase2/hosted_worker.py` | Claim re-authorization now uses the permission model (`approve` authority), not `role in (owner, editor)`. |
| `src/postriff_phase2/hosted_identity.py` | `verified_auth_time()` (JWT `iat`, stale when missing) for step-up. |
| `src/postriff_phase2/hosted_app.py` | Routes: `GET /api/workspaces`, `GET/PATCH/DELETE …/members[/{userId}]`, `GET/POST/DELETE …/invitations[/{id}]`, `POST /api/invitations/accept`, `GET/DELETE /api/auth/sessions[/{id}]`, `GET …/audit`; `client_address()` / `client_label()`; 429 label; verifier exposes `auth_time`. |
| `scripts/check_postriff_hosted_preflight.py` | Requires migration 004 file. |
| `scripts/postriff_disposable_postgres.py` | **new.** Disposable local cluster runner (UTF8, `LC_ALL=C`) on 127.0.0.1:55438. |
| `tests/phase2/rls.sql` | Loads 004 after 002. |
| `tests/phase2/postgres_isolation.py` | **new.** Two-tenant negative suite (10 checks). |
| `tests/test_postriff_phase2_hosted.py` | +5 unit tests (matrix, grant escalation, auth time, client address/label, new routes). |

Hashes before/after: `evidence/changed-files.json`; diff: `evidence/source-diff.patch`; originals: `evidence/before/`.

## Validation (this round, observed)

| Check | Command | Result |
|---|---|---|
| Python unit suite | `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | **157 pass / 0 fail** (baseline 152 + 5) |
| Pre-existing PG suites on 004 schema | `LC_ALL=C .venv/bin/python scripts/postriff_disposable_postgres.py tests/phase2/postgres_repository.py tests/phase2/postgres_safety.py` | **pass / pass** (backward-compatible) |
| Two-tenant isolation | `… tests/phase2/postgres_isolation.py` | **pass**, 10 checks: owner flags on bootstrap; foreign ≡ nonexistent for read/mutate/export/media/members/audit/invitations; workspace list self-scoped; invitation hashed/single-use/normalized; role matrix (editor/approver/viewer, owner protections); step-up window; approver flag revoked mid-job → `held`, zero attempts; sessions self-scoped; 31st verify/min → 429; audit tenant-read-only + immutable, private tables never browser-readable |
| Phase 3 PG script | `LC_ALL=C .venv/bin/python tests/phase3/postgres.py` | pass (unchanged code; locale fix only) |
| Web typecheck/tests/build | not rerun — no web sources changed; baseline reused (tsc 0, 75/75, build OK) |
| Environment | Python 3.14.5 venv (hosted pin 3.12; no 3.13+ syntax introduced); PostgreSQL 17.11 disposable, deleted after run |

`validation_unavailable`: Git diff (no `.git`); hosted Supabase application of 004; production login playthrough; MFA/passkey enrollment (Supabase Auth dashboard configuration, not code); separate per-service machine identities (platform configuration).

## Acceptance mapping (§28 tenant isolation, §8, §9)

- enumerate/fetch/mutate/export/object/job/error paths: **verified on disposable PG**. Stream path: not applicable until Milestone B SSE exists.
- Job claims revalidate workspace + approve authority: verified (`postgres_safety.py` + isolation check 7).
- Errors do not reveal cross-tenant existence: verified (identical 403 message for foreign vs random UUID across nine paths).
- Roles owner/admin/editor/approver/viewer + four separate permissions: implemented and matrix-tested.
- Invitations expire (7 d), bind to workspace/role, single-use, hash-only at rest: verified.
- Session list + remote revoke; step-up for sensitive actions; login throttling: verified. MFA/passkey option: **blocked_external_gate** (Auth provider configuration).

## Actual external state

No deployment. No hosted DB change. Production remains as last observed 2026-09-14 (synthetic, `externalExecution:false`). Hosted code now **requires** migration 004 columns; deploying this code before applying 004 would break `transaction()`. Sequence is therefore: approve + apply 004 → deploy.

## Remaining gates (exact action previews)

1. **Apply migration 004 to the hosted Supabase project** (`buoyhkbodnhzngaotoel`, us-east-1). Additive; runs inside one transaction. Rollback script (only if needed): `drop table pr_auth_throttle, pr_sessions, pr_audit_events, pr_invitations; alter table pr_memberships drop column can_publish, can_reply, can_moderate, can_manage_connections, invited_by, updated_at; drop policy team_membership on pr_memberships; alter table pr_memberships drop constraint pr_memberships_role_check, add constraint pr_memberships_role_check check (role in ('owner','editor','viewer'));` and re-apply the 002 `pr_bootstrap` body. **Not executed. Awaiting approval.**
2. Deploy the updated API (after 1). **Not executed.**
3. Enable MFA/passkey in Supabase Auth settings. **Configuration, awaiting approval.**

## Rollback / recovery (source)

Hunk-level only. Verify each file's current SHA-256 equals the "after" hash in `evidence/changed-files.json`, then reverse-apply the corresponding hunks of `evidence/source-diff.patch`; delete the four new files. Re-run the unit suite and the PG trio.

## Next concrete action

Milestone B1: migration 005 (`pr_conversations`, `pr_messages`, `pr_attachments`, `pr_agent_runs`, `pr_agent_events`, `pr_skill_releases`, `pr_tool_releases`) and the `AgentRuntime` interface with §10.4 event translation (D4), fixture runtime first.
