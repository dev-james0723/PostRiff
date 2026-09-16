# Pairing, synchronization and security acceptance

State: local contracts and disposable local PostgreSQL; not hosted or physical two-device acceptance.

## Implemented boundaries

- Separate Phase 3 SQLite database and `p3_runtime` state. Account/profile/draft domain remains the existing implementation. Device identity is separate from PostRiff session and social account capabilities.
- Five-minute, single-use 64-bit random enrollment code; exact actor/workspace/name confirmation in native dialog; at most five attempts per actor in five minutes. Rejected guesses are committed to avoid rollback defeating rate limits.
- Main-only pairing secret; browser request alone cannot confirm. Device credential encrypted with Electron safeStorage; database stores its hash. Neither credential nor hash is returned in workspace projection/export.
- Workspace membership and role checked at request, claim and result boundaries. Jobs bind actor/device/operation/source hash/voice/brief/type/template/skill versions, expiry and idempotency. No cross-workspace discovery or writes.
- Durable claim, attempt, lease and event cursor; duplicate claim never starts again. Disconnect/lease expiry requires reconciliation. Revocation blocks new claims/result writes; previously accepted candidates persist.
- Exact source selection, approved active facts, versioned voice and neutral skill overrides. Local-only voice/source eligibility requires explicit choices before managed execution; eligibility is not a claim of upload or synchronization.
- Pending edits are local browser/device data. Explicit save uses expected variant/workspace revisions and an idempotency key. A conflict retains the unsent text and shows current saved text before rebase. Pairing uploads no home directory or cache.
- Agent output is schema-checked and kept as a candidate. Existing customized variants receive a proposed update. Portable profile results enter the existing field-level review. No publishing approval is created.
- Renderer Node disabled, context isolation and sandbox enabled, permissions denied, exact sender/frame checks, finite IPC, constrained navigation/window opening, local CSP. No shell or generic filesystem IPC.
- File helper opens each path component with `O_NOFOLLOW`, rejects traversal/symlinks/non-regular files and verifies an approved hash. Real Codex/Gemini execution remains disabled until their broader runtime isolation is qualified.

## Evidence

- `evidence/phase3-focused.log`: focused contract, process fixture, managed transport/accounting, source/profile, export, two-customer and recovery checks.
- `evidence/postgres.log`: fresh disposable PostgreSQL 17 cluster, additive migration, paired-device heartbeat, two users/workspaces, stale revision rejection, direct browser denial and revoked membership rejection. Cluster stopped after tests.
- `evidence/desktop-acceptance.json`: packaged macOS launch outside development working directory, synthetic account/source/drafts, independent edit, offline pending text, restart, encrypted vault persistence and revocation. The native confirmation response is injected by the test harness; this does not represent an actual user's approval or hosted test.
- Desktop/mobile screenshots: responsive UI, readable source/recovery states and no horizontal overflow. Keyboard focus, reduced-motion mode and zero page errors tested. This is not a formal accessibility certification.

## Migration / rollback

`migrations/postriff/003_phase3_runtime.sql` is additive: one private runtime table, forced RLS, no anon/authenticated grants, service-only access, workspace deletion cascade. Credential hashes are not put in browser-readable workspace JSON. It was applied only to the disposable local cluster. `HostedRuntimeService` reuses existing verified principal/workspace transactions and is not mounted or deployed to Preview.

Rollback local UI/source using only the scoped backup/diff after checking subsequent changes. Keep the separate Phase 3 database/vault and exports for recovery. Quit the app to stop its sidecar. Do not automatically delete retained work or run a destructive down migration. For a later hosted rollout, disable runtime endpoints/workers first and preserve jobs for reconciliation before any table removal.

## Exact remaining acceptance

- Hosted desktop sign-in/enrollment confirmation transport, remote endpoint mounting, protected credential handoff to an external native agent, and genuine two-device sync are not qualified or deployed.
- Cloud model execution, quota recovery and native resume/cancellation semantics remain untested for real providers.
- Physical sleep/wake and a second physical device were not tested; process restart, simulated network loss and leases are lower-level checks.
- Windows installation/runtime, signing, notarization, auto-update and public distribution: `validation_unavailable` (no corresponding environment/authorization).
- The synthetic Instagram fixture preserves English quotations rather than claiming a model translated them. Real bilingual output and editorial quality remain provider acceptance work.
