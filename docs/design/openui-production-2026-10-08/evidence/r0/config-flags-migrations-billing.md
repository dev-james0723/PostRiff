# R0 map — config / flags / migrations / billing / privacy (lanes A + B)

Reader: read-only R0 baseline for role A. Worktree `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`,
branch `claude/rafii-openui-production-20261008`, HEAD `3da806f0` (= `origin/consumer-saas` `3da806f0e31a01396a3bd4a9e27f66f9b21ce816`).
Git remote metadata from the shared `.git/FETCH_HEAD`, dated 2026-10-08 12:18 local. No fetch was run.

Labels:
- **[V]** verified code/file fact at this SHA. Paths are repo-relative and `:N` is a line number.
- **[D]** documented in the repo (release receipts and docs), but not re-checked live.
- **[I]** inference or recommendation.
- **[U]** unknown. It needs a live check that this reader did not run.

No secret values appear below. Env var names, Supabase project refs and Vercel project IDs are identifiers that are already committed to the repo.

---

## 1. Feature-flag mechanisms (there is no single flag system)

### 1.1 Agent Runtime v2 flags: `src/postriff_phase2/agent_runtime_v2/config.py`
- [V] `FLAGS` tuple at `:21`: `RAFII_AGENT_V2_ENABLED`, `RAFII_VOICE_ENABLED`, `RAFII_IMAGE_AGENT_ENABLED`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_PROACTIVE_V2_ENABLED`, `RAFII_AGENT_THINKING_STATES_ENABLED`.
- [V] `_flag(values, name)` at `:67`. A flag is true only for `1|true|yes|on`, case-insensitive. Everything else is off.
- [V] `RuntimeConfig.from_environment(values=None)` at `:102-136`:
  - Reads `os.environ` once, when `AgentRuntimeService.__init__` runs (`service.py:63`). The runtime is cached per hosted service in `http.runtime_for` (`agent_runtime_v2/http.py:23-43`), so env is effectively read once per process.
  - Produces `flags={name: _flag(...) for name in FLAGS}`, model aliases, provider, base URL, prices, image estimates, tracing, and key presence. Keys stay in a private `_env` and are read by `credential()` at `:143`.
- [V] Provider selection at `:106-115`:
  - Accepted values of `RAFII_AGENT_PROVIDER` are `openai` and `gateway`. Any other value raises `ValueError`.
  - Default is `openai` when `OPENAI_API_KEY` is set, else `gateway` when `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` is set, else `None`.
  - A requested provider without its key becomes `None`. The config never substitutes another provider.
- [V] Model aliases at `DEFAULT_MODELS` `:28-35`:

  | Env var | Default |
  |---|---|
  | `RAFII_AGENT_PRIMARY_MODEL` | gpt-6-sol |
  | `RAFII_AGENT_FAST_MODEL` | gpt-6-luna |
  | `RAFII_AGENT_VISION_MODEL` | gpt-6-sol |
  | `RAFII_AGENT_IMAGE_MODEL_QUALITY` | gpt-image-2.5-sunburst |
  | `RAFII_AGENT_IMAGE_MODEL_FAST` | gpt-image-2.5-flare |
  | `RAFII_LIVE_MODEL` | gpt-live-1 |

- [V] Workloads at `WORKLOADS` `:40`: `deterministic`, `fast_language`, `standard_reasoning`, `deep_reasoning`, `vision`, `voice_front_end`, `image_fast`, `image_quality`. The alias map is `_ALIAS_FOR` at `:41-49`.
- [V] `route(workload, *, reason) -> Route` at `:159-172`.
  - An unknown workload raises `ValueError`.
  - Voice needs `OPENAI_API_KEY`.
  - With no provider, it returns `available=False` plus a blocker string.
  - The Route dataclass (`:71-83`) has `workload, provider, model, reason, available, blocker`.
- [V] `public()` at `:184-188` returns `{"flags", "models", "provider", "voiceAvailable", "imageAvailable"}` and never a credential.
- [V] `choose_reasoning()` at `:191-201` is the deterministic Manager workload picker.
  - `deep_reasoning` is chosen for keywords such as compare, plan a, campaign plan, strategy, analy, 計劃, 策略, 分析, or `steps_hint>=3`.
  - Any attachment selects `vision`.
- [V] Other runtime env vars:
  - `RAFII_AGENT_BASE_URL`
  - `RAFII_AGENT_MODEL_PRICES`: JSON object of model → [in, out] USD/MTok.
  - `RAFII_AGENT_IMAGE_PRICES`
  - `RAFII_AGENT_OPENAI_TRACING`
  - `RAFII_AGENT_HARNESS`: local QA only, refused on Vercel (`harness.enabled()`, used at `http.py:29`).

### 1.2 Coworker flags: `src/postriff_phase2/coworker/flags.py`
- [V] `FLAGS` at `:12-47` holds 35 `RAFII_*` coworker and trend flags. `EGRESS_FLAGS` is at `:50-53`.
- [V] `enabled(name)` at `:81` raises `KeyError` for an unknown name. That is fail-loud, so a new name must be added to the tuple.
- [V] `attach(values)` at `:62` pins the hosted app's isolated environment. `public()` at `:92` returns `{"flags": snapshot}`.
- [V] The module docstring at `:3-6` sets the rule: "Flags reach the browser only through the coworker status payload (`public()`), never as NEXT_PUBLIC_* build flags."

### 1.3 Preview isolation: `src/postriff_phase2/deployment.py:6-76` (`isolated_environment`)
- [V] When `VERCEL_ENV=preview`, the function requires all of the following:
  - `POSTRIFF_ENVIRONMENT=staging`
  - `POSTRIFF_STAGING_PROJECT_REF` and `POSTRIFF_PRODUCTION_PROJECT_REF`, distinct from each other
  - Supabase URLs matching staging
  - a TLS staging DSN
  - an exact `POSTRIFF_STAGING_PUBLIC_BASE_URL`
  - test-only Stripe keys
  - `POSTRIFF_STAGING_SECRET_SHA256` pins for named secrets
- [V] Preview also forces these off:
  - `POSTRIFF_RESEARCH=0` and `POSTRIFF_LOCAL_CLI=0`
  - every egress flag at `:59-69`, including phone, SMS, scout and trend flags
  - growth flags at `:71-75`
- [V] In production (`VERCEL_ENV != preview`) the env passes through unchanged.
- [I] The GenUI flags are not egress flags as long as the Presenter uses the same provider route as the Manager. They do not need to join the preview kill list. If A wants preview to test GenUI, preview must already satisfy the staging pins.

### 1.4 Other flag families (all env, all default off)
- [V] Phone: `phone/contracts.py:16` defines `RAFII_PHONE_ENABLED` and the `_OUTBOUND/_INBOUND/_SCHEDULED/_PROACTIVE/_VERIFICATION_ENABLED` flags.
- [V] Chat media: `hosted_app.chat_media_from_environment` at `hosted_app.py:180-187` reads `RAFII_CHAT_ATTACHMENTS_ENABLED`, `RAFII_MEDIA_NOTES_ENABLED` and `RAFII_VIDEO_UPLOADS_ENABLED`.
- [V] Productivity connectors: `productivity_connectors.py:31-32` reads `RAFII_NOTION_CONNECTOR_ENABLED` and `RAFII_GMAIL_CONNECTOR_ENABLED`.
- [V] Billing and ops: `POSTRIFF_CREDITS_ENABLED`, `POSTRIFF_CREDIT_PURCHASES_ENABLED` and `POSTRIFF_REPLY_SENDING_ENABLED` (`hosted_app.py:209`).
  - `POSTRIFF_BUDGET_POLICY` (`billing.py:87`).
  - `POSTRIFF_AI_PAUSED=1`, the operator kill switch for all paid AI (`billing.py:97-99`).
  - `POSTRIFF_LIVE_CHARGES_ENABLED`.
- [V] Writer route: `POSTRIFF_MODEL_ID`, `POSTRIFF_MODEL_IDS`, `POSTRIFF_MODEL_PRICES`, `POSTRIFF_FEATURED_MODEL_IDS` and `AI_GATEWAY_ENDPOINT` (`hosted_app.py:120-140`).
- [V] Scoped-admission env patterns. These are the only existing "canary audience" mechanisms:
  - `POSTRIFF_METRIC_WORKSPACE_ALLOWLIST` (`growth/metric_schedule.py:29,46-54`). It holds explicit UUIDs only. Empty, wildcard or malformed input admits nobody.
  - `RAFII_AI_UNLIMITED_USER_IDS` (`developer_usage.py:10-17`). It is a quota exemption, not a permission.
- [V] Build-time web flags: the only `NEXT_PUBLIC_*` feature flags are `NEXT_PUBLIC_RAFII_THINKING_ORBS`, `NEXT_PUBLIC_PASSKEY_SIGN_IN`, `NEXT_PUBLIC_SENTRY_DSN` and `NEXT_PUBLIC_SENTRY_DISABLED`, plus `NEXT_PUBLIC_APP_URL` and the Supabase vars.
- [V] No DB-backed feature-flag table exists. A search for `pr_feature`, `pr_flags`, `feature_controls` and `runtime_flags` found nothing.
  - DB-held per-workspace "markers" do exist in `pr_workspaces.state`, for example `state.founderOps` (`billing.ops_metadata`, `billing.py:24-35`) and `state.accountBlock` (`operator_actions.py`).
  - Founder settings are in migration 070. They are founder-only.
- [I] Every env flag change on Vercel needs a new deployment to take effect. This is platform behaviour, not checked in the repo. The fastest existing emergency path is Vercel instant rollback (promote the previous deployment), as documented in `docs/releases/rafii-library-20261007.md:13`.

### 1.5 How flags reach the web
- [V] Route: `GET /api/workspaces/{id}/agent/status` → `agent_runtime_v2/http.py:53-54` → `AgentRuntimeService.status` (`service.py:75-86`).
  - It requires the `read` role.
  - It returns `{"runtime": "agent-runtime-1", **cfg.public(), "canUseModel": member.allows("edit"), "voice": {available, blocker}, "manager": {available, blocker}}`.
- [V] The web client calls `createAgentApi().status` at `web/src/lib/agent-runtime/client.ts:57`.
  - The type is `AgentStatus` at `web/src/lib/agent-runtime/types.ts:155-165`, with `flags: Record<string, boolean>`.
  - The hook is `useAgent()` at `web/src/lib/agent-runtime/use-agent.ts:10-21`, with React Query key `['agent-runtime','status',workspaceId]` and a 60 s `staleTime`.
  - Consumers: `web/src/features/site-agent/chat.tsx:103` (`agentOn = status.manager.available`) and `:164` (voice = `flags.RAFII_VOICE_ENABLED && flags.RAFII_AGENT_V2_ENABLED`).
- [I] Any name added to `config.FLAGS` appears automatically in `status.flags` with no TS type change. The recommended addition is a computed `genui: {available, actions, edits, blocker}` block in `status()` that applies role, route, price and allowlist checks server-side. The browser should never derive eligibility from raw flags.
- [V] The coworker status payload is `coworker/http.py:152` (`area == "status"`), the `flags.public()` source.

### 1.6 Production flag evidence
- [D] `docs/releases/founder-full-activation-20261002/effective-configuration.json` is a read-only production Vercel config read on 2026-10-02. It showed:
  - `RAFII_AGENT_V2_ENABLED=true`
  - `RAFII_CONTROL_ENABLED=true`
  - `RAFII_CONTROL_MOUNT=embedded`
  - `RAFII_CONTROL_ENVIRONMENT=production`
  - `RAFII_FOUNDER_CALLS/EMAIL/PUSH/VOICE_ENABLED` absent
- [D] `activation-readiness.json` marks the "Founder text agent" as `configured_off` (`ops_workspace_not_ready`, `approved_policy_not_saved`).
- [D] `metric-disposition.json:1258` says `POSTRIFF_CREDITS_ENABLED` was unset (credits off).
- [U] Current values of `RAFII_AGENT_PROVIDER`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_VOICE_ENABLED`, `POSTRIFF_BUDGET_POLICY`, `POSTRIFF_CREDITS_ENABLED` and `POSTRIFF_AI_PAUSED` on production today. They need a read-only Vercel env check.

