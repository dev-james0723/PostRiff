# R0 map: runtime core (lanes B and F reuse)

Reader: role A R0 baseline (read-only). Source: worktree `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`, HEAD `3da806f0` (branch `claude/rafii-openui-production-20261008`). Mapped 2026-10-08.

Method: `rg`/`sed`/`cat` only. No builds, no tests, no installs, no model calls, no DB access. The Agents SDK is not installed on this Mac (`python3 -c "import agents"` fails), so SDK internals are **not verified locally**.

Labels: **[CODE]** means verified in source at this SHA, with file:line. **[INFER]** means my inference; it needs a probe. **[GAP]** means it is missing or a risk.

Paths are relative to the repo root. `ARV2` = `src/postriff_phase2/agent_runtime_v2/`.

---

## 0. Ten facts that drive the design

1. **[CODE]** A turn is one **synchronous, blocking** `POST /api/workspaces/{w}/agent/turns` that returns status 201 with JSON when the turn finishes. The Manager runs through `asyncio.run(manager_mod.drive(ctx, Runner.run(...), 240))` (`ARV2/service.py:491`). Nothing streams to the browser. The browser polls `GET runs/{run}/events?cursor=` every 400 ms for progress (`web/src/lib/agent-runtime/use-thinking-state.ts:55-67`).
2. **[CODE]** `Runner.run_streamed` is used **nowhere** in `src/`. `MeteredModel.stream_response` exists (`ARV2/manager.py:191-195`). It **increments `model_requests` but records no span, tokens, cost or failure**. If B routes a stream through it as-is, usage goes unmetered. **[GAP]**
3. **[CODE]** Hidden retries are off where the Agents SDK uses OpenAI clients: `AsyncOpenAI(..., max_retries=0, timeout=90)` (`ARV2/manager.py:134`). Phone does the same (`phone/asgi.py:99,233`, `phone/code_speech.py:76`). Follow-up chips use a urllib transport with no retry (`ARV2/creative.py:57-76`). No test asserts `max_retries=0` for the agent runtime client. Phone tests do assert it. **[GAP]** G/B should add that test. Whether openai-agents 0.22.3 adds a retry layer of its own is **[INFER] unverified**; probe it in cloud CI.
4. **[CODE]** Every `repository.transaction(token, w)` makes a **Supabase `getUser` HTTPS call (no cache)** and takes **`FOR UPDATE OF w` on the workspace row** (`src/postriff_phase2/hosted.py:113-143`, SQL at line 119; verifier at `hosted_app.py:50-100`, `provider_candidates.py:239-245`). Every `ideas._insert_event` also takes the workspace row lock plus a per-run advisory lock (`ideas.py:933-951`). Writing per-delta events through these paths would serialize the whole workspace and call Supabase once per chunk.
5. **[CODE]** The event table `pr_agent_events` has a **CHECK constraint on `kind`** that allows only the 11 SAFE_EVENTS (`migrations/postriff/005_consumer_web_ideas.sql:58-66`; `agent_runtime.py:14,50-58`). Workspace members can read it through RLS `tenant_read` (005:86-97). It is capped at 2000 events per run (`ideas.py:33`). The `ui.*` kinds and raw source deltas cannot go there. A new private table is required.
6. **[CODE]** Each Manager turn reserves exactly once, before any model call: `ledger.reserve(..., "text_model", estimate(24_000 in, 4_000 out), f"agent:{run_id}", charge_batch=False, run_id=run_id, credit_authority=...)` (`service.py:658-667`). Settlement happens exactly once in `_finalize` (`service.py:837-838`) or in `_abort_run` (943-950). If the cost is unknown, settlement uses `"unknown"` and the hold is kept (`billing.py:294-299`). Settlement is idempotent and terminal (`billing.py:278-293`).
7. **[CODE]** The turn's reservation is **already settled** when `turn()` returns. A presenter that starts afterwards cannot spend from it. It needs its own reservation, plus an explicit check against the turn-level ceiling (see D2).
8. **[CODE]** In credit-mode workspaces (`POSTRIFF_CREDITS_ENABLED=1` and an active `creditPolicy`), `CreditBook.prepare` raises 402 when `credit_authority` is None (`credit_wallet.py:143-147`). Text Manager turns always pass `None` (`service.py:670-673`; only phone and founder set `reservation_approval`). So credit-mode text turns **fall back to the site agent with reason `budget`** (`service.py:430-433`). A presenter reservation would be refused the same way. **[GAP]** The production value of that flag has not been checked.
9. **[CODE]** API routing: `vercel.json` sends `/api/(.*)` to the Python WSGI service `postriff_api` (`api/index.py`, `maxDuration: 300`). A precedent for a separate ASGI service exists: `rafii_phone_media` (Starlette, `api/phone.py` → `phone/asgi.py:17-48`) with path-specific rewrites. WSGI `_json` always sets `Content-Length` (`hosted_app.py:276-284`). The only "SSE" (Ideas `runs/{id}/events`) is a buffered replay that then closes (`hosted_app.py:381-394`). No Next.js `route.ts` exists under `web/src/app`.
10. **[CODE]** Proposals live **inside the assistant message JSON** (`pr_messages.body.siteAgent.proposals[]`). They have a 24 h TTL (`site_agent/proposals.py:22`) and a digest over fixed fields (`proposals.py:42-50`). They are checked at apply time and again inside the command transaction (`site_agent/service.py:1082-1144`). The only apply/dismiss authority is `approvals.decide(...)` → `site_agent.apply_proposal` / `dismiss_proposal`. Over HTTP that is `POST agent/approvals/decide` (`ARV2/http.py:73-74` → `service.py:1187-1202`).

---

## 1. `AgentRuntimeService.turn()`, end to end (`ARV2/service.py`)

