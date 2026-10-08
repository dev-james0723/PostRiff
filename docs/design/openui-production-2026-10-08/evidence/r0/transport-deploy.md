# R0 map: transport and deploy (lanes A/B)

**Reader:** read-only R0 reader for role A. **Worktree:** `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`. HEAD is `3da806f0` (`consumer-saas`). Nothing outside this file was changed. No build, install or test was run.
**Date:** 2026-10-08.
**Labels used below:**
- **[CODE]** a fact read from the repository at `3da806f0`.
- **[VERCEL-SRC]** read from the upstream Vercel runtime source (`vercel/vercel` main, fetched 2026-10-08). The runtime version actually deployed was not pinned or checked.
- **[DOCS]** from official vercel.com documentation.
- **[LIVE]** a read-only API or HTTP probe made today.
- **[INFER]** my inference. It needs proof on a deployment before anyone relies on it.

---

## 1. Deployment topology (vercel.json, .vercelignore)

### 1.1 `vercel.json` [CODE]
- **Services (`vercel.json:3-30`):**
  - `postriff_web`: `root: "web/"`, `framework: "nextjs"`.
  - `postriff_api`: `root: "."`, `runtime: "python"`, `entrypoint: "api.index:app"`. `functions["api/index.py"]` has `maxDuration: 300`. Its `excludeFiles` drops `.venv/**`, `.phase3-build-venv/**`, `.env*`, `broker.key`, `*.command`, `desktop/**`, `vendor/**`, `src/james_au_social/**`, `**/__pycache__/**`, `web/**`, `tests/**`, `docs/**` and `studio/**`.
  - `rafii_phone_media`: `root: "."`, `runtime: "python"`, `entrypoint: "api.phone:app"`, `maxDuration: 660`, with the same `excludeFiles`.
- **Rewrites, in order (`vercel.json:31-56`):**
  1. `/api/phone/dial/media/(.*)` → `rafii_phone_media`
  2. `/api/phone/media/(.*)` → `rafii_phone_media`
  3. `/api/(.*)` → `postriff_api`
  4. `/(.*)` → `postriff_web`
