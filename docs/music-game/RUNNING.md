# Note Garden — running, testing and known limits

Route: **`/play/note-garden`** (public, no sign-in, client-only). Spec: `SPEC.md`, `DESIGN.md`, `RESEARCH.md` in this
folder. Task `ao-rafii-20261031-bf90f0`.

## Where the code lives

| Path | What |
|---|---|
| `web/src/lib/music-game/curriculum.ts` | Levels, SPEC banks, seeded run generation, sound schedules, round scoring. Pure, no imports |
| `web/src/lib/music-game/progress.ts` | `localStorage` key `rafii.noteGarden.v1` (versioned, sanitised, guarded, reset) |
| `web/src/lib/music-game/synth.ts` | Web Audio "garden bell" voice, clicks, limiter, volume cap, mute |
| `web/src/components/music-game/*` | Game UI (screens, SVG drawings, scoped CSS module) |
| `web/src/app/play/note-garden/{page,layout}.tsx` | The route |
| `web/tests/music-game*.test.mjs` | Unit tests (`node --test`) |
| `web/tests/music-game-browser.cjs` | Playwright browser journey |

No new dependencies. No server routes, API calls, cookies, analytics calls, audio files or images.

## Run it locally

All commands run from `web/` with Node 24 (`.nvmrc`). On the M3 Max, Homebrew `node@24` is keg-only:

```sh
export PATH=/opt/homebrew/opt/node@24/bin:$PATH
cd web
npm ci                                   # repo lockfile, no new packages
node_modules/.bin/next dev -p 3107 -H 127.0.0.1      # dev, then open http://127.0.0.1:3107/play/note-garden
# or production mode:
node_modules/.bin/next build
node_modules/.bin/next start -p 3117 -H 127.0.0.1    # http://127.0.0.1:3117/play/note-garden
```

No `.env` is needed: the route does not touch Supabase or any provider. Stop the server when done. Don't run
`next build` in the same `web/` folder while a dev server is running there.

## Test it

```sh
# Unit tests for the game (engine, storage, synth, source guards)
node --test tests/music-game*.test.mjs

# The repo's whole node suite (includes the game tests); run directly, not through the :jcb script
node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs

# Lint and types
node_modules/.bin/oxlint src
node_modules/.bin/tsc --noEmit

# Browser journey: start a server first (see above), then
RAFII_NOTE_GARDEN_URL=http://127.0.0.1:3117 node tests/music-game-browser.cjs
# optional screenshots
RAFII_NOTE_GARDEN_URL=http://127.0.0.1:3117 NOTE_GARDEN_SHOTS=/tmp/note-garden-shots node tests/music-game-browser.cjs
```

**Known baseline failure (not caused by the game).** On a machine without the Python package `psycopg`, the whole-suite
command ends with one failure: `tests/visual-analysis.test.cjs` → `ModuleNotFoundError: No module named 'psycopg'`. The
repo's `:jcb` script normally installs Python first. On 2026-10-31 the same command on `consumer-saas` 5670ce3c, in a
temporary worktree that was removed afterwards, gave exit 1 with 935/936 passing and the same test failing with the
same error. This branch gives 981/982: the extra 46 are the game's own tests, and all of them pass.

The browser journey needs Playwright's Chromium for the pinned `playwright` version. If it is missing:
`node_modules/.bin/playwright install chromium`. The journey covers these checks:
- level 1 played with the keyboard only
- levels 2–3 with the mouse and level 4 by touch, on a phone viewport
- mute and reset, both persisted
- Help me keeps keyboard focus, the hint is announced in a status region, and on a phone it scrolls into view
- while the first sound plays, answers keep their look: `aria-busy` plus a "Listen…" cue, and taps are ignored
- Next is described by the feedback text
- loudness after the limiter stays ≤ −6 dBFS, even with mashed replays, an answer and Next
- one sound at a time: a replay mid-sound and leaving mid-sound stop every earlier oscillator (checked on the
  audio clock)
- AudioContext created only after a gesture
- sound-off pictures
- reduced motion
- ≥ 48 px targets
- axe-core with 0 serious/critical violations on 9 screens
- 0 console errors
- 0 requests off the local origin

