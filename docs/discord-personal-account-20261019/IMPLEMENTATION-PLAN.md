# Discord personal-account implementation plan

> For agentic workers: execute inline with the installed executing-plans and test-driven-development workflows. Preserve the existing Discord release/acceptance lane. The user explicitly requested implementation after the PRD; no additional design-approval pause is required.

**Goal:** Make personal Discord account connection a first-class, explicitly non-publishing capability while preserving the existing authorized bot publishing path.

**Architecture:** Extend the current identity projection/callback and Channels UI. Reuse existing OAuth, vault, workspace/member permissions, bot installation, destination authorization and frozen-job machinery. No new provider credential, database schema or runtime deployment is needed for this additive source change.

**Tech stack:** existing Python/Next.js/React/TypeScript and existing local dependencies.

**Spec:** `RAFII-DISCORD-PERSONAL-ACCOUNT-PRD.md` (same directory); exact inspected baseline `63864bd6654f62a165c398ce4c493528aee6f501`.

## Global constraints

- Canonical Production: `postriff-phase2-private` / `buoyhkbodnhzngaotoel`; no staging substitution.
- No real provider messages, active publication jobs, production promotion/merge, new paid services, secret changes or shared scheduler changes in this implementation.
- Preserve all existing worktrees, active agents, untracked evidence, drafts and frozen reviews.
- The existing production-candidate is concurrently used for acceptance; use the additive owned `personal-account-source-20261019` worktree from the exact candidate, not a restart or a reset of the release lane.
- Preserve Vercel no-auto-build controls. Do not run deployments for a code/copy change. Restore dependencies only in the owned worktree, from the unchanged lockfile, when verified environment drift blocks validation; do not mutate shared dependencies.
- Historical CI passes qualify only their original commits. Local source/SSR tests are not real Discord or production-browser acceptance.
- Webhook and User Install engineering remain separately specified in PRD §§13–14. This source patch must not claim either path is implemented or enabled.

## Review focus

1. A stored or submitted identity field must never produce publish/schedule authority.
2. Same-member foreign-workspace and same-workspace foreign-member records must not leak through identity projection.
3. A linked account without `guilds` must receive a scope-upgrade choice, not an automatic failing discovery call.
4. Callback identity success must target a real identity surface, without a false Assisted/personal-publishing claim.
5. A paused/unconfigured provider or unauthorized workspace member must not gain an enabled connect control through the new presentation component.

## Task 1: Identity projection and OAuth explanations

Files: modify `src/postriff_phase2/discord/oauth.py`; add `tests/test_discord_personal_account_contract.py`.

Interfaces: `identity_capabilities() -> dict` returns fixed non-authority metadata; `DiscordConnections.public_identities(workspace, token)` projects only allowlisted fields from matching workspace/member records; `save_identity` returns the same contract. Existing publishing/grant methods are unchanged.

- [x] Run existing OAuth and installation baseline tests.
- [x] Write tests for explicit non-publishing projection/callback, secret exclusion, foreign records, missing session and least-privilege identity explanation.
- [x] Observe the expected baseline failures.
- [x] Implement fixed metadata, explicit workspace/member filtering and truthful OAuth permission text.
- [x] Run new tests plus existing Discord lifecycle/destination/publishing/worker regressions.

## Task 2: First-class Channels account section and callback

Files: add `web/src/features/channels/discord-personal-accounts.tsx`; modify `channels-view.tsx`, `connect-sheet.tsx`, `connect-return.tsx`, `web/src/lib/api/types.ts`; add `web/tests/discord-personal-account.test.cjs`.

Interfaces: a pure presenter receives actor-filtered `identities`, optional Discord provider, `canManage`, and `onConnect`/`onManage(identityId)` callbacks. `ConnectRequest.discordIdentityId?: string` selects only a matching existing identity when managing. API identity types add optional literal non-publishing fields for compatibility with older responses.

- [x] Test actual SSR component output for no-server empty state, linked identity display, paused provider, role restriction, safe escaping and no publishing action.
- [x] Implement the presenter using existing visual/control tokens and semantic controls.
- [x] Place it on Channels without changing existing bot/channel cards; name the empty publishing list accurately when personal identities exist.
- [x] Scroll callback identity success to the new real identity surface; preserve other provider callbacks.
- [x] Replace Discord-specific misleading Assisted text without altering unrelated provider semantics.

