# Rafii Conversation Composer — Compact Delivery Summary + Channel × Language Planner

Date: 2026-09-28  
Status: approved design direction, implementation not started  
Target: Rafii conversation chat composer (mobile-first, responsive)  
Base: `consumer-saas` at `8cd7ad91` when this spec was created

## 1. Why this change

The current conversation composer is functionally powerful but visually cramped on phones. The main cause is not the textarea itself. It is that several controls are permanently expanded at the same time:

- a horizontally scrolling `Draft for` row,
- one segmented `ChannelLanguageChip` per destination,
- one or more languages inside each destination chip,
- a separate model/tool row,
- attachments, reminders and the send action.

On a phone, the relationship between **channel** and **language** is also harder to scan because the horizontal pill rail is spatial rather than tabular. With three or more channels, important state can sit half off-screen.

The redesign must keep the existing power:
- multiple channels,
- multiple connected accounts on the same platform,
- one or more output languages per destination,
- message-specified language overrides,
- remembered per-platform language preferences,
- model / writing voice / image controls,
- attachments,
- existing publishing and scheduling semantics.

The goal is **not** to remove capability. It is to compress the default state and reveal the detailed controls only when the user asks for them.

## 2. Verified current implementation

The current default branch already has the required data model and most language behavior.

### Current code path
- `web/src/features/agent/composer.tsx`
  - builds destination rows from `chips` + `useChannelLanguages`,
  - renders the horizontal `Draft for` scroller,
  - renders `ChannelLanguageChip`,
  - renders model / voice / image controls,
  - preserves message-language precedence and reminders.
- `web/src/features/agent/use-channel-languages.ts`
  - supports account-level destination keys,
  - supports several languages per destination,
  - produces one outbound destination per `(destination, language)`,
  - remembers language settings without silently changing sibling accounts.
- `web/src/features/agent/language-dialog.tsx` + `language-dialog-ops.ts`
  - already implement staged language editing,
  - already support several languages per destination,
  - already implement the reversible “All channels use the same language” mode,
  - already preserve Cancel/Escape semantics.
- `web/src/features/agent/conversation-view.tsx`
  - owns conversation composer state and restores the previous turn’s destinations.
- `web/src/features/agent/plan-card.tsx`
  - already owns scheduling-plan presentation/interaction.
- `web/src/features/agent/home/idea-composer.tsx`
  - is a separate v9 Home/Create composition surface and is **not** the primary target of this change.

There should be **no backend schema, migration, provider permission, OAuth, publishing-rights, or scheduling-engine change** for this task.

## 3. Product decision

Use a two-level interaction:

1. **Compact summary by default**
   - chat remains visually dominant,
   - the composer shows a short delivery summary instead of every destination/language control,
   - essential send/attachment actions remain directly available.

2. **Expanded Delivery Planner on demand**
   - tapping the summary opens a structured vertical `Channel × Language` editor,
   - every destination and its language(s) are shown on the same row,
   - “Use same language for all” is available without destroying the user’s individual staged choices,
   - the user applies or cancels explicitly.

The design should feel like an AI coworker that understands intent, not a permanently expanded social publishing dashboard.

## 4. Default compact composer

### 4.1 Visual hierarchy

Order inside the compact conversation composer:

1. message textarea,
2. attachment strip only when attachments exist,
3. **Delivery Summary trigger**,
4. compact secondary tools + primary send button,
5. blockers/reminders only when relevant.

The horizontal `Draft for` chip rail is removed from the default compact state.

### 4.2 Delivery Summary trigger

Suggested structure:

```text
┌──────────────────────────────────────┐
│  [in] [ig] [th]  3 channels         │
│                  2 languages     ›   │
└──────────────────────────────────────┘
```

For one destination:

```text
LinkedIn · 繁體中文（香港）        ›
```

For several destinations:

```text
[in][ig][th]  3 channels · 2 languages  ›
```

If one destination has several languages:

```text
Instagram · English +2              ›
```

If there are multiple accounts on the same platform, the count is by destination/account selection key, not by unique platform.

### 4.3 Summary rules

The summary must:
- use real `ChannelIcon` marks,
- show at most three destination icons before `+N`,
- count unique effective language tags across active destinations,
- show a concise human-readable single-destination label when there is only one,
- never require horizontal scrolling,
- never truncate the only visible information about whether multiple languages are active,
- show an accessible expanded description through `aria-label` or visually hidden text.

Examples:
- `LinkedIn · 繁體中文（香港）`
- `3 channels · 2 languages`
- `5 channels · 4 languages`
- `Instagram · English +2`

The model is global, not per-channel. Keep model access in the compact tools area or an adjacent small setting trigger; do not imply the model varies per destination.

### 4.4 Composer size target

At 390 × 844 with a one-line message and no attachment chips:
- no essential control may scroll horizontally,
- the non-textarea composer chrome should target roughly 104–136 px,
- the compact composer should be materially shorter than the current `Draft for` + tool-rail layout,
- the conversation should regain enough vertical space that the composer no longer dominates the viewport.

Do not achieve this by shrinking text below the existing readable sizes.

