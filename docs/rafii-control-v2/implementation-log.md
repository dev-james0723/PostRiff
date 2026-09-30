# Rafii Control v2 implementation log

Status: Phase 0 boundary and requested Phase 1 read-only foundations implemented and locally verified. Full v2 operational acceptance is not claimed. Commit/PR delivery follows this verified candidate; activation decisions below remain unresolved. Local/synthetic only; no production activation.

## Baseline — 2026-09-29

- Canonical checkout: `consumer-saas`, HEAD `468811b73d28b4389f931519827c05d0e6c8abfb`, 525 changed paths at inspection. No canonical source files modified, stashed, reset, cleaned or staged.
- Isolated worktree: `/Users/ouxianxing/.codex/worktrees/rafii-founder-control-v2/James-Au-Studio`.
- Branch: `feat/rafii-founder-control-v2`; fetched/verified base `d91660b7936a5158b820914107306ad4a1e51c2d`.
- Base GitHub release gates: success, runs 36623516044 and 36623634575. These are observed provider records, not local reruns.
- Production provider observation: `dpl_uwCTSjT1Tr56yftdvGy5xp9ny2uP`, Ready, existing `postriff-phase2-private` project with Next.js and Python services. No authenticated production journey was run.
- Authoritative v2 master copied byte-for-byte from supplied tech-pack to the requested design path. SHA-256 `1ababaaff637a04be105fa41caf1eb57f071c1e57819eb39116c030fea993002`. V1 is background only. No same-project founder route will be added to the consumer deployment.
- Migrations 001–046 on base, with reserved gaps 026–029. Active refs/worktrees contain 047 Inbox and Universal Library, 048 pricing. Next currently free: 049; recheck before commit.
- Runtime anchors rechecked: Supabase verifier/verified claims, agent typed contracts/forbidden effects, canonical profiles/memberships/subscriptions/usage ledger, notifications, existing release/DB/browser harnesses.
- Available disk approximately 8 GB. Build resource failures must remain infrastructure failures.

## Implementation units

1. Founder boundary (`src/rafii_control/{auth,http,store}.py`, migration 049): server operator UUID, capability allowlist, AAL2 with actual MFA AMR freshness, opaque hashed session, exact host/origin/CSRF, revocation/epochs, append-only audit, dedicated session/read roles. Tests first in `tests/control/test_boundary.py`, then PostgreSQL/RLS integration.
2. Read models and intelligence (`store.py`, `intelligence.py`, `metrics.py`, `projections.py`): bounded canonical metadata views and metrics registry/receipts; data quality, isolated tool registry, recommendation and engineering evidence validation. No command executor, private-content fetch, paid model or new webhook writer.
3. Separate `control-web/` shell and control-only API/deployment config: disabled default, ephemeral Supabase sign-in/MFA exchange, Command, Customers/User 360, Workspaces, analytics/source/engineering/audit views, founder intelligence panel. Reuse installed Next/React/Recharts conventions. Browser/API/DB and accessibility tests.
4. Full relevant suite, static security and spec gap reviews, clean commit/push and PR against `consumer-saas`. Preview only if a separate synthetic control project satisfies policy. No merge or production promotion.

## Unresolved activation decisions

Verified ops domain/RP origins; actual founder UUID binding; deployment project approval/configuration; dedicated login credentials and region; approved retention/financial metric policy; paid model/integration/monitor budgets. These do not prevent local implementation and remain off by default.

## Verification history — local only

