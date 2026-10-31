# Note Garden — Visual, Motion & Audio Design (v1)

Stack: React 19 + Tailwind 4 (already in `web/`), inline SVG and the Web Audio API. **No new dependencies, images,
fonts or audio files.** Scope the theme to the route (e.g. a `.note-garden` wrapper with CSS variables) so it doesn't
leak into Rafii's app themes. The game uses this light theme regardless of the site theme.

## 1. Direction

*A calm picture-book garden.* Cream paper, deep-navy ink, and flowers that bloom as the child learns. It is friendly
for 6-year-olds without looking babyish to 10-year-olds: flat shapes, rounded corners, one mascot, and no glitter or
confetti storms. Every answer carries **an icon and a word**, never colour alone (WCAG 1.4.1).

## 2. Palette (contrast measured with the WCAG 2.x relative-luminance formula)

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--ng-bg` | `#FFF8E7` | page (cream) | — |
| `--ng-card` | `#FFFFFF` | cards, staff paper | — |
| `--ng-ink` | `#1F2A44` | text, staff lines, notes | 13.47:1 on bg · 14.26:1 on card |
| `--ng-muted` | `#4A5568` | secondary text | 7.11:1 on bg |
| `--ng-leaf` | `#0B6E4F` | primary buttons (white text), ✓ ring | white on it 6.25:1 · as ring on bg 5.91:1 |
| `--ng-sky` | `#56B4E9` | "high"/bird accents (ink text on it) | ink on it 6.18:1 |
| `--ng-sky-deep` | `#0072B2` | selected state (white text) | white on it 5.19:1 |
| `--ng-sun` | `#F2B705` | stars, sunflower (ink text on it) | ink on it 7.84:1 |
| `--ng-orange` | `#E69F00` | "low"/frog accents (ink text) | ink on it 6.33:1 |
| `--ng-clay` | `#A84300` | "Try again" ✕ marker and text | 5.72:1 on bg · white on it 6.06:1 |
| `--ng-petal` / `--ng-mint` | `#F7C6D9` / `#CDEFE3` | flower and garden fills (decor) | ink on them 9.53 / 11.58:1 |
| `--ng-focus` | `#6A2C91` | focus ring | 8.33:1 on bg · 8.82:1 on card |
| `--ng-disabled` | `#6B7280` | "Tried" label text | 4.57:1 on bg (AA) |

The accent hues come from the Okabe–Ito colour-blind-safe set. **No red–green pairing**: "correct" is leaf + ✓ and
"try again" is clay + ✕ + the word. Non-text UI parts (button borders, staff lines, focus ring) are all ≥ 3:1 (1.4.11).

## 3. Typography

Use **Geist**, already loaded by `web/src/app/layout.tsx`, so no new font is needed. Use weights 500/700, and show
numbers with `font-variant-numeric: tabular-nums`.

| Role | Phone | Tablet/desktop | Weight / line-height |
|---|---|---|---|
| Title "Note Garden" | 40 px | 56 px | 700 / 1.1 |
| Question prompt | 26 px | 32 px | 700 / 1.25 |
| Answer label | 24 px | 28 px | 700 |
| Note letters (A–G) | 36 px | 40 px | 700 |
| Body / hint / reveal | 20 px | 22 px | 500 / 1.45 |
| Small (Grown-ups panel) | 16 px | 16 px | 500 |

Sentence case, left-aligned body, max 40 characters per line in prompts, no all-caps and no italics for children's text.
Text must survive 200% zoom without overlap (1.4.4) and the 1.4.12 text-spacing overrides.

## 4. Layout

Use one column of fixed zones, so the prompt, stage and answers sit in the same place every time:
**Top bar** (← back · "Question 3 of 8" · 🔊 sound toggle) → **Prompt** → **Stage** (staff, pots or dots) →
**Answers** → **Helper row** (Hear it again · Help me) → **Garden strip** (flowers, decorative) → **Next** (after an
answer).

| Viewport | Rules |
|---|---|
| Phone portrait < 640 px | Full width with 16 px padding. Stage ≤ 42 vh. Answers in a 1-column (2–3 options) or 2-column (4 options) grid, each **≥ 72 px tall**, 12 px gaps. Helper row is two 56 px buttons. Keep the Next button in the thumb zone (sticky at the bottom, with `env(safe-area-inset-bottom)` padding) |
| Phone landscape (height < 500 px) | Two columns: stage on the left (55%), prompt + answers on the right. Hide the garden strip |
| Tablet 640–1023 px | Centred column, max-width 720 px. Answers in a row (2–3 per row), each ≥ 80 px tall |
| Desktop ≥ 1024 px | Centred card, max-width 960 px. Stage and answers side by side only for `find-note`/`hear-rhythm` cards. Otherwise stack as tablet |

**Targets:** every interactive element is **≥ 64×64 CSS px** (phones: 72 px tall), with ≥ 12 px between targets.
That exceeds WCAG 2.5.5 AAA (44 px). Answer cards for `find-note`/`hear-rhythm` are ≥ 120 px tall. Use **tap only**:
no drag, swipe, double-tap or long-press (2.5.1/2.5.7). The "Open all levels" control asks for a confirm dialog, not a
long-press.

## 5. Staff and notation (inline SVG, hand-authored)

- `viewBox` width 320; line spacing `s = 20`; 5 lines; bottom line E4 at `y0`. Pitch position `p` (E4=0, F4=1, G4=2,
  A4=3, B4=4, C5=5, D5=6, E5=7, F5=8, G5=9, D4=−1, C4=−2), so `y = y0 − p·s/2`.
- Note head: ellipse `rx 11.5, ry 8.5`, rotated −20°, filled ink. Stem 3 units wide, 3.5·s long. **Stem up** for
  p < 4 (on the right side), **down** for p ≥ 4 (on the left). C4 gets one ledger line 32 units wide.
