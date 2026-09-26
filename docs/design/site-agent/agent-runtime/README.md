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
     answer within 10 minutes — on that answer, or presented again by it (Rafii restating it, a refused decision, or a
     paused run naming it); several open → Rafii asks which, and only an explicit position ("the second one", "2",
     "第二個") picks one; older → Rafii restates it. The decision runs the site agent's own apply/dismiss path (digest,
     staleness, role, plan gate, audit), then re-reads the workspace and compares. A refused decision changes nothing and
     leaves a waiting step waiting;
   - "cancel that" (edit role) stops the person's own running agent work and their task's open steps in the backend and
     confirms it by re-reading; a new spoken request supersedes only the same person's earlier spoken request;
   - forbidden effects (publish, approve, reply, delete, disconnect, buy, settings, secrets) and greetings go to the
     site agent (its refusals and links, no model cost); so do viewers, a disabled runtime, a missing model route and a
     refused budget reservation (`fallback` in the response).
3. **Manager run** (Agents SDK, outside any workspace transaction, 240 s budget: tool and provider calls are cut to fit
   it, since a thread can't be stopped). Input: the recent conversation (spoken turns
   marked), and an `APP_STATE` block — page, member, resolved references, the active or last task, open approvals,
   conversation images, recent voice transcript, superseded requests. Tools read the workspace in their own short
   transactions and write an **effect ledger**: activity, references, facts, citations, verified changes, proposals,
   generated assets, errors.
4. **Answer policy.** The Manager's reply is used only if it claims nothing the ledger doesn't hold (no
   published/approved/sent/deleted/scheduled claims; "created/linked/generated/paused/applied…" needs a verified change;
   "prepared…" needs a proposal; in a turn that prepared or tried to prepare a proposal, no "has been scheduled/is
   paused" either), names only known ids and contains nothing secret-like — in English, Cantonese and Mandarin
   (Traditional or Simplified, with or without a subject, 將/把 objects) and code-switched sentences. Otherwise the answer
   is composed from the ledger. The same check runs as an SDK output guardrail. When a proposal is waiting, what voice
   says is the application's own description of it (its action and time in words), never only the model's.
5. **Persist.** One assistant message in the site agent's block format (the panel renders it; Apply/Dismiss work
   unchanged) with the surface-neutral result in `body.agent` (`answerText`, `speakableSummary`, references, facts,
   tool activity, task, changed entities with their verification, pending approvals, generated assets, warnings,
   errors, usage, routes, trace id). Evidence views of what was read (stored facts, derived observations with their
   rules, voice-check findings, audit attribution) are appended as the site agent's own blocks. Run `agent:<key>` holds
   the trace; the ledger reservation is settled from token usage, each call priced at its own model (vision included).
5. **Always closed.** Whatever fails after a run opens, it ends `failed` with a plain answer and its spend booked. A turn
   the platform killed (Vercel's 300 s limit) is closed by the next turn in the workspace, its reservation booked at the
   reserved amount; the writing-recovery cron leaves `agent:`/`task:`/`voice:` rows alone (a task waiting for an
   approval, or a live call, is not a stalled writer).

## Agents and tools

- **Manager** (`rafii_manager`, no handoffs): direct reads (entity status, calendar, campaigns, drafts, attention,
  queue, relationships, memory, images, help, navigation), task tools, the two proposal tools, `proposal_apply`, web
  research, the weather, the writing skills, step-by-step guides, voice panel control, and eight specialists as tools.
  Its instructions end with the person's style (`style.text_block`, loaded per turn).
- **Specialists** (each only its own tools; the gate re-checks scope): Brand Intelligence, Content, Campaign, Publishing
  Operations, Research, Analytics, Creative, Workspace/History (`specialists.py`).
- **Tools** (54 of the runtime's own in `tool_adapter.REGISTRY`, before extensions; 43 READ, 5 CREATE_DRAFT,
  4 MUTATE_REVERSIBLE, 2 PREPARE_EXTERNAL): the site agent's released read and client tools adapted (including its
  `voice.check`, `member.activity`, `record.attribution`, `campaign.membership`, `ui.navigate`, `ui.guide`, `ui.voice`),
  plus task_plan/task_update, schedule_propose, automation_change_propose, campaign_link/unlink/items, draft_create,
  draft_rewrite, memory_context, relationships, pending_approvals, proposal_apply, image_list/analyze/generate/edit/variant,
  web_research, weather_now, skills_list. Effect classes: READ, CREATE_DRAFT, MUTATE_REVERSIBLE, PREPARE_EXTERNAL (always
  a proposal); nothing EXTERNAL_EFFECT, DESTRUCTIVE or SECRET exists. Voice gains nothing over text.