### 1.7 Suggested GenUI flags (from `05-RELEASE-RUNBOOK.md:17-23`) and where to put them
- Suggested names: `RAFII_GENUI_ENABLED`, `RAFII_GENUI_ACTIONS_ENABLED`, `RAFII_GENUI_EDITS_ENABLED`, `RAFII_GENUI_FOUNDER_ENABLED`.
- [I] Put them in `agent_runtime_v2/config.FLAGS`. That gives one reader, exposure through status, use by founder turns, and the same `_flag` semantics.
- [V] The founder runtime reuses the consumer `base.cfg` (`rafii_control/founder_agent.py:300-306`: `FounderAgentRuntime(scoped, base.cfg, ...)`), so `cfg.enabled('RAFII_GENUI_FOUNDER_ENABLED')` works inside founder turns.
- [V] `rafii_control.hosted` hands ControlApplication only env keys that start with `RAFII_FOUNDER_` (`rafii_control/hosted.py:97-100`). A flag named `RAFII_GENUI_FOUNDER_ENABLED` is therefore not visible in `ControlApplication.flags`. Read it through `base.cfg`, or name it `RAFII_FOUNDER_GENUI_ENABLED` if founder_activation readiness must list it (`founder_activation.py:20-25` keys feature IDs to `RAFII_FOUNDER_*` flags).
- [I] Canary audience: add `RAFII_GENUI_WORKSPACE_ALLOWLIST`, following the `metric_schedule.allowed_workspaces` pattern (UUIDs only; empty = nobody), plus an explicit `RAFII_GENUI_AUDIENCE=allowlist|all`. "All eligible" must be an explicit value, never inferred from an empty list.

---

## 2. Role, plan and entitlement eligibility

- [V] `src/postriff_phase2/permissions.py`:
  - `ROLES` (`:10`): owner, admin, editor, approver, viewer.
  - `FLAGS` (`:11`): can_publish, can_reply, can_moderate, can_manage_connections.
  - `CLASSES` (`:15-25`): read (all), edit (owner/admin/editor), approve (owner/approver or `can_publish`), owner, and others.
  - `ACTION_CLASSES` (`:27-55`). Unknown actions default to `edit`. Owner-only actions include `memory_egress`, `research_egress`, `connector_egress`, `writer_defaults`, `media_egress`, `voice_sample_grant` and `raffi_recurrence_*`. Approve-class actions include `raffi_run_decide/commit` and `p2_approve`.
  - `STEP_UP_ACTIONS` (`:57`) with a 600 s window.
  - `Membership.allows()` at `:74`. `require()` at `:92` raises 403 with the message "This action needs the '<req>' permission".
