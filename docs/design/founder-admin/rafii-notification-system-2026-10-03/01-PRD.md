# Rafii Notification System — Product Requirements Document

Date: 2026-10-03
Owner: Rafii
Status: Approved direction for implementation

## 1. Product intent

Rafii notifications should tell the user what matters without turning the product into a wall of alerts.

The system has to answer four different questions with four different surfaces:

- What is Rafii doing right now? -> Live Pill.
- What needs my attention? -> Stacked Notification Center.
- Did my last action work? -> Lightweight Toast.
- What happened earlier? -> Activity Feed.

This separation is the main product decision. It reduces noise and makes notification behavior predictable.

## 2. User experience principles

### 2.1 Calm by default
Ordinary unread notifications must not create a permanently alarming red state. Use Rafii's neutral foreground/background tokens by default. Reserve semantic warning/error treatment for actual warning/error events.

### 2.2 Physical, not flashy
The Notification Center should feel like a small stack of physical cards. In the collapsed state, the back cards visibly peek behind the front card. Expansion should use spring motion and depth changes, not a generic dropdown fade.

### 2.3 Action-first
If a notification requires a human decision, the primary action must be visible directly on the card when space permits. Do not force a navigation round-trip for every approval/retry/review action.

### 2.4 State is real
The Live Pill must reflect actual task/agent state. It must not run a decorative fake cycle.

### 2.5 Durable versus ephemeral is explicit
A toast disappearing must never be the only record of a decision-required event, security event, billing issue or failed workflow that the user may need to revisit.

## 3. Primary surfaces

## 3.1 Rafii Live Pill

Purpose: show active agent/workflow state without polluting durable notifications.

Placement:
- In the main authenticated app chrome near Rafii controls / notification area.
- Must not overlap Call Rafii controls.
- On narrow mobile layouts, it may collapse to icon + short state label.

States:
- idle: hidden or minimal "Rafii" presence; no continuous pulse.
- running: "Rafii · Working…" with optional short task label.
- progress: "Analyzing 14 campaigns" or similar bounded progress text when real progress data exists.
- waiting: "Needs your input" and clicking opens the relevant task/approval surface.
- success: brief completion morph, then collapse.
- error: short failure state with "View" / "Retry" only when those actions are valid.
- disconnected/degraded: only if the runtime can reliably detect this state.

Behavior:
- Width/shape morphs between states with a spring.
- No auto-cycling demo animation.
- Success should remain visible long enough to be perceived, then transition to toast/activity history unless the user must act.
- A running task becoming blocked promotes a durable notification.
- Multiple simultaneous tasks should summarize, e.g. "Rafii · 3 tasks running", and open the task/activity surface.

## 3.2 Stacked Notification Center

Purpose: show durable notifications and "needs attention" items.

Collapsed appearance:
- Bell/control remains compact.
- Up to 3 visual card edges peek behind the front card when notifications exist.
- Do not rely on a bright red numeric badge as the primary visual.
- A small neutral count may be shown if useful, but the stack itself should communicate accumulated items.
- Accessible label must announce meaningful count and state.

Expansion:
- Hover on pointer devices may preview/expand.
- Click/tap toggles.
- Keyboard focus exposes the same information.
- Escape collapses.
- Outside tap/click collapses when appropriate.
- Card stack fans open vertically with spring motion.
- Maximum popover preview should remain bounded. A "View all" route opens the full history/center.

Ordering:
1. critical/security requiring action;
2. action-required / approval / reconnect / payment issue;
3. warnings;
4. normal unread;
5. informational items.

Within the same priority, newest first unless the backend provides a stronger ordering contract.

Card content:
- semantic icon or source marker;
- concise title;
- one or two lines of supporting text;
- relative timestamp;
- unread state that is not color-only;
- up to two visible actions;
- optional "Open" / deep-link affordance;
- source/task context only when it helps disambiguate.

Examples:
- Checkout needs attention — "3 failed attempts · 2m" — View / Retry.
- Approval required — "Campaign draft waiting" — Review / Approve.
- Agent task completed — "Pricing audit finished" — Open result.
- Connection expired — "Reconnect Instagram to publish" — Reconnect.

Dismiss/read rules:
- Reading is not the same as dismissing.
- Informational items may be swipe-dismissed/archived if the backend semantics support it.
- Action-required, billing, critical and security items must keep a durable record.
- Dismiss/archive must not silently execute the primary action.

## 3.3 Lightweight Toast

Purpose: immediate feedback tied to a local user action.

Use for:
- Copied.
- Saved.
- Invite sent.
- Settings updated.
- Retry started.
- Undo for a reversible local action.
- Temporary API error that does not require durable follow-up.

Do not use as the only surface for:
- approvals;
- billing failure;
- security event;
- account access issue;
- failed scheduled workflow;
- reconnect requirement;
- production incident;
- any state the user may need to revisit later.

Current Sonner integration should remain unless a targeted migration to the existing shadcn Base UI Toast is justified by a concrete missing capability. Do not replace Sonner merely for visual novelty.

## 3.4 Activity Feed

Purpose: durable history and completed work.

