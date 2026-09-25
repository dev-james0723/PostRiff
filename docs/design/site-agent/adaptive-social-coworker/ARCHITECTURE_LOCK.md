# Rafii Adaptive Social Coworker: WP0 architecture lock (2026-09-24)

Governing spec: `../RAFII_ADAPTIVE_SOCIAL_COWORKER_ENGINEERING_SPEC_2026-09-24.md`.

It extends `../RAFII_MULTIMODAL_AGENT_RUNTIME_ENGINEERING_SPEC_2026-09-24.md` and `../agent-runtime/ARCHITECTURE_LOCK.md`, and keeps `../README.md` and `../verification-matrix.md` true.

This note maps the spec onto the code on `raffi/site-agent`. It was taken at HEAD `5e9f846`, and HEAD moved `bc44eee` → `6022e15` → `cb51ac5` → `5e9f846` while it was written.

It records, with reasons:
- the facts that decide the design;
- the concurrency boundaries;
- the migrations;
- every deviation from the spec's suggested layout.

The machine-readable companion is [`capability-ledger.json`](capability-ledger.json). It holds the James → Rafii migration ledger and the capability inventory.

## 1. Repository facts that decide the design

| # | Fact (evidence) | Consequence |
|---|---|---|
| F1 | Hosted API is one synchronous WSGI app on Vercel Python (`api/index.py`, `maxDuration` 300). There is one per-minute cron, `/api/cron/worker` (`vercel.json`), handled at `hosted_app.py:408-437`. Its steps run serially with no per-step isolation. | All background work (notification delivery, detector scan, weekly planning, learning sweeps) is a **bounded, try/except-isolated step** in the same cron. There is no new infrastructure: no Redis, Kafka or queue service. |
| F2 | Postgres is Supabase over the transaction pooler (`:6543`). There is no LISTEN/NOTIFY and no pgmq/pg_cron/pg_net. The API connects as a BYPASSRLS role and never `SET ROLE`s (`deployment.py:21-22`). | The queue is **Postgres-native rows + `FOR UPDATE SKIP LOCKED` + lease fencing**, the same as `hosted_worker.PostgresWorker` (`hosted_worker.py:56-135`). Tenant isolation is **application-level first** (every query filters by workspace, inside `repository.transaction`). RLS is defence in depth for browser roles only. |
| F3 | Workspace data is one revisioned JSON document (`pr_workspaces.state`). It is mutated through `repository.command(workspace_id, token, revision, trusted_command, requirement, step_up, audit_event, after)` (`hosted.py:141-162`). Effects hooks run in the same transaction (`hosted.py:156-157`; registered at `hosted.py:361-363`). The whole document goes to every member, viewers included, and into exports. | Small, bounded, workspace-wide product state (weekly recipes, week plans, source→campaign objects, FactPacks, overlay metadata, watchlists, opportunities) lives in `state.coworker`, mutated with `repository.command` and an explicit `requirement`. **Per-user, secret, high-churn or bulky data goes in tables:** preferences, push subscriptions, deliveries, raw evidence, hypotheses and product events. |
| F4 | The publishing worker and campaign worker write state **outside** `repository.command` (`hosted_worker.py:122`, `campaign_worker.py:41-107`). | Domain events cannot come only from command effects. Decision **N2**: a deterministic **state detector** derives events from authoritative state, with dedupe keys. It runs both as a command effect (immediate) and as a cron scan (for worker-made transitions). |
| F5 | Email: Resend over raw HTTPS (`email.py`). HTML is inline-styled, English only, with no preheader, locale, version, `Idempotency-Key` or kept provider id (`email.py:74-86,186-196`). There are 7 direct call sites, 4 of them sending **inside open DB transactions** (`hosted.py:469-497`, `email.py:243-275`, `automation_runs.py:409-436`, `campaign_worker.py:240-264`). | The new `NotificationService` sends only from a claimed delivery row, after commit. The legacy senders stay byte-for-byte when `RAFII_NOTIFICATIONS_V2_ENABLED` is off. When it is on, the kinds v2 owns are routed through events, with one guard in `Mailer` and no edits at each call site (§4 N5). |
| F6 | `cryptography==50.0.1` is pinned and supports ECDH P-256, ES256, AESGCM and HKDF. `pywebpush` is not installed. The repo convention is "provider over HTTPS, no SDK". | Web Push (RFC 8291 aes128gcm + RFC 8292 VAPID) is implemented in-house on `cryptography`. There is no new dependency. |
| F7 | `src/postriff_phase2/capabilities.py` **already exists**: publish-route capability, imported by `automation_runs.py`, `automation_plan.py` and `site_agent/tools.py`. | The registry is **`skill_registry.py` + `skill_compiler.py`** plus `skills/rafii-registry.json`. `capabilities.py` is untouched (deviation D1). |
| F8 | Skills reach hosted code in exactly one place: `SkillLibrary.bind` from `ideas.py:1000` (writer runs). Agent Runtime v2 instructions are hard-coded strings (`agent_runtime_v2/manager.py:23-58`, `specialists.py:19-101`). 8 `postriff-*` skills have no consumer. 44/45 are `unversioned`. | WP1 adds versions to every default skill. It adds a registry with runtime consumers, verified by *behaviour*: the compiler or the binder actually selects the skill. It adds a compiler the runtime can call. Orphans are fixed by binding them to a consumer or classifying them `dormant`, with the reason recorded. |
| F9 | `skills/james-au-*` ship in the hosted Vercel bundle: neither `.vercelignore` nor `excludeFiles` names them. `SkillLibrary.load("james-au-content-craft")` succeeds. `james-au-social-orchestrator/references/zhihu-browser.md` holds a local path, a localhost port and a personal account handle. Generic `postriff-*` files that are bound on **every** writing run carry James's voice anchor and music/Cantonese/builder defaults (e.g. `postriff-content-craft/references/human-voice-pass.md:10-13`). | WP1: keep `james-au-*` out of the hosted bundle (`.vercelignore`). Restrict `SkillLibrary.load` to product prefixes. De-James the bound `postriff-*` files at the exact lines listed in the ledger, with version bumps. Add a no-leak test over every file the hosted binder or compiler can reach. |
| F10 | Humanizer: there is no code. The only text is `human-voice-pass.md`, which carries a fixed James voice. The global `humanizer-zh` (MIT, 歸藏) and English `humanizer` v2.8.0 (MIT, blader) exist. The paid-route skill budget is already saturated: 59,374 of 60,000 characters, with 3 references omitted on a 2-destination turn. | The Humanizer is a **separate evaluator stage** (deterministic detectors + meaning-preservation diff). It is also available as a knowledge pack (`rafii-humanizer-en`, `rafii-humanizer-zh` with zh-Hant/yue register) for revise-capable routes. It is not appended to the saturated writer prompt. |
| F11 | Learned preferences (`postriff_alpha/learning.py:161-165`) carry scope (platform, language, contentType), evidenceState, source, status and confirmedBy. They do **not** keep evidence ids, counter-evidence, confidence, lastSupportedAt, expiry or `replaces`. Proposals keep evidence ≤6 and support (`learning_extract.py:187-262`). | WP4 overlays are an **additive extension**: new optional fields on learning items plus a derived overlay view (`coworker/overlays.py`). Explicit brand/voice/platform overlays are kept in `state.coworker.overlays`. There is no parallel preference ledger. Strategy hypotheses go in their own table, never read by `memory.render_files`. |
| F12 | Research: `ExaSearch` + `JinaReader` + `Researcher` (`research.py`), gated by the owner's `researchEgress` (`research.py:89-109`). Fetched paragraphs are **auto-approved facts** (`ideas.py:707`). There is no provider field, author, raw hash, evidence type, claim link or contradiction model. A local-only `SourceLog`/`assess_claim` exists in `james_au_social` (not imported by hosted code). | `coworker/research_broker.py` wraps the existing callables, so `Researcher(search=, read=)` and `automation_research.find(search=, read=)` keep working. `coworker/fact_pack.py` ports the claim/contradiction semantics, without importing them. A snippet is never a verified claim. |
| F13 | Engagement data exists: `pr_audience_threads`, `pr_reply_drafts` and `audience.py` (`draft_reply`, `reply_preview`, `approve_reply` with digest + `confirmed`). | WP9 engagement copilot = deterministic triage/summary over `pr_audience_threads`, and drafts through `AudienceService.draft_reply`. External sending stays `approve_reply` (unchanged permission/approval). |
| F14 | Metrics: `insights.compare` refuses mixed cohorts and insufficient samples and sets `causalityEstablished:False`. `pr_metric_observations` has an unavailable≠0 CHECK. Ingestion is **not wired in production** (`ingest_post_insights` is only called by the dev harness). | WP8 builds hypotheses over `insights`, and says so when data is absent. "No data" is `insufficient_evidence`, never a hypothesis. |
| F15 | Flags: `RAFII_*` flags live in `agent_runtime_v2/config.py` `FLAGS`. They are default-off, and `_flag` accepts 1/true/yes/on. `cfg.enabled(name)` is False for any name not in `FLAGS`. That file belongs to the runtime session. | New flags live in `coworker/flags.py` with the same semantics and the same `.env.example` documentation style. Deviation D5: they are merged into `config.FLAGS` when the runtime session releases the file. |
| F16 | Migration numbers **020–023 are taken on other branches**: `raffi/launch-final` has 020_credit_quotes…022 (committed), and `ai-routing` has 020_ai_routing…023_companion_relay. `postriff_migrate.py:15-19` refuses duplicate numbers, and the checksum ledger forbids renaming a file after it is applied. | New migrations are numbered **024** and **025**. Gaps are legal for the runner, which rejects only duplicates and unknown applied names. Owner decision 2026-09-25: 020–022 are the production credit migrations, 023 is retired, 024–025 stay the coworker's, and ai-routing moves to 026–029 (`docs/postriff-migration-numbering.md`). Production has no ledger; it is migrated with one-off pinned runners. |
| F17 | Test env: there is no venv in the worktree. The local Python 3.14 venv lacks `openai-agents`, so 8 orchestration tests skip and the agent-runtime PG script prints SKIPPED and exits 0 (a false green). PG 17.11 is available. Playwright 1.62.1 browsers are mismatched (the cache has chromium-1243 and webkit-2359). | Every Python gate here runs with a CI-faithful **Python 3.12 venv** (`requirements-dev.txt`, which includes `openai-agents==0.22.3`), created outside the repo in the session scratchpad. It is always run with `POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0`. Browser runs use the `RAFII_CHROMIUM_PATH`/`RAFII_WEBKIT_PATH` overrides. |

