# WP16 local integration receipt

Status: verified locally. Runtime hash `62a11e2d7e21dbef1d01163702718d48573767ed8045f7131df43c2cc2e57129` is SHA-256 of the compact sorted runtime path→SHA-256 JSON map (20 files). Exact current files and deltas from accepted `1a6630ac…` are in [wp16-validation.json](wp16-validation.json). Backend service remains `0f1e2d32a1b2be403f23f46d0d7540283d83e2d61428156cfa70a50ba3ded44b`.

## Changes

- Lab now sets editor text from the canonical returned `variant_edit` Snapshot. No payload, lineage or markup change. The editor file changed `3016c5b9…` → `b164943b…`; exact immediate text, clean state and another Review are tested.
- Opportunity views require native intersection, visible document, unoccluded hit-testing and at least500ms. One observer/timer per card, at most two attempts with the same event UUID/body. Hidden/unmounted/default-OFF and obscured cards cannot emit late events. Closing the trust drawer resumes a fresh dwell after focus restoration/scroll.
- Signed page candidates retain API order. Acceptance optionally links the actual returned exposure ID. Explicit Not relevant records dismissal without a reason; trend measurements and evidence remain. Missing/failed exposure IDs are omitted.
- Zod/JSON Schema is additive and backward compatible. Contract: [CONTRACT.md](CONTRACT.md). Preservation addendum: [wp16-feature-preservation.json](wp16-feature-preservation.json).

## Verification

- **46 real API + PostgreSQL browser checks**,1440/390. Original22 Radar/Ideas and16 Lab checks retained;8 new signed exposure/dismiss checks. No Trend API response interception. Identity, observations, destination and saved Lab draft are explicit synthetic seeds.
- **30 focused synthetic browser checks**,1440/390, against the same production build. Explicit intercepted API/document visibility fixtures with real native IntersectionObserver. Includes timing, hidden, occlusion, unmount, drawer resume, default/receipt flags OFF, UUID retry, missing ID, conflict, keyboard/focus, reduced motion, axe0 serious/critical and viewport fit.
- Normal `npm run build -- --webpack` **PASS**, including TypeScript. Build ID `9L4H7Tr2d3wlBYey8pBmN`; no mocked fonts. Scoped source lint6 files:0 warnings/errors. Canonical schema export and strict input regressions pass; Python/JS syntax and diff checks pass.
- Independent DB assertions: one exposure + one decision per Radar/dismiss workspace, four succeeded local Lab jobs, zero model usage events, zero provider/model reservations and zero unexpected backend/browser egress. Dismissal creates no source/draft. Lab canonical edit persists revision2; concurrent revision4 survives stale UI apply and stale variant revision, both409.

Exact commands and artifact paths are in the JSON receipt. Main evidence:

- `/private/tmp/trend-wp16-final-r2/{build.log,browser-results.json,harness-result.json}`
- `/private/tmp/trend-exposure-fixture-receipt/results.json`
- Visually inspected mobile opportunity actions, desktop dismissal, real mobile dismissal; screenshots remain in those directories.

## Historical findings and boundaries

`/private/tmp/trend-tier-c-lab-r3/harness-result.json` remains `passed_with_findings` for the pre-fix editor whitespace defect. The normal-build repair38 passed separately at `/private/tmp/trend-tier-c-lab-fixed`. The first exposure attempt showed native IOv2 treating readable glass as invisible; the first real run exposed missing resume after closing the drawer. Both have explicit final regression coverage.

The earlier201 layout matrix remains historical evidence; it was not rerun or relabelled as current. No broader redesign was performed. Reported views do not prove attention or a complete candidate universe. No provider/model generation or publication was exercised. This worker made no commit, push, merge or deployment. Owned local servers and ephemeral PostgreSQL stopped; only owned generated tsconfig includes were cleaned. Original font-loader failure remains historical and was not diagnosed as repaired by these successful builds.
