# Milestone C receipt — Channels, scheduling, publication, receipts

**Date:** 2026-09-15 · **State:** implemented and locally verified with provider doubles · **External state:** unchanged (no deployment; no hosted migration; no provider app created; no OAuth grant; no post submitted)

## Connector selection (D12) — `connector-audit.md`
Fresh official-doc audit (79 URLs). Launch set: **LinkedIn (member posting, self-serve `w_member_social`)**, **Threads** (Meta App Review), **Instagram professional** (Meta App Review + Business Verification). Alternate: Bluesky (no review). Deferred: X (per-call billing), Facebook Pages, YouTube, TikTok, Pinterest, Mastodon.

## What changed

| Path | Change |
|---|---|
| `migrations/postriff/006_consumer_web_channels.sql` | **new, additive.** `pr_oauth_transactions` (state hashed, PKCE verifier encrypted, bound to workspace/member/provider/capability/redirect/expiry, single-use with outcome), `pr_encrypted_credentials` (application-layer ciphertext, key id, scopes, expiry, refresh flag, revocation), `pr_channel_capabilities` (per-capability level + evidence + version + verified_at). Credentials/transactions service_role-only; capabilities tenant-read. |
| `src/postriff_phase2/oauth.py` | **new.** `CredentialVault` (Fernet; key from `POSTRIFF_CREDENTIAL_KEY`, key-id bound, rotation-aware), `pkce_pair()` (S256), `OAuthService`: `start` (manage_connections, throttle, PostRiff-owned HTTPS callback only), public `callback_redirect` (never exchanges), `complete` (same workspace + same member, single use, expiry, denial path, exchange with verifier, identity confirmation, encrypted custody, scope-drift → Assisted, capability rows), `channels` (customer view), `token_for_worker` (server-only decrypt + refresh), `verify` (identity/scope re-check), `disconnect` (step-up, remote revoke, ciphertext wiped, approvals held). |
| `src/postriff_phase2/channels.py` | **new.** Capability taxonomy Direct/Assisted/Bridge/Unsupported per capability with mandatory evidence; connection-state dimensions `disconnected → identity_known → scope_missing/token_expired/reauthorization_required → read_verified → publish_verified`. |
| `src/postriff_phase2/providers.py` | **new.** LinkedIn/Threads/Instagram adapters (authorize URL, exchange incl. Meta short→long-lived, identity, refresh, revoke) over an injected bounded HTTPS transport; `registry_from_environment` mounts only with client credentials; `production_reviewed` only via explicit `POSTRIFF_OAUTH_<ID>_REVIEWED=true`. |
| `src/postriff_phase2/hosted_social.py` | **new.** Dedicated connector executor for `PostgresWorker`: LinkedIn `POST /rest/posts` (201 + `x-restli-id` → `provider_accepted`), Threads and Instagram container → publish; reconciliation by post lookup (text/permalink match → `verified`) or container status; 401/403 → `held`, 429 → `scheduled`, anything inconclusive → `uncertain`; unreviewed provider → `held` without network. |
| `src/postriff_phase2/contracts.py` | `resolve_time` records `tzdb` (time-zone database provenance). |
| `src/postriff_phase2/store.py` | `approve_many` groups destination jobs under one `scheduleId` (states stay per destination); `DAILY_LIMITS` (IG 100, Threads 250, LinkedIn 150 per 24 h) enforced at approval. |
| `src/postriff_phase2/hosted.py` | `HostedWorkspaceService.oauth`; `upsert_verified_channel` accepts audited platforms and a `capability_verified` flag (publish only when scopes granted to a reviewed app). |
| `src/postriff_phase2/hosted_app.py` | Routes: `GET …/channels`, `POST …/channels/{provider}/oauth/start`, `GET /api/oauth/{provider}/callback` (302 to app, drops unknown params), `POST …/channels/{provider}/oauth/complete`, `POST …/channels/{id}/verify`, `DELETE …/channels/{id}`; worker mounts `HostedSocial` only when a reviewed provider exists, else stays `DisabledHostedSocial`. |
| `requirements.txt` | `cryptography==50.0.1` (token custody). |
| `scripts/check_postriff_hosted_preflight.py`, `tests/phase2/rls.sql` | Require/load 006. |
| `tests/test_postriff_channels.py` (7), `tests/test_postriff_providers.py` (9), `tests/phase2/postgres_channels.py` (9 checks) | **new.** |

## Validation (observed)