- **Headers (`vercel.json:57-100`):** every path `/(.*)` gets `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and `Permissions-Policy: camera=(), microphone=(self), geolocation=()`. Only `/sw.js` gets a CSP (`default-src 'self'; script-src 'self'`).
  - **There is no application-wide Content-Security-Policy.** No CSP blocks `eval` in the rendered app, and none restricts `connect-src`. The no-eval rule in the OpenUI spec is therefore enforced by code review only, not by the browser.
- **Crons (`vercel.json:101-106`):** `/api/cron/worker`, every minute.

### 1.2 What Vercel guarantees for this layout [DOCS: vercel.com/docs/services/routing]
- Top-level rewrites are evaluated in order, and the first match wins.
- A service receives the original path. For example, `/api/x` arrives as `/api/x`, not as `/x`.
- Routing into a service is final: there is no fallback to later rewrites.
- The phone service confirms the path behaviour in practice: its Starlette app matches the full path `/api/phone/media/{call_id}` (`src/postriff_phase2/phone/asgi.py:46-47`).

### 1.3 Route-order contract checks that must change together with `vercel.json` [CODE]
- **`scripts/check_postriff_hosted_preflight.py:62-77`, check `vercel-services-routing`.** It requires `routes ==` exactly the four rewrites above, plus the exact service runtime and entrypoint values. **Any added rewrite or service fails preflight** unless this list is updated in the same commit.
- **`tests/test_postriff_hosted_deployment.py:100-116`.** It mutates `vercel.json` (swaps rewrites, shortens `maxDuration`, changes `excludeFiles`) and expects preflight to fail. It must be extended for any new route.
- **`scripts/consumer_ready_artifact.cjs:28-43`.** It builds only `services.postriff_api` with `@vercel/python` and records `rewrites`. A new Python service would need its own archive step.
- **`.github/workflows/consumer-ready.yml`.** The "Actual isolated Python function archive" step pins `vercel@59.23.2`.

### 1.4 `.vercelignore` (upload boundary) [CODE]
- Excluded: `/docs/`, `/migrations/`, `/scripts/`, `/tests/`, `/templates/`, `/vendor/`, `web/tests/`, `web/plans/`, `/*.md`, `/*.zip`, `/.github/`, `/control-web/`, `/api/control.py`, `/vercel.control.json` and others (`.vercelignore:1-73`).
- Consequences:
  - Generated OpenUI assets the Python side needs must live under `src/...`, as `02-CONTRACTS.md` §1 already specifies. They cannot sit under `web/`, because `web/**` is excluded from the Python bundle.
  - Generated assets cannot sit under `/scripts/`, which is excluded from upload.
- `scripts/check_postriff_hosted_preflight.py:84-87` verifies these rules.

### 1.5 Live project facts [LIVE: Vercel API + HTTP probe, read-only]
- **Project:** `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`), team `team_PgXY5VdAYKcsv0RLoDPHscNq`. It is the only team visible to the connector. `nodeVersion: 24.x`.
- **Current production deployment:** `dpl_23gCJrH5BWZt5gQSV4iqNt2sV5Vt`, READY, `githubCommitSha 3da806f0e31a01396a3bd4a9e27f66f9b21ce816`. It matches the baseline.
- **Prior rollback candidates:**
  - `dpl_FftzybN56AvCf93cx7eEYjtBjTzw` at `07b3295e`.
  - `dpl_6XUpCXLgiFHp8vkV9kZv1VPUxdzs` at `8377ebbb`.
- **Project domains:** only `postriff-phase2-private.vercel.app` and `postriff-phase2-private-staging.vercel.app` (git branch `staging`). The second project, `rafii-consumer-staging`, has only `rafii-consumer-staging.vercel.app`.
- **`rafii.io` is not attached to either project, and the DNS name `rafii.io` does not resolve from this Mac** (`curl: Could not resolve host`).
  - This is a hard external prerequisite for G24 ("verified canonical rafii.io").
  - A must not claim rafii.io as the verified origin. Buying a domain or changing DNS needs James's explicit approval.
- **Deployment Protection:** `ssoProtection: {enabled: true, deploymentType: "all_except_custom_domains"}`.
  - Probe: `GET https://postriff-phase2-private.vercel.app/api/health` → **200**.
  - Probe: the per-deployment URL `postriff-phase2-private-nsmoxqq5j-…vercel.app/api/health` → **302** (Vercel login).
  - So preview and per-deployment URLs require Vercel Authentication. Deployed G04 streaming tests on a preview need existing approved access: the `_vercel_jwt` cookie, or `x-vercel-protection-bypass` with the automation-bypass secret.

---

## 2. Python entrypoints

### 2.1 `api/index.py` (WSGI) [CODE]
- `api/index.py:1-11` inserts `src/` into `sys.path` and re-exports `postriff_phase2.hosted_app.app`.
- That object is `HostedApplication()`, a module-level instance (`hosted_app.py:1042`). It is lazy: `_runtime()` (`hosted_app.py:264-273`) builds `runtime_from_environment()` on first use.

### 2.2 `api/phone.py` and `phone/asgi.py`: the existing ASGI service precedent [CODE]
- `api/phone.py:1-13` exports `create_lazy_app()`.
- `phone/asgi.py:17-47`, `create_lazy_app(*, values=None, application_factory=None)`:
  - Starlette, with only `WebSocketRoute('/api/phone/media/{call_id}')` and `WebSocketRoute('/api/phone/dial/media/{call_id}')`.
  - Import and lifespan need no credentials.
  - The kill switch `RAFII_PHONE_ENABLED` is rechecked on every upgrade through `PhoneConfig(os.environ).enabled(...)`.
  - The heavy runtime is built lazily under an `asyncio.Lock` via `asyncio.to_thread(factory)`. Failure closes with code 1008 and `report_failure(...)` (no error text).
- `phone/asgi.py:50-271`, `create_app(hosted=None, phone=None, live_connect=None, *, media_only=False, code_transcribe=None)`:
  - Builds `HostedApplication(hosted, worker, auth, os.environ.get('CRON_SECRET'))` from `runtime_from_environment()`.
  - When `media_only=False` (local uvicorn only), it mounts the WSGI app with `Mount('/', app=WSGIMiddleware(wsgi))`.
  - Synchronous DB and service work runs through `asyncio.to_thread`.
  - Provider clients use `AsyncOpenAI(..., max_retries=0)`, i.e. no hidden SDK retries. This is the precedent the presenter should follow.
- **Phone receipt** (`docs/design/rafii-live-agent/RAFII_PHONE_MODE_IMPLEMENTATION_RECEIPT_2026-09-26.md:10,51`): the media service was added because a long-lived bidirectional WebSocket was needed. Starlette's `WSGIMiddleware` emits a deprecation notice, which was accepted.
- **Lesson:** a separate ASGI service costs a new function bundle, a separate cold start, new exact rewrites ahead of `/api/(.*)`, preflight and test updates, and a duplicate runtime init.

### 2.3 Python runtime pins [CODE]
- `.python-version` = `3.12`. `.node-version` = `24.15.0`.
- `requirements.txt`: `openai-agents==0.22.3`, `openai==3.19.2`, `starlette==1.7.0`, `uvicorn==0.54.0`, `websockets==16.1.1`, `psycopg[binary]==3.3.5`, `jsonschema==4.26.0`, `Pillow==12.3.0`, `pypdf==6.19.0`, `cryptography==50.0.1`.
- Starlette `StreamingResponse` is available if an ASGI fallback is ever needed. No new dependency is required for either option.

---

## 3. `hosted_app.py` request pipeline and `/api/workspaces/{id}/agent/*`

### 3.1 WSGI callable [CODE]
`HostedApplication.__call__(environ, start_response)` (`hosted_app.py:451-482`):
- Mints `request_id = uuid4().hex` into `environ['postriff.request_id']`.
- Wraps `start_response` so that every response carries `X-Request-ID` and the status is captured.
- `try: return self._handle(...)`, then `finally:` it logs JSON `request.completed` (requestId, method, status, durationMs, coarse route; never path, body or identity) and calls `request_metrics.observe(...)`.
- **Streaming caveat [INFER, from code shape].** The `finally` runs when `_handle` returns the iterable, not when a generator finishes. Duration and status of a streamed response would be logged at hand-off, and exceptions raised inside the generator bypass both `except` blocks (`hosted_app.py:1015-1039`). A streaming adapter must:
  - catch everything inside the generator and turn it into a terminal `ui.failed` or `ui.interrupted` frame;
  - log its own content-free `request.stream_closed` record from `close()`.

### 3.2 `_handle` order of guards [CODE]
`hosted_app.py:484-1039`:
1. `/api/control/v2/*` goes to the founder Control WSGI app, before any consumer guard (`:489-497`).
2. A `Bearer prt_…` API token is checked first through `api_tokens.authorize(...)` (`:498-501`). `api_tokens.route_scope` (`api_tokens.py:18-39`) is an explicit allowlist that contains **no** `agent` route, so API tokens get 403 `token_scope_denied` on every `/agent/ui/*` path before the handler runs.
3. Public, cron and webhook routes come next (`:502-700`). The cron route checks `CRON_SECRET` with `hmac.compare_digest(supplied, "Bearer " + expected)` and requires at least 16 characters (`:611-616`).
4. `if not api_bearer: self._origin(environ, mutation)` (`:701-702`), then `service = self._runtime()` and `token = self._token(environ)` (`:703-704`).
5. `/api/workspaces/{w}/agent/...` is dispatched at `:781-784` to `agent_runtime_v2.http.handle(self, environ, start_response, service, token, method, parts)`.

### 3.3 Helpers to reuse [CODE]
- `_json(start_response, status, body, extra_headers=None)` (`:275-282`) sets `Content-Type: application/json; charset=utf-8`, `Content-Length`, `Cache-Control: no-store`, `nosniff` and `no-referrer`. Do not use it for streams, because it sets `Content-Length`.
- `_token(environ)` (`:284-289`) requires `Authorization: Bearer <token>` longer than 27 characters, otherwise `AlphaError(..., 401)`.
- `_body(environ)` (`:291-307`):
  - requires `application/json`, otherwise 415;
  - `0 < CONTENT_LENGTH <= 12_000_000`, otherwise 413;
  - the body must be a JSON object.
  - The OpenUI routes should enforce their own tighter caps after this (128 KiB source and so on, per contracts §7).
- `_origin(environ, mutation)` (`:309-320`). This is the **request guard and CSRF check**:
  - Only mutations (POST/PUT/PATCH/DELETE) are checked.
  - They need the header `X-PostRiff-Request: founder-alpha`.
  - If `Origin` is present it must equal `f"{X-Forwarded-Proto}://{X-Forwarded-Host or Host}"`.
  - GETs have no origin check (bearer only). Because bearer tokens travel in headers, there is no cookie CSRF risk.
- `_query_int(environ, key, default)` (`:322-330`) accepts digits only, otherwise 400. `_query_str` is at `:332-335`.
- **Error envelope** (`:1015-1025`): `AlphaError` becomes `{"error": str, "code": code}` with its status. The safe failure classification goes into `environ['postriff.failure']`. A generic `Exception` becomes 500 `{"error": "...Check what was saved before trying again.", "code": "internal_error"}` with `exceptionType` and a masked `routePattern` (`route_pattern()`, `:248-253`).

### 3.4 `agent_runtime_v2/http.py` (routes under `/api/workspaces/{id}/agent/`) [CODE]
- `handle(app, environ, start_response, service, token, method, parts)` (`http.py:46-86`):
  - `require_session_token(token)` (`api_guard.py:5-8`) refuses API tokens with 403.
  - `workspace_id, resource = parts[2], parts[4]`; `rest = parts[5:]`; `runtime = runtime_for(service)` (`http.py:23-43`, one `AgentRuntimeService` per hosted service; `harness.enabled()` raises on Vercel, `harness.py:23-28`).
- Existing routes:
  - `GET status`
  - `POST turns` (201)
  - `GET conversations/{c}/active-run`
  - `GET runs/{run}`
  - `GET runs/{run}/events?cursor=`
  - `POST runs/{run}/cancel`
  - `GET conversations/{c}/state`
  - `GET tasks/{task}?cursor=`
  - `POST approvals/decide`
  - `POST attachments`
  - `POST voice/sessions[/{v}/transcript|/end]`
  - anything else → 404 `"This hosted route is unavailable."`
- **Mount point for OpenUI:**
  - `parts[4] == "ui"` gives `rest = ["presentations", …] | ["queries"] | ["actions"] | ["actions","activate"]`.
  - Add one branch in `http.py` (A-owned hook) delegating to a new module, e.g. `agent_runtime_v2/ui_http.py`. Lanes B, D and F own the handlers behind it.
  - No `vercel.json` change is needed for the WSGI option.

### 3.5 How a turn runs today (the precedent for progress delivery) [CODE]
- `AgentRuntimeService.turn(...)` (`service.py:89-138`) runs **synchronously inside `POST /turns`**:
  - `_manager_turn` (`:419-440`)
  - `_run_manager` (`:442-`)
  - `asyncio.run(manager_mod.drive(ctx, Runner.run(manager, items, context=ctx, max_turns=14, run_config=run_config), TURN_BUDGET_SECONDS))` (`:491`)
  - `TURN_BUDGET_SECONDS = 240` (`service.py:39`), under `maxDuration` 300.
- Progress reaches the browser by **DB-backed polling, not streaming**:
  - `ideas._insert_event(cur, ws, run_id, safe_event(...))` (`ideas.py:941-951`) writes `public.pr_agent_events(run_id, workspace_id, seq, kind, body)`.
  - `run_events` (`service.py:1143-1157`) and `ideas._events_for` (`ideas.py:1815-1823`, `seq > cursor`, `LIMIT 500`) read them back.
  - Web polls: `use-run.ts:30-41` (1200 ms, backoff to 15 s); `use-thinking-state.ts:58`; founder `features/founder/agent/chat.tsx:34` (`POLL_MS = 1500`).
- **Why `pr_agent_events` cannot carry `ui.delta`** [CODE]:
  - `SAFE_EVENTS` is a closed allowlist (`agent_runtime.py:14`). `_insert_event` raises 500 for any other kind (`ideas.py:942-943`).
  - Each insert takes `SELECT … FROM pr_workspaces WHERE id=%s FOR UPDATE` plus `pg_advisory_xact_lock` (`ideas.py:934-939`).
  - `MAX_EVENTS = 2000` per run (`ideas.py:33`, `:947-948`).
  - The contracts (§4) also forbid raw source in SAFE_EVENTS channels.
  - **So UI events and checkpoints need F's own store**, with A allocating the migration. The highest file in `migrations/postriff` at this SHA is `096_universal_library_duplicate_index.sql`; gaps such as 072-087 suggest other branches hold numbers, so A must check across branches. `pr_agent_events` may only carry a safe pointer (for example `artifact.created`).
- **Existing pseudo-SSE** (`hosted_app.py:381-395`, Ideas `runs/{run}/events` with `Accept: text/event-stream`):
  - Replays stored events, then closes. It sets `Content-Length`, so the response is fully buffered.
  - Framing to reuse: `id: {runId}:{seq}`, `event: {type}`, `data: {json}`, then a final `event: run.status` with `retry: 2000`.
  - `Last-Event-ID` is parsed as `rsplit(':')[1]` and merged with `?cursor=` (`:385-387`). This is the precedent for `GET …/events?after=`.
- **There is no real chunked streaming anywhere in the Python code.** Grep for `text/event-stream`, `StreamingResponse`, `chunked` and `Transfer-Encoding` finds only the buffered SSE above and an `Accept` header in `research.py:210`.

### 3.6 Lock and transaction cost of `repository.transaction` [CODE]
`PostgresWorkspaceRepository.transaction(token, workspace_id)` (`hosted.py:112-133`), on every call:
1. Verifies the session with `verify_session(token)`. That is a Supabase `getUser` HTTPS request (`hosted_app.py:55-64`, 12 s timeout) plus a DB statement for tombstones, revocations and MFA (`:75-86`).
2. Opens a fresh `psycopg.connect(..., prepare_threshold=None, connect_timeout=8)` (`hosted_app.py:47`).
3. Takes `SELECT … FROM pr_workspaces w JOIN pr_memberships … FOR UPDATE OF w`. **That is a workspace-wide row lock.**

The `Ledger` methods assume the workspace row is already locked (`billing.py:118-119`). Implications for B and F:
- Reserve, claim the lease and persist the artifact in **one short** `repository.transaction` before provider dispatch.
- **Never** hold it during the stream.
- Checkpoint writes during the stream should use `connection_factory()` directly, keyed on the artifact or lease row. Do not re-enter `repository.transaction` per checkpoint, which would cost one Supabase call plus one workspace lock each time.
- Finalize (CAS commit plus ledger settle) in one short `repository.transaction`, which re-verifies the session and membership.
- Replay GETs that go through `repository.transaction` also take the workspace lock today (`run_events` does). A read-only membership helper without `FOR UPDATE` would reduce contention for `GET events?after=` and `/queries`. That is an A decision, because `hosted.py` is shared.

### 3.7 Provider streaming hook [CODE]
- `MeteredModel.stream_response(...)` (`manager.py:191-195`) only increments `ledger.model_requests`. **It records no tokens, span or cost.**
- `get_response` (`:172-189`) records spans.
- B must not reuse `MeteredModel` streaming as is. Wrap the stream, capture the final usage event, and settle known or unknown usage exactly once.
- `drive()` (`manager.py:154-160`) closes clients in the same loop.

---

## 4. Web client transport [CODE]

- **Base URL:** always same-origin relative paths.
  - `lib/api/client.ts:95`: `ws(id) = /api/workspaces/{id}`.
  - `lib/agent-runtime/client.ts:9`: `base(w) = /api/workspaces/{w}/agent`.
  - Production has no `POSTRIFF_API_ORIGIN`. `next.config.ts:6-11,51-64` proxies `/api/:path*` to `POSTRIFF_API_ORIGIN ?? http://127.0.0.1:4331` only in development or when the variable is set, and preview forbids it (`deployment-env.mjs:12`; `deployment.py:29-30`).
- **Guard header:** `APP_GUARD_HEADER = { 'X-PostRiff-Request': 'founder-alpha' }` (`lib/api/client.ts:78`). It is sent on every request, including GETs.
- **Bearer source:** `AuthProvider.getToken` (`lib/auth/session.tsx:138-149`):
  - Supabase mode: `supabaseRef.current.auth.getSession()` then `.access_token`, using the `@supabase/ssr` browser client (`lib/supabase/client.ts`).
  - Dev mode: `dev:<principal>`.
  - Injected through `createApi(getToken)` (`session.tsx:151`) and `createAgentApi(getToken)` (`use-agent.ts:13`).
- **Fetch wrappers:**
  - `lib/api/client.ts:117-140`: `headers(auth)` adds `Content-Type`, guard and `Authorization`; `get` uses `cache: 'no-store'`; `send` optionally adds `AbortSignal.timeout(ms)`. `parse` (`:99-115`) reads `{error, code}` and `X-Request-ID` (32 hex characters) into `ApiError(message, status, code, requestId)` (`:80-91`).
  - `lib/agent-runtime/client.ts:44-81`: `createAgentApi`, with `get`/`post(path, body, signal?)`. Its `parse` (`:28-42`) **drops `X-Request-ID`** (a small gap for stream error correlation).
- **No streaming client exists.** There is no `EventSource`, `getReader()` or `ReadableStream` consumer (grep finds only `TextDecoder` for file decoding, in `capture-card.tsx:214` and `text-file.ts:45`).
  - `useUiArtifactStream` (F) must be new code: `fetch` POST or GET with `Authorization` and the guard, `response.body.getReader()`, `TextDecoder('utf-8', {stream:true})`, an SSE line parser that keeps partial lines, dedup by `seq`, and gap detection followed by `GET events?after=`.
  - `EventSource` is unusable because it cannot send `Authorization`, and credentials must not go in URLs.
- **Next proxy** (`web/src/proxy.ts:48-72`): the matcher excludes `api/`, `_next/*`, `monitoring` and static files. Every other path runs `updateSession()`, which refreshes Supabase cookies (`lib/supabase/middleware.ts`).
- **Next route handlers:** only one exists, `web/src/app/auth/callback/route.ts` (GET, PKCE exchange). There is no `web/src/app/api/` directory, and **no `/api/*` Next handler can be reached in production**, because the top-level rewrite sends `/api/(.*)` to Python. App Router folders that start with `_` are private (not routable), so an internal path must not start with `_`.
- **Sentry (Next server):** `instrumentation.ts:4-36` uses `sendDefaultPii: false`, `beforeSend: scrubTelemetry` and `onRequestError = Sentry.captureRequestError`. A validator route must catch its own errors and never put source text in error messages.

---

## 5. Can Vercel Python WSGI flush chunked streaming?

**Answer: yes, per the platform source and docs [VERCEL-SRC][DOCS]. It is still unproven on this deployment.** G04 must still produce deployed evidence.

### 5.1 Vercel runtime source: `vercel/vercel` `python/vercel-runtime/src/vercel_runtime/vc_init.py` (main, 1777 lines)
- **IPC (streaming) mode** is used when `VERCEL_IPC_PATH` is set (`:91-94`).
  - For a WSGI app it starts `ThreadingHTTPServer(("127.0.0.1", 0), Handler)` (`:1256-1259`), one thread per request.
  - `Handler.handle_request` (`:1143-1223`):
    - reads the full request body into `wsgi.input = BytesIO(body)` and sets `CONTENT_LENGTH`;
    - forwards headers as `HTTP_*`, dropping `Transfer-Encoding`;
    - calls `response = wsgi_user_app(env, start_response)`;
    - runs `for data in response: if data: self.wfile.write(data); self.wfile.flush()`, then `finally: response.close()` when the response has a `close()` method.
  - **Each yielded WSGI chunk is written and flushed immediately.** On a client disconnect, `wfile.write` raises. The `finally` then calls `response.close()`, which raises `GeneratorExit` at the generator's current `yield`.
  - So disconnects are detected only on the **next write**. Heartbeats (around every 10 s) bound that detection latency.
- **ASGI** apps run under vendored uvicorn with `lifespan="auto"` (`:1225-1254`).
- A legacy `vc_handler(event, context)` path (`:1281`, `:1389`) builds the response as one whole body, i.e. buffered. Per the changelog below it is the old non-IPC mode.

### 5.2 Docs
- Changelog, 2025-01-06, "Python Vercel Functions now have streaming enabled by default": streaming is "enabled by default for all Vercel Functions using the Python runtime", and `VERCEL_FORCE_PYTHON_STREAMING` "is no longer necessary". It does not distinguish WSGI from ASGI.
- Python runtime doc (`/docs/functions/runtimes/python`, updated 2026-08-12): "Vercel Functions support streaming responses when using the Python runtime."
- Flask KB (`/kb/guide/ship-a-flask-app-on-vercel`): "Return a Flask `Response` backed by a generator to stream text, server-sent events, or AI model output". That is the WSGI generator pattern.

### 5.3 Not verified
- The exact `vercel-runtime` version the production build uses.
- Whether the CDN or edge compresses or coalesces `text/event-stream` from Python.
- iOS Safari chunk delivery.
- Behaviour through the local dev chain (Next dev rewrite proxy to wsgiref `LocalConcurrentServer`, `scripts/postriff_dev_hosted.py:448-453`).

Required response headers to reduce buffering risk: `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-store, no-transform`, `X-Accel-Buffering: no`, **no `Content-Length`**, and no hop-by-hop headers (WSGI forbids `Connection`).

### 5.4 Proof needed for G04
The harness is refused on Vercel (`harness.py:26-27`). Prove transport in two steps:
1. **Preview (no model cost):** a flag-gated, authenticated probe route, `GET /api/workspaces/{w}/agent/ui/diagnostics/stream` behind `RAFII_GENUI_STREAM_PROBE=1`, set in preview only. It emits three frames 1.5 s apart, including a multi-byte UTF-8 character split across two frames. Record client and server monotonic timings, and a network capture showing frames arrive before the response ends.
2. **Production canary:** the same assertion on a real `POST /presentations`.

---

## 6. Server-to-server mechanisms that exist today [CODE]

- **Next to Python:** `web/src/lib/workspace/server-bootstrap.ts:6-39` with `bootstrap.ts:12-51`.
  - The server component fetches `origin + /api/me` and `/api/workspaces` with `Authorization: Bearer <supabase access_token>`.
  - On preview it forwards `Cookie: _vercel_jwt=…` and/or `x-vercel-protection-bypass` **taken from the incoming request**, through the public deployment origin (`bootstrapOrigin`, which accepts `VERCEL_URL`, `VERCEL_BRANCH_URL` or `POSTRIFF_STAGING_PUBLIC_BASE_URL` on preview and `NEXT_PUBLIC_APP_URL` in production).
  - Options: `redirect:'error'`, `AbortSignal.timeout(2500)`.
  - This proves preview Deployment Protection is active, and that the app reuses user-held access rather than a stored bypass secret.
- **Secrets that exist:** `CRON_SECRET`, used for the cron bearer (`hosted_app.py:611-616`) and as a fallback HMAC base in `notifications/webhooks.py:150-155` (`hmac.new(base, b"rafii-notification-unsubscribe-v1", sha256)`).
- **Missing:** no `VERCEL_AUTOMATION_BYPASS_SECRET` usage, no internal-service token, and no Python-to-Node call anywhere.
- **Preview secret pinning:** `deployment.py:44-52` requires the SHA-256 fingerprint of each named secret in `POSTRIFF_STAGING_SECRET_SHA256` on preview. **Any new secret must be added to that `names` set** so preview stays pinned. A owns this.
- **Flags:** env-based only.
  - `agent_runtime_v2/config.py:21` `FLAGS = (RAFII_AGENT_V2_ENABLED, …)`; `RuntimeConfig.from_environment` (`:103-136`); `.enabled()` (`:139`); exposed through `GET agent/status → flags` (`config.public()`, `:184-188`).
  - `POSTRIFF_AI_PAUSED=1` is the global paid-AI kill switch (`billing.py:97-99`).
  - **Changing an env var takes effect only after a redeploy.** A DB-backed instant switch does not exist. Kill-switch latency is therefore the redeploy time unless A adds one.
  - `RuntimeConfig.from_environment()` reads `os.environ` directly, bypassing `isolated_environment`.

### 6.1 Vercel Service bindings [DOCS: /docs/services/bindings, /docs/services]
- **Declared on the caller:** `"bindings": [{"type":"service","service":"<target>","format":"url","env":"<ENV_NAME>"}]`. Vercel injects the absolute target URL at runtime only (not at build, not in middleware).
- **The URL is deployment-aware:** a preview reaches the same preview's target.
- **"Internal calls also skip the public request pipeline. Firewall, Deployment Protection, the project's top-level middleware, and CDN request accounting do not apply."** Each call is billed as a single service request.
- **"A binding grants internal access only. It does not authenticate or authorize the call."** Application-level auth is still required.
- Supported for Node.js and Python (not Go or Rust). Services are Beta. The bindings changelog says "(beta)".
- **Not verified:** a binding whose target is a `framework: "nextjs"` service, and whether a binding call bypasses top-level rewrites when the target path is shadowed publicly [INFER].

---

## 7. Recommendations

### 7.1 Streaming adapter: reuse the WSGI app; no new rewrite
**Primary.** Implement streaming inside the existing WSGI app at `/api/workspaces/{w}/agent/ui/*`: `http.py` branch `resource == "ui"` delegates to `ui_http.py`. No `vercel.json`, preflight or route-order change.

**Shape of `POST …/agent/ui/presentations`:**
1. **Before `start_response`, all synchronous:**
   - `require_session_token`; guard and origin are already enforced by `_handle`.
   - `app._body` plus contract caps.
   - One short `repository.transaction`: membership `require(...)`, parent-run authorization, durable lease claim (create or resume by idempotency key), ledger reservation inside the combined turn budget, artifact persisted as `queued`. Commit.
   - A duplicate idempotency key returns the existing artifact. It replays rather than producing again.
   - Errors here use the normal JSON `AlphaError` envelope, because no stream has started.
2. **Then:**
   - `start_response('200 OK', [('Content-Type','text/event-stream; charset=utf-8'), ('Cache-Control','no-store, no-transform'), ('X-Accel-Buffering','no'), ('X-Content-Type-Options','nosniff'), ('Referrer-Policy','no-referrer')])`. The outer wrapper adds `X-Request-ID`.
   - Return a closing-iterator object:
     - a worker thread runs `asyncio.run(presenter(...))` with `AsyncOpenAI(max_retries=0)` (phone precedent) and pushes `UiEventV1` objects to a bounded `queue.Queue`;
     - the generator `get(timeout=10)` yields SSE frames (`id: {artifactId}:{seq}`, `event: {kind}`, `data: {json}`), or `ui.heartbeat` on timeout;
     - checkpoints are persisted through `connection_factory()` on the lease row every N bytes or ms, not per token and never under `pr_workspaces FOR UPDATE`;
     - finalize in one short `repository.transaction` (validate through the Node seam, CAS commit, settle the ledger), then emit `ui.ready`.
   - `close()`, on `GeneratorExit` (client gone) or normal end:
     - cancel the worker (`loop.call_soon_threadsafe(task.cancel)`) and join it with a deadline;
     - mark the artifact `interrupted` or `canceled` and settle known or unknown usage once (never treat unknown as zero);
     - log `request.stream_closed`.
   - Every exception inside the generator becomes a terminal `ui.failed` frame with a stable reason code. Nothing is re-raised.
3. **Budget:** the presenter's 60 s limit applies inside the `postriff_api` `maxDuration` of 300 s. The Manager turn (up to 240 s) runs in a **separate** `POST /turns`, so the two never stack in one invocation.
4. **`GET …/presentations/{id}/events?after=`:** authorized bounded replay. Honour `Last-Event-ID` the way `hosted_app.py:385-387` does. Tail for at most about 25-45 s with heartbeats, then close; the client reconnects with `after=lastSeq`. It never dispatches a provider call.

**Fallback (only if the preview G04 probe shows WSGI buffering).** Add an ASGI service modelled on `rafii_phone_media`:
- `api/genui.py` exports a lazy Starlette app (`create_lazy_app` pattern), using `StreamingResponse` plus `request.is_disconnected()`. Guard, origin and token checks are imported from `HostedApplication` static methods via an environ shim.
- Rewrite placed **after the two phone rules and before `/api/(.*)`**: `{"source": "/api/workspaces/([^/]+)/agent/ui/presentations(.*)", "destination": {"service": "rafii_genui_stream"}}`.
- Service: `{"root": ".", "runtime": "python", "entrypoint": "api.genui:app", "functions": {"api/genui.py": {"maxDuration": 300, "excludeFiles": <same set>}}}`.
- Update `check_postriff_hosted_preflight.py:62-77`, `tests/test_postriff_hosted_deployment.py:100-116` and the artifact script in the same commit.
- Keep non-streaming UI routes on WSGI.

**Degraded mode.** If streaming fails on a client (for example an iOS Safari quirk), use the existing blocking-POST plus parallel polling of `GET events?after=`. It is progressive at checkpoint granularity. It is not the G04 pass condition.

### 7.2 Python presenter calling the trusted Node parser validator
**Primary.** Python calls a Next.js route handler over a Vercel service binding, with HMAC request signing.

- **`vercel.json` (A):**
  - Add to `services.postriff_api`: `"bindings": [{"type":"service","service":"postriff_web","format":"url","env":"RAFII_WEB_INTERNAL_URL"}]`.
  - Add a top-level rewrite `{"source": "/internal/(.*)", "destination": {"service": "postriff_api"}}` placed **immediately before** `/(.*)`. This shadows the route publicly: Python answers with 401/403/404, so the Next handler has no public ingress. The binding call targets the service directly [INFER, must be proven in preview].
- **Route handler (A owns the file; C owns the imported adapter):** `web/src/app/internal/genui/v1/validate/route.ts`.
  - `export const runtime = 'nodejs'`, `export const dynamic = 'force-dynamic'`, `POST` only.
  - Reject `content-length > 160 KiB`, or a non-JSON body, before reading.
  - Verify the HMAC with constant-time compare (`crypto.timingSafeEqual`).
  - Call C's pure `validateAndMerge({mode:'generate'|'patch', baseSource, candidateSource, libraryHash})` from `web/src/lib/agent-runtime/ui-parser/`. It does no rendering, network or tool execution.
  - Return `{accepted, canonicalSource, sourceHash, errors[≤N], statementCount, queryNames, actionNames}` with `Cache-Control: no-store`.
  - Catch all errors. Return a fixed `{accepted:false, errors:[{code:'validator_error'}]}` so Sentry never receives source.
- **Add `internal/` to the `proxy.ts` matcher exclusion** (`proxy.ts:68-71`) so `updateSession`, which calls Supabase, never runs on validator calls.
- **Auth:**
  - New secret `RAFII_GENUI_VALIDATOR_SECRET` (≥32 random bytes, a server env var on both services, never `NEXT_PUBLIC_`). Add it to `deployment.py` `names` for preview pinning, and to the preflight `REQUIRED_ENV` once activated.
  - Request headers:
    - `X-Rafii-Validator-Timestamp: <unix seconds>`;
    - `X-Rafii-Validator-Key: v1`;
    - `X-Rafii-Validator-Signature: hex(HMAC_SHA256(secret, "v1\n" + ts + "\n" + sha256_hex(body)))`.
  - Body binds scope: `{workspaceId, artifactId, attemptId, libraryHash, mode, …}`.
  - Reject `|now - ts| > 60 s`. Replay is harmless because the function is pure.
  - Do not reuse `CRON_SECRET` or `POSTRIFF_CREDENTIAL_KEY`: that would copy a high-value key into the web function's environment.
- **Python client:**
  - `urllib.request.Request(urljoin(os.environ['RAFII_WEB_INTERNAL_URL'], 'internal/genui/v1/validate'), data=…, headers=…)` with `urlopen(timeout=8, context=ssl.create_default_context())` (same stack as `supabase_verifier`, `hosted_app.py:55-64`).
  - No retries. A non-200 response or a timeout means "not accepted", which leads to a native fallback.
  - Validate only at finalize and on patch merge, not per chunk.
- **Fallback if a binding to the Next service does not work on preview:**
  - Call `POSTRIFF_PUBLIC_BASE_URL` (production) or the preview's own origin with the same HMAC.
  - On preview, add `x-vercel-protection-bypass: $VERCEL_AUTOMATION_BYPASS_SECRET`. This needs "Protection Bypass for Automation" enabled. It is an existing Vercel feature, but enabling it is a project-setting change to record.
  - Drop the public shadow rule; HMAC is then the only gate.
- **Rejected alternative:** a dedicated non-Next Node service (`root: services/ui-validator/`) would need a second lockfile and install of the OpenUI packages, risking version drift from the browser renderer.

### 7.3 Founder surface
- Founder routes run inside `rafii_control.http.ControlApplication.__call__` (`rafii_control/http.py:75-170`).
- **Auth there:**
  - `__Host-rafii-control` cookie, `X-CSRF-Token`, an allowed origin and host;
  - capability `copilot.use` for `/agent/*` (`http.py:322-339`);
  - a 270 s deadline for `/agent/*` (`:66-73`);
  - body ≤ 32768 bytes (`:98-99`).
- **It always returns a single JSON body** (`:169-170`). Its deadline `ContextVar` is reset in `finally` before any generator could run.
- **Recommendation:** map founder GenUI to `/api/control/v2/agent/ui/{presentations,queries,actions,…}` registered beside the founder agent routes (`http.py:273-281`).
  - Use the existing founder pattern, a blocking POST plus `GET …/events?after=` polling (as `features/founder/agent/chat.tsx:34`), unless A adds a reviewed streaming branch to `ControlApplication`.
  - Never accept a client `isFounder` flag.

---

## 8. Risks and gaps
1. **`rafii.io` neither resolves nor is attached to any Vercel project** [LIVE]. G24 cannot pass until James attaches the domain and DNS. The production alias today is `postriff-phase2-private.vercel.app`.
2. WSGI streaming is supported by platform source and docs, but **this deployment has not been proven**. The deployed `vercel-runtime` version, CDN compression and iOS Safari behaviour are untested.
3. The `HostedApplication` log, metrics and error handling do not cover generator bodies (`hosted_app.py:451-482`, `1015-1039`).
4. `repository.transaction` adds a Supabase round trip and a workspace `FOR UPDATE` per call (`hosted.py:112-133`), so it cannot be used per checkpoint. The current replay reads lock the workspace too.
5. `pr_agent_events` is unusable for UI deltas (`SAFE_EVENTS`, workspace lock per insert, 2000-event cap).
6. `MeteredModel.stream_response` records no usage (`manager.py:191-195`). This affects G13 accounting.
7. No app-wide CSP exists to back the no-eval rule. A Report-Only CSP would be optional hardening; adding an enforcing CSP now risks breaking Next and Sentry.
8. Kill switches are env flags, effective only after a redeploy. There is no DB-backed instant switch.
9. Preview needs Vercel Authentication. Deployed G04 tests need user-held `_vercel_jwt` access or automation bypass. Never weaken protection globally.
10. Service bindings are Beta. A `nextjs` binding target and the shadow-rewrite behaviour are unverified.
11. `.claude/launch.json` in this worktree points at the **dirty main checkout** (`/Users/ouxianxing/Documents/James-Au-Studio`). Do not use it for previews from this worktree.
12. Local dev streaming runs Next dev rewrite to wsgiref (HTTP/1.0, threaded). It probably streams [INFER], but it is not production evidence.
13. `lib/agent-runtime/client.ts` `parse` drops `X-Request-ID`. Add it to the stream client so errors can be correlated.
