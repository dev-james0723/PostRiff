# Note Garden — Game & Pedagogy Spec (v1)

Route: **`/play/note-garden`** (public, no sign-in). Display title: **Note Garden** · tagline *Grow flowers with music*.
Audience: ages 6–10, mostly early readers. Every question is **untimed**. Visual and audio rules are in `DESIGN.md`;
sources are in `RESEARCH.md`.

## 0. Core loop and rules (all levels)

`Title → Garden map → Level intro ("Learn" card) → 6–8 questions → Level done (stars) → map`.
The teaching loop follows Kodály: **listen/see first → compare → answer → reveal the deciding feature**.

- **Questions per run:** L1 6 · L2 8 · L3 6 · L4 6. Draw without replacement from the level's banks, in the slot order
  below. Shuffle answer order, but never put the correct answer in the same position 3 times in a row.
- **Wrong answer #1:** the chosen button greys out with ✕ and the label "Tried" and becomes disabled. The Try-again copy
  plays and focus returns to the first enabled option. Once only one option is left, **reveal** at once.
- **Wrong answer #2 (or one option left):** reveal. The correct option gets a ✓ and a green ring, the *reveal* line for
  that item shows, and the note or rhythm plays again. The child taps **Next**. Nobody gets stuck and nothing is lost.
- **Correct:** a ✓ and the *correct* line (rotate through the praise list, no repeats back to back). The item's sound
  plays, a flower blooms in the garden strip, and a **Next** button appears. No auto-advance, so the child controls the
  pace.
- **Hint** (💡 "Help me", always available): one hint per question, shown inline. **Hints never reduce stars**, because
  asking for help is a good habit.
- **Replay** (🔊 "Hear it again"): on every question with sound, unlimited. It never affects scoring.
- **Garden strip:** one flower per *finished* question, right or wrong. Flowers never wilt, so there is no loss state.
- **Stars per run:** `f` = questions correct on the **first try**, `n` = question count.
  `3★ if f ≥ n−1` · `2★ if f ≥ ceil(n/2)` · else `1★`. Finishing always earns at least 1★.
  (n=6: 3★ ≥5, 2★ ≥3. n=8: 3★ ≥7, 2★ ≥4.) Keep the **best** stars per level.
- **Unlocking:** L1 starts open. Finishing level *k* with any stars unlocks *k+1*. The Grown-ups panel has
  "Open all levels" for teachers. Locked levels show a 🔒 and the text "Finish Level k to open".
- **Leaving mid-level:** the ← button asks "Leave this level? Your flowers will wait for you next time." with options
  *Keep playing* / *Leave*. Mid-run state is **not** saved; the level restarts next time.

### Progress storage (localStorage only)
Key `rafii.noteGarden.v1`. Value:
`{"v":1,"best":{"1":0,"2":0,"3":0,"4":0},"done":{"1":false,...},"allOpen":false,"muted":false,"volume":"medium"}`
Store only this: no name, ID, timestamp or answer history. Read it inside try/catch; corrupt or missing data means
defaults. If storage is unavailable (private mode), play still works and progress is not remembered. Grown-ups
"Reset progress" deletes the key.

### Note names and pitch
Scientific pitch names (C4 = middle C), equal temperament, A4 = 440 Hz: `f = 440·2^((midi−69)/12)`.
Bank range **C4–G5**: C4 261.63 · D4 293.66 · E4 329.63 · F4 349.23 · G4 392.00 · A4 440.00 · B4 493.88 · C5 523.25 ·
D5 587.33 · E5 659.26 · F5 698.46 · G5 783.99. Letter names A–G, which are the same in UK and US use.

---

## L1 — High or Low? *(ears only)*
**Goal:** tell same from different, then hear whether the melody goes **up** (higher) or **down** (lower).

**Learn card:** Pip stands by a tall sunflower and a tiny mushroom. "High sounds are up like birds. Low sounds are down
like frogs. Tap them!" Tapping the sunflower plays G5 and the mushroom plays C4. **Let's play** continues.