## Task 3: Missing server-discovery scope and selection safety

Files: add `web/src/lib/channels/discord-personal-account.ts`; modify `connect-sheet.tsx`; test helper in the new Node test file.

Interfaces: `discordDiscoveryState(identity) -> 'choose_identity' | 'reconnect_required' | 'scope_required' | 'ready'`; `discordCanConnect(provider, canManage) -> boolean`. These helpers control presentation only; server authorization remains authoritative.

- [x] Test absent/disconnected/reconnect-required identities, strictly boolean scope consent and a valid linked scope.
- [x] Disable server-list action unless the chosen identity has the required stored consent; show explicit permission-upgrade action that only prepares OAuth inputs.
- [x] Preserve the chosen account during management; require user interaction on the official authorization page.
- [x] Disable relevant mode/selection changes while busy; reject mismatched or stale discovery results.
- [x] Verify type compatibility and affected unit tests; do not manufacture current live permission from cached metadata.

## Task 4: Review and exact-source evidence

- [x] Run the applicable full local Python discovery and Node test commands when supported; report skips/environment errors exactly.
- [x] Run TypeScript checking against the unchanged lockfile; distinguish source check from Next build. Any isolated dependency restoration must be recorded.
- [x] Review changed paths, authorization boundaries, strings and accidental unrelated changes.
- [x] Save raw test logs, status, patch and exact file hashes. Commit only explicit owned paths.
- [x] Preserve the original release lane unchanged. A feature-branch push is not public release; retain no-auto-build controls.
- [x] Deliver PRD, implementation status and the precise unverified hosted/live/additional-mode gates.

## Execution ledger

Ruling: isolate the additive extension from the already isolated production-candidate, because that worktree belongs to the concurrent OAuth/acceptance continuation. This retains the exact existing source and avoids taking ownership of another agent’s writes; it adds a reconciliation step before integration.

Ruling: the first implementation delivery covers the actual personal-account UX and explicit capability boundary. Webhook and user-installed-app runtime are not asserted to exist; their complete specifications and external acceptance obligations remain in the PRD. No successful source test will be used to close those tasks.

Ruling: replace the initial no-install assumption with isolated exact-lock dependency recovery. The main node_modules tree was incomplete and mismatched the project lock (Next 16.3.5 installed versus 16.3.8 locked; OpenUI/GSAP/thinking-orbs absent). Only the new worktree symlink was removed; npm ci --ignore-scripts --no-audit --no-fund --prefer-offline restored its private tree without changing package files or the shared dependency directory. Receipt dependency-restore.json reports returncode 0; the restored TypeScript check also returned 0. This addresses environment drift rather than suppressing diagnostics.

Ruling: strengthen request-context handling after whole-diff review. OAuth-start and discovery responses must match the current generation; changing provider or preparing identity reconnection clears stale guild selection. Two additional wiring tests were observed failing, then all 11 personal-account Node/SSR/wiring tests passed after the correction. These are not running-browser interaction tests.

Task 1: source implementation and scoped RED/GREEN tests complete. Baseline 40 tests passed; six new backend tests passed; Discord regression suite reported 261 tests passed before the final copy-only backend correction. The final full Python gate remains separately recorded.
Task 2: source implementation and actual component SSR tests complete; running-browser accessibility/responsiveness is unverified.
Task 3: helper and request-wiring implementation complete; 11 combined Node/SSR/wiring tests passed.
Task 4: local verification, explicit failure reporting, review, packaging and checkpoint commit/push completed. The exact runtime/test hashes were verified before commit 0c3e1bf615bce1213d786ce1e8c87e7875701e44. The worktree was clean, the feature branch was pushed without force, and the remote SHA matched. No new PR or Production deployment was made. Completing these execution steps does not mean the full Python/browser/live gates passed; consult IMPLEMENTATION-STATUS.md and the raw receipts.

Final verification: 261 Discord tests passed; all 990 web unit tests passed; TypeScript exit 0; lint 36 warnings/0 errors. Initial full Python failures were retained. After restoring missing tracked source and an isolated pinned Python environment, 29 recovery modules ran 443 tests with 12 skips and no failures. Two unchanged Linux-renderer modules remain unresolved on macOS, and there is no subsequent full-green Python claim.

