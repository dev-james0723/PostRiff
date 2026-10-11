# R0 map: security, tests and CI (lanes D, G and A)

- **Reader:** read-only R0 reader for role A. **Date:** 2026-10-08.
- **Worktree:** `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`, branch `claude/rafii-openui-production-20261008`, HEAD `3da806f0` (= `origin/consumer-saas`).
- **Method:** rg, sed, cat, git show/log, and read-only `gh api` calls. I ran no builds, tests, npm, tsc or JCB tasks, and printed no secret values.
- **Legend:** **[V]** = verified in code or command output. **[I]** = my inference, which needs confirmation.

> **Concurrent-change notice [V]:** I did not modify anything. During my read, two files in this worktree became modified: `.james-cloud-build.json` (only `lockfileSha256` changed) and `.depot/workflows/james-cloud-build.yml` (cache-mount names changed from `07c94c20` to `c347e642`). That is what `jcb setup --force` produces. Someone else in this worktree regenerated JCB (see §9.4). Those edits are uncommitted.

---

## 1. Authorization model: `src/postriff_phase2/permissions.py` (113 lines) [V]

| Symbol | Line | Facts |
|---|---|---|
| `ROLES` | 10 | `("owner","admin","editor","approver","viewer")`. The task text says "owner/editor/viewer", but migration 001 had only those three. Migration 004 (`004_consumer_web_tenancy.sql:7-9`) widened the check to five roles. |
| `FLAGS` | 11 | `can_publish, can_reply, can_moderate, can_manage_connections` (columns on `public.pr_memberships`) |
| `CLASSES` | 15-24 | `read` (all roles), `edit` (owner/admin/editor), `approve` (owner/approver, or flag `can_publish`), `reply` (owner, or `can_reply`), `moderate` (owner, or `can_moderate`), `manage_connections` (owner/admin, or flag), `manage_members` (owner/admin), `owner` (owner) |
| `ACTION_CLASSES` | 27-54 | Maps an action name to its class. **Any action not listed is `edit`.** Approvals: `p2_review/p2_approve/p2_approve_many/p2_cancel` and `raffi_run_decide/raffi_run_commit` are `approve`. Owner-only: all `*_egress`, `writer_defaults`, `preference`, `learning_*`, `profile_decide`, `voice_sample_grant`, `raffi_recurrence_activate/pause/resume/cancel`. Read: `refresh`, `p2_refresh`, `raffi_recurrence_watch`. |
| `STEP_UP_ACTIONS`, `STEP_UP_WINDOW` | 57-58 | `{p2_channel_disconnect, delete_account, member_update, member_remove, invitation_create, session_revoke}`, 600 s |
| `class Membership(role, flags)` | 61-83 | `.from_row(role, can_publish, can_reply, can_moderate, can_manage_connections)`. `.allows(req)`: owner always passes; otherwise role in `spec.roles`, or (flag set and role is not viewer). An unknown requirement returns False, so it fails closed. `.summary()` |
| `classify(action)` | 86-89 | Raises on a non-string action. Unknown actions classify as `edit`. |
| `require(membership, requirement)` | 92-94 | Raises `AlphaError("This action needs the '<req>' permission in this workspace.", 403)` |
| `require_action(m, action)` | 97-98 | `require(m, classify(action))` |
| `validate_grant` | 101-113 | Members can grant only flags they hold themselves. Only owner/admin can create admins. |

**Implications for D (UI action effect classes):**
- Every `actionId` in the manifest must map to an explicit requirement class.
- `classify()` defaults unknown names to `edit`, so a new UI action that is really an approval or an owner decision must be registered explicitly. Otherwise an editor could reach it.
- Recommendation: give `ui_actions.py` its own allowlist `{actionId: (domain_action, requirement, step_up)}`. It must not fall back to `classify` for unknown IDs; unknown IDs are refused.
- Viewers (and any role) may run queries with `require(m, "read")`.

## 2. Principal derivation, `transaction()` semantics and the DB role

### 2.1 `PostgresWorkspaceRepository.transaction(token, workspace_id, *, allow_deleting=False)`: `src/postriff_phase2/hosted.py:113-133` [V]

1. If the token is an API token (`api_tokens.is_api_token`, prefix `prt_`), the principal is `api_tokens.resolve(token, workspace_id)["createdBy"]`. Otherwise the principal is `self.verify_session(token)`. The comment says "Verified identity only".
2. One connection is opened from `connection_factory()`, then a single statement runs: `SELECT w.revision, w.state, m.role, m.can_publish, m.can_reply, m.can_moderate, m.can_manage_connections FROM public.pr_workspaces w JOIN public.pr_memberships m … JOIN public.pr_profiles p … WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w`.
   - **It takes a row lock on the workspace row** for the whole `with` block.
3. No row raises `AlphaError("Workspace unavailable.", 403)`. A foreign workspace and a nonexistent one give the same message.
4. `state.accountDeletion` raises 409 `account_deletion_pending`, unless `allow_deleting` is set and the caller is owner. `state.accountBlock` raises `operator_actions.blocked_error()`.
5. API-token grants are re-validated and locked (`api_tokens.validate`).
6. It yields `(cur, row, principal)`. The membership is `Membership.from_row(*row[2:7])`, also exposed as `HostedWorkspaceService.ideas._member(row)` (`ideas.py:699`).

Related methods:
- `assert_fresh(token, principal)` (135-143): step-up check. API tokens are refused. Uses `verify_session.auth_time` against `STEP_UP_WINDOW`.
- `get()` (145) uses `allow_deleting=True`.
- `command(workspace_id, token, revision, trusted_command, requirement="edit", step_up=False, audit_event=None, after=None)` (150-171):
  - runs `require(...)`, optionally step-up, then a revision CAS (`409 workspace_revision_conflict`);
  - runs `trusted_command(state, principal)`, then `UPDATE pr_workspaces SET state, revision=revision+1`;
  - writes `audit()` and runs `self.effects` hooks and `after(cur, state, principal)`, all in the same transaction.
