# Rafii Agent Runtime — WP00 architecture lock (2026-09-24)

Governing spec: `../RAFII_MULTIMODAL_AGENT_RUNTIME_ENGINEERING_SPEC_2026-09-24.md`. This note maps it onto the code
that exists on `raffi/site-agent` (HEAD `064982b` plus the concurrent session's in-flight gap work) and records every
deviation from the spec's suggested layout with its reason (spec §48).

## Repository facts that decide the design

| Fact | Consequence |
|---|---|
| The hosted API is one synchronous WSGI app on Vercel Python (`api/index.py`, `maxDuration` 300 s, no websockets; its "SSE" is a finite, cursor-replayable body). | Agent turns run synchronously inside a request (`Runner.run_sync`). Progress is cursor-polled `pr_agent_events`, the same way the panel already follows runs. No long-lived server socket (so no Live sideband; see ADR-L3). |
| Workspace data is one revisioned JSON document (`pr_workspaces.state`), mutated only through `repository.command` / `mutate` with a permission class per action (`permissions.ACTION_CLASSES`), audit in `pr_audit_events`, effects hooks (learning, planning sync). | Every agent mutation goes through `repository.command` with the action's own requirement, then `repository.get` re-reads and the tool compares. Model calls never happen inside a transaction (each transaction locks the workspace row). |
| Conversations, runs, events and usage already exist: `pr_conversations`, `pr_messages` (answers in `body.siteAgent`), `pr_agent_runs` (idempotency-key prefixes `site:`…), `pr_agent_events` (SAFE_EVENTS only), `pr_usage_ledger` (reserve → settle). | No new conversation, memory, usage or run table. Agent answers are stored in the existing `body.siteAgent` block format, so the panel renders them unchanged and the existing apply/dismiss endpoints stay the only approval path. Task plans are `pr_agent_runs` rows keyed `task:`; voice sessions are rows keyed `voice:`; agent turns `agent:`. |
| Proposals (`site_agent/proposals.py`) are digest-bound, stored on the answer message, applied by `SiteAgentService.apply_proposal` with permission re-check, staleness refusal, billing gate and audit. | Proposal tools call the same builders (`build_schedule`, `build`); approval (panel click or bound spoken "yes") calls the same `apply_proposal`. The Agents SDK HITL interruption (`needs_approval`) only pauses a run; it never applies. |
| Images: `state.phase2.assets` (decoded, private storage, `add_asset` command, audited `media.generated`), image generation through `IdeasService._image_turn` (ledger reserve → provider → stage → command → settle). Media attach to a post at review preparation (`p2_review` with `assetId`, `alt`, `rightsConfirmed`). | Vision and image generation/editing extend that pipeline (same staging, command, audit, ledger) and add lineage fields to the asset record. Attaching an image to a scheduled post is a field of the schedule proposal (digest-covered), requested from the site-agent owner (ADR-I3). |
| Learned preferences carry `source`, `evidenceState`, `confirmedBy`, `since`, `replaces`, `status`; proposals carry `support` and evidence (`learning_service`, `postriff_alpha.learning`). Memory reaches a cloud model only through `memory.projection(state, "cloud")`, gated by the owner's cloud-memory decision. | Provenance / explicit-vs-inferred / confidence are derived from those fields; no migration. The agent runtime is a cloud processor and uses the same projection (ADR-M1). |
| All current model traffic goes through Vercel AI Gateway (`AI_GATEWAY_API_KEY`); no `OPENAI_API_KEY` exists locally or in `.env.example`. | The runtime supports both providers behind config aliases; GPT-Live requires the OpenAI key. Its absence is reported as a blocker, never replaced by another paid route. |
| `site_agent/*`, `campaigns.py`, `ideas.py`, `hosted_app.py`, the site-agent web panel/types, the site-agent tests, README/matrix/evidence are being edited by a concurrent session (gaps V04, D04, K05/X03, X04, H05) until its commits land. | This work lives in new files. Integration edits in those files happen only after that session releases them. The agent runtime wraps its gap functions (`voice.check`, `member.activity`, `record.attribution`, `raffi_campaign_link/unlink`) instead of duplicating them. |
| `vercel.json` sends `Permissions-Policy: microphone=()`. | Voice Mode needs `microphone=(self)` (ADR-L5). |

## Decisions

**ADR-P1 — package.** `src/postriff_phase2/agent_runtime_v2/` beside `site_agent/`. It imports the site agent's verified
executors, proposal builders, references, knowledge and policy; it never copies them. Modules: `config` (flags, model
aliases, router), `contracts` (surface-neutral result, effect classes, steps), `context` (run context + effect ledger),
`tool_adapter` (policy gate, site tools adapted), `domain_tools`, `creative` (vision, image generation/editing),
`task_state`, `memory_layers`, `graph`, `approvals`, `specialists`, `manager`, `answer_policy`, `live` (GPT-Live broker),
`service` (the one entry point), `http` (routes), `evals/`.

**ADR-P2 — one turn operation.** `AgentRuntimeService.turn(workspace_id, token, payload)` runs a Rafii turn for text,
delegated voice and image requests alike (modality is an input, not a branch in business logic). Deterministic front
door first (forbidden effects → the site agent's refusal; spoken/typed confirmation → the approval binder; "cancel
that" → backend cancellation), then the Manager. When the runtime is off, the member can't use a model (viewer), no
model route is configured, or the budget refuses the reservation, the turn is the existing `SiteAgentService.turn`
unchanged (spec §41 safe fallback). Flag: `RAFII_AGENT_V2_ENABLED`.

**ADR-A1 — Agents SDK placement.** `openai-agents==0.22.3` (Python ≥3.10; the repo pins 3.12). One Manager `Agent`
with direct deterministic read tools and eight specialists exposed with `Agent.as_tool` (Brand Intelligence, Content,
Campaign, Publishing Operations, Research, Analytics, Creative, Workspace/History). No handoffs: no specialist needs to
own the conversational turn (the person always talks to Rafii); `handoffs=[]` is asserted in tests (spec §10: handoff
only with a documented reason). Each specialist gets only its tool subset; the gate re-checks scope.

**ADR-A2 — models.** Aliases `RAFII_AGENT_PRIMARY_MODEL` (default `gpt-6-sol`), `RAFII_AGENT_FAST_MODEL`
(`gpt-6-luna`), `RAFII_AGENT_VISION_MODEL` (`gpt-6-sol`), `RAFII_AGENT_IMAGE_MODEL_QUALITY` (`gpt-image-2.5-sunburst`),
`RAFII_AGENT_IMAGE_MODEL_FAST` (`gpt-image-2.5-flare`), `RAFII_LIVE_MODEL` (`gpt-live-1`). Provider `openai` uses the
Responses model; provider `gateway` uses the gateway's OpenAI-compatible Chat Completions endpoint (GPT-6 function
calling there needs `reasoning_effort: none`, which the router sets). Every routing decision is in the trace. The
existing writer selector is untouched: drafting still uses the writer the person chose.

**ADR-A3 — tracing.** One correlation id (`trace_<32 hex>`) per turn: browser event → Live delegation id → Manager →
specialists → tools → approval → mutation → verification → result. It is the SDK `trace_id` (format checked), stored in
the run artifact, echoed in events and audit meta. A local trace processor keeps span summaries (no inputs/outputs,
`trace_include_sensitive_data=False`). Export to OpenAI traces only when `RAFII_AGENT_OPENAI_TRACING=1` and an OpenAI key
is set (and never under ZDR).

**ADR-T1 — task state.** Plans on `pr_agent_runs` (`task:` rows) with step events; `done` only from a tool's verified
result; unattempted steps reported as they stand; impossible steps failed with their own reason (spec §16, X04).

**ADR-H1 — HITL.** Proposals as today. `proposal_apply` is an SDK tool with `needs_approval=True`; an interruption
becomes a pending approval bound to the proposal id and digest, and the serialized `RunState` stays server-side in the
task row. Approval → server permission re-check + digest → `SiteAgentService.apply_proposal` → re-read → the resumed
run's tool call only verifies. A rejected proposal is never retried without a new request.

**ADR-H2 — spoken confirmation.** A "yes" (any language) binds only when exactly one open proposal in the conversation
was presented in the latest assistant answer, within 10 minutes, with no newer answer since; digest and role are
re-checked by the apply path. Two open proposals → ask which. Older → re-state it and ask again.

**ADR-L1 — GPT-Live transport.** Browser WebRTC; the browser POSTs its SDP offer to
`/api/workspaces/{id}/agent/voice/sessions`; the server authenticates, authorizes, reserves the voice budget and calls
`POST https://api.openai.com/v1/live/sessions` with the project key (JSON `session` + `transport {type: webrtc, sdp}`), and
returns only the SDP answer and ids. No client secret exists for Live, and the key never reaches the browser.
`session.client.data_channel.allowed_client_events` / `allowed_server_events` are set explicitly.

**ADR-L2 — client delegation.** `delegation: {type: "client"}`. On `session.delegation.created` the browser takes the
user's utterance from `session.input_transcript.delta`, calls the same `agent/turns` endpoint with `modality: "voice"`,
sends quiet progress with `session.thinking.append` and the verified result with `session.commentary.append`
(`speakableSummary`, ≤ 500 tokens). Live has no cancel command: cancellation is backend-side (`agent/runs/{id}/cancel`
and the "cancel that" front door) and is confirmed before Rafii says it.

**ADR-L3 — no sideband.** A sideband WebSocket needs a long-lived server connection this WSGI deployment can't hold.
Transcripts reach the server through the authenticated delegation and transcript endpoints instead. Recorded as a
deliberate deviation; revisit if the API moves to a runtime with websockets.

**ADR-L4 — voice state and privacy.** Speaking/listening state comes from real session signals (remote audio level,
output transcript deltas, `session.closed`), never timers. `store: false`; no raw audio is persisted; transcripts are
stored as ordinary conversation messages (`modality: "voice"`). No voice biometrics, no voice authentication.

**ADR-L5 — browser permissions.** `vercel.json` `Permissions-Policy` becomes `microphone=(self)`; camera and geolocation
stay denied.

**ADR-M1 — egress.** The agent runtime is a cloud route. Brand Brain, voice and learned-preference *content* reach it
only through the owner's cloud-memory decision (`memory.projection(state, "cloud")`), with private boundaries withheld;
otherwise tools return what exists and that it is withheld. Draft text reaches it when the person asks about or works on
that draft (the same basis as a rework sent to a cloud writer today). Images reach the vision model only when attached
to the request or named by id in this workspace.

**ADR-I1 — images.** Primary path: Responses API `image_generation` tool (`model` set explicitly; Sunburst for quality
and edits, Flare for fast variants), host model from the router. Gateway path: Images API through the existing gateway
runtime. Originals are never overwritten: an edit is a new asset with `lineage {operation, parentAssetId,
sourceAssetIds, model, route, promptSummary, runId, traceId}`. A failed save never shows a transient base64 image as an
asset.

**ADR-I2 — vision.** The backend vision model (router workload `vision`) receives the image as an `input_image` data URL
plus the question and a minimal context; visible text in the image is data. GPT-Live never receives images.

**ADR-I3 — image on a scheduled post.** Requested from the site-agent owner: optional digest-covered `media
{assetId, alt, rightsConfirmed}` on schedule proposals, passed to `p2_review` (which already enforces decoded media,
alt text and rights confirmation). Until it lands, the tool reports the step as needing the person, with the reason.

## Verification plan

Deterministic: Agents SDK `ScriptedModel` for Manager/specialist orchestration, approvals, guardrails, cancellation;
fake GPT-Live HTTP and data channel; fake image/vision transports; PostgreSQL scenario scripts on a private cluster;
browser QA with a fake Live transport and Chromium fake media. Live (opt-in, budget-capped, never in the default
suite): `scripts/agent_runtime_live.py --live-voice | --live-reasoning | --live-images` with explicit env guards.