## 5. Delivery Planner

### 5.1 Presentation

Use the project’s existing Rafii dialog/sheet primitives.

Responsive behavior:
- phone: bottom sheet / full-width sheet behavior with safe-area padding,
- tablet/desktop: centered or anchored dialog using the existing `RafiiDialog` system,
- max content height: bounded; matrix scrolls internally when necessary,
- focus returns to the Delivery Summary trigger on close.

Do not create a separate custom modal system.

### 5.2 Header

Recommended:

```text
Publish to
Choose channels and output language
```

Optional secondary summary:
`3 channels · 2 languages`

### 5.3 Channel × Language matrix

Every active destination is one row:

```text
[in] LinkedIn · James        繁體中文（香港）  ›
[ig] Instagram · Studio      English           ›
[th] Threads                 繁體中文（香港）  ›
```

For a destination with multiple languages:

```text
Instagram · Studio
English   Español   + Add language
```

Rules:
- destination identity stays left,
- its language control(s) stay in the same row/group,
- account name is shown when necessary to disambiguate two accounts on the same platform,
- language labels use the existing locale catalogue, flags/native names and `LanguageName`,
- `+ Add language` uses existing language picker behavior,
- removal never allows a selected destination to end with zero languages,
- no horizontal carousel for core configuration.

### 5.4 Channel selection

Add a clear `+ Add channel` row below the matrix.

It must reuse existing account/destination selection behavior rather than inventing a parallel source of truth. The selected state ultimately remains `useChannelLanguages().selection` and must preserve `channelId`.

Removing a destination from the planner must use the existing selection/toggle semantics and must not revoke/disconnect the account.

### 5.5 “Use same language for all”

Show a switch near the matrix heading:

```text
Use same language for all           [off]
```

Required semantics:
- OFF: every destination keeps its own staged language list.
- ON: user selects one shared language to apply to all destinations.
- Turning ON must **not** destroy the previously staged individual configuration.
- Turning OFF before Apply restores the staged per-destination configuration.
- Apply commits the chosen state.
- Cancel, backdrop close and Escape leave the applied configuration unchanged.

Do not call `languages.useEverywhere()` immediately on toggle. Reuse the existing staged behavior from `LanguageDialog` / `language-dialog-ops`.

### 5.6 Message-specified language

The existing rule remains:
- a language explicitly named in the user’s message wins for that draft,
- message-specified language does not overwrite remembered language settings.

In the new summary/planner, show a small non-blocking “From message” indicator for affected language values. It must be discoverable to assistive technology. Avoid relying on color alone.

### 5.7 Reminders

Preserve:
- regionless locale warning,
- untuned-language wording warning,
- gendered-language self-reference prompt.

In compact mode:
- show only the first relevant reminder plus `+N more`.

In the planner:
- show reminder(s) adjacent to the destination/language they affect when practical.

Reminders remain non-blocking.

## 6. Model, voice, image and attachment controls

This change is primarily about destination/language layout.

Preserve all existing behavior:
- model qualification and priced-route send guard,
- reasoning selection,
- Writing Like Me / neutral voice,
- image-generation availability and state,
- attachment blockers and `@` mention behavior,
- slash commands,
- IME-safe `⌘/Ctrl + Enter`,
- message character limit.

Design requirement:
- no second full-width horizontal control rail on phones,
- secondary tools can collapse to icons at narrow widths,
- primary send action remains visually dominant,
- tool labels remain available to screen readers and via title/tooltip where the project already does so.

## 7. Scheduling / “Ready to publish”

Do not create fake pre-submit schedule state just because the message text says “Tuesday at 9”.

The schedule is authoritative only after the existing agent/runtime produces a real `SchedulePlan`.

When a real plan exists, improve the existing `PlanCard` presentation into a compact “Ready to publish” confirmation surface:

```text
Ready to publish                         Edit

LinkedIn      繁中                   Preview
Instagram     English                Preview
Threads       繁中                   Preview

Schedule
Tue · 9:00 AM
```

This card should:
- read from the existing plan/run data,
- not duplicate scheduling logic,
- keep existing confirmation/edit/cancel behavior,
- allow platform previews where the current preview path supports them.

## 8. Proposed component architecture

### New
- `web/src/features/agent/delivery-summary.tsx`
  - pure presentational summary + helper for counts/labels.
- `web/src/features/agent/delivery-planner.tsx`
  - responsive Rafii dialog/sheet with channel × language matrix.
- `web/src/features/agent/delivery-planner-state.ts`
  - optional staged state/helper layer if extraction from `language-dialog-ops.ts` needs a stable reusable API.
- `web/src/features/agent/delivery-summary.test.cjs`
- `web/src/features/agent/delivery-planner-ops.test.cjs` if new state logic is introduced.

### Modify
- `web/src/features/agent/composer.tsx`
  - replace permanent `Draft for` horizontal rail with `DeliverySummary`,
  - retain send guards and compact tools,
  - expose/open planner state cleanly.
- `web/src/features/agent/conversation-view.tsx`
  - provide account labels / selected destination data,
  - own planner open state if needed,
  - keep destination restore behavior intact.