- `mutate(workspace_id, token, expected_revision, action, payload)` (173-198): routes to `HostedPhase2Commands`, with `requirement=classify(action)` and `step_up=action in STEP_UP_ACTIONS`.
- `audit(cur, workspace_id, actor, kind, subject="", meta=None)` (96-98): inserts into `public.pr_audit_events`, which is append-only. It must stay content-free: no prompts, bodies, tokens or emails.
- `throttle(cur, scope, limit, window_seconds)` (82-93): a fixed-window counter on `public.pr_auth_throttle`, keyed by a hashed scope, raising 429. **This is the reusable mechanism for the contract's "60/min per principal+artifact" query admission.**

### 2.2 How the session is verified: `hosted_app.py:50-98` (`supabase_verifier`) and `provider_candidates.py:231-245` [V]

- The bearer comes from `HTTP_AUTHORIZATION`. `HostedApplication._token(environ)` (`hosted_app.py:285-290`) requires `Bearer ` plus more than 20 characters.
- `SupabaseSessionCandidate.verify` performs a server-side HTTPS **Supabase `GET /auth/v1/user` on every call**, with a 12 s timeout. It requires a 36-character id and a confirmed email or phone.
  - Then one DB statement checks `pr_account_tombstones`, `pr_session_revocations` (by `session_id`) and `pr_mfa_enforcement`, plus the operator block.
  - If MFA is enforced and the session is not aal2, it returns 403 `mfa_required`.
- **There is no caching [V].** Every `repository.transaction()` costs one Supabase HTTPS round trip plus one DB query.
  - [I] For streaming, live queries (G17 latency) and repeated checkpoints, don't call `transaction(token, …)` per delta.
  - Use the existing worker pattern `automation_runs.principal_repository(service, workspace_id, principal, requirement, check=None)` (`src/postriff_phase2/automation_runs.py:38-63`). It verifies once, then hands back a private capability object. Every transaction still re-checks membership class and workspace equality. `founder_agent.py` and `phone/service.scoped_runtime` use the same pattern.
- The verifier exposes `verify.session_id`, `verify.auth_time`, `verify.aal`, `verify.proof` and `verify.passkey_time`.

### 2.3 DB role and RLS: application-layer isolation, not RLS [V]

- The production API connects with `psycopg.connect(POSTRIFF_DATABASE_URL, prepare_threshold=None, connect_timeout=8)` (`hosted_app.py:38-47`). `docs/postriff-phase-2/hosted-deployment-preparation.md:25,37` says this goes through the Supabase transaction-mode pooler on port 6543 with TLS.
- **`src/postriff_phase2` never runs `SET ROLE` or sets `request.jwt.claim*` [V].** Tenant isolation for every consumer API request is the explicit membership JOIN plus `workspace_id=%s` predicates in application SQL.
  - [I] The pooler login is a privileged role (Supabase `postgres`), so RLS does not constrain the Python API.
- RLS exists as **defense in depth for direct browser access**, meaning PostgREST with the `authenticated` role:
  - `001_phase2.sql:5-63`: `postriff_private.member(uuid)` helper; `tenant_read` SELECT policies for `authenticated`; `trusted_write ... to service_role`; `revoke all from public, anon, authenticated`; `grant select to authenticated`.
  - **Service-only tables** use a different pattern: revoke everything from anon/authenticated, `grant all to service_role`, and a `service_only` policy. Examples: `031_chat_media.sql:44-49`, `093_universal_library.sql:61-69`.
  - **`pr_agent_runs` and `pr_agent_events` (`005_consumer_web_ideas.sql:40-69, 88-94`) are `tenant_read` [V].** Any active member of the workspace, including a viewer, can SELECT every run's `artifact` jsonb and event bodies directly through PostgREST.
  - [I] Consequence: raw OpenUI source deltas or canonical source must **not** be stored in `pr_agent_events` or `pr_agent_runs.artifact` if conversation privacy is stricter than workspace-wide read. New UI artifact tables should be **service_only**, and the API should filter by scope.
  - `pr_agent_events.kind` has a CHECK constraint (`005:64`) that allows only the 11 `SAFE_EVENTS` kinds (`agent_runtime.py:14`). New `ui.*` kinds cannot go in there without a migration, and the contract says raw deltas must not go there anyway.
- **Founder side uses real DB-role isolation [V].**
  - `rafii_control/store.py:31-44`: `ControlStore.transaction(read)` asserts `current_user` is `rafii_control_reader` or `rafii_control_session`, and not superuser or bypassrls. It sets `rafii_control.environment` and `statement_timeout`.
  - `store.py:200-215`: the login must be non-superuser and non-bypassrls outside local, then it runs `SET ROLE`.
  - The roles are created in `049_rafii_control_foundation.sql:7-12`.
- **"Do not use service-role bypass to prove RLS" (spec R3/G07) [V]:** the existing harness proves RLS only in `tests/phase2/rls.sql` via `set role authenticated` plus `select set_config('request.jwt.claim.sub', '<uuid>', false)` (`rls.sql:72-73, 107, 127`).
  - All Python PG scripts connect as the initdb superuser (`-A trust`) and prove *application-layer* isolation through `HostedWorkspaceService` with an injected `verify`.
  - Any new UI table needs (a) rls.sql-style `authenticated` negative assertions and (b) app-layer two-tenant negatives.

### 2.4 Workspace path vs. membership, and workspace switch

- **Server [V]:**
  - The workspace ID always comes from the URL (`parts[2]` in `hosted_app._handle`, or `agent_runtime_v2/http.py:50`). It is only a *requested* scope; `transaction()` proves membership on every call.
  - There is no server-side session-to-workspace binding, so a "switch" is simply a different path ID.
  - Midstream switch safety on the server therefore means re-running `transaction()`/`principal_repository` on each replay, query and action. Per §2.2, replays are re-authorized on every request.
