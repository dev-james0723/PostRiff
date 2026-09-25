# Rafii Agent Runtime — contract as built

One Rafii across typed chat, Voice Mode and images. Text turns, spoken requests delegated by GPT-Live, and image
requests all run through one backend operation (`AgentRuntimeService.turn`) with one Manager on the OpenAI Agents
SDK, the same conversation, the same memory, the same permissions and the same proposal path as the site agent.
Implements `../RAFII_MULTIMODAL_AGENT_RUNTIME_ENGINEERING_SPEC_2026-09-24.md`; decisions and deviations are in
[ARCHITECTURE_LOCK.md](ARCHITECTURE_LOCK.md); results are in [verification-matrix.md](verification-matrix.md)
(generated; do not edit).

Status: built and verified locally with deterministic stand-ins for the external models. **Not verified live**: a real
GPT-Live session, a real reasoning model driving the Manager, real vision, and real GPT Image 2.5 generation/editing
(no `OPENAI_API_KEY` in this environment, and the AI Gateway OIDC token expired on 2026-09-15). Everything is off
unless the `RAFII_*` flags are set; with them off the site agent answers exactly as before.

## How a turn works

1. **Authenticate, bind, dedupe.** Same session, request guard and origin checks as the rest of the API; API tokens are
   refused. Idempotency key `agent:<key>`. Images sent with the turn must be this workspace's assets; each is recorded
   once on the conversation (`pr_attachments`), so "the second image" is stable.
2. **Deterministic front door** (no model):
   - a bare "yes"/"no" (English, Cantonese, Mandarin) binds only to exactly one open proposal presented in the latest
     answer within 10 minutes; several open → Rafii asks which, and only an explicit position ("the second one", "2",
     "第二個") picks one; older → Rafii restates it. The decision runs the site agent's own apply/dismiss path (digest,
     staleness, role, plan gate, audit), then re-reads the workspace and compares;
   - "cancel that" stops running agent work and open steps in the backend and confirms it by re-reading;
   - forbidden effects (publish, approve, reply, delete, disconnect, buy, settings, secrets) and greetings go to the
     site agent (its refusals and links, no model cost); so do viewers, a disabled runtime, a missing model route and a
     refused budget reservation (`fallback` in the response).
3. **Manager run** (Agents SDK, outside any workspace transaction). Input: the recent conversation (spoken turns
   marked), and an `APP_STATE` block — page, member, resolved references, the active or last task, open approvals,
   conversation images, recent voice transcript, superseded requests. Tools read the workspace in their own short
   transactions and write an **effect ledger**: activity, references, facts, citations, verified changes, proposals,
   generated assets, errors.
4. **Answer policy.** The Manager's reply is used only if it claims nothing the ledger doesn't hold (no
   published/approved/sent/deleted/scheduled claims; "created/linked/generated…" needs a verified change; "prepared…"
   needs a proposal), names only known ids and contains nothing secret-like. Otherwise the answer is composed from the
   ledger. The same check runs as an SDK output guardrail.
5. **Persist.** One assistant message in the site agent's block format (the panel renders it; Apply/Dismiss work
   unchanged) with the surface-neutral result in `body.agent` (`answerText`, `speakableSummary`, references, facts,
   tool activity, task, changed entities with their verification, pending approvals, generated assets, warnings,
   errors, usage, routes, trace id). Evidence views of what was read (stored facts, derived observations with their
   rules, voice-check findings, audit attribution) are appended as the site agent's own blocks. Run `agent:<key>` holds
   the trace; the ledger reservation is settled from token usage.

## Agents and tools

- **Manager** (`rafii_manager`, no handoffs): direct reads (entity status, calendar, campaigns, drafts, attention,
  queue, relationships, memory, images, help, navigation), task tools, the two proposal tools, `proposal_apply`, and
  eight specialists as tools.
- **Specialists** (each only its own tools; the gate re-checks scope): Brand Intelligence, Content, Campaign, Publishing
  Operations, Research, Analytics, Creative, Workspace/History (`specialists.py`).
- **Tools** (50, `tool_adapter.REGISTRY`; 40 READ, 5 CREATE_DRAFT, 3 MUTATE_REVERSIBLE, 2 PREPARE_EXTERNAL): the site agent's released read tools adapted unchanged (including its
  `voice.check`, `member.activity`, `record.attribution`, `campaign.membership`), plus task_plan/task_update,
  schedule_propose, automation_change_propose, campaign_link/unlink/items, draft_create, draft_rewrite,
  memory_context, relationships, pending_approvals, proposal_apply, image_list/analyze/generate/edit/variant,
  web_research. Effect classes: READ, CREATE_DRAFT, MUTATE_REVERSIBLE, PREPARE_EXTERNAL (always a proposal); nothing
  EXTERNAL_EFFECT, DESTRUCTIVE or SECRET exists. Voice gains nothing over text.
- **What executes directly** for a role that allows it, because the person asked: drafting through the writing pipeline
  (drafts are reviewable), images saved to the library, linking drafts/posts/images to a campaign (the campaign's own
  relation; audited; reversible). **What is only ever a proposal**: scheduling or moving a post (which then still needs
  its own approval to publish) and automation changes.
- **HITL:** `proposal_apply` always pauses the run (SDK `needs_approval`); the paused run is stored server-side with
  identifiers only (never the session token). When the person approves, the site agent's path applies it and the
  resumed call only re-reads and verifies.

## Tasks, memory, relationships

- **Tasks:** `pr_agent_runs` rows keyed `task:` with step events; states planned, running, done, needs_user, blocked,
  failed, canceled. Only a tool that did the work and re-read the state marks a step done; an unverified result is
  failed; nothing is dropped. Steps waiting on a proposal follow the stored proposal, whichever surface decided it.