- **What executes directly** for a role that allows it, because the person asked: drafting through the writing pipeline
  (drafts are reviewable), images saved to the library, linking drafts/posts/images to a campaign (the campaign's own
  relation; audited; reversible). **What is only ever a proposal**: scheduling or moving a post (which then still needs
  its own approval to publish) and automation changes.
- **HITL:** `proposal_apply` always pauses the run (SDK `needs_approval`); the paused run is stored server-side with
  identifiers only (never the session token), and its answer names the proposal so the next "yes" binds to it. When the
  person approves, the site agent's path applies it, the paused run is taken off its task, and the resumed call (a
  reserved model run) only re-reads and verifies; if it can't resume, the deterministic "Done and checked" answer
  stands. A finished task keeps no paused model state.

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

- The browser sends its WebRTC offer to `POST agent/voice/sessions`; the server checks both flags (voice delegates to the
  agent runtime), the member (edit), the concurrency cap (2 live sessions) and the budget (reserving the session cap,
  recorded on the session row in the same transaction), then creates the session with
  `POST https://api.openai.com/v1/live/sessions` using the project key: `gpt-live-1`, a short Live prompt (template
  headings, delegation rules, language line), client delegation, an explicit data-channel allowlist, `store: false`, and
  the conversation so far as history. Only the SDP answer and ids return. The voice and language come from the request
  when it names valid ones, otherwise from the person's style (`style.load`, default before migration 026); the Live
  prompt ends with the style's delivery lines (`style.voice_block`), and the start response returns the `locale` and
  `voice` the call actually uses. The Live prompt lists every backend capability (workspace, web search and weather,
  images, drafting with the platform skills, the screen, navigation and guides, panel control), never says it can't look
  something up or see the page, and says one short goodbye when the person ends the call (the app hangs up).
- `session.delegation.created` → the browser calls the same `agent/turns` with `modality: "voice"`; quiet progress goes
  back with `session.thinking.append`, the verified result with `session.commentary.append`. Barge-in is GPT-Live's
  (full duplex); "Stop talking" drops local audio and appends a yield instruction; a new spoken request supersedes a
  running one before its next change; "cancel that" cancels in the backend.
- The voice session lives outside React (navigation and panel re-framing keep it; switching workspace or leaving the
  signed-in app ends it), speaking state comes from the remote audio level and transcript deltas, transcripts are
  stored as text on the voice session row as the call goes (batches of 50; no audio), a request takes exactly the words
  said since the previous one, and a brief connection drop that recovers returns to live by itself.
- Billing: a call is billed on the server's clock (+15 s at creation); what the client reports can't lower it. A session
  a tab never ended (or a sign-out, which can't end it without a session) is closed on the next start in the workspace
  and billed from its start to its last recorded activity plus a minute, at most the 30-minute cap.

## Images

Vision: the backend vision model with the image as a data URL (`store: false`); visible text is returned as data.
Generation/editing: the Responses image tool (`gpt-image-2.5-sunburst` default and for edits, `gpt-image-2.5-flare` for
fast variants) or the gateway Images API; the product's pipeline (reserve → provider → private staging → audited
`add_asset` → settle → re-read). Edits and variants are new assets with lineage (operation, parent, sources, model,
route, prompt summary, run, trace, conversation, billing basis); the original is re-read to prove it is unchanged. An
image is booked at the provider's reported cost (the gateway) or the configured per-image price (the OpenAI image
tool reports tokens, not money), so it uses a media credit and never stays "unknown"; the same image asked twice in
one turn is made once. A failure saves nothing and claims nothing; a provider whose outcome is unknown (a timeout) is
held as unknown. The panel scales a photo down in the browser to at most 3 MiB before upload (Vercel Functions take
request bodies up to 4.5 MB; base64 adds a third). Scheduling a post with an image carries the image, its alt
text and the person's rights confirmation in the digest-bound proposal.