## 2. Concurrency lock (who owns what until their commits land)

| Owner (session) | Owned paths (do not edit) | How this work integrates |
|---|---|---|
| Multimodal Agent Runtime ("Opus 5.5 Extra High") | `src/postriff_phase2/agent_runtime_v2/*`, `tests/test_agent_runtime.py`, `tests/phase2/postgres_agent_runtime.py`, `scripts/agent_runtime_pg.py`, `scripts/agent_runtime_live.py`, `docs/design/site-agent/agent-runtime/*`, `web/src/features/rafii-voice/*`, `web/src/lib/agent-runtime/*`, `web/tests/agent-runtime-*.cjs` | New tools register **from my module** through `agent_runtime_v2.tool_adapter.register(ToolSpec(...))`, which the owner confirmed. Names are sent to the owner to add to Manager/specialist scopes. Skill provenance is exposed as a pure function (`skill_compiler.provenance_for_run`) for the owner to put in the run trace at `service._finalize`. |
| Site agent ("Raffi Site-wide AI Agent v0.1") | `src/postriff_phase2/site_agent/*`, `campaigns.py`, `ideas.py`, `src/postriff_alpha/generation.py`, `tests/test_site_agent.py`, `tests/phase2/postgres_site_agent*.py`, `web/tests/site-agent*.cjs`, `scripts/site_agent_*.py`, `docs/design/site-agent/{README.md,verification-matrix.md,evidence/*}`, `web/src/features/site-agent/*`, `web/src/lib/site-agent/*`, `web/src/lib/api/types.ts`, `web/src/lib/api/client.ts`, the Automations view | Only public APIs are used: `IdeasService.turn/apply`, `campaigns.apply_action` through `repository.command`, `AudienceService`. `hosted_app.py` gets a ~5-line dispatch, announced to the owner beforehand. The web uses its own API module (`web/src/lib/coworker/api.ts`), built on the same `createApi` contract, without editing `client.ts`/`types.ts`. |
| rafii-v9 UI session (separate worktree) | `James-Au-Studio-rafii-v9` (web copy/UI) | There are no shared files in this worktree. Merge risk: that session relabels publish states in `web/src/features/queue/job-status.ts` (drift from spec rule 7). This is noted for the merge owner. |
| Other branches | `raffi/launch-final` (5 unmerged commits touching `hosted.py`, `hosted_app.py`, `store.py`, `campaign_worker.py`, `model_runtime.py`, web api/client…; migrations 020–022; secret-scanner rename). `ai-routing` (020–023). | Keep edits to those shared files minimal and additive, each marked with a one-line comment. Record the merge order in §7. |

