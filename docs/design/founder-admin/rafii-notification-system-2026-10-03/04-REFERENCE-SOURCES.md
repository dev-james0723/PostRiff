# Rafii Notification System — Reference Sources

Date verified: 2026-10-03

These references are inspiration and implementation research only. Rafii must keep its own visual language and source contracts.

## 1. Motion — stacked notifications

URL:
https://motion.dev/examples/react-toast-stack

Use for:
- depth/stack mental model;
- enter/exit choreography;
- physical layering;
- spring-based expansion.

Do not:
- copy styling wholesale;
- add animation primitives not needed by the existing Rafii Motion stack.

Relevant current Rafii source:
web/src/components/motion/notification-stack.tsx

## 2. Motion — iOS-inspired notification stack

URL:
https://motion.dev/examples/react-notifications-stack

Use for:
- expand/collapse interaction study;
- card layering;
- variants/spring reference.

Do not:
- ship an Apple clone.

## 3. Aceternity UI — Dynamic Island

URL:
https://ui.aceternity.com/blocks/illustrations/dynamic-island

Use for:
- compact -> working -> complete state morph;
- fixed-height layout to avoid layout shift;
- spring transition inspiration.

Rafii adaptation:
- states must be driven by real task/agent state;
- no automatic demo cycling;
- add waiting/error/degraded states only when actual runtime evidence exists.

## 4. shadcn/ui — Base UI Toast

URL:
https://ui.shadcn.com/docs/components/base/toast

Changelog:
https://ui.shadcn.com/docs/changelog/2026-07-toast

Use for:
- reference behavior for actions;
- status types;
- promise states;
- stack/swipe semantics;
- accessible toast primitives.

Important:
Rafii already uses Sonner. Do not migrate system-wide merely because this component exists. Adopt only if it solves a concrete capability gap.

## 5. shadcn/ui — Sonner

URL:
https://ui.shadcn.com/docs/components/aria/sonner

Use for:
- existing lightweight ephemeral feedback;
- local success/error/promise feedback.

Relevant current Rafii source already imports Sonner in notification/settings workflows.

## 6. Magic UI — Animated List

URL:
https://magicui.design/docs/components/animated-list

Use for:
- sequential entrance reference for a historical Activity Feed.

Do not:
- use it as the primary Notification Center;
- replay dramatic list animation on every page load.

## 7. Local Rafii implementation anchors

Verified identical between the inspected Founder activation worktree and canonical spec base at authoring time:

- web/src/components/motion/notification-stack.tsx
  git blob: 2061d0820340a360a09d44a8852d644794320123
- web/src/components/layout/notification-bell.tsx
  git blob: 73d062d2dcfc595725ed020101d91f5683ee82a2
- web/src/components/ui/notification-card.tsx
  git blob: 52f733ded1bb2e736ed6da085e0bc7107d9643af
- web/src/features/coworker/notifications/bell-list.tsx
  git blob: 8119219f931edb811c355bfbe71420613d9ed253
- web/src/features/account/notifications-view.tsx
  git blob: 2a88d78b344cd42ebbfe682764792db742df5186

Authoring base:
- branch: codex/rafii-notification-spec-20261003
- base commit: ead73924
- upstream: origin/consumer-saas

## 8. Existing backend/test anchors

Use the current canonical versions at implementation time:
- migrations/postriff/024_notification_core.sql
- migrations/postriff/034_unified_notifications.sql
- tests/control/test_founder_notifications.py
- tests/control/test_founder_notifications_pg.py
- web/tests/unified-notifications-browser.cjs

These existing contracts are why this feature should begin as a presentation/interaction upgrade rather than a new notification backend.
