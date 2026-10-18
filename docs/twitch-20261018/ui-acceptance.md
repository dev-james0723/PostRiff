# Twitch native UI acceptance — 2026-10-18

Implemented in `/workspace/scratch/84c4d423cd8c/rafii-twitch-worktree`. This receipt covers isolated frontend engineering and offline checks. It does not establish live OAuth, public release, production readiness, commercial authorization or deployed browser acceptance.

## Results

| Check | Result |
| --- | --- |
| Behavioral and authenticated API contract tests | **21 passed, 0 failed**, exit 0 |
| Actual React/shared UI component rendering tests | **6 passed, 0 failed**, exit 0 |
| Server-to-browser native operation schema checks, including optional fields | **112 passed**, exit 0 |
| Full project TypeScript check | **0 errors**, exit 0 |
| Targeted frontend Oxlint | **0 warnings, 0 errors**, exit 0 |
| Frontend/backend Site Agent route manifests | Byte-identical, `cmp` exit 0 |
| Diff whitespace validation | `git diff --check` exit 0 |

The last schema receipt is bound to `src/postriff_phase2/twitch_native.py` SHA-256 `a1faa848cd384e2c4770936a0f48d7e028589d44bebe294052bea8a1ea6f4022`, following the native extreme-numeric-input hardening. The generator validates fixture payloads against the actual Python registry. The browser runner rejects a stale source hash and parses the same payloads through the production TypeScript parser. These are 112 operation-contract checks in addition to the 27 Node test cases.

Earlier intermediate counts were 20 behavioral tests and 5 rendering tests. The final counts are **21 and 6** after adding accepted-clip reconciliation coverage.

## Actual runtime and dependencies

| Component | Version |
| --- | --- |
| Node | 24.19.0 |
| npm available in the runner | 11.9.0 |
| TypeScript | 5.7.2 |
| React / React DOM | 19.2.4 / 19.2.4 |
| `@types/react` / `@types/react-dom` | 19.2.14 / 19.2.3 |
| `@types/node` | 22.10.2 |
| Oxlint | 1.65.0 |

The repository declares npm 11.12.1; the isolated runner actually supplied npm 11.9.0. The existing lockfile dependencies were installed unchanged with lifecycle scripts disabled. No dependency manifest or lockfile was modified. The complete locked dependency copy lives at `/tmp/rafii-twitch-ui-project-deps/node_modules`; the ignored `web/node_modules` symlink points there. An earlier small compiler-only environment is at `/tmp/rafii-twitch-ui-typecheck` and was not used for the final project check.

The disposable dependency copy was installed with:

```sh
npm ci --legacy-peer-deps --ignore-scripts --no-audit --no-fund --fetch-retries=0 --fetch-timeout=15000
```

`--legacy-peer-deps` matches the repository's existing `web/.npmrc`. This installed 335 packages in the free isolated runner. No Mac build or other mission process was used.

## Exact verification commands

Run from `/workspace/scratch/84c4d423cd8c/rafii-twitch-worktree`:

```sh
node web/tests/twitch-native-controls.test.mjs
node web/tests/twitch-native-render.test.cjs
PYTHONPATH=src python web/tests/twitch-native-schema-fixture.py /tmp/rafii-twitch-native-fields.json
node web/tests/twitch-native-schema-contract.mjs /tmp/rafii-twitch-native-fields.json
node /tmp/rafii-twitch-ui-project-deps/node_modules/typescript/bin/tsc --noEmit --incremental false -p web/tsconfig.json
web/node_modules/.bin/oxlint web/src/features/twitch web/src/app/app/twitch web/src/lib/api/client.ts
cmp web/src/lib/site-agent/route-manifest.json src/postriff_phase2/site_agent/route_manifest.json
git diff --check
```

The direct Node TypeScript tests emit a harmless `MODULE_TYPELESS_PACKAGE_JSON` warning. Individual subtest totals above come from the direct-file commands; the runner's `node --test` subprocess mode can display only a file-level total. No package-mode change was made to suppress the warning.

## What the checks establish

The tests execute the actual API client, schema parser and React components. They cover authenticated and encoded workspace/connection routes, missing-session rejection, server denial, no automatic mutation retries, exact payload preservation, Boolean and nested fields, Unicode character lengths, live-availability fail-closed behavior, current authorization generation and approval expiry, payload/time/declaration invalidation, scheduled-draft recovery, safe official OAuth/CDN URLs, private and escaped provider data, distinct partial/asynchronous/unknown receipts, and explicit clip-result reconciliation.

The native workspace uses the existing Rafii authentication, workspace, channel and site-context components. Every write follows preview, exact per-action approval and durable receipt. Stream keys and authorized clip links use the separate interactive endpoint and are cleared after 30 seconds or tab hide; no secret or content is automatically downloaded or persisted by the browser. The entire Twitch content body is `data-private` for the existing generic Site Agent collectors. Only a local connection ID and current group/action names are registered in page context; typed native Agent tools remain responsible for consent-controlled model output.

Database RLS, backend tenant isolation and provider response validation have their own backend test evidence; the frontend checks do not substitute for them.

## Remaining unverified work

Live OAuth and callback behavior, live EventSub delivery, live mutation receipts, interactive deployed/staging browser accessibility, public connect release and commercial/content-storage approval remain unverified by this UI work. No GitHub push, PR, merge, production change, deployment or live external action was performed. The complete implementation and resume notes are in `web/src/features/twitch/ENGINEERING-HANDOFF.md`.
