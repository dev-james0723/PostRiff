# WP09 / WP16 UI validation receipt

> Historical baseline. The final creator redesign receipt is `REDESIGN_VALIDATION.md`, with current source hashes in `redesign-validation.json`.

Date: 2026-09-27. Managed worktree: `social-trend-intelligence/James-Au-Studio`. No commit or deployment. Feature exposure remains server flag + workspace allowlist controlled, default off.

Implemented `/app/trends`, trust drawer, stored metrics/coverage/method/calibration views, timeline gaps and graph-equivalent lists, opportunities/Ideas acceptance, watches, and Opportunity Lab inside the existing draft editor. Production API reads use the existing authenticated session/workspace primitives and strict Zod response validation. No production fixture routes or synthetic defaults. Narrow integrations only: `features/coworker/nav.ts` and `features/pipeline/edit-draft-dialog.tsx`.

Canonical schema: `web/src/lib/coworker/trend-types.ts`; generated artifact: `docs/design/social-trend-intelligence/api.schema.json`; nested protocol and Stage3 compatibility: `CONTRACT.md`. Server-owned lineage and existing variant_edit payload are retained.

## Completed checks

All commands below run from this worktree's `web/` unless specified.

- `npm run lint`: PASS, 819 files, zero warnings/errors.
- `npm run typecheck -- --incremental false`: PASS, including after generated tsconfig cleanup.
- `node tests/trend-contract.cjs`: PASS canonical generated schema, strict mutations, precise verification enum and restricted evidence projection.
- `node --test tests/trend-lab.test.cjs`: PASS 3 tests covering frozen draft/opportunity/context/receipt/deadline binding, selective edit ambiguity, and stage/calibration qualification.
- `TREND_WEB_URL=http://127.0.0.1:3198 TREND_EVIDENCE_DIR=/tmp/trend-ui-production-evidence node tests/trend-browser.cjs`: PASS 47 recorded checks at 1440/390/820 against the actual production build. Execution is explicitly **synthetic intercepted browser**; all API responses are test fixtures. This is not full vertical API/DB E2E.
- Browser checks: flags-off zero trend requests; stored authenticated browsing; loading/empty/error/unavailable/partial/collecting/invalid/expired/deleted/aggregate states; receipt410 removes cached claims; persisted watch acknowledgement and revision-safe disable; Ideas source acceptance without generation; Lab explicit evaluation, user-fact guard, existing revision edit and asynchronous stale-result race. No unexpected mutations, browser runtime errors or external browser requests.
- Accessibility: Radar/trust drawer at all three widths, Lab at1440 and 200% equivalent reflow had zero serious/critical axe findings (including contrast). Keyboard graph/list access, focus trap, Escape, focus restoration and reduced-motion drawer transitions passed. 200% check uses820 physical pixels/410 CSS pixels through Chromium device metrics; it is an automated browser-zoom-equivalent reflow check, not manual browser chrome zoom or full human conformance certification.
- Screenshots reviewed: `/tmp/trend-ui-production-evidence/radar-{1440,390,820}.png`, `zoom-200.png`, `lab-1440.png`. Results: `/tmp/trend-ui-production-evidence/results.json`; browser log: `/tmp/trend-production-browser.log`.
- Backend integration owner reported actual Python service projections validate under Draft202012Validator against the generated schema for list/detail/receipt/opportunities/opportunity/accept/watch, and88 local backend tests pass. This is owner-reported evidence, distinct from this worker's browser suite.

## Actual build evidence and original failure

Original command:

```sh
NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SENTRY_DISABLED=1 POSTRIFF_DIST_DIR=.next-trend-build POSTRIFF_API_ORIGIN=http://127.0.0.1:9 npm run build -- --webpack
```

Original failure in `src/components/themes/font.config.ts` (full original log `/tmp/trend-build.log`):

```text
TypeError: Cannot read properties of null (reading '1')
    at /Users/ouxianxing/Documents/James-Au-Studio/web/node_modules/next/dist/compiled/@next/font/dist/google/loader.js:122:78
```

The original offending remote font URL was not emitted. Read-only diagnostics of all16 configured font CSS responses found no invalid suffix; the exact offending URL remains unidentified. Do not invent a URL or claim a code fix. A separate mocked-font diagnostic build passed, but is not production build evidence.

Final actual build command, without mocked fonts:

```sh
NODE_OPTIONS=--require=/tmp/trend-build-font-trace.cjs NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SENTRY_DISABLED=1 POSTRIFF_DIST_DIR=.next-trend-releasecheck POSTRIFF_API_ORIGIN=http://127.0.0.1:9 npm run build -- --webpack
```

PASS: optimized compile, TypeScript, page generation and `/app/trends` route. Final log `/tmp/trend-build-final.log`; earlier fresh successful real fetch trace `/tmp/trend-build-real-retry.log`. The temporary preload only logs CSS/font URLs and returns Next's original response unchanged. No dependency/source font modifications. Final build reused normal Next font cache. Original failure is transient/unreproduced, not repaired by this UI patch.

Stopped own3198/3199 loopback servers. Removed exactly six generated `.next-trend-{ui,build,releasecheck}` type includes; `tsconfig.json` and `next-env.d.ts` have no diff. Other workers' files are preserved.

## Remaining boundary

Tier C real API + disposable PostgreSQL browser integration is a separate newly authorized task; these47 fixture checks do not satisfy it. Live provider rights, calibrated semantic/outcome performance, production deployment and paid acquisition/model validation remain outside this UI evidence. No paid API/model calls were made. Usage/cost accounting is unavailable; no savings estimate is claimed.

## Tier C completion (before redesign)

Real API + disposable PostgreSQL browser integration PASS:22 checks at1440/390, no trend response interception. Existing Ideas source appears immediately after acceptance and afterreload. Independent DB confirms one source and decision perworkspace, exact server lineage, no generated drafts and zero trendjobs. Backend socket/DNS denial probes pass; unexpected backend/browser egress0. Identity, observations and destination are explicit synthetic seeds; this does not qualify real provider results.

Command from repository root: `PYTHONDONTWRITEBYTECODE=1 /private/tmp/rafii-release-venv/bin/python scripts/trend_browser.py --out /tmp/trend-tier-c-cachefix`. Evidence: `/tmp/trend-tier-c-cachefix/{browser-results.json,harness-result.json,build.log,real-*.png}` and `/tmp/trend-tier-c-cachefix.log`. Actual production rebuild, full typecheck and scoped lint pass. Own testprocesses and generated type includes cleaned.

Tier C exposed and resolved a backend fractional-clock bound bug (backend owner) and stale Ideas snapshot afteracceptance. Approved UI repair awaits existing `useSnapshot().refetch({throwOnError:true})` before showing the link; payload and lineage remain unchanged. Hashdelta `/tmp/trend-cache-fix-hash-delta.json`: before ae8fa5043de8e2437477e345c7b3a3eb97759b069197096bb3d0843296c97948; after586c6d89acacbf5302d3412a980703897c7af5f08586953ee9d1a5bbc15c94b2. MarkupSHA unchanged f18e27503103ba338071cc834e97696c9cbc0b4510f843212dd13397a00147f9.47 unchanged-layout checks remain prior evidence only. A subsequent full UI redesign is newly authorized and requires fresh affected UI/accessibility and realAPI regression checks.