- [V] The Agent Manager gate is `_front_door` (`service.py:141-167`). It falls back to the site agent when:
  - `RAFII_AGENT_V2_ENABLED` is off → `runtime_off`
  - the member is not `edit` → `role_grounded`, so viewers never trigger model spend
  - there is no `standard_reasoning` route → `no_model_route`
  - the intent is forbidden or a greeting
- [V] `status()` reports `canUseModel = member.allows("edit")`.
- [V] There is no plan-based feature gating for the agent.
  - Plans are `pr_plan_terms.plan in ('trial','studio','assist')` (`migrations/postriff/007_consumer_web_billing.sql:6-25`). All rows are seeded `status='proposed'`.
  - Entitlements (`pr_entitlements`: writing_batches_remaining, media_credits_remaining, ...) apply only to `charge_batch` reservations and images. Agent reservations use `charge_batch=False` (`service.py:664`).
  - Paid-AI eligibility is enforced by budgets (`billing.Ledger.reserve`). A budget must be `approved`, which happens only through `POSTRIFF_BUDGET_POLICY`. Otherwise the reservation fails with 402 "Paid AI drafting is not switched on yet."
- [I] GenUI eligibility should use the same rule as the Manager. Generating needs:
  - `RAFII_GENUI_ENABLED`
  - the workspace in the allowlist or audience=all
  - the `edit` role
  - an available, priced route
  - budget acceptance at reservation time

  Reading or replaying a stored artifact needs only `read`. Actions keep their original domain class (`approve` or `owner`) through `permissions.require_action`.

---

## 3. Founder authentication, flags and routes (J09 seam)

- [V] Founder Control is embedded in the consumer API. In `hosted_app.py:489-497`, any `/api/control/v2/*` path goes to `rafii_control.hosted.embedded_app(os.environ, ...)`. Consumer bearer, guard and runtime do not apply there.
- [V] The boundary is `rafii_control/auth.py`:
  - `CAPABILITIES` (`:17-22`) include `copilot.use` and `founder.agent.turn`.
  - `Boundary` (`:159+`) requires `assurance == 'aal2'` with MFA no older than 300 s for session exchange (`:184`). A stored session must be `aal2` (`:212`).
  - Sessions use a cookie (`COOKIE`) and CSRF (`csrf_token`).
  - `Config` (`:45-118`) reads `RAFII_CONTROL_ENABLED`, `RAFII_CONTROL_MOUNT` (`separate|embedded`), `RAFII_CONTROL_ENVIRONMENT`, `RAFII_CONTROL_ORIGINS`/`RAFII_CONTROL_ORIGIN`, `RAFII_CONTROL_SUPABASE_URL`, `RAFII_CONTROL_STAGING_PROJECT_REF` and `RAFII_CONTROL_PRODUCTION_PROJECT_REF`.
- [V] Founder agent routes (`rafii_control/http.py:273-281`):
  - `POST /api/control/v2/agent/turns` needs the `Idempotency-Key` header, regex `[A-Za-z0-9:_-]{8,200}`.
  - `GET /agent/runs/{ID}`, `POST /agent/runs/{ID}/cancel`, `GET /agent/conversations/{ID}/state`.
  - Capability is `copilot.use` (`:326,339`). The POST budget purpose is `founder.agent.turn` (`:183`).
- [V] Extension routes:
  - `http.register_route(method, pattern, capability, module, function, step_up=, budget=, demo_ok=)` (`:26-33`). Patterns are full-match against the path after the prefix is stripped.
  - Extension routes are matched before the hardcoded `/agent/*` routes (`:247-255`).
  - The precedent is `founder_voice.py:536-547`, which registers `/agent/voice/...` with `copilot.use` and budget `founder.agent.turn`.
- [V] Founder transport limits:
  - Deadline is 270 s for `/agent/*` (`http.py:64-73`) and 10 s for ordinary reads.
  - POST body is capped at 32,768 bytes (`:101`) with `application/json` required.
  - Responses are JSON with `Cache-Control: private, no-store`. ControlApplication has no streaming path today.
- [V] `FounderAgentRuntime(AgentRuntimeService)` (`founder_agent.py:368+`):
  - It runs on `RAFII_FOUNDER_OPS_WORKSPACE_ID` as a scoped principal (`scoped_service`, `:285-298`).
  - It has no site-agent fallback.
  - Conversation namespaces are `[founder:<mode>:<environment>]`.
  - `reservation_approval = founder_reservation_approval` (`:278-283`) returns `(None, {"costCenter": "founder_ops"})`.
  - Founder spend is capped by `founder_policy.policy_from_marker` and `spending()` inside `Ledger.reserve` (`billing.py:190-201`), which raises 402 "Founder daily spending limit reached."
- [I] Recommended founder GenUI route family is `/api/control/v2/agent/ui/...`, registered through `register_route(..., 'copilot.use', ..., budget='founder.agent.turn')`.
  - Streaming would need a new ControlApplication code path, because current responses are JSON. Alternatively, founder presentation can use persisted-snapshot polling and replay, with honest labelling.
  - Keep patch bodies ≤ 32 KiB, which matches the contract's patch cap.

---

## 4. Migrations

### 4.1 Files at `3da806f0` (`migrations/postriff/`)
- [V] Present:
  - 001–002, 003 (local-only, skipped by the runner)
  - 004–025, 030–046, 049, 051–060, 062–071, 088, 093–096
  - `hosted-004-008.sql` and `hosted-precheck.sql`, which are not numbered and not picked up by the runner glob
- [V] Gaps: 026–029, 047–048, 050, 061, 072–087, 089–092, 097+. The highest number is **096** (`096_universal_library_duplicate_index.sql`).
- [V] Number policy is uniqueness only.
  - `scripts/postriff_migrate.py:15-19` (`migrations()`) globs `[0-9][0-9][0-9]_*.sql`, raises `ValueError('Duplicate migration numbers')` and drops `003_`.
  - `tests/test_migration_numbers.py:16-31` covers uniqueness and duplicate refusal.
  - Contiguity is not required.

### 4.2 Authoring conventions (enforced by tests and established by precedent)
- [V] `tests/test_migration_numbers.py:38-59` (for 031), followed by later files such as 093:
  - outer `begin;` / `commit;` lines
  - every `create table` or `create index` uses `if not exists`
  - no `drop` and no `truncate`
  - no `storage.` DDL
  - `enable` and `force row level security`
  - `revoke all on public.%I from public, anon, authenticated`
  - `grant all ... to service_role`
  - `create policy service_only ... for all to service_role using (true) with check (true)`
  - no grants to `authenticated` or `anon`
  - Template code: `031_chat_media.sql` tail and `093_universal_library.sql:61-69`.
- [V] RLS harness: `tests/phase2/rls.sql` `\ir`-loads migrations, and the test asserts they are in sorted order (`test_migration_numbers.py:54-59`).
  - 093 loads at `:56`. Seed data follows, then 094–096 load at `:142-144`.
  - **A new migration must be appended after `:144`.**
- [V] Full ledger suite: `tests/phase2/postgres_consumer_migrations.py`. It applies 001–012, then a populated upgrade with all migrations, replay, checksum-tamper refusal, `pg_dump` and restore, and a fresh install.
- [V] Disposable-PG runner: `scripts/postriff_pg_suite.py`. It creates a new cluster per `tests/phase2/postgres_*.py`, loads `rls.sql`, and reads `POSTRIFF_PG_BIN`.
- [V] CI: `.github/workflows/library-release.yml:9` triggers on `migrations/postriff/**`, and `rafii-control.yml:4` on 049–07x. Both run PostgreSQL 17 in the cloud. Other workflows run `scripts/postriff_pg_suite.py <names>`.

