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

The browser journey needs Playwright's Chromium for the pinned `playwright` version. If it is missing:
`node_modules/.bin/playwright install chromium`. The journey covers these checks:
- level 1 played with the keyboard only
- levels 2–3 with the mouse and level 4 by touch, on a phone viewport
- mute and reset, both persisted
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
| 10 | Analyser-node check that peaks stay ≤ −6 dBFS | Not built. Gain caps and limiter settings are unit-tested | **NOT_TESTED**. The real output level needs a listening/analyser check |

Answer lock: answers wait while a question's first sound plays only when that sound is ≤ 3.5 s (DESIGN §9). Rhythm
questions (count-in + rhythm ≈ 6 s) are never locked.

## Release prerequisites (not done here)

- **D1, analytics:** the root layout mounts Vercel Web Analytics when `NEXT_PUBLIC_VERCEL_ANALYTICS=1`. It records page
  views for every route, including `/play/note-garden`. Per the orchestrator's decision D1, the root layout was **not**
  edited. Before a public release, decide whether to exclude `/play/*` (for example with `beforeSend`).
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
