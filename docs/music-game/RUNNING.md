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
it had. One helper, `web/src/lib/play-path.ts` (`isPlayPath`), decides what counts as `/play`:
`pathname === '/play' || pathname.startsWith('/play/')`. The match is case-sensitive and nothing is decoded.

Observed with `next start` on 2026-10-31: only the literal `/play/note-garden` renders the game.
- `/PLAY/note-garden`, `/Play/note-garden` and `/%70lay/note-garden` are ordinary 404 pages and keep the site's
  analytics.
- `/play/` and `/play/note-garden/` redirect (308) to the slash-less path.
- `/play/%6Eote-garden` is a 404 inside the play area, so it sends nothing either.

| Surface | What happens on /play | Where |
|---|---|---|
| Vercel Web Analytics (when `NEXT_PUBLIC_VERCEL_ANALYTICS=1`) | `<Analytics>` is not rendered, so a direct visit never loads the script. `beforeSend` (the documented API in `@vercel/analytics` 1.6.1) drops `/play` page views and events after a client-side visit | `web/src/components/layout/site-analytics.tsx`, `web/src/app/layout.tsx` |
| Sentry browser SDK (when a DSN is set) | Booting on `/play` never loads or initialises the SDK. After a client-side visit, a transport gate drops every envelope (event, transaction, session, client_report and any other type) while on `/play` or heading there. `beforeSend`/`beforeSendTransaction` drop `/play` events. Router transitions into `/play` are not recorded. The tally of events dropped on `/play` is also subtracted from the next client_report sent elsewhere | `web/src/lib/sentry-client.ts`, `web/src/instrumentation-client.ts`, `web/src/components/layout/sentry-route-start.tsx` |
| Sentry server SDK | `beforeSend`/`beforeSendTransaction` drop events whose request URL or transaction is `/play`, and `onRequestError` skips `/play` request paths. While a `/play` request is handled, no outcome is recorded, so there's no tally in a later client_report (no dropped error, no sampled-out transaction). The request is also not counted in the request-session aggregates | `web/src/instrumentation.ts`, test `web/tests/play-sentry-server.test.cjs` |
| Files the /play page loads (D12) | `/play` references no site manifest and no server-hosted icons: a `/play` segment layout sets `manifest: null` and an inline SVG tab icon. On the server, asset and metadata requests (`/_next/static`, `/_next/image`, manifest, favicon, icons) whose Referer is `/play` count as `/play` traffic, so they are not counted as request sessions or outcomes. Pages and RSC requests are never matched, so leaving `/play` still counts as a visit to the next page | `web/src/app/play/layout.tsx`, `web/src/lib/play-path.ts` (`isPlayAssetRequest`), `web/src/instrumentation.ts` |
| Sign-in session (Supabase) | The proxy returns before the session refresh: no `getUser()` call, and no auth cookie set or refreshed, even for a signed-in parent on the same device. The legacy-host redirect still runs first | `web/src/proxy.ts`, test `web/tests/play-proxy.test.cjs` |
| Speed Insights | Not installed; not added | — |

Precise behaviour around `/play` (browser):
- **Entering `/play` by client-side navigation:** Sentry starts a new session from its `pushState` hook before the
  address bar changes. The gate therefore also uses the destination that Next passes to `onRouterTransitionStart`, and
  that session envelope is dropped.
- **Leaving `/play` after a visit that started elsewhere** (privacy N2): the one session envelope Sentry emits at the
  moment of leaving is dropped by design, because the address bar still shows `/play`. From then on the page reports
  as usual:
  - the Analytics component mounts again and records that page's view
  - Sentry sends errors
  - client_reports flush on hide, minus the tally of events dropped on `/play`

  That page therefore has no session-start envelope for this navigation.
- **Leaving `/play` after a visit that began on `/play`** (privacy N1, D11): Sentry was never loaded.
  `SentryRouteStart` (in the root layout, always mounted) calls `ensureSentryForPath` on every route React commits.
  On the first non-play commit, the SDK is loaded and initialised with the normal options, exactly as a direct visit
  to that page would. There is no timer or deadline. After the chunk loads, the current location is checked again:
  if the child has gone back to `/play`, nothing initialises until the next non-play commit. There is one import and
  at most one init (`src/lib/sentry-starter.ts`, tested with a deferred loader in `tests/sentry-starter.test.mjs`).
  Vercel Analytics records one page view, for that page only.