Content:
- completed agent tasks;
- notification history;
- approvals resolved;
- retries and recoveries;
- relevant system/account events;
- publish/workflow status changes.

The feed should use restrained sequential entrance motion only when new items arrive. It must not replay dramatic animations every time the page opens.

The feed is the place for "what happened"; the Notification Center is the place for "what needs attention".

## 4. Information architecture

The bell/stack should no longer feel like two unrelated sections ("Needs attention" then "Recent"). The user should perceive one coherent priority-sorted center even if the data still comes from multiple existing sources.

Presentation grouping may include:
- Needs attention
- Recent
- Earlier

But the UI must normalize visual treatment and interaction.

Full notification/history route should be reachable from the stack via "View all". Notification settings remain a separate destination.

## 5. Notification classification

Every presented item must map to a class:

### action_required
Human input is required to continue or resolve something.

### critical
Material production/account impact. May bypass quiet presentation rules where existing policy allows.

### security
Security-sensitive event. Durable record required.

### warning
Meaningful degradation or risk, no immediate destructive state.

### success
Completed task/workflow. Usually Activity Feed + optional transient toast; only durable bell entry when it remains useful.

### info
Low urgency update. Prefer Activity Feed over bell unless explicitly unread/delivered by current product policy.

## 6. Priority and noise controls

The system must prevent notification inflation.

Rules:
- One underlying event should not produce duplicate visible cards just because it appears in both attention and server-notification sources.
- Use an existing stable dedupe key when present.
- If no safe cross-source identity exists, do not invent fuzzy deduplication.
- Repeated failures from the same workflow should update/group when the backend has a durable grouping key; otherwise preserve individual records.
- Live progress ticks must never become individual durable notifications.

## 7. Responsive behavior

Desktop:
- Stack/popover width approximately 320-368 px.
- Up to 3 visible stack layers when collapsed.
- Hover preview allowed.
- Expanded cards support pointer actions.

Mobile:
- No hover dependency.
- Tap opens/closes.
- Full-width sheet/popover treatment is allowed if required by existing responsive primitives.
- Swipe gesture must not conflict with browser/system back gestures.
- Minimum touch target 44x44 CSS px for actions.

## 8. Motion specification

Use existing Motion dependency.

Collapsed stack:
- front card remains readable;
- second/third layers use subtle y-offset, scale and/or inset;
- opacity remains high enough that the stack reads as depth, not disabled content.

Expand:
- spring layout transition;
- cards separate vertically;
- no aggressive overshoot;
- target visual settle around 250-450 ms depending on spring.

New item:
- enters from a small positive y offset and slight scale change;
- pushes existing cards back in depth;
- no large fly-in.

Dismiss:
- lateral motion only on devices where swipe is supported;
- fade/slide should complete quickly;
- immediately expose the next card without layout flash.

Reduced motion:
- eliminate spring/depth choreography;
- switch states immediately or with a minimal opacity transition;
- no pulsing indicators.

## 9. Visual language

Use Rafii design tokens and existing glass/radius primitives.

Default:
- neutral foreground/background;
- subtle border;
- controlled glass where already part of Rafii chrome;
- readable hierarchy;
- restrained shadow/depth.

Semantic state:
- warning/error/critical colors appear as small icon/accent/status treatment, not a full screaming card fill.
- unread state must include shape/text/weight difference, not color alone.

Avoid:
- Apple clone styling;
- neon SaaS gradients;
- emoji as the primary production icon language;
- persistent bouncing;
- oversized red badges;
- every card having a different color.

## 10. Accessibility

Required:
- full keyboard operability;
- Escape collapse;
- focus visible;
- screen-reader count/state label;
- unread state announced in text;
- action buttons have clear names;
- no hover-only actions;
- WCAG 2.2 AA target for the touched surfaces;
- reduced-motion support;
- touch targets >= 44x44 where feasible;
- card ordering in DOM matches reading/navigation order.

## 11. Failure and degraded states

If notification data is partially unavailable:
- preserve any readable source;
- show a compact "Some updates couldn't load" state;
- do not display a false "All caught up";
- do not silently zero the badge/count if the system cannot determine unread state.

If action execution fails:
- keep the durable card;
- show inline error or local toast;
- preserve retry if safe;
- do not mark the action executed until the server confirms.

## 12. Analytics / observability

Track product events only if current Rafii telemetry conventions support them:
- notification_center_opened;
- notification_action_started;
- notification_action_succeeded;
- notification_action_failed;
- notification_marked_read;
- notification_archived;
- live_pill_opened;
- live_task_promoted_to_notification.

Do not add third-party tracking merely for this feature.

## 13. Success criteria

The redesign succeeds when:
- the notification area looks and behaves like one Rafii system rather than a bell plus unrelated lists;
- active agent work is visible without spamming notifications;
- actionable notifications can be understood and acted on directly;
- normal confirmations remain lightweight;
- history is still discoverable;
- existing Founder notification policy and backend durability remain intact;
- mobile, keyboard, reduced-motion and dark/light states are verified;
- there is no measurable increase in idle CPU/GPU churn caused by decorative animation.