| Slot | Format | Bank (draw 1 per slot, no repeat) |
|---|---|---|
| Q1–Q2 | `same-different`: two notes, 600 ms each, 400 ms apart. Options **Same** (= =) / **Different** (≠) | Same: C4–C4, G4–G4, E5–E5 · Different: C4–C5, G4–C4, E5–G4. Q1 draws from Same and Q2 from Different, shown in random order |
| Q3 | `up-down`, **big jump** (6th–8ve). Options **Up** (↑ bird) / **Down** (↓ frog) | C4→C5, C5→C4, G4→G5, G5→G4, E4→C5, A4→C4 |
| Q4–Q5 | `up-down`, **medium** (5th) | C4→G4, G4→C4, F4→C5, D5→G4, G4→D5, C5→F4 |
| Q6 | `up-down`, **small** (so–mi, 3rd) | G4→E4, E4→G4, D5→B4, B4→D5 |

- Prompt: "Listen. Same or different?" / "Listen. Did the music go up or down?"
- Hint: "Let's listen slowly." Replays at 900 ms per note with an 800 ms gap.
- Reveal: "They were the same note." / "They were different notes." / "It went **up**, higher like a bird." / "It went
  **down**, lower like a frog."
- **Sound off:** show two dots at the notes' relative heights, labelled "Sound is off. Here is a picture of the sound."

## L2 — Note Names *(treble staff, C4–G5)*
**Goal:** name notes on the treble staff using landmarks (Middle C, the G line) and the line/space patterns.

**Learn card:** a staff with the treble clef. "The music staff has 5 lines and 4 spaces. Notes sit **on** a line or
**in** a space. Tap a note to hear its name!" Show C4, E4, G4, B4, D5 and F5 as tappable notes. Each tap plays its pitch
and shows the letter.

| Slot | Format | Bank |
|---|---|---|
| Q1–Q3 | `name-note`: one note on the staff. "What is this note?" Three letter buttons | **Low garden**: C4 D4 E4 F4 G4 |
| Q4 | `find-note`: "Tap the **G**!" Three cards, each a mini-staff with one note | Target from low garden; distractors are 2 other low-garden notes with **different letters** |
| Q5–Q7 | `name-note` | **High garden**: A4 B4 C5 D5 E5 F5 G5, plus a revisit of E4 or G4 |
| Q8 | `find-note` | Target from high garden; distractors are other C4–G5 notes with different letters |

- **Distractors for `name-note`:** the letter one step away (above or below, chosen at random) plus the letter three
  steps away. All three letters must differ. Example: correct G gives F or A, plus D or C.
- After answering, play the note and show its letter under it.
- **Hints by note:**
  - Line notes E4, G4, B4, D5, F5: "Line notes from the bottom: **E G B D F**. Every Green Bug Digs Fast!"
  - Space notes F4, A4, C5, E5: "Space notes from the bottom spell **F A C E**."
  - C4: "This note has its own little line below the staff. It's **Middle C**!"
  - D4: "This note hangs just under the bottom line. It's one step up from Middle C."
  - G5: "This note sits on top of the staff, one step above the top line (F)."
- Reveal: "This is **{L}**. It sits {on line n / in space n / on its own little line / under the staff / on top of the
  staff}." Count lines and spaces from the bottom.
- Screen-reader label for the staff: "A note {on the second line from the bottom}". Use the position, never the letter.

## L3 — Long and Short *(note values and beats, 4/4, 80 bpm)*
**Goal:** know how many beats each note lasts, fill a 4-beat bar, and match a rhythm you hear to its notation.

**Learn card:** a row of flower pots, one per beat (4 pots). "Music has a steady **beat**, like walking. Some notes last
1 beat, some last longer!" There are 5 tappable symbols, each with a caption, and each plays its rhythm over a soft
click:
quarter note *(crotchet)* = **1 beat** "ta" · two eighth notes *(quavers)* = **1 beat together** "ti-ti" ·
half note *(minim)* = **2 beats** "ta-a" · whole note *(semibreve)* = **4 beats** "ta-a-a-a" ·
quarter rest *(crotchet rest)* = **1 quiet beat** "shh". Show both names on the learn card only. Questions use beats.

