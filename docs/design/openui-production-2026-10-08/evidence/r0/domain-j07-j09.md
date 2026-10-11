# R0 domain map — J07 Research, J08 Automations/recovery, J09 Founder agent

Reader: role-A R0 read-only reader. Baseline: worktree `rafii-openui-a-integration-20261008` at `3da806f0` (branch
`claude/rafii-openui-production-20261008`). Method: `rg/grep/sed` only; no builds or tests run. Paths are relative to the repo root.

Legend: **[V]** = verified by reading code at the cited line; **[I]** = inference (not proven by code or not
checked against a running deployment); **[GAP]** = missing adapter, contract drift or risk an implementer must handle.

---

## 0. Shared mechanisms every lane reuses (all verified)

| Mechanism | Where | What it guarantees |
|---|---|---|
| Tool spec + effect class | `src/postriff_phase2/agent_runtime_v2/contracts.py:17-21` `EFFECTS = READ, CREATE_DRAFT, MUTATE_REVERSIBLE, PREPARE_EXTERNAL, EXTERNAL_EFFECT, DESTRUCTIVE, SECRET`; `FORBIDDEN_EFFECTS = (EXTERNAL_EFFECT, DESTRUCTIVE, SECRET)`; `ToolSpec` at :47-71 (`name, effect, permission, description, idempotent, approval, voice, audit, tenant='workspace'`). `PREPARE_EXTERNAL` must have `approval=True` (:69). | Use `ToolSpec.effect` as the server-side effect class for D's `ui_capabilities`. The OpenUI `Query`/`Mutation` label must never be trusted; map from this. |
| Single execution gate | `agent_runtime_v2/tool_adapter.py:96 execute(ctx, tool, args, *, scope, agent)` | scope check, tenant check (`tenant_mismatch` :85), voice check, `membership.allows(spec.permission)` re-checked, cancel check before non-READ, schema check, typed failures. |
| Tool registry | `tool_adapter.py:51 REGISTRY`, `register(spec, schema, label)` :54 | **Global** per process; founder tools are registered into the same dict (see §3.6). |
| Permission classes | `src/postriff_phase2/permissions.py:15-24 CLASSES` (`read, edit, approve, reply, moderate, manage_connections, manage_members, owner`); `ACTION_CLASSES` :27-52; `STEP_UP_ACTIONS` :55; `Membership.allows` :74; `require` :92 | `research_egress`→owner; `raffi_recurrence_activate/pause/resume/cancel`→owner; `raffi_run_decide/commit`→approve; `raffi_recurrence_watch`→read; unknown action→`edit`. |
| Generic workspace command route | `hosted_app.py:993-1006` `POST /api/workspaces/{id}/actions` body `{action, payload, expectedRevision}` → `service.mutate(...)` → `hosted.py:230 __call__` dispatch (research at :246, recurrences at :260) | Revision CAS (`expectedRevision`), permission by `permissions.classify(action)`. |
| Agent runtime routes | `agent_runtime_v2/http.py:46 handle()` under `/api/workspaces/{id}/agent/{resource}` — mounted from `hosted_app.py:781` | `resource = parts[4]`; natural seam for A's new `resource == "ui"` branch. Uses `app._json` (single JSON body; **no streaming helper**). Body limit `hosted_app._body` :292-307 = 12,000,000 bytes, JSON content-type required. |
| Proposal → native decide | Agent: `POST /api/workspaces/{id}/agent/approvals/decide` → `agent_runtime_v2/service.py:1187 decide(runtime, ws, token, payload)` (requires `conversationId, messageId, proposalId, digest, decision∈{apply,dismiss}`, optional `timeZone`) → `agent_runtime_v2/approvals.py:136 decide(...)` → `site_agent/service.py:1082 apply_proposal` / `:1146 dismiss_proposal`, then re-read `approvals.verify_applied` :102. Site panel: `POST /api/workspaces/{id}/site-agent/proposals/{apply|dismiss}` (`hosted_app.py:421-426`). | Digest + expiry + status check `site_agent/proposals.py:188 check()`; TTL `proposals.py:22 TTL_SECONDS = 24*3600`; owner re-check inside the locked `after()` (`site_agent/service.py:1111-1115`). This is the ONLY apply/dismiss authority. Note `approvals.decide` retries once on `workspace_revision_conflict` (:147-154) — a domain-level re-read, not a model retry. |
| Web client | `web/src/lib/agent-runtime/client.ts:9 base = /api/workspaces/{w}/agent`; `decide` :64-65; `turn` :58; `run` :59; `runEvents` :61 | F/D bridges should call these, not new fetchers. |

---

## 1. J07 — Research / content intelligence

### 1.1 The approved research route (verified)

