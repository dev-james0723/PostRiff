# Rafii Multimodal Agent Runtime — Engineering Specification
Version: 1.0
Date: 2026-09-24
Status: EXECUTION-READY
Target worktree: /Users/ouxianxing/Documents/James-Au-Studio-site-agent
Target branch: raffi/site-agent
Audience: Coding agents and engineers implementing the next generation of Rafii

## 0. Executive directive

Upgrade Rafii from a site-wide grounded assistant into a unified, OpenAI-native, multimodal agent runtime.

The product must feel like one persistent coworker whether the user types, speaks, uploads an image, asks Rafii to generate an image, changes pages, or returns later.

This is not “add a voice button.” It is an architectural upgrade that makes text chat, natural full-duplex voice, vision, image generation/editing, app context, memory, tools, approvals, proactive intelligence, and specialist reasoning surfaces of the same agent.

The implementation must preserve the existing site-agent safety and truthfulness contracts. Voice or multimodality must never create a second permission system, second memory, or second source of truth.

The current site-agent implementation is the baseline, not disposable prototype code. Extend it deliberately and keep its verified behavior green.

## 1. Product definition

Rafii is a workspace-aware AI coworker for social content, campaigns, publishing operations, brand intelligence, creative work, research, and planning.

The target user experience is comparable in conversational fluidity to a modern full-duplex voice assistant, while retaining the groundedness and inspectability of an enterprise agent.

A user must be able to start in any modality and continue in any other modality without losing context.

Examples:
- Type: “Build a launch campaign around this article.”
- Later speak: “For that campaign, make the Instagram version more visual.”
- Upload a screenshot while still speaking: “This is the layout I mean.”
- Ask: “Generate a cleaner version in our brand style.”
- Interrupt Rafii while it is speaking: “Actually, keep the original typography.”
- Ask: “What still needs my approval?”
- Say: “Apply the automation change.” The same proposal and permission checks used in text must run.
- Navigate to Calendar and ask: “What am I looking at?” The conversation and task state must continue.

The user should perceive exactly one Rafii identity and one conversation, not a collection of loosely connected bots.

## 2. Current baseline that must be preserved

The active site-agent branch already provides:
- one site-wide conversation available from every app page;
- page and selected-item awareness using structured context rather than DOM scraping;
- grounded answers from help content and stored workspace records;
- deterministic reference resolution for “this,” “that,” ordinal selections, day references, and follow-up answers;
- typed tools with effect classes and role checks;
- proposal-based scheduling and automation edits;
- refusal of publishing, replies, DMs, deletion, billing changes, settings changes, account disconnection, and secret disclosure from chat;
- conversation persistence across navigation and reload;
- Brand Brain, voice profile, memory, campaigns, calendar, reviews, publishing, search, and proactive observations;
- audit events, usage ledger integration, route validation, tenant isolation, and answer-link inspection;
- desktop dock, tablet sheet, and phone drawer;
- locally verified browser and PostgreSQL scenario suites.

Read before implementation:
- docs/design/site-agent/README.md
- docs/design/site-agent/verification-matrix.md
- tests/test_site_agent.py
- tests/phase2/postgres_site_agent_scenarios.py
- web/tests/site-agent-browser.cjs

Do not regress those contracts in order to gain new capability.

## 3. Non-negotiable architectural principles

### 3.1 One brain, multiple surfaces
Text, voice, image upload, image generation, and future surfaces share one backend orchestration layer, one conversation identity, one memory model, one authorization system, and one task state.

### 3.2 Application state is truth
The model is never the source of truth for drafts, campaigns, schedules, approvals, publishing outcomes, members, entitlements, or billing. Rafii reads the application state, acts through typed tools, then re-reads state before reporting success.

### 3.3 Conversation is not authorization
A user saying “yes” is meaningful only when it is bound to one explicit pending approval with a known action digest and current permissions. Voice cannot weaken this rule.

### 3.4 Manager orchestration first
Prefer one Rafii Manager Agent that calls specialists as tools. Use handoff only when a specialist genuinely needs to take over the conversational turn. The user should normally remain in a conversation with Rafii.

### 3.5 Deterministic before generative
Use deterministic code for permissions, entity resolution, date parsing where possible, action policy, proposal digests, state transitions, id validation, and truth checks. Use models for language, reasoning, synthesis, creative work, semantic interpretation, and planning.

### 3.6 Multimodality is contextual, not parallel
An image attached during voice mode belongs to the same task. A generated asset belongs to the same campaign/draft provenance chain. Do not create disconnected “image chats.”

## 4. OpenAI architecture decisions

### ADR-001 — GPT-Live-1 is the primary voice front-end
Use GPT-Live-1 for the natural voice experience because it is designed for full-duplex conversation, smooth interruption handling, and delegation to a backend agent.

GPT-Live handles spoken interaction. It is not the authoritative business agent.

Use client delegation so Rafii controls backend context, orchestration, permissions, app tools, and returned results.

Do not implement the primary experience as a simple STT → text LLM → TTS chain unless required as a fallback.

### ADR-002 — OpenAI Agents SDK is the backend agent runtime
Adopt the OpenAI Agents SDK for the backend orchestration layer:
- Agent / Runner;
- agents as tools;
- selective handoffs;
- function tools;
- guardrails;
- sessions;
- human-in-the-loop approval;
- tracing;
- testing utilities.

The existing deterministic site-agent logic remains valuable. Wrap or adapt it into tools and policies instead of deleting it.

### ADR-003 — GPT-Live does not directly receive images
GPT-Live-1 currently supports text and audio, not direct image input. Visual inputs must be routed to a vision-capable backend model through delegation.

Do not silently send images to the Live front-end.

### ADR-004 — GPT Image 2.5 is the creative image path
Use the Responses API image generation tool for conversational image workflows.
Default quality path: gpt-image-2.5-sunburst.
Default fast iteration path: gpt-image-2.5-flare.
Preserve existing image-provider abstractions where they are product requirements; do not break current routing.

