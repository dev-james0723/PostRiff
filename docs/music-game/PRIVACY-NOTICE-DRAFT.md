# DRAFT: Note Garden privacy section, for counsel

> **DRAFT. Not legal advice and not published.** Decision D9: the site privacy policy is legal text owned by James and
> counsel. This file proposes wording and lists the facts it rests on. Nothing here changes
> `web/src/app/(marketing)/privacy/page.tsx`.

## Why this is needed (privacy review F4)

The site policy, section 11 "Children" (`web/src/app/(marketing)/privacy/page.tsx`), says: "Rafii is not directed at
anyone under 18 and we do not knowingly collect data from them." Note Garden (`/play/note-garden`) is a music game made
for children aged 6 to 10. So the policy currently contradicts the product, and it says nothing about what the game
stores or sends.

## Facts the proposed text relies on (verified in code and tests on branch `task/ao-rafii-20261031-bf90f0`)

| Fact | Evidence |
|---|---|
| No accounts, no sign-in and no forms. The game never asks for a name or any personal detail | Game UI code in `web/src/components/music-game/`. The route is public (`/play` is outside the sign-in gate) |
| No ads | No ad code or third-party scripts in the game |
| Progress is kept only in the browser, under one key | `web/src/lib/music-game/progress.ts`: localStorage `rafii.noteGarden.v1` |
| Exact stored value | `{"v":1,"best":{"1":0-3,…,"4":0-3},"done":{"1":true/false,…},"allOpen":true/false,"muted":true/false,"volume":"soft"/"medium"}`. No names, IDs, timestamps or answer history |
| Reset | Grown-ups → "Reset progress" deletes the key. Only a non-default sound choice (muted or soft) is written back. Clearing the browser's site data also removes it |
| No cookies from the game | No game code sets cookies. The site proxy skips its sign-in session refresh on `/play` (`web/src/proxy.ts`), so no auth cookie is set or refreshed there |
| No analytics or error telemetry from `/play` | Decision D1 = exclude. Vercel Web Analytics is not loaded and drops `/play` page views. Sentry is not loaded when a visit starts on `/play`, and every envelope is dropped while on `/play` (`web/src/instrumentation-client.ts`, `web/src/instrumentation.ts`). Checked by `web/tests/play-telemetry-browser.cjs` |
| Sound is made in the browser; no microphone | Web Audio synthesis only (`web/src/lib/music-game/synth.ts`). No recording or audio read-back APIs |
| The page is still served by a host | Like any web page, loading it sends a request (IP address, browser type, page address) to the hosting provider, which keeps request logs. **[COUNSEL/JAMES: confirm the provider, the log contents and the retention period]** |
| The host may set its own cookies | The game and the site's own code set none on `/play`. The hosting provider or its security layer (for example bot or DDoS protection) may still set strictly necessary security cookies of its own. Not observed locally. **[COUNSEL/JAMES: confirm with the provider before claiming "no cookies"]** |

## Proposed wording (plain English, for parents)

**Note Garden (our music game for children)**

Note Garden at rafii.io/play/note-garden is a free music game for children aged 6 to 10. We built it to collect as
little as possible:

- **No accounts, no names.** Children never sign in, and the game never asks for a name, email or any other personal
  detail. There are no ads.
- **Progress stays on your device.** The game saves only stars, finished levels, the sound setting and the volume in
  your browser's local storage, under the name `rafii.noteGarden.v1`. It is not sent to us. To delete it, open
  "Grown-ups" and choose "Reset progress", or clear this site's data in your browser.
- **No tracking.** We do not run analytics or error reporting on the game's pages, and the game itself sets no
  cookies. Our hosting provider may set strictly necessary security cookies. **[COUNSEL: confirm]**
- **Sound stays on your device.** The music is made in your browser. The game does not use the microphone.
- **Like every website,** our hosting provider receives basic technical information (such as your IP address and
  browser type) when the page loads, in order to deliver it. **[COUNSEL: provider name, what is logged, retention]**

Questions: **[CONTACT EMAIL / ADDRESS PLACEHOLDER]**

## Suggested change to section 11 "Children" (for counsel to decide)

Current: "Rafii is not directed at anyone under 18 and we do not knowingly collect data from them."

One option: "Rafii's main service is not directed at anyone under 18 and we do not knowingly collect data from them.
Note Garden, our music game for children, is described in [section X]: it has no accounts, collects no personal
information, and keeps progress only on the child's device."

## Open questions for counsel (not answered here)

1. Which children's-privacy rules apply to a free, account-less game for ages 6–10 offered from Hong Kong to a
   worldwide audience? For example: US COPPA, the UK Age Appropriate Design Code, GDPR Article 8 and national ages of
   consent, and Hong Kong's PDPO.
2. Is local-only storage (`localStorage`, never transmitted) personal data in any of those regimes? Does it need a
   notice or consent?
3. Do the hosting provider's request logs for `/play` need a specific disclosure, retention limit or processor terms?
4. Should the Grown-ups panel link to this section? A link is held back for now (privacy review F5) because it would
   point at the current, contradicting policy.
5. The wider Rafii site still runs Vercel Web Analytics and Sentry on other routes. Does the policy need to state that
   `/play` is excluded?