## Deviations from SPEC/DESIGN (decided by the integration owner)

| # | SPEC/DESIGN says | Built | Why |
|---|---|---|---|
| 1 | Correct: show the praise line | Praise line **plus** the item's reveal sentence | Teaches why the answer is right, not only that it is |
| 2 | Reset deletes the key | Deletes the key, then writes back **only** a non-default sound choice (muted / soft) | A reset should never surprise a child with sound; stars, done and open-all are gone |
| 3 | count-beats hint: beat dots light up with the sound | Hint text + the note replayed over beat clicks; no animated dots | Avoids a JS/CSS timing loop synced to audio; clicks carry the count |
| 4 | hear-rhythm hint replays at 60 bpm | Same, but a whole note is capped at 3 s (DESIGN §9 "longest sound 3 s") | SPEC 60 bpm × 85% would be 3.4 s; DESIGN cap wins |
| 5 | fill-bar has no prompt sound | Prompt plays the bar with the gap silent over clicks; after answering, the full bar plays | Gives "Hear it again" something useful; ears check the count |
| 6 | name-note plays the note after answering | Also plays it when the question appears | Pairs pitch with position, as the learn card does; gives no letter away |
| 7 | Desktop: stage beside answers for find-note / hear-rhythm | One stacked column at all widths | Simpler and the same order for every question (DESIGN "fixed zones") |
| 8 | Pip bob stops after 10 s, pauses when hidden | CSS bob runs 3 × 3 s then stops; none with reduced motion | Same effect without JS |
| 9 | Title copy only | Decorative row of 12 flowers on the title, one per star earned | Makes the "grow flowers" promise visible; `aria-hidden`, the map states stars in words |
| 10 | Analyser-node check that peaks stay ≤ −6 dBFS | Built into the browser journey: an AnalyserNode after the limiter, at Medium | Measured −10.4 dBFS for mashed replays + answer + Next, and −10.0 dBFS for the L3 learn sounds (Chromium headless). The review measured −5 dBFS at 0b0348d4, before one-sound-at-a-time |

**One sound at a time.** Every new sound replaces the previous one: question, replay, hint, answer feedback, a learn-card
tap, Next, leaving, any screen change, mute and unmount all fade out what is playing (25 ms) and stop its oscillators.
Feedback cues play in the same schedule as the answer sound, so they cannot stack either. Sound requests are tokened
(`synth.request()`). If the AudioContext is still resuming when something newer happens (a sound, stop, mute,
navigation or unmount), the older request is dropped and never plays. Resuming is single-flight: there is one shared `resume()` per context. A failure is handled once and
only for the current context. After a failure, the next sound builds a fresh context, with no permanent "failed"
state. An exhaustive orderings test (2,775 sequences) checks these rules.

Answer lock: answers wait while a question's first sound plays only when that sound is ≤ 3.5 s (DESIGN §9). Rhythm
questions (count-in + rhythm ≈ 6 s) are never locked. Answering one of those cuts the rhythm off and plays the answer
feedback. The lock is decided along with the question, so answers never flash enabled and then disabled.

## UX/accessibility review follow-ups (rafii-5, reviewed 0b0348d4)

Fixed: M1 Help me focus · M2 hint announced and scrolled into view · M3 overlap loudness (one sound at a time, measured
above) · M4 Grown-ups copy (decision D3: only what the game guarantees) · M5 30ch lines, one sentence per line on learn
cards · M6 L2 learn staves full-width on phones · M7 listening cue instead of greyed answers · m1 picture icons for
Same/Different · m2 🦘 for Skip, so 🐸 means only "low" · m3 praise per skill · m4 "Sound on/off" text · m5 sticky Next
in landscape, focus without scrolling · m6 Next described by the feedback · m7 Grown-ups link moved off the Play row
to a footer · m8 larger ✓ with a Yes/Answer chip.

Not changed, by decision:
- **Read-aloud (M5 v2 idea):** not added. Some browsers send `speechSynthesis` text to cloud voices, so it is deferred
  to v2.
- **Grown-up gate (m7):** only the link was moved. A reading or maths gate adds friction and protects no data: reset and
  open-all already ask to confirm.
