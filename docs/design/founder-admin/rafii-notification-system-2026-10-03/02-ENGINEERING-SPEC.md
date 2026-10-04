# Rafii Notification System — Engineering Specification

Date: 2026-10-03
Status: implementation-ready
Primary repo: /Users/ouxianxing/Documents/James-Au-Studio

## 1. Engineering strategy

Upgrade the existing Rafii notification stack in place. Do not introduce a parallel notification service.

The existing system already has:
- Motion-based notification stack UI;
- notification bell/popover;
- generic notification card with actions;
- server notification center and unread count;
- attention items;
- Sonner;
- Founder notification routing/policy;
- browser and backend notification tests.

Implementation should add a presentation layer and state-specific UI surfaces around those foundations.

## 2. Source-of-truth rules

At execution time:
1. Resolve the newest approved Rafii canonical lineage.
2. Create a fresh isolated worktree.
3. Do not reset, stash, clean, overwrite or modify unrelated dirty worktrees.
4. Re-read the files listed under "Existing source integration points" from that exact worktree before patching.
5. Preserve backend notification delivery/policy semantics unless this spec explicitly requires a change.

The worktree used to author this spec is documentation-only and must not be assumed to be the final implementation base if a newer approved branch exists.

## 3. Existing source integration points

Expected current paths:
- web/src/components/motion/notification-stack.tsx
- web/src/components/layout/notification-bell.tsx
- web/src/components/ui/notification-card.tsx
- web/src/features/coworker/notifications/bell-list.tsx
- web/src/features/account/notifications-view.tsx
- web/src/lib/use-attention.ts or current equivalent
- web/src/lib/coworker/hooks.ts
- web/src/lib/coworker/types.ts
- tests/control/test_founder_notifications.py
- tests/control/test_founder_notifications_pg.py
- web/tests/unified-notifications-browser.cjs
- migrations/postriff/024_notification_core.sql
- migrations/postriff/034_unified_notifications.sql
- Founder notice migration(s), currently represented by the existing Founder notification tests

Before adding any new file, search for an existing equivalent.

## 4. Target architecture

UI event flow:

existing data sources
  -> presentation adapters
  -> normalized notification view model
  -> surface router
       -> Live Pill
       -> Notification Stack / Center
       -> Toast
       -> Activity Feed

Backend delivery policy remains authoritative for persistence and external channels.

### 4.1 Presentation adapter

Create a small UI-only normalization layer, preferably under:
web/src/features/notifications/

Suggested files:
- presentation.ts
- types.ts
- notification-center.tsx
- live-pill.tsx
- activity-feed.tsx

If an existing notifications feature directory is already canonical in the execution worktree, use it instead.

Do not move large existing modules just to match this suggested layout.

### 4.2 Normalized type

Use a view model similar to:

```ts
export type RafiiNotificationPriority = 'critical' | 'high' | 'normal' | 'low';

export type RafiiNotificationKind =
  | 'action_required'
  | 'critical'
  | 'security'
  | 'warning'
  | 'success'
  | 'info';

export type RafiiNotificationSurface =
  | 'center'
  | 'activity'
  | 'toast';

export type RafiiNotificationAction = {
  id: string;
  label: string;
  type: 'redirect' | 'api_call' | 'workflow' | 'modal';
  style?: 'primary' | 'danger' | 'default';
  href?: string;
  disabled?: boolean;
};

export type RafiiNotificationViewModel = {
  id: string;
  dedupeKey?: string;
  source: 'attention' | 'server' | 'founder' | 'agent';
  kind: RafiiNotificationKind;
  priority: RafiiNotificationPriority;
  title: string;
  description?: string;
  createdAt: number;
  unread: boolean;
  durable: boolean;
  dismissible: boolean;
  href?: string;
  actions: RafiiNotificationAction[];
  groupKey?: string;
  taskId?: string;
};
```

Treat this as a presentation contract, not a new persistence schema.