- **Browser [V]:**
  - `web/src/lib/workspace/provider.tsx:123-134` `switchTo(workspaceId)` sets React state, `localStorage[WORKSPACE_KEY]` and the cookie `postriff_workspace`. It does **not** abort in-flight fetches or clear the query cache.
  - TanStack queries are keyed by workspace (for example `['usage', selected]`).
  - When the identity changes, `web/src/lib/auth/session-query-boundary.tsx:8-15` remounts a **new QueryClient**, and its unmount runs `cancelQueries()` and `clear()`.
  - `signOut` (`session.tsx:229-245`) calls `api.logout()`, `clearDraftStorage()` and Supabase `signOut({scope:'local'})`.
  - The API client (`web/src/lib/api/client.ts:78,117-132`) adds `Authorization: Bearer` and `X-PostRiff-Request: founder-alpha` (`APP_GUARD_HEADER`). It uses `AbortSignal` only for timeouts.
  - **Gap [V]:** nothing aborts per-workspace streams when the workspace switches. F and C must key artifact caches and streams by `(identity, workspaceId)` and abort in effect cleanup when `workspaceId` changes. Contract §4 says to "Abort previous scope requests on workspace switch".

## 3. HTTP boundary to extend

### 3.1 Consumer [V]

- `hosted_app.HostedApplication._handle` (`hosted_app.py:484+`) runs in this order:
  1. `/api/control/v2/*` is delegated to founder Control (500-508).
  2. API-token authorize (497-501).
  3. Public routes.
  4. `_origin(environ, mutation)` (310-321): every POST/PUT/PATCH/DELETE needs `X-PostRiff-Request: founder-alpha`, and the `Origin` header must equal the forwarded proto and host.
  5. `token = self._token(environ)`.
  6. Path dispatch.
- `/api/workspaces/{id}/agent/*` is dispatched to `agent_runtime_v2/http.py:handle(app, environ, start_response, service, token, method, parts)` (`hosted_app.py:781-784`).
  - That handler calls `api_guard.require_session_token(token)` first (`api_guard.py:5-8`), so API tokens are refused with 403.
  - Existing resources: `status`, `turns`, `conversations/{c}/active-run`, `runs/{r}`, `runs/{r}/events?cursor=`, `runs/{r}/cancel`, `conversations/{c}/state`, `tasks/{t}`, `approvals/decide`, `attachments`, `voice/sessions…`. Anything else returns 404 "This hosted route is unavailable." (`http.py:86`).
  - **The new `/api/workspaces/{id}/agent/ui/...` falls naturally under `resource == "ui"` in this handler.** That makes `agent_runtime_v2/http.py` the shared file A must patch (one `if resource == "ui": return ui_http.handle(...)` line), with no change to `hosted_app.py`.
- Response helpers: `app._json` (276-283) sets Content-Length, `Cache-Control: no-store`, `nosniff` and `no-referrer`. `app._body` (292-308) requires a JSON content type and at most 12,000,000 bytes.
  - [I] The 128 KiB and 32 KiB source caps must be enforced separately and before parsing.
  - The app is **WSGI**. Streaming SSE needs an iterator body, not `_json`; that is B's G04 proof.

### 3.2 Founder [V]

- Route family: `/api/control/v2/agent/*`, in `src/rafii_control/http.py`.
  - `FOUNDER_PREFIXES` (line 18) includes `/agent/`.
  - Agent routes get a 270 s budget (67-71).
  - `_capability(path, method)` (313-345) is deny-by-default. Existing founder agent turn and run paths require `copilot.use`.
- Authorization goes through `Boundary.authorize(token, capability, origin=, csrf=, unsafe=, step_up=...)` (`rafii_control/auth.py:198-227`):
  - requires assurance `aal2`;
  - requires the capability to be in the operator's capabilities;
  - unsafe requests need the origin allowlist plus `csrf_token` HMAC;
  - per-minute `BUDGETS` (`auth.py:28`), e.g. `founder.agent.turn: 20`.
- **Extension seam (no edit to `_capability` needed):** `register_route(method, pattern, capability, module, function, *, step_up|budget|demo_ok)` (`rafii_control/http.py:26-33`). A module registers at import, and the module must be listed in `rafii_control/slices.py:13-26 SLICES`. That registry is shared, so A owns it.
  - Recommended founder UI routes: `/agent/ui/presentations…` with capability `copilot.use` (read) and budget `founder.agent.turn`.
- The founder agent runs as the ops-workspace member via `principal_repository`. Its idempotency keys are namespaced `founder:<mode>:<environment>:` (`rafii_control/founder_agent.py:1-24`).

### 3.3 Routing and deploy constraints for a Node parser seam [V]

- `vercel.json` rewrites, in order: phone media → `rafii_phone_media`, then `/api/(.*)` → `postriff_api` (Python), then `/(.*)` → `postriff_web`. `api/index.py` has `maxDuration: 300`.
- **`scripts/check_postriff_hosted_preflight.py:61-75` requires the rewrites array to *equal* exactly these four entries.** `tests/test_postriff_hosted_deployment.py:~101-116` swaps entries and expects failure. So any new `/api/...` rewrite to `postriff_web` means editing vercel.json, the preflight checker and its test, all A-owned.
- Precedent exists for a Next route handler outside `/api`: `web/src/app/auth/callback/route.ts`. `web/next.config.ts:51-63` proxies `/api/*` to Python only when `POSTRIFF_API_ORIGIN` is set or in development; non-`/api` paths stay in Next.
- [I] Lowest-risk parser seam: a Next route handler at a non-`/api` path, called server-to-server from Python with an HMAC internal secret. This needs no vercel.json change, but Python would call its own public origin. See decision D3.
- `.vercelignore` excludes `/migrations/`, `/scripts/`, `/tests/` and `/docs/` from deploy upload.

## 4. Existing mechanisms D/G must reuse (security-relevant)

- **Approvals [V]:** `agent_runtime_v2/approvals.py`.
  - `decide(service, workspace_id, token, *, conversation_id, message_id, proposal_id, digest, decision, zone=None)` (136-163) calls `service.site_agent.apply_proposal` or `dismiss_proposal`. It retries once only on `workspace_revision_conflict`, then re-reads and runs `verify_applied` (102-133).
  - HTTP route: `POST /api/workspaces/{id}/agent/approvals/decide`.
  - `open_proposals` (52-63) returns `digest` and `expiresAt` and filters out expired proposals. `BIND_WINDOW_SECONDS = 600`.
  - **This is the only apply/dismiss authority for generated UI (contract §6).**
