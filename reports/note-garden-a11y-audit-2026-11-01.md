# Note Garden accessibility audit (read-only)

| | |
|---|---|
| Product | Note Garden, the children's music game at `/play/note-garden` |
| Base | `origin/consumer-saas` @ `6b706eeb08c19300fc39186bfb32adea12849afa` (merge of PR #230). Every `file:line` below points at this commit |
| Date | 2026-10-31 (local run), report file dated 2026-11-01 as requested |
| Auditor | AO worker `rafii-9`, role 17-product-ux-accessibility; global task `m__YQxn1YdNwQirCsvos52QQ` |
| Scope | `web/src/app/play/**`, `web/src/components/music-game/**`, `web/src/lib/music-game/**`, `web/src/lib/play-launch.ts`, the root layout as it affects `/play`; all 7 screens (title, hello, map, learn L1–L4, question L1–L4, level done, grown-ups) and all 3 dialogs (leave, open all, reset) |
| Standard | WCAG 2.2, levels A and AA (AAA mentioned only as best practice). Severity: **high** = blocks a task for keyboard, screen-reader or low-vision users, or fails A/AA on essential UI; **medium** = significant barrier with a workaround, or an SC failure outside the core play loop; **low** = polish or best practice |
| Source changed | None. The only file added on the branch is this report |

## Method

1. **Source inspection** of every file in scope, line by line (≈3,850 lines including docs), against the intended behaviour in `docs/music-game/SPEC.md` and `DESIGN.md`.
2. **Contrast** computed with the WCAG 2.x relative-luminance formula from the CSS tokens at `web/src/components/music-game/note-garden.module.css:3-16`. `color-mix(in srgb, …)` values were interpolated per channel. The script was `/tmp/rafii9-probe/contrast.mjs`.
3. **Existing tests**, run unchanged: the unit tests and the repo's Playwright journey `web/tests/music-game-browser.cjs`, which already runs axe-core.
4. **Ad-hoc probes** (system temp dir, not in the repo: `/tmp/rafii9-probe/probe.cjs`, `probe2.cjs`, `probe3.cjs`, and in repair 1 `probe4.cjs`), run against a local production build. They used the repo's own Playwright and axe-core, with no new dependencies, and covered:
   - axe with tags `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice` (violations and incomplete) on 23 screen states: the 7 screens, the 3 dialogs, every level's question, hint, settled and done states, and the muted question;
   - keyboard: Tab sequence on every screen, with the computed `:focus-visible` outline and the bounding box for every stop;
   - focus placement after every screen change and every dialog action;
   - the Chromium accessibility tree (`ariaSnapshot`, and CDP `Accessibility.getFullAXTree` for the dialogs);
   - an inventory of live regions per state;
   - bounding boxes of every interactive element at 390×844 and 320×568;
   - focus against the sticky Next bar at 390×844, 320×568, 844×390 and 667×375;
   - `prefers-reduced-motion: reduce` vs `no-preference`, using `document.getAnimations()` and computed `animation-name` on each screen;
   - horizontal overflow at 320 px.

### Tools and environment

| Item | Version |
|---|---|
| macOS | 27.2 (26B123), Apple M3 Max |
| Node / npm | v24.22.2 / 11.19.1 (Homebrew `node@24`) |
| Next.js / React | 16.4.3 / 19.2.4 (from the lockfile, `npm ci` in this worktree) |
| Playwright / browser | 1.62.1 / Chromium (Chrome for Testing) 151.0.7922.34, headless |
| axe-core | 4.13.0 |
| Server | `RAFII_PLAY_ENABLED=1 next build` then `RAFII_PLAY_ENABLED=1 next start -p 3167 -H 127.0.0.1` (loopback only, stopped after the run). The launch switch was enabled only through its documented env var (`web/src/lib/play-launch.ts:7-9`) |

### Commands run (exit codes)

| Command (cwd `web/` unless noted) | Exit | Decisive output |
|---|---|---|
| `git fetch origin consumer-saas` (repo root) | 0 | `origin/consumer-saas` = `6b706eeb08c19300fc39186bfb32adea12849afa` |
| `git switch -c task/m__YQxn1YdNwQirCsvos52QQ 6b706eeb…` | 0 | `rev-parse HEAD` = base |
| `npm ci` | 0 | lockfile install |
| `node --test tests/music-game*.test.mjs` | 0 | `tests 59 · pass 59 · fail 0` |
| `RAFII_PLAY_ENABLED=1 node_modules/.bin/next build` | 0 | build complete |
| `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3167/play/note-garden` | 0 | `200` |
| `RAFII_NOTE_GARDEN_URL=http://127.0.0.1:3167 node tests/music-game-browser.cjs` | 0 | 16 × `ok`, `axeScreens:10`, `moderateOrMinor:[]` (0 axe violations of any impact) |
| `node /tmp/rafii9-probe/contrast.mjs` | 0 | ratios quoted below |
| `node /tmp/rafii9-probe/probe.cjs` | 1 | All data in this report was written to `out.json` before the failure. The script's final reduced-motion loop then timed out on a selector race (my script's bug, not an app failure); that part was re-run in `probe2.cjs` |
| `node /tmp/rafii9-probe/probe2.cjs` | 0 | dialog names, focus after Open all, reduced motion on settled and done screens |
| `node /tmp/rafii9-probe/probe3.cjs` | 0 | phone-landscape sticky-bar focus check |
| `kill <next start pid>` | 0 | port 3167 free afterwards |
| Repair 1: `RAFII_PLAY_ENABLED=1 next start -p 3167 -H 127.0.0.1` (same build of 6b706eeb; HEAD only adds this report) + `curl` | 0 | `HTTP 200` |
| Repair 1: `node /tmp/rafii9-probe/probe4.cjs` | 0 | L4 questions 4–6 picture named "Picture of the sound: Two hidden notes. Listen to them." (muted, and sound on + Help me) |
| Repair 1: `kill <pid 90102>` | 0 | port 3167 free afterwards |

