# Rafii Notification System — Start Here

Date: 2026-10-03
Status: implementation-ready design package
Scope: Rafii Founder / workspace notification experience
Target product repo: /Users/ouxianxing/Documents/James-Au-Studio
Implementation target must be a fresh isolated worktree from the newest approved canonical Rafii lineage at execution time.

## Why this package exists

Rafii already has a meaningful notification foundation. The correct move is not to replace it with another generic toast package. The goal is to turn the existing foundation into a coherent Rafii-specific notification system with four clearly separated surfaces:

1. Rafii Live Pill — transient live agent/task state.
2. Stacked Notification Center — durable, actionable notifications.
3. Lightweight Toast — short local confirmations and failures.
4. Activity Feed — durable historical events and completed work.

The experience should feel physical, calm and legible: stacked cards that peek behind the front card, spring open into a readable list, and collapse without visual noise. Agent work should use a compact morphing pill rather than constantly generating durable notifications.

## Current product evidence

Existing source already contains:
- web/src/components/motion/notification-stack.tsx
- web/src/components/layout/notification-bell.tsx
- web/src/components/ui/notification-card.tsx
- web/src/features/coworker/notifications/bell-list.tsx
- web/src/features/account/notifications-view.tsx
- web/tests/unified-notifications-browser.cjs
- tests/control/test_founder_notifications.py
- existing notification migrations and Founder notice routing

Observed behaviors already present:
- Motion-based expandable stack with reduced-motion handling.
- Bell popover that combines items needing attention with unread server notifications.
- Action-capable notification cards.
- Sonner usage for transient feedback.
- Durable Founder notification policy with in-app delivery, email/push gating, quiet hours and digest behavior.
- Existing Playwright coverage for notification settings and accessibility.

This package therefore specifies an upgrade and consolidation, not a parallel notification subsystem.

## Design direction

Primary inspiration:
- Motion stacked notifications: physical stack, depth, spring expansion.
- Aceternity Dynamic Island: compact-to-expanded state morphing for live agent work.
- shadcn Base UI Toast: modern accessible toast primitive with actions, statuses, promise states, stacking and swipe dismissal.
- Sonner: keep for small ephemeral feedback where it is already integrated.
- Magic UI Animated List: reference for the historical Activity Feed, not for the core notification center.

The visual design must remain Rafii-native. Do not copy demo styling, gradients, colors, Apple chrome, or vendor branding.

## Core product rule

Not every event is a notification.

Use:
- Live Pill for work that is currently happening.
- Toast for immediate local feedback that does not require later attention.
- Notification Center for durable events the user may need to revisit or act on.
- Activity Feed for history and completed events.

If a live task becomes blocked or requires a human decision, promote it into a durable notification.

## Implementation priority

P0
- Replace the current plain badge + list perception with the Rafii stacked-card interaction.
- Reuse existing motion stack, notification card and bell infrastructure.
- Introduce a presentation adapter that normalizes existing attention/server/founder notification sources for one visual system.
- Add action buttons to stacked cards where existing backend data supports them.
- Preserve unread/read semantics, accessibility and safe navigation.
- Add live agent pill with real state-driven transitions.
- Keep Sonner for local ephemeral feedback.

P1
- Add a full Activity Feed view backed by existing durable event/notification history.
- Add filtering and grouping only if supported by existing source data.
- Add swipe-to-dismiss/archive for dismissible informational items.
- Refine notification preference routing and priority visuals.

P2
- Cross-device continuity refinements.
- Optional richer grouping/summarization if the backend provides stable dedupe/group keys.

## Non-goals

Do not:
- build a second notification database;
- replace existing Founder notice policy;
- move all Sonner events into durable notifications;
- persist every live agent state transition;
- install a new animation library if Motion already satisfies the requirement;
- add a schema migration merely for visual presentation;
- make critical/security notifications dismissible in a way that loses their durable record;
- use continuous idle animation that burns CPU/GPU;
- create an always-red badge for ordinary unread items.

## File map

- 01-PRD.md — product behavior and UX requirements.
- 02-ENGINEERING-SPEC.md — architecture, file-level changes, data adapters, state machine, testing.
- 03-ACCEPTANCE.md — acceptance matrix.
- 04-REFERENCE-SOURCES.md — external references and how to use them.
- visuals/interaction-states.svg — original implementation reference showing the intended states.

No AGENT-HANDOFF.md is included. The handoff is intentionally delivered as a concise chat paragraph for direct copy/paste.