Constants (34-52): `KEY_PREFIX="agent:"`, `AGENT_MODEL="rafii-agent"`, `MAX_MESSAGE=4000`, `MAX_ATTACHMENTS=4`, `TURN_BUDGET_SECONDS=240`, `SUPERSEDE_WINDOW_SECONDS=180`, `STALE_TURN_SECONDS=600`, `HISTORY_MESSAGES=12`, `RUNTIME_VERSION="agent-runtime-1"`, `TRACE_HOOKS` with `register_trace_hook(fn)` (46-51), `EPOCH=digest({"runtime": RUNTIME_VERSION})`.

The class `AgentRuntimeService(service, cfg=None, *, model_factory=None, image_studio=None, vision=None, live_transport=None, clock=None)` is at lines 60-72. It is built once per process in `ARV2/http.py:23-43 runtime_for(service)`, which uses the harness only when `RAFII_AGENT_HARNESS=1` and refuses that on Vercel (`harness.py:23-28`).

`turn(workspace_id, token, payload) -> dict` (89-138):

1. **Payload parsing.**
   - `message` is cleaned to 4000 characters.
   - `modality` is one of `text|voice|image`.
   - `references` are validated by `turn_references.parse`, which returns 400 on bad shape.
   - `attachments` hold at most 4 items of `{assetId, role: post|reference}`.
   - The idempotency key is `payload.idempotencyKey` (100 chars) or `uid()`. Then `run_key = "agent:" + key`.
   - `pageContext` goes through `site_agent.contracts.page_context`; `timeZone` through `intent.safe_zone`.
   - `traceId` must match `^trace_[0-9a-f]{32}$` (`contracts.py:33-43`); otherwise a new one is generated.
2. **Admission transaction** (109-123): `require(member,"read")`.
   - **Idempotent replay:** if a `pr_agent_runs` row exists for `(workspace_id, idempotency_key=run_key)`, it returns `_stored(...)` with no model call (112-115).
   - It validates `conversationId` through `ideas._conversation` (404 if foreign).
   - It runs `_attach` (188-210). That requires `edit`, a ready asset in this workspace, and records `attachment_rows`. The `readable` flag is set only if `media_consent.allowed(state, processor(vision.provider, vision.model))`.
   - It runs `_front_door` (141-168).
3. **Front door** returns one `mode`:
   - `choose`, `cancel`, `confirm`, `reject`. Binding goes through `approvals.bind`.
   - `fallback`, with reason `runtime_off` (`RAFII_AGENT_V2_ENABLED` off), `role_grounded` (no `edit`), `no_model_route`, or `forbidden`/`greeting` from the classifier.
   - `manager`.
4. `fallback` runs `_fallback` (219-240), which calls `SiteAgentService.turn` and wraps it into `contracts.empty_result` with `composedBy:"site_agent"`.
5. If there is no conversation yet, `_new_conversation` (212-216) inserts into `pr_conversations`, then attachments are re-attached.
6. `confirm|reject|choose` → `_decide_turn` (243-324). `cancel` → `_cancel_turn` (336-378). Slash commands → `commands.direct(...)` (135-137, `ARV2/commands.py`).
7. Otherwise `_manager_turn` (419-440):
   - `_supersede` runs for voice or `payload.supersede` (531-543).
   - `config.choose_reasoning` picks `vision`, `deep_reasoning` or `standard_reasoning` (`config.py:191-201`).
   - `_open_run(..., model=AGENT_MODEL, reserve_for=workload, delegation_id, live_session)`. An `AlphaError` with status 402/403/409/429/503 (other than `workspace_revision_conflict`) leads to `_fallback(reason="budget")`. That path makes no model call and uses no other paid route.
   - Any later exception goes to `_abort_run` (929-958). The run always ends settled and closed.
8. `_run_manager` (442-529):
   - One read transaction gathers focus/references (`_resolve` 557-579), chips, the active task (with `_sync_task`), conversation images, open proposals, history (581-592, 12 messages, 1200 chars each), the recent voice transcript and the style.
   - It builds `RafiiRunContext` (`ARV2/context.py:86-189`) with `cancelled` = a DB status check, `deadline = monotonic()+240` and `thinking_emit`.
   - `_assemble` (594-630) builds input items: history plus one user item with `<context kind="APP_STATE">` (escaped JSON) and `<request kind="USER_INSTRUCTION">`.
   - `manager_mod.build(ctx, model_factory, workload)` returns `(Agent, routes)`.
   - `RunConfig(workflow_name="rafii.turn", trace_id, group_id=conversation_id, trace_include_sensitive_data=False)`.
   - `Runner.run(manager, items, context=ctx, max_turns=14, run_config=...)` inside `drive(...)`. `drive` = `asyncio.wait_for` plus closing every provider client in the same event loop (`manager.py:154-160`).
   - If there are interruptions, `result.to_state().to_json(context_serializer=...)` stores ids only, never the token (492-505).
   - Exceptions map to `fallback_reason`: `guardrail_output`, `guardrail_input`, `max_turns`, `timeout`, an AlphaError code (`run_cancelled`), or `model_error` (508-525).
9. `_finalize` (765-860) assembles the result through **`contracts.empty_result(trace_id, modality)`** (`contracts.py:93-115`):
   - It runs `answer_policy.check(answer, ledger)`. If the reply is rejected or missing, it falls back to the deterministic `answer_policy.compose(ledger, task, note)`.
   - **Blocks** come from the site-agent `BLOCK_TYPES` (`site_agent/contracts.py:24-25`), in this order: `text(answer)`, `proposal_diff` per `ledger.proposals` via `site_proposals.view`, `result_list("Steps")`, `evidence_blocks` (1241-1263; at most 6, from `EVIDENCE_INTENTS` 1235-1237), `ledger.client_blocks()`, `citations`, warnings, and an `agent_{reason}` warning.
   - Follow-up chips (`_manager_follow_ups` 714-732) run only if the Manager offered fewer than 2. They are paid from the **room left in the same reservation** (`estimateUsdMicro - spent`), which is the precedent for "a sub-call fits inside the turn ceiling".
   - Result fields: `answerText`, `speakableSummary`, `composedBy`, `references[:20]`, `citations[:4]`, `facts[:20]`, `toolActivity[:40]`, `task`, `changedEntities[:20]`, `generatedAssets[:8]`, `warnings[:6]`, `errors[:6]`, `routes`, `usage{modelRequests, inputTokens, outputTokens, costUsdMicro, route, billing}`, `followUps`, `language`, `blocks`.
   - One transaction (834-860) then does: the final status (`cancelled` if the DB says so, otherwise `completed`); `ledger.settle(reservation, "completed" if cost is known else "unknown", cost)`; `record_calls(cur, ctx, reservation)` into `pr_ai_call_events`; the task save; `_store_pending_run`; and `_persist`.