- **Backend providers [V]:** `src/postriff_phase2/research.py` — `ExaSearch` (MCP JSON-RPC to `https://mcp.exa.ai/mcp`, :202) and
  `JinaReader` (`https://r.jina.ai/`, :248), wrapped by `Researcher` (:265; `run(text, intent="draft")` :291). Limits :31-43:
  `SEARCH_TIMEOUT=12`, `READ_TIMEOUT=15`, `TOTAL_BUDGET_SECONDS=30`, `SEARCH_ATTEMPTS=3`, `READ_ATTEMPTS=2`, `MAX_RESULTS=6`,
  `MAX_PAGES=2`, `MAX_FACTS=12`, `MAX_FACT_CHARS=500`. Walled hosts skipped (`SKIP_DOMAINS` :45).
  Output: `{query, pages:[{title,url,host,published,facts[],fetchedAt}], searched[], warnings[], elapsed}` (:327-328).
  `published` is from Exa search metadata (may be `""`); `fetchedAt` is UTC ISO.
- **Env var names [V]:** `POSTRIFF_RESEARCH` (`"0"` = deployment off, `enabled()` :66), `POSTRIFF_EXA_MCP_URL`, `POSTRIFF_READER_URL`,
  `POSTRIFF_HOSTED`, `VERCEL` (hosted detection :80-81).
- **Consent (egress authorization) [V]:** `research.consent(state)` :84 reads `state["researchEgress"]` (default `{"web": False}`);
  `allowed(state)` :89 = `enabled() and (not hosted() or consent.web is True)`; `consent_summary(state)` :94 →
  `{web, decidedAt, decidedBy, processors, hosted, enabled}`; owner-only write `apply_research_action` :101 for action
  `research_egress` with payload `{web: bool, confirmed: true}` (permission `owner`, `permissions.py:34`). Wired at `hosted.py:246`.
  Web UI writer: `web/src/features/memory/access-card.tsx:217`. Read: `GET /api/workspaces/{id}/memory` →
  `ideas.memory_files` (`ideas.py:391`, returns `"research": research.consent_summary(state)` at :397).
- **Research-off state [V]:** agent tool returns `{"ok": False, "code": "research_off", "error": RESEARCH_OFF, "guide": "turn_on_web_search"}`
  (`agent_runtime_v2/specialists.py:105-120`). Guide `turn_on_web_search` exists in `site_agent/guide_manifest.json`
  (10 guides). Drafting path returns `research.off_record(query)` :112 (`{"off": True, "warnings":[OFF_NOTE]}`).
  Site tool `privacy.egress_state` (`site_agent/tools.py:546`) returns `webResearch`, `researchOnDeployment`.
  Test: `tests/test_agent_runtime.py:1013 test_research_off_says_so_and_offers_the_guide`.

### 1.2 Agent-runtime entry points (verified)

- Tool `web_research` — `specialists.py:109-128`: `ToolSpec("web_research", READ, "read", ...)`, schema `{question: string ≤400, required}`.
  Executor: opens `ctx.workspace()` to read consent, then `Researcher.run(question)`; returns
  `{"ok": True, "verified": bool(pages), "data": {"query", "pages":[{title,url,host,published|None,fetchedAt,facts[≤6×400]}], "warnings"}}`.
  Side effect: appends `{"text": "Web source: <title> (<url>, fetched <fetchedAt>)", "kind": "external", "rule": "web research"}`
  to `ctx.ledger.facts` (:126). **Does not persist pages as workspace sources.**
- Callers: in `MANAGER_TOOLS` (`agent_runtime_v2/manager.py:30-34`) and the `research` specialist (`specialists.py:69-75`, tools
  `help_search, help_get, content_search, library_search, library_read, web_research`, workload `standard_reasoning`; only built when
  `RAFII_SPECIALISTS_ENABLED` — `manager.py:377`). Slash command `search` (`agent_runtime_v2/commands.py:34`).
- Manager instruction: "News, trends ... call web_research ... Name each source and its date" (`manager.py:68-70`).
- Tool output is untrusted data (`tool_adapter.py` doc §; `context.untrusted`).

### 1.3 Drafting path that DOES persist research as sources (verified)

`IdeasService._research(workspace_id, token, payload, text, parsed, key, conversation_id, *, reworking=False)` — `ideas.py:1050-1133`:
idempotent claim in `public.pr_research_requests` (migration `019_research_requests.sql`; columns `workspace_id, idempotency_key,
request_digest, status, result`) **before** external I/O (:1080-1091); runs `Researcher`; then a workspace command that, per page,
adds a `source` (`self.commands(state, actor, "source", {"kind":"text","text":body,"title":title})`), sets
`source["origin"] = {"kind":"web_research","url","host","query","published","fetchedAt"}`, `source["unknowns"]`,
`source["egressConsent"] ⊇ {"cloud"}`, and runs `approve_source` for all facts (:1101-1115). Consent is re-checked inside the
command (:1099). Records `product_events.record(... "research.completed" ...)`.
- Draft linkage [V]: saved variants carry `sourceIds` and `provenance.runId` (`ideas.py:1933-1955`); `ideas._project` honours
  `payload["sourceIds"]` (:1600). Frontend already marks web sources: `web/src/features/ideas/use-sources.ts:34 isWeb`,
  `source-list.tsx:142-182` (host chip).
- Agent tool `draft_create` (`domain_tools.py:438-479`) schema = `{brief, platforms[], language?, campaignId?, stepId?}` — **no
  `sourceIds`**; it calls `_writing_run` (:400) with `text=""` so research may run inside the writing pipeline but cannot be pinned
  to the pages the user saw.