## Summary

| Severity | Count | IDs |
|---|---|---|
| High | 1 | A11Y-01 |
| Medium | 4 | A11Y-02, A11Y-03, A11Y-04, A11Y-08 |
| Low | 3 | A11Y-05, A11Y-06, A11Y-07 |

| Category (from the brief) | Result |
|---|---|
| 1. Keyboard-only play, focus, order, traps, obscured focus | 1 finding (A11Y-03); everything else passes |
| 2. Accessible names and roles | 3 findings (A11Y-01, A11Y-05, A11Y-08); everything else passes |
| 3. Screen-reader announcements | 2 findings (A11Y-06, A11Y-07); core feedback and hints are announced |
| 4. Reduced motion | **No findings** |
| 5. Colour contrast (text, focus, non-text) | 1 finding (A11Y-04, stars); all text and focus indicators pass |
| 6. Target size | **No findings** |
| 7. Not relying on sound or colour alone | 3 findings (A11Y-02 sound, A11Y-08 sound, A11Y-04 colour) |

Automated result: axe-core 4.13.0 reported **0 violations** on all 23 probed states and 10 journey screens. It reported two kinds of `incomplete` result: `duplicate-id-aria` on the grown-ups screen (confirmed as A11Y-01) and `color-contrast` on SVG text and the dialog title. axe could not resolve those backgrounds, so they were computed by hand and all pass (see "No findings"). A clean axe run doesn't mean WCAG conformance: A11Y-02, 03, 04, 06, 07 and 08 were found by source reading and manual probing. A11Y-08 was added in repair 1, after independent review rafii-10 found it.

## Findings

### A11Y-01 — The Reset progress dialog is announced with the Open-all question (duplicate `id`) · **High**

- **Where:** `web/src/components/music-game/parts.tsx:45` (`aria-labelledby='ng-dialog-title'`) and `parts.tsx:51` (`<p id='ng-dialog-title' …>`). The id is a hard-coded constant, and `web/src/components/music-game/grown-ups.tsx:103` and `grown-ups.tsx:115` render two `ConfirmDialog`s on the same screen at the same time.
- **WCAG:** 4.1.2 Name, Role, Value (A); 1.3.1 Info and Relationships (A).
- **Evidence:**
  - On the grown-ups screen the DOM holds two elements with `id="ng-dialog-title"`: "Open all four levels on this device?" and "Delete stars on this device?" (probe2 `titleIdsInDom`).
  - With **Reset progress** open, Chromium's computed accessibility tree (CDP `Accessibility.getFullAXTree`) names the dialog **"Open all four levels on this device?"**. Its visible question is "Delete stars on this device?" and its buttons are **Cancel** / **Delete**. The `ariaSnapshot` shows the same: `dialog "Open all four levels on this device?": paragraph: Delete stars on this device? · button "Cancel" · button "Delete"`.
  - axe 4.13.0 flags this as `duplicate-id-aria` (incomplete) on the "D grown-ups" and "D open-all dialog" states.
- **Impact:** A screen-reader user who opens the destructive Reset confirmation hears a question about opening levels, then a **Delete** button. That is a wrong name on the one destructive action in the game.
- **Fix:** Give each dialog its own title id, for example `const titleId = useId();` in `ConfirmDialog`, then `aria-labelledby={titleId}` and `<p id={titleId}>`. Add a browser check that the open dialog's accessible name equals its visible question.

### A11Y-02 — With sound on, listening questions have no non-audio path unless the player finds the sound toggle · **Medium**

- **Where:** `web/src/components/music-game/play-screen.tsx`:
  - `play-screen.tsx:154` (`const showPicture = silent || picture;`);
  - `:75` (dots) and `:97` (rhythm), which show the picture only when `settled || showPicture`, and otherwise the text at `:67` ("Listen carefully. Tap “Hear it again” to listen once more.");
  - `:224`: **Hear it again** reveals the picture only `if (silent)`;
  - `:229`: **Help me** shows the picture only for Level 4 heard-only step/skip (`:79`, `isSoundPicture = showPicture || hint`); for L1 same/different, L1 up/down and L3 "Which rhythm did you hear?" the hint is audio ("Let's listen slowly.", "Listen again, slowly.").