### ADR-005 — Text and voice share the same backend manager
Text chat calls the Rafii Manager directly.
Voice calls GPT-Live-1, which delegates backend work to the same Rafii Manager.
Image analysis and generation also enter through the same Manager/task context.

### ADR-006 — Default reasoning model is configurable
Do not hard-code a model into business logic.

Provide environment/configuration aliases such as:
- RAFII_AGENT_PRIMARY_MODEL
- RAFII_AGENT_FAST_MODEL
- RAFII_AGENT_VISION_MODEL
- RAFII_AGENT_IMAGE_MODEL_QUALITY
- RAFII_AGENT_IMAGE_MODEL_FAST
- RAFII_LIVE_MODEL

For an OpenAI-first configuration, evaluate current production models such as gpt-6-sol for highest-complexity reasoning and a cheaper compatible model for low-risk classification/summarization. Keep existing writer/model selection compatibility.

Use aliases during development if desired. Pin a dated snapshot for production only after evals prove behavior.

### ADR-007 — No browser execution of privileged tools
The browser may transport audio and UI events, but business tools, secret-bearing connectors, permissions, proposal application, and state mutation must execute on trusted server infrastructure.

## 5. Target architecture

~~~
                              ┌─────────────────────────────┐
                              │         RAFII UI            │
                              │ text · voice · images · app │
                              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │                                                 │
          text / image / actions                            live microphone
                    │                                                 │
                    ▼                                                 ▼
        ┌──────────────────────┐                         ┌──────────────────────┐
        │  Rafii Agent API     │                         │     GPT-Live-1       │
        │ authenticated server │                         │ full-duplex voice    │
        └──────────┬───────────┘                         └──────────┬───────────┘
                   │                                                │
                   │                                      client delegation
                   │                                                │
                   └──────────────────────┬─────────────────────────┘
                                          ▼
                             ┌────────────────────────┐
                             │   RAFII MANAGER AGENT  │
                             │ OpenAI Agents SDK      │
                             └────────────┬───────────┘
                                          │
        ┌────────────┬────────────┬────────┼─────────┬────────────┬───────────┐
        ▼            ▼            ▼        ▼         ▼            ▼           ▼
      Brand       Content      Campaign  Publish   Research    Analytics   Creative
      agent        agent        agent     agent      agent       agent       agent
        └────────────┴────────────┴────────┴─────────┴────────────┴───────────┘
                                          │
                                          ▼
                             ┌────────────────────────┐
                             │  RAFII TOOL / POLICY   │
                             │ typed tools · HITL     │
                             └────────────┬───────────┘
                                          │
                                          ▼
                             ┌────────────────────────┐
                             │ APP SOURCE OF TRUTH    │
                             │ Postgres · providers   │
                             │ drafts · campaigns     │
                             │ reviews · automations  │
                             │ memory · audit · usage │
                             └────────────────────────┘
~~~

## 6. Runtime surfaces

### 6.1 Text surface
Keep the existing site-wide panel and conversation persistence.
Replace ad-hoc orchestration incrementally with the shared Agent Runtime behind its API.
A text request and delegated voice request must be able to produce the same tool plan for the same state.

### 6.2 Voice surface
Add a Voice Mode inside the existing Rafii panel plus an optional expanded immersive view.
Voice must be able to continue while the user navigates the app.
Voice must not create a separate conversation id unless the user explicitly starts a new conversation.

Required controls:
- start / end;
- mute / unmute microphone;
- speaker output state;
- interrupt / barge-in support;
- transcript visibility;
- typed input while voice remains connected;
- attach image/file while voice remains connected;
- compact tool/progress cards;
- visible pending approval card;
- reconnect/retry state;
- reduced-motion behavior;
- explicit microphone permission error;
- graceful text fallback.

### 6.3 Image surface
Images may enter through:
- attachment from text chat;
- attachment during voice mode;
- screenshot supplied by the app;
- existing Rafii asset;
- output of image generation/editing.

Every image item needs a stable application asset id, provenance, workspace scope, and relationship to the current task/campaign/draft where applicable.

## 7. GPT-Live voice implementation contract

### 7.1 Connection
For the browser, use WebRTC.
The OpenAI project key must never be exposed to the browser.
The application server authenticates the Rafii user and brokers the Live session using the official GPT-Live WebRTC flow.

Use a server-side sideband/control connection when needed for observability and control without routing microphone audio through the application server.

### 7.2 Delegation
Use client delegation.

GPT-Live prompt responsibilities:
- Rafii identity and concise speaking style;
- natural turn-taking;
- interruption behavior;
- when to ask the backend for help;
- how to acknowledge delegated work without inventing results;
- how to present confirmations conversationally;
- multilingual speaking behavior.

Backend prompt responsibilities:
- all business procedures;
- application state;
- permissions;
- action policy;
- tool choice;
- memory;
- campaign and brand reasoning;
- truth verification;
- structured result returned to Live.

Do not copy the giant backend prompt into the Live session.

### 7.3 Full-duplex behavior
Voice acceptance requires:
- user can interrupt Rafii while Rafii is speaking;
- Rafii stops or adapts without waiting for its audio to finish;
- a backend task may continue while the user keeps talking;
- follow-up speech can refine or cancel pending delegated work;
- Rafii does not claim the delegated task completed before verified backend result arrives;
- user can change subject and later return to the unfinished task.

### 7.4 Spoken confirmations
For a single low/medium-risk pending proposal, “yes,” “confirm,” or equivalent may approve only when:
- there is exactly one active approval request;
- Rafii just named the exact action and relevant target;
- proposal digest still matches;
- the authenticated role is still allowed;
- server re-check succeeds.

If two approvals are pending, voice must ask which one.
Never bind a generic “yes” to an old approval.
Destructive or policy-forbidden operations stay forbidden.