Ports: this work uses API `:4741`, Postgres `:55721`, PG suite `:55738`, web `:3390` and distDir `.next-coworker`. It never uses `:4541/:55521/:3190/:55438/:55531/web/.next` (site agent) or `:4641/:55621/:3290/.next-agent-runtime` (runtime).

Staging is by explicit path only. There is no stash, reset, checkout or `git add -A`.

## 3. Package layout (new files; the smallest coherent set)

```
skills/rafii-registry.json                      # WP1 single source of truth: every default capability, versioned + hashed
skills/rafii-humanizer-en/ rafii-humanizer-zh/  # WP1/WP4 knowledge (generalised, MIT attribution kept)
skills/rafii-weekly-operator/ rafii-source-to-campaign/ rafii-engagement-triage/ rafii-listening-opportunity/  # workflow knowledge
src/postriff_phase2/skill_registry.py           # load/validate/hash/lock, orphan + leak + policy checks, CLI
src/postriff_phase2/skill_compiler.py           # Capability Planner → Skill Selector → bounded context + provenance record
src/postriff_phase2/notifications/              # WP2/WP3: catalog, planner, preferences, store(emit), detector, delivery, email_render, push, webhooks, service
src/postriff_phase2/coworker/                   # flags, runtime(attach), humanizer, overlays, research_broker, fact_pack,
                                                # source_intake, weekly_operator, creative, performance, listening,
                                                # engagement, attention, growth, agent_tools, http, service (CoworkerService)
migrations/postriff/024_notification_core.sql   # WP2/WP3 tables
migrations/postriff/025_coworker_evidence_growth.sql  # research evidence, strategy hypotheses, product events, experiments
web/public/sw.js, web/src/lib/coworker/*, web/src/features/coworker/*, web/src/app/app/<new routes>
tests/test_rafii_*.py, tests/phase2/postgres_coworker_*.py, web/tests/coworker-*.cjs
```

Edits to existing shared files are listed exhaustively. Each is additive and has a reason:

| File | Edit | Why |
|---|---|---|
| `src/postriff_phase2/skills.py` | Restrict `load()` to product prefixes (`postriff-`, `rafii-`) unless an explicit Studio root is used. Keep bind order and hashes as they are. | F9: hosted must not load personal skills. |
| `skills/postriff-*/SKILL.md` + the listed references | Add `metadata.version`, remove James-specific lines, bump versions. | F8/F9. |
| `.vercelignore` | Add `skills/james-au-*/`. | F9. |
| `scripts/consumer_ready_artifact.cjs` | Add `skills/james-au-` to the forbidden regex. | F9: the deployment artifact check enforces it. |
| `src/postriff_phase2/hosted_app.py` | A ~5-line dispatch to `coworker/http.py`, one line in `runtime_from_environment` (`coworker.runtime.attach`), and one isolated cron step. | API surface + worker (announced to the site-agent owner). |
| `src/postriff_phase2/email.py` | A guard in `Mailer._deliver` that routes v2-owned kinds to the notification service when the flag is on. `ResendTransport` gains an optional idempotency key and returns the provider id. | F5 (the legacy path is unchanged when the flag is off). |
| `src/postriff_phase2/deployment.py` | Pin the new egress flags off in preview, and pin `RESEND_WEBHOOK_SECRET` and `POSTRIFF_VAPID_PRIVATE_KEY`. | Preview must not inherit production secrets or live egress. |
| `src/postriff_phase2/account_deletion.py` | Delete the user's push subscriptions, notification preferences and deliveries before the profile. | New user-keyed tables. |
| `tests/phase2/rls.sql` | Add `\ir` for 024 and 025. | Otherwise the PG suites run without the new tables. |
| `.env.example` | Document the new flags and secrets (names only). | Convention (F15). |
| `vercel.json` | A header rule for `/sw.js` (`Cache-Control: no-cache`, `Service-Worker-Allowed: /`). | Web Push (spec §18). The runtime session already committed its change to this file. Re-check before editing. |