### 1.4 Other research-like services (verified, do NOT route J07 through them without authorization)

- `coworker/research_broker.py` (provider abstraction, injection scanning, `KINDS` incl. `local_agent_reach`) — used by coworker
  listening/growth; adds evidence types. Hosted egress still gated by `research.allowed`.
- `automation_research.py` (708 lines) — automation research stage (`automation_runs.research_step` :158).
- `growth/*` incl. `jev.py`, `growth/trends/providers/runtime.py` (requires `researchEgress.web`) — separate (possibly paid) routes.
  **[I]** treat as out of scope for J07 unless already authorized; spec forbids new paid routes.

### 1.5 J07 thin adapters D must build (GAP)

1. **Structured research projection [GAP]:** pages exist only in the transient tool output; the persisted result keeps only the
   string facts (`service.py:817` `"facts": ledger.facts[:20]`). `result.citations` is help citations only (`contracts.py:102`).
   ToolActivity rows carry no data. → D needs `ui_domain/research.py` that captures `web_research` output into the projection
   (recommended: a bounded additive `ledger.research` list persisted as `result.research = {state: available|empty|off|unavailable,
   query, pages:[{title,url,host,published|null,fetchedAt}], warnings}` — shared-contract change owned by A).
   `published=""` must render as "no date", never as fetch date.
2. **Save page(s) as sources [GAP]:** user-triggered action `research.save_sources` (effect MUTATE_REVERSIBLE, permission `edit`,
   re-check `research.allowed`) reusing the exact `_research` command closure semantics (source + origin + approve_source) and a
   `pr_research_requests`-style idempotency key. Do not re-fetch pages at action time unless the user asks; bind to the
   projection's page digest.
3. **Draft from selected sources [GAP]:** `draft_create` lacks `sourceIds`. Either A approves an additive optional
   `sourceIds` arg (≤20, validated against `state.sources` active ids) or D's adapter calls `_writing_run` with `sourceIds`.
4. Query binding `research.state` → `consent_summary` + deployment flag (read, any member) to render the explicit off state and
   owner-only "turn on" guide link (`ui_guide turn_on_web_search`); non-owners see "ask an owner".
5. Follow-up research ("deliberate follow-up") = a new agent turn (metered), never a Query refresh; Query refresh of a research
   binding must re-read stored projection only (zero egress).

Tests to extend: `tests/test_postriff_research.py` (consent :105), `tests/test_agent_runtime.py:1013`.

---

## 2. J08 — Automations and workspace recovery

### 2.1 Data location (verified)

Workspace JSON state `pr_workspaces.state` → `state["raffi"]["campaignPlanning"]` = `{campaigns[], recurringTasks[], occurrences[]}`
(`campaigns._root` :72; web reader `web/src/features/automations/use-automations.ts:25-44 automationsOf`).
- Task fields used: `id, campaignId, name, version, status ∈ {draft, active, paused, cancelled}, schedule{kind?, slots|localTime,
  timeZone, ...}, destinations[], workflow{policy ∈ {auto, review, drafts}, stages}, nextOccurrence{scheduledFor(epoch), local,
  utc, offset, fold}` (`campaigns.py:270-271`), `nextPublish, definitionDigest, publishAuthority, pausedUntil, deletedAt`.
- Occurrence: `id, taskId, state ∈ {pending, running, completed, ...}, lifecycle, scheduledFor, completedAt, conversationId,
  costUsdMicro, seenAt, skills[], items[{key,state,reason}]` (`automation_runs.py:116, 396`).
- Helpers: `automation_edit.live_tasks(state)` :26 (excludes cancelled/deleted); `automation_plan.describe(schedule)` :354 (text incl.
  time zone); `automation_plan.card(state, task_id, needs, notes, *, providers, live)` :362 (plan, policy, platforms, last 3 runs,
  nextPublish, firstRun); `campaigns.upcoming(schedule, after, count≤14)` :273; `campaigns.next_occurrence` :242;
  `campaigns.first_run` :482; `campaigns.definition_digest` :471.

### 2.2 Read functions (verified; site-agent tools, adapted into the runtime by `tool_adapter._SITE_NAMES` :227-242)

| Tool id → runtime name | Function | Returns |
|---|---|---|
| `automation.list` → `automation_list` | `site_agent/tools.py:508 automation_list(ctx)` | `{automations:[{automationId,name,status,schedule(text),policy,platforms,nextRun(epoch),nextPublish}]}` ≤20 |
| `automation.get` → `automation_get` | `:519 automation_get(ctx, automationId)` | `taskId,name,status,scheduleText,nextOccurrence,nextPublish,policy,plan,platforms,runs,needs,contentLabel,voiceMode` |
| `automation.explain` → `automation_explain` | `:526 automation_explain_tool(ctx, question, automationId=None)` → `automation_explain.answer(...)` | `{text, lines, about, automationId, runId}`, verified when a task was found |
| `channels.capabilities` → `channels_capabilities` | `:406 channels_capabilities(ctx, platform=None, connectionId=None)` | per account `connectionState, readiness, revoked, levels{identity,publish,schedule,analytics,comments_read,reply}, canPublish, publishCode, publishReason`, `publishingLive` |
| `attention.summary` | `site_agent/reads.py:472` | stored facts / derived observations |
| `ui.guide` → `ui_guide` | `site_agent/tools.py:612 ui_guide(ctx, guideId, auto=False)` | allowlisted guide (`guide_manifest.json`: `connect_account, write_first_post, schedule_draft, approve_post, set_up_voice, create_automation, upload_image, turn_on_web_search, choose_model, check_plan`) |

