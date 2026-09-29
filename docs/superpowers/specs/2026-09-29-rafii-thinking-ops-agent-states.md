# Rafii ThinkingOps — semantic agent-state system using thinking-orbs

**Date:** 2026-09-29  
**Status:** Approved engineering specification / not implemented  
**Repository:** `dev-james0723/PostRiff`  
**Base:** `consumer-saas`  
**Upstream visual system:** https://github.com/Jakubantalik/thinking-orbs  
**Inspected package:** `thinking-orbs@0.3.1` (MIT)

## 1. Goal

Replace Rafii's generic "thinking/loading" indicators with a truthful semantic state system driven by what the agent is actually doing.

The product-level system has **10 ThinkingOps**:

1. `working`
2. `searching`
3. `solving`
4. `listening`
5. `connecting`
6. `weaving`
7. `composing`
8. `breathing`
9. `shaping`
10. `acting`

The first nine are rendered directly with the official `thinking-orbs` React component and its official states. The tenth, `acting`, is a Rafii semantic state only. It MUST NOT introduce copied, reimplemented, or invented orb geometry. Its visual is a short sequence of two official states, `connecting → working`, while the accessible label remains "Taking action…".

The important requirement is not visual decoration. **The animation must be a truthful view of the current application-owned runtime phase.** Rafii must never cycle states randomly or infer a state from generated prose.

## 2. Verified current architecture

The implementation must begin from current `consumer-saas`, not an older Agent Chat branch.

### 2.1 Current Agent Chat UI

Relevant files:

- `web/src/features/agent/conversation-view.tsx`
- `web/src/features/agent/activity-strip.tsx`
- `web/src/features/agent/use-run.ts`
- `web/src/components/agents/loading-states/agent-progress.tsx`
- `web/src/components/agents/loading-states/thinking-shimmer.tsx`
- `web/src/lib/agent-runtime/client.ts`
- `web/src/lib/agent-runtime/types.ts`

Today, `conversation-view.tsx` uses generic loading UI:

- queued → ASCII/Braille `Loader` + `ThinkingShimmer`
- other active stages → `StageProgress`, backed by the custom 3×3 `AgentProgress`
- site-agent pending answer → `ThinkingShimmer`
- the safe-event contract already carries `progress.updated` with `stage`

Current legacy stage labels include `writing`, `drafting`, and `image_generation`.

### 2.2 Agent Runtime V2 is currently synchronous at the HTTP boundary

`web/src/lib/agent-runtime/client.ts` calls:

`POST /api/workspaces/{workspace}/agent/turns`

and awaits the whole `AgentTurnResponse`.

On the backend:

- `src/postriff_phase2/agent_runtime_v2/service.py` opens a `pr_agent_runs` row and writes `run.started`.
- Manager + specialists + tools run before the POST returns.
- `toolActivity` is currently assembled into the final result after the turn.
- `src/postriff_phase2/agent_runtime_v2/context.py` records completed tool activity into the `EffectLedger`.
- `src/postriff_phase2/agent_runtime_v2/tool_adapter.py` is the central gate for every typed tool.
- `src/postriff_phase2/agent_runtime_v2/manager.py` wraps every model call through `metered(...)`.
- Existing safe run events are stored in `public.pr_agent_events` through `IdeasService._insert_event`.

Therefore, merely swapping the spinner for an orb would be misleading. The browser currently does not know, while a V2 turn is in flight, whether Rafii is searching, composing, shaping, or acting.

### 2.3 Existing event infrastructure should be reused

Existing safe event families already include:

- `run.started`
- `progress.updated`
- `source.added`
- `artifact.created`
- `message.delta`
- `message.completed`
- `warning.created`
- `action.proposed`
- `run.completed`
- `run.failed`
- `run.cancelled`

The Ideas runtime already stores these in `pr_agent_events` with monotonically increasing sequence numbers. There is no need for a new table or migration.

## 3. Non-goals

This work MUST NOT:

- expose model chain-of-thought, hidden reasoning tokens, prompts, or raw tool arguments;
- change what Rafii is allowed to read or mutate;
- add a new model call;
- alter credit/budget policy;
- bypass approval or publishing safeguards;
- make Agent Runtime V2 asynchronous;
- replace the existing run/task/activity audit trail;
- replace the Thread Map music-reactive rail;
- copy or redraw `thinking-orbs` source animation geometry;
- invent a tenth upstream orb.

## 4. Upstream visual dependency contract