### 4.3 Runner and production application
- [V] `scripts/postriff_migrate.py`:
  - `plan(db)` (`:28-37`) reads the ledger `postriff_private.schema_migrations(name, sha256, applied_at)`.
  - It refuses: a DB with migrations absent from the release, a checksum drift, and a schema without a ledger.
  - `apply(db)` (`:39-51`) takes `pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))`, executes `body(path)` with `prepare=False`, and inserts ledger rows.
  - The CLI applies only to loopback (`:53-64`). The docstring says production needs "its separately reviewed runner/approval."
- [V] Production practice, pattern 1: pinned per-release runners. Examples are `docs/releases/caller-identity-045/migrate_045.py` and `docs/releases/inbound-042/migrate_042.py`.
  - The runner hard-codes `SQL_SHA` and checks the file checksum.
  - It asserts `POSTRIFF_DATABASE_URL` host = `db.buoyhkbodnhzngaotoel.supabase.co`, or the pooler with user `postgres.buoyhkbodnhzngaotoel`.
  - It asserts `VERCEL_ENV=production` and `VERCEL_PROJECT_ID=prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`.
  - Default mode is read-only (`SET TRANSACTION READ ONLY`). `--apply` adds `lock_timeout 10s`, `statement_timeout 60s` and the same advisory lock.
  - It refuses a partial shape, then verifies columns, constraints, indexes, forced RLS, `service_only` policies and grants.
  - It inserts the ledger row only when the ledger exists.
  - Connection: `psycopg.connect(dsn, autocommit=True, prepare_threshold=None, connect_timeout=15)` (`migrate_045.py:242`). This is the "prepare_threshold=None" prod DB runner method.
  - [D] The runner executed inside an **intentionally non-promotable Vercel production-environment build** (`caller-identity-045/apply.log`: `dpl_85gLw6w9td2aQfnKN8ThuewDYdFW`, "intentionally non-promotable build"). A read-only preflight build ran first (`RAFII_CALLER_IDENTITY_2026-09-28.md:11`).
  - [D] Ordering rule: the migration must verify and commit **before** app promotion (`RAFII_CALLER_IDENTITY_2026-09-28.md:9`).
- [D] Production practice, pattern 2: Supabase MCP `apply_migration`.
  - 093–095 were applied to production project `buoyhkbodnhzngaotoel` on 2026-10-08 with Supabase versions `20261008023039`, `20261008023049` and `20261008023058` (`docs/releases/rafii-library-20261007.md:17`).
  - 096 was **not yet applied** at that checkpoint (`:19,27`).
- [D] Ledger divergence risk. Production `postriff_private.schema_migrations` on 2026-10-02 had 56 entries plus 088, making 57 (`founder-full-activation-20261002/production-migration-verification.json`).
  - That list did **not** include 037, 038, 039, 041, 044 or 046, which are in the repo.
  - It is unknown whether 093–095, applied through MCP, were also written to the postriff ledger.
  - [I] Consequence: generic `postriff_migrate.plan()` against production would report PENDING or refuse. Keep using a pinned single-migration runner with shape verification, and check the live schema plus **both** ledgers (`postriff_private.schema_migrations` and `supabase_migrations.schema_migrations`) read-only before applying.
- [D] Staging project is `oxacvkhpfgytkepxcaqh` (`founder-full-activation-20261002/migration-plan.json:3`, `database-permission-evidence.json:5`).

### 4.4 Migration numbers claimed by other branches
Method: `git diff --name-only --diff-filter=AR origin/consumer-saas...<ref> -- migrations/` over all 157 `refs/remotes/origin/*` and 215 local `refs/heads/*`. A `--diff-filter=M` pass found no remote branch modifying existing migrations.

| Number | Claimed file(s) | Branch(es) (most recent first) |
|---|---|---|
| 100, 101 | `100_social_cost_reservations.sql`, `101_x_oauth_provider.sql` | **active today (2026-10-08):** origin `codex/social-connection-recovery-20261007`; local `codex/linkedin-publishing-recovery-20261008`, `codex/threads-capability-recovery-20261008` |
| 089 | `089_youtube_creator.sql` | origin `codex/rafii-youtube-creator-20261005` (2026-10-08) |
| 089–096 | `089_james_daily_call`, `090_james_daily_call_indexes`, `091_james_agent_team`, `092_..._audio`, `093_..._decision_binding`, `094_..._mission_registry`, `095_..._spoken_choice`, `096_..._acceptance_audio` | origin `codex/james-agent-team-20261005`. **093–096 collide with merged Universal Library** |
| 089 | `089_private_request_capture.sql` | origin `codex/rafii-personalization-audit-20261004` |
| 089–092 | `089_pricing_credit_catalog_v2`, `090_free_lifecycle_bootstrap`, `091_pricing_public_four_plans`, `092_fixed_plan_checkout_approval` | origin `codex/rafii-stripe-sandbox-20261003` |
| 091, 092 | `091_founder_support_workflow`, `092_founder_support_surveys` | origin `codex/founder-support-workflow-20261003` |
| 089, 090 | james_daily_call | origin `feat/james-daily-call-20261002`, `fix/james-call-account-binding-20261003`; local `feat/james-personal-ops-os-20261003` |
| 047, 048, 050, 080, 081, 083, 084, 087 | inbox_operational_sync, pricing_credit_catalog_v2, free_lifecycle_bootstrap, customer_results, relationships, visual_packs, briefs_proof_strategy, source_uploads | origin `claude/rafii-product-growth-v2`, `claude/rpg-browser`; many local `claude/rpg-*` and `worktree-agent-*` refs |
| 048–052, 093, 094 | pricing_v2 recovery, including duplicates `051_*`/`052_*`, `093_rafii_pricing_lab`, `094_pricing_research_consent` | local `codex/rafii-pricing-v2-recovery-20261002` (stale) |
| 026–029 | ai_routing, ai_connections, mcp_connector, companion_relay | local `rafii/ai-routing-renumber-026-029` (stale) |
| 044 | `044_youtube_coach.sql` | local `codex/rafii-v3-stage4-20260928`. Collides with merged `044_social_provider_webhooks` (stale) |

- [V] No ref claims **097, 098, 099, or anything ≥102**. A search found no `09[7-9]_`/`10[2-5]_` file names except a test fixture string `099_other.sql` (`tests/test_trend_release.py:30`).
- [I] 097–099 are the obvious "next after 096" for any session that branches from consumer-saas. 102 is the obvious "next after 101" for the social-recovery owners.
- [I] Recommendation: allocate **`110_agent_ui_artifacts.sql`**, one additive file holding all OpenUI technical storage, and reserve **111** for a follow-up fix (the 096 precedent). Record the claim in `coordination.json`.
- [I] Before merge, re-run the branch scan after a fresh `git fetch`, check open PRs, and query production ledgers read-only.

### 4.5 Storage facts that force a new table (input for F's migration proposal)
- [V] `pr_agent_runs` (`005_consumer_web_ideas.sql:40-56`):
  - Columns: `id, conversation_id, workspace_id, actor, status, model, reasoning, context_digest(64), policy_epoch(64), idempotency_key, artifact jsonb, artifact_hash, usage jsonb, created_at, updated_at`.
  - `status` CHECK: running|completed|failed|cancelled|applied.
  - `reasoning` CHECK was extended by `017`.
  - `unique(workspace_id, idempotency_key)`.
  - 53 SQL readers in `src/`, including writing recovery, founder projections (`054` grants select on selected columns) and `active_run` (`service.py:1125-1140`, filters `idempotency_key LIKE 'agent:%'`).
  - [I] Do not store presentation attempts as extra `pr_agent_runs` rows.