Site-tool runner `site_agent/tools.py:155 run(tool_id, args, ctx)` validates schema (`validate` :104) and permission via
`REQUIREMENT.get(tool_id, "read")` (:87). The publishing specialist scope is at `specialists.py:59-67`.

HTTP reads (verified): `GET /api/workspaces/{id}` (full snapshot; `hosted_app.py:968-969`); `GET /api/workspaces/{id}/channels`
(`oauth.channels` `oauth.py:682`, reads `pr_channel_capabilities`); `GET /api/workspaces/{id}/coworker/attention`
(`coworker/http.py:154` → `coworker/service.py:1056 attention` → `coworker/attention.py:35 build`; **feature-flagged**: 404
`feature_disabled` unless `RAFII_NOTIFICATIONS_V2_ENABLED` or `RAFII_WEEKLY_OPERATOR_ENABLED`, `coworker/service.py:41-42`).
Attention items: `channel.reconnect_required` (audience `manage_connections`), `publish.failed/uncertain`, `campaign.*` with `href`
deep links (attention.py:14-63). Founder-side connection health read model: `public.pr_connection_health` (060) via
`rafii_control.business_connection_health` (066) — founder only.

### 2.3 Write / prepare functions (verified)

| Function | Effect / permission | Notes |
|---|---|---|
| `domain_tools.py:228-262 automation_change_propose(ctx, {request, automationId?, stepId?})` | `MUTATE_REVERSIBLE`, `edit`, `approval=True`, audit `automation.changed_by_proposal` | Builds proposal via `site_agent/proposals.py:52 build(state, text, *, actor, now, owner, paid, zone, conversation_task_id, providers, live)`; proposal carries `taskId, changes, summary, preview, requiredPermission (owner for pause/resume), expiresAt (+24h), digest` (`proposals.py:84-85`, `proposal_digest` :42). Returns `{ok, needsUser, proposal:{proposalId,type,summary,status:"proposed",requiredPermission,expiresAt,view}}` (`_proposal_record` :150-158). |
| `domain_tools.py:161-225 schedule_propose` | `PREPARE_EXTERNAL`, `approve`, approval | J02 primarily; uses `resolve_when` (:128, deterministic dates). |
| Apply/dismiss | native decide (§0) | `proposals.apply` :198, `view` :237 (expired shown as such). |
| `campaigns.apply_action` `campaigns.py:820` | via `POST /actions` | `raffi_recurrence_preview` :889 (creates **draft** task, cost limit 0–$10, `draftsPerOccurrence==1`), `_save` :911, `seen` :913 (read-class-ish; marks runs seen), `watch` :925 (email opt-in, `read`), `activate` :936 (owner, `confirmed`, publish authority for `auto`), `pause` :975, `resume` :986, `cancel` :1006 (owner). |
| Channels | `POST /channels/{c}/oauth/start|complete`, `/verify`, `DELETE /channels/{c}` (`hosted_app.py:844-886`) | `p2_channel_disconnect` is `manage_connections` + step-up (`permissions.py:31,55`). |

### 2.4 J08 manifest rules (recommendations, derived from verified effects)

- Allowed generated **queries**: `automation_list`, `automation_get`, `automation_explain`, `campaigns.upcoming` (next N runs, read
  adapter), `channels_capabilities`, attention (only when flag on; else `unavailable`, not empty).
- Allowed generated **actions**: only `automation_change_propose` (prepare) → native proposal card → existing decide endpoint.
  Optional harmless: `raffi_recurrence_seen`.
- **Never** in generated surface: `raffi_recurrence_activate/resume` (start real recurrence), `raffi_run_decide/commit`
  (publication), `raffi_recurrence_cancel`, `watch` (email), OAuth start/complete, disconnect, verify. Render as native links:
  `/app/automations`, `/app/channels` + `ui_guide connect_account`.
- Time zone: display `task.schedule.timeZone` and `nextOccurrence.local/offset`; never recompute in the model (domain_tools
  comment :128 "a model never computes dates").

### 2.5 J08 gaps [GAP]

1. No dedicated "automation run history" endpoint: history = `occurrences` filtered by `taskId` from the snapshot (last 3 in
   `card`). D needs a bounded paginated read adapter (`ui_domain/automations.py`) over the snapshot (cursor by `scheduledFor`),
   member `read`.
2. Connection status for consumers is two sources (`channels_capabilities` vs flagged attention); D should merge with explicit
   `coverage` and `unavailable` when the attention flag is off.