- **Idempotency [V]:** there is no generic idempotency table. Each feature has its own `idempotency_key` with a unique constraint: `pr_agent_runs unique(workspace_id, idempotency_key)` (`005:50,56`), and also 007, 018, 019, 024, 033 and 040.
  - Reference test: `tests/phase2/postgres_final_idempotency.py`. It covers same key replays the run, same key with a different request returns 409, and crash after reservation leaves a single run.
  - [I] `UiActionV1` idempotency needs a new A-allocated additive table, or reuse of a domain command's own key.
- **Cost kill switch [V]:** `billing.ai_paused()` is `POSTRIFF_AI_PAUSED == "1"` (`billing.py:97-99`).
- **Agent flags [V]:** these are env-based, from `agent_runtime_v2/config.py:103+`: `RAFII_AGENT_V2_ENABLED`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_VOICE_ENABLED`, `RAFII_IMAGE_AGENT_ENABLED`, `RAFII_AGENT_THINKING_STATES_ENABLED`, `RAFII_PROACTIVE_V2_ENABLED`, `RAFII_AGENT_PROVIDER`, `RAFII_AGENT_PRIMARY_MODEL`, `RAFII_AGENT_FAST_MODEL`, `RAFII_AGENT_MODEL_PRICES`, `OPENAI_API_KEY`, `AI_GATEWAY_API_KEY`/`VERCEL_OIDC_TOKEN`.
  - I found **no DB-backed runtime feature-flag service** (rg for kill-switch/feature_flag found only connector waves and learning).
  - [I] A Vercel env change only takes effect on a new deployment, so an env-only `RAFII_GENUI_*` kill switch costs one redeploy.
- **Local QA harness [V]:** `agent_runtime_v2/harness.py:23-30`. `RAFII_AGENT_HARNESS=1` swaps in a scripted Manager and fake providers. It is **refused when `VERCEL=1`**. The Agents SDK `agents.testing.ScriptedModel` is used in PG tests (`postgres_agent_runtime.py:30`).

## 5. Test infrastructure

### 5.1 Python unit tests [V]

- **Interpreter:** `.python-version` = `3.12`. CI uses `actions/setup-python` with `python-version-file`.
- **Dependencies:** `requirements-dev.txt` = `-r requirements.txt` + `pip-audit==2.10.1, httpx==0.28.1, fastapi==0.141.1, detect-secrets==1.5.0, jsonschema==4.26.0`. `requirements.txt` pins `openai-agents==0.22.3`, `openai==3.19.2`, `psycopg[binary]==3.3.5`, `Pillow==12.3.0`, `starlette==1.7.0`, `uvicorn==0.54.0`, `websockets==16.1.1`, `cryptography==50.0.1`, `pypdf==6.19.0`, `jsonschema`.
- **Runner:** `python -m unittest discover -s tests -p 'test_*.py'` with `PYTHONPATH=src:tests` (`consumer-ready.yml:50`). There are 228 `tests/test_*.py` files plus 50 in `tests/control/`.
  - `tests/control` is discovered because it has `__init__.py`.
  - `tests/` has no `__init__.py`, and neither does `tests/phase3/`, so phase3 is not discovered.
  - **A new directory such as `tests/agent_ui_acceptance/` is discovered only if it has `__init__.py`** (Python 3.12 unittest does not discover namespace packages).
- **Wrapper:** `scripts/consumer_ready_check.py <name> <cmd…>` (40 lines):
  - records `docs/consumer-ready/evidence/<name>.{json,log}`, `-source.json` fingerprints, HEAD SHA and exit code;
  - reports `INVALIDATED` if the source changed during the run;
  - **removes env keys containing `API_KEY`, `DATABASE_URL`, `SUPABASE`, `STRIPE_SECRET`, `OAUTH_CLIENT_SECRET` or `SENTRY_AUTH_TOKEN`.** Live-model tests therefore cannot run under it.

### 5.2 PostgreSQL scenarios: `tests/phase2/postgres_*.py` (≈100 standalone scripts, not unittest) [V]

- **Provisioning:** no docker, no CI service container, no local Supabase. Each script starts a **disposable local cluster** with `initdb -A trust --no-locale -E UTF8` then `pg_ctl start -h 127.0.0.1 -p <port>`. The binaries come from `POSTRIFF_PG_BIN` (default `/opt/homebrew/opt/postgresql@17/bin`; CI uses `/usr/lib/postgresql/17/bin`).
- After start it loads `tests/phase2/rls.sql` via `psql`. That file creates the `anon`, `authenticated` and `service_role` (bypassrls) roles, an `auth` schema with `auth.uid()` reading `request.jwt.claim.sub`, and storage stubs. It then applies a **subset** of migrations (001, 002, 004–012, 018, 019, 023–025, 030–039, 041–046, 093, then 094–096 at the end), seeds users `…0001` and `…0002`, runs two-tenant RLS assertions, and tombstones user `…0002`.
  - Tests that need later migrations apply them inline, e.g. `postgres_agent_runtime.py:203` (058) and `postgres_final_idempotency.py:43` (020).
- **Runners:**
  - `scripts/postriff_pg_suite.py [stem…]` (49 lines): one new cluster per script on port **55438**. It auto-includes every `tests/phase2/postgres_*.py` except `postgres_repository.py` and `postgres_safety.py`. It passes `POSTRIFF_TEST_DSN`, `LC_ALL=C` and `POSTRIFF_RESEARCH=0`, and exits nonzero if any script fails. This is used by CI (`consumer-ready.yml:52`) and JCB (`library-cloud-validation.sh:16`).
  - `scripts/agent_runtime_pg.py [scripts] [--port 55621]` (51 lines): the same isolation on a separate port; scripts read `POSTRIFF_PG_PORT`.
  - `scripts/postriff_disposable_postgres.py` (54 lines): one cluster for several scripts.
- **Script conventions:**
  - top-level code builds `HostedWorkspaceService(connection, verify, …)` with a fake `verify(token) → uuid`, plus `verify.session_id` and `verify.auth_time`;
  - `denied(call, status, message)` helpers;
  - `consumer_fixtures.approve_budgets(connection, wid)` for paid paths;
  - the role matrix is built with `service.invite(...)`, `accept_invitation(...)` and `update_member(...)` (`postgres_isolation.py:100-134`).
  - **New scripts should read `POSTRIFF_PG_PORT` (default 55438)** so they work under both runners.
- **Env needed:** `POSTRIFF_PG_BIN`, `POSTRIFF_PG_PORT` (optional), `PYTHONPATH=src:tests`, `POSTRIFF_RESEARCH=0`, `LC_ALL=C`. No hosted credentials.

### 5.3 Web tests [V]

- **Runner:** `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` (`consumer-ready.yml:55`). The shell glob means only **top-level** `web/tests/*.test.{cjs,mjs}` files run: 85 `.cjs` and 16 `.mjs` today.
  - A file like `web/tests/agent-ui-renderer.test.cjs` is auto-included.
  - **`web/tests/agent-ui-journeys/` and `web/tests/agent-ui-e2e/` subdirectories are not** included; they need explicit steps.
- **Pattern:** `require('typescript')`, `ts.transpileModule` and `node:vm` load TS modules in isolation (e.g. `voice-session-lifecycle.test.cjs`). A few tests use `react-dom/server`. There is no jsdom or happy-dom.
  - [I] ESM-only `@openuidev/*` packages may need dynamic `import()` from `.mjs` tests. C must check this.
- **Web scripts** (`web/package.json`): `lint` = `oxlint src`, `typecheck` = `tsc --noEmit`, `build` = `next build`, `test:library` and `ci:library` (JCB, §9).
- **Pins:** Node `24.15.0` (`.node-version`), npm `11.12.1`, `playwright 1.62.1`, `axe-core 4.13.0`, `next 16.3.8`, `react 19.2.4`, `recharts 3.8.0`, `zod ^4.3.6`, `@tanstack/react-query ^5.95.2`. **No `@openuidev/*` is installed yet.** `web/.npmrc` = `legacy-peer-deps=true`.

### 5.4 Browser harness [V]

- `scripts/postriff_dev_hosted.py --port 4438 --pg-port 55479 [--phone-fixture|--founder-fixture|…]`: the real hosted code on a disposable PG with `rls.sql`. Identity is `Bearer dev:<uuid>` (lines 51-56) and providers are synthetic.
- `scripts/consumer_ready_web.py --prepare npm ci` then `npm run build|start` builds an isolated copy under `.codex/consumer-ready/web`.
- `scripts/consumer_ready_browser.py [--library|--founder|--performance|--history-import]` owns the API/web/DB processes.
- Browser scenes are `node web/tests/*-browser.cjs` with Playwright Chromium and WebKit.
- Voice and agent scenes use a second harness with `RAFII_AGENT_HARNESS=1` and `next dev` (`rafii-browser.yml:85-100`).

### 5.5 Live (paid) checks [V]

- `scripts/agent_runtime_live.py`: refuses to run unless `RAFII_LIVE_CHECKS=1` and the needed credential (`OPENAI_API_KEY`) are present. It has a `--budget-usd` cap; reaching the cap is a FAIL. It never prints keys.
- Also `scripts/live_model_qualification.py` and `scripts/agent_runtime_matrix.py`.
- **No GitHub workflow and no JCB config carries a model credential.** The only workflow secrets are `RAFII_ENGINEERING_INGEST_DSN` and `RAFII_WATCHDOG_DSN`, and JCB `envAllowlist` is `[]`. G03's 30 real generations cannot run in CI as configured (decision D7).

## 6. GitHub Actions (`.github/workflows/`) [V]

| Workflow (name) / job | Trigger | Main content | Python/PG/browser |
|---|---|---|---|
| `consumer-ready.yml` "Rafii local release gates" / `local-gates` | **every** `pull_request`, plus `workflow_dispatch` | Python unittest discover; `postriff_pg_suite.py` (all PG scripts); node web tests and `trend-contract`; typecheck/lint/isolated build; copy audit; Vercel Python function archive; secret scan; pip-audit and npm audit; Playwright `session-cache-browser`, `consumer_ready_browser.py` (plain, `--performance`, `--history-import`) | all three. **Timeout 40 min; PR #133 took 25m05s** |
| `rafii-browser.yml` "Rafii browser scenes" / `scenes` | PR paths `web/**`, `src/postriff_phase2/**`, `scripts/postriff_dev_hosted.py` | Production build, dev harness on 4438/55479, Chromium and WebKit scenes, site-agent, live-agent (harness on 4440/55480 with `next dev` on 4441), phone (fake), guide | browser+PG; 60 min |
| `founder-browser.yml` "Founder admin browser" / `founder` | PR paths web, rafii_control, postriff_phase2, migrations, `rls.sql`, etc. | Founder passkey sign-in and founder scenes | browser+PG; 45 min |
| `library-release.yml` / `library` (and `dependency-lock` only on dispatch) | PR to `consumer-saas`, paths `src/postriff_phase2/**`, `web/**`, `tests/**`, migrations, `scripts/*library*` | `npm --prefix web run ci:library` | Python+PG+browser; 40 min |
| `growth-studio.yml` / `growth-studio` | every PR | Growth Studio browser+PG | 15 min |
| `growth-metrics.yml` / `native-learning-browser` | PR paths (postriff_phase2, growth tests) | PG suite subset plus trend browsers | 30 min |
| `rafii-control.yml` / `local-foundation` | PR paths rafii_control, control-web, migrations 049–079, `rls.sql`, etc. | `scripts/rafii_control_pg.py`, control-web build | 15 min |
| `preview-window-validation.yml` / `preview` | PR paths preview-window, `conversation-view.tsx` | node test and browser | 12 min |
| `founder-engineering-evidence.yml` / `record` | push to `consumer-saas`, `workflow_run` of 4 workflows, cron every 15 min | `python -m rafii_control.ci_evidence` (secret DSN) | — |
| `founder-watchdog.yml` / `heartbeat` | cron every 10 min | heartbeat (secret DSN) | — |

- **No workflow sets `OPENUI_TELEMETRY_DISABLED`.** All of them set `NEXT_TELEMETRY_DISABLED=1`.
- **Required checks as the founder evidence collector defines them** (`src/rafii_control/ci_evidence.py:79-102 REQUIRED_CHECKS`):
  - `consumer-ready/local-gates` (always);
  - `rafii-control/local-foundation`, `rafii-browser/scenes` and `founder-browser/founder` (path-conditional);
  - `vercel/production`.
  - **`tests/control/test_ci_evidence.py` fails if a workflow's `paths` filter drifts from the copy in `REQUIRED_CHECKS`.** Editing those three path filters therefore requires editing `ci_evidence.py`.
  - A brand-new workflow is not "required" in founder evidence unless it is added there.
- **PR #133 actual checks [V]:** Vercel Preview Comments, founder, growth-studio, library, local-gates, scenes, dependency-lock (skipped), Vercel. All passed.

## 7. Branch protection and merge path [V]

- `gh api repos/dev-james0723/PostRiff/branches/consumer-saas/protection` returns **404 "Branch not protected"**. Rulesets are `[]` and branch rules are `[]`.
- Repo settings: **`visibility: public`**, `allow_auto_merge: true`, merge commit, squash and rebase all allowed, `delete_branch_on_merge: false`.
- Recent merges (#118–#133) were all **manual merges by `dev-james0723`** using merge commits ("Merge pull request #133…"), with **no auto-merge** set.
- Vercel production builds from `consumer-saas` (`ci_evidence.py` `vercel/production`). The Vercel project seen in checks is `postriff-phase2-private`. **Merging is the production deploy.**
- Consequences:
  - [V] GitHub does not block merging a red PR.
  - [I] `gh pr merge --auto` without required checks can merge immediately.
  - The release owner must check every check run on the exact head SHA before merging.
  - **The repository is public**, so evidence, fixtures and docs committed here are public: no real user data, tokens or private URLs in evidence.

## 8. Active PRs relevant to CI [V]

- **#129** (draft) `codex/jcb-cloud-validation-20261005`, "Add manual JCB validation and isolated browser acceptance on Depot". **Not merged.** It contains `scripts/jcb-e2e-harness.sh` (commit `dee1bcb6`, 61 lines).
  - Its config: tasks `{test: test:jcb, ci: ci:jcb, e2e: e2e:jcb}`, `runner.e2e = depot-ubuntu-24.04-8`.
  - Its `web/package.json` scripts: `test:jcb` = cloud-python-bootstrap plus all node web tests; `ci:jcb` = lint, typecheck, test:jcb, build; `e2e:jcb` = cloud-python-bootstrap plus `jcb-e2e-harness.sh`.
  - The harness installs PG17, runs `consumer_ready_web.py` prepare/build, links the Next cache, installs Playwright Chromium, then runs `consumer_ready_browser.py`.
  - **It conflicts with production's library task mapping.**
- **#134** (draft, Library document previews) and **#131** (draft, social connection recovery) both target `consumer-saas`. [I] They are potential conflicts on `web/**` and the library code.

## 9. JCB / Depot

### 9.1 Production config: `.james-cloud-build.json` at 3da806f0 [V]

- `packageRoot: web`, `provider: depot`, `npm` 11.12.1, Node 24.15.0, `installCommand: npm ci`.
- **tasks `{lint: lint, typecheck: typecheck, build: build, test: test:library, ci: ci:library}`. There is no `e2e` task.**
- runner `{validation: depot-ubuntu-24.04-8, build: depot-ubuntu-24.04-16}`, `envAllowlist: []`, `localFallback: false`, `transportMode: remote_patch`, `baseRef: refs/remotes/origin/consumer-saas`, `orgId: jf34f85hr0`, `cacheScope: e408bbcd8242`.
- `inputExcludes: [docs/**, desktop/**, vendor/**, studio/**, motion/**, downloads/**, artifacts/**, *.zip]`. **`docs/**` is not uploaded**, so cloud tests must not read the engineering package or `acceptance.json` from `docs/`.
- `environment`: `NEXT_PUBLIC_APP_URL`, empty Supabase public vars, `NEXT_PUBLIC_SENTRY_DISABLED=1`, `POSTRIFF_API_ORIGIN=http://127.0.0.1:4438`, `POSTRIFF_DEV_SSR=1`, `LC_ALL=C`.

### 9.2 Task-to-script chain [V]

- `.depot/workflows/james-cloud-build.yml` (362 lines, `workflow_dispatch` only) has one job per task: `lint`, `typecheck`, `build`, `test`, `ci`.
- Each job checks out the code, verifies `.depot/jcb-source.json`, sets up Node, matches npm 11.12.1, mounts the Depot cache (`depot/cache-mount@v1`), runs `npm ci` in `web/`, and then runs **`npm run <script>`**.
  - `test`: `npm run test:library` = `bash ../scripts/cloud-python-bootstrap.sh bash ../scripts/library-cloud-validation.sh`.
    - `cloud-python-bootstrap.sh` (76 lines) requires `CI=true` and Linux, so it **refuses the Mac**. It checks `.python-version`, makes a mktemp venv, runs `pip install -r requirements-dev.txt` (`--isolated`, pypi), exports `PATH` and `TREND_VISUAL_TEST_PYTHON`, then execs its arguments.
    - `library-cloud-validation.sh` (16 lines) runs `python -m unittest test_library_extract test_hosted_storage_library test_hosted_storage_video`, then apt-installs `postgresql` (Ubuntu default, [I] PG16, not 17), then `python scripts/postriff_pg_suite.py postgres_library_lifecycle`.
  - `ci`: `npm run ci:library` = bootstrap plus `library-release-validation.sh` (32 lines). That runs npm audit evidence, `library-cloud-validation.sh`, typecheck, lint, build, `consumer_ready_secrets.py`, the library samples and ffmpeg, Playwright Chromium and WebKit, `consumer_ready_browser.py --library`, and `npm audit --audit-level=high`.
- **JCB `test` and `ci` today run only the Library subset.** They are not the full release gates; those live in GitHub `consumer-ready.yml`.

### 9.3 How `jcb` works (`/Users/ouxianxing/Documents/James-Cloud-Build/scripts/jcb.py`, 669 lines; launcher `bin/jcb` → `~/.local/bin/jcb`) [V]

- `TASKS = ('lint','typecheck','test','build','e2e','ci','docker-build')` (line 19) is a **fixed set**. Custom task names are not possible; you can only remap one of these seven to a `web/package.json` script.
- `detect()` (51-157) validates:
  - each task maps to an *existing* package.json script;
  - `taskArgs` are string arrays;
  - env literals use `[A-Z_]` names;
  - `envAllowlist` contains secret names only;
  - runner names;
  - the frozen install command.
  - It also **recomputes `lockfileSha256` from the actual lockfile** at runtime.
- `workflow(cfg)` (168-250) renders the YAML deterministically. The YAML embeds:
  - each task's `npm run <script> [-- taskArgs]`;
  - the env literals and `${{ secrets.X }}` for the allowlist;
  - runner sizes;
  - cache names `jcb-<cacheScope>-<runtimeHash>-<lockfileSha256[:8]>-…`.
- `_execute()` (545-606) and `doctor` (`main`, ~653): **refuse if the YAML in the snapshot ≠ `workflow(cfg)`** ("JCB workflow differs from reviewed config; run setup first").
- `jcb setup [--force]` (`main`, ~641-648) **rewrites both** `.depot/workflows/james-cloud-build.yml` and `.james-cloud-build.json`.
- Submission: `depot ci run --workflow .depot/workflows/james-cloud-build.yml --job <task> --org <org> --follow`, run from a sanitized snapshot (`scripts/snapshot.py`). The snapshot:
  - takes tracked files plus untracked non-ignored files, minus `inputExcludes`;
  - forbids `.env*`, `.ssh`, `.agents`, `.claude`, `.codex`, `.token-pilot`, `.vercel`, `node_modules`, `.next`, keys and pems;
  - sends a patch against `baseRef`.
- Result: a receipt under `James-Cloud-Build/receipts/`, a run URL of the form `https://depot.dev/orgs/<org>/workflows/<runId>`, and the remote exit code. Use `jcb status RUN_ID --org ORG` to poll.
- `localFallback` requires `JCB_ALLOW_LOCAL=1` *and* `localFallback: true`. It is false here.
- **Answer to "can a new task script be added via `.james-cloud-build.json` without regenerating the YAML?" No [V].**
  - Changing a task mapping, `taskArgs`, an env literal, `envAllowlist`, a runner, or **the lockfile** (its hash is in the cache names) all change `workflow(cfg)`. JCB then refuses until `jcb setup --force` regenerates the YAML.
  - What does *not* need regeneration: changing the *body* of an already-mapped npm script, or of the shell script it calls (e.g. `scripts/library-cloud-validation.sh`).
- Health [V]: today's receipts show JCB and Depot working, e.g. a PostRiff `build` from the `rafii-youtube-creator` worktree passed at 2026-10-08T16:01Z (run `mc4zwhhx23`).

### 9.4 Staleness at the baseline [V]

- At committed `3da806f0`, the YAML cache names use lockfile prefix **`07c94c20`**, but `web/package-lock.json` sha256 starts with **`c347e642`**. Both were last touched by `8377ebbb`.
- So **`jcb doctor` and every `jcb <task>` would refuse on the committed baseline.**
- Someone has since run `jcb setup --force` in this worktree, which is the uncommitted diff noted at the top. A must commit that regeneration, or redo it after the OpenUI lockfile change, which changes the hash again.

## 10. Wiring plan for the new agent-ui suites ([I] recommendations, built only on the verified mechanisms above)

1. **Python unit tests** (`tests/test_agent_ui_*.py`, from B, C, D and F): auto-discovered by `consumer-ready.yml:50`.
   - G's `tests/agent_ui_acceptance/` needs `__init__.py` and `test_*.py` names.
   - No secrets are allowed; they are stripped anyway.
2. **PG scenarios** (`tests/phase2/postgres_agent_ui_actions.py`, `postgres_agent_ui_store.py`): auto-run by `postriff_pg_suite.py` in local-gates.
   - Use `POSTRIFF_PG_PORT` and apply A's new migration inline (like the 058 example) or add it to `rls.sql`.
   - Adding it to `rls.sql` triggers founder-browser and rafii-control.
   - Add `authenticated`-role negative assertions for the new tables (service_only).
   - **Watch the local-gates budget: 25 of 40 minutes are used.** Keep it to 2–3 scripts, or put the agent-ui PG and browser work in its own workflow.
3. **Web node tests** (`web/tests/agent-ui-*.test.cjs` at top level): auto-run by the `ci-web` step.
   - Journey and e2e subdirectories need explicit `node --test web/tests/agent-ui-journeys/*.test.cjs` lines, or a single wrapper.
4. **One runner script:** G's `scripts/agent_ui_validation.sh {unit|database|browser|live|release}`.
   - `unit` → `python -m unittest` (explicit modules) plus `node --test web/tests/agent-ui-*.test.cjs`.
   - `database` → `python scripts/postriff_pg_suite.py postgres_agent_ui_actions postgres_agent_ui_store postgres_isolation postgres_site_agent …`.
   - `browser` → `consumer_ready_web.py` build, `postriff_dev_hosted.py` with `RAFII_AGENT_HARNESS=1` where needed, then `node web/tests/agent-ui-e2e/*.cjs`.
   - `live` → the `RAFII_LIVE_CHECKS=1` pattern with a budget cap. It must not run under `consumer_ready_check.py`.
   - `release` → verify SHA and evidence freshness.
   - Guard every mode with `CI=true` and Linux, as `cloud-python-bootstrap.sh` does.
5. **GitHub:** add `.github/workflows/agent-ui.yml` (PR to `consumer-saas`; paths `web/**`, `src/postriff_phase2/**`, `migrations/postriff/**`, `tests/**`, `scripts/agent_ui_*`), modeled on `rafii-browser.yml`.
   - Add `OPENUI_TELEMETRY_DISABLED: '1'` to the env of **every** workflow that runs `npm ci` (8 workflows) **before** the OpenUI dependency lands.
   - Optionally add the new check to `ci_evidence.REQUIRED_CHECKS`. Its path copy is pinned by `tests/control/test_ci_evidence.py`.
6. **JCB:** in A's single dependency/lockfile commit:
   - add npm scripts `test:release` (library tests plus agent-ui unit/PG), `ci:release` and `e2e:agent-ui` (cherry-pick `scripts/jcb-e2e-harness.sh` from #129 or write a G variant);
   - set tasks `{test: test:release, ci: ci:release, e2e: e2e:agent-ui}` and env `OPENUI_TELEMETRY_DISABLED=1`;
   - then run `jcb setup --force` and `jcb doctor`, and commit both files.
   - Library CI keeps `test:library` and `ci:library` unchanged, because the GitHub `library-release.yml` calls `ci:library` directly.
7. **Vercel:** the production and preview builds run `npm install` too. [I] Set `OPENUI_TELEMETRY_DISABLED=1` in the Vercel project env (an A action) before merging the dependency.

## 11. Risks and gaps

- **R1 [V]:** No branch protection, a public repo, and merge = production deploy. Nothing on the server enforces the gates; A must hand-verify every check on the exact head SHA.
- **R2 [V]:** The committed JCB YAML is stale (`07c94c20` vs `c347e642`). It is regenerated but uncommitted in this worktree, and the OpenUI lockfile change will invalidate it again.
- **R3 [V]:** JCB `test`/`ci` cover only the Library, and there is no `e2e` task in production. #129, which adds e2e, is an unmerged draft that conflicts on JSON and package.json.
- **R4 [V]:** `pr_agent_runs.artifact` and `pr_agent_events` are readable by every workspace member, including viewers, through PostgREST. UI source must go in a service_only table.
- **R5 [V]:** Consumer API isolation is application-layer, on a privileged DB login. Every new SQL path must carry the membership JOIN, `transaction()` or `principal_repository`, plus explicit `workspace_id` predicates. RLS will not catch a missing predicate.
- **R6 [V]:** `classify()` defaults unknown actions to `edit`. UI actions need an explicit allowlist.
- **R7 [V]:** `verify_session` makes an uncached Supabase HTTPS call on every `transaction()`. That hurts query latency (G17) and long streams risk token expiry. Use `principal_repository` after the first verification.
- **R8 [V]:** The vercel.json rewrites are pinned by an equality check in `check_postriff_hosted_preflight.py` and its test. An `/api` Node route needs coordinated edits.
- **R9 [V]:** The WSGI `_json` helper buffers whole responses. Streaming needs a separate iterator path (B, G04 still unproven).
- **R10 [V]:** No model credential exists in GitHub or JCB, so the G03 30-sample live run and G17 real timings need a credentialed runner. JCB `envAllowlist` needs a Depot secret, or a bounded Mac run (network-bound).
- **R11 [V]:** The browser `switchTo` does not abort in-flight requests. New stream and query hooks must do it.
- **R12 [I]:** JCB's Library PG runs on Ubuntu's default PostgreSQL (probably 16), while GitHub uses 17. A version difference is possible.
- **R13 [V]:** local-gates already takes 25 of its 40-minute timeout. Adding per-script PG clusters could time it out.
- **R14 [V]:** There is no DB-backed feature-flag service. An env kill switch takes effect only through a redeploy.

## 12. Decisions A must freeze (recommendations)

1. **D1, the UI action authority table:** a static allowlist in `ui_actions.py` mapping `actionId` to `(domain command, permissions class, step_up, effect class)`. Unknown IDs are refused. Never call `classify()` on generated names.
2. **D2, principal plumbing:**
   - Authenticate once per HTTP request with `repository.transaction`.
   - Long-lived producers, streams and replays use the `automation_runs.principal_repository` capability, which re-checks membership on every transaction.
   - Never hold the `FOR UPDATE OF w` workspace lock across a model call.
3. **D3, Node parser seam:** a Next route handler outside `/api` (e.g. `web/src/app/agent-ui/validate/route.ts`), authenticated by a server-only HMAC secret plus run binding, with no vercel.json change. The fallback is an explicit `/api/agent-ui/validate` → `postriff_web` rewrite placed before `/api/(.*)`, together with updates to the preflight check and its test.
4. **D4, storage privacy:** new UI tables use the service_only RLS pattern (031/093). No raw source goes into `pr_agent_events`; it keeps SAFE_EVENTS pointers only. Migration number 097+ is allocated by A, applied inline in the PG tests and appended to `rls.sql` with `authenticated` negatives.
5. **D5, query admission:** reuse `hosted.throttle(cur, scope, 60, 60)` with scope `ui-query:<principal>:<artifact>`, on the existing `pr_auth_throttle` table.
6. **D6, CI topology:**
   - Unit and node tests go into the existing local-gates by naming convention.
   - Agent-ui PG, browser and journey work goes in a new `.github/workflows/agent-ui.yml` that calls `scripts/agent_ui_validation.sh`.
   - JCB gets `test:release`, `ci:release` and `e2e:agent-ui`, regenerated once with `jcb setup --force` in the lockfile commit.
   - Add `OPENUI_TELEMETRY_DISABLED=1` to all `npm ci` workflows, the JCB env and the Vercel env before the install.
7. **D7, live evidence runner:** run G03 and G17 live samples through a separate budget-capped script, not `consumer_ready_check.py`. Use the existing production model credential via an approved secret store (adding a Depot or GitHub secret is a new credential placement, so confirm with James), or a bounded network-only Mac run. Do not substitute fixtures.
8. **D8, merge gate:** with no branch protection, A merges manually (merge commit, matching history) only after all checks pass on the exact head SHA, including the new agent-ui workflow. Don't rely on `--auto`.
9. **D9, kill switch:** env flags `RAFII_GENUI_ENABLED`, `RAFII_GENUI_ACTIONS_ENABLED`, `RAFII_GENUI_EDITS_ENABLED` and `RAFII_GENUI_FOUNDER_ENABLED`, read per request (like `ai_paused()`), with Vercel instant rollback as the faster path. Document that an env flip needs a redeploy. An optional DB flag can come later only if G23 needs a sub-minute disable.
10. **D10, founder UI routes:** add a `rafii_control` slice module that calls `register_route('GET'|'POST', r'/agent/ui/...', 'copilot.use', …, budget='founder.agent.turn')`, listed in `slices.SLICES`. Never accept a client founder flag.