10. `_persist` (862-897):
    - It appends **one assistant `pr_messages` row** with body `{text, runId, siteAgent:{version, runId, status, intent:"agent", language, blocks, citations, grounding, proposals, context, model, followUps, feedback, refs, pending?, presents?}, agent: visibleResult}`. The visible result has `costUsdMicro` stripped (878).
    - It patches `body.agent.pendingApprovals` with `messageId` (881-884).
    - It inserts events: `artifact.created{artifact:"site_agent.block", block}` (≤10), `action.proposed`, `message.completed{text≤12000}`, and `run.completed{usage}` / `run.failed` / `run.cancelled`.
    - It updates `pr_agent_runs` with `status`, `artifact={version:1,result,trace}`, `artifact_hash=digest(artifact)` and `usage`.
11. `_stored(cur, w, run_id)` (899-908) returns `{conversationId, runId, status, messageId (latest assistant message for the run), result: artifact.result, traceId}`. It is used for replays and `GET runs/{run}`.

`_spend(ledger, default_model)` (910-927) gives total micro-USD. It skips image calls, which have their own reservations. Any call in `ledger.calls` without an integer `cost_usd_micro`, or any span with an unpriced model, makes the total `None` (unknown, never zero).

`_reap_stale_turns(cur, w)` (960-986) runs in `_open_run` in its own transaction. For `agent:` runs that are cancelled and older than 600 s with an unsettled reserve, it settles `unknown`. For `agent:` runs still `running` and older than 600 s, it settles every open reserve for that `run_id` as `unknown` and persists `failed` (`turn_stalled`).

**Exact reuse points for B and F:**
- The parent run id, conversation id and message id are known only after `_persist`. For a fresh turn they come back in the `turn()` response (`runId`, `messageId`, `conversationId`).
- The safe extension seam in `_finalize` is `TRACE_HOOKS` (trace-only). There is **no hook to add a `ui` section to `result`**. A must add a small seam in `service.py`, which A owns: `result["ui"]` built from the projection, persisted in the same `_persist` transaction.

---

## 2. Persistence: tables and repository code

| Table | DDL | Key columns | Written by |
|---|---|---|---|
| `pr_conversations` | `migrations/postriff/005_consumer_web_ideas.sql:5-13` (also `hosted-004-008.sql:125`) | `id uuid`, `workspace_id`, `created_by`, `title≤200`, `archived_at` | `service._new_conversation` (212); founder namespaced titles (`rafii_control/founder_agent.py:113-145`) |
| `pr_messages` | 005:16-27 | `id uuid`, `conversation_id`, `workspace_id`, `seq` (unique per conversation), `role user/assistant/system`, `body jsonb`, `run_id` | `ideas._append_message(cur,w,c,role,body,run_id)` (`ideas.py:710-716`, seq = max+1) |
| `pr_attachments` | 005:29-38 | kind `source/asset/link`, `ref jsonb` | `attachment_rows.record` |
| `pr_agent_runs` | 005:40-56; reasoning check altered in 017 | `id`, `conversation_id`, `workspace_id`, `actor`, `status` (`running/completed/failed/cancelled/applied`), `model`, `reasoning` (`quick/standard/deep`), `context_digest(64)`, `policy_epoch(64)`, `idempotency_key` **unique per workspace**, `artifact jsonb`, `artifact_hash`, `usage jsonb` | `_open_run` (649-652), `_persist` (896), `cancel` (402) |
| `pr_agent_events` | 005:58-66 | PK `(run_id, seq)`, `kind` **CHECK in 11 SAFE kinds**, `body jsonb`, `at` | `ideas._insert_event` (941-951); limit `MAX_EVENTS=2000` (`ideas.py:33`) |
| `pr_usage_ledger` | `007_consumer_web_billing.sql:56-77` | `kind reserve/settle/release/adjust`, `dimension text_model/image_generation/tool/storage/action`, `estimated_usd_micro`, `actual_usd_micro`, `cost_state estimated/actual/estimated_unknown/released`, `run_id`, `reservation_id`, `idempotency_key` **unique per workspace**, `meta` | `billing.Ledger.reserve/settle` |
| `pr_ai_call_events` | `058_founder_ai_usage.sql:18-52` | one row per physical attempt; `feature` regex `^[a-z][a-z0-9_]{0,39}$`; `dedupe_key` unique; `cost_source` gateway/provider/unknown/`table:<v>`; `(cost NULL) = (source unknown)` | `manager.record_calls` / `record_span` → `ai_call_events.write_attempts` (`ai_call_events.py:279-301`) |
| `pr_credit_quotes` | `020_credit_quotes.sql:4-17` | `request_digest`, `workspace_revision`, `model`, `provider`, `max_millicredits`, `expires_at`, `reservation_id` | `CreditBook.issue/claim` |

RLS for conversations, messages, runs and events: `tenant_read` for `authenticated` via `postriff_private.member(workspace_id)`, plus `trusted_write` for service_role (005:86-97). Conversations are workspace-shared. `ideas._conversation` checks only workspace scope, not the creator (`ideas.py:703-708`). Cancel is limited to the actor (`service.py:383-385, 394-398`).

Run kinds share `pr_agent_runs` by **idempotency-key prefix**: `agent:` (turns), `task:` (task plans, `task_state.py:22`), `voice:` (Live sessions), `site:` (site agent), plus writer runs (`run:` in the ledger). Code that filters by prefix:
- `ideas.recover_stalled`: `ideas.py:1837-1839`
- `operational_signals.py:19`
- `site_agent/member_activity.py:147`
- `service.py:383,536,966,971,1008,1133`
- `live.py:274,358,484`
- `phone/store.py:61-62`
- founder business projection grant (`054_rafii_control_founder_views.sql:13,65`)