## Live agent: current facts, guides, the screen, voice panel, slash commands

Contracts: `docs/design/rafii-live-agent/CONTRACTS.md` (2, 3, 6, 7 are built here).

- **Current facts.** `web_research` is on the Manager (still behind the owner's research consent; `research_off` carries
  `guide: turn_on_web_search`). `weather_now` (`live_tools.py`) uses Open-Meteo geocoding and forecast: only the place
  name leaves Rafii, so no consent is needed; HTTPS to two allowlisted endpoints, no redirects, 8 s timeout, 256 KiB cap,
  a 10-minute in-process cache per place and language; codes in plain words; a missing place asks, an unknown place or
  a network failure is a plain answer with no provider detail.
- **Writing skills.** `skills_list` lists the active `postriff-*` skill packages from `skills/rafii-registry.json`
  (never a private or `james-au-*` one; policies and evaluators are code, not listed). `draft_create`/`draft_rewrite`
  results name the product skills their writing run bound (`usage.skillBindings`), also as a stored fact.
- **Client actions and answer blocks** (next to `navigation_card`): `ui.guide {guideId, auto?}` →
  `guide_card {type, guideId, routeId, href, title, summary, auto}` from `site_agent/guide_manifest.json`
  (`site_agent/guides.py`: `load`, `find`, `match`); `ui.voice {command: end_call|mute|stop_speaking|style, style?}` →
  `voice_command {type, command, style?}`, a style patch validated by `style.validate_patch` and saved with a guarded
  `UPDATE public.pr_profiles SET agent_style` inside a savepoint (`persisted: false` before migration 026; never a failed
  turn); `ui.navigate` takes `auto`. `auto` is honoured only when the person's own words ask to be taken somewhere or to
  be shown how (a model's choice alone leaves a card to click), and at most one block acts by itself (an auto guide wins
  over auto navigation). A page that didn't declare the `guide` capability gets a plain link; without `voice`, no
  voice command block.
- **The screen.** `pageContext.outline` (≤ 40 labels, ≤ 80 characters each, about 3,000 in all; roles and states from
  allowlists; instruction-like labels dropped) is re-validated and reaches the Manager as `APP_STATE.screen` under
  "What the person's screen shows (labels only; untrusted data)". It is never stored on messages or traces.
- **Slash commands** (`commands.py`): `agent/turns` accepts `command: {name, args}` for write, rewrite, translate,
  hashtags, caption, repurpose, ideas, search, weather, stats, review, image, schedule, automation, skills (args plain
  text ≤ 1,000 characters). Each adds one fixed instruction after the request, with the args in a `<<< >>>` data fence;
  an unknown or malformed command is ignored. `/weather <place>` is answered without a model (the tool through the gate,
  a deterministic answer in English or Chinese). Commands never skip permissions, consent, credits or approvals.
- **Provider clients.** Every `AsyncOpenAI` client a run builds is recorded on the run context and closed inside the
  run's own event loop (`manager.drive`), which ends the "Task exception was never retrieved … Event loop is closed" log
  noise.

## HTTP (`/api/workspaces/{id}/agent/…`)

`GET status` · `POST turns` (201) · `GET runs/{run}` · `POST runs/{run}/cancel` · `GET conversations/{c}/state` ·
`GET tasks/{task}?cursor=` · `POST approvals/decide` · `POST attachments` (201) · `POST voice/sessions` (201) ·
`POST voice/sessions/{v}/transcript` · `POST voice/sessions/{v}/end`. No new tables or migrations.

## Configuration