## 5. Adapters

### 5.1 Attention adapter
Map current attention items into:
- kind = action_required unless the source explicitly indicates critical/security;
- priority = high by default;
- durable = true when the underlying item is durably represented;
- dismissible = false unless backend semantics explicitly allow dismissal;
- href from the existing safe route.

### 5.2 Server notification adapter
Map existing server notifications using type/category/payload.

Rules:
- preserve stable notification id;
- preserve createdAt;
- preserve unread/read status;
- only expose payload href through the existing safeAppHref/safe-route guard;
- derive actions only from explicit supported metadata or known type mapping;
- never execute arbitrary URLs or payload-supplied code.

### 5.3 Founder notice adapter
If Founder workspace uses a separate current endpoint/view:
- preserve existing severity;
- map security/critical/warning/info directly;
- preserve existing read semantics;
- do not bypass quiet-hours/external-channel policy because this layer is in-app presentation only.

### 5.4 Agent/live adapter
Live task state is not automatically a durable notification.

Represent active task state separately:
```ts
type RafiiLiveState =
  | { status: 'idle' }
  | { status: 'running'; label: string; taskId?: string; progress?: number }
  | { status: 'waiting'; label: string; taskId?: string; href?: string }
  | { status: 'success'; label: string; taskId?: string; resultHref?: string }
  | { status: 'error'; label: string; taskId?: string; retryable: boolean; href?: string }
  | { status: 'degraded'; label: string };
```

Only use states that the actual runtime can prove.

## 6. Dedupe and grouping

Do not perform fuzzy title/body dedupe.

Order of preference:
1. existing backend dedupe key;
2. stable underlying task/workflow/event id;
3. stable notification id.

Cross-source dedupe is permitted only when two sources expose the same stable underlying identity.

If attention and server notification items refer to the same event but no stable shared key exists, preserve both rather than guessing.

Grouping:
- use existing groupKey/workflow/task identity if present;
- grouped cards may summarize repeated events;
- the full Activity Feed must preserve the underlying history.

## 7. Surface routing rules

Implement one routing function for presentation behavior.

Pseudo-contract:

```ts
function chooseSurface(event): Set<RafiiNotificationSurface> {
  // local action confirmation -> toast
  // running/progress -> live pill only
  // completed agent task -> activity + optional toast
  // waiting for user -> center + activity
  // security/critical/action_required -> center + activity
  // warning -> center or activity according to existing delivery policy
  // info -> activity unless current durable notification policy says it is unread in center
}
```

Do not create a separate database field for "surface" unless a proven persistence requirement exists.

## 8. Notification stack upgrade

Primary file:
web/src/components/motion/notification-stack.tsx

Preserve:
- useReducedMotion;
- keyboard Escape behavior;
- pointer/tap distinction;
- focus handling;
- bounded maxVisible;
- existing Motion dependency.

Enhance collapsed card transforms:
- visible y offset;
- slight scale reduction on deeper cards;
- subtle opacity/depth treatment;
- optional clip/inset retained if it looks correct.

Suggested visual values:
- front: scale 1, y 0, opacity 1;
- second: scale ~0.975, y 7-9 px, opacity ~0.92;
- third: scale ~0.95, y 14-18 px, opacity ~0.82.

These are starting values, not hard-coded visual law. Tune against Rafii chrome.

Expanded:
- reset scale/opacity;
- vertical gap 4-8 px;
- keep card order stable;
- allow cards to render richer action content.

Add AnimatePresence only if needed for insertion/removal. Do not add it merely because the reference example uses it.

## 9. Bell / center integration

Primary file:
web/src/components/layout/notification-bell.tsx

Current behavior combines:
- attention count;
- unread server count;
- separate attention list;
- BellNotificationList.

Target:
- compute normalized view models;
- render one coherent NotificationCenter / NotificationStack;
- preserve loading/partial states;
- preserve CallRafii / PhoneWorkspaceSync integration if still required;
- preserve notification settings link;
- preserve safe navigation;
- no false "all caught up" when a source is unavailable.