## 4. Decisions

**R1: Capability registry.** `skills/rafii-registry.json` holds one manifest per capability. Its fields are:
- `id`, `version` (semver), `kind` ∈ knowledge/workflow/tool/policy/evaluator, `sha256`;
- `description`, `intents`, `platforms`, `formats`, `locales`;
- `agents` (compatible specialists), `consumers` (resolvable code references);
- `tool` (a registered typed tool name, or `null`), `policy` (a code reference such as `postriff_phase2.permissions:ACTION_CLASSES`), `evaluator` (a code reference);
- `personalization` ∈ `overlay_only`/`none`/`protected`, `risk`, `tests`, `deprecation` ∈ `active`/`dormant`/`deprecated`, `private` (true only for Studio-only material that the hosted bundle excludes).

The sha256 is computed from the skill directory's files for skill-backed entries, and from the module source + schema for code-backed entries. `scripts/rafii_skill_registry.py --check|--lock` verifies it. Changing content without bumping the version fails the check.

**R2: Consumers are proven, not declared.** The registry test resolves every consumer reference (import + attribute). For knowledge and workflow skills, it also asserts that the named consumer **actually selects the skill** for at least one declared intent/platform, whether that consumer is the `SkillLibrary.bind` selection or `skill_compiler.compile`.

The orphan count is the number of default skill directories without a proven consumer. CI fails when it is above 0, except for entries with `deprecation: dormant` and a recorded reason; those are listed in the report.

**R3: Compiler.** `skill_compiler.compile(task)` builds the effective context from:
- `task = {agent, intent, platforms, locales, format, contentType, workspaceState?, cloudAllowed}`.

It returns:
- `{text (bounded), selections[{id, version, sha256, kind}], overlays{voiceRevision, brandRevision, personalizationRevision, strategyRevision}, tools[{name, sha256}], policies[...], evaluators[{id, version}], budget, omitted}`.

The rules:
- It injects only the relevant knowledge, never every skill.
- Policies are listed as code references and never injected as text that could be overridden.
- User overlays enter only through `overlays.effective_view(state, cloudAllowed)`, so the cloud-memory decision is honoured (runtime ADR-M1).
- `provenance_for_run(compiled, route, traceId)` is the record the runtime puts in `pr_agent_runs.artifact.trace.provenance` (no migration).
- The writer path keeps `SkillLibrary.bind`, and its bindings are joined into the same provenance shape.

**R4: No James in defaults.** `skills/james-au-*` are classified `private: true`, with consumer Studio (`src/james_au_social/studio_codex.py`). They are excluded from the hosted bundle and refused by hosted `SkillLibrary.load`.

A no-leak test scans every file reachable by `SkillLibrary.bind` or the compiler for James identity, biography, projects, career, tone, visual identity and private markers (the ledger lists the patterns). It also runs a cross-workspace test: workspace A's overlays never appear in workspace B's compiled context.

**N1: Notification tables (024).** Five tables:
- `pr_notification_events`: `UNIQUE(scope_key, dedupe_key)`, where `scope_key` is the workspace id, or `user:<id>` for a person-level security event (whose `workspace_id` is null).
- `pr_notification_deliveries`: `UNIQUE(event_id, user_id, channel)`, `UNIQUE(idempotency_key)`, lease columns, bounded attempts, terminal `dead`.
- `pr_notification_preferences`: per user and `(scope_key, category)`, where `scope_key` `'*'` means the person's defaults and a workspace id scopes a row to that workspace; `'*'` as the category covers every category. `in_app` and `email_unsubscribed` are nullable: null means "not set here", so a broader row or the default decides, and an explicit `false` re-subscribes a narrower scope.
- `pr_push_subscriptions`: endpoint/keys encrypted with `CredentialVault`, plus `endpoint_sha256`.
- `pr_notification_provider_events`: `(provider, event_id)` replay ledger, mirroring `pr_billing_events` but separate, so billing health stays accurate.
- Plus `pr_notification_scan (workspace_id, revision)`, so the detector skips unchanged workspaces.

Access control:
- All of them are service-only (as in 008/016), except deliveries and preferences, which the signed-in person can read for their own rows (`authenticated` SELECT with an `own_read` policy: `user_id = auth.uid()` and active membership). Nobody but the service role writes.
- The API always checks membership in app code (F2).
- `user_id` columns have **no FK to `pr_profiles`**: the 018 `created_by` FK already breaks account deletion. Deletion is explicit in `account_deletion.py`.

**N2: Events are derived from authoritative state.** `notifications/detector.py` is a pure, deterministic function `detect(state, relational) -> [Event]`. Each event is keyed by a dedupe key made of the entity id and the state version: a job id + its status + attempt count, or an occurrence id + its stage.
- It is called from a `repository.effects` hook, which is the transactional outbox for command-path changes.
- It is also called from the cron scan, for changes made by workers and billing.
- Billing, trial and security conditions come from `pr_subscriptions`, `pr_trials` and `pr_audit_events`, with the same dedupe keys the legacy senders use.
- New coworker features (Weekly Operator, research, learning proposals, opportunities) call `notifications.emit(cur, …)` explicitly, in their own transaction.

