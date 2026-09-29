# Handoff — implement Rafii ThinkingOps semantic agent states

**Date:** 2026-09-29  
**Spec:** `docs/superpowers/specs/2026-09-29-rafii-thinking-ops-agent-states.md`  
**Spec branch:** `docs/rafii-thinking-ops-agent-states-20260929`  
**Spec commit:** `a0ab1a9acc30d731e0939bffe902e66b8957dbb4`

## Mission

Implement the approved Rafii ThinkingOps system end-to-end.

This is an **execution task**, not a new design exercise. Read the authoritative spec first. Preserve existing Agent Runtime safety, permissions, approvals, budgets, events, live voice behavior, and current unrelated work.

The visual source MUST be the official package from:

https://github.com/Jakubantalik/thinking-orbs

Use the exact inspected package version `thinking-orbs@0.3.1`.

There are nine official upstream visual states:

- working
- searching
- solving
- listening
- connecting
- weaving
- composing
- breathing
- shaping

The tenth Rafii ThinkingOp is `acting`. It is **not** a new upstream animation. Implement it only as a semantic composite of official `connecting → working`.

## Before editing

1. Inspect the real repository, current branch, HEAD, status, worktrees, and `AGENTS.md` / `CLAUDE.md` / local instructions.
2. Re-check latest `origin/consumer-saas`.
3. Preserve every unrelated WIP change. Do not clean/reset/stash other people's work unless the repo instructions explicitly require and you can prove ownership.
4. Read the full spec from the docs branch/commit above.
5. Re-read these current integration surfaces:
   - `web/src/features/agent/conversation-view.tsx`
   - `web/src/features/agent/activity-strip.tsx`
   - `web/src/features/agent/use-run.ts`
   - `web/src/lib/agent-runtime/client.ts`
   - `web/src/lib/agent-runtime/types.ts`
   - `web/src/features/site-agent/chat.tsx`
   - `web/src/features/rafii-voice/voice-indicator.tsx`
   - `src/postriff_phase2/agent_runtime_v2/context.py`
   - `src/postriff_phase2/agent_runtime_v2/tool_adapter.py`
   - `src/postriff_phase2/agent_runtime_v2/manager.py`
   - `src/postriff_phase2/agent_runtime_v2/service.py`
   - current Agent HTTP route owner
   - `src/postriff_phase2/agent_runtime.py`
   - `src/postriff_phase2/ideas.py`
6. Confirm the current event/store behavior before modifying it.

If current code has moved, adapt the file locations while preserving the spec's contracts rather than forcing stale paths.

## Non-negotiable constraints

- Do not imitate or redraw thinking-orbs.
- Do not vendor its animation geometry.
- Do not expose chain-of-thought, hidden reasoning, prompts, raw tool arguments, URLs, secrets, or user text in semantic progress events.
- Do not infer state from assistant prose.
- Do not add model calls for state classification.
- Do not change tool authority, permissions, approval policy, credit policy, or publishing rules.
- Do not make Agent Runtime V2 asynchronous.
- Do not add a database migration.
- Do not replace the music-reactive Thread Map rail.
- Do not add fake delays or cycle states for visual variety.
- Do not label a proposal as `acting`.
- Telemetry failure must never fail a user's actual request.

## Implementation phases

### Phase 1 — official visual primitive

- Pin `thinking-orbs` exactly to `0.3.1` in the web package and lockfile.
- Add the app-owned `ThinkingOp` type.
- Add `RafiiThinkingOrb` and `RafiiThinkingStatus`.
- The nine upstream states must render through the official `ThinkingOrb` component.
- `acting` must render only official `connecting → working`.
- Use the package's tuned 20px/64px sizes.
- Respect reduced motion.
- Add pure mapping tests before wiring the UI.

### Phase 2 — backend semantic telemetry

Create the single server-owned ThinkingOp mapping module specified in the spec.

Instrument:

- run opening;
- Manager/model calls;
- specialist calls;
- the central tool gate.

Reuse `progress.updated` and existing `pr_agent_events`.