- Boundary RED: missing `rafii_control` implementation; GREEN 19 tests.
- Database role/RLS RED: missing migration; repaired actual canonical column names (`plan_terms_id`, `last_seen`); GREEN restricted-role suite.
- Intelligence RED: missing service; GREEN bounded DSL, unknown/cross-grain/currency denial, unavailable/zero distinction, isolated forbidden-effect-free tools and engineering evidence checks.
- Definition kernels RED: missing module; GREEN native currency/annual normalization/top-up exclusion, cash movement identity deduplication/overlap, mature retention denominators, private event payload denial.
- Projection RED: missing projector; GREEN deduplication, cursor lineage, conflicting replay rejection and ingest/reader privilege separation.
- Latest `.control-venv/bin/python scripts/rafii_control_pg.py`: **36 tests passed**, including 7 PostgreSQL integration tests. Disposable PostgreSQL 17; synthetic identities/domain fixtures only.
- `control-web`: host/local-forwarding contracts **2 passed**; typecheck PASS; lint **0 warnings/0 errors**; production build PASS with Next 16.3.5/Node 24.15.0.
- Browser attempts: matching Playwright executable initially missing. Isolated headless Chromium 151 installed under `.control-browsers/` (ignored). First actual browser API request found local Node fetch replacing the forwarded Host; API correctly returned 404. Native bounded HTTP forwarding repair is being verified. Browser acceptance is **not yet passed**.
- Runtime files: `src/rafii_control/{auth,http,store,intelligence,metrics,projections,hosted}.py`; separate API entry `api/control.py`; `control-web/`; migration `049_rafii_control_foundation.sql`; `scripts/rafii_control_pg.py`; `tests/control/`; deployment wiring/release gates still pending.
- Schema: private operator/session/audit/query receipt/source/engineering/run/recommendation/rate-budget/event/cursor/rollup tables, forced RLS; fixed boolean identity function and canonical safe metadata views; distinct reader/session/ingest roles and non-login column-limited projection owner. No operator seeded by migration. Canonical customer, financial and credit tables are unchanged.

## Final verification and reviews