Deviation D2: the spec's wording is "feature modules emit events". The worker/billing paths would otherwise need edits in five shared files. Deriving events from authoritative state is also more truthful: it cannot report a publish outcome that state does not hold.

**N3: Planner.** `notifications/planner.py` is pure code. For each event and recipient it decides:
- the category, the urgency (`immediate`/`digest`/`in_app_only`), `transactional`, and which channels;
- the quiet-hours deferral (zoneinfo, DST-safe), mute, unsubscribe, rate limit and security classification.

The spec §15 defaults are encoded in `notifications/catalog.py`. A model can never set any of these. Routine success (`publish.verified`, `automation.completed`) goes to in-app and the digest by default, never one email per post.

**N4: Delivery.** A cron step claims deliveries with `FOR UPDATE SKIP LOCKED`, sets `lease_owner`/`lease_until` and `attempts+1`, and **commits before any network call**. It completes with a fence on `(id, lease_owner)`.
- Backoff is `min(60·2^attempt, 6h)` with deterministic jitter. After 6 attempts the delivery becomes `dead`.
- Failure classes:
  - `transient`: 5xx, 429 or timeout. The delivery is retried.
  - `permanent`: 4xx, a bounce, or push 404/410. A push 404/410 also revokes the subscription.
  - `config`: the transport is unconfigured. The delivery is marked `suppressed` with that reason, never "sent".
- The idempotency key is `delivery.id`. It is sent to Resend as `Idempotency-Key` and used as the tag for webhook correlation.
- A lost provider response becomes an `uncertain` failure class. It is retried with the **same** idempotency key, so the provider dedupes it.
- Delivery failure never touches domain state: deliveries are separate rows in separate transactions.

**N5: Legacy email bridge.** When `RAFII_NOTIFICATIONS_V2_ENABLED` is off, nothing changes (all existing email tests stay valid). When it is on:
- `Mailer._deliver` refuses to send kinds that v2 owns (`review_ready`, `approval_expired`, `platform_disconnected`, `publish_failed`, `run_skipped`, `drafts_ready`, `trial_ending`, `trial_ended`, `payment_failed`, `subscription_activated` and `new_device`). It returns `{sent: False, reason: "routed_to_notifications_v2"}`, and the detector emits the matching event.
- `invitation` and `welcome` stay direct: they are synchronous account operations whose response reports `emailSent`.

**E1: Email.** `notifications/email_render.py` provides:
- the components EmailShell, Preheader, BrandHeader, ContextLabel, Headline, StatusPill, PrimaryCard, MetricsRow, PrimaryCTA, SecondaryAction, Footer and NotificationSettingsLink;
- one template function per event family;
- localized strings in `notifications/email_locales.json`, for en, zh-Hant, zh-Hant-HK/yue and zh-Hans;
- `TEMPLATE_VERSION`, html.escape everywhere, absolute https deep links only, a subject/preheader that carries no private content, `List-Unsubscribe` + `List-Unsubscribe-Post` using a signed token, and a plain-text fallback.

The renderer is Python, under `src/`, because `web/**` and `docs/**` are excluded from the function (F1). The Resend webhook (Svix signature, 300 s tolerance, `svix-id` replay ledger) is matched before the `_origin` guard, like the Stripe webhook.

**E2: Push.**
- `web/public/sw.js` handles `push` and `notificationclick`, opening same-origin relative deep links only.
- Opt-in is explicit, and only from Account → Notifications. The page never auto-prompts.
- `notifications/push.py` implements VAPID ES256 and aes128gcm.
- The payload is `{title, body, url, tag}`, at most 3 KB, with no draft text, DMs, analytics or secrets.
- 404/410 revokes the subscription and 429 honours `Retry-After`.
- The transport interface `PushTransport.send(subscription, payload, ttl, urgency, topic)` leaves room for APNs/FCM later.

**A1: Adaptive overlays.** `coworker/overlays.py` exposes three separate views:
- **voice** (how the person writes: approved voice revision + learned `writing_preference` items + explicit voice overlays);
- **brand/content** (Brand Brain `brandHub` + explicit brand overlays + terminology);
- **strategy** (`pr_strategy_hypotheses`, which is never injected as identity).

Every item carries: explicit|inferred, evidenceIds, counterEvidenceIds, confidence (0–1, from support and counter-evidence), scope (platform, language, contentType, audience), revision, replaces, createdAt, lastSupportedAt, expiresAt (decay: inferred items half-life 90 d, then `expired`), and status active|paused|expired|retired.

The controls are inspect, edit (explicit only), disable, reset and export, all through `repository.command` at owner level. Explicit items outrank inferred ones. A platform-scoped item never applies to another platform. Protected policy keys cannot be overlaid; the registry `personalization: protected` is enforced by `skill_registry.validate_overlay`.

**H1: Humanizer stage.** `coworker/humanizer.py` runs voice-fit (reusing `site_agent/voice_check.analyze` read-only), then the humanizer detectors, then the meaning-preservation diff, then platform/locale lint (`locale_lint`, `text_measure`).
- The humanizer detectors cover EN AI-vocabulary/phrase clusters and zh markers (zh-Hans, zh-Hant, yue) as density signals, not blacklists.
- The meaning-preservation diff compares numbers, dates, named entities, negations, hedges/uncertainty, attribution and scope words between source/facts and candidate.
- The output is a candidate annotated with findings and `evaluatorVersion`.
- A rewrite is applied only by a model route that can revise. Locally the deterministic stage **never rewrites text**; it flags. Deviation D3: rewriting needs a live model, so locally this is PARTIAL-by-design, and the evaluator is verified.