- [V] `pr_agent_events` (`005:60-68`):
  - `kind` CHECK lists exactly the 11 SAFE_EVENTS (`agent_runtime.py:14`).
  - `ideas._insert_event` (`ideas.py:941-951`) raises on non-SAFE kinds and caps at `MAX_EVENTS = 2000` per run (`ideas.py:33`).
  - `ui.*` kinds cannot go here, and the contract forbids raw deltas in SAFE channels.
- [V] `pr_messages` (`005:16-27`): body jsonb, `unique(conversation_id, seq)`, `run_id`. The assistant body is `{"text","runId","siteAgent":{...},"agent":{...}}` (`service.py:862-897`).
- [I] The minimal additive set (F proposes, A allocates) is service-only tables, FK-cascading to `pr_workspaces(id)` and `pr_agent_runs(id)`:
  1. artifact header with lease and attempt
  2. immutable revisions (CAS on `(artifact_id, revision)`)
  3. bounded private event log (`(artifact_id, seq)` PK)
  4. activation and idempotency rows for UI actions, unless D reuses an existing domain idempotency store

  Write a pinned `docs/releases/<release>/migrate_110.py` modelled on `migrate_045.py`.

---

## 5. Billing, credits and accounting

### 5.1 Tables (`007_consumer_web_billing.sql` unless noted)
- [V] `pr_usage_ledger` (`:56-78`) is append-only and idempotent.
  - Columns: `id, workspace_id, member_id, run_id, job_id, reservation_id, kind(reserve|settle|release|adjust), dimension(text_model|image_generation|tool|storage|action), provider, model, quantity, unit, estimated_usd_micro, actual_usd_micro, cost_state(estimated|actual|estimated_unknown|released), charge_batch, idempotency_key, meta jsonb, at`.
  - Constraint: `unique(workspace_id, idempotency_key)`.
- [V] `pr_budgets` (`:81-91`): `scope` PK (`workspace:<id>`, `global`, `global-month`), `window_kind`, `warn/stop/spent/reserved_usd_micro`, `status candidate|approved`.
- [V] `pr_plan_terms` (`:6-25`), `pr_subscriptions` (`:27-39`) and `pr_entitlements` (`:41-53`).
- [V] `pr_credit_quotes` (`020_credit_quotes.sql:4-18`): `max_millicredits` from 0 to 1e8, `expires_at`, `reservation_id` (single claim).
- [V] Migration 058 creates:
  - `pr_ai_call_events` (`058_founder_ai_usage.sql:18-49`). `feature` regex `^[a-z][a-z0-9_]{0,39}$`; `workload` regex `^[a-z][a-z0-9_.]{0,59}$`; cost known ⇔ `cost_source != 'unknown'` (`pr_ai_call_events_cost_known`); unique `dedupe_key`.
  - `pr_ai_call_settlements` (`:56-64`), a late-cost sidecar.
  - `pr_price_versions` (`:67-87`), seeded with `gateway-list-2026-09-24`, `agent-v2-2026-09-24`, `media-constants-2026-09-24` and `pricing-provisional-2026-09-24`.
  - `pr_usage_rollups`.

### 5.2 Ledger API (`src/postriff_phase2/billing.py`)
- [V] `Ledger(credits_enabled, clock)` (`:118-124`) is built in `HostedWorkspaceService.__init__` (`hosted.py:392`) with `credits_enabled = POSTRIFF_CREDITS_ENABLED == "1"` (`hosted_app.py:209`). All methods take the caller's cursor.
- [V] `reserve(cur, workspace_id, member_id, dimension, estimated_usd_micro, idempotency_key, *, charge_batch, provider="", model="", run_id=None, job_id=None, meta=None, credit_authority=None)` (`:169-259`):
  - The same key with the same fingerprint returns `duplicate: True`. The same key with a different fingerprint returns 409.
  - `POSTRIFF_AI_PAUSED=1` → 503.
  - Policy `requestMax` per reservation → 402.
  - The plan has a `creditPolicy` but credits are disabled → 503.
  - Credits: `CreditBook.prepare` needs a `credit_authority` dict, else 402 "Confirm this task credit limit before generating."
  - `personDayStop` over a rolling 24 h → 402.
  - Budget not `approved` → 402. Workspace/global/global-month `spent+reserved+estimate > stop` → 402.
  - Inserts a `reserve` row with `meta.fingerprint`, `meta.budgetScopes` and attribution (`actorClass`, `costCenter`, `environment` from `RAFII_CONTROL_ENVIRONMENT`, `aiUsageExempt`, `service`, `action = meta.via`).
  - Increments `reserved_usd_micro`.
  - Returns `{reservationId, duplicate, warnings, entitlement}`.
- [V] `settle(cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None)` (`:261-313`):
  - outcome is `completed`, `failed` or `unknown`.
  - `completed` with `None` becomes `unknown`.
  - `unknown` inserts `cost_state='estimated_unknown'`, keeps the reservation held and records no cost.
  - A terminal `actual`/`released` row is idempotent.
  - Moves reserved to spent on the exact `budgetScopes`.
  - Consumes one batch only for `completed` + `charge_batch`.
- [V] Reconciliation:
  - `unknown_reservations()` (`:315-323`) and `reconcile_unknown(..., operator, evidence)` (`:325-343`, audit kind `usage.reconciled`).
  - Operator tooling: `scripts/reconcile_unknown_usage.py`, and founder routes `/api/control/v2/usage/unknown` and `/usage/reconcile/preview|confirm` (`rafii_control/founder_actions.py:900-901`, capability `usage.reconcile`, step-up).
- [V] Budget policies (`:67-84`), selected by `POSTRIFF_BUDGET_POLICY`:

  | Policy | global/day | global-month | workspace/month | personDayStop | requestMax |
  |---|---|---|---|---|---|
  | `launch-2026-09-24` | $10 | $100 | $10 | $3 | $1 |
  | `paid-2026-09-24` | $50 | $500 | $40 | $5 | $2 |

  An unknown policy ID → 503. No policy → budgets stay `candidate`, so every paid call → 402.
- [V] Exemptions: `ai_usage_exempt(member_id)` uses the `RAFII_AI_UNLIMITED_USER_IDS` UUID list (`developer_usage.py`). Exempt users skip caps and charged scopes but stay in the ledger.
- [V] Founder ops workspaces (`ops_metadata`) skip customer budgets and use the founder daily cap.

### 5.3 Credits (`credit_meter.py`, `credit_wallet.py`)
- [V] Constants and helpers:
  - `POLICY_VERSION = 'credits-candidate-2026-09-23-v1'`
  - `CREDITS_PER_USD = 300`
  - `millicredits(cost_usd_micro)` rounds up to 100-milli steps
  - `quote_task(..., route='managed'|'byok'|'cli')` is a non-billable preview (`credit_meter.py:24-32`)
- [V] `CreditBook` (`credit_wallet.py:63-178`):
  - `policy()` requires a plan `creditPolicy == POLICY_VERSION` with status active.
  - `issue()` creates a quote that expires after 600 s, with `max_millicredits ≤ 1e8`.
  - `authorize(cur, ws, actor, revision, request_digest, quote_id)`.
  - `prepare()` checks quote model, provider and digest, `millicredits(estimate) ≤ quote.maximum`, and available ≥ maximum. It allocates lots for the **full quote maximum**.
  - `claim()` **single-use**: `UPDATE ... SET reservation_id WHERE reservation_id IS NULL`.
  - `settlement()` uses `min(maximum, millicredits(actual))` and releases the rest.
