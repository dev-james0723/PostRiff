# Rafii Notification System — Acceptance Matrix

Date: 2026-10-03

## Product acceptance

| Area | Acceptance |
|---|---|
| Surface model | Live work, actionable notifications, local feedback and history are rendered through distinct Live Pill, Notification Center, Toast and Activity Feed surfaces. |
| Existing foundation | Existing Motion stack, bell, notification card, server notification hooks and Founder notice policy are reused rather than duplicated. |
| Collapsed stack | With 2+ items, back-card edges/depth are visible. The visual does not depend on a bright red numeric badge. |
| Expanded stack | Pointer, tap and keyboard users can open and close it. Cards expand into readable stable order with no overlap. |
| Priority | Critical/security/action-required items sort ahead of ordinary unread items. |
| Actions | Supported cards expose up to two valid actions and only show completion after confirmed server success. |
| Failure | A failed action remains actionable and its durable notification is not lost. |
| Read vs archive | Mark-read and dismiss/archive are distinct semantics. Critical/security/action-required history remains durable. |
| Live Pill | States are driven by real task/agent state, not a decorative timer. |
| Promotion | A live task that needs human input becomes a durable notification. |
| Toast | Copy/save/invite/local mutation feedback remains lightweight and ephemeral. |
| Activity Feed | Completed/history events remain discoverable without crowding the bell. |
| Partial data | A readable source still renders if another source fails; the UI never falsely says "All caught up". |
| Safe links | Notification links are validated same-origin app routes using existing safe navigation logic. |
| External policy | Founder email/push/quiet-hours/digest policy is unchanged unless separately approved and tested. |

## Visual acceptance

Capture and review:
- Desktop light, collapsed, 0 notifications.
- Desktop light, collapsed, 1 notification.
- Desktop light, collapsed, 3 notifications.
- Desktop dark, collapsed, 3+ notifications.
- Desktop expanded stack.
- Mobile 375 px expanded stack.
- Action-required card with two actions.
- Critical/security card.
- Partial-source failure.
- Live Pill running.
- Live Pill waiting for user.
- Live Pill success.
- Reduced-motion behavior.

Visual rules:
- No card text overlap.
- No stack layer clipping into app chrome.
- No horizontal overflow at 375 px.
- No unread state communicated by color alone.
- No persistent bouncing/pulsing in idle state.
- Semantic warning/error color remains an accent, not a full-card alarm by default.

## Interaction acceptance

### Mouse / trackpad
- Hover preview/expand may work on pointer devices.
- Pointer leave collapses unless focus remains within the component.
- Clicking an action does not accidentally trigger card navigation.
- Clicking/tapping outside closes an expanded transient stack when appropriate.

### Touch
- First tap opens the stack.
- Action buttons are at least approximately 44x44 CSS px.
- Swipe-dismiss, if implemented, does not conflict with browser back navigation.
- A swipe dismisses only a dismissible item.

### Keyboard
- Bell is focusable.
- Enter/Space opens.
- Tab reaches each interactive action in logical order.
- Escape closes.
- Focus is not thrown to document start after close.
- Focus-visible styling is present.

## Accessibility acceptance

- WCAG 2.2 AA target on modified surfaces.
- Existing axe 2A/2AA browser gate remains green.
- aria-label/accessible name includes notification count/state.
- "Unread" is represented in accessible text.
- Reduced-motion path avoids spring/depth choreography.
- Screen reader order matches visual/DOM order.
- Loading, partial and empty states are distinguishable.

## Data acceptance

- No fuzzy title/body dedupe.
- Shared stable dedupe key is used when present.
- Cross-source merging happens only with provable shared identity.
- Existing unread state remains authoritative.
- Live progress ticks are not persisted as separate notifications.
- No P0 database migration unless source audit proves the existing model cannot represent a required durable state.

## Performance acceptance

- No new idle requestAnimationFrame loop.
- No new polling introduced solely for visual motion.
- Notification preview is bounded.
- Opening/closing the stack is visually smooth on mobile Safari.
- Live Pill morph does not shift surrounding app chrome.
- No continuous expensive blur/filter animation.

## Required tests

At minimum:
1. Presentation adapter unit tests.
2. Priority sorting and dedupe tests.
3. Surface-routing tests.
4. Notification action pending/success/failure tests.
5. Live Pill state transition tests.
6. Existing notification browser test.
7. New/extended browser tests for stack open/close, mobile, keyboard, partial failure and actions.
8. Existing Founder notification policy tests.
9. Relevant Founder/app-shell regression tests.
10. Web typecheck/build gate required by current repo policy.

## Release receipt

Final evidence must record:
- exact implementation branch;
- exact final commit;
- canonical base commit;
- tests executed and pass/fail;
- screenshots/evidence paths;
- whether a migration was required;
- any known blocked external-provider verification;
- confirmation that unrelated worktrees were not reset/stashed/cleaned/overwritten.