**S1: Research Broker.** `coworker/research_broker.py` defines `ResearchProvider` with `capabilities()`, `readiness(state)`, `search(query, scope)`, `fetch(ref)` and `provenance(result)`. The providers:

| Provider | Wraps | Hosted? |
|---|---|---|
| `WebSearchProvider` | Exa | yes, behind owner `researchEgress` |
| `WebReaderProvider` | Jina | yes, behind owner `researchEgress` |
| `OfficialPlatformApiProvider` | `social_history`, owned posts only | yes |
| `MCPResearchProvider` | registered connectors only | readiness `not_configured` until one exists |
| `LocalAgentReachProvider` | Agent Reach | never hosted |

`LocalAgentReachProvider` readiness checks `not research.hosted()`, an explicit `POSTRIFF_AGENT_REACH=1`, and file-only checks. It never calls `agent-reach doctor` (that makes network calls).

Every item carries: provider, platform, query, url, retrievedAt, publishedAt, author, accessMethod, contentHash (raw), representedScope, evidenceType, rights, claim links. Raw excerpts go to `pr_research_evidence` (025). Fetched text is wrapped as untrusted data, and an injection-pattern detector flags it (a flag, not a block).

**S2: FactPack → CanonicalBrief → campaign.**
- `coworker/fact_pack.py`: claims with status confirmed/corroborated/attributed/disputed/unverified, evidence relations supports/contradicts/context_only, and contradictions kept. A search snippet alone is `unverified` and `usableForDraft:false`.
- `coworker/service.py` (`CoworkerService.source_campaign`, with `source_intake.py` and `fact_pack.py`): SourceArtifact → FactPack → CanonicalBrief → AngleCandidates → ChannelDrafts (through `IdeasService.turn/apply` with the brief as `material`, data only) → CreativeBriefs → CampaignArtifact. The campaign is created through `campaigns.apply_action('raffi_campaign_create')` inside `repository.command`, and drafts are linked with `raffi_campaign_link`.
- The objects live in `state.coworker.sourceCampaigns` (bounded). Provenance ids travel through every stage and are asserted in tests.

**W1: Weekly Social Operator.** `coworker/weekly_operator.py`:
- A recipe in `state.coworker.weekly.recipes` holds goals, platforms, frequency, mix, campaigns, planning day, timezone, watchlists, voice mode, review policy, asset expectations and budget.
- A week in `state.coworker.weekly.weeks` has `states planned → researching → generating → quality_check → ready_for_review → approved → scheduled` and blocked states `needs_input | needs_source | needs_asset | channel_unavailable | approval_expired`.
- The cron triggers it on the planning day in the recipe's timezone. Each stage is idempotent and keyed `weekly:{recipe}:{isoWeek}:{stage}`.
- Drafts come through the existing writing pipeline, and the quality stage uses H1.
- Reaching `ready_for_review` emits exactly one `campaign.week_ready` (dedupe `week_ready:{week}`).
- Approval uses the **existing** review/approval path (`p2_review` → approve). Weekly Operator never schedules or publishes by itself, and an approval that expires becomes `approval_expired`.
- Measure/learn feed WP8 through the existing learning events.

**C1: Creative.** `coworker/creative.py` uses the existing asset pipeline (`state.phase2.assets`, the audited `add_asset`, the usage ledger) and the runtime's non-destructive lineage fields, `lineage {operation, parentAssetId, sourceAssetIds, model, route, promptSummary, runId, traceId}`, without editing `agent_runtime_v2/creative.py`.
- Local/deterministic parts: platform aspect/safe-area plans, carousel/thumbnail concepts, a brand-fit checklist, a CTA hierarchy check, and an alt-text requirement check.
- Generation, editing and vision critique need a model. Locally they use the runtime's fake transports, and are labelled so.

**P1: Performance learning.** `coworker/performance.py` builds comparable cohorts over `insights`. Its dimensions are platform, contentType, language, hook style, length bucket, CTA, visual type, weekday, hour bucket and frequency.
- A hypothesis is emitted only when n ≥ 5 per arm and the difference exceeds noise.
- Each hypothesis records sample size, date range, evidence ids, counter-evidence, confidence, `causal:false` (enforced by a DB CHECK), status `candidate|experiment|supported|rejected|expired`, and expiry.
- It never writes voice or learning items. It can propose an experiment and emit `learning.preference_proposed` for the owner's decision only.

**L1: Listening + Engagement.**
- Watchlists use only lawful, available sources: the research broker with owner consent, owned-account APIs and audience threads.
- An opportunity carries evidence, source, freshness, relevance, novelty, confidence, expiry and proposed action. `opportunity.detected` needs deterministic thresholds and is digest-only below high confidence. There is no manufactured urgency.
- Engagement triage and reply drafts go over `pr_audience_threads`. Sending stays `AudienceService.approve_reply`: `reply` permission, digest and `confirmed:true`.

**T1: Attention.** `coworker/attention.py` is a deterministic synthesis of:
- approvals, failed/held/uncertain jobs and reconnects;
- deadlines, weekly plans and missing assets;
- important engagement and high-confidence opportunities;
- budget/billing.

Each item has a priority (a fixed rule table), `why`, evidence and a deep link. Engagement is never marked urgent by default.

**G1: Growth.** `coworker/growth.py`:
- `pr_product_events` (025) holds ids, counts and categories only, with a TTL.
- Metrics are computed from events + existing tables. There are 18 metrics, listed in the spec §22 and README.
- `pr_experiment_assignments` gives deterministic hash bucketing per workspace, with exposure logging. Nothing hard-codes a winner.