3. Recovery guides are an allowlist of 10; there is no per-provider "reconnect LinkedIn" guide id beyond `connect_account` — use
   that plus account-card deep link; do not invent guide ids.

Tests: `tests/test_postriff_campaigns.py:27` (activation explicit + idempotent per occurrence), `tests/test_site_agent.py:636,649`
(propose-not-apply; stale/expired/tampered refused), `tests/test_agent_runtime.py:260-342, 593`, `tests/test_postriff_automation_chat.py`
(16 tests), `web/tests/rafii-automations.cjs`, `web/tests/rafii-guide*.cjs`, `web/tests/channel-list.test.cjs`.

---

## 3. J09 — Founder agent

### 3.1 Route family and auth mechanism A must map (verified)

- **Route family:** `/api/control/v2/*`. In the consumer deployment, `hosted_app.py:489-497` delegates this prefix to
  `rafii_control.hosted.embedded_app(os.environ, self._runtime)` (`src/rafii_control/hosted.py:113`) **before** any consumer bearer /
  request guard. Active only when `RAFII_CONTROL_MOUNT=embedded` (else 404 closed app) and `RAFII_CONTROL_ENABLED=1`. Separate project
  `vercel.control.json` + `api/control.py` (`ops.` origin) also exists.
- Main `vercel.json` rewrites `/api/(.*)` → `postriff_api` (Python `api/index.py`, `maxDuration 300`). Founder pages are
  `web/src/app/founder/**` in the main Next app; `web/src/proxy.ts:15-41 founderGate` redirects `/founder/*` without the
  `__Host-rafii-control` cookie to `/founder/sign-in` (cookie validity is decided by the API).
- **Auth chain:** `src/rafii_control/auth.py`
  - `COOKIE='__Host-rafii-control'` :16; capabilities allowlist `CAPABILITIES` :17-22.
  - `Boundary.exchange(upstream_token, origin)` :175 — `POST /api/control/v2/session/exchange` with header `X-Control-Exchange: 1`,
    `Authorization: Bearer <Supabase access token>`, `Origin ∈ allowed_origins` (`http.py:105-110`). Requires operator row
    (`rafii_control.platform_operators`, role `founder`, status `active`; `store.py:46-48`), `aal == 'aal2'` **and** MFA
    timestamp ≤300 s old (`fresh_mfa` :127: `totp|mfa/totp|mfa/phone|mfa/webauthn`), upstream session active. Issues opaque
    token (sha256 stored in `rafii_control.founder_sessions`), `Set-Cookie ... Secure; HttpOnly; Path=/; SameSite=Strict; Max-Age=28800`.
  - `Boundary.authorize(token, capability, *, origin, csrf, unsafe, step_up, ..., purpose)` :198 — session not revoked/expired,
    idle < 1800 s, environment + `auth_epoch` match, `assurance=='aal2'`, capability ∈ operator capabilities; **non-GET requires
    Origin ∈ allowed origins and `X-CSRF-Token == HMAC(token,'rafii-control-v2-csrf')`** (:215); `step_up` = MFA ≤300 s; per-minute
    budget `store.budget(purpose, user, BUDGETS.get(purpose, 300))` (`BUDGETS` :28: `copilot.use 5, metrics.query 240,
    founder.agent.turn 20, founder.call.request 5, founder.action 10, founder.voice 5, founder.export 10`); writes
    `rafii_control.admin_audit_log` per request.
  - Embedded host check: `X-Forwarded-Host` must be in `RAFII_CONTROL_ORIGINS` (`http.py:84, 173-178`).
- **Dispatcher:** `src/rafii_control/http.py:51 ControlApplication.__call__` — JSON only, `CONTENT_LENGTH ≤ 32768` (:99),
  `Content-Type: application/json` for non-GET, single JSON response envelope `{requestId, environment, asOf, dataState,
  receiptIds, data}` (:142-143); `deadline_seconds` :66 → 270 s for `/agent/*`, 30 s `/overview`, 10 s otherwise.
- **Extension seam for new founder routes:** `http.register_route(method, pattern, capability, module, function, *, step_up,
  budget, demo_ok)` :26 (methods GET/POST/PUT/DELETE; capability must be in `CAPABILITIES`; full-match regex). Handler signature
  `module.function(app, principal, request)` with `request = {method, path, body, query, match, mode, now, requestId, environ}`
  (:20-22, :255). Routes under `/agent/` are founder routes (`FOUNDER_PREFIXES` :18). Data mode only via `?mode=demo|live`
  (`query_mode` :192); non-GET in demo refused unless `demo_ok`.
- Existing founder agent routes (`http.py:273-281`, capability `copilot.use` for POST `/agent/turns`, GET `/agent/runs/{id}`,
  POST `/agent/runs/{id}/cancel`, GET `/agent/conversations/{id}/state`; budget purpose `founder.agent.turn` for POST `/agent/*`
  via `budget_purpose` :181-185). `/agent/turns` requires `Idempotency-Key` header equal to `body.idempotencyKey`
  (`[A-Za-z0-9:_-]{8,200}`, :274-276).