Count semantics:
- visible compact count should reflect meaningful unread/actionable items;
- accessible label should include total actionable/unread count;
- avoid bright red as default;
- critical state may use semantic critical treatment.

Do not silently change backend unread counts.

## 10. Rich notification card

Primary existing file:
web/src/components/ui/notification-card.tsx

Reuse existing action types:
- redirect;
- api_call;
- workflow;
- modal.

Required improvements:
- semantic kind/priority visuals;
- one or two actions;
- loading/executed/error state;
- timestamp;
- unread indicator that is not color-only;
- optional source/task context;
- mobile 44 px action target;
- keyboard focus order;
- optional archive/dismiss control only for dismissible items.

Action execution:
1. set pending state;
2. call existing endpoint/mutation;
3. wait for confirmed result;
4. update/invalidate notification data;
5. only then mark action executed;
6. on failure keep card actionable and show error/toast.

Never infer "success" from a click alone.

## 11. Rafii Live Pill

Suggested file:
web/src/features/notifications/live-pill.tsx

Use Motion layout/spring primitives already installed.

States:
- running;
- progress;
- waiting;
- success;
- error;
- degraded.

Implementation rules:
- fixed/min height so morphs do not cause header layout shift;
- animate width/layout, not expensive continuous canvas/filter effects;
- progress indicator only when actual progress exists;
- if no progress exists, use neutral working state;
- no fake percentage;
- no perpetual pulse when idle;
- click opens the active task/run when a valid href exists;
- waiting state promotes durable action item;
- success auto-collapses after a short visible interval using app state, not a demo timer loop;
- respect prefers-reduced-motion.

If existing app chrome has a better current surface for agent status, integrate there rather than duplicating it.

## 12. Toast policy

Existing Sonner imports are valid.

Keep Sonner for:
- success/error feedback;
- local API mutation result;
- copy/save/invite confirmations.

Evaluate shadcn Base UI Toast only if implementation needs:
- a capability Sonner cannot meet;
- stronger action/promise behavior that reduces custom code;
- consistent primitive behavior already adopted elsewhere in the current branch.

Do not run a system-wide toast migration in this task.

## 13. Activity Feed

First search for an existing activity/history surface.

If one exists:
- integrate normalized completed/history events there.

If none exists:
- create a bounded Activity Feed view or section using existing durable notification/event data;
- do not create a new event store for visual convenience.

Behavior:
- newest first;
- date grouping optional;
- new-item entrance motion only;
- no stagger replay every page load;
- pagination/infinite loading based on current API support;
- links use safe internal navigation.

## 14. Persistence and database

P0 expectation: no new migration.

Existing notification and Founder notice tables remain the source of truth.

A migration is allowed only if, after source audit, one of these is genuinely missing:
- stable action metadata that cannot safely live in existing payload/typed contract;
- archive/dismiss state required by product behavior and not representable today;
- stable group/dedupe key required by backend semantics.

If a migration is required:
- write a failing backend test first;
- keep it additive;
- preserve old readers;
- document rollback;
- update RLS/permissions if applicable;
- do not overload "read" to mean "archived".

## 15. Safe actions and navigation

All notification deep links:
- must be same-origin app routes or validated through existing safeAppHref logic;
- must reject javascript:, external arbitrary payload links and malformed paths.

API/workflow actions:
- map from a trusted action catalog/type;
- never execute arbitrary endpoint strings from untrusted payloads;
- respect current auth/capability boundaries;
- critical/destructive actions may require existing confirmation/fresh-MFA gates.

## 16. Partial availability

The center may combine multiple queries.

Represent per-source states:
- loading;
- ready;
- unavailable.

Rendering:
- if at least one source is ready, render it;
- show a compact partial warning for unavailable sources;
- "All caught up" only when all required sources are readable and empty;
- count/aria label must not claim zero if count is unknown.