**RT1: Agent Runtime convergence.**
- `coworker/agent_tools.py` registers READ/CREATE_DRAFT tools through `tool_adapter.register`. They include `attention_summary_v2`, `weekly_plan_get`, `weekly_plan_prepare` (CREATE_DRAFT), `research_search`, `fact_pack_get`, `overlay_context`, `strategy_context`, `notification_list`, `engagement_triage` and `engagement_draft_create` (CREATE_DRAFT; the reply-send tool does not exist).
- EXTERNAL_EFFECT is forbidden by the runtime and stays forbidden.
- Specialist mapping: Manager = `rafii_manager`, Research = `research`, Content = `content`, Creative = `creative`, Analysis = `analytics`. **No new agents** (deviation D4: the spec names five specialists; the runtime already has eight, and the five map onto existing keys).
- Scope-list and instruction edits are requested from the runtime owner.
- Fallback: with any coworker flag off, every tool returns `{ok:false, code:"feature_disabled"}`. With the runtime off, the site agent answers as before.

## 5. Feature flags (default off; `1/true/yes/on`)

`RAFII_SKILL_REGISTRY_V2_ENABLED`, `RAFII_NOTIFICATIONS_V2_ENABLED`, `RAFII_WEB_PUSH_ENABLED`, `RAFII_ADAPTIVE_SKILLS_ENABLED`, `RAFII_WEEKLY_OPERATOR_ENABLED`, `RAFII_RESEARCH_BROKER_ENABLED`, `RAFII_CREATIVE_AGENT_ENABLED`, `RAFII_PERFORMANCE_LEARNING_ENABLED`, `RAFII_LISTENING_ENABLED`, `RAFII_ENGAGEMENT_COPILOT_ENABLED`, `RAFII_GROWTH_EXPERIMENTS_ENABLED`.

They are defined in `coworker/flags.py` and reported through `GET /api/workspaces/{id}/coworker/status`, never as `NEXT_PUBLIC_*`. The preview deployment pins every egress flag off (`deployment.isolated_environment`). The rollout plan is in `ROLLOUT.md`.

## 6. Deviations from the governing spec

| ID | Spec says | This implementation | Reason |
|---|---|---|---|
| D1 | `capabilities.py` for the registry | `skill_registry.py` + `skill_compiler.py` + `skills/rafii-registry.json` | F7 name collision |
| D2 | Feature modules emit events | Deterministic state detector (effect hook + cron scan) plus explicit `emit()` for new features | F4. Worker/billing state changes bypass `repository.command`, and deriving from authoritative state cannot claim unheld outcomes |
| D3 | Humanizer rewrites | Deterministic evaluator stage flags. Rewriting only on a model route that can revise | No live model locally. Deterministic text rewriting would risk meaning drift |
| D4 | Five specialists | Map onto existing runtime keys; no new agents | Spec §13 "do not add agents to mirror modules"; the runtime already has them |
| D5 | Flags in one config system | `coworker/flags.py` mirrors `agent_runtime_v2/config._flag`; merged into `config.FLAGS` on release | F15 file ownership |
| D6 | `rafii-content-craft`, `rafii-research-provenance`, `rafii-visual-craft` ids | Keep `postriff-content-craft`, `postriff-research-and-source-log`, `postriff-social-graphics` ids (registry `aliases` lists the spec names) | Recorded writer-run hashes/ids and `SkillLibrary` constants stay stable. The spec §6 allows retention "until a rename is justified" |
| D7 | Spec §16 suggests FK-free design implicitly | No FK from new user-keyed tables to `pr_profiles`; explicit deletion | Verified 018 deletion bug (`account_deletion.py:108-111`) |
| D8 | Migration "020" implied next | 024 / 025 | F16 collisions |

## 7. Migrations and merge order

- `024_notification_core.sql` and `025_coworker_evidence_growth.sql` are forward-only and idempotent (`if not exists`, with `pg_policies`-guarded policies, in the 018 style).
- There is no down migration. Rollback means turning the flags off. The tables can stay empty, or be dropped by a new forward migration if the owner decides to.
- Before merge, re-run `git for-each-ref` over every branch plus the main checkout's untracked migrations. If 024/025 have been taken meanwhile, renumber **before** any environment applies them. Renaming after apply is refused by the checksum ledger.
- Production migrations are **not** run by this work.

## 8. Verification plan (the evidence standard is §29 of the execution prompt)

Deterministic unit tests (`tests/test_rafii_*.py`) and PostgreSQL scenarios (`tests/phase2/postgres_coworker_*.py`, auto-discovered by `postriff_pg_suite.py`) run on the Python 3.12 venv with `POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0`, on port 55738.

The email render evidence and push service-worker browser checks run through Chromium and WebKit using the path overrides.

The machine-readable results go to `docs/design/site-agent/adaptive-social-coworker/evidence/verification.json`. They are generated by `scripts/rafii_coworker_verify.py` and never edited by hand.

Nothing is sent, published, charged or deployed live.

## 9. Decisions made during implementation (recorded after the lock)