Semantic events must contain only fixed enums/reason codes.

Dedupe consecutive identical ops. Cap semantic events per run.

### Phase 3 — live observation for synchronous turns

Keep `POST /agent/turns` synchronous.

Add:

- conversation-scoped active-run read endpoint;
- Agent Runtime run-events read endpoint backed by the existing safe event store;
- web client methods;
- pending-turn hook that discovers the run and follows events while the POST remains pending.

When telemetry cannot be observed, show only `working`.

### Phase 4 — product surfaces

Wire the shared status component into:

- Full Agent Chat
- Site Agent chat/panel
- Voice Mode

Do not animate historical messages.

Voice state priority:

- session handshake → connecting
- user speech → listening
- active delegated backend operation → its semantic ThinkingOp
- ready idle → breathing

Keep existing Cancel, streaming, ActivityStrip, image card, errors and warnings.

### Phase 5 — acceptance and proof

Run all focused tests, full relevant gates, build, accessibility/browser scenes and visual acceptance.

The proof must use real scripted/fixture runtime activity and show at least:

- working → searching → weaving → composing → done
- connecting → listening → solving → breathing
- one safe/reversible real `acting` case

A static playground or manually timed demo does **not** count as acceptance evidence.

## Required mapping checks

At minimum prove:

- Research / web_research → searching
- Content / draft create-rewrite → composing
- Creative / image operations → shaping
- Manager planning → solving
- multi-evidence Manager synthesis → weaving
- voice input → listening
- voice/session handshake → connecting
- idle Voice Mode → breathing
- explicit safe application-changing operation → acting
- unknown/insufficient telemetry → working

The agent must not broaden `acting` simply because a tool is technically non-read.

## Compatibility

Legacy Ideas/writer stages must continue to work:

- queued → working
- writing/drafting → composing
- image_generation → shaping
- unknown → working

Prefer explicit semantic `thinkingOp` when present.

## Validation requirements

### Backend

Run focused unit tests plus the existing Agent Runtime suite.

Add tests for:

- deterministic map;
- event privacy;
- dedupe;
- terminal/cancel behavior;
- cross-workspace isolation;
- active-run scoping;
- no migration;
- telemetry failure isolation.

### Web

Run:

- focused ThinkingOps unit tests;
- existing Agent Chat tests;
- site-agent browser tests;
- Voice browser tests;
- typecheck;
- lint;
- production build;
- copy audit where required by repo policy.

### Browser

Test at least:

- 320px
- 390×844
- 430×932
- desktop 1440px

In light + dark where existing browser harness supports it.

Verify:

- no console errors;
- no hydration warnings;
- no unexpected overflow;
- axe passes;
- reduced motion works;
- Cancel still works;
- animation stops immediately on terminal result;
- historical chat does not animate every orb.

## Performance / event budget

Target:

- only latest active status animates;
- ≤32 semantic state events per turn;
- no permanent polling after completion;
- no provider/model request added;
- active-run/event observer is scoped to the pending turn only.

Record any measurable change in request/event counts in the implementation receipt.

## Release discipline

Work in an isolated implementation branch/worktree based on latest `consumer-saas`.

Do not merge or deploy until:

1. implementation is complete;
2. tests and production build pass;
3. browser visual evidence is reviewed;
4. privacy check confirms semantic events contain enums only;
5. exact final HEAD is recorded.

If the user's execution instruction at that time explicitly says to ship, then follow the repo's normal merge/deploy/verify process. This handoff by itself does not grant production release authorization.

## Final report format

Report:

- branch + exact final HEAD;
- changed files;
- exact package version;
- semantic state mapping actually implemented;
- tests with counts;
- browser/accessibility results;
- event/privacy evidence;
- performance/event-count evidence;
- link/path to screen recording or screenshots;
- whether merged;
- whether pushed;
- whether deployed;
- any remaining blockers.

Do not report "done" if the states only animate in a playground. The acceptance target is the real Rafii Agent surfaces driven by real runtime state.