- `web/src/features/agent/language-dialog.tsx`
  - extract/share staged matrix behavior rather than copying it.
- `web/src/features/agent/language-dialog-ops.ts`
  - only if a small reusable staged API is needed; preserve existing tests.
- `web/src/features/agent/plan-card.tsx`
  - presentation-only refinement for ready-to-publish state, if included in this implementation slice.

### Avoid unless required
- `use-channel-languages.ts`: current semantics are already sufficient.
- backend/API/migrations.
- provider publishing code.
- OAuth/permissions.
- Home/Create composer structure.

## 9. Responsive behavior

### 320–389 px
- one compact Delivery Summary row,
- icon-only secondary tools where necessary,
- planner rows may stack destination identity above language controls,
- input font stays >=16 px where needed to avoid iOS zoom,
- no horizontal page overflow.

### 390–430 px
- preferred phone layout,
- destination identity and primary language fit on one row for common labels,
- multi-language rows wrap inside their own row, not the whole dialog.

### 768 px
- planner remains dialog/sheet, matrix uses one row per destination.

### Desktop 1440 × 900
- compact conversation composer still uses summary-first behavior,
- planner may render as centered dialog rather than bottom sheet,
- do not regress desktop keyboard interaction.

## 10. Accessibility

Required:
- Delivery Summary: real button, `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls`.
- Planner: labelled dialog, focus trap via existing Rafii primitive, Escape behavior, focus return.
- Same-language switch: `role="switch"` or project-standard accessible switch semantics.
- Every language picker announces destination + current language + action.
- “From message” state is expressed in text/ARIA, not color only.
- minimum practical touch target 44 × 44 px on mobile.
- keyboard can reach every destination, language picker, add/remove, Apply and Cancel.
- reduced motion removes nonessential slide/height animation.
- maintain readable contrast in dark and light themes.

## 11. Non-goals

Do not:
- redesign the whole conversation page,
- change agent scheduling semantics,
- add provider permissions,
- change publishing eligibility,
- add new paid model behavior,
- change destination persistence semantics,
- remove support for multiple languages on one destination,
- remove account-level selection,
- regenerate or translate existing drafts when language settings change.

## 12. Acceptance criteria

Functional:
1. User can select 1–N destinations and assign a specific language to each.
2. Two accounts on the same platform remain separate destinations.
3. One destination can still have several languages.
4. “Use same language for all” is staged and reversible before Apply.
5. Cancel leaves the previously applied configuration untouched.
6. Apply produces the same `Destination[]` semantics as today.
7. Explicit message-language overrides still win for the current draft without changing remembered settings.
8. Send guards, model qualification, attachments, voice, image and IME behavior remain unchanged.

Layout:
1. At 390 × 844, no essential composer control requires horizontal scrolling.
2. The default composer is visibly shorter than the current pill-rail implementation.
3. 3 channels / 2 languages is readable without opening the planner.
4. 5+ channels does not create a multi-row chip wall.
5. Long locale/account names wrap or truncate intentionally without overlap.
6. No clipping behind iOS safe area or bottom navigation.
7. No dialogs, popovers or language lists render off-screen.

Accessibility:
1. Keyboard-only planner flow works.
2. Focus returns to the summary trigger.
3. Dialog, switch, language pickers and send action have correct accessible names/roles.
4. Reduced-motion mode avoids nonessential movement.

Regression:
1. existing language-dialog ops tests stay green,
2. composer message-limit and attachment wiring tests stay green,
3. composer account selection tests stay green,
4. existing scheduling/plan tests stay green.

## 13. Verification contract

Run at minimum:
- targeted unit/component tests for new summary/planner helpers,
- existing language-dialog tests,
- existing composer account / attachments / message-limit tests,
- typecheck,
- lint,
- relevant web test suite.

Browser/device:
- Chromium + WebKit,
- 390 × 844,
- 430 × 932,
- 768 × 1024 when practical,
- 1440 × 900.

Exercise:
- 1 channel / 1 language,
- 3 channels / 2 languages,
- 5+ channels,
- two accounts on one platform,
- several languages on one destination,
- shared-language ON → OFF restoration,
- Apply vs Cancel,
- message language override,
- long locale names,
- attachment present,
- busy/send-disabled state,
- keyboard + Escape,
- reduced motion.

Visual QA:
- screenshots before/after at 390 and 430 widths,
- check alignment, rhythm, text wrapping, clipping, overflow, sticky/fixed layers and safe areas,
- inspect browser console and failed network requests.

## 14. Product rationale

The core layout rule is:

**Conversation first. Delivery configuration summarized. Detailed publishing controls expanded only on demand.**

The important relationship is not “all channels” next to “all languages.” It is:

- LinkedIn → 繁體中文（香港）
- Instagram → English
- Threads → 繁體中文（香港）

That relationship is why the expanded state is a vertical matrix, not another horizontal carousel.

The compact state then reduces the same configuration to a legible summary:
`3 channels · 2 languages`.

This keeps Rafii feeling like a coworker while preserving the power-user publishing model already present in the codebase.