| ID | Decision | Why |
|---|---|---|
| I1 | The Weekly Operator drafts through `IdeasService.turn` with the slot brief as `material` and an explicit instruction, not through `recurring_binding`. | `ideas._finish` validates `recurringBinding` against an automation occurrence (`campaign_worker.validate`), so a weekly draft would be refused. `material` is the pipeline's existing drafting-request path, the one campaign reworks and runtime `draft_create` use: never an automation, schedule or memory. A per-week cost guard sums `pr_agent_runs.usage.costUsd` for `weekly:{week}:%` before each slot. |
| I2 | Writer extras drop order on a tight budget: Humanizer packs → the existing optional references (`DROP_ORDER`) → the active workflow's skill → `FALLBACK_ORDER`. | The paid-route budget (60k characters) is already nearly full. The deterministic Humanizer stage checks every draft either way, while the workflow skill is small and specific to the run. Omissions are recorded in `usage.skillOmissions`. |
| I3 | Registry hashes are stored as `sha256:<hex>`. | Bare 64-hex strings trip detect-secrets' "Hex High Entropy String" in the release secret scan. A labelled digest is not an entropy finding, and no allowlist entries were added. |
| I4 | Agent Runtime integration uses the runtime owner's guarded extension points (`domain_tools.EXTENSION_MODULES`, `specialists.extend_scope`, `specialists.INSTRUCTION_HOOKS`, `service.register_trace_hook`), added in 6b0a9af. No runtime file is edited by this work. | File ownership (§2). An extension that fails is skipped by the runtime and never breaks a turn. |
| I5 | `operational_signals` keeps `notificationDelivery: 'not_configured'` while v2 is off, so the existing test and contract are unchanged. With v2 on, it reports `rafii_v2`, `notificationBacklog` and `notificationDead24h`, and excludes v2-owned legacy rows from `notificationsUnsent`. | Existing tests are never weakened. |
| I6 | Preview refuses the egress flags (notifications, push, research broker, listening) and pins the new secrets. | Same fail-closed rule as `POSTRIFF_RESEARCH` / `POSTRIFF_LOCAL_CLI`. |
| I7 | `listening.ingest` requires relevance ≥ 0.2 before scoring. | A fresh, novel but unrelated result must not become an opportunity. The unit test caught this. |
| I8 | Email template version `rafii-email/1.0.3`. | 1.0.1 fixed a duplicated `class` attribute and link contrast in dark mode, which axe caught. 1.0.2 removed a duplicated approval sentence and softened the dark divider. 1.0.3 makes the weekly-ready lead truthful: posts are checked against the person's voice, and against sources only where they have them. |

## 10. Review remediation (WP10-WP11 adversarial review)

A bounded read-only review (6 tracks plus a skeptic, 2026-09-25) reported 53 findings: 11 high, 9 medium and the rest low; 1 was refuted. HANDOFF.md lists each with its outcome. These decisions came out of it:

| # | Decision | Why |
|---|---|---|
| V1 | **First scan is a silent baseline.** A workspace's first detector scan (no `pr_notification_scan` row, and created more than 10 minutes ago) records the events its state implies without planning any delivery. The very first cron run treats the last day's security audit rows the same way. | Turning notifications v2 on must never mail people about months-old failures, or repeat alerts the legacy mailer already sent. |
| V2 | **Idle workspaces are re-scanned hourly** (`RESCAN_SECONDS`), besides every workspace whose revision changed. | Billing, trial and token-expiry conditions change without a workspace revision; the legacy senders for them are routed to v2. |
| V3 | **Legacy parity for automations.** The detector emits `campaign.approval_required` when the worker records `notices.reviewSentAt`, again for an item whose approval was voided (its own dedupe key), and `publish.failed` for an item that failed without a job. `trial_ended` stays with the legacy mailer (v2 has no trial-ended event). `billing.subscription_active` is keyed on the subscription, so a renewal is not a new activation. | Routing a legacy kind to v2 must never drop or change the notice. |
| V4 | **Preferences are re-checked at send time** (`planner.opted_out`): an unsubscribe, a bounce or complaint suppression, a mute, or a channel switched off after the delivery was planned completes the row as `suppressed` (reason recorded). Transactional notices ignore these, as at planning time. | "You won't receive these any more" must hold for email already queued. |
| V5 | **Digest recovery and truth.** An expired digest claim is recovered on its own (same rows, so the same Idempotency-Key and body). Rows excluded from a digest are completed as cancelled/suppressed, never as sent. The provider webhook applies a digest's outcome to all its rows. Unsubscribe links are based on the delivery's creation time, so a retry renders the same body. | Resend refuses a different body under the same key, and a crash must not turn into a duplicate or a false "sent". |
| V6 | **A $0 weekly limit drafts nothing.** Runs with no recorded cost count at their usage-ledger reservation, else a fixed $0.05 estimate; only a run that made no model call counts as free. | The owner's limit is a hard cap on paid drafting. |
| V7 | **Truthful weekly state.** An expired approval moves the week to `approval_expired` whatever else it holds; answering a question in a week already in review reopens it; the agent tool reports only posts that call drafted and read back; the meaning check records its basis (`approved_facts`, `your_answer` or `none`) and the UI says "Facts not checked" for `none`. | prepared ≠ scheduled ≠ published, and "checked" only when it was. |
| V8 | **Bounded time.** The coworker cron step has a 120 s budget within the worker's 300 s. A paid writer run starts only if 95 s remain; the agent tool drafts at most 2 posts per call and refuses when the turn has under 100 s left. | Nothing paid runs past its caller's deadline. |
| V9 | **Permission before egress.** Research search and link sources check `edit` before any provider is called. Week detail is readable by any member; only an editor's read saves the Queue sync. The attention route and tool are gated on notifications v2 or the weekly operator. | A viewer never causes egress, and flags-off leaves the Overview unchanged. |
| V10 | **Registry gates.** A consumer probe may only use a workflow that production code enters (`workflow_context` or a compile task); `rafii-listening-opportunity` is dormant until listening drafts. The leak gate also scans the coworker UI and email copy. Provenance marks a method as attached but not model-applied where a deterministic path produced the text, and the runtime trace records the skills compiled into each routed agent's instructions. | The registry must describe what actually shapes output. |