### 7.5 Languages
Voice must be tested in:
- English;
- Cantonese;
- Mandarin;
- code-switching between these languages.

Rafii should normally answer in the user’s current conversational language while preserving exact product/entity names where useful.
Do not create separate memories per language.

## 8. Unified Agent Runtime

Create a backend package that becomes the shared orchestration layer rather than duplicating text and voice logic.

Recommended location after discovery:
src/postriff_phase2/agent_runtime_v2/

Suggested modules:
- manager.py
- context.py
- models.py
- session.py
- policy.py
- guardrails.py
- approvals.py
- memory.py
- task_state.py
- tool_adapter.py
- tracing.py
- result_contracts.py
- specialists/
- evals/

Do not mechanically create this exact tree if the existing site_agent package has a cleaner integration point. First map the existing package and choose the smallest coherent migration.

The backend must expose one high-level operation:
“run a Rafii turn against authenticated workspace context.”

Inputs should include:
- conversation id;
- user/member identity;
- workspace id;
- modality;
- user text/transcript;
- page context;
- selected entity;
- attachments/assets;
- active task/proposal references;
- locale/timezone;
- model policy.

Outputs should be typed and surface-neutral.

## 9. Surface-neutral result contract

Define a structured result that can drive text UI, voice, and future mobile clients.

At minimum:
- answer_text;
- speakable_summary;
- references;
- citations/help references;
- stored-fact vs derived-observation labels;
- tool activity;
- progress steps;
- created/changed application entities;
- pending approvals;
- generated assets;
- warnings;
- recoverable errors;
- usage/cost summary;
- trace id.

Voice should normally speak “speakable_summary,” not a raw markdown answer.

The visual panel may render richer blocks from the same result:
- links;
- proposal cards;
- task checklist;
- image cards;
- citations;
- status chips;
- expandable technical details.

Do not make GPT-Live parse arbitrary markdown in order to know what happened.

## 10. Rafii Manager Agent

The Manager owns the user’s task and remains the default conversational agent.

Responsibilities:
1. understand the request in context;
2. resolve workspace references;
3. decide whether deterministic tools are enough;
4. decide whether specialist reasoning is needed;
5. plan multi-step work;
6. execute safe/read operations immediately;
7. produce or request artifacts through specialists;
8. stop at approval gates;
9. verify mutations by re-reading state;
10. return one coherent result.

The Manager must not call a specialist simply because one exists.
Prefer direct deterministic tools for simple questions.

The Manager may call multiple specialists when a request genuinely spans domains, but it remains accountable for synthesis and truth.

Use Agents-as-tools by default so the Manager retains the conversation.
Use handoff only for a reason documented in code and tests.

## 11. Specialist agents

### 11.1 Brand Intelligence Agent
Tools/context:
- Brand Brain;
- voice profile;
- learned preferences;
- prior approved examples;
- style rules and prohibited claims.

Capabilities:
- explain why text does/does not fit the user’s voice;
- compare draft against brand/voice traits;
- identify evidence for each judgment;
- separate explicit preferences from inferred patterns;
- produce structured revision guidance.

### 11.2 Content Agent
Capabilities:
- draft;
- rewrite;
- shorten/expand;
- adapt by platform;
- translate/localize;
- preserve source provenance;
- return new revision/draft rather than silently overwriting unless domain rules explicitly say otherwise.

### 11.3 Campaign Agent
Capabilities:
- campaign planning;
- content gaps;
- audience/platform mapping;
- campaign relationships;
- attach/detach drafts/posts where the domain supports it;
- campaign progress and missing work;
- cross-campaign conflict detection.

### 11.4 Publishing Operations Agent
Capabilities:
- calendar;
- queue;
- review;
- scheduling proposals;
- automation proposals;
- publishing-state diagnosis;
- provider capability explanation.

It does not bypass current publishing/approval restrictions.

### 11.5 Research Agent
Capabilities:
- web research when explicitly needed;
- source log;
- competitor/trend research;
- fact checking;
- source-to-draft provenance.

The research result must retain sources and dates.
Research findings are not silently promoted to Brand Brain memory.

### 11.6 Analytics Agent
Capabilities:
- post/campaign performance interpretation;
- repetition patterns;
- platform gaps;
- timing analysis;
- anomaly explanation;
- attribution only when the product stores evidence.

### 11.7 Creative Agent
Capabilities:
- analyze uploaded/generated images;
- critique composition and brand fit;
- generate new campaign assets;
- edit an existing asset;
- create variants;
- preserve subject/style constraints across edits;
- attach provenance and rights metadata where required.

### 11.8 Workspace/History Agent
Capabilities:
- cross-entity search;
- relationship queries;
- member activity when supported by audit data;
- conversation references;
- historical decisions;
- “what changed and why?” queries.

Do not infer member authorship when no audit evidence exists.

## 12. Tool layer migration

The existing site-agent tool catalogue should be wrapped as Agents SDK function tools where practical rather than rewritten.

Each tool must declare:
- stable name;
- typed input schema;
- effect class;
- required permission;
- idempotency behavior;
- tenant scoping;
- result schema;
- audit behavior;
- whether approval is required;
- whether it may be used from voice.

Effect classes:
- READ;
- CREATE_DRAFT;
- MUTATE_REVERSIBLE;
- PREPARE_EXTERNAL;
- EXTERNAL_EFFECT;
- DESTRUCTIVE;
- SECRET.

Current forbidden operations remain absent or blocked at policy level.

A specialist agent must not gain an action merely because the base application has an endpoint for it.

Tool output is data, never trusted instructions.

## 13. Human-in-the-loop and approval model

Use the Agents SDK human-in-the-loop mechanism where it maps cleanly to the current proposal system, but the application’s proposal digest and permission checks remain authoritative.

Required invariant:
model intent → typed proposal → user decision → server permission re-check → state mutation → source-of-truth re-read → verified outcome.