- [V] `request_digest(operation, payload, conversation_id)` (`:183-195`) accepts only `quick-start|turn|media-notes`.
- [V] Agent Runtime v2 turns pass `credit_authority=None` unless a `reservation_approval` hook exists. Hooks exist for founder (`founder_reservation_approval` → None authority) and phone (`phone/service.py:460`, `billing.manager_approval`).
  - [I] So with `POSTRIFF_CREDITS_ENABLED=1` and a plan that carries `creditPolicy`, an ordinary browser agent turn's reservation raises 402. The turn falls back to the site agent (`service.py:428-433`). Credits mode today has no agent-turn credit authority path.
  - [D] Production credits were off on 2026-10-02.

### 5.4 Agent turn accounting (`agent_runtime_v2/service.py`), the pattern the Presenter must follow
- [V] `_manager_turn` (`:419-440`): `choose_reasoning` → `_open_run` → on `AlphaError` 402/403/409/429/503 it falls back with reason `budget`, and no other paid route is tried.
- [V] `_open_run` (`:633-668`):
  - It refuses with 503 `price_unknown` if the `fast_language` or `vision` route is unpriced (`:637-643`).
  - It reaps stale turns in its own transaction.
  - It inserts the `pr_agent_runs` row with `idempotency_key = "agent:" + key`.
  - It reserves `estimate_usd_micro(model, 24_000, 4_000)` under key `f"agent:{run_id}"`, `dimension="text_model"`, `charge_batch=False`, `meta={"via":"rafii_agent","traceId":...}`.
  - The returned reservation carries `estimateUsdMicro` as "the turn's ceiling".
  - [I] Arithmetic: gpt-6-sol 24k×$2 + 4k×$10 = **88,000 µUSD ($0.088)**; gpt-6-luna = **4,400 µUSD**.
- [V] Child calls inside a turn's ceiling: `_manager_follow_ups` (`:714-731`) computes `room = reservation.estimateUsdMicro - _spend(...)` and calls only if the ceiling fits.
- [V] Separately reserved child calls: `_simple_follow_ups` (`:733-763`) reserves `f"agent-follow-ups:{run_id}"` with `run_id=run_id` and `via=rafii_follow_ups`. A refusal means quietly no chips. A reservation that was made is always settled, as unknown on error.
- [V] `_finalize` (`:765-860`) settles the turn reservation once, `completed` with cost or `unknown` (`:837-838`). It then calls `record_calls()` to write `pr_ai_call_events` under a savepoint.
- [V] `_spend(ledger, default_model)` (`:910-927`): any call without an int cost, or any unpriced span, makes the total `None`, so the turn settles `unknown`.
- [V] `_abort_run` (`:929-958`): spend unknown → `unknown`; no calls → `failed`, 0; else `completed`, spent.
- [V] `_reap_stale_turns` (`:960-990`): `STALE_TURN_SECONDS = 600`. It settles open reservations of dead `agent:%` runs as `unknown`, never as an estimate. **It ignores keys that do not start with `agent:`.**
- [V] Timings: `TURN_BUDGET_SECONDS = 240` (`:39`). Vercel `api/index.py` `maxDuration: 300` (`vercel.json`).
- [V] No hidden retries: `manager.provider_model` builds `AsyncOpenAI(..., max_retries=0, timeout=90)` (`manager.py:126-140`, rationale at `:132-133`).
- [V] Failure classification: `failure_status` (`manager.py:237`), `failure_diagnostic` (`:225`, allowlisted fields only) and `_note_failure` (`:254-266`). 429 and 4xx are refused at cost 0; timeout, 5xx and cancel leave the outcome unknown.
- [V] Metering wrapper: `manager.metered()` (`:163-204`). `get_response` records spans and failures. **`stream_response` only increments `model_requests` and records no span, usage or failure.**
  - No streaming provider call exists anywhere today; `Runner.run` is used only at `service.py:491,1074` and `founder_agent.py:449`.
- [V] Direct-HTTP precedent: `followups.plan()` and `followups.suggest()` (`agent_runtime_v2/followups.py:86-160`).
  - The ceiling is `ceil(bytes/3)+16` input tokens plus a fixed `max_output_tokens`.
  - It uses the Responses API on openai and chat completions on gateway, with structured output.
  - A 4xx is refused at no cost. An uncertain outcome becomes an `estimated` span **booked at the ceiling**.

### 5.5 Prices
- [V] Agent prices: `config.DEFAULT_PRICES` (`:53-58`), USD/MTok.
  - gpt-6-sol (2, 10), gpt-6-luna (0.1, 0.5), gpt-6-astra (10, 50), gpt-5.6-terra (2, 12).
  - Labelled "Verified against developers.openai.com on 2026-09-24" (`:25`).
  - Override with `RAFII_AGENT_MODEL_PRICES`. An unpriced model is never called.
- [V] Writer and gateway prices: `model_runtime.DEFAULT_PRICES` with `DEFAULT_PRICES_VERSION="gateway-list-2026-09-24"` (`model_runtime.py:32-39+`), from the AI Gateway `/v1/models` list on 2026-09-24.
- [V] Price-table drift guard: `tests/test_founder_ai_call_events.py:609-611` asserts `config.DEFAULT_PRICES == 058 agent-v2 seed` and `model_runtime.DEFAULT_PRICES == gateway seed`.
  - [I] **Changing `DEFAULT_PRICES` requires a new `pr_price_versions` migration row.** Reuse existing priced models.
- [V] Price-version tagging: `manager.price_version(cfg, model)` (`:269-277`) returns `agent-v2-2026-09-24`, or `configured` for an env override. `span_attempt` (`:280-302`) gives an `estimated` span status `unknown` and a NULL cost in `pr_ai_call_events`.
- [V] Image and voice: `DEFAULT_IMAGE_ESTIMATE_USD_MICRO` is 40,000 for fast and 190,000 for quality. GPT-Live is 50,000 µUSD/min with a 30 min cap (`config.py:61-64`).
- [I] Presenter ceiling examples, with input ≈20k tokens:

  | Model | max_output 16k | full 128 KiB output (≈44k tokens at bytes/3) |
  |---|---|---|
  | gpt-6-luna | 2,000 + 8,000 = 10,000 µUSD | ≈26k µUSD |
  | gpt-6-sol | 40,000 + 160,000 = 200,000 µUSD | ≈480k µUSD |

  All of these fit under `requestMax` $1 or $2, but sol eats into `personDayStop` quickly. A must freeze `max_output_tokens`.

### 5.6 Known accounting gaps and inconsistencies
1. [V] Streamed SDK calls are unmetered (`metered().stream_response`). B must capture final usage from the stream's completion event, or use a direct streaming transport with its own span and failure notes.
2. [V] Follow-up chips book an uncertain call at its ceiling as `completed` cost (`followups.py:131-140` → `_spend` prices estimated spans). The Manager path settles `unknown` instead.
   - [I] The Presenter should follow the Manager rule: uncertain means `settle(..., "unknown", None)` with the hold retained, so no estimate becomes actual.
3. [V] The reaper covers only `agent:%` runs. Presenter reservations need their own reaper, for example in a lease-expiry sweep. Otherwise open holds stay `estimated` forever.
4. [V] The credit quote is single-claim. A second, Presenter reservation cannot ride the turn's quote without a new CreditBook method.
5. [V] `ai_call_events.feature` accepts any `^[a-z][a-z0-9_]{0,39}$`.
   - [I] Use `feature="agent"` with `workload="ui_presenter"` (dots allowed) so the founder AI views count it, or confirm how the founder views treat a new feature value before introducing `agent_ui`.

