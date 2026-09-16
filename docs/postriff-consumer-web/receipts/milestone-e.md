# Milestone E receipt — Web experience, operations, launch acceptance

**Date:** 2026-09-16 · **State:** implemented; verified in a browser against the real hosted code on the local dev harness · **External state:** unchanged (no deployment; no hosted migration; no real provider or identity)

## What changed

| Path | Change |
|---|---|
| `scripts/postriff_dev_hosted.py` | **new.** Local dev harness (D14): real hosted code + disposable PostgreSQL; synthetic identity/providers/storage, labelled in the UI; background worker tick; SPA fallback; orderly shutdown. |
| `studio/web/src/founder/Cloud.tsx`, `cloud-api.ts`, `cloud.css` | **new.** Typed client for the §21 routes; screens: `IdeasCloud` (conversation list, Chat/Edit/Preview panes, quick-start, run log, apply), `ChannelsCloud` (capability matrix cards, inline permission step before redirect, re-verify, two-step disconnect, OAuth return handling), `UsagePlan` (entitlement, plan terms labelled proposed, budget bar, ledger, export/diagnostics/privacy), `AnalyticsLimited`, `AudienceLimited` (reply draft → exact preview → approve), `AccountMenu`. |
| `studio/web/src/founder/FounderApp.tsx` | Exactly six primary destinations; Skills/You moved to the account (utility) menu; collapsible sidebar (persisted); global `+ Create` → Ideas; mobile bottom nav (Dashboard/Ideas/Scheduling/Audience + More sheet with Channels/Analytics/utility); `dev` auth mode; `/channels/connect` OAuth return; hosted routing for Ideas/Channels/Usage/Analytics/Audience; DEV banner; onboarding rail only in setup mode. |
| `AuthEntry.tsx`, `api.ts`, `types.ts` | Dev sign-in entry; `authMode` union; catalog `execution`. |
| `alpha/index.html`, `alpha/public/manifest.webmanifest`, `sw.js`, `icon.svg`, `icon-maskable.svg` | Installable PWA: manifest, icons, theme color, service worker (D15), share target. |

## Validation (observed, 2026-09-16)

| Check | Result |
|---|---|
| `npx tsc --noEmit` / `vite build` (hosted config) | pass; bundle 626 kB (>500 kB advisory unchanged from baseline) |
| `npm test` | **75/75** |
| Python unit suite | **186/186**; PG `repository/safety/isolation/ideas/channels/billing` + Phase-3 PG: **all pass** |
| Browser — desktop 800×801 (pane), dev harness | Welcome → dev sign-in → Ideas: quick-start from pasted text → two native candidates (LinkedIn EN, Instagram 繁中) with run log (11 safe events) → "Add to my drafts" → 2 reviewable drafts (revision 4). Channels: Connect Threads → inline permission step (scopes shown) → local consent → callback → authenticated exchange → capability card: Identity **Direct**, Post **Direct**, Schedule **Assisted**, Analytics/Comments/Reply/Moderate **Unsupported**, evidence strings, expiry, re-verify/disconnect. Analytics: explicit limited state + rules. Audience: explicit limited state + capability note. Account menu: You / Skills / Usage & Plan / Export / Sign out. Usage & Plan: 10 batches, 14-day trial (fixture provider, price proposed), $0.00 spend with $6.00 candidate stop, overage Stop, four plan terms all PROPOSED, data buttons. |
| Browser — mobile 375×812 | Six destinations reachable (4 in bottom nav + More sheet); Chat/Edit/Preview segments; no horizontal overflow; targets ≥44 px (nav 54 px); Create as round button; DEV banner wraps. |
| Keyboard/SR primitives | skip link, `aria-current`, menu `role=menu/menuitem` with Escape + initial focus, `aria-expanded`/`aria-haspopup`, tablists for segments/destinations, `role=progressbar` with values, dialogs `aria-modal`, `:focus-visible` outlines, reduced-motion respected. |

`validation_unavailable`: automated a11y run (axe/Lighthouse not in repo); real cellular-network access (needs a deployed URL and a phone); PWA install prompt on a real device; push permission flow end to end (SW handlers exist; no push service); real provider screens; Scheduling calendar grid (still grouped list — `Phase2.tsx` unchanged); `Schedule N posts` aggregate label (multi-destination approve exists in API, single-destination UI); Dashboard four-card layout unchanged.

## Defects found and fixed during the pass
- Local sign-in shown instead of dev entry (prop mapping) → fixed.
- Permission step crashed (`provider` string clobbered the object) → fixed; also replaced `window.confirm` with an inline permission step and a two-step disconnect.
- Stale shell after rebuild (cache-first SW) → network-first shell (D15).
- OAuth return landed on Ideas before the exchange ran (nav ordering) → fixed.
- Green button link text invisible → fixed.
- Onboarding rail present on cloud Ideas → guarded to setup mode.
- Dev harness orphaned its PostgreSQL on SIGTERM → orderly shutdown.

## Acceptance mapping (§28 Mobile/PWA, §5, §24)
- Six destinations at 390×844 without horizontal overflow: **verified at 375×812** (narrower than the criterion).
- Ideas mobile: prompt, URL/text source, preview, apply: verified; document/image attachment UI: not built (API exists).
- Catalog/guided creation on mobile: existing `ContentTypes` component is reachable through the guided setup mode; not re-verified this pass.
- Push requires permission and never executes: SW handlers open a URL only; permission prompt UI not built.
- Onboarding one question at a time: quick-start asks two confirmations + language before the first preview; the guided voice setup remains available.

## Actual external state
Nothing deployed. The only running instances are local: the alpha SQLite server (4326) and the dev harness (4331).

## Remaining gates (none executed)
1. Apply 004–007 to the hosted DB; set `POSTRIFF_CREDENTIAL_KEY`, `POSTRIFF_PUBLIC_BASE_URL`; deploy web + API; run `scripts/validate_postriff_hosted_preview.py`.
2. Provider apps + reviews (C9); model route qualification (B11); payment provider + legal (D8).
3. Observed end-to-end cloud journey with the founder laptop off, second workspace, real device on cellular — requires 1–2.

## Next concrete action
Evidence diff and `consumer-web-release-receipt.md` stating exactly what is observed-real, synthetic, blocked, and unavailable.