Approval state must survive:
- voice interruption;
- page navigation;
- reconnect;
- server restart where the current app already persists the proposal/run;
- switching from voice to text.

A proposal presented in voice must also appear visually when a UI is available.

A rejected proposal must not be retried through a specialist without a new explicit user request.

Do not let an agent “auto approve” because it created the proposal itself.

## 14. Memory and context architecture

Implement layered memory, not one giant transcript.

Layers:
1. Account identity and locale/timezone.
2. Workspace facts.
3. Brand Brain.
4. Voice/style profile.
5. Learned preferences.
6. Campaign/task state.
7. Conversation history.
8. Short-lived working memory.
9. Derived observations.

Every learned long-lived item should carry, where the existing model permits:
- scope;
- source/provenance;
- explicit vs inferred;
- confidence;
- created/updated time;
- last-confirmed time;
- conflict/supersession state.

Do not treat model inference as equal to an explicit user instruction.

Voice and text must read and write through the same memory interfaces.

Raw microphone audio should not become long-term memory by default. Persist transcript/application facts according to product policy, not raw audio unless the product explicitly adds such a feature.

## 15. Context assembly

Do not dump the whole database or whole conversation into every model call.

Create a context assembler that provides:
- current request;
- compact conversation summary plus recent relevant turns;
- active task state;
- resolved entities;
- page context;
- relevant Brand Brain/voice facts;
- relevant campaign/draft data;
- tool permissions;
- help/research excerpts only when needed.

Use relevance and explicit references to bound context.
Preserve exact ids in machine context, but avoid exposing opaque ids conversationally unless useful.

Context must distinguish:
- USER_INSTRUCTION;
- APP_STATE;
- MEMORY;
- TOOL_RESULT;
- HELP_CONTENT;
- EXTERNAL_SOURCE;
- MODEL_DERIVATION.

Untrusted content from pages, uploads, external sources, draft text, and tool output must be delimited as data and must not be able to redefine agent policy.

## 16. Task state and multi-step work

Add a first-class task plan for requests that need more than one meaningful action.

A step has:
- id;
- label;
- state: planned / running / done / needs_user / blocked / failed / canceled;
- dependencies;
- entity links;
- output refs;
- approval refs;
- timestamps.

Example:
1. Find launch campaign — done.
2. Analyze missing platforms — done.
3. Create Instagram draft — done.
4. Generate image — running.
5. Attach draft to campaign — done.
6. Schedule Thursday 18:00 — needs_user.

The UI should show this checklist while voice continues.

Safe independent steps may run without waiting for later gated steps.
A compound request must never silently drop a subtask.
If a task is impossible, report that step specifically rather than marking the whole plan complete.

## 17. Relationship graph

Build a queryable relationship layer over the product’s existing records.

Core nodes:
- campaign;
- source;
- idea;
- draft;
- draft revision;
- asset;
- review;
- scheduled job;
- published post;
- automation;
- account/channel;
- member;
- agent run;
- research source.

Core edges:
- derived_from;
- belongs_to_campaign;
- adapted_from;
- uses_asset;
- reviewed_by;
- scheduled_as;
- published_as;
- created_by_automation;
- modified_by;
- informed_by;
- supersedes.

Start by deriving edges from existing normalized records.
Add a migration only for relationships that the domain cannot represent reliably, such as first-class draft↔campaign association if still absent.

Do not create a generic opaque graph store before proving existing relational data is insufficient.

## 18. “Does this sound like me?” capability

This is a required feature, not a help-text answer.

Flow:
1. retrieve explicit voice profile;
2. retrieve relevant learned style evidence;
3. retrieve a small set of approved examples;
4. compare target sentence/draft;
5. produce structured trait-level findings;
6. cite the evidence category for every finding;
7. distinguish deterministic facts from model judgment;
8. optionally create a revised version through Content Agent.

Example output structure:
- Matches: concise opening; low emoji use.
- Mismatch: sentence uses promotional superlatives not present in approved examples.
- Evidence: explicit preference / learned pattern / examples.
- Confidence: high / medium / low.
- Suggested revision: separate artifact.

Never claim “this is exactly your voice.”
Do not learn a new preference merely because one generated draft used it.

## 19. Vision and image understanding

When a user supplies an image during text or voice:
1. store/resolve the workspace-scoped asset;
2. pass image plus task context to a vision-capable backend model;
3. return structured findings to the Manager;
4. let GPT-Live speak the concise result when in voice mode.

Required visual capabilities:
- describe the design;
- inspect composition;
- identify visible text;
- compare to Brand Brain creative rules;
- compare two variants;
- reason about aspect ratio/platform fit;
- identify missing/weak CTA visually;
- use the image as a reference for generation/editing;
- relate the asset to the current campaign/draft.

Do not send confidential unrelated workspace state with an image call.
Do not pretend to see pixels that the backend never received.

## 20. Image generation and editing

Primary conversational path: Responses API image generation tool.

Model policy:
- quality/edit precision: gpt-image-2.5-sunburst;
- fast iteration: gpt-image-2.5-flare;
- model ids configurable.

Required operations:
- generate from text;
- generate from campaign/Brand Brain brief;
- edit supplied/existing image;
- continue multi-turn edit lineage;
- create variants;
- save result to the Rafii asset library;
- attach to draft/campaign when requested;
- preserve original asset;
- record model, prompt summary, source assets, and parent revision.

Image changes should be non-destructive by default.

While in voice mode:
User: “Move the subject left and make the headline quieter.”
Rafii delegates the image edit, keeps the conversation active, then announces the verified result and renders the new image card.

Never make image generation completion depend on the voice model producing the image itself.

## 21. Model router

Implement a policy-driven model router with explicit reasons, not ad-hoc if-statements scattered across features.

Suggested workload classes:
- deterministic: no model;
- fast language: inexpensive model;
- standard reasoning;
- deep reasoning;
- vision;
- voice front-end;
- image-fast;
- image-quality.

