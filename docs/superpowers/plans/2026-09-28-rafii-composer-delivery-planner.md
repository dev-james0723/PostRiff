# Rafii Compact Delivery Planner — Implementation Plan

Date: 2026-09-28  
Spec: `docs/design/rafii-composer-delivery-planner/SPEC.md`  
Branch prepared for handoff: `codex/rafii-composer-delivery-planner-20260928`

## Goal

Replace the conversation composer’s permanent horizontal `Draft for` channel/language rail with a compact delivery summary that opens a structured Channel × Language planner, while preserving all existing destination, language, model, attachment, publishing and scheduling semantics.

This is a frontend interaction/layout change. Do not add backend schema, provider permissions or migrations unless implementation proves one is genuinely required.

## Before editing

1. Confirm repository is `dev-james0723/PostRiff`.
2. Confirm the handoff branch contains the current SPEC and this plan.
3. Fetch `origin/consumer-saas` and inspect whether it advanced after this plan was written.
4. Rebase/merge only if needed and resolve against current behavior; do not overwrite unrelated concurrent work.
5. Read:
   - `docs/design/rafii-composer-delivery-planner/SPEC.md`
   - `docs/design/rafii-v9/briefs/C-language-model-dialogs.md`
   - `docs/design/rafii-v9/briefs/E-home-composer.md`
   - `web/src/features/agent/composer.tsx`
   - `web/src/features/agent/use-channel-languages.ts`
   - `web/src/features/agent/language-dialog.tsx`
   - `web/src/features/agent/language-dialog-ops.ts`
   - `web/src/features/agent/conversation-view.tsx`
   - `web/src/features/agent/plan-card.tsx`
6. Capture a baseline mobile screenshot of the existing conversation composer at 390 × 844 with at least 3 destinations and 2 languages.

## Task 1 — Build pure delivery-summary derivation

Create:
- `web/src/features/agent/delivery-summary.tsx`
- `web/src/features/agent/delivery-summary.test.cjs` (or the repo’s nearest existing test convention)

Implement a small pure helper that receives the effective active destination rows and returns:
- destination count,
- unique effective language count,
- up to three channel marks plus `+N`,
- human-readable single-destination summary,
- accessible full summary string.

Cases to lock with tests:
1. one destination / one language,
2. one destination / multiple languages,
3. three destinations / two languages,
4. five destinations,
5. two accounts on same platform count as two destinations,
6. message-provided language counts as effective language.

Keep the component presentational. Do not move destination persistence into it.

## Task 2 — Replace the horizontal rail in compact Composer

Modify:
- `web/src/features/agent/composer.tsx`

Remove the default-state permanent horizontal `Draft for` scroller / `ChannelLanguageChip` wall.

Render:
1. textarea,
2. attachment strip when present,
3. compact `DeliverySummary` trigger,
4. compact model / voice / image tool row + send,
5. blockers/reminders.

Requirements:
- no essential horizontal scroll at 390 px,
- summary trigger is a real button,
- `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls`,
- keep existing `canSend` calculation unchanged unless a failing test proves an adjustment is required,
- preserve IME handling, slash commands, attachments, message limit, consent, model qualification, voice, image and reminders.

Add the smallest new props required to open the planner. Prefer an explicit `deliveryPlanner`/callback prop over hidden global state.

## Task 3 — Reuse staged language behavior for the planner

Do **not** duplicate the complex logic in `language-dialog.tsx`.

Refactor the smallest reusable unit from:
- `web/src/features/agent/language-dialog.tsx`
- `web/src/features/agent/language-dialog-ops.ts`

The reusable state/editor must preserve:
- staged per-destination language arrays,
- multiple languages per destination,
- reversible shared-language mode,
- Apply/Cancel semantics,
- message-language precedence display,
- existing locale catalogue/search,
- focus and Escape behavior.

Existing `language-dialog-ops.test.cjs` must stay green before proceeding.

If extraction would create a larger regression risk than a thin shared controller, keep the existing dialog intact and share only its staged-operation helper/data model.

## Task 4 — Build DeliveryPlanner