---

## 6. Privacy and egress boundaries the Presenter must respect

- [V] The Agent Runtime is a cloud processor (`memory_layers.py:14-17`).
  - Memory bodies reach it only when `memory.egress(state).cloud is True` (`memory.py:156-159`; owner action `memory_egress`, `memory.apply_memory_action` `:196-204`).
  - Private, local-only, excluded and unlabelled boundaries never leave, even then (`memory.projection` `:162-186`).
  - `memory_layers.cloud_allowed(state)` (`:28-29`).
- [V] Media: `media_consent.allowed(state, processor(provider, model))` (`media_consent.py:18-45`) is processor-specific. Consent is for an exact `{provider}:{model-family}`, owner action `media_egress`.
  - [I] A Presenter on a different provider than the Manager would be a new processor. Use the same provider route and never send media bytes or signed URLs.
- [V] Sources: `source_policy.classify(source, operation, provider_class)` (`:76-93`).
  - Cloud needs `"cloud" in source.egressConsent`. `prohibited` and `retracted` sources are excluded.
  - `project_context(...)` (`:100-121`) admits at most 20 sources and only approved facts.
- [V] Owner-only egress decisions (`permissions.ACTION_CLASSES`): `research_egress`, `connector_egress`, `writer_defaults`, `voice_sample_grant`.
- [V] CLI routes:
  - `cli_runtime.ClaudeCliRuntime` uses ROUTE `claude-code`, `POSTRIFF_LOCAL_CLI` and `POSTRIFF_CLAUDE_BIN`, with budget `POSTRIFF_CLI_BUDGET_USD` (default 0.50). `provider_class="cloud"` because the request leaves the machine.
  - `codex_runtime.CodexCliRuntime` is similar.
  - Both are unavailable on Vercel, and both serve only as writers.
  - The person's chosen writer travels as `ctx.writer_model` (`context.py:98`, `domain_tools.py:406-407`) and is never swapped.
- [V] **No BYOK runtime exists.** `byok` appears only as a `credit_meter.quote_task` route label. The `ai_connections` and `ai_routing` migrations exist only on stale local branches.
- [I] Presenter rules:
  - Eligible only after an authorized Manager turn on the configured cloud route.
  - Projection is limited to data the Manager could already see under the same egress decision.
  - A turn answered by the site-agent fallback or a deterministic path renders natively, with no Presenter call. It never silently upgrades to a cloud presenter.
  - Record `egress_decision = {provider, memoryCloud, mediaProcessorAllowed, sourcesExcluded}` in the projection.

### 6.1 Logging, telemetry and redaction
- [V] Web Sentry:
  - `web/src/instrumentation.ts`: Node and Edge init only when `NEXT_PUBLIC_SENTRY_DSN` is set and `NEXT_PUBLIC_SENTRY_DISABLED` is unset. `sendDefaultPii:false`, `tracesSampleRate:0`, `beforeSend: scrubTelemetry`.
  - `web/src/instrumentation-client.ts`: lazy SDK import under the same gate.
  - `web/src/lib/telemetry.ts` `scrubTelemetry` keeps only type, ID, level, release and environment, error-type allowlist, `value:'Application error (message withheld)'`, and frames with filename withheld unless `/_next/static/...`.
  - [I] OpenUI render errors therefore reach Sentry without messages or DSL. Do not add breadcrumbs or context with source.
- [V] Python logging is structured JSON events with class names only:
  - `log.error(json.dumps({"event":"agent_turn.aborted","errorClass":...,"traceId":...}))` (`service.py:934`)
  - per-request `request.completed` with method, status, duration and a coarse route class (`hosted_app.py:~468-474`)
  - `request_metrics.observe` per route pattern
  - `budget.warning_crossed` without identifiers (`billing.py:257-258`)
- [V] Redaction helpers:
  - `site_agent/tools.redact(value, limit=300)` (`site_agent/tools.py:196-205`): secret patterns and emails.
  - `learning_signals.redact` and `growth/audience_miner.redact`.
  - `manager.failure_diagnostic`, allowlisted error fields.
  - `agent_runtime.safe_event(kind, **body)` (`agent_runtime.py:50-58`): SAFE_EVENTS only, with `text`/`message` cleaned to 12,000 chars.
  - `ai_call_events` rows hold IDs, counts and amounts only (`ai_call_events.py:1-20`).
- [V] There is no OpenUI telemetry setting anywhere today.
  - [I] `OPENUI_TELEMETRY_DISABLED=1` must go in the JCB `.james-cloud-build.json` `environment` block (A-owned), any GitHub workflow that runs `npm ci`, and the Vercel build env.
  - [V] JCB pins `lockfileSha256` for `web/package-lock.json` (`.james-cloud-build.json`). A must update it with any lockfile change.
    - [V] While this reader ran, another process changed two files in this worktree; this reader did not.
      - `.james-cloud-build.json`: `lockfileSha256` went from the committed `07c94c20…` to `c347e642…`.
      - `.depot/workflows/james-cloud-build.yml`: 20 lines changed.
    - The worktree is therefore no longer clean at `3da806f0`. A should confirm it made these changes (likely `jcb setup`/`doctor`).
  - [V] JCB tasks currently map `test` → `test:library` and `ci` → `ci:library`.

---

## 7. Audit helper

- [V] `hosted.audit(cur, workspace_id, actor, kind, subject="", meta=None)` (`hosted.py:96-98`). It is content-free and append-only, and inserts into `pr_audit_events`.
  - Schema: `004_consumer_web_tenancy.sql:46-61`. `kind` 3–80 chars, `subject` ≤200 chars, `meta` jsonb.
  - Read access is admin/owner only, per `015_audit_visibility.sql` and `hosted.audit_events` (`hosted.py:1200-1205`).
- [V] Domain commands audit automatically. `PostgresWorkspaceRepository.command(..., audit_event=fn, after=fn)` (`hosted.py:150-171`) does CAS on `pr_workspaces.revision` (409 `workspace_revision_conflict`), then permission `require`, optional step-up, then `audit()` in the same transaction.
- [V] Existing kinds look like `api_token.created`, `channel.connected`, `billing.checkout_started`, `usage.reconciled`, `credit.adjusted_by_operator`, `founder.spend.warning`.
- [I] UI actions must route to the original command so its audit fires. Add at most metadata-only kinds such as `agent_ui.action_applied` with IDs only.
- [V] Founder audit goes through `Boundary._audit` / `ControlApplication.terminal_audit` (`rafii_control/http.py:283-293`).

---

## 8. Route and deployment facts A owns

- [V] `vercel.json` services:
  - `postriff_web` (Next, root `web/`)
  - `postriff_api` (Python WSGI `api.index:app`, `maxDuration 300`)
  - `rafii_phone_media` (ASGI `api.phone:app`, Starlette and uvicorn pinned in `requirements.txt`, `maxDuration 660`)
- [V] Rewrites, in order:
  1. `/api/phone/dial/media/(.*)` and `/api/phone/media/(.*)` → phone media service
  2. `/api/(.*)` → postriff_api
  3. `/(.*)` → web
- [V] The precedent for a dedicated service with a precise rewrite before the catch-all is `rafii_phone_media`, the only existing ASGI service.
- [V] Consumer mount: `hosted_app.py:781-784` sends `/api/workspaces/{id}/agent/*` to `agent_runtime_v2/http.handle`, with `resource = parts[4]`.
  - [I] The contract base `/api/workspaces/{id}/agent/ui/...` lands naturally in `handle` as `resource == "ui"`. No `vercel.json` change is needed unless streaming forces a separate ASGI service.