- **Recommended founder OpenUI mapping:** `/api/control/v2/agent/ui/{presentations, presentations/{id}, presentations/{id}/events,
  presentations/{id}/cancel, presentations/{id}/edits, presentations/{id}/state, queries}` registered through `register_route`
  with capability `copilot.use`, handlers calling `founder_agent.require_founder(principal)` (:86 — requires `copilot.use,
  control.read, metrics.query`, role founder, AAL2, live session). No `actions/activate`/`actions` route in v1 founder manifest
  (read-only). Never accept a client `isFounder`; founder scope is only `ctx.extra['founder']` set server-side.

### 3.2 Founder agent runtime (verified)

`src/rafii_control/founder_agent.py`:
- `turn(service, control_principal, body, request_id, *, control, values, base, model_factory)` :699 → `validate_turn(body)` :235
  (strict keys `message, mode` + optional `conversationId, idempotencyKey, modality(text|voice), timeZone, locale, pageContext`;
  `MAX_MESSAGE=4000`), `_prepare` :668 (`require_founder`, `_resolve_ops` :655 → env `RAFII_FOUNDER_OPS_WORKSPACE_ID` or
  `rafii_control.founder_settings.ops_workspace_id`; 409 `POLICY_DISABLED` blocker `ops_workspace_not_configured`), `founder_scope_for` :352,
  `founder_runtime` :298 (→ `scoped_service` :284 using `automation_runs.principal_repository(service, ops, operator, "edit")`
  `automation_runs.py:38`), `FounderAgentRuntime(AgentRuntimeService)` :366 (no site-agent fallback `_fallback` :391; founder
  Manager `_run_manager` :422 with `RafiiRunContext.extra={"founder": ...}`, `max_turns=12`, `TURN_BUDGET_SECONDS`), `_persist` :482
  adds `result["founder"] = founder_section(...)` and `founder_blocks(section)` (receipts/drafts result_lists).
- Idempotency / namespaces: runtime key `founder:<mode>:<env>:<key>` (`runtime_key` :117; run key prefix `agent:founder:` :46);
  conversations in the ops workspace titled `[founder:<mode>:<env>] ...` (`conversation_title` :135, `namespace_of_title` :140,
  `check_conversation` :415). Reservations tagged `{"costCenter":"founder_ops"}` (`founder_reservation_approval` :278).
- `run` :737, `cancel` :757, `conversation_state` :773 — only this operator's founder runs (`_founder_run` :727).
- Manager: `build_manager` :539/_build :557 — tools = `founder_tools.FOUNDER_TOOL_NAMES` only, `founder_prompts.instructions`,
  `output_type=founder_prompts.reply_type()`, output guardrail `answer_policy.output_guardrail()`, input guardrail
  `rafii_founder_forbidden_effects` :522 (refund/ban/delete/deploy/shell/SQL/send trip before any model call).
- Context: `assemble` :581 — page context as `APP_STATE` data; `CONTEXT_KEYS = section, route, selectedEntity, chart, period,
  filters, incidentId, outline` :51; `UI_CAPABILITIES = ("navigate","open_evidence")` :53; `founder_context` :158 re-validates.
- Result section `founder_section` :610: `{version, mode, environment, namespace, composedBy, receiptIds, receipts[≤20],
  facts:[{text, receiptId, kind:"stored"}] (only receipts produced this turn; others counted in factsDropped), hypotheses[],
  recommendations:[{text, metric, period, success}], unknowns[], links[], drafts[≤6]}`.
- Audit: `_audit_turn` :676 → `admin_audit_log` action `founder.agent.turn`.

### 3.3 Founder tool manifest (verified, `src/rafii_control/founder_tools.py`)

All `ToolSpec(..., tenant=FOUNDER_TENANT)`; `FOUNDER_TOOL_NAMES` :39-41:

| Tool (line) | Effect / perm | Use in OpenUI founder manifest |
|---|---|---|
| `founder_metric_query` :374 | READ | yes — via `_metric_query` :316 → `QueryService.metric_query(query, principal, request_id, mode, demo_data)` (`intelligence.py:150`); every call writes a receipt in `rafii_control.query_receipts`. |
| `founder_chart_explain` :395 | READ | yes |
| `founder_entity_lookup` :457, `founder_entity_search` :528 | READ | yes (field allowlist `SAFE_FIELDS` :53; no emails/messages/cards) |
| `founder_attention_list` :573 | READ | yes |
| `founder_cost_breakdown` :638 | READ | yes; `dimension ∈ feature|model|plan|workspace|provider`, but `workspace` returns `dimension_not_instrumented` (:641-643); metrics `ai_cost_by_feature` / `ai_cost_actual`. |
| `founder_incident_read` :681, `founder_source_health` :688 | READ | yes |
| `founder_navigate` :906 | READ | yes (links only inside `/founder`) |
| `founder_draft_message` :719 | CREATE_DRAFT, edit (text only, stores nothing) | presentation only; no send |
| `founder_reminder_prepare` :831, `founder_report_prepare` :858 | PREPARE_EXTERNAL, approval | native confirm only |
| `founder_incident_ack` :875 | MUTATE_REVERSIBLE (only mutation) | **exclude** — native Operations page |