Routing inputs:
- task type;
- requested quality;
- latency sensitivity;
- selected user model where applicable;
- budget/entitlement;
- modality;
- context size;
- required tool support.

Record route decision in the trace.

Do not silently fall back to a paid model/provider that the current product policy forbids.
When a required model is unavailable, produce a truthful fallback or blocker.

## 22. Proactive intelligence

Rafii should become proactive without becoming autonomous in unsafe ways.

Sources:
- calendar gaps;
- pending reviews;
- failed/held jobs;
- campaign deadlines;
- repeated content;
- platform neglect;
- missing assets;
- campaign/draft inconsistency;
- unhandled research;
- expiring or stale work;
- unanswered approval requests.

Separate:
A. deterministic signals;
B. model-derived recommendations.

Every proactive recommendation must show enough evidence to inspect.
Do not manufacture urgency.
Do not perform external effects without the same normal approvals.

Add a “What should I pay attention to?” path that can synthesize multiple sources into a prioritized explanation without inventing facts.

## 23. Agent self-correction and verification

For every mutation:
1. execute through the domain service/tool;
2. read the resulting object again from authoritative storage;
3. compare intended vs actual state;
4. only then report success.

If verification differs:
- report partial/failed state;
- preserve ids and audit trail;
- do not have the model cosmetically rewrite it as success;
- suggest the next safe action.

For external publishing/provider work, preserve current receipt semantics:
prepared ≠ scheduled ≠ sent ≠ provider-accepted ≠ verified-published.

The agent must use exact product states rather than collapsing them into “done.”

## 24. Member activity and attribution

Implement a grounded member-activity reader only from stored audit/activity evidence.

Questions:
- “What did Alex do this week?”
- “Who approved this?”
- “Who changed this automation?”
- “What did Alex post?”

Return:
- attributable events;
- timestamps;
- linked entities;
- action type;
- source audit evidence.

If a post lacks enough data to attribute it to a person, say so.
Never infer a member from writing style, login recency, or nearby events.

Scope by workspace and viewer permissions.

## 25. Draft ↔ campaign linkage

Close the current K05/X03 capability gap with a real domain operation.

Required commands:
- add this draft to Campaign X;
- remove this draft from Campaign X;
- which campaign is this draft in?;
- show drafts in Campaign X;
- add these two posts/drafts to the launch campaign.

First inspect the existing campaign schema.
If a normalized relation already exists, expose it.
If not, add the smallest coherent migration and domain service.

Do not encode campaign membership in free text, tags, or agent memory.
Audit attach/detach events.
Ensure compound requests can use the relation before reaching a later scheduling approval.

## 26. API and transport work

Add narrowly scoped endpoints after repository discovery.

Likely server responsibilities:
- start authenticated GPT-Live WebRTC session;
- authorize session workspace/conversation;
- accept client delegation requests;
- stream delegated task progress;
- submit/cancel task;
- approve/reject pending action;
- upload/resolve conversational asset;
- generate/edit image;
- resume conversation/task state.

Do not expose the OpenAI project key.
Do not put secret-bearing tool configuration in client JavaScript.

Use existing request guard, origin checks, authentication, workspace authorization, and audit conventions.

Prefer existing site-agent routes for text turns where compatible rather than creating a parallel “v2 chat” API that forks behavior.

## 27. Frontend implementation

Recommended feature additions under the current site-agent UI:
- voice launcher state;
- live session store;
- transcript timeline integration;
- audio level / speaking state;
- delegated task activity;
- multimodal composer;
- attachment cards;
- generated image cards;
- task checklist;
- pending approval card;
- reconnect banner;
- voice settings;
- privacy disclosure.

The same answer timeline should render messages produced by text or voice.

Do not maintain a second “voice history” store.

Page navigation must not tear down the voice session unless the user ends it or the session cannot survive the app lifecycle.

On mobile:
- account for safe areas;
- keep controls reachable;
- avoid iOS input zoom;
- handle interruption from phone audio/session changes gracefully;
- restore to text mode if voice cannot resume.

Reduced motion must suppress decorative avatar/speaking animation without disabling essential state feedback.

## 28. Rafii character and voice UI

The animated Rafii character is presentation, not runtime authority.

States may include:
- idle;
- listening;
- thinking/delegated work;
- speaking;
- waiting for approval;
- error/reconnect.

Character animation failure must not break Voice Mode.
Always provide a static/reduced-motion fallback.

Do not block the agent-runtime release on the separate video-generation balance issue.
The existing still assets may ship with the new voice runtime.

Voice speaking state should be driven by actual session events, not guessed timers.

## 29. Security and privacy

Required invariants:
- tenant isolation on every tool and asset;
- server-held API credentials;
- no secrets sent into prompts unless an explicitly approved tool requires them and the model does not receive raw secret value;
- proposal/action digest prevents stale or substituted approval;
- permission re-check at execution;
- current destructive-action policy preserved;
- prompt injection boundaries preserved for drafts, web content, uploaded files, help articles, and provider output;
- uploaded images treated as untrusted data;
- model output cannot invent app links or ids;
- trace/log redaction;
- no raw microphone persistence by default;
- no silent biometric/identity inference from voice;
- no voice-based member authentication;
- no cross-workspace memory.

Add security tests specifically for modality switching:
voice request → text approval;
text proposal → voice approval;
image prompt injection → tool request;
voice interruption during approval;
stale approval after navigation/reconnect.

## 30. Observability and tracing

Use OpenAI Agents SDK tracing where policy allows, plus Rafii’s own application audit/usage records.

Every agent run should have one correlation id across:
- frontend conversation event;
- Live delegation if any;
- manager run;
- specialist runs;
- tool calls;
- approval interruptions;
- application mutation;
- verification read;
- usage/cost;
- final result.

Record:
- selected model;
- reasoning route;
- tool names and duration;
- specialist calls;
- handoffs if any;
- retries;
- guardrail trips;
- approval wait time;
- final application state;
- error class.