| Check | Result |
|---|---|
| Python unit suite | **182 pass / 0 fail** (166 after B + 16) |
| PG on 004–006: `repository`, `safety`, `isolation`, `ideas`, `channels` | **all pass** (see run log; `channels` 9/9: state binding + hashing + encrypted verifier; cross-workspace/cross-member state unusable; denial consumes without storing; PKCE verifier reaches exchange, tokens encrypted at rest and absent from state/API, single-use state; scope drift → Assisted + `read_verified`; server-only refresh, credentials/transactions never browser-readable; expiry refused; disconnect needs step-up, revokes remotely, wipes ciphertext, worker loses token; audit without tokens) |
| Adapter request shapes (fake transport) | LinkedIn/Threads/Instagram authorize/exchange/identity/refresh/revoke; provider error → 502; registry env gating |
| Worker classification (fake transport) | unreviewed → `held` with zero network; LinkedIn 201+URN → `provider_accepted`, lookup PUBLISHED+text match → `verified`, 429 → `scheduled`, 403 → `held`, 200-without-evidence → `uncertain`; no read scope → `uncertain`; Threads container→publish, reconcile by id or container (`PUBLISHED` container ≠ `verified`); Instagram without image → `failed`; missing grant raises |
| Multi-destination | `approve_many` → shared `scheduleId`, independent per-destination cancel; `tzdb` recorded |
| Web | not rerun (no web sources changed) |

`validation_unavailable`: any real provider OAuth/token/publish/reconcile (no PostRiff provider app exists; no grant; adapters exercised only with doubles); production app review; non-founder test accounts; live rate-limit/revocation-mid-execution behavior; real signed-URL fetch by Meta for image containers; LinkedIn image upload path (candidate code exists in `provider_candidates.py`, not wired into `HostedSocial` text-first submit); calendar grid UI (Milestone E).

## Acceptance mapping (§28 Channels / Scheduling)
- Each connected account belongs to one workspace: `pr_encrypted_credentials` pk (workspace, connection); connection id derives from provider + account → the same account in a second workspace is a separate, explicitly authorized grant. Verified (PG).
- OAuth state/callback/confirmation/scopes/persistence/refresh/revocation/capability verification: **tested with doubles** (PG 9/9 + unit). Real provider: external gate.
- Public capabilities reflect production review state: `production_reviewed` flag → Direct only when true; otherwise Assisted/Unsupported with evidence text. Verified.
- identity/publish/schedule/analytics/comments/reply/moderation distinct: `pr_channel_capabilities` per capability. Verified.
- Unsupported/Bridge-only clear: taxonomy + evidence strings. Verified.
- Schedules survive restarts / DST / invalidation / duplicate prevention / reconciliation / partial success: pre-existing verified behavior retained (`postgres_safety.py`, unit), plus `scheduleId` grouping and `tzdb`. Multi-destination partial success now expressible.
- Agent text cannot invoke publish: unchanged; no tool path to `HostedSocial`.

## Actual external state
Nothing deployed or applied. Live execution remains **structurally off**: `runtime_from_environment` mounts `HostedSocial` only if a provider is both credentialed and flagged reviewed; neither exists in any environment.

## Remaining gates (exact action previews; none executed)
1. Apply 004 → 005 → 006 to the hosted Supabase project. Rollback for 006: `drop table pr_channel_capabilities, pr_encrypted_credentials, pr_oauth_transactions;`.
2. Set `POSTRIFF_CREDENTIAL_KEY` (generate with `CredentialVault.generate_key()`; store only in Vercel env), `POSTRIFF_PUBLIC_BASE_URL=https://<production domain>`.
3. Create PostRiff's LinkedIn app (Share on LinkedIn, `w_member_social`), register `…/api/oauth/linkedin/callback`; set `POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID/SECRET`. Do **not** set `_REVIEWED=true` until an end-to-end non-founder test account publishes and reconciles.
4. Create/confirm Meta app with Threads use case; submit App Review; then Instagram Business Verification + App Review. Same flag discipline.
5. Real publication test with an explicit, exact approval (account, content, timing, destination) — a separate authorization step.
6. Deploy (after 1–2), then run `scripts/validate_postriff_hosted_preview.py` against the deployment.

## Rollback / recovery
Hunk-level via `evidence/source-diff.patch` after hash check; delete the eight new files; `pip uninstall cryptography` not required (unused when vault key absent).

## Next concrete action
Milestone D1: migration 007 (`pr_subscriptions`, `pr_entitlements`, `pr_usage_ledger`, `pr_billing_events`, `pr_plan_terms`) and the reserve/settle/release ledger with a fixture payment adapter.