- **Site notifications region (m9):** the root layout's Sonner toaster appears in the accessibility tree. The root layout
  is out of scope and was not edited.
- **Announcement timing (m6):** Next is described by the feedback, but a real screen reader was not used
  (**NOT_TESTED** with VoiceOver, NVDA or TalkBack).

## No analytics or telemetry on /play (decision D1 = exclude, done)

Nothing analytics or telemetry is sent from `/play` or anything below it. Every other route keeps exactly the analytics
it had. One helper, `web/src/lib/play-path.ts` (`isPlayPath`), decides what counts as `/play`. It matches `/play`,
`/play/` and `/play/note-garden`, but not `/player`, `/playground` or `/app/play`.

| Surface | What happens on /play | Where |
|---|---|---|
| Vercel Web Analytics (when `NEXT_PUBLIC_VERCEL_ANALYTICS=1`) | `<Analytics>` is not rendered, so a direct visit never loads the script. `beforeSend` (the documented API in `@vercel/analytics` 1.6.1) drops `/play` page views and events after a client-side visit | `web/src/components/layout/site-analytics.tsx`, `web/src/app/layout.tsx` |
| Sentry browser SDK (when a DSN is set) | Booting on `/play` never loads or initialises the SDK. After a client-side visit, a transport gate drops every envelope (events, transactions, sessions) while on `/play` or heading there. `beforeSend`/`beforeSendTransaction` also drop `/play` events, and router transitions into `/play` are not recorded | `web/src/instrumentation-client.ts` |
| Sentry server SDK | `beforeSend`/`beforeSendTransaction` drop events whose request URL or transaction is `/play`, and `onRequestError` skips `/play` request paths | `web/src/instrumentation.ts` |
| Speed Insights | Not installed; not added | — |

Sentry starts a new session from its `pushState` hook before the address bar changes. The client gate therefore also
uses the destination that Next passes to `onRouterTransitionStart`. Leaving `/play` resets it.

**Check it** (production build with telemetry switched on and a dummy local DSN; the test aborts every off-origin
request, so nothing reaches a real collector):

```sh
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=https://public@127.0.0.1/1 node_modules/.bin/next build
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=https://public@127.0.0.1/1 node_modules/.bin/next start -p 3117 -H 127.0.0.1
RAFII_TELEMETRY_URL=http://127.0.0.1:3117 node tests/play-telemetry-browser.cjs
node --test tests/play-telemetry.test.mjs        # unit tests for the helper
```

The browser test checks five things:
1. A direct `/play/note-garden` load has no analytics script, no Sentry, 0 telemetry requests and 0 off-origin requests.
2. `/pricing` still requests `/_vercel/insights/script.js`, initialises Sentry and sends an error, as a positive control.
3. A client-side navigation from `/pricing` into `/play` sends nothing.
4. Navigating back to `/pricing` resumes telemetry.
5. Rebuild without those variables before the normal game journey, or run the journey against this build: it passed
   with 0 off-origin requests on 2026-10-31.

Not observed end to end: a server-side error during a `/play` request. The server path is covered by the helper's unit
tests and the hook code above.

## Release notes (not done here)

- **D3, Grown-ups copy:** the panel claims only what the game guarantees. Since D1 is now done, the site may also say
  that `/play` sends no analytics.
- `src/proxy.ts` still runs `updateSession` for `/play/*`. This only refreshes an existing Rafii session cookie. The game
  sets no cookies.
- The route renders dynamically (`ƒ`) because the root layout reads the theme cookie.
- No deploy was made. Hosted previews are off by project policy (`CLAUDE.md`).

## Known limitations

- English only. Treble clef only (C4–G5). No spoken narration; non-readers rely on icons, sound and pictures.
- Icons are system emoji, so their look depends on the device's emoji font. Staff, rhythms, Pip, flowers and stars are
  SVG.
- Sound was exercised in headless Chromium only, so the timbre and loudness have not been judged by ear. Safari/WebKit
  and real phones have not been run (**NOT_TESTED**).
- Progress is per browser and device. Private mode or blocked storage means nothing is remembered, but play still works.
- Pedagogy is backed by secondary sources (RESEARCH.md). There has been **no testing with children**.
- Phone-landscape two-column layout exists in CSS but was not screenshotted.