## Approved multi-mode continuation (2026-10-19)

Base 0c3e1bf615bce1213d786ce1e8c87e7875701e44, owned branch only. The earlier first-delivery scope is superseded for engineering, not its historical evidence. No external activation, registration, sends, jobs, database application, deployment, push or spend.

1. **Webhook custody and protocol.** Extend `discord/oauth.py`, `social_connectors.py`, `oauth.py`: purpose `webhook`, v2 state/issuer/PKCE, independent identify proof and fixed-path webhook GET proof, encrypted kind=webhook envelope, namespaced connection, explicit existing choose_destination consent. Add `discord/webhooks.py` for strict resource/payload/transport contracts. No URL input or bot fallback. Tests `test_discord_multimode.py` and existing OAuth/installation regressions.
2. **Same publication lane.** Extend `discord/authorization.py`, `hosted_social.py`, existing worker grant custody in `oauth.py`: distinct webhook target/sender in frozen digest, existing review/approve/job/cancel/lease/rate admission/seal/consume, wait=true create, known-ID GET readback only, no uncertain create retry. Extend `discord/rate_limits.py` using secret-hashed webhook major identity, never token in ledger. Preserve legacy bot frozen manifests. Synthetic tests exercise actual engine/worker/transport, before-approval denial, wrong-kind/tenant/generation/revoke/unknown/cancel.
3. **Signed private interactions.** Add `discord/interactions.py`, mounted raw HTTPS route in `hosted_app.py`; persistent replay and explicit actor/workspace binding with additive collision-checked migration; authenticated bind/unbind API validates own linked identity. Ed25519 cryptography already installed; raw timestamp+body, strict app/context/owner/user, signed PING; bounded private draft/review link only. Dry-run registration/config readback validator in `scripts/discord_user_install_config.py`; exact command ID/version configuration required. Tests `test_discord_interactions.py`, persistent SQL fixture.
4. **UI and locales.** Extend existing Channels connection sheet/personal-account surface, API types and existing schedule/review UI. Show identity/bot/webhook/user-install status distinctly; flags default OFF and exact qualification required. Sender frozen and visible; identity never target. Reuse existing translation packs/control tokens. Add real running-browser synthetic fenced harness for no-server/scope-upgrade/wrong-subject/stale/callback/sender/unavailable/mobile/desktop/keyboard; no live origins.
5. **Evidence.** RED before implementation, GREEN after; existing Discord regression, full web tests/static via authorized existing route, synthetic loopback browser, SQL/RLS fixture. Preserve logs and source SHA256 acceptance matrix. Final Linux/full persistent/live acceptance stays open if unavailable; never mark source-only or synthetic as live.

### Audit findings
Existing `DiscordConnections` uses encrypted single-use OAuth rows and workspace/member transactions. `HostedSocial.prepare_discord_dispatch` -> rate reservation -> `PostgresWorker._seal_discord_dispatch` -> authorize rate consumption -> submit is the canonical path. `freeze_manifest`/`job_authorized` bind review and worker. Generic choose_destination already separates destination consent. Worker receipt/recovery/cancel and generation fencing are retained. Existing rate templates reject webhooks and existing provider.session/grant assume bot; these need explicit kind dispatch, not forged bot IDs. Current JCB doctor exits 2 (Depot authentication unavailable); no remote job submitted. Token Pilot enrollment preview includes protected read-only .agents/.codex paths, so enrollment_blocked; no installer application or hook trust changes.

### Private command entry refinement

Interaction responses link to `/app/queue/discord?workspaceId=...&identityId=...`. Add authenticated `GET /api/workspaces/{workspace}/discord/private-review/{identity}` validating the current actor's own active mapping and identity generation before the UI selects that workspace and opens Queue. Files: `discord/interactions.py`, `hosted_app.py`, API client, `features/channels/discord-review-entry.tsx`, `app/app/queue/discord/page.tsx`. This avoids an ignored workspace query or browser-selected fallback. No draft content or token enters the interaction. Bounded storage uses one checkout (pool 200ms, standalone connect2s, SQL300ms/lock100ms); deny a success beyond the internal2s deadline. Hosted3s latency acceptance remains external.
