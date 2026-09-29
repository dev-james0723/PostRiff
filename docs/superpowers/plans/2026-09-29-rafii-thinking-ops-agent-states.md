# Rafii ThinkingOps implementation plan

**Date:** 2026-09-29
**Spec:** `docs/superpowers/specs/2026-09-29-rafii-thinking-ops-agent-states.md`
**Handoff:** `docs/superpowers/handoffs/2026-09-29-rafii-thinking-ops-agent-states-handoff.md`
**Branch:** `feat/rafii-thinking-ops-20260929`
**Base:** `consumer-saas`

## Objective

Implement the approved semantic ThinkingOps system end-to-end using the official `thinking-orbs@0.3.1` React component and the existing Rafii run/event infrastructure. Preserve current permissions, approvals, budgets, publishing rules, and synchronous Agent Runtime V2 behavior.

## Work packages

### WP1 — official visual primitive

1. Pin `thinking-orbs@0.3.1` in `web/package.json` and lockfile.
2. Add the app-owned `ThinkingOp` type and client resolver.
3. Add `RafiiThinkingOrb` and `RafiiThinkingStatus`.
4. Map the nine official states 1:1.
5. Implement `acting` only as an official `connecting → working` visual composite.
6. Add focused source-level/unit tests for dependency pin, mapping, legacy stage fallback, labels, and no prose classifier.

### WP2 — semantic backend telemetry

1. Add `agent_runtime_v2/thinking_state.py` with fixed enums, reason codes, tool/specialist mappings and event builder.
2. Extend `RafiiRunContext` with bounded, failure-isolated semantic emission.
3. Attach an emitter when an Agent Runtime run opens and emit `working`.
4. Instrument model/specialist calls in `manager.py`.
5. Instrument the central typed-tool gate in `tool_adapter.py`.
6. Ensure proposal-only tools never map to `acting`.
7. Reserve `weaving` for deterministic multi-channel synthesis evidence.
8. Add backend tests for mapping, privacy, dedupe, cap, and telemetry failure isolation.

### WP3 — live state observation without async refactor

1. Add Agent HTTP route for conversation-scoped active run.
2. Add Agent HTTP route for safe run events backed by existing `IdeasService.events`.
3. Add client types/methods.
4. Add `useThinkingState` pending-turn observer with bounded polling/backoff.
5. Keep `POST /agent/turns` synchronous.
6. Add scope/isolation and terminal-state tests.

### WP4 — product surfaces

1. Replace latest active full Agent Chat spinner/progress visual with `RafiiThinkingStatus`, preserving Cancel/streaming/artifacts/errors.
2. Add shared pending status in Site Agent chat while a turn is in flight.
3. Integrate Voice Mode prominent 64px states:
   - handshake → connecting
   - input speech → listening
   - delegated backend state → semantic op when available
   - idle ready → breathing
4. Keep Thread Map audio rail unchanged.
5. Filter/collapse semantic progress events from ActivityStrip debug noise.

### WP5 — verification

1. Python focused ThinkingOps tests.
2. Existing Agent Runtime unit tests and PG scenarios where CI supports DB.
3. Web focused tests.
4. Typecheck, lint, production build, copy audit.
5. Browser scenes at 320, 390×844, 430×932, 768×1024, 1440×900 where harness supports them.
6. Reduced-motion, keyboard Cancel, axe, console/network errors, no horizontal overflow.
7. Scripted real runtime proof:
   - working → searching → weaving → composing → done
   - connecting → listening → solving → breathing
   - one safe/reversible acting case.
8. Record exact event counts, privacy evidence, branch/HEAD and any blocked physical-device verification.

## Rollback

Two independent flags:
- backend semantic telemetry: `RAFII_AGENT_THINKING_STATES_ENABLED`
- web renderer: `NEXT_PUBLIC_RAFII_THINKING_ORBS`

Turning the web flag off restores the previous loader without altering task execution. Turning backend telemetry off stops new semantic events while preserving all existing run/event behavior.

## Completion rule

Do not treat a playground as acceptance. Complete only after real Rafii surfaces are driven by real safe runtime state, all applicable gates are green, and the final branch identity/evidence is recorded.