- **WCAG:** 1.1.1 Non-text Content (A). The "test or exercise" exception applies to listening exercises, so this is **not** a strict conformance failure. It is reported because the brief asks whether deaf and hard-of-hearing players have a non-audio path, and the design intends one (DESIGN.md §112, SPEC "Sound off"). 1.3.3 Sensory Characteristics (A) is met: the prompts say "Listen" but don't rely on sound for *instructions*.
- **Evidence:**
  - In a live L1 question with sound on, the stage text before and after **Help me** was only "Listen carefully. Tap “Hear it again” to listen once more.", with no `img` in the stage (probe `stage["D L1 q1 before answer"]`, `["D L1 q1 after hint"]`).
  - With sound muted, the same question shows `img "Picture of the sound: two dots at the same height."` and the text "Sound is off. Here is a picture of the sound." (probe `stage["muted L1 q1"]`).
  - So the path exists: the **Sound on/off** toggle is on the play screen (`play-screen.tsx:246`). But nothing on a listening question says so.
- **Impact:** A deaf or hard-of-hearing child, or one on a device whose audio "works" but who can't hear it (no headphones in class), sees a question they can't answer. The workaround (turn sound off) is reachable but not discoverable from the question.
- **Fix:** Pick one:
  - (a) Show the existing picture when **Help me** is pressed on every sound-only question, not only L4. Mirror `:79` in the `dots` and `rhythm` cases: `settled || showPicture || hint`.
  - (b) Add a visible "Show me a picture" button next to **Hear it again** that sets `picture`, whatever the sound setting.
  - (c) Extend the `:67` text with "Can't hear it? Turn the sound off to see a picture."
  - Options (a) and (b) need no copy change to SPEC. Note: SPEC says hints never reduce stars, so (a) keeps scoring unchanged.

### A11Y-03 — Focus is lost to `<body>` after confirming **Open all levels** · **Medium**

- **Where:** `web/src/components/music-game/grown-ups.tsx:78-84`. The **Open all levels** button is replaced by a paragraph once `allOpen` is true. `grown-ups.tsx:109-112` confirms, and `parts.tsx:39` closes the native dialog, which tries to return focus to the now-removed button.
- **WCAG:** 2.4.3 Focus Order (A).
- **Evidence (Chromium, keyboard only):** On **Open all levels**, Enter, then **Open**, Enter:
  - `document.activeElement` is `BODY` (probe `focusAfter["open-all confirmed"]`, probe2 `afterOpenAll`);
  - the next **Tab** leaves the page (activeElement still `BODY`);
  - **Shift+Tab** lands on "Back to Rafii", the last control.
  - The status text "All levels are open." *is* announced through `role=status` (`grown-ups.tsx:89`).
  - For comparison: Cancel/Escape on the same dialog, and Cancel on Reset, return focus to the opening button. Leave/Keep playing on the play screen are also correct.
- **Impact:** Keyboard and screen-reader users lose their place in the grown-ups panel. Focus restarts from the end of the page (or the top in some screen readers). It's a one-off, adult-only action, which is why it isn't rated High.
- **Fix:** Move focus *after* React has committed the change and the dialog has closed. Calling `focus()` inside `onConfirm` doesn't work, for two reasons:
  - At that moment the new "All levels are open." paragraph isn't in the DOM yet, because `onOpenAll()` only queues a state update.
  - The modal `<dialog>` is still open. `ConfirmDialog` closes it in its own `useEffect` (`parts.tsx:35-40`), and while it's open, everything outside it is inert. `dialog.close()` then restores focus to the removed button, which is what leaves focus on `<body>`.

  Recommended, either of:
  - (a) In `GrownUps`, set a state flag in `onConfirm` (e.g. `setFocusAfter('open')`). Consume it in a `useEffect` that focuses the target and clears the flag. Use `useEffect`, not `useLayoutEffect`: React runs a child's passive effects before its parent's in the same commit, so by the time `GrownUps`'s effect runs, `ConfirmDialog` has already called `dialog.close()`. A parent `useLayoutEffect` would run while the dialog is still modal. Good targets:
    - the "All levels are open." paragraph (`grown-ups.tsx:79`), given `tabIndex={-1}` and a ref;
    - or the **Reset progress** button (`grown-ups.tsx:85`), which exists before and after.
  - (b) Give `ConfirmDialog` an optional `returnFocusTo` ref and focus it right after `dialog.close()` in its effect (`parts.tsx:39`).

  Test: in `web/tests/music-game-browser.cjs`, after pressing Enter on **Open**, assert that `document.querySelector('dialog[open]') === null` and that `document.activeElement` *is* the chosen destination. For example, `document.activeElement?.textContent?.trim() === 'All levels are open.'` (or `=== 'Reset progress'`), not merely that it isn't `BODY`. Add the same check for **Delete** in Reset progress, where the opener survives.