## 17. Performance

Requirements:
- no new always-on polling solely for animation;
- no idle RAF loop;
- no continuous blur/filter animation;
- normalize/sort with memoization if the source arrays are non-trivial;
- only render a bounded preview in the header surface;
- defer full history to the full center/feed;
- preserve app responsiveness on mobile Safari.

Goal:
- no noticeable frame drop opening/closing the stack on a recent iPhone;
- header layout must not jump when Live Pill changes state.

## 18. Accessibility implementation

Required tests:
- tab to bell;
- Enter/Space open;
- Escape close;
- focus remains predictable;
- action buttons reachable;
- screen reader gets unread text and count;
- no clickable div-only controls;
- reduced motion path;
- light/dark contrast;
- 375 px layout no horizontal overflow;
- axe WCAG 2A/2AA baseline at minimum, matching existing test conventions.

## 19. Test plan

### Unit/component
Add or extend tests for:
- normalize attention item;
- normalize server notification;
- priority ordering;
- stable dedupe;
- no fuzzy dedupe;
- surface routing;
- live state transitions;
- action pending/success/failure;
- reduced-motion styles/behavior where testable.

### Browser
Extend existing notification browser coverage with:
- bell collapsed with 0, 1, 3, >3 items;
- visual back-card peek;
- tap expansion on mobile emulation;
- pointer hover/focus expansion on desktop;
- keyboard open/close;
- action button execution with fake backend;
- failed action remains actionable;
- partial-source unavailable state;
- "All caught up" correctness;
- dark/light;
- 375/1280 viewport;
- no horizontal overflow;
- axe checks.

### Founder backend regression
Run existing Founder notification tests to prove:
- external channel policy unchanged;
- quiet hours unchanged;
- digest unchanged;
- critical/security routing unchanged;
- durable in-app notice behavior unchanged.

### Regression
Run:
- web typecheck;
- relevant unit tests;
- notification browser test;
- Founder notification backend tests;
- any existing founder navigation/app shell tests touched by bell/live-pill changes.

## 20. Visual regression evidence

Capture at minimum:
1. desktop light collapsed stack;
2. desktop dark collapsed stack;
3. desktop expanded stack;
4. mobile expanded stack;
5. action-required card;
6. live pill running;
7. live pill waiting;
8. live pill success;
9. partial-data failure state;
10. reduced-motion state where screenshot differences matter.

Store evidence under the repo's existing evidence convention. Do not invent a new top-level evidence taxonomy.

## 21. Implementation sequence

Task 0 — authority
- resolve canonical branch;
- fresh worktree;
- baseline tests.

Task 1 — normalize
- add presentation types/adapters;
- unit tests.

Task 2 — stack/card
- upgrade stack depth;
- rich card actions;
- accessibility tests.

Task 3 — bell integration
- unify attention + server/founder presentation;
- preserve loading/partial semantics.

Task 4 — Live Pill
- connect real agent/task state;
- promotion path for waiting/action-required.

Task 5 — Activity Feed
- reuse existing history surface/data.

Task 6 — browser acceptance
- mobile/desktop/light/dark/keyboard/axe.

Task 7 — regression
- Founder backend policy suite;
- web typecheck/build gates relevant to the project.

Task 8 — release evidence
- screenshots;
- exact branch/commit;
- acceptance receipt.

## 22. Definition of done

Done means:
- no parallel notification subsystem;
- stack feels physically layered when collapsed and expands cleanly;
- action-required cards support valid direct actions;
- Live Pill reflects real work state;
- transient feedback still uses lightweight toast;
- completed/history events have a durable place;
- backend Founder notification policy is unchanged unless explicitly tested/approved;
- zero false "all caught up" states under partial failure;
- keyboard/reduced-motion/mobile acceptance passes;
- existing notification tests remain green;
- implementation evidence is tied to one final source commit.