### 4.1 Package

Add an exact dependency, not a range:

```json
"thinking-orbs": "0.3.1"
```

Update the committed web lockfile in the same change.

Use the public React component:

```tsx
import { ThinkingOrb, type OrbState } from 'thinking-orbs';
```

Do not product-code against `MODE_DRAWS` or other package internals. The engine export was useful for the review lab, but the production integration should use the supported React surface.

### 4.2 Sizes

Use the package's tuned sizes rather than arbitrary canvas scaling:

- **20px** for inline chat/status indicators
- **64px** for Voice Mode / prominent focused-agent state

Do not scale a 64px profile down to 20px in CSS.

### 4.3 Reduced motion

Production MUST respect the package's normal reduced-motion behavior.

The previous review playground intentionally bypassed reduced motion so its animations could always be inspected. That exception does not apply to the product.

### 4.4 Attribution

Keep the dependency and MIT license metadata intact. Add a short attribution in the engineering doc or third-party notices if the repo has such a file. Do not add marketing copy or visible attribution in the user UI unless otherwise required.

## 5. Product ThinkingOp type

Create one app-owned semantic enum:

```ts
export type ThinkingOp =
  | 'working'
  | 'searching'
  | 'solving'
  | 'listening'
  | 'connecting'
  | 'weaving'
  | 'composing'
  | 'breathing'
  | 'shaping'
  | 'acting';
```

Recommended file:

`web/src/components/agents/thinking/thinking-op.ts`

Mirror the enum server-side in one module:

`src/postriff_phase2/agent_runtime_v2/thinking_state.py`

The semantic enum belongs to Rafii. The visual renderer then maps it to official `thinking-orbs`.

## 6. The 10 ThinkingOps and exact product meaning

| ThinkingOp | Official visual | Rafii meaning | Primary triggers |
|---|---|---|---|
| `working` | `working` | generic active work where a more specific state is not known | run opening, unknown tool, queue/wait, safe fallback |
| `searching` | `searching` | retrieving or looking up evidence | web research, help/content/workspace search, approved-source retrieval |
| `solving` | `solving` | planning, analysis, comparison, diagnosis, constraint resolution | Manager reasoning, task planning, campaign/publishing/analytics reasoning |
| `listening` | `listening` | Voice Mode is receiving the person's speech/audio input | microphone input / speech-in-progress |
| `connecting` | `connecting` | establishing a real connection/session/handshake | voice session setup, connector/OAuth/session/provider handshake |
| `weaving` | `weaving` | synthesising multiple evidence streams into one answer | Manager synthesis after multiple tools/specialists/evidence categories |
| `composing` | `composing` | creating or rewriting language/content | Content specialist, draft create/rewrite, legacy writing/drafting |
| `breathing` | `breathing` | Rafii is ready and present but not currently executing a turn | Voice Mode idle/ready between utterances |
| `shaping` | `shaping` | forming a visual/structured creative artifact | Creative specialist, image analyse/generate/edit/variant, image generation |
| `acting` | **official `connecting → working` sequence** | carrying out an allowed side-effect that changes state | verified reversible mutation, accepted proposal application, safe local client action |

### 6.1 Acting is deliberately not "publishing"

Rafii's current Agent Runtime forbids or gates many high-risk effects. `acting` means only that an **already-authorized application action is currently executing**.

Examples that may use `acting` when the existing permission/approval system allows them:

- applying a person-confirmed proposal;
- reversible campaign membership changes;
- a draft edit/save;
- a safe in-app navigation/guide action when it actually executes client-side.

A mere proposal MUST NOT show `acting`. It is still `solving` until the person authorizes an application action.

## 7. State source-of-truth

The browser must not classify state from generated text.

State is selected by a small, deterministic, app-owned resolver from known runtime facts:

1. Voice/client session state
2. Current typed tool execution
3. Current specialist/model role
4. Manager synthesis phase
5. Generic run state fallback

### 7.1 Precedence

When multiple signals exist:

1. explicit local voice transport state (`connecting`, `listening`)
2. explicit current tool semantic state
3. specialist semantic state
4. Manager synthesis state
5. `working` fallback

`breathing` is only valid when no run is active and the Voice surface is ready.

Do not keep `listening` on screen while the backend is actively handling a delegated request.

## 8. Backend semantic-state emitter

### 8.1 New module

Add:

`src/postriff_phase2/agent_runtime_v2/thinking_state.py`

Responsibilities:

- define the allowed semantic op enum;
- map typed tools/specialists/workloads to an op;
- build safe `progress.updated` events;
- deduplicate consecutive identical ops;
- never accept free-form user/model text as a state;
- cap reason codes to a fixed allowlist.

Recommended event body:

```json
{
  "type": "progress.updated",
  "stage": "agent_state",
  "thinkingOp": "searching",
  "thinkingSource": "tool",
  "reasonCode": "web_research"
}
```

All values above are fixed application enums. No prompt, query, URL, input text, output text, secret, file path, account identifier, or raw arguments may be included.

### 8.2 Context hook

Extend `RafiiRunContext` with an optional safe event emitter, for example:

```py
thinking_emit: Callable[[dict], None] | None = None
last_thinking_op: str | None = None
```

and a method:

```py
ctx.thinking(op, source, reason_code)
```

It should:

- validate `op`;
- no-op when the feature flag is off;
- no-op when identical to the previous op;
- write through the existing `IdeasService._insert_event` path in a short transaction;
- silently stop emitting when the run is no longer `running`;
- never let telemetry failure crash or change a user task.

Maximum semantic-state events per turn: **32**. This is far below the existing 2,000-event run limit.

### 8.3 Turn opening

After `run.started`, emit `working` immediately.

If the request is already deterministically known to be a planning/analysis command, `solving` may replace it as the first semantic state, but do not add a model call just to classify it.

## 9. Tool mapping

Put the mapping in one server module. Do not scatter string comparisons across UI components.

### 9.1 Searching

At minimum:

- `web_research`
- `help_search`
- `help_get`
- `content_search`
- `workspace_search`
- other explicitly search/retrieval-only tools

The Research specialist itself defaults to `searching`.

### 9.2 Composing

At minimum:

- Content specialist
- `draft_create`
- `draft_rewrite`
- writing pipeline operations
- legacy Ideas stages `writing` and `drafting`

### 9.3 Shaping

At minimum:

- Creative specialist
- `image_analyze`
- `image_generate`
- `image_edit`
- `image_variant`
- legacy `image_generation`

### 9.4 Acting

Use an explicit allowlist of actual application-changing operations, not a broad "anything non-read" rule.

Examples include the runtime's verified/reversible mutation paths and a person-confirmed proposal application.

Do **not** map:

- `schedule_propose`
- `automation_change_propose`

to `acting`; those only create proposals and are semantically planning/solving.

### 9.5 Solving

Use for:

- task planning;
- proposal reasoning;
- Brand Intelligence;
- Campaign reasoning;
- Publishing Operations reasoning;
- Analytics reasoning;
- Workspace/history reasoning when it is interpreting evidence rather than simply retrieving it;
- Manager calls before there is a more specific mode.

### 9.6 Connecting

Use for actual session/connection setup, not every network request.

Examples:

- Voice session negotiation;
- connector/OAuth/provider handshake surfaces;
- a future Agent tool that explicitly establishes a connection.

Web research is `searching`, not `connecting`, even though it uses the network.

## 10. Model/specialist phase instrumentation

`src/postriff_phase2/agent_runtime_v2/manager.py` already wraps model calls in `metered(...)`.

Before each model request, emit a semantic state based on `agent`:

- `rafii_manager`, initial reasoning → `solving`
- `content` → `composing`
- `research` → `searching`
- `creative` → `shaping`
- other specialists → `solving`

### 10.1 Weaving

`weaving` should be reserved for real synthesis, not used as a generic pretty transition.

Emit `weaving` on a later Manager model call when the shared ledger already contains evidence from **at least two distinct semantic evidence channels**, for example:

- two different specialists; or
- one specialist + a separate direct tool family; or
- multiple source categories that the Manager is now combining.

If that condition is not met, keep `solving`.

No model-derived classification is permitted.

## 11. Live state delivery for synchronous Agent Runtime V2

This is the critical piece.

### 11.1 Keep POST /agent/turns synchronous

Do not refactor the execution model.

The POST can continue to resolve only after the turn completes.

### 11.2 Add a tiny active-run lookup

Add an authenticated read endpoint:

`GET /api/workspaces/{workspaceId}/agent/conversations/{conversationId}/active-run`

Response:

```json
{
  "runId": "…",
  "status": "running",
  "startedAt": 0
}
```

or `null` / a stable empty result when there is no active run.

Rules:

- re-use normal workspace authentication and read permission;
- query only `pr_agent_runs` scoped to the exact workspace + conversation;
- return only safe identifiers/status/time;
- never return another workspace's run;
- latest active run only.

No migration is required.

### 11.3 Add Agent Runtime event read route

Expose:

`GET /api/workspaces/{workspaceId}/agent/runs/{runId}/events?cursor=N`

This should delegate to the same existing safe-event storage/read logic used by Ideas runs. Do not duplicate event persistence.

Return only existing safe events.

### 11.4 Frontend pending-turn observer

Add a hook such as:

`web/src/lib/agent-runtime/use-thinking-state.ts`

When a local Agent Runtime turn is pending:

1. render optimistic `working`;
2. poll `active-run` quickly until the run appears;
3. once `runId` exists, poll its events by cursor;
4. resolve the newest semantic `progress.updated` event;
5. stop when the POST settles, the run reaches a terminal state, or the component unmounts.

Recommended cadence:

- active-run discovery: 200 ms for the first 2 s, then 500 ms;
- event polling while active: 350–500 ms;
- exponential backoff after failures;
- no more polling after terminal state.

If telemetry is unavailable, remain on `working`. **Never guess a more specific state.**

Do not fail the user's turn because this observer failed.

## 12. Legacy Ideas/writer run compatibility

Legacy writing already exposes `progress.updated.stage`.

Client mapping:

- `queued` → `working`
- `writing` → `composing`
- `drafting` → `composing`
- `image_generation` → `shaping`
- unknown stage → `working`

If future legacy events emit a semantic `thinkingOp`, prefer that explicit value.

This lets Agent Chat use one renderer for both V2 and existing writing runs.

## 13. Frontend component architecture

Add:

- `web/src/components/agents/thinking/thinking-op.ts`
- `web/src/components/agents/thinking/rafii-thinking-orb.tsx`
- `web/src/components/agents/thinking/rafii-thinking-status.tsx`
- `web/src/lib/agent-runtime/thinking-state.ts`
- `web/src/lib/agent-runtime/use-thinking-state.ts`

### 13.1 RafiiThinkingOrb

Contract:

```tsx
<RafiiThinkingOrb op="searching" size={20} />
```

For the official nine:

```tsx
<ThinkingOrb state={op as OrbState} size={size} />
```

For `acting`:

- render official `connecting` briefly;
- transition to official `working`;
- never invent geometry;
- accessible state remains `acting`.

Suggested connecting prelude: roughly 400 ms. It is not a fake wait: if the action finishes earlier, immediately stop the state; do not delay completion.

### 13.2 RafiiThinkingStatus

Owns:

- orb;
- user-facing label;
- optional elapsed time;
- `role="status"`;
- one polite live-region announcement when a meaningful state persists long enough.

User labels:

- working → **Working…**
- searching → **Searching…**
- solving → **Thinking through it…**
- listening → **Listening…**
- connecting → **Connecting…**
- weaving → **Pulling it together…**
- composing → **Writing…**
- breathing → **Ready**
- shaping → **Shaping…**
- acting → **Taking action…**

These labels describe activity without exposing hidden reasoning.

## 14. Anti-flicker and transition policy

The state system is not an animation carousel.

Rules:

- consecutive identical events are deduplicated on the server;
- the client coalesces changes shorter than about 300 ms where doing so does not hide terminal completion;
- target minimum visible dwell for a nonterminal semantic state: ~350 ms;
- never hold the UI open just to satisfy minimum dwell;
- completion/cancel/error wins immediately;
- do not animate through intermediate states that the runtime did not emit;
- do not randomly cycle during a long model call.

The orb's own continuous animation is enough motion.

## 15. Where the new status appears

### 15.1 Full Agent Chat

Modify:

`web/src/features/agent/conversation-view.tsx`

Replace the current generic queued/StageProgress visual for the latest active run with `RafiiThinkingStatus`.

Keep:

- Cancel action;
- streaming text;
- image-generation card;
- ActivityStrip;
- warnings and failure UI.

Do not replace historical assistant avatars with animated orbs.

### 15.2 Site Agent panel/chat

Modify:

- `web/src/features/site-agent/chat.tsx`
- where needed, `web/src/features/site-agent/answer.tsx`

While a turn is pending, use the same `RafiiThinkingStatus`.

When there is no live semantic run id, use `working` only.

### 15.3 Voice Mode

Modify:

- `web/src/features/rafii-voice/voice-indicator.tsx`
- `web/src/features/rafii-voice/voice-mode.tsx` and/or `web/src/lib/agent-runtime/voice-session.ts` only as required