Never log access tokens, raw credentials, or unredacted secret-bearing provider responses.

Provide developer-visible trace links/ids in local/dev mode, not noisy end-user UI.

## 31. Evaluation strategy

This upgrade is not complete when a demo works.

Create a versioned eval suite with categories:
1. text regression;
2. voice conversation;
3. interruption/barge-in;
4. delegation;
5. multilingual voice;
6. multimodal image understanding;
7. image generation/editing;
8. cross-modal continuity;
9. memory/provenance;
10. multi-step planning;
11. approval/HITL;
12. permissions;
13. hallucination/missing data;
14. provider failure;
15. reconnection;
16. accessibility;
17. cost/latency;
18. security/injection;
19. inspectability;
20. source-of-truth verification.

Keep the existing 79 scenario suite and browser suite as regression baseline.
Extend; do not replace with weaker checks.

## 32. Voice evaluation scenarios

At minimum:
- V-A01: start voice, ask current page, correct answer;
- V-A02: navigate while speaking, context updates;
- V-A03: interrupt Rafii mid-sentence, old audio stops;
- V-A04: backend tool runs while user keeps talking;
- V-A05: user refines delegated request before completion;
- V-A06: user says “cancel that,” task cancels if cancellable;
- V-A07: one pending proposal, spoken confirmation applies exactly it;
- V-A08: two pending proposals, generic “yes” must not apply either;
- V-A09: voice ends, text continues same conversation;
- V-A10: text starts task, voice continues same task;
- V-A11: Cantonese conversation;
- V-A12: Mandarin conversation;
- V-A13: code-switching;
- V-A14: mic permission denied, text fallback works;
- V-A15: Live API disconnect, UI recovers truthfully;
- V-A16: backend model error, voice does not hallucinate completion;
- V-A17: user speaks while image generation runs;
- V-A18: voice-generated approval survives page navigation;
- V-A19: reduced motion and screen-reader labels;
- V-A20: no privileged tool executes in browser.

Capture transcript and event evidence without persisting raw audio unless test harness explicitly needs a fixture.

## 33. Multimodal evaluation scenarios

At minimum:
- MM01: upload screenshot and ask what is wrong;
- MM02: same screenshot discussed by voice;
- MM03: generate image from campaign brief;
- MM04: edit generated image with one change while preserving the rest;
- MM05: edit an uploaded image;
- MM06: create fast variants with Flare;
- MM07: create final-quality asset with Sunburst;
- MM08: generated asset is saved with provenance;
- MM09: attach generated asset to draft where supported;
- MM10: user references “the second image” later;
- MM11: switch from image discussion to text then voice without losing reference;
- MM12: image contains prompt-injection text; policy is not changed;
- MM13: image generation fails; no fake asset id or success claim;
- MM14: another workspace’s asset is unreachable;
- MM15: image rights/required publishing checks remain enforced.

Add pixel/visual snapshot tests only where stable; prefer semantic assertions for model-generated content.

## 34. Agents SDK testing

Use the SDK’s deterministic testing utilities for orchestration owned by Rafii:
- scripted model responses;
- tool execution;
- guardrails;
- sessions;
- handoffs;
- approval interruptions;
- retry behavior;
- event normalization.

Use live integration tests only for behavior owned by the external model/API:
- actual GPT-Live audio;
- real WebRTC;
- live vision quality;
- live image generation;
- current provider transport.

Do not make the normal unit suite depend on paid live model calls.

Create budget-capped, opt-in live verification commands with explicit environment guards.

## 35. Performance targets

Measure rather than guess.

Voice:
- connection establishment;
- time to first audible response;
- interruption stop latency;
- delegated-result latency;
- reconnect time.

Text:
- first UI feedback;
- first streamed token/event;
- tool completion;
- total turn.

Image:
- request accepted;
- first progress event if available;
- final asset stored.

The UI must immediately show that a task/delegation started even when deep reasoning takes longer.

Long backend work must not freeze the voice conversation.

Do not sacrifice truthful verification merely to report an artificially low latency number.

## 36. Cost controls

Track usage by:
- voice session duration;
- backend model tokens;
- image input/output;
- generated images;
- hosted tools;
- external providers.

Use application entitlements and current ledger conventions.

Add:
- per-run cost estimate;
- final settled cost;
- model route;
- user-visible limit behavior where the product already exposes usage.

Do not automatically escalate every query to the largest model.
Use deep reasoning for tasks that need it, not greetings or deterministic reads.

Do not silently route to another paid provider when a budget/entitlement blocks the chosen route.

## 37. Failure semantics

Every failure must map to a truthful state:
- model unavailable;
- voice transport disconnected;
- mic unavailable;
- permission denied;
- tool validation failed;
- application conflict;
- stale proposal;
- image generation failed;
- asset storage failed;
- external provider failed;
- budget/entitlement blocked;
- user canceled;
- task partially completed.

The assistant must say what completed and what did not.

A failed voice response must not erase completed backend work.
A failed image save must not present a transient base64 image as a persisted Rafii asset.
A reconnect must not replay an already-applied mutation.

## 38. Data/migration policy

Before adding tables:
1. inspect current Postgres schema;
2. inspect JSON/event fields already used by conversations/runs;
3. reuse existing normalized records where semantically correct;
4. add only the smallest required migration.

Potential reasons for a migration:
- first-class draft↔campaign association;
- durable task-plan state if current run/event storage cannot support resume;
- durable multimodal asset lineage if current asset schema cannot represent it.

Do not create duplicate conversation, member, campaign, or usage ledgers.

Every migration must have:
- forward migration;
- rollback or safe compatibility strategy;
- tests;
- existing-data behavior;
- tenant constraints/indexes;
- no destructive rewrite unless explicitly approved.

## 39. Compatibility requirements