**[GAP] Rows with a new prefix in `pr_agent_runs` (for example `ui:`) would be swept by `ideas.recover_stalled` as stalled writer runs** (settle `usage.reservationId` and insert `run.failed`), counted by `operational_signals`, and listed in member activity. Do not model presentation attempts as `pr_agent_runs` rows.

Event replay:
- `service.run_events(runtime, w, token, run_id, cursor=0)` (1143-1157) → `ideas._events_for` (`ideas.py:1815-1824`). Each event is `{id:"{runId}:{seq}", seq, type, ...body, at}`, up to 500 per call, with `cursor = last seq`. It needs `read` and does not check the actor.
- HTTP: `GET agent/runs/{run}/events?cursor=` returns JSON only (`http.py:64-65`).
- The Ideas route variant honours `Last-Event-ID` in the form `{run}:{seq}` and sends buffered `text/event-stream` (`hosted_app.py:381-394`). That is the id convention to reuse: the contract's `{artifactId}:{seq}` matches it.

Progress ("thinking"):
- `thinking_state.event(op, source, reason_code)` → `safe_event("progress.updated", stage="agent_state", thinkingOp, thinkingSource, reasonCode)` (`ARV2/thinking_state.py`). It uses fixed enums only, with at most 32 per run (`context.py:169-183`).
- It is emitted only while the run is `running` (`service._emit_thinking` 411-416).
- It is gated by `RAFII_AGENT_THINKING_STATES_ENABLED`.

---

## 3. Cancel, `active_run`, tasks, HITL resume

- `AgentRuntimeService.cancel(w, token, run_id)` (391-403): needs `edit`, actor only, `agent:` runs only, and returns 404 otherwise. It inserts `run.cancelled` and sets `status='cancelled'`. The Manager observes this cooperatively: `ctx.check_cancelled()` runs before every non-READ tool (`context.py:151-153`, `tool_adapter.py:117-118`), and `ctx.cancelled` = `_is_cancelled` is a DB read (545-547). **[INFER]** An in-flight provider call is **not** aborted. Cancel takes effect at the next tool boundary.
- `cancel_running(w, token, conversation_id, *, reason, exclude=None, only=None)` (380-389) applies to the member's own running `agent:` runs in a conversation.
- `active_run(runtime, w, token, conversation_id)` (1125-1140) returns the latest running `agent:` run as `{runId, status, startedAt}` or None. HTTP: `GET agent/conversations/{c}/active-run`.
- Tasks:
  - `task_state.TaskPlan` (`task_state.py:32-183`) is stored as a `pr_agent_runs` row keyed `task:<uuid>`, with `artifact.task`.
  - Step changes become `progress.updated{stage:"task_step"}` events.
  - API: `active(cur,w,c)`, `latest`, `load(cur,w,task_id,lock)`, `create(...)`, `save(cur, ideas, w, plan, trace_id)`.
  - Only the tool that did the work may set `done` (`contracts.TOOL_ONLY_STEP_STATES`).
  - HTTP: `GET agent/tasks/{task}?cursor=` (`task_view` 1160-1170) and `GET agent/conversations/{c}/state` (`conversation_task` 1173-1184).
- SDK HITL (ADR-H1):
  - `_store_pending_run` (989-1003) saves `artifact.pendingRun{state, proposalIds, storedAt, writerModel}` on the task row.
  - `_claim_pending_run` (1005-1016) pops it after a verified apply.
  - `_resume_pending_run` (1018-1096) uses `RunState.from_json(manager, state, context_override=ctx)`, approves only `proposal_apply` with a matching `proposalId`, rejects everything else, and runs `Runner.run(..., max_turns=8)`. It makes its **own reservation**, `agent-resume:{run_id}`.

---

## 4. Approvals lifecycle (digest, expiry, decide)

- Binding by conversation (`ARV2/approvals.py`):
  - `is_confirmation`/`is_rejection`/`is_cancel_request` are regexes for EN, Cantonese and Mandarin, at most 60 characters (21-41).
  - `open_proposals(cur,w,c,now)` (52-62) scans the last 40 assistant messages for `status=="proposed"` and `expiresAt>now`.
  - `find` (65-70).
  - `bind` (73-98) binds only to exactly one open proposal presented in the latest answer within `BIND_WINDOW_SECONDS=600`, or one restated via `siteAgent.presents{proposalIds, at}`. Otherwise it returns `{ask, candidates}` or `{none}`.
- Building a proposal:
  - `site_agent/proposals.py`: `TTL_SECONDS=24*3600` (22); `STATES=("proposed","applied","dismissed","expired","superseded","failed")` (24).
  - `proposal_digest(p)` hashes the fields `type, taskId, changes, before, createdBy, variantId, variantRevision, channelId, localTime, timeZone, jobId, acknowledgedWarnings`, plus `acceptUpdate`, `confirmReview` and `media` when present (42-50).
  - `check(p, digest_value, now)` raises 409 with code `proposal_closed`, `proposal_expired` or `proposal_digest` (188-196).
  - `view(p, now)` is the browser-safe projection. It drops `createdBy` and shows expired status (237+).
- Apply:
  - `site_agent.service.apply_proposal(w, token, payload{messageId, conversationId, proposalId, digest, expectedRevision, timeZone})` (1082-1144):
    1. Permission is `approve` for `schedule_draft|reschedule_post`, otherwise `edit`. Also `edit` if `needsEdit`, and the owner check if `requiredPermission=="owner"`.
    2. `check` runs before the command and again inside `after` under `FOR UPDATE`.
    3. Then the plan gate `require_publishing`, the domain apply via `repository.command(...)` with optimistic `expectedRevision`, and the audit event.
    4. On stale/expired the stored proposal becomes `superseded`/`expired`.
  - `approvals.decide(service, w, token, *, conversation_id, message_id, proposal_id, digest, decision, zone)` (136-163) wraps that. It retries **once** on `workspace_revision_conflict` with a freshly read revision. That retry is a domain-level re-read, not a provider retry.
  - It then re-reads and runs `verify_applied(state, proposal)` (102-133) → `{outcome, verified, checks, proposal, result, revision}`.