- Treble clef: draw a simplified original SVG path, `aria-hidden`. Don't copy glyph outlines from fonts such as Bravura.
- Rhythm symbols are drawn the same way (filled or hollow heads, stems, beam 5 units thick for E2, a simplified
  zig-zag quarter rest). Beats are shown as **flower pots** under the bar, one per beat, and a half note spans 2 pots.
- Staff stroke 2 units, ink; minimum rendered staff width 280 px on phones.

## 6. Mascot — "Pip"

Pip is a seed sprout built from SVG primitives only. The body is a 64-unit circle (`--ng-mint`, 3-unit ink stroke).
Two leaf "ears" are ellipses in `--ng-leaf`, the eyes are two ink dots, and the smile is an arc. Expressions are made
by swapping paths: *happy* (curved eyes), *thinking* (one eyebrow, used for hints) and *cheer* (both leaves up). Pip is
**never sad or disappointed**, even after wrong answers, where the thinking face is used. Pip is decorative
(`aria-hidden`); any line Pip "says" is real text in a speech bubble.

## 7. Motion

| Event | Default | `prefers-reduced-motion: reduce` |
|---|---|---|
| Flower blooms (correct/finished) | scale 0.6→1 + petal rotate 12°, 400 ms `cubic-bezier(.2,.8,.2,1)` | 150 ms opacity fade, no scale |
| Correct ✓ ring | 200 ms ring grow | instant |
| Try again | button shakes 2 × 4 px, 240 ms total | no shake; ✕ appears instantly |
| Pip idle bob | 2 px, 3 s loop; **stops after 10 s** and pauses while the tab is hidden | none |
| Level-done stars | sequential pop, 150 ms apart | all appear at once |
| Screen change | 200 ms cross-fade | instant |

Rules: use only transform and opacity. No flashing (≤ 1 flash/s, well under 2.3.1), no parallax or auto-scrolling, and
nothing that moves for longer than 5 s without a pause (2.2.2). Respect the media query in CSS and in any JS timing.

## 8. Accessibility checklist (implementer must meet)

- One `<h1>` per screen; the prompt is the `<h2>`; landmarks `<main>` and `<nav>` (top bar).
- Answers are real `<button>`s with text names ("Up", "G", "2 beats"). Icons are `aria-hidden`. Notated options use
  `aria-label` describing the rhythm in words ("quarter, quarter, half").
- An `aria-live="polite"` region announces correct/try-again/reveal text. Move focus to **Next** after the answer and
  to the prompt heading on each new question.
- Visible focus: 3 px `--ng-focus` outline with 3 px offset, never hidden behind sticky bars (2.4.11).
- Fully keyboard operable with Tab/Shift-Tab, Enter and Space. No single-key shortcuts.
- Sound-dependent questions get a visual equivalent when sound is off (SPEC "Sound off").
- No time limits anywhere (2.2.1). Set `lang="en"` on the game root.

## 9. Audio design (Web Audio, synthesised only)

- **Start:** create one `AudioContext` lazily on the first user tap ("Let's go") and `resume()` it on later taps.
  Never autoplay before a gesture. If `AudioContext` is missing, show the "No audio support" copy and the visual mode.
- **Signal chain:** `voice → masterGain → DynamicsCompressor (limiter) → destination`.
  Limiter: threshold −12 dB, knee 0, ratio 20, attack 3 ms, release 100 ms.
- **Pitch voice ("garden bell"):** a `triangle` oscillator plus a `sine` an octave up at 0.15 gain, through a
  `lowpass` at 2.5 kHz (Q 0.7). It is soft and clear, with no harsh square or saw waves.
  ADSR: **A 12 ms · D 150 ms · S 0.55 · R 280 ms**. Peak voice gain 0.6 (before master). Schedule envelopes with
  `setTargetAtTime` or linear ramps; never jump gain values, to avoid clicks.
- **Beat click (count-in, L3):** a 1200 Hz sine, A 2 ms, exponential decay to silence in 60 ms, gain 0.25. Beat 1 gets
  1600 Hz.
- **Feedback sounds** (optional, ≤ 400 ms): correct = rising C5→E5→G5 at 90 ms each; try again = **one soft low G4**
  (no buzzer or descending "fail" motif). They play at 70% of voice level and are skipped if the item audio is playing.
- **Volume caps (hearing safety):** master gain **Medium 0.20 / Soft 0.10**, with a hard ceiling of **0.25** in code.
  The output peak must stay ≤ −6 dBFS after the limiter, so check with an `AnalyserNode` in a dev test. The default is
  Medium and there is no "loud" setting. No sustained tones: the longest single sound is the whole note at 80 bpm
  (3 s), and every other sound is under 1 s. A browser can't measure dB SPL (WHO H.870 is 75 dB for children), so the
  Grown-ups panel says: "Keep headphone volume low."
- **Mute:** the 🔊 toggle sets `masterGain` to 0 with a 30 ms ramp, stops queued sounds (track the scheduled source
  nodes and `stop()` them), and persists `muted` in localStorage. While muted, the "Hear it again" button stays and
  shows the visual equivalent. Also stop all sound on `visibilitychange` → hidden and when the route unmounts
  (`audioContext.close()`).
- **Timing:** schedule with `audioContext.currentTime + 0.05`, never `setTimeout`. Lock the answer buttons only while a
  prompt sound plays the *first* time (≤ 3.5 s), so the child hears the question before answering. Replays never lock.

## 10. Done-definition for design

Verify the palette pairs above in the built UI with axe/Lighthouse. Check a 320 px-wide phone, a 768 px tablet and a
1280 px desktop. Check reduced motion in OS settings, keyboard-only play of every level, and sound-off play of every
level.