### A11Y-04 — Earned and empty stars differ only by a pale yellow fill (1.72:1 to 1.82:1), with no visible count · **Medium**

- **Where:** `web/src/components/music-game/drawings.tsx:250` (`fill={on ? 'var(--ng-sun)' : 'none'}`). Used by `StarRow` (`parts.tsx:7-16`) on the map (`note-garden.tsx:228`) and the level-done screen (`note-garden.tsx:270`). The count "N of 3 stars" exists only as screen-reader text (`parts.tsx:13`, `.srOnly`).
- **WCAG:** 1.4.1 Use of Color (A): the only difference between an earned and an unearned star is the fill colour. 1.4.11 Non-text Contrast (AA), as context: the yellow fill against the ink outline is 7.84:1, so the adjacent-colour test is met. The earned-vs-empty *difference* is what's low.
- **Evidence:** Computed from tokens: `--ng-sun #f2b705` vs `--ng-bg #fff8e7` (done screen) = **1.72:1**, and vs `--ng-card #ffffff` (map beds) = **1.82:1**. Both outlines are identical: ink `#1f2a44`, stroke 1.6 on a 24-unit viewBox. SPEC.md:147 asks for "best stars shown as ★★☆ with text '2 of 3 stars'". The text is present for screen readers only. On the done screen, the visible heading wording varies by star count (`curriculum.ts:129-133`) but never states the number.
- **Impact:** Low-vision players, or anyone on a washed-out screen, can't reliably tell 1 from 2 or 3 stars. Stars are the game's main progress signal, but no task is blocked, hence Medium.
- **Fix:** Show the existing text visibly: drop `.srOnly` from `parts.tsx:13` (or add a visible "2 of 3" next to the big stars on the done screen). Optionally give the empty star a distinct shape cue, such as a dashed outline or a lighter-weight stroke, so the earned/unearned difference doesn't depend on colour.

### A11Y-08 — On heard-only Level 4 step/skip items, the "picture of the sound" has no text equivalent · **Medium** (added in repair 1)

- **Where:**
  - `web/src/components/music-game/play-screen.tsx:78-80`: for `step-skip` items with `!q.seen` and not yet settled, the stage shows a `SoundDots` picture when the sound is off or the hint is shown (`isSoundPicture = showPicture || hint`). Its label is `` `Picture of the sound: ${q.stageLabel}` ``.
  - `web/src/lib/music-game/curriculum.ts:431-433`: `stageLabel` for unseen items is the constant `'Two hidden notes. Listen to them.'`.
  - `web/src/components/music-game/drawings.tsx:67-70`: `SoundDots` makes `label` the SVG's accessible name (`role='img' aria-label={label}`).
  - The heard-only items are questions 4–6 of every Level 4 round (`curriculum.ts:478-480`).
- **WCAG assessment:**
  - **1.1.1 Non-text Content (A)** has a test-or-exercise exception. An ear-training item may legitimately be audio-only, and its text alternative then only has to give a descriptive identification. "Two hidden notes. Listen to them." does that for the *sound*, so the audio stimulus itself is not a conformance failure.
  - The `SoundDots` graphic is different. It is the game's own non-audio equivalent of that sound, offered on purpose to players who can't use audio (DESIGN.md:112). It carries the information needed to answer: the two dots are drawn at the notes' relative heights (`drawings.tsx:64`). Its accessible name doesn't convey any of that, so in the same situation sighted players get an answerable picture and screen-reader users don't.
  - The picture is not the exercise itself. On Level 1, describing the same dots in text ("the second dot is higher", `curriculum.ts:233-237`) was judged not to invalidate the exercise. So I assess the L4 picture's name as **not** covered by the exception, a 1.1.1 gap for this graphic. It is also a gap against the brief's goal that nothing relies on sound alone (the 1.3.3 / 1.4.1 "single sensory channel" principle).
- **Severity — Medium, reasoning:**
  - It fully blocks *answering* these 3 of 6 items for screen-reader users who can't use the audio (deafblind players, or any screen-reader user playing muted). The text gives them nothing to tell step from skip, with sound off or with the hint shown, and no workaround exists within the item.
  - It is not High because the round still completes. A wrong answer on a 2-option item reveals the answer, and the reveal text and settled staff label (`play-screen.tsx:82-86`) are accessible. It also affects only the heard-only third of one level, and screen-reader users who can hear play it normally.