- HTTP: `POST agent/approvals/decide` body `{conversationId, messageId, proposalId, digest, decision: apply|dismiss, timeZone?}` → `service.decide` (1187-1202). That also resolves task steps.
- **Rule for D/E/F:** every generated "approve" control must call this exact route with the stored digest. The `UiActionV1` `activationId` is an extra gate in front of it, never a replacement.

---

## 5. Model router, credentials, egress (`ARV2/config.py`)

- Flags (21): `RAFII_AGENT_V2_ENABLED`, `RAFII_VOICE_ENABLED`, `RAFII_IMAGE_AGENT_ENABLED`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_PROACTIVE_V2_ENABLED`, `RAFII_AGENT_THINKING_STATES_ENABLED`. `cfg.enabled(name)` (139).
- Model aliases (28-35), all overridable by env:

  | Env var | Default |
  |---|---|
  | `RAFII_AGENT_PRIMARY_MODEL` | `gpt-6-sol` |
  | `RAFII_AGENT_FAST_MODEL` | `gpt-6-luna` |
  | `RAFII_AGENT_VISION_MODEL` | `gpt-6-sol` |
  | `RAFII_AGENT_IMAGE_MODEL_QUALITY` | `gpt-image-2.5-sunburst` |
  | `RAFII_AGENT_IMAGE_MODEL_FAST` | `gpt-image-2.5-flare` |
  | `RAFII_LIVE_MODEL` | `gpt-live-1` |

  Do not hardcode these.
- Workloads (40): `deterministic, fast_language, standard_reasoning, deep_reasoning, vision, voice_front_end, image_fast, image_quality`. Alias map (41-49).
- Provider choice (`from_environment` 103-136):
  - `RAFII_AGENT_PROVIDER` ∈ `openai|gateway`. If unset, it is `openai` when `OPENAI_API_KEY` is set, else `gateway` when `AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN` is set, else None.
  - Base URL is `RAFII_AGENT_BASE_URL` or the default (`https://api.openai.com/v1` / `https://ai-gateway.vercel.sh/v1`).
  - **One provider serves every non-voice workload.** Voice is always `openai` (163-169).
- `cfg.route(workload, reason=...) -> Route(workload, provider, model, reason, available, blocker)` (159-172). An unconfigured route reports `available=False` and is never swapped for another paid provider. `cfg.qualified(model)` adds the `openai/` prefix for the gateway (151-156).
- Credentials: `cfg.credential(provider)` reads from a private `_env` at call time (143-149). Keys are never attributes, events or logs.
- Prices:
  - `DEFAULT_PRICES` USD/MTok `(in,out)` (53-58). Override with `RAFII_AGENT_MODEL_PRICES` (JSON).
  - `cfg.estimate_usd_micro(model, in_tok, out_tok)` returns micro-USD, or **None when unpriced, which blocks the call** (178-182).
  - Image prices: `RAFII_AGENT_IMAGE_PRICES`. Live: `DEFAULT_LIVE_USD_MICRO_PER_MINUTE`.
  - `_open_run` refuses to start (503 `price_unknown`) if `fast_language` or `vision` is available but unpriced (637-643).
- Model settings (`manager.py:113-120`):
  - Gateway: `ModelSettings(parallel_tool_calls=True, extra_args={"reasoning_effort":"none"}, include_usage=True)`.
  - OpenAI: `Reasoning(effort=high|medium|low)`, `store=False`.
- Provider model (`manager.py:126-141`): `OpenAIResponsesModel` for `openai`, `OpenAIChatCompletionsModel` for the gateway. The client is pushed onto `ctx.clients` through a ContextVar `_CLIENTS` and closed in `drive`.
- Tracing: a local `TraceCollector` keeps metadata only. Export to OpenAI is off unless `RAFII_AGENT_OPENAI_TRACING=1` and an OpenAI key is set (`manager.py:386-433`).
- **Egress classes.** `local-only` / `BYOK` / `CLI` / `cloud` belong to the **writer pipeline**, not this runtime:
  - `credit_meter.quote_task(route='managed'|'byok'|'cli')` (`credit_meter.py:24-26`) is a non-billable proposal.
  - Writer runtimes declare `provider_class` (`model_runtime.py:360` is cloud; `cli_runtime.py:207` is cloud, meaning a local CLI connected to its cloud provider). `ideas.py:254,467-468,1658` give `voice_route` = `"cloud:{provider}:{model}"` or `"local-cli"`.
  - Memory bodies reach a cloud route only if `state.memoryEgress.cloud is True`. Private, local-only, excluded and unlabelled boundaries are always withheld (`memory.py:156-185`; agent mirror `memory_layers.cloud_allowed` at `ARV2/memory_layers.py:26`).
  - Media reaches a model only if `state.mediaEgress.cloud` is true **and** the processor `provider:family` was confirmed (`media_consent.py:18-50`).
  - Writing samples need an exact-route grant (`voice_sources.project`, `memory.py:170-175`).
  - **[CODE] The Agent Runtime itself is always a cloud processor** (`memory_layers.py` docstring 15-17).
- Admission for writer-route/credits: `ideas.turn(...)` uses `credit_requests.authorize(...)` with `creditQuoteId` (`ideas.py:1297-1322`). Agent text turns do not.

---

## 6. Usage ledger, credits, call events: "settle once"