- Latest source-stable full Python gate: **3,006 run, 2,755 passed, 251 skipped, zero failures/errors**. Source fingerprint `09c98474358c25ac7db6834576240fd056048836185a1feac28c60627e5624b3`, unchanged during execution. An earlier passing run was invalidated when the local artifact helper was added during its source-bound wrapper; the final run replaces it.
- Control: **45/45 passed, zero skips**, including **7 actual PostgreSQL/RLS tests**, migration 049 applied twice safely, fresh candidate import, MFA/expiry/revocation/host/CSRF/audit/Preview DSN tests, bounded DSL, engineering stages, privacy/golden kernels and idempotency/projection checks.
- Production-mode local browser: **PASS**, Next -> WSGI -> restricted disposable PostgreSQL, widths **390 and 1440**, route/User 360/private canary/receipts/copilot/CSRF/logout journeys; **zero page errors and zero settings axe violations at both widths**. Synthetic screenshots in `evidence/` were visually inspected. This is not a worldwide performance or full accessibility certification.
- Control frontend: **3/3 contracts PASS**, typecheck PASS, lint **0 errors/0 warnings**, production build PASS (Node 24.15.0, Next 16.3.5), using a fresh portable dependency installation.
- Existing consumer web contracts: **478 passed, zero failures/skips**. Local Python dependency path was corrected before the successful rerun. Consumer typecheck PASS after supplying missing pinned GSAP packages in a **worktree-only dependency overlay**; shared node_modules were not modified. Consumer lint: **0 errors, one existing warning**.
- Existing PostgreSQL regressions: **90 script executions PASS** using unchanged legacy inputs. The first aggregate had 89 successful executions and one provenance rejection although all 35 assertions passed. That guard had counted in-worktree installed psycopg modules as newly imported source. The same pinned dependency environment copied outside the repo yielded **35/35 passed, zero skips, source guard unchanged**. No unrelated test code was changed.
- Static source secret gate PASS with zero unexpected findings and unchanged source. Supplemental offline scan covered **79 Control/spec/pack files**; **31 verified SHA metadata findings and one synthetic rejected Basic Auth URL fixture** were reviewed, with zero unexpected findings. Dependency audits: **zero Control npm and Python vulnerabilities**. Compile/static syntax/diff checks PASS.
- Authoritative pack: **66 checks passed, zero failed**; master byte equality and required SHA-256 verified. The pack's **96 designed product acceptance cases are not 96 executed product tests**.
- Staged whitespace review: implementation files pass. Supplied spec Markdown hard breaks and CSV CRLF are preserved byte-for-byte as required; their original whitespace warnings are recorded rather than rewriting the authoritative package.
- Actual local Python archives PASS: Control **688 files / 2,366,692 bytes**, consumer **4,759 files / 31,007,139 bytes**. Consumer source/zip excludes Control. Pinned CLI 59.23.2 / Python builder 14.2.0; no deployment or Vercel runtime invocation. `scripts/rafii_control_artifact.cjs` preserves an allowlisted candidate and digest receipt without loading credentials or linking a project.
- Security follow-up RED tests failed on missing/incorrect behavior before repairs, then passed: request-bound denial/prohibited audit, authoritative error codes, copilot validation-before-reservation and safe terminal failure, locale data packaging, staged database binding/distinct logins/TLS/redirect denial. Engineering provider green remains suspected without a qualified manifest.
- Schema changes: only additive **049_rafii_control_foundation.sql**. No operators or credentials enrolled; no canonical customer/billing/credit rows changed by the implementation. Active refs/worktrees rechecked before delivery: no other 049 filename found.
- Existing test-generated tracked evidence under `docs/design/site-agent/agent-runtime/evidence/pg-scenarios.json` and `docs/postriff-research-20260918/evidence/receipt-snapshot.json` was returned to its original base content in this isolated worktree. It is not included in the change.
- Initial draft PR #83 Control CI failed because npm had generated linked local dependency paths while the temporary shared dependency symlink was present. This was an implementation packaging error, not a passing CI result. A regression contract failed first; the lockfile was regenerated in a fresh empty directory and installed into worktree-owned node_modules. Shared dependencies remained unchanged. The corrected install, all **3 frontend contracts**, typecheck/lint/build, **45/45 Control/PostgreSQL tests**, both browser journeys, archive and zero-vulnerability audit passed locally. CI on the correction is separately reported by the PR provider records.
- Final engineering review extended stage qualification to deployment and error evidence as well as check records. Two added subcases reproduced inappropriate advanced-stage promotion before the repair. All advanced stages now retain an observed-stage field but remain suspected without qualified stage evidence. The latest **3,006-test** source-stable suite, static secret gate, **45/45** Control/PostgreSQL suite, desktop/mobile browser journeys and actual Control archive passed again. No production bug-fix or production-verification claim is made.
- Reviews: `security-review.md`, `spec-gap-review.md` and `integration-map.md`. Exact counts, commands, artifacts, limitations and recoverable local logs: `evidence/verification.json`.

## Changed files and next action

Source: `src/rafii_control/{auth,http,store,intelligence,metrics,projections,hosted,__init__}.py`, `api/control.py`, `control-web/`, `tests/control/`, migration 049, `requirements-control.txt`, `vercel.control.json`, `scripts/rafii_control_{package,artifact,pg}` and `.github/workflows/rafii-control.yml`. Packaging guards: `.gitignore`, `.vercelignore`. Documentation: authoritative v2 spec/pack, migration reservation and `docs/rafii-control-v2/`.

Next action is review of the feature-branch PR; do not merge/promote or activate production. Before Phase 2 authority expansion, approve/qualify actual founder identity, ops domain/project, staging separation and hosted roles/TLS, data region/retention, financial metric policies and source/model budgets. Qualified rollup materialization, live source adapters, richer copilot/chart behavior and operational acceptance remain explicit gaps in `spec-gap-review.md`. Current proposed business definitions remain unavailable with receipts. No paid integration, email/push, refund, real account change, production migration, DNS change or production deployment occurred. Dedicated Control Preview was not created because required separate project/staging gates are absent.