- **Not observed end to end:** a server-side error inside a real `/play` request under `next start`. The server path
  is covered by `tests/play-sentry-server.test.cjs`, which uses the installed SDK with an in-memory transport.

**Check it** (production build with telemetry switched on and a dummy local DSN; the test aborts every off-origin
request, so nothing reaches a real collector):

```sh
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=https://public@127.0.0.1/1 node_modules/.bin/next build
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=https://public@127.0.0.1/1 node_modules/.bin/next start -p 3117 -H 127.0.0.1
RAFII_TELEMETRY_URL=http://127.0.0.1:3117 node tests/play-telemetry-browser.cjs
node --test tests/play-telemetry.test.mjs tests/play-proxy.test.cjs tests/play-sentry-server.test.cjs tests/sentry-starter.test.mjs
```

The browser test checks:
1. **Direct `/play/note-garden` load:** no analytics script, no Sentry, 0 telemetry requests and 0 off-origin requests.
2. **`/pricing` (positive control):** requests `/_vercel/insights/script.js`, initialises Sentry and sends an error.
3. **Client-side navigation `/pricing` → `/play`:** while playing questions, navigating within `/play` and hiding the
   page (`visibilitychange` and `pagehide`), there are 0 `/monitoring`, 0 `/_vercel/*` and 0 off-origin requests, and
   no `/play` page view is queued for Vercel Analytics.
4. **Back to `/pricing`:** a `/pricing` page view is queued, Sentry sends again, and the client_report flushed on hide
   contains no `/play` tally.
5. **A visit that begins on `/play`, then navigates client-side to `/pricing` (and, separately, to `/`):** Sentry
   initialises and the analytics script loads there, with page views only for that page. An error is sent, and no
   telemetry request leaves while the page shows `/play`.

**Server telemetry from a whole `/play` visit (D12)** needs a local Sentry sink, because the server only flushes its
counts every 60 s:

```sh
SINK=http://public@127.0.0.1:3127/1
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=$SINK SENTRY_RELEASE=local node_modules/.bin/next build
NEXT_PUBLIC_VERCEL_ANALYTICS=1 NEXT_PUBLIC_SENTRY_DSN=$SINK SENTRY_RELEASE=local node_modules/.bin/next start -p 3117 -H 127.0.0.1
# fresh server, touch only /play first (the readiness check may curl /play/note-garden)
RAFII_TELEMETRY_URL=http://127.0.0.1:3117 SINK_PORT=3127 node tests/play-server-telemetry-sink.cjs   # ~2.5 min
```

Requests a headless `/play/note-garden` visit makes to the server (2026-10-31): the page itself plus 24 files under
`/_next/static` (JS, CSS, the preloaded font). Nothing else. Before D12, those 24 files were counted as 24 request
sessions plus sampled-out transactions. The page also referenced `/manifest.webmanifest`, `/icon` and `/apple-icon`.
After D12, the server sends nothing for that visit within the 70 s window, while a home visit still produces its 42
sessions and client_report.

Limits:
- Next always adds the root `app/favicon.ico` link on every page, including `/play`. A real browser's `/favicon.ico`
  request is excluded when it carries a `/play` Referer, and counted (counts only, no URL) when it carries none.
  Headless Chromium never requests favicons, so this is **NOT_TESTED**.
- Any request without a Referer cannot be attributed to `/play`.
- `og:image`/`twitter:image` point at absolute `rafii.io` URLs that browsers do not fetch. Only link-preview crawlers
  do.

Rebuild without those two variables before the normal game journey, or run the journey against this build. Both
passed with 0 off-origin requests on 2026-10-31.

## Release notes (not done here)

- **Privacy policy (privacy F4, decision D9):** the site policy's section 11 says Rafii is not directed at anyone under 18,
  which contradicts this game. Proposed wording and open questions for counsel are in
  [`PRIVACY-NOTICE-DRAFT.md`](PRIVACY-NOTICE-DRAFT.md). The policy page itself was not edited.
- **Grown-ups Privacy link (F5):** held back until the policy has a children's section. Otherwise the link would point
  at the contradicting text.
- **D3, Grown-ups copy:** the panel claims only what the game guarantees. The page description now says "No sign-in, no
  ads, no tracking. Progress stays on this device." (F3)
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