| Slot | Format | Bank |
|---|---|---|
| Q1 | `count-beats`: "How many beats?" Options **1 beat / 2 beats / 4 beats** | quarter(1), half(2), whole(4) |
| Q2 | `count-beats` | eighth pair(1), quarter rest(1), half(2) |
| Q3–Q4 | `fill-bar`: a bar of 4 pots with one empty gap. "Which note fills the gap?" Options: quarter / half / whole (symbol plus beat caption) | `[H Q _]→Q` · `[Q Q _]→H` · `[_]→W` · `[Q _ Q]→H` · `[H _]→H` · `[E2 Q _]→H` · `[H E2 _]→Q` · `[R Q _]→H` |
| Q5–Q6 | `hear-rhythm`: 4-beat count-in clicks, then the rhythm plays. "Which rhythm did you hear?" Three notated options | Triples (target listed first): `P1,P2,P8` · `P2,P1,P3` · `P4,P5,P1` · `P5,P4,P3` · `P6,P1,P8` · `P8,P1,P2` · `P9,P1,P2` |

Tokens: Q quarter, H half, W whole, E2 two beamed eighths, R quarter rest.
Patterns: **P1** Q Q Q Q · **P2** H H · **P3** W · **P4** Q Q H · **P5** H Q Q · **P6** E2 Q E2 Q · **P8** E2 E2 Q Q · **P9** Q R Q R.
(P7 was dropped as too close to P6.) Rhythm notes play on C5; each sounds for 85% of its value so repeated notes are
distinct.

- Hints: count-beats "Clap and count: 1, 2, 3, 4. How many claps does the note last?" (the note plays while beat dots
  light up) · fill-bar "Every bar has **4** beats. Count the beats you already have." (show a running count under each
  pot) · hear-rhythm "Listen again, slowly." (replay at 60 bpm).
- Reveal: "A {name} lasts **{n}** beat(s)." / "{a} + {b} = 3 beats. We need **1** more, so it's a quarter note." / "You
  heard ta ta ti-ti ta…" (spoken-syllable text of the target).

## L4 — Step or Skip? *(listening + staff)*
**Goal:** a **step** goes to the next-door note (a 2nd, line to space). A **skip** jumps over at least one note (a 3rd
to a 5th, line to line or space to space). *Changed from the default "one listening concept" slot: steps/skips was
chosen over same/different, which moved to L1. See RESEARCH §2.*

**Learn card:** stepping stones on a staff. Pip hops: "A **step** goes to the next stone. A **skip** jumps over a
stone!" There are two buttons: *Show a step* (C4→D4 plays and Pip steps) and *Show a skip* (C4→E4 plays and Pip leaps).

| Slot | Format | Bank |
|---|---|---|
| Q1–Q3 | `step-skip` **seen + heard**: both notes on the staff, played in order (600 ms each). Options **Step** (👣) / **Skip** (🐸 leap) | Steps: C4–D4, E4–F4, G4–A4, B4–C5, D5–C5, F5–E5, A4–G4, G5–F5 · Skips: C4–E4, E4–G4, G4–B4, F4–A4, D5–B4, E5–C5, C4–G4, A4–E5, G5–C5. Each run includes at least one step and one skip |
| Q4 | `step-skip` **heard only**: the staff shows two "?" stones, then reveals the notes after the answer | Step, or a **5th** skip (C4–G4, A4–E5, G5–C5) |
| Q5–Q6 | heard only | any step, or a 3rd skip |

- Hint (seen): "Look! Next-door notes are steps. Line to line or space to space is a skip." · Hint (heard): "Let's
  listen slowly." Replay 900 ms per note, with dots at relative height.
- Reveal: "That was a **step**, to the next-door note." / "That was a **skip**. It jumped over **{n}** note(s)."

---

## Copy deck (every screen; plain English, ≤ 12 words per line)