Do not break:
- existing provider/model selector;
- preview writer;
- existing Brand Brain;
- existing Voice Profile learning;
- current automation engine;
- current approval workflow;
- existing publishing providers;
- site-agent help system;
- route manifest;
- current mobile/tablet/desktop layouts;
- current Vercel/server runtime assumptions unless an explicit architecture change is justified;
- current test harness.

If OpenAI Agents SDK requires a new Python dependency, add and pin it according to repository conventions.
If browser packages are required, prefer the official @openai/agents package and keep secret-bearing tool execution server-side.

Avoid forcing the entire app onto a new framework just for voice.

## 40. Implementation work packages

### WP00 — Discovery and architecture lock
- read repository instructions and current branch;
- inspect site_agent package, hosted routes, ideas.py, writer/model runtime, memory, campaigns, assets, usage, audit;
- inspect current web panel/store;
- inspect concurrent branch risks;
- write ADR summary based on actual repo;
- confirm package/runtime compatibility;
- produce exact file-change plan.

Exit: architecture maps to real code and no duplicate subsystem is proposed.

### WP01 — Agents SDK foundation
- add SDK dependencies;
- create shared Manager runtime;
- define typed context/result;
- wrap a small subset of read-only site-agent tools;
- prove text parity on existing scenarios;
- add tracing correlation id.

Exit: existing text requests can run through the new manager in a feature-gated path.

### WP02 — Tool adapter and policy bridge
- adapt the existing tool catalogue;
- map permissions/effect classes;
- connect existing proposal system to HITL interruptions;
- preserve proposal digest;
- add source-of-truth verification wrapper;
- add agent/tool regression tests.

Exit: no privileged behavior bypasses current policy.

### WP03 — Unified sessions, context, memory, task state
- shared conversation across text/voice;
- active-task state;
- layered context assembler;
- memory provenance/confidence;
- cross-modal references;
- durable pending approvals.

Exit: a task can begin in text and continue through another surface without losing references.

### WP04 — GPT-Live transport
- authenticated Live session endpoint;
- browser WebRTC;
- client delegation bridge;
- short Live prompt;
- sideband/server controls if required;
- interruption/cancel/reconnect state;
- usage accounting.

Exit: user can hold a natural spoken conversation while backend work runs.

### WP05 — Voice UX
- integrate controls into Rafii panel;
- immersive optional view;
- transcript and text input;
- page navigation continuity;
- tool/progress cards;
- spoken + visual approvals;
- multilingual handling;
- accessibility and reduced motion.

Exit: desktop/tablet/phone browser QA passes.

### WP06 — Vision and image runtime
- attachment model;
- asset resolution;
- vision delegation;
- Responses image-generation tool;
- Sunburst/Flare routing;
- image editing lineage;
- save/attach to workspace;
- image failure semantics.

Exit: generate, inspect, edit, save, and continue the image conversation in text and voice.

### WP07 — Specialist agents
- Brand Intelligence;
- Content;
- Campaign;
- Publishing Operations;
- Research;
- Analytics;
- Creative;
- Workspace/History.

Exit: specialists are agents-as-tools with clear scope and Manager-controlled synthesis.

### WP08 — Capability gaps
Close current partial scenarios:
- voice-fit analysis;
- live rewrite/shorten;
- draft↔campaign relationship;
- compound request chaining;
- member activity attribution where evidence exists.

Add tests before calling each gap complete.

### WP09 — Relationship graph and proactive intelligence
- derive graph;
- expose graph queries;
- task/campaign gap synthesis;
- proactive recommendations with evidence;
- no autonomous external effects.

### WP10 — Security, guardrails, observability
- input/output/tool guardrails;
- cross-modal injection tests;
- trace correlation;
- cost settlement;
- secret redaction;
- modality-switch approval tests.

### WP11 — Evals and live provider verification
- deterministic agent tests;
- expanded Postgres scenarios;
- browser QA;
- virtual/fake audio tests;
- opt-in real GPT-Live verification;
- opt-in image generation verification;
- latency/cost evidence.

### WP12 — Integration and release readiness
- rebase/merge risk review;
- three-way comparison of shared ideas.py changes;
- full regression suite;
- regenerated matrix;
- documentation;
- commit series;
- merge recommendation;
- no production deployment unless explicitly authorized.

## 41. Feature flags

Ship incrementally behind explicit flags, for example:
- RAFII_AGENT_V2_ENABLED
- RAFII_VOICE_ENABLED
- RAFII_IMAGE_AGENT_ENABLED
- RAFII_SPECIALISTS_ENABLED
- RAFII_PROACTIVE_V2_ENABLED

Flags must not create two incompatible data models.
They may select runtime path, but conversations and stored state remain compatible.

Provide safe fallback to existing site-agent behavior when a new runtime feature is disabled.

## 42. Definition of done

The project is not “done” because it speaks.

Required completion criteria:

Architecture:
- one shared backend Manager powers text and voice delegation;
- no parallel memory/permission/business-logic stack.

Text:
- current site-agent scenarios remain green;
- no regression in grounding, links, permissions, proposals, browser layout.

Voice:
- real GPT-Live session verified;
- full-duplex interruption verified;
- backend delegation verified;
- conversation continues while backend works;
- same conversation persists across text/voice;
- spoken approval binds exactly to current proposal;
- multilingual cases verified.

Multimodal:
- image upload/analysis works;
- image generation works;
- image edit works;
- generated asset persists with provenance;
- image context continues across text and voice.

Agent intelligence:
- specialist delegation works;
- multi-step plan tracks every requested step;
- “sounds like me” gives evidence-based analysis;
- draft↔campaign linking is real;
- member attribution is grounded;
- proactive recommendations cite evidence.

Safety:
- tenant isolation;
- current forbidden actions remain forbidden;
- cross-modal injection tests pass;
- secrets remain redacted;
- no privileged browser tool execution.

Verification:
- 0 FAIL in final acceptance matrix;
- PARTIAL allowed only for a documented external dependency, not an unimplemented core requirement.

