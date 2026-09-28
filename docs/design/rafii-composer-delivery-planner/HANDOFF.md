# Coding-agent handoff — Rafii compact delivery planner

Use this prompt in a fresh coding-agent session.

---

Work in repository `dev-james0723/PostRiff`.

Continue from branch:

`codex/rafii-composer-delivery-planner-20260928`

Do not start by redesigning the feature from scratch. The product decision is already made.

Read first:

1. `docs/design/rafii-composer-delivery-planner/SPEC.md`
2. `docs/superpowers/plans/2026-09-28-rafii-composer-delivery-planner.md`
3. `docs/design/rafii-v9/briefs/C-language-model-dialogs.md`
4. `docs/design/rafii-v9/briefs/E-home-composer.md`
5. the current implementation files named by the plan.

## Objective

Fix the cramped Rafii **conversation chat composer** while preserving its existing multi-channel / per-channel-language power.

The default composer must become **compact-first**:
- replace the permanent horizontal `Draft for` channel/language pill rail with a concise Delivery Summary,
- show states such as `3 channels · 2 languages`,
- keep chat content visually dominant,
- keep model/voice/image/attachments/send functional.

Tapping the summary must open a structured **Channel × Language** planner:
- one destination/account per row,
- its language(s) in the same row/group,
- multiple languages on one destination preserved,
- multiple accounts on one platform preserved,
- `Use same language for all` supported as a staged, reversible mode,
- Apply commits,
- Cancel/Escape do not mutate the applied configuration,
- `+ Add channel` reuses existing destination selection semantics.

Do not create a second destination/language state model. Reuse the current:
- `useChannelLanguages`,
- `LanguageDialog` / `language-dialog-ops`,
- locale catalogue / picker,
- account-level `channelId` semantics.

## Important current-state finding

The default branch already has the correct underlying language model. The UI problem is primarily the permanent compact-composer presentation in `web/src/features/agent/composer.tsx`, where destination chips are rendered in a horizontal scrolling rail.

Do not regress:
- explicit language named in the user’s message wins for that draft but is not remembered,
- several languages per destination,
- account-level destination keys,
- destination restore from the previous turn,
- model qualification,
- reasoning,
- Writing Like Me,
- image generation,
- attachments / `@` mentions,
- slash commands,
- IME-safe send,
- consent,
- reminders,
- credit/submission gates.

## Scheduling

Do not infer a real schedule in the composer just because the user typed “Tuesday at 9”.

Only show a `Ready to publish` scheduled confirmation from the existing authoritative `SchedulePlan`/runtime state. If you refine `PlanCard`, keep it presentation-only and do that after the core composer/planner is green.

## Scope guard

No backend schema or migration work is expected.
No provider/OAuth/permission changes.
No paid-model changes.
Do not redesign Home/Create unless a shared no-behavior-change extraction is necessary.
Preserve unrelated concurrent work.

## Verification

Follow the plan exactly, including:
- relevant unit/regression tests,
- typecheck + lint,
- Chromium + WebKit,
- 390 × 844 and 430 × 932 mobile layouts,
- desktop 1440 × 900,
- screenshot-based layout QA,
- keyboard/focus/reduced-motion checks,
- console/network error checks.

Test at least:
- 1 channel / 1 language,
- 3 channels / 2 languages,
- 5+ channels,
- two accounts on the same platform,
- multiple languages on one destination,
- same-language ON → OFF restoration,
- Apply vs Cancel,
- message-language override,
- attachments,
- busy/send-disabled.

Do not merge or deploy as part of this handoff unless James separately asks for execution/release. Stop after implementation + verification and report the exact branch/commit, changed files, tests, screenshots, browser/device coverage, and anything still unverified.