- `Ledger.reserve(cur, w, member, dimension, estimated_usd_micro:int, idempotency_key, *, charge_batch, provider, model, run_id, job_id, meta, credit_authority)` (`billing.py:169-259`):
  - **Same key returns the same row.** A different fingerprint gives 409 (178-184).
  - Checks: `ai_paused` → 503; Founder ops budget → 402; policy `requestMax` per reservation → 402; entitlement; credit policy without credits → 503; `CreditBook.prepare` (credit mode) → 402 without authority; batch/media allowances; `personDayStop` across workspaces → 402; workspace, global and global-month budgets (`pr_budgets` rows locked `FOR UPDATE`) → 402.
  - It inserts a `reserve` row with `meta` (fingerprint, budgetScopes, attribution: `actorClass`, `costCenter`, `environment`, `service`, `action=meta.via`) and increments `reserved_usd_micro`.
- `Ledger.settle(cur, w, reservation_id, outcome in completed|failed|unknown, actual_usd_micro=None, idempotency_key=None)` (`billing.py:261-313`):
  - `completed` without actual becomes `unknown`.
  - It takes an advisory lock per reservation, and **terminal states (`actual`/`released`) win**. The default key is `settle:{rid}:{outcome}`.
  - `unknown` inserts an `estimated_unknown` row once and keeps the hold.
  - `completed` → `settle`/`actual`; `failed` → `release`/`released`. Budgets are adjusted from the estimate to the actual.
  - `reconcile_unknown(...)` (325-343) needs an operator and evidence.
- Credit book: `CreditBook.prepare(cur,w,actor,estimate,model,provider,authority)` (`credit_wallet.py:143-160`) needs a quote matching the digest, model and provider. `request_digest(operation in quick-start|turn|media-notes, payload, conversation_id)` (183+). **No `agent-ui` operation exists.**
- Ledger key prefixes set the Founder feature attribution:
  - Map: `LEDGER_FEATURES` (`src/rafii_control/founder_metrics_ai.py:60-63`) and SQL `054_rafii_control_founder_views.sql:41`. A test keeps them equal (`tests/control/test_founder_ai.py:98`).
  - Existing agent prefixes: `agent`, `agent-follow-ups`, `agent-resume`, `founder`. **A new prefix like `agent-ui:` maps to `'other'`** unless both are updated.
- Provider attempts:
  - `manager.metered(...)` (163-202) appends a span per answered call: `{span, agent, workload, model, inputTokens, outputTokens, latencyMs, provider, status, startedAt, requestId?, cachedTokens?, reasoningTokens?}`. Failures go to `ledger.calls` via `_note_failure` (254-266), using the `failure_status` taxonomy (237-251).
  - `record_calls(cur, ctx, reservation)` (305-321) writes all of them under a savepoint, with `physical_attempt_id = f"{trace_id}:s{i}"` / `:c{i}` and `feature="agent"`.
  - The `dedupe_key` identity includes workspace, feature, run, reservation, workload, attempt number, physical id and request id (`ai_call_events.py:164-165`). A separate reservation id and/or feature avoids collisions.
- The follow-up chips precedent for a bounded side call is `followups.plan` → reserve → call → settle (`followups.py:86-99`, `service.py:734-763`). The ceiling comes from input bytes/3 plus fixed output tokens. An uncertain failure is booked at the ceiling as an `estimated` span (`followups.py:~150`, `manager.span_attempt` 291).

---

## 7. Agents SDK usage

- Pins (`requirements.txt`): `openai-agents==0.22.3` (line 8), `openai==3.19.2` (9), `starlette==1.7.0` (11), `uvicorn==0.54.0` (12), `websockets==16.1.1` (13), `psycopg[binary]==3.3.5` (3).
- Imports used: `agents.Agent, Runner, RunConfig, ModelSettings, OpenAIResponsesModel, OpenAIChatCompletionsModel, add_trace_processor, set_trace_processors, GuardrailFunctionOutput, input_guardrail, output_guardrail`; `agents.exceptions.{InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered, MaxTurnsExceeded}`; `agents.run_state.RunState`; `agents.models.interface.Model`; tests use `agents.testing.{ScriptedModel, assistant_message, function_call}` (`tests/test_agent_runtime.py:27`).
- The Manager is `Agent(name="rafii_manager", instructions=instructions(ctx), tools=sdk_tools(...)+specialist tools, handoffs=[], model=Metered(...), output_type=answer_policy.reply_type(), output_guardrails=[truthful], input_guardrails=[forbidden])` (`manager.py:379-382`).
  - Structured output `ManagerReply{answer, speakable, language="en", follow_ups: list[str]}` (`answer_policy.py:184-194`).
  - Specialists are `Agent.as_tool` (`specialists.py:160+`). Founder uses `max_turns=12` (`rafii_control/founder_agent.py:449`).
- `Runner.run_streamed`: **not used anywhere**. **[INFER]** It exists in 0.22.x (`RunResultStreaming.stream_events()`, `.cancel()`), but a cloud probe must confirm it against the pinned version before B depends on it.

---

## 8. HTTP, transport and deployment seams

- Agent routes (`ARV2/http.py:46-86`), mounted at `hosted_app.py:781-784` after the origin guard and bearer (`hosted_app.py:702-704`):
  - `status`, `turns`, `conversations/{c}/active-run`, `runs/{r}`, `runs/{r}/events`, `runs/{r}/cancel`, `conversations/{c}/state`, `tasks/{t}`, `approvals/decide`, `attachments`, `voice/sessions[/{v}/transcript|end]`.
  - `require_session_token` rejects API tokens with 403 (`api_guard.py`).