- **Memory:** `memory_context` reads identity, workspace, Brand Brain, voice profile, learned preferences (explicit vs
  inferred, accepted by, evidence state, confidence, supersession), campaigns and the task — from the existing stores.
  Brand Brain/voice/preference content reaches the agent model only when the owner allowed cloud memory.
- **Relationships:** `graph.neighbours` derives edges (derived_from, belongs_to_campaign, created_by_automation,
  reviewed/scheduled/published_as, uses_asset, edited_as…) from stored fields, each naming its source field.

## Voice Mode (GPT-Live)

- The browser sends its WebRTC offer to `POST agent/voice/sessions`; the server checks the flag, the member (edit), the
  concurrency cap (2 live sessions) and the budget (reserving the session cap), then creates the session with
  `POST https://api.openai.com/v1/live/sessions` using the project key: `gpt-live-1`, a short Live prompt (template
  headings, delegation rules, language line), client delegation, an explicit data-channel allowlist, `store: false`, and
  the conversation so far as history. Only the SDP answer and ids return.
- `session.delegation.created` → the browser calls the same `agent/turns` with `modality: "voice"`; quiet progress goes
  back with `session.thinking.append`, the verified result with `session.commentary.append`. Barge-in is GPT-Live's
  (full duplex); "Stop talking" drops local audio and appends a yield instruction; a new spoken request supersedes a
  running one before its next change; "cancel that" cancels in the backend.
- The voice session lives outside React (navigation and panel re-framing keep it), speaking state comes from the remote
  audio level and transcript deltas, transcripts are stored as text on the voice session row (no audio), and a session a
  tab never ended is reaped on the member's next start with its cost held as unknown.

## Images

Vision: the backend vision model with the image as a data URL (`store: false`); visible text is returned as data.
Generation/editing: the Responses image tool (`gpt-image-2.5-sunburst` default and for edits, `gpt-image-2.5-flare` for
fast variants) or the gateway Images API; the product's pipeline (reserve → provider → private staging → audited
`add_asset` → settle → re-read). Edits and variants are new assets with lineage (operation, parent, sources, model,
route, prompt summary, run, trace, conversation); the original is re-read to prove it is unchanged. A failure saves
nothing, claims nothing and holds uncertain spend as unknown. Scheduling a post with an image carries the image, its alt
text and the person's rights confirmation in the digest-bound proposal.

## HTTP (`/api/workspaces/{id}/agent/…`)

`GET status` · `POST turns` (201) · `GET runs/{run}` · `POST runs/{run}/cancel` · `GET conversations/{c}/state` ·
`GET tasks/{task}?cursor=` · `POST approvals/decide` · `POST attachments` (201) · `POST voice/sessions` (201) ·
`POST voice/sessions/{v}/transcript` · `POST voice/sessions/{v}/end`. No new tables or migrations.

## Configuration

Flags: `RAFII_AGENT_V2_ENABLED`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_VOICE_ENABLED`, `RAFII_IMAGE_AGENT_ENABLED`,
`RAFII_PROACTIVE_V2_ENABLED`. Models: `RAFII_AGENT_PRIMARY_MODEL` (gpt-6-sol), `_FAST_MODEL` (gpt-6-luna),
`_VISION_MODEL` (gpt-6-sol), `_IMAGE_MODEL_QUALITY` (gpt-image-2.5-sunburst), `_IMAGE_MODEL_FAST` (gpt-image-2.5-flare),
`RAFII_LIVE_MODEL` (gpt-live-1); provider `openai` (`OPENAI_API_KEY`, needed for voice) or `gateway`. Prices per model
in `config.py` (override `RAFII_AGENT_MODEL_PRICES`); a model without a price is never called. `vercel.json` allows the
microphone for this origin only. Dependency: `openai-agents==0.22.3`, `openai==3.19.2`.

## Verification

- `PYTHONPATH=src:tests python -m unittest tests.test_agent_runtime` — deterministic (Agents SDK `ScriptedModel`).
- `PYTHONPATH=src:tests python scripts/agent_runtime_pg.py tests/phase2/postgres_agent_runtime.py --port 55621` —
  43 scenarios on a disposable PostgreSQL with the real services, including the spec's vertical slice.
- `node web/tests/agent-runtime-browser.cjs [--browser=webkit --shots=off]` against the dev harness with
  `RAFII_AGENT_HARNESS=1` (local only; refused on Vercel) — Voice Mode in Chromium and WebKit.
- `RAFII_LIVE_CHECKS=1 OPENAI_API_KEY=… python scripts/agent_runtime_live.py --reasoning --vision --images --live-session`
  — opt-in, budget-capped live checks.
- `python scripts/agent_runtime_matrix.py --unit` — regenerates the matrix from the evidence.

## Files

- Backend: `src/postriff_phase2/agent_runtime_v2/` — `config`, `contracts`, `context`, `tool_adapter`, `domain_tools`,
  `creative`, `task_state`, `memory_layers`, `graph`, `approvals`, `answer_policy`, `specialists`, `manager`, `service`,
  `live`, `http`, `api_guard`, `harness`, `evals/catalog`. Wiring: `hosted_app.py` (4 lines).
- Web: `web/src/lib/agent-runtime/` (client, types, live transport, voice session, hook) and
  `web/src/features/rafii-voice/` (Voice Mode, image attach, answer extras, voice indicator); mounted in the site
  agent's `chat.tsx` and `panel.tsx`.
- Tests and scripts: `tests/test_agent_runtime.py`, `tests/phase2/postgres_agent_runtime.py`,
  `web/tests/agent-runtime-browser.cjs`, `scripts/agent_runtime_pg.py`, `scripts/agent_runtime_live.py`,
  `scripts/agent_runtime_matrix.py`.