Privileged native controls (keep native, step-up, preview→confirm): `founder_actions.py:900-928` (`/usage/reconcile/*`,
`/actions/credits/*`, `/actions/accounts/{id}/(un)block/*`, `/actions/refunds/*`), `founder_support.py:88-89` (reply/status/reveal),
`founder_policy.py:137`, `founder_ops.py:191`.

### 3.4 Founder read models (verified)

Metric catalog: `src/rafii_control/pack/catalogs/metrics.json` (83 rows: 63 `proposed_definition_not_activated`, 20 `activated_v1`)
+ `metrics.d/{ai,ops,product,revenue}.json` (all `activated_v1`), loaded by `intelligence.Catalog` :40-82 (schema enum
extended from catalog :68-75). Proposed ids answer `dataState='unavailable', reason='definition_not_activated'` (`intelligence.py:163-165`)
— i.e. **absent metrics are already "unavailable", never zero**. Activated in metrics.d: revenue `mrr, delinquent_mrr,
mrr_movements, logo_churn, credit_grants, credit_consumption, credit_available, mrr_forecast, cash_collected`; ai `ai_calls, ai_tokens,
ai_latency, ai_fallback_retry_rate, ai_cost_per_call, cost_per_useful_outcome, ai_cost_forecast`; ops `api_error_rate, api_latency,
queue_health, connection_health, publish_by_provider, slo_burn, support_aging`; product `activation_funnel, time_to_value,
feature_adoption, retention_weekly, time_back, retention_correlations`. Query rules (`Catalog.validate_query` :84): ≤366-day
interval, allowed dimensions per metric, one grain, `currency` groupBy mandatory for native-currency metrics, `metricIds` 1–6.
MRR semantics (`founder_metrics_revenue.py:1-27`): normalized by interval (annual/12, quarterly/3, weekly 52/12, daily 365/12);
paid subscription without a priced event → `coverage.unknown` (never list price); never summed across currencies.

Views (reader role `rafii_control_reader`, projections via `rafii_control_business_projection`; all `security_barrier`):
- 054: `business_subscriptions_v2, business_payments_v2, business_usage_v2, business_refunds, business_disputes, business_agent_runs,
  business_phone_calls, ...`; tables `founder_follow_ups, workspace_classifications`.
- 055/067/068/070: `founder_incidents(+_events,_acks)`, `founder_briefing_schedules/_occurrences`, `founder_contact_policy/_attempts`,
  `founder_reports`, `founder_notices`, `founder_notification_preferences`, `founder_action_requests`, `founder_settings`.
- 057–060 (public, service_only): `pr_invoices, pr_subscription_events, pr_ai_call_events, pr_ai_call_settlements, pr_price_versions,
  pr_usage_rollups, pr_learning_daily_rollups, pr_connection_health, pr_operational_snapshots`.
- 063 revenue: `business_subscription_events` (eventType, interval, intervalCount, unitAmountMinor, currency, discount...),
  `business_invoices`, `business_subscription_snapshots_v2` (mrrMinor, interval), `business_credit_entries`.
- 064 AI: `business_ai_calls` (feature, workload, provider, model, status, tokens, ...), `business_usage_rollups` (day, feature,
  model, provider, estimatedUsdMicro, unknown, tokensUnreported...), `business_price_versions`.
- 065 product: `business_product_events, business_learning_events, business_learning_rollups, business_workspace_starts,
  business_channel_audit`.
- 066 ops: `business_request_metrics, business_operational_snapshots, business_connection_health`.
- 068: `business_account_blocks`. 088: `business_product_observations, business_telemetry_health, business_support_tickets`
  (identityVisibility `masked`).
Reliability/support routes: `GET /support/tickets` (`founder_support.py:23 list_tickets(app, principal, request)`, `customers.read`),
`GET /incidents`, `GET /usage/unknown`, `GET /overview?mode=` (`live_metrics.overview` :630), `GET /revenue/movements|invoices`,
`GET /customers/risk`, `GET /product/funnel/stuck`, `GET /metrics/receipts/{id}`.

### 3.5 Founder frontend (verified)

- Client `web/src/lib/founder/api.ts`: `FOUNDER_API_BASE='/api/control/v2'` :38, CSRF from `GET /session` (:157-173), `credentials:
  'same-origin'`, `agentTurn` :240 (sends `Idempotency-Key`), `agentRun` :241, `conversationState`, `cancelRun`, `metricsQuery` :204,
  `founderKeys` :267-279 (React Query keys partitioned by mode+environment).
- Agent UI: `web/src/features/founder/agent/{chat.tsx, answer.tsx, panel.tsx, store.ts, voice.tsx, voice-api.ts}`;
  `FounderAnswer({response, actions})` `answer.tsx:185` renders `result.blocks` via site-agent `RichText` and `response.founder`.
  Polls `GET /agent/runs/{id}` every 1500 ms (`chat.tsx:33-34`). Founder voice uses `founder:` workspace keys (`voice-api.ts:149`).