- **Evidence (live, `/tmp/rafii9-probe/probe4.cjs`, Chromium 151, production build of 6b706eeb):** on questions 4–6 of Level 4, the stage `img` was named **"Picture of the sound: Two hidden notes. Listen to them."**, both with sound muted and with sound on after **Help me**. The drawn dots differed: `cy` 61.6 → 74.2, 150 → 137.4, 30 → 42.6, 42.6 → 48.9, 80.5 → 74.2 (6.3 viewBox units per semitone). For comparison, Level 4 questions 1–3 ("Look and listen") are named by staff position, e.g. "Two notes: the first in the bottom space, the second in the second space from the bottom.", which screen-reader users can answer from.
- **Other heard-only items checked:**
  - **L1 same/different and L1 up/down** (`curriculum.ts:239-277`): the picture label comes from `dotsLabel` (`curriculum.ts:233-237`): "two dots at the same height" / "the second dot is higher|lower". That's equivalent to the drawing, so they're not affected (sound-on discoverability is A11Y-02).
  - **L3 "Which rhythm did you hear?"** (`curriculum.ts:386-401`): the picture label names every note ("Picture of the rhythm: short, short, long", using `RHYTHM_FEEL`, `:384`, `:397`). The answer cards are named with `TOKEN_WORDS` ("Rhythm A: quarter, quarter, half", `:101`, `:410`). The two vocabularies differ, so a screen-reader user has to map "short" to "quarter". A sighted sound-off player makes the same mapping from block lengths to note symbols, so the information is equivalent and this is not a finding. Polish: use one vocabulary in both labels.
- **Fix:** Pick one:
  - Simplest: when the sound picture is shown, give it the same accessible description the "seen" items and the settled staff already use. At `play-screen.tsx:80`, pass `` label={`Picture of the sound: the first note ${positionPhrase(stage.notes[0])}, the second ${positionPhrase(stage.notes[1])}.`} `` (the reasoning is the same as on questions 1–3).
  - Alternatively, describe the dots' movement as `dotsLabel` does on L1, e.g. "the second dot is one step higher" / "the second dot jumps over a line" (this states the answer, as the L1 label already does for up/down).
  - Add a browser check: on a muted L4 question 4, assert the stage `img` name isn't the "Two hidden notes" text.

### A11Y-05 — The Sound toggle changes its label *and* its pressed state · **Low**

- **Where:** `web/src/components/music-game/parts.tsx:68` (`aria-pressed={!muted}`) and `parts.tsx:72` (`{muted ? 'Sound off' : 'Sound on'}`). The component is used on the play screen (`play-screen.tsx:246`) and the grown-ups panel (`grown-ups.tsx:55`).
- **WCAG:** 4.1.2 Name, Role, Value (A) is satisfied, because the state is exposed. This is best practice from the WAI-ARIA APG button pattern: a toggle's label should not change when its state changes.
- **Evidence:** In the accessibility tree the control reads `button "Sound on" [pressed]`, then after activation `button "Sound off"` with `aria-pressed="false"` (probe notes `soundToggleBefore` / `soundToggleAfter`). A screen reader announces "Sound off, toggle button, not pressed", which is a double negative that young children (and their adults) may find confusing.
- **Fix:** Pick one:
  - Keep `aria-pressed` with a constant label ("Sound"), and show on/off visually with the icon plus a separate visible word.
  - Or drop `aria-pressed` and keep a changing *action* label ("Turn sound off" / "Turn sound on").

### A11Y-06 — The "Listen…" lock cue and the nudge on early taps are visual only · **Low**

- **Where:** `web/src/components/music-game/play-screen.tsx:38-48` (`ListenCue`, a plain `<p>`), `:259`, `:189-192` (an early tap only increments `nudges`, which wobbles the ear emoji), `:260` (`aria-busy` on the answers group) and `:277` (`aria-disabled` on each answer while locked).
- **WCAG:** 4.1.3 Status Messages (AA). "Listen…" is a status message that appears without a focus change, and it isn't in a live region.
- **Evidence:**
  - Accessibility tree during the lock (L4 question): `paragraph: Listen…`, `group "Answers"` containing `button "Step" [disabled]` and `button "Skip" [disabled]`.
  - The live-region inventory on question screens lists only `#ng-feedback` (`aria-live=polite`), the hint `role=status`, and the site's toast region. None of these contains the cue.
  - A screen-reader user who activates a locked answer hears nothing; the only feedback is the wobble.
- **Impact:** Small. The lock lasts at most 3.5 s (`play-screen.tsx:30`), hearing screen-reader users hear the question sound itself, and the state is exposed as dimmed/disabled. Deaf screen-reader users (for example on braille) get no explanation of why the answers are unavailable. Note: `aria-busy` on a group of controls may make some assistive technology hold back the group's contents. This was not tested with a real screen reader.
- **Fix:** Put the cue text into the existing hint/status region (or give the `ListenCue` `<p>` `role="status"`, keeping it mounted so the region exists before the text changes). Consider dropping `aria-busy` from the group, since `aria-disabled` already conveys the state.

### A11Y-07 — Learn-card changes are not announced (L2 letter reveal, L4 step/skip demo) · **Low**

- **Where:**
  - `web/src/components/music-game/learn-card.tsx:60`: an L2 staff tile's `aria-label` changes from "A note on …" to "C, a note on …" after activation, while focus stays on it.
  - `learn-card.tsx:91`: the L4 demo staff's `img` label changes when **Show a step** / **Show a skip** is pressed, and it isn't in a live region.