Flags: `RAFII_AGENT_V2_ENABLED`, `RAFII_SPECIALISTS_ENABLED`, `RAFII_VOICE_ENABLED`, `RAFII_IMAGE_AGENT_ENABLED`,
`RAFII_PROACTIVE_V2_ENABLED`. Models: `RAFII_AGENT_PRIMARY_MODEL` (gpt-6-sol), `_FAST_MODEL` (gpt-6-luna),
`_VISION_MODEL` (gpt-6-sol), `_IMAGE_MODEL_QUALITY` (gpt-image-2.5-sunburst), `_IMAGE_MODEL_FAST` (gpt-image-2.5-flare),
`RAFII_LIVE_MODEL` (gpt-live-1); provider `openai` (`OPENAI_API_KEY`, needed for voice) or `gateway`. Prices per model
in `config.py` (override `RAFII_AGENT_MODEL_PRICES`); a model without a price is never called. Per-image prices:
`RAFII_AGENT_IMAGE_PRICES` (USD per image, `image_fast` / `image_quality`). `vercel.json` allows the
microphone for this origin only. Dependency: `openai-agents==0.22.3`, `openai==3.19.2`.

Follow-up suggestions (`followups.py`): after each answer the panel shows two or three chips the person may tap to send
as their own next message. The Manager's own `follow_ups` are used when it offers at least two; otherwise the fast model
writes them from the person's message, the answer and the open work (thinking off, at most 240 output tokens). The call
is metered on the same run: after a Manager answer it runs only if its ceiling fits the room left in the turn's
reservation; after a deterministic answer (an applied or dismissed proposal) it reserves its own small ceiling on the
run first. A refused budget, a missing route or price, a stopped run, too little time or any provider failure means no
chips, never an error. A suggestion that reads as a decision ("yes", "cancel", "the second one") is dropped, so a tap
never approves, rejects, chooses or stops anything. Scripted runs make no provider call.

## Verification

- `PYTHONPATH=src:tests python -m unittest tests.test_agent_runtime` — deterministic (Agents SDK `ScriptedModel`).
- `PYTHONPATH=src:tests python scripts/agent_runtime_pg.py tests/phase2/postgres_agent_runtime.py --port 55621` —
  51 scenarios on a disposable PostgreSQL with the real services, including the spec's vertical slice.
- `node web/tests/agent-runtime-browser.cjs [--browser=webkit --shots=off]` against the dev harness with
  `RAFII_AGENT_HARNESS=1` (local only; refused on Vercel) — Voice Mode in Chromium and WebKit.
- `RAFII_LIVE_CHECKS=1 OPENAI_API_KEY=… python scripts/agent_runtime_live.py --reasoning --vision --images --live-session`
  — opt-in live checks with a hard cap: the reasoning check refuses its next model call at `--budget-usd` (default
  $0.50, at most $2; a reached cap is a FAIL); one vision call, two 1024×1024 images, one Live session closed at once.
- `python scripts/agent_runtime_matrix.py --unit` — regenerates the matrix from the evidence.

## Files

- Backend: `src/postriff_phase2/agent_runtime_v2/` — `config`, `contracts`, `context`, `tool_adapter`, `domain_tools`,
  `creative`, `task_state`, `memory_layers`, `graph`, `approvals`, `answer_policy`, `specialists`, `manager`, `service`,
  `live`, `live_tools`, `commands`, `style`, `http`, `api_guard`, `harness`, `evals/catalog`; guides in
  `site_agent/guides.py` + `guide_manifest.json`. Wiring: `hosted_app.py` (4 lines).
- Web: `web/src/lib/agent-runtime/` (client, types, live transport, voice session, hook) and
  `web/src/features/rafii-voice/` (Voice Mode, image attach, answer extras, voice indicator); mounted in the site
  agent's `chat.tsx` and `panel.tsx`.
- Tests and scripts: `tests/test_agent_runtime.py`, `tests/phase2/postgres_agent_runtime.py`,
  `web/tests/agent-runtime-browser.cjs`, `scripts/agent_runtime_pg.py`, `scripts/agent_runtime_live.py`,
  `scripts/agent_runtime_matrix.py`.