| Screen | Text |
|---|---|
| Title | **Note Garden** · *Grow flowers with music* · button **Play** · small link **Grown-ups** |
| Sound start (first tap) | Pip: "Hi! I'm Pip. Let's make music!" · button **Let's go** |
| Garden map | "Pick a garden bed!" · L1 **High or Low?** · L2 **Note Names** · L3 **Long and Short** · L4 **Step or Skip?** · locked: "Finish Level {k} to open" · best stars shown as ★★☆ with text "2 of 3 stars" |
| Learn card footer | **Let's play** · **Back** |
| Question header | "Question {i} of {n}" · buttons **Hear it again** · **Help me** · **Next** |
| Correct (rotate) | "Yes! Great listening!" · "You got it!" · "That's right! Nice looking!" · "Well done. You counted carefully!" · "Brilliant ear!" · "Correct! Your garden is growing!" |
| Try again (rotate) | "Not quite. Try again!" · "So close! Have another go." · "Hmm, listen once more." |
| Reveal lead-in | "Let's see together." + item reveal line + **Next** |
| Level done | 3★ "Amazing! Your garden is full of flowers!" · 2★ "Great work! Your flowers are blooming!" · 1★ "You finished! Every try helps you grow." · buttons **Play again** · **Next level** · **Garden map** |
| All four done | "You grew the whole Note Garden! 🌻" · **Play any level again** |
| Leave dialog | "Leave this level? Your flowers will wait for you next time." · **Keep playing** · **Leave** |
| Sound off notice | "Sound is off. Here is a picture of the sound." |
| No audio support | "Sound can't play on this device. You can still play with pictures." |
| Grown-ups panel | As shipped (decision D3; the original "Nothing is sent anywhere" over-claimed, because pages are still served by a host): "For grown-ups" · "Note Garden has no accounts. It never asks for names or personal details. Progress is saved only on this device. There are no ads." · toggle **Sound** · **Volume: Soft / Medium** · **Open all levels** · **Reset progress** (confirm: "Delete stars on this device?" **Delete** / **Cancel**) · **Back to Rafii** |

Never use: "Wrong", "Fail", "Game over", timers, countdowns, lives, streaks, "Don't stop now", or ads.

---

## Implementation contract (for the engine)

- Question types: `same-different`, `up-down`, `name-note`, `find-note`, `count-beats`, `fill-bar`, `hear-rhythm`,
  `step-skip` (`seen: boolean`). Level config = ordered slots `{type, bankId, count}`. Banks are static TS data.
- **Compatibility with the default curriculum:** levels 1–4, their order and their themes are unchanged. Two changes:
  L1 gains 2 `same-different` warm-ups, and L4 uses steps/skips. If the engine already has a same/different L4, its
  items move into L1 slots 1–2.
- No network requests, no `fetch`, no cookies, no analytics events, and no third-party scripts from game code.

## Assumptions

1. **English only, v1.** Letter names (A–G) and US note-value names in questions, with UK names on the L3 learn card.
   Solfège is not shown except the rhythm syllables ta/ti-ti.
2. **Treble clef only.** Bass clef and ledger lines beyond C4 are out of scope.
3. **No speech audio.** Text is short; kids who can't read yet rely on icons, sound and Pip's pictures. Recorded or TTS
   narration is a possible v2 (no paid APIs).
4. **Hints are free** and do not lower stars (no punishing failure). The trade-off is that stars measure first tries
   only.
5. `/play/*` is outside the `/app` sign-in gate (`web/src/proxy.ts` only gates `/app` and `/founder`). The proxy still
   calls `updateSession` for every path. That only refreshes an *existing* Rafii session cookie; the game itself sets
   none.
6. **Open decision for James:** the root layout mounts Vercel Web Analytics when `NEXT_PUBLIC_VERCEL_ANALYTICS=1`. It
   is cookieless, but it records page views. The recommended fix is to exclude `/play/*` (for example via `beforeSend`)
   so the children's route collects nothing. The integration owner should not change it without approval.
7. The WHO 75 dB guidance can't be measured from a browser. The digital gain caps in DESIGN are the safeguard, plus the
   grown-up volume setting.
8. Pedagogy order is backed by secondary sources (see RESEARCH). No user testing with children has been done.
   **NOT_TESTED.**