- **WCAG:** 4.1.3 Status Messages (AA), best-practice reading. The new letter or picture is the result of the action.
- **Evidence:** Probe `learnL2TileName`: before `"A note on its own little line below the staff"`, after `"C, a note on its own little line below the staff"`, with 0 live regions inside `main`. Probe `learnL4DemoLabelAfterSkip`: the label updated, and `announced: false` (no `aria-live` or `role=status` ancestor). Whether a screen reader re-reads the changed name of a focused button differs by screen reader and browser, and was not tested here.
- **Fix:** Add one visually hidden `role="status"` region to `LearnCard` and write "C" / "That was a skip: …" into it on activation.

## Observations (not rated as findings)

- **Feedback may be spoken twice.** `#ng-feedback` is `aria-live="polite"` (`play-screen.tsx:309`), and **Next**, which receives focus when settled, is `aria-describedby='ng-feedback'` (`play-screen.tsx:347`). Some screen readers will read the feedback from the live region and again as Next's description. This is intentional per the code comment at `music-game-browser.cjs:192` and DESIGN §108. Verify with VoiceOver/NVDA before changing it.
- **The question number isn't spoken on a new question.** Focus moves to the prompt `h2` (`play-screen.tsx:169`); "Question 2 of 6" (`play-screen.tsx:242-245`) sits in the nav and isn't part of that announcement. It's still reachable by reading, so it's polish only.
- **Tried (disabled) answers use `--ng-disabled #6b7280` on `#f6f1e4` = 4.29:1** (`note-garden.module.css:232-237`). Inactive controls are exempt from 1.4.3, and the "✕ Tried" mark is clay `#a84300` on `#f6f1e4` = 5.37:1. No finding.

## Categories and checks with no findings, and how that was concluded

### Category 4 — Reduced motion: no findings
- **Source:** `note-garden.module.css:772-784` sets `animation: none` for every animated selector (`.screen` fadeIn, `.answer[data-state='right']` ring, `.answer[data-shake='true']` shake, `.bigStars svg[data-on='true']` pop, the `.listenCue` wobble, `.pipBob` bob), and replaces the flower `bloom` (scale and rotate) with a 150 ms opacity fade. I grepped every `animation:` declaration in the module (lines 50, 242, 246, 267, 387, 468, 518) and each one is covered.
- **JS motion:** the only JS-driven movement is `window.scrollTo(0, 0)` (`play-screen.tsx:168`) and `scrollIntoView({ block: 'nearest' })` (`:179`, `:185`). Neither passes `behavior: 'smooth'`, and the computed `scroll-behavior` of the root was `auto` in the probe, so both are instant jumps. The global styles (`web/src/styles/globals.css`, `rafii.css:557-559`) add no smooth scrolling to `/play`.
- **Live:** with `reducedMotion: 'reduce'`, `document.getAnimations()` returned `[]` and no element under `main` had a computed `animation-name` other than `none` on title, hello, map, question, the early-tap nudge, the settled question and level done (probe `motion["RM …"]`, probe2 `rmSettled`, `rmDone`). With `no-preference`, the level-done screen ran `fadeIn` and `pop` ×2 (probe2 `noPrefDone`), so the emulation was in effect. The existing journey also asserts this (`ok - AC8 prefers-reduced-motion respected`).
- No flashing content was found (2.3.1). Pip's bob runs 3 × 3 s and stops (`note-garden.module.css:518`).

### Category 6 — Target size: no findings
- **Source:** `.button, .answer, .ghost, .iconButton` have `min-height: 64px; min-width: 64px` (`note-garden.module.css:100-107`); `.linkButton` has `min-height: 64px` (`:162`); `.answer` 72 px (`:206`), or 120 px for cards (`:220`); `.bed` 96 px (`:402`); `.learnTile` 120 px (`:549`).
- **Live:** I measured every visible `button`, `a[href]`, `input` and `label` on title, grown-ups, the dialog, map, learn L1–L4 and question L1–L4 at 390×844 and 320×568. The smallest enabled targets were the two volume radios' `<input>` at **24×24** (`note-garden.module.css:613-614`), which sit inside their `<label>` targets of **121×64**, so the effective hit area is the label. Every other control was **≥ 64×64**. This passes 2.5.8 (AA, 24 px) and the project's own 48 px goal; 64 px also meets 2.5.5 (AAA, 44 px).

### Category 1 — Keyboard: passes apart from A11Y-03
- **2.1.1 Keyboard:** every control is a native `<button>`, `<a href>` or `<input type=radio>`. There are no click handlers on non-interactive elements (grep of `onClick` in `components/music-game/*.tsx`).
  - The existing journey completes Level 1 keyboard-only (`ok - AC2/AC6 level 1 completed with the keyboard only`), toggles mute by keyboard, and resets progress.
  - My probe tabbed through every screen at 1280×900. It reached every learn tile (L1 ×2, L2 ×6, L3 ×5, L4 ×2), every answer on L1–L4, **Hear it again**, **Help me**, **Next**, **Back** (leave dialog), the Sound toggle, the volume radios (Arrow keys changed Soft→Medium), **Open all levels**, **Reset progress**, **Back**, **Back to Rafii**, **Play again**, **Next level** and **Garden map**. It played L1–L4 to the level-done screen by keyboard (Enter on the focused answer), using **Open all levels** to unlock L2–L4.