- [V] Consumer guards:
  - `require_session_token`: API tokens are refused for the agent (`agent_runtime_v2/api_guard.py:5-8`).
  - Mutations need the `X-PostRiff-Request: founder-alpha` header and a same-origin check (`hosted_app.py:310-320`).
  - JSON body limit is 12,000,000 bytes (`hosted_app.py:299`). [I] UI routes must enforce their own smaller caps: 32 KiB patch, 16 KiB state, query inputs.
- [V] Responses use `_json` (`hosted_app.py:276-282`) with `Cache-Control: no-store` and `Content-Length`, so they are not streamed. The web client fetches with `cache:'no-store'`, `Authorization: Bearer`, and `APP_GUARD_HEADER` (`client.ts:43-55`).
- [V] Toolchain pins:
  - Node 24.15.0 (`.node-version`) and Python 3.12 (`.python-version`)
  - `next 16.3.8`, `react 19.2.4`, `@sentry/nextjs ^10.45.0` (`web/package.json`)
  - `openai-agents==0.22.3`, `openai==3.19.2`, `starlette==1.7.0`, `uvicorn==0.54.0` (`requirements.txt`)
  - No `@openuidev/*` package or OpenUI code exists yet.

---

## 9. Risks and gaps (summary)

1. **Migration ledger divergence in production.** The postriff ledger lacked 037/038/039/041/044/046 on 2026-10-02. 093–095 were applied through Supabase MCP (a second ledger). The generic runner can't be used. A pinned runner and a live read-only schema check are mandatory.
2. **Number collision pressure.** 097–099 and 102 are natural picks for parallel sessions. 100/101 are actively claimed by three branches today. 089–096 are multiply claimed (james-agent-team 093–096 collides with the merged Library).
3. **No streaming anywhere.** WSGI `_json` responses, an unmetered `stream_response`, and a founder app that is JSON only. B and A must prove deployed chunk delivery, either via WSGI iterator streaming on Vercel Python or a new ASGI service with a precise rewrite.
4. **Credits mode has no agent credit authority.** With credits on, agent turns fall back, and a Presenter reservation would fail with 402. The single-claim quote blocks a child reservation.
5. **Kill-switch latency.** Env flags need a redeploy. Instant rollback is the only immediate lever. There is no DB-backed flag.
6. **Inconsistent uncertain-cost handling.** Follow-ups book the ceiling; the Manager books unknown. The reaper ignores non-`agent:` keys.
7. **Price-table drift test.** Any new default model price needs a price-version migration.
8. **Founder transport.** The 32 KiB body cap, JSON-only responses and the 270 s deadline. Founder flags are filtered by the `RAFII_FOUNDER_` prefix in ControlApplication.
9. **Production flag state unknown today.** It must be read live, beyond the 2026-10-02 evidence. Credits and budget policy values are unverified.
10. **`pr_agent_events` CHECK and SAFE_EVENTS** cannot carry `ui.*`. Reusing `pr_agent_runs` for attempts would pollute 53 readers.

---

## 10. Decisions A must freeze (recommended option first)

| # | Decision | Recommendation | Alternatives |
|---|---|---|---|
| D1 | Flag home and names | Add `RAFII_GENUI_ENABLED`, `RAFII_GENUI_ACTIONS_ENABLED`, `RAFII_GENUI_EDITS_ENABLED` and `RAFII_GENUI_FOUNDER_ENABLED` to `agent_runtime_v2/config.FLAGS`. Expose a computed `genui{available,actions,edits,blocker}` in `status()`. Founder reads them through `base.cfg`. | Coworker `flags.py` (wrong reader); `NEXT_PUBLIC_*` (forbidden by the existing rule) |
| D2 | Canary audience | `RAFII_GENUI_WORKSPACE_ALLOWLIST` (UUID list, empty = nobody) plus `RAFII_GENUI_AUDIENCE=allowlist|all`, both enforced server-side in `status()` and on every UI route | DB table (new scope); user-ID list |
| D3 | Kill switch | Env flags as durable state, with Vercel instant rollback for emergencies. `POSTRIFF_AI_PAUSED=1` stays as the global paid-AI stop. No new flag table. | A singleton control row in migration 110 for a faster per-capability stop |
| D4 | Migration number and shape | One file, `110_agent_ui_artifacts.sql`, with 111 reserved. Service-only RLS template. FK to `pr_agent_runs` and `pr_workspaces` with cascade. Append `\ir` after `rls.sql:144`. Pinned `migrate_110.py` modelled on `migrate_045.py`, applied in a non-promotable production build **before** app promotion. | 097 or 102 (collision-prone); Supabase MCP apply (second ledger) |
| D5 | Presenter accounting | A separate reservation keyed `agent-ui:{parentRunId}:{attemptId}`, `run_id=parentRunId`, `meta.via='rafii_genui'` and `parentReservationId`. Admission must check `parent actual-or-held + presenter ceiling ≤ policy.requestMax`. Uncertain outcome → `settle unknown`. A lease-expiry sweep settles abandoned holds as unknown. | Grow the Manager reservation and defer settle (cross-request hold, reaper conflict); fit inside the turn's `room` (too small: 88k µUSD) |
| D6 | Credits mode | When the workspace plan has `creditPolicy`, the Presenter is unavailable (native fallback, blocker `credit_authority_unavailable`) until a reviewed child-claim CreditBook method exists. Credits are off in production. | Implement `CreditBook.prepare_child` against the parent quote's remaining maximum |
| D7 | Presenter route and model | Add workload `ui_presentation` with alias `RAFII_AGENT_PRESENTER_MODEL`, defaulting to the resolved `RAFII_AGENT_FAST_MODEL` (gpt-6-luna, already priced). Same provider as the Manager. Fixed `max_output_tokens`, giving a deterministic ceiling via the followups bytes/3 rule. `max_retries=0`. 60 s timeout capped by the remaining budget. | Reuse `standard_reasoning` (sol, about 20× cost); a new paid model (needs a price-version migration and authorization) |
| D8 | Metering of streamed calls | B implements stream-aware metering. Final usage from the completion event becomes a span. A missing or cut stream is a `_note_failure`-style call with unknown cost. Write `pr_ai_call_events` with `feature='agent'`, `workload='ui_presenter'`, `physical_attempt_id='{attemptId}:p{n}'`. | Reuse `metered()` unchanged (loses usage) |
| D9 | Streaming transport | First prove WSGI chunked iterator flushing on the existing `postriff_api` deployment. If it does not flush, add one ASGI service following the `rafii_phone_media` precedent, with a precise `/api/workspaces/(.*)/agent/ui/presentations(.*)` rewrite placed before `/api/(.*)`. | Migrate the whole API to ASGI (forbidden by the runbook) |
| D10 | Founder UI routes | `register_route` under `/agent/ui/...` with `copilot.use` and budget `founder.agent.turn`. Snapshot and replay are JSON. Founder streaming is added only if D9's adapter is reused behind the Control boundary. | A separate founder Vercel project (separate mount; drops the consumer runtime) |
| D11 | Egress for the Presenter | Projection = data the Manager already saw under the same provider and egress decision. No media bytes or signed URLs. Memory bodies only if `memory.egress(state).cloud`. Record `egress_decision`. Fallback and deterministic turns get native rendering only. | Separate consent (new UX, out of scope) |
| D12 | Audit | Rely on the original domain command audits. Add only ID-only `agent_ui.*` kinds for activation and applied outcome if G requires them. | A new audit table (forbidden) |