## 43. Final verification commands/results to report

The coding agent must report exact commands and outcomes for:
- whole-repo Python unit tests;
- whole PostgreSQL suite;
- site-agent scenario suite;
- new Agent Runtime tests;
- voice deterministic tests;
- multimodal tests;
- web contract tests;
- typecheck;
- lint;
- production build;
- secret scan;
- Chromium browser QA;
- WebKit browser QA;
- accessibility scan;
- inspectability/link validation;
- opt-in live GPT-Live smoke test;
- opt-in live backend model test;
- opt-in image generation/edit test.

For paid live tests, record model and usage but never print API keys.

Regenerate verification documentation from machine-readable evidence where possible.

A failing assertion is FAIL. Do not weaken the assertion or re-label it to make the report green.

## 44. Git and concurrent-work rules

Work on the existing raffi/site-agent worktree unless a separate integration worktree is required.

Before editing shared files:
- inspect git status;
- inspect worktrees;
- identify concurrent branches;
- compare origin/main and the site-agent branch;
- do not overwrite another session’s uncommitted work.

ideas.py is known shared-risk code.
Preserve both:
- Home quick-start current-idea fix;
- weekday/rework classification fix;
plus any newer concurrent changes.

Use small, coherent commits by work package when practical.

Do not push, merge, or deploy production merely because implementation tests pass. Final push/merge/deploy requires explicit owner authorization.

Never commit secrets, generated credentials, raw audio, huge temporary media, local .next artifacts, or live provider fixtures.

## 45. What not to build

Do not:
- create one giant prompt pretending to be an architecture;
- give every specialist unrestricted access to every tool;
- build dozens of agents for simple deterministic operations;
- create a separate Voice Rafii memory;
- use speech transcript as authentication;
- allow Voice Mode to bypass proposal confirmation;
- put the OpenAI project key in browser code;
- run secret-bearing business tools in the browser;
- trust model claims of mutation success;
- store raw microphone audio by default;
- use agent memory as campaign membership;
- let image generation overwrite originals;
- make the animated character a release blocker for the agent runtime;
- duplicate existing tables without proving need;
- replace a working verified site-agent subsystem just for aesthetic architectural purity.

The goal is greater intelligence with stronger coherence, not complexity for its own sake.

## 46. Recommended first vertical slice

Before implementing every specialist, prove the architecture with one complete cross-modal workflow:

Scenario:
1. Open a campaign.
2. Start Voice Mode.
3. Ask Rafii what is missing.
4. Rafii delegates to Manager while continuing spoken conversation.
5. User uploads a reference image.
6. Rafii’s backend vision analyzes it.
7. User asks for a new Instagram asset in Brand Brain style.
8. Creative Agent generates it.
9. Content Agent drafts matching copy.
10. Campaign Agent attaches draft and asset to the campaign.
11. User asks to schedule Thursday 18:00.
12. Rafii presents a proposal visually and verbally.
13. User confirms.
14. Application re-checks permission, applies, re-reads state.
15. Rafii reports exact verified result.
16. End voice and continue by text; all context remains.

This vertical slice proves voice, delegation, vision, image generation, specialists, app tools, approval, verification, memory, and cross-modal continuity in one workflow.

Do this before scaling the same pattern everywhere.

## 47. Current official OpenAI references

Verified on 2026-09-24. Re-check before implementation because API surfaces can change.

GPT-Live:
https://developers.openai.com/api/docs/guides/live
https://developers.openai.com/api/docs/guides/live-delegation
https://developers.openai.com/api/docs/guides/live-prompting
https://developers.openai.com/api/docs/guides/live-conversations
https://developers.openai.com/api/docs/models/gpt-live-1
https://developers.openai.com/api/docs/guides/voice-webrtc
https://developers.openai.com/api/docs/guides/voice-agents

Agents SDK:
https://openai.github.io/openai-agents-python/
https://openai.github.io/openai-agents-python/tools/
https://openai.github.io/openai-agents-python/human_in_the_loop/
https://openai.github.io/openai-agents-python/tracing/
https://openai.github.io/openai-agents-python/testing/
https://openai.github.io/openai-agents-python/handoffs/
https://openai.github.io/openai-agents-python/running_agents/

TypeScript Agents SDK / realtime reference:
https://openai.github.io/openai-agents-js/
https://openai.github.io/openai-agents-js/guides/voice-agents/
https://openai.github.io/openai-agents-js/guides/voice-agents/transport/

Image and model references:
https://developers.openai.com/api/docs/guides/image-generation
https://developers.openai.com/api/docs/guides/tools-image-generation
https://developers.openai.com/api/docs/guides/image-prompting
https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst
https://developers.openai.com/api/docs/models
https://developers.openai.com/api/docs/guides/latest-model

Important current facts:
- GPT-Live-1 is full duplex, handles natural voice, and delegates backend reasoning/tool work.
- GPT-Live-1 does not directly accept image input; send visual context to a vision-capable backend.
- Browser voice should use WebRTC.
- The application remains responsible for permissions, confirmations, business records, and task state.
- OpenAI Agents SDK provides tools, agents-as-tools, handoffs, guardrails, sessions, HITL, tracing, and deterministic testing utilities.
- The Responses API image generation tool supports conversational image generation/editing with GPT Image models.
- GPT Image 2.5 Sunburst is the high-quality/edit-precision path; Flare is the fast path.

## 48. Final engineering instruction

Treat this document as the governing target architecture for the Rafii Agent upgrade.

When actual repository facts conflict with an implementation detail suggested here:
1. preserve the product invariants;
2. inspect the real code;
3. choose the smallest coherent integration;
4. document the deviation and reason;
5. keep tests and evidence stronger, not weaker.

The success criterion is simple:
Rafii should feel like one intelligent coworker that can listen, speak, see, create, reason, remember, use the app, ask for approval, verify its own work, and continue seamlessly across modalities without becoming less safe or less truthful.