- **[GAP — contract drift, I-high]** FE type `FounderAgentTurnResponse.founder` is top-level and `FounderAgentSection.facts: string[]`
  (`web/src/lib/founder/types.ts:388-408`), but the backend puts the section at `data.result.founder` with
  `facts:[{text, receiptId, kind}]` and `recommendations:[{text,metric,...}]` (`founder_agent.py:633-637`). Unless another layer
  maps it (none found by grep), `FounderSectionView` never renders and only `founder_blocks` result-lists show. F/E must read
  `result.founder` and render objects; verify on staging before relying on it.

### 3.6 How founder scope is kept out of consumer chat (verified) — and the holes

Verified guards:
1. Founder tools are `tenant='founder'`; `tool_adapter.tenant_mismatch` :85-93 blocks founder tools in workspace turns and workspace
   tools in founder turns; `founder_scope(ctx)` :73 only reads `ctx.extra['founder']` which only `founder_agent` sets.
2. Consumer Manager tool list is explicit (`manager.MANAGER_TOOLS` :30-34); test
   `tests/test_agent_runtime_founder.py:109 test_customer_manager_has_no_founder_tools_and_the_founder_manager_only_founder_tools`,
   `:77`, `:129`; `tests/control/test_founder_agent.py:391, 531, 572, 594`.
3. `/api/control/v2` never accepts consumer bearer; cookie+CSRF+AAL2 only.
4. Consumer web features (`features/agent`, `site-agent`, `rafii-voice`) import nothing from `features/founder` (grep).

Holes / risks [GAP]:
- **REGISTRY is process-global:** in the embedded mount, importing `rafii_control.founder_tools` registers 13 founder tools in the same
  `REGISTRY` the consumer runtime uses. D's `ui_capabilities` must build manifests from an explicit per-journey allowlist **and**
  filter `spec.tenant` ('workspace' for consumer, 'founder' for founder), never by iterating `REGISTRY`.
- **Ops workspace is a normal consumer workspace:** the founder is an active `owner` in `public.pr_memberships` for the ops workspace
  (`founder_ops.py:162-165`; bootstrap ordering `069_founder_ops_bootstrap.sql`). Consumer routes (`GET /api/workspaces/{ops}/agent/runs/{id}`,
  conversations) authenticated with an AAL1 Supabase bearer can therefore read stored founder runs (`result.founder` receipts) —
  no consumer-side filter on `[founder:` titles or `agent:founder:` run keys was found. For OpenUI, F's store and D's consumer
  query/replay routes must refuse artifacts whose parent run key starts with `agent:founder:` (or a stored `scope='founder'`),
  and the founder routes must refuse non-founder artifacts.

### 3.7 J09 constraints for the founder transport [GAP]

- Control responses are one JSON body; no SSE in `ControlApplication.__call__` (:169-170). Founder streaming needs either an A-owned
  streaming branch in the control dispatcher or a poll/replay mode (`GET .../events?after=`) — decide explicitly.
- Control body limit 32,768 bytes (`http.py:99`) < contract patch bound (32 KiB source + JSON escaping). Founder edits must cap
  `patchSource` lower (≈24 KiB) or A raises the limit for that one route.
- Default budget for POST `/agent/*` is `founder.agent.turn` = 20/min; `queries` route must set `budget='metrics.query'` (240/min) or the
  contract's 60/min admission cannot be met; presentations/edits keep `founder.agent.turn`.
- Demo vs Live must be part of artifact scope (`namespace founder:<mode>:<env>`); never mix.

---

## 4. Test inventory relevant to J07–J09 (verified file names)

Python: `tests/test_postriff_research.py`, `tests/test_postriff_automation_research.py`, `tests/test_postriff_automation_chat.py`,
`tests/test_postriff_campaigns.py`, `tests/test_site_agent.py`, `tests/test_agent_runtime.py`, `tests/test_agent_runtime_founder.py`,
`tests/control/test_founder_agent.py` (+ `_pg` suites: `test_founder_revenue_pg.py`, `test_founder_ai_pg.py`, `test_founder_ops_pg.py`,
`test_founder_product_pg.py`, `test_live_metrics_pg.py`), `tests/control/test_embedded_mount.py`, `tests/control/test_boundary.py`.
Web: `web/tests/founder-*.test.cjs`, `founder-browser.cjs`, `founder-sign-in-browser.cjs`, `rafii-automations.cjs`,
`rafii-guide*.cjs`, `channel-list.test.cjs`. CI workflows present: `.github/workflows/{rafii-control.yml, founder-browser.yml,
rafii-browser.yml, consumer-ready.yml, ...}`.

## 5. Not verified here

Production env values (`RAFII_CONTROL_MOUNT`, `RAFII_CONTROL_ENABLED`, `RAFII_CONTROL_ORIGINS` containing `https://rafii.io`,
`RAFII_FOUNDER_OPS_WORKSPACE_ID`, `POSTRIFF_RESEARCH`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_NOTIFICATIONS_V2_ENABLED`), whether Vercel
Python flushes WSGI iterables incrementally, and whether migrations 054–088 are applied in production. Memory notes say Founder
Admin v2 activation was pending as of 2026-10-01; treat founder production readiness as unverified.
