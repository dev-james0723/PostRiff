# Rafii × Mastodon — G2 isolated Local Release Candidate acceptance

**Date:** 2026-10-17 (U.S. Eastern). **Decision: LOCAL BUILD GO; LINUX E2E/CAPACITY NOT RUN; PUBLIC/PRODUCTION NO-GO.**

This supersedes the earlier G1 build-blocked assessment **only for the newer local build evidence**. The original G1 audit and SHA-256 manifest remain immutable.

## Immutable source and safety boundary

- GitHub: `dev-james0723/PostRiff`, default `consumer-saas`. Checked remote main: `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1`.
- Integrated isolated candidate before this G2 evidence commit: `9d79030efd8fde00b85d8ec6b0ea7618dad2a5bb`; parents `7432c56d` and Mastodon PR #176 head `53c8ab89`.
- Isolated worktree: `/Users/ouxianxing/Documents/.agent-worktrees/rafii-mastodon-public-rc-20261017`.
- Production Supabase: `buoyhkbodnhzngaotoel` **read-only**. G1 verified 62/62 applied migration file hashes; pending Mastodon migrations are 131/132/133; do not mistake old preview 113/114/115 as Production acceptance.
- No PR, Push, Merge, Vercel deploy, Production migration, feature flag change, live OAuth, provider write, new paid resource, or user rollout.

## Dependency and Next.js build acceptance

- A prior isolated X-build snapshot had byte-identical `web/package-lock.json` (SHA-256 `1b300aacc1220cf05699ea08bd92986ebff7c4068fad447be9a0866084f3f0c5`), matching all 462 lockfile package entries.
- Used APFS Copy-on-Write (`cp -cR`) to create an **actual independent** `web/node_modules` directory. No symlink to another worktree and no modification of source dependencies. Logical size roughly 1.0 GiB, initial additional allocated blocks measured roughly 60 MiB.
- Node.js `24.15.0`, Next.js `16.3.8`, actual checked-in `web/next.config.ts`. The **final full Turbopack Build passed** with exit 0 in **69.9 s**. It used the default TypeScript phase and the original Sentry configuration (Sentry environment credentials were absent).
- Environment was an explicitly constructed safe allowlist: no Production API, Supabase, payment, OAuth, Mastodon or Sentry keys; `NEXT_TELEMETRY_DISABLED=1`, `POSTRIFF_OAUTH_MASTODON_DISABLED=true`. No external service test was run.
- Build compiled successfully in **13.7 s**, TypeScript step completed, generated **114/114 static pages**, finalized routes, and produced `.next/BUILD_ID`, `routes-manifest.json` and `prerender-manifest.json`. Resource controls: 1,600 MiB V8 heap ceiling, `RAYON_NUM_THREADS=2`, process nice +14; 11 Next workers observed in logs, hence do not call this a single-threaded benchmark.
- Recorded logs: `evidence/next24-full-original-config-build-20261017.log` and JSON receipt. Build output remains locally in `web/.next` for controlled validation.
- Separate Node 24 `tsc --noEmit --pretty false` passed with exit 0. Earlier diagnostic split Compile/Generate each also passed but bypassed duplicate Next TypeScript and/or Sentry. **Those diagnostic results are NOT the basis for the full build claim.**

## Browser smoke qualification — NOT Linux E2E

- Linux-only browser suites were not changed or bypassed. Official `web/tests/mastodon-account-browser.cjs` and `mastodon-queue-browser.cjs` explicitly require Linux + CI, protected synthetic backend, PostgreSQL and account/queue assertions.
- On macOS, Playwright package 1.62.1 expected Chromium rev 1234 and WebKit rev 2336, but the only local cache contained Chromium 1243 and WebKit 2359. Directly launching existing executable paths worked for diagnostic guest smoke, **but browser revision parity is unverified**.
- Diagnostic generated build: Chromium + WebKit **12/12** loopback guest route checks passed, `/app/*` redirected to `/auth/sign-in`, and no browser requests left loopback.
- Final exact-config build: Chromium **6/6** guest route checks passed, no browser page errors / external requests; WebKit timed out during **browser launch** under high Mac load, before accessing a page. This is **NOT** a verified full-build WebKit acceptance, nor evidence of a Mastodon UI defect.
- No authenticated workspace session, actual OAuth state, two-server provider API, media, Queues with real account or cross-tenant interactive flow was tested. Mac browser smoke must never be reported as Linux E2E.

## Capacity / Linux host constraint and execution audit

- Observed 9 concurrent Kynlo Heavy Jobs, about 30 GiB swap, memory pressure warning and load up to ~42 on a 12-core Mac; remaining disk roughly 17–18 GiB at that checkpoint.
- Both running Colima instances are assigned to other D Festival / D Hub work. Starting an isolated new VM or using another project's daemon would compete for resources. **No VM/container was started, borrowed, stopped or modified.**
- `tests/phase2/postgres_mastodon_scale.py` enforces genuine Linux `CI=true`, 1,000 synthetic users and bounded SQL concurrency. **NOT RUN** here. Do not spoof platform/CI.
- The existing `scripts/cloud-mastodon-validation.sh` and `cloud-mastodon-browser.sh` are **NOT offline-only**: they may use `sudo apt-get`, `npm install` and Playwright browser downloads and the latter uploads an Actions artifact. DO NOT execute these scripts unchanged in this local-only, no-paid/isolated approval scope.
- Future free local Linux testing needs a *dedicated* isolated non-production Linux environment with headroom, an offline-pinned Python venv, PostgreSQL 16/17, Node 24, matching Playwright/browser binaries, exact local rewrite `127.0.0.1:4348`, and bounded ports/limits. All actual environment changes require their own safety preflight. Never use the busy D Festival VMs.

## Remaining release gates

1. Genuine isolated Linux PostgreSQL **1,000-user concurrent admission and Queue** regression with no provider egress and independently reviewed results.
2. Genuine Linux Chromium/WebKit full `Mastodon` Channels/Profile/Queue/Calendar browser fixture, including mobile/desktop, current account/instance, approval/hold, scheduled and independent workspace recovery. No mismatched browser revision shortcuts.
3. Independent Production-compatible Auth/Storage/DB backup plus tested restore, exact forward migration 131–133 rehearsal, environment and OAuth secret isolation.
4. Separate real authorization from the owner for **two Mastodon accounts on two independently operated servers**, exact scopes, and individually approved publish/edit/delete/schedule/cancel readback.
5. Release-level protected CI, final SHA/merge review, staged rollout, rollback gates and separate approvals for PR, Merge, Production migration, deploy, invited Beta, and public switch.

**Public status remains NO-GO.** A local Build PASS by itself does not authorize any user account access or release.

## Evidence and handoff

All G2 local logs, synthetic browser route results, build receipts, safety constraints, and a new SHA-256 manifest are in:
`/Users/ouxianxing/Documents/Rafii-Mastodon-Public-RC-20261017/`

Refer to `GO-NO-GO-G2.md` and `AGENT-HANDOFF-G2-NEXT.md` when resuming; the old G1 reports are preserved for provenance.