- **2.1.2 No Keyboard Trap:** on every screen, Tab past the last control left the document (`<body>` reached). The native modal `<dialog>`s cycle Cancel → Confirm → out, and **Escape** cancels (`parts.tsx:46-49`). This was verified on the leave and open-all dialogs; focus returned to the opener.
- **2.4.3 Focus Order:**
  - Tab sequences matched the visual order on every screen. Play screen: Back → Sound → answers → Hear it again → Help me, then Next once settled.
  - Screen changes focus the new `h1`/`h2`: map heading after Leave, the level-done heading on all 4 levels, the prompt `h2` per question (journey assertion).
  - A wrong answer focuses the first open answer, and a settled question focuses **Next** (`play-screen.tsx:176-181`).
  - The only failure is A11Y-03.
- **2.4.7 Focus Visible:** all 115 Tab stops recorded across 26 screen-state sequences (115/115) matched `:focus-visible`, with computed `outline: solid 3px rgb(106, 44, 145)` (`note-garden.module.css:27-30`). The radio's label shows the same ring through `:has(input:focus-visible)` (`:624-627`). The global styles have no `outline: none` that applies to `/play`.
- **2.4.11 Focus Not Obscured (Minimum):** the sticky Next bar (`note-garden.module.css:358-363`, and `:713-716` in landscape) never fully covered a focused element. I tabbed both directions on settled L1–L4 questions at 390×844 and 320×568, and on settled L1 at 844×390 and 667×375: overlap was **0 px** at every stop, and every stop was within the viewport. `scroll-margin-block: 96px` on focus (`:32-34`) supports this.

### Category 2 — Names and roles: passes apart from A11Y-01, A11Y-05 and A11Y-08
- **Buttons, toggles, dialogs:** every button has a text name; icons and emoji are `aria-hidden` (e.g. `play-screen.tsx:240, 282, 320, 325`). The dialogs are native `<dialog>` with `aria-labelledby` (wrong only in A11Y-01). Volume is a `<fieldset>` with a `<legend>` (`grown-ups.tsx:57-67`).
- **Answers:** text answers are named by their visible text. Note cards have `aria-label="A note on …"`, rhythm cards `"Rhythm A: ta, ta, ta-a"`, and fill-bar cards `"Quarter note, 1 beat"` (`curriculum.ts:321, 355, 410`). Tried and right states are added to the name (", tried", ", Yes"/", Answer") and shown visibly as "✕ Tried" / "✓ Yes".
- **2.5.3 Label in Name:** checked for each control with visible text. Each accessible name contains its visible label: "Back" ⊂ "← Back"; "1 beat" ⊂ "Quarter note, 1 beat"; "Rhythm A" starts "Rhythm A: …"; bed names "Level 1: High or Low? … 0 of 3 stars" contain the visible title.
- **SVGs (1.1.1):**
  - The stage staff, beat bar, symbol, sound-dot and rhythm-block pictures are `role="img"` with a text label (`drawings.tsx:35, 70, 128, 162, 184`). Labels match what the picture shows (staff positions, "the second dot is higher", "short, short, long"). The exception is the sound-dot picture on heard-only L4 items, whose label omits the dot heights (A11Y-08). The repair-1 re-check covered every `SoundDots`, `RhythmBlocks` and `Staff` label source (`play-screen.tsx:73-97`, `curriculum.ts:233-237, 397, 431-433`).
  - Pip, flowers, stars and the clef are `aria-hidden` (`drawings.tsx:39, 203, 228, 247`). Their information is given in text elsewhere: the stars have screen-reader text, Pip's lines are real text, and the flowers are explicitly decorative.
  - Map beds include the star count in the button name.
- **1.3.1:** one `main` per screen, a `nav "Game"` on the play screen, and headings h1 → h2. The answers are a `group "Answers"`; the map is a list. `lang="en"` is set on `<html>` (root layout) and on the game root (`note-garden.tsx:153`). The title is "Note Garden · Rafii" (2.4.2).
- axe 4.13.0 (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice): 0 violations on 23 states.

### Category 3 — Announcements: passes apart from A11Y-06 and A11Y-07
- **New question:** focus moves to the prompt `h2` (`play-screen.tsx:169`), so it's read.
- **Feedback** (right / try again / reveal) goes into `#ng-feedback` `aria-live="polite"` (`play-screen.tsx:309-315`). The live inventory showed "Let's see together. They were different notes." etc. after answers on L1–L4.
- **Hints** go into a `role="status"` region (`play-screen.tsx:328-335`). Live text appeared after **Help me** on L1–L4, e.g. "Line notes from the bottom: E G B D F. Every Green Bug Digs Fast!"
- **Level done:** focus moves to the heading (e.g. "Great work! Your flowers are blooming!"), and "2 of 3 stars" follows in the tree.
- **Grown-ups:** results are announced through `role="status"` (`grown-ups.tsx:89-91`).