Create:
- `web/src/features/agent/delivery-planner.tsx`
- targeted planner state tests if new logic exists.

Use existing Rafii dialog primitives.

Render:
- header: `Publish to` / `Choose channels and output language`,
- summary count,
- `Use same language for all` switch,
- vertical Channel × Language matrix,
- destination/account identity on the left,
- language control(s) on the same row/group,
- `+ Add language`,
- `+ Add channel`,
- Apply + Cancel.

Channel behavior:
- use the existing `chips` / channel/account data passed by ConversationView,
- use `languages.toggle`, `setTargets` or current selection APIs,
- never disconnect/revoke an account,
- preserve `channelId` for account-level destinations,
- do not invent a second persistent destination store.

On narrow phones, allow a matrix row to stack internally; never revert to a horizontal carousel.

## Task 5 — Wire ConversationView

Modify:
- `web/src/features/agent/conversation-view.tsx`

Add planner-open state and supply:
- active language selection,
- channel/account labels,
- available channel chips,
- model summary if the final compact presentation needs it.

Preserve:
- restore-last-turn destination behavior,
- attachments,
- runtime submission,
- credit gating,
- voice/image behavior,
- navigation and live-run state.

Do not change Home/Create composer unless a shared primitive requires a no-behavior-change import/refactor.

## Task 6 — Compact secondary controls

Within the conversation composer only:
- keep send as the dominant action,
- keep model accessible without a second full-width permanent rail,
- collapse secondary tools to icon buttons at narrow widths when necessary,
- maintain >=44 px practical touch targets,
- keep labels available to assistive tech.

Do not hide model qualification/error state.

## Task 7 — Optional same-slice PlanCard visual refinement

Only after Tasks 1–6 are green, refine:
- `web/src/features/agent/plan-card.tsx`

Goal: when a real SchedulePlan exists, present a tidy `Ready to publish` summary with:
- destination → language rows,
- authoritative schedule,
- edit/change-time actions,
- preview links where already supported.

Rules:
- presentation-only,
- no new schedule parser,
- no client-side claim that a schedule exists before runtime returns one,
- preserve all existing confirmation/edit/cancel behavior.

If this threatens the core composer scope, leave it as a follow-up and record that explicitly.

## Task 8 — Automated regression tests

At minimum run the existing relevant tests:
- language dialog ops,
- composer accounts,
- composer attachments wiring,
- composer message limit,
- relevant conversation/home generation tests,
- schedule/PlanCard tests if PlanCard changed.

Add tests for:
- summary counts/labels,
- 5+ destinations,
- two accounts on same platform,
- same-language ON → OFF restoration,
- Apply vs Cancel,
- multi-language destination,
- message-provided language indicator/semantics.

Then run:
- web typecheck,
- lint,
- relevant web test suite.

Use repository-native commands discovered from package scripts; do not invent commands if names differ.

## Task 9 — Browser and visual QA

Use the project browser test stack.

Required viewports:
- 390 × 844,
- 430 × 932,
- 768 × 1024 if applicable,
- 1440 × 900.

Required engines:
- Chromium,
- WebKit/Safari-class.

Exercise:
1. 1 channel / 1 language,
2. 3 channels / 2 languages,
3. 5+ channels,
4. two accounts on same platform,
5. multi-language one destination,
6. shared-language ON → OFF,
7. Apply,
8. Cancel,
9. message language override,
10. attachments present,
11. busy/send-disabled,
12. keyboard navigation and Escape,
13. reduced motion.

Capture after screenshots at 390 and 430 and compare with the baseline.

Check:
- no horizontal overflow,
- no clipped locale/account text,
- no overlap with bottom nav / safe area,
- correct focus return,
- dialogs/pickers stay in viewport,
- console errors,
- failed network requests.

## Task 10 — Final handoff evidence

Before calling implementation complete, report:
- exact files changed,
- branch + commit,
- test commands and results,
- browser engines/viewports checked,
- physical vs emulated device status,
- screenshot paths/evidence,
- console/network result,
- any deferred PlanCard work,
- any blocker or unverified state.

Do not merge/deploy merely because the UI looks correct. Merge/deploy is a separate explicit execution/release step.