- Mutations need `X-Postriff-Request: founder-alpha` plus a same-origin check (`hosted_app.py:310-321`). Bearer comes from `HTTP_AUTHORIZATION` (287-291). JSON body limit is 12 MB with `application/json` required (292-307). **[GAP]** That 12 MB global limit is far above the contract's 128 KiB/32 KiB. Enforce the contract limits per route.
- Error mapping: `AlphaError` → `{error, code}` with its status. Other exceptions → 500 `internal_error`, logging only the class and a route pattern (`hosted_app.py:1015-1040`). **[GAP]** `__call__`'s `finally` logs duration when `_handle` *returns*. In a streaming WSGI generator, errors raised during iteration bypass these handlers, so the generator must catch and emit `ui.failed` itself. Request metrics would understate duration.
- Founder:
  - `/api/control/v2/*` is handled by `rafii_control.hosted.embedded_app` (cookie + CSRF + capability), before the consumer bearer (`hosted_app.py:489-497`).
  - Founder agent routes are at `src/rafii_control/http.py:273-281` (`/agent/turns`, `/agent/runs/{id}`, `/cancel`, `/conversations/{id}/state`), capability `copilot.use` (326, 339).
  - `FounderAgentRuntime(AgentRuntimeService)` (`founder_agent.py:366+`) uses `scoped_service`, `reservation_approval=founder_reservation_approval` (cost centre `founder_ops`) and has no site-agent fallback.
  - The founder tool tenant comes from `ctx.extra['founder']` (`tool_adapter.py:73-93`).
  - **Founder UI routes therefore belong under `/api/control/v2/agent/ui/...`**, using the same capability check.
- Vercel (`vercel.json`): services `postriff_web` (Next), `postriff_api` (`api.index:app`, WSGI `HostedApplication`, maxDuration 300), `rafii_phone_media` (`api.phone:app`, ASGI Starlette, maxDuration 660). Rewrites: `/api/phone/(dial/)?media/(.*)` → phone, `/api/(.*)` → api, `/(.*)` → web. The web dev proxy is in `web/next.config.ts:10-61` (dev only).
- **[INFER]** Whether Vercel's Python runtime flushes WSGI iterable chunks incrementally is unknown. The ASGI service pattern (`phone/asgi.py:51+`, `WSGIMiddleware` plus Starlette routes) is the proven way to add a Starlette `StreamingResponse` behind a precise rewrite. R0 must prove chunked delivery on a preview deployment (contract §2.5).
- Web client (`web/src/lib/agent-runtime/client.ts:44-81`): `fetch` with `Authorization: Bearer`, `APP_GUARD_HEADER`, `cache:'no-store'`; base `/api/workspaces/{w}/agent`. The voice client calls the same `turn` with `modality:'voice'`, `delegationId`, `voiceSessionId` and speaks `result.speakableSummary` (`web/src/lib/agent-runtime/voice-session.ts:400-418`).

---

## 9. What lane B must call or extend (presenter, streaming, metering)

**Admission.**
1. Load the parent run with `require(member, "edit")`. Same actor as the parent run? See D7.
2. Check eligibility: parent `status=='completed'`, `idempotency_key LIKE 'agent:%'`, and `result.composedBy=='manager'` with `usage.billing=='metered'`. **Not** fallback runs, site agent or deterministic runs: those never sent data to a cloud model, so presenting them would create new egress.
3. Check `cfg.enabled("RAFII_AGENT_V2_ENABLED")` and the new UI flag.
4. Check `cfg.route(<presenter workload>).available` and `cfg.estimate_usd_micro(...)`, which must not be None.

**Reservation.**
- `service.ledger.reserve(cur, w, principal, "text_model", ceiling, <key>, charge_batch=False, provider=route.provider, model=route.model, run_id=<parentRunId>, credit_authority=<same authority path as parent: runtime._reservation_approval(...)>, meta={"via":"rafii_agent_ui","traceId":..., "attemptId":...})`.
- Do it in a short transaction *before* dispatch. Settle it once in the stream's `finally` with `ledger.settle(..., "completed"|"failed"|"unknown", cost)`.
- Write attempts with `ai_call_events.write_attempts(base={feature:"agent_ui" or "agent", run_id: parentRunId, reservation_id}, attempts=[span_attempt(cfg, span) with physical_attempt_id=f"{attemptId}:p{n}"])`. Reuse `manager.span_attempt` and `failure_status` as they are.

**Client and model.**
- Reuse `manager.provider_model(cfg, workload)`, which already sets `max_retries=0` and `timeout=90` (lower it to fit 60 s), and `manager.settings_for(cfg, workload)` (gateway `include_usage=True`).
- Wrap with `manager.metered(...)`, **after extending `MeteredModel.stream_response`** to:
  1. append a span from the terminal event's usage (Responses `response.completed`; ChatCompletions final usage chunk);
  2. call `_note_failure` on exceptions or cancellation;
  3. book an aborted or unknown stream at its ceiling as `estimated`.
- That is a narrow patch to `manager.py`. Per the plan, B sends it to A.