Use 64px official orbs for the prominent voice state:

- negotiating session → `connecting`
- user speaking/input active → `listening`
- delegated backend task → backend semantic op
- ready between turns → `breathing`

Do not replace or couple this to the Thread Map/music waveform rail. They solve different UI problems.

## 16. Existing ActivityStrip

Keep `ActivityStrip` as the detailed evidence/audit surface.

Semantic state events may appear in debug details, but avoid flooding the disclosure. Either:

- filter `progress.updated` events carrying `thinkingOp` from the raw detail list; or
- collapse consecutive semantic-state rows.

The orb answers "what is Rafii doing now?". ActivityStrip answers "what actually happened?".

## 17. Accessibility

Requirements:

- respect `prefers-reduced-motion` through the upstream component;
- wrapper supplies accessible text, so decorative orb canvas may be `aria-hidden`;
- use `role="status"`;
- `aria-live="polite"`, not assertive;
- do not announce every sub-300 ms transition;
- do not announce state changes aloud in Voice Mode;
- labels must remain meaningful without animation;
- forced-colors mode must retain visible label/status even if canvas appearance degrades;
- keyboard behavior and Cancel remain unchanged.

## 18. Privacy and security

A ThinkingOp event is product telemetry, not reasoning content.

Allowed event information:

- fixed ThinkingOp enum;
- fixed source enum;
- fixed reason code;
- run sequence/timestamp already part of the event system.

Forbidden:

- prompts;
- chain-of-thought;
- model hidden reasoning;
- raw tool arguments;
- query text;
- user content;
- document/file paths;
- URLs;
- tokens/credentials;
- secret/provider identifiers;
- free-form model output.

Permissions and action authority continue to live in the existing typed-tool gate.

## 19. Performance budget

- Only animate the latest active status, not every historical message.
- Use 20px orb for inline statuses.
- Use 64px only for focused Voice Mode.
- No new model calls.
- No new database tables.
- ≤32 semantic progress events per run.
- Event observer is active only while a turn is pending.
- Stop polling immediately on terminal state/unmount.
- Avoid importing internal engine code; let the published component own its animation loop.
- Production build must show no hydration warnings.

## 20. Feature flags and rollout

Recommended flags:

Backend:
- `RAFII_AGENT_THINKING_STATES_ENABLED`

Web:
- `NEXT_PUBLIC_RAFII_THINKING_ORBS=1`

Behavior:

- backend off → no semantic events;
- web off → current loading UI;
- backend on + web on → full semantic state system;
- web on + backend events unavailable → `working` fallback.

Rollout:

1. land dependency + components + pure resolver tests;
2. land backend semantic events and read endpoints;
3. enable in local browser harness;
4. run full Agent Chat / site-agent / voice browser acceptance;
5. enable Preview/staging;
6. verify real turn behavior and event privacy;
7. production flag on;
8. preserve immediate flag rollback to old loading UI.

## 21. Exact implementation surface

### Web dependency

- `web/package.json`
- web lockfile

### New web files

- `web/src/components/agents/thinking/thinking-op.ts`
- `web/src/components/agents/thinking/rafii-thinking-orb.tsx`
- `web/src/components/agents/thinking/rafii-thinking-status.tsx`
- `web/src/lib/agent-runtime/thinking-state.ts`
- `web/src/lib/agent-runtime/use-thinking-state.ts`

### Web modifications

- `web/src/lib/agent-runtime/types.ts`
- `web/src/lib/agent-runtime/client.ts`
- `web/src/features/agent/conversation-view.tsx`
- `web/src/features/site-agent/chat.tsx`
- `web/src/features/rafii-voice/voice-indicator.tsx`
- only touch `voice-mode.tsx` / `voice-session.ts` if required to expose their already-known transport state
- `web/src/features/agent/activity-strip.tsx` only for semantic-event filtering/collapse

### New backend file

- `src/postriff_phase2/agent_runtime_v2/thinking_state.py`

### Backend modifications

- `src/postriff_phase2/agent_runtime_v2/context.py`
- `src/postriff_phase2/agent_runtime_v2/tool_adapter.py`
- `src/postriff_phase2/agent_runtime_v2/manager.py`
- `src/postriff_phase2/agent_runtime_v2/service.py`
- Agent HTTP routing module / `hosted_app.py` as appropriate for the current route owner