### Category 5 — Contrast: passes apart from A11Y-04
All values are computed from the tokens at `note-garden.module.css:3-16`, with text size and weight taken from the module.

| Pair | Ratio | Needed |
|---|---|---|
| Ink `#1f2a44` on bg `#fff8e7` / card `#fff` / hint `#fcefc8` | 13.47 / 14.26 / 12.44 | 4.5 |
| Muted `#4a5568` (`.small`, `.notice`, `.bedNote`, `.counter`, `.tagline`; 16–20 px) on bg / card / `#f6f1e4` | 7.11 / 7.53 / 6.67 | 4.5 |
| White on leaf `#0b6e4f` (`.button`) / hover `#095c42` | 6.25 / 8.01 | 4.5 |
| Leaf on card (`.markRight`, 18 px bold = normal text; staff letters) | 6.25 | 4.5 |
| Leaf / clay `#a84300` / sky-deep `#0072b2` on bg (feedback leads 24 px bold, "Listen…" 22 px bold = large) | 5.91 / 5.72 / 4.90 | 3 |
| Ink on SVG fills: sky dot `#56b4e9`, sun `#f2b705`, orange pot `#e69f00`, mint `#cdefe3` | 6.18 / 7.84 / 6.33 / 11.58 | 4.5 |
| Focus ring `#6a2c91` on bg / card | 8.33 / 8.82 | 3 |
| Ink borders of answers, beds, ghost and icon buttons on bg / card | 13.47 / 14.26 | 3 |
| Right-answer ring leaf on bg; checked-radio ring sky-deep on card | 5.91 / 5.19 | 3 |

- The focus ring next to the checked-radio ring is purple against sky-deep, 1.70:1. Its outer edge is against the card at 8.82:1, so the indicator stays visible.
- The axe `color-contrast` "incomplete" nodes were the `aria-hidden` "←" in Back (ink on card), SVG `<text>` (computed above), and the leave-dialog title (ink on card, 14.26:1). All pass.
- The sound-dot fills (sky 2.31:1, sun 1.82:1 on card), the hint border and the card borders are below 3:1. They're not findings: the dots are identified by their ink outline and the numbers "1"/"2", and the borders are containers, not controls.

### Category 7 — Sound and colour: passes apart from A11Y-02, A11Y-08 and A11Y-04
- **Colour (1.4.1):**
  - Right vs tried answers use ring plus "✓ Yes"/"✓ Answer" text vs a dashed border plus "✕ Tried" text (`play-screen.tsx:289-301`, `note-garden.module.css:232-243`).
  - Try-again vs correct feedback differ in wording, not only in clay/leaf.
  - Locked beds show 🔒, the text "Finish Level N to open", a dashed border and `disabled`.
  - Sound dots are numbered "1"/"2" as well as coloured (`drawings.tsx:74-77`). The beat bar's gap is dashed, not just coloured.
  - The Sound toggle's state is in its text.
- **Sound:** every sound-carrying question has a picture with a text label when sound is off or unavailable (`play-screen.tsx:155`, verified muted on L1, and the journey asserts `ok - AC3 muted questions show a picture of the sound and stay answerable`). For sighted players, no essential information is sound-only once sound is off. For screen-reader users with sound off, L1 (same/different, up/down) and L3 (which rhythm) pictures have text equivalents, but heard-only L4 step/skip items do not (A11Y-08, verified live on questions 4–6). The gap when sound is on is A11Y-02.

## Limitations

- **No real screen reader was used** (VoiceOver, NVDA, JAWS or TalkBack). Announcement behaviour is inferred from roles, live regions and Chromium's accessibility tree. A11Y-06, A11Y-07 and the "spoken twice" observation should be confirmed with VoiceOver + Safari and NVDA + Firefox/Chrome.
- **Chromium headless only.** No Safari/WebKit, Firefox, iOS or Android device, so `:has()`, native `<dialog>` focus restoration and `aria-busy` handling were not checked per browser. A11Y-03 is caused by the button being removed, so it should reproduce everywhere, but it was observed only in Chromium.
- **No zoom or text-spacing test** at 200%/400% (1.4.4, 1.4.10, 1.4.12) beyond checking that 320 px wide viewports had no horizontal overflow (`scrollWidth == clientWidth` on all probed screens). No Windows High Contrast / forced-colors check.
- **Contrast was computed from tokens**, not sampled from rendered pixels. Emoji glyph colours are font-dependent and were not assessed (they're all `aria-hidden` and paired with text).
- **No testing with children** (also noted in `docs/music-game/RUNNING.md:257`). Ages 6–10 may need simpler status wording than adults; that's out of scope here.
- In my keyboard play-through, answers were activated with Enter after focusing them programmatically (for speed). Reachability by Tab was proven separately by the per-screen Tab sequences, and the repo journey plays L1 with Tab and Enter only.
- The live run used a production build of this exact commit with `RAFII_PLAY_ENABLED=1`. No production or preview URL was contacted.