**Driving the stream.** Either `Runner.run_streamed(Agent(name="rafii_presenter", tools=[], handoffs=[], output_type=None, model=metered))`, or direct `model.stream_response(...)`. Both must close clients within the loop (copy `drive`'s `finally close_clients`).

**Deadline.** Presenter limit 60 s, capped by `ctx`-style remaining time and by Vercel maxDuration 300.

**Projection inputs (no new reads).** Use the persisted parent `result` (`references`, `facts`, `toolActivity`, `changedEntities`, `pendingApprovals`, `generatedAssets`, `task`) plus the EffectLedger-derived `site_results` used by `evidence_blocks`. Note: `site_results` is not persisted today. **[GAP]** D's `project_ui_context` must either re-read through tools or persist a bounded projection in `_finalize`.

**Truth guard.** Generated commentary is model text. Run `answer_policy.check(text, ledger_like)` (`answer_policy.py:88`) on Text props, or render it only as "commentary" and never as status. Native `answerText`, warnings and approvals stay outside the generated subtree.

**Cancellation.** Contract `POST presentations/{id}/cancel` is not the run cancel. Set the attempt's state to `canceled` in F's store. The producer must poll that state between chunks and abort its stream (`RunResultStreaming.cancel()` or close the client). Then settle `unknown` if any bytes were received, or `failed`/0 if nothing was dispatched (`ModelNotDispatched`, `manager.py:26`).

---

## 10. What lane F must call or extend (artifact store on the existing run model)

**Identity to attach.** Use `conversation_id` (`pr_conversations.id`), `message_id` (the assistant `pr_messages.id` from `_stored(...)["messageId"]`) and `parent_run_id` (`pr_agent_runs.id`, an `agent:` run). Store IDs as uuid with `::text` comparisons, the same convention as `service.py`.

**Recommended additive tables** (A owns the migration; the next number appears to be **097** at this SHA, current max is `096_universal_library_duplicate_index.sql`, also referenced in `tests/phase2/rls.sql`):
- `pr_ui_artifacts`: `id`, `workspace_id`, `conversation_id` (FK cascade), `message_id` (FK), `parent_run_id` (FK `pr_agent_runs` cascade), `slot`, `revision`, `state`, `validation_state`, `library_version/hash`, `prompt_hash`, `source_hash`, `canonical_source` (≤128 KiB), `fallback_text`, `manifest_id`, `binding_version`, `safe_state jsonb` (≤16 KiB), `state_revision`, `as_of`, timestamps. Add `unique(workspace_id, parent_run_id, slot)`.
- `pr_ui_attempts`: `id`, `artifact_id`, `target_revision`, `idempotency_key` with unique `(workspace_id, idempotency_key)`, `producer_lease_until`, `state`, `reservation_id`, `retry_of_attempt_id`.
- `pr_ui_artifact_events`: PK `(artifact_id, seq)`. Kinds are `ui.*` with `body` holding the delta or pointer. This table is private: either service_role only, read through the API, or with RLS identical to messages.
- Server-only manifest table: `pr_ui_manifests`, D's.
- Action receipts/idempotency: D's.
- Apply the RLS pattern from 005:86-97. Add rows to `tests/phase2/rls.sql`.

**Writes.**
- Do **not** use `ideas._insert_event` for `ui.*` events. The kind CHECK, SAFE_EVENTS and the workspace-row lock per event all rule it out.
- Checkpoint coarsely (by bytes or time) in short transactions.
- **[INFER]** To avoid one Supabase `getUser` call plus a workspace row lock per checkpoint, authenticate once at stream start through `repository.transaction`. Then write checkpoints keyed by the lease through `service.repository.connection_factory()` with explicit `workspace_id` + `artifact_id` + lease predicates. The precedent is `ideas.recover_stalled`, which uses `connection_factory` directly (`ideas.py:1832+`). Re-check authorization on every replay, query and action request.
- **Optional safe pointer:** insert one `safe_event("artifact.created", artifact="agent_ui.presentation", artifactId=..., revision=...)` into the **parent run's** `pr_agent_events` at ready. That kind is allowed (`agent_runtime.py:14`), and `_persist` already uses this exact shape with `artifact="site_agent.block"` (`service.py:885-886`). Note that `_emit_thinking` refuses non-running runs but `_insert_event` does not.

**Leases and reaping.**
- One producer per `(workspace, principal, conversation, parent_run, slot, target_revision)`, enforced with a unique key plus `producer_lease_until`.
- Copy `_reap_stale_turns` (`service.py:960-986`): when a lease has expired with an open reserve → `ledger.settle(..., "unknown", None)` and attempt state `interrupted`. Call it at presentation admission and from `/api/cron/worker` next to `ideas.recover_stalled()` (`hosted_app.py:634-635`).

**Idempotent create/resume.** Mirror `turn()`'s `SELECT ... WHERE workspace_id=%s AND idempotency_key=%s` early-return to `_stored` (`service.py:112-115`): the same key returns the same artifact and attempt, and never a new producer.

**Replay.** `GET presentations/{id}/events?after=` mirrors `run_events`/`_events_for`: a `read` permission check, `seq>%s ORDER BY seq LIMIT 500`, event id `{artifactId}:{seq}`, and `Last-Event-ID` parsing as at `hosted_app.py:385-388`.

**Surfaces and voice.** The native result stays in `pr_messages.body.agent` and `body.siteAgent.blocks`. Voice reads only `result.speakableSummary` (`voice-session.ts:418`), so it is unaffected by the artifact. Selection context should travel the existing `references`/chips path (`turn_references.parse`; `ctx.chip_refs`, `service.py:453-456, 603-605`) rather than a new channel.

**History.** `_history` reads only `body.text` (`service.py:581-592`), so artifacts add no prompt tokens to later turns unless deliberately projected.

---

## 11. Risks and gaps (summary)

1. **[GAP]** No streaming transport is proven: a WSGI buffered JSON response with Content-Length. The ASGI service precedent exists. A deployment probe is mandatory.
2. **[GAP]** `MeteredModel.stream_response` does not meter usage. It must be fixed before any streamed spend.
3. **[GAP]** Credit-mode workspaces have no credit authority for agent text turns. A presenter reservation would be refused (402). The production value of `POSTRIFF_CREDITS_ENABLED` is unknown.
4. **[GAP]** No result field or hook carries UI eligibility or projection. A needs a `service.py` seam.
5. **[GAP]** `ledger.site_results` (raw tool results) are not persisted. A projection after the turn must re-read or persist a bounded copy.
6. **[GAP]** A new ledger prefix needs a `LEDGER_FEATURES` and 054-view update, otherwise Founder analytics shows it as `other`.
7. **[GAP]** `pr_agent_runs` rows with a new prefix would be swept by `ideas.recover_stalled`, `operational_signals` and member activity. Use separate tables.
8. **[GAP]** Each transaction makes a Supabase getUser call (12 s timeout) and locks the workspace row. Per-delta DB writes would serialize the workspace.
9. **[GAP]** The global 12 MB JSON body limit is far above the contract bounds. Add per-route limits.
10. **[GAP]** No test pins `max_retries=0` for the agent runtime client. SDK-level retry behaviour in 0.22.3 is unverified.
11. **[INFER]** Run cancel is cooperative at tool boundaries and does not abort in-flight provider I/O. Presenter cancel must abort its own stream.
12. **[GAP]** There is no Next.js route handler for the "trusted Node parser adapter". `/api/*` goes to Python, so the validator route must live outside `/api/` (for example under `/internal/...` on `postriff_web`) with service auth. That is A's seam.
13. **[CODE]** Proposal TTL is 24 h and digest-bound. A UI activation (60 s) is an additional gate in front of `approvals/decide`. It must not mint or alter proposals.