### Explicitly no migration

Reuse:

- `public.pr_agent_runs`
- `public.pr_agent_events`

## 22. Test plan

### 22.1 Backend unit tests

Add `tests/test_rafii_thinking_state.py`.

Prove:

- every ThinkingOp validates;
- unknown op is refused/no-op;
- tool → state mappings are deterministic;
- proposal creation is not `acting`;
- real allowlisted mutation is `acting`;
- Research → `searching`;
- Content → `composing`;
- Creative → `shaping`;
- Manager multi-channel synthesis → `weaving`;
- consecutive state duplicates do not emit duplicate events;
- semantic telemetry failure cannot fail a tool;
- no raw args/user text are stored.

### 22.2 PostgreSQL/runtime tests

Extend the current Agent Runtime PG scenario.

Prove:

- live semantic events are stored on the correct run;
- event sequence is monotonic;
- a canceled/terminal run rejects late semantic events;
- active-run lookup is workspace/conversation scoped;
- another workspace cannot read the run or events;
- no migration is required.

### 22.3 Web unit tests

Add a focused test file such as:

`web/tests/rafii-thinking-orbs.test.cjs`

Prove:

- exact package dependency is pinned;
- nine official ops map 1:1 to upstream states;
- `acting` only composes official states;
- legacy stage mapping works;
- unknown telemetry → `working`;
- completed/cancelled/failed state stops animation;
- no prose-based classifier exists;
- ActivityStrip still reports final safe activity.

### 22.4 Browser acceptance

Add `web/tests/rafii-thinking-orbs-browser.cjs` or extend the existing Rafii browser scenes.

Cover:

- full Agent Chat;
- slash-command Agent Runtime turn;
- site-agent panel;
- Voice Mode connecting/listening/breathing;
- delegated search;
- drafting;
- image generation;
- allowed action;
- dark and light;
- reduced motion;
- keyboard Cancel;
- 320, 390, 430, and desktop widths;
- zero console errors;
- zero unexpected horizontal overflow;
- axe pass.

### 22.5 Visual proof

Capture a short browser recording showing at least these real runtime transitions using fixture/scripted tools, not a fake animation demo:

`working → searching → weaving → composing → done`

and Voice Mode:

`connecting → listening → solving → breathing`

For `acting`, use a safe fixture or reversible application action and prove the semantic state corresponds to the actual operation.

## 23. Acceptance criteria

This work is complete only when all are true:

1. Product uses `thinking-orbs@0.3.1` official React components.
2. No copied/reimplemented orb geometry exists in Rafii.
3. All 10 Rafii ThinkingOps are represented.
4. Nine map directly to official upstream states.
5. `acting` is explicitly a Rafii semantic composite built only from official states.
6. Agent V2 UI changes states from live runtime events, not generated prose.
7. No chain-of-thought or raw tool input is exposed.
8. Legacy writing stages still render correctly.
9. Voice uses connecting/listening/breathing appropriately.
10. Proposal creation is never falsely shown as an action already happening.
11. Permission, approval, budget and publishing behavior are unchanged.
12. No DB migration is introduced.
13. Reduced motion works.
14. Browser acceptance and accessibility gates pass.
15. Real visual proof shows state transitions matching actual fixture/runtime activity.
16. Feature flag rollback restores the current loader without affecting task execution.

## 24. Implementation order

### Phase 1 — visual primitive and resolver

- pin dependency;
- implement ThinkingOp types;
- implement official orb wrapper + `acting` composite;
- implement legacy stage resolver;
- unit test.

### Phase 2 — Agent Runtime semantic telemetry

- server enum/mapping;
- context emitter;
- model/specialist instrumentation;
- tool instrumentation;
- event privacy/dedupe tests.

### Phase 3 — live observation

- active-run read route;
- agent run-events route;
- web client methods;
- pending-turn observer;
- isolation/terminal-state tests.

### Phase 4 — product surfaces

- full Agent Chat;
- site-agent panel;
- Voice Mode;
- ActivityStrip cleanup.

### Phase 5 — end-to-end acceptance

- scripted real-state browser scenes;
- reduced motion;
- accessibility;
- performance;
- screenshots/screen recording;
- feature-flag rollout.

## 25. Engineering principle

**The orb follows Rafii; Rafii never performs for the orb.**

Do not add delays, fake transitions, or extra agent/model work just so a visually interesting state appears. A person should be able to learn the meaning of these animations over time because the same real class of work always produces the same state.
