# Rafii Full Generative UI Implementation Plan

> **For agentic workers:** Execute with available native parallel agents or superpowers:executing-plans in isolated worktrees. Use test-driven development and verification-before-completion. One implementation owner per file; at most one independent reviewer. Do not add serial approval meetings for the already-requested implementation.

**Goal:** Ship all C01–C10 capabilities and J01–J09 journeys as one tested production release.  
**Architecture:** Preserve Rafii's Manager and native chat; introduce a guarded, persistent OpenUI layer using shared contracts and original domain services. One integration owner accepts lane commits and owns the release.  
**Tech Stack:** Existing Python/Agents SDK, Next/React/Zod/TanStack/Recharts, official OpenUI renderer/parser, current auth/DB/ledger/CI.  
**Spec:** `01-ENGINEERING-SPEC.md`; interfaces in `02-CONTRACTS.md`.

## Global constraints

- Full production scope, not a prototype, three-journey MVP or hidden preview.
- Preserve existing business authority, permissions, consent, approvals, billing and unrelated work.
- Use isolated worktrees; no reset/clean/stash of another session's changes.
- One shared-contract owner; one migration/lockfile/deployment owner; one release owner: A.
- All tests/evidence refer to an exact candidate SHA; mock success is not live verification.
- No new paid/data-egress service without existing authorization; no real external customer actions for tests.
- Heavy cloud validation preferred; only one heavy local build/test batch at a time.

## Review focus

1. Two tabs or surfaces apply a stale layout/action against changed domain data: reject/reconcile, not overwrite.
2. User starts typing while stream/repair/patch arrives: input and focus survive, or a native conflict UI protects them.
3. Generated Query calls a write tool on mount: zero writes and explicit denial.
4. Stream disconnects after provider work or command commit: reconcile usage/idempotency; never blind retry.
5. Consumer chat requests founder/private memory data or changes workspace mid-request: zero cross-scope leakage.

## Seven roles and owned paths

Paths are proposed for NEW feature files. Existing hooks are identified from the inspected baseline and must be rechecked before modification. A may record a path mapping to fit current repository conventions; no two owners then edit the same mapped path.

| Role | Responsibility | Exclusive ownership |
|---|---|---|
| A | Coordinator / contracts / integration / release | `ui-contracts.ts`, `ui_contracts.py`, `tests/fixtures/agent_ui/contracts/`, shared generated-asset manifests, package/lockfiles, config, migrations, `vercel.json`, shared `http.py`/`service.py` hooks, CI wiring, release/coordination files |
| B | Provider runtime / real stream / billing | `agent_runtime_v2/ui_presenter.py`, `ui_stream.py`, `ui_metering.py`, presenter/stream/accounting tests; sends narrow shared-file patches to A |
| C | Renderer / component core / parser boundary | `web/src/features/agent/generative-ui/core/`, `components/primitives/`, `library.tsx`, `renderer.tsx`, `web/src/lib/agent-runtime/ui-parser/`, `web/scripts/generate-openui-assets.mjs`, parser/render tests |
| D | Authenticated queries / actions / projection | `agent_runtime_v2/ui_projection.py`, `ui_capabilities.py`, `ui_queries.py`, `ui_actions.py`, `ui_domain/`, `generative-ui/bridges/`, security/action/adapter tests |
| E | Rafii journey composition | `generative-ui/components/journeys/`, `generative-ui/journeys/`, `agent_runtime_v2/generated/journey-examples/`, journey integration tests/specs; requests domain adapters from D |
| F | Artifact storage / history / multi-surface / voice | `agent_runtime_v2/ui_store.py`, `generative-ui/state/`, `generative-ui/surfaces/`, stream client hook; bounded edits to `conversation-view.tsx`, `site-agent/answer.tsx`, founder answer and existing voice-result consumer |
| G | Independent acceptance / fault / security / performance | `tests/agent_ui_acceptance/`, `web/tests/agent-ui-e2e/`, `scripts/agent_ui_validation.sh`, acceptance results and evidence; reports fixes to the owning lane, does not compete for production files |

A does not write C's component bodies or D's domain adapters while coordinating. G may write independent test harnesses early, then reviews the integrated candidate. No reviewer-of-reviewer loop. Shared-file changes from B/C/D/F arrive as small patches/commits for A to apply and validate.

## Dependency graph and target cadence

R0 (A + C/B capability checks + G baseline) → contract/checkpoint SHA → R1/R2/R3/R4/R5 in parallel → R6 integrated regression and real journeys → R7 production release and activation.

**Today, October 8:** A resolves baseline/contracts, then dispatches the five implementation lanes and G's independent test harness. Integrate tested commits incrementally as they land; do not wait for five giant branches. **Tonight's target:** one candidate with all capabilities/journeys wired, tests running against real services. **October 9 target:** complete remaining acceptance, controlled deployment/activation and production receipt. These are work targets, not guaranteed completion times. If a gate fails, keep repairing the gate and all independent work; do not relabel a partial result or silently remove a journey.

Only contract approval/ownership and canonical baseline are serial blockers. Pure component tests, source inspection, fixtures, read-only adapter discovery and QA harness setup can start immediately. No duplicate research reports or separate planning phase per agent. Each agent reads this packet and its files, then implements.

## R0 — Establish a safe shared base and package capability proof

**Owner:** A; C/B supply focused compatibility evidence; G captures baseline.

**Inspect:** current PRs/branches, production branch, dirty main worktree, repo instructions, exact Python interpreter, current package locks, existing cloud jobs, auth/routing/DB/model configuration and real canonical deployment origin. Do not print secret values.

**Produces:** accepted base SHA, one integration worktree, per-role worktrees/branches, frozen contract hash, route/parser seam decision, component capability tests, role ownership register and baseline test results.

- [ ] Create isolated integration worktree from fresh `origin/consumer-saas`; preserve the main worktree and existing agent sessions.
- [ ] Add failing contract tests: legacy answer without artifact remains valid; UI ready cannot set business verified; cross-scope artifact is denied.
- [ ] C probes the pinned OpenUI APIs for composition, reactive state, Query, guarded Mutation/action, state hydration, incremental patch merge, parser errors and SSR/client boundary. A alone updates dependencies/lockfile after tests. Disable telemetry before install.
- [ ] B proves three separated chunks reach a deployed authenticated browser before the final chunk. Determine minimal Python/ASGI routing need from evidence.
- [ ] C proves the Node parser adapter can validate/merge without executing tools. A records exact internal route/auth mechanism and package versions.
- [ ] Resolve tests/runtime commands from existing scripts; no global Python installation or package-manager switch.
- [ ] Make the contract commit; all five lanes start from it. A records hashes and dispatches paths explicitly.

**Gate:** shared types and actual package features work, original client unaffected, no fabricated 'streaming works' claim. A must handle a dependency mismatch here rather than sending contradictory assumptions to five agents.

## R1 — Full presentation generation and accounting

**Owner:** B. **Consumes:** UiProjection, UiArtifactV1, UiEventV1, storage lease interface. **Produces:** `stream_presentation`, real provider events, correct attempt/usage accounting and bounded repair.

**Files:** B-owned Python modules above. **Tests:** `tests/test_agent_ui_presenter.py`, `test_agent_ui_stream.py`, `test_agent_ui_accounting.py`.

- [ ] Write failing tests for no business tools, denied egress route, missing price, combined turn budget, streamed final usage, timeout, cancel, exactly-one repair and no generation for plain text/reopen.
- [ ] Run the tests and capture genuine failures.
- [ ] Implement via existing router/credentials/ledger; do not change Manager output type or writer selection. Coalesce meaningful result projections instead of a call per tool event.
- [ ] Drain SDK stream/finalization, checkpoint source, reconcile known/unknown outcome, then emit ready only after validation and persistence.
- [ ] Test duplicate producer/reconnect with F's storage contract and injected network faults.
- [ ] Run unit tests and capped real-model fixtures permitted by existing budget; commit the owned files, report SHA/tests/interfaces to A.

## R2 — Native-looking reactive UI and incremental edit engine

**Owner:** C. **Consumes:** artifact/manifest contract and D bridge interfaces. **Produces:** renderer, grouped library, prompt export, official parser validation/merge and stable accessible controls.

**Tests:** `web/tests/agent-ui-renderer.test.cjs`, `agent-ui-parser.test.cjs`, `agent-ui-state.test.cjs` (or verified existing TS runner adapter).

- [ ] Write failing tests for unknown component, missing root, fragmented source, library/hash mismatch, Query/Mutation class confusion, state hydration, stable input focus and rejected stale patch.
- [ ] Implement primitive wrappers using existing Rafii design tokens. Build tool-bound charts/tables with source coverage and accessible alternatives; generated text cannot override native verified status.
- [ ] Implement official parser adapter and build-time grouped prompt assets; reject excessive source/tree/effects and detect contract drift.
- [ ] Connect reactive fields/read queries; integrate guarded user actions through D. Preserve input on stream/edit; explicit dirty-field protection before removal.
- [ ] Validate failed generation/repair fallbacks, keyboard/reduced-motion/mobile behavior and lazy bundle loading.
- [ ] Run tests/typecheck/lint, provide narrow dependency/route changes to A, commit owned files.

## R3 — Complete read/action bindings and tenant safeguards

**Owner:** D. **Consumes:** current domain APIs plus contract. **Produces:** projection, manifest resolver, query/action bridge and required service adapters for all journeys.

**Tests:** `tests/test_agent_ui_actions.py`, `test_agent_ui_queries.py`, `test_agent_ui_projection.py`, `tests/phase2/postgres_agent_ui_actions.py`.

- [ ] Write failing tests for viewer write, cross-tenant/founder access, expired/revoked capability, Query(writeName), untrusted external instruction, source-URL abuse, stale revision/digest and duplicate actions.
- [ ] Map real Library/voice/campaign/analytics/research/automation services for E. Build missing thin in-repo adapters rather than placeholder objects. Return coverage/unavailable explicitly when a real upstream lacks data.
- [ ] Enforce typed query bounds/debounce/cancel/refresh and action activation/effect classes on the server.
- [ ] Route edits/approvals through original service methods, keep audit/re-read and durable idempotency; add selection/result context events without keystroke logging.
- [ ] Run real PostgreSQL scenarios with owner/editor/viewer and separate tenant plus founder identity. Do not use service-role bypass to 'prove' RLS.
- [ ] Commit owned files; give A minimal shared route hooks and E exact adapter schemas/evidence.

## R4 — Ship every Rafii journey, not a component showcase

**Owner:** E. **Consumes:** C registry primitives, D adapter schemas, F surface/artifact integration. **Produces:** full J01–J09 behavior, prompt examples, real-service journey tests and final polish.

**Tests:** one named scenario per J01–J09 under `web/tests/agent-ui-journeys/`; backend service assertions where the UI writes/prepares.

- [ ] Write normal/empty/denied/partial/failure scenarios for each journey; define exact expected entity/result, not screenshot-only tests.
- [ ] Implement all domain wrappers/examples with capability-scoped composition. Do not hardcode fixture data into shipping components.
- [ ] Prove a multi-step request can move from Library selection → voice-aware draft → campaign/calendar proposal in the same conversation with retained references.
- [ ] Prove J06 charts have correct units/coverage and J09 never reaches consumer manifests. Confirm 'trained', 'saved', 'scheduled' are backed by service results.
- [ ] Prove an explicit UI follow-up edits an existing artifact without losing form/filter/selection state.
- [ ] Integrate progressively and commit tested slices; add a missing-data recovery state without counting it as normal-path success.

## R5 — Durable history, surfaces and voice continuity

**Owner:** F. **Consumes:** stream, parser, action/result contracts. **Produces:** storage/CAS, replay, state persistence and shared surface mounts.

**Tests:** `tests/phase2/postgres_agent_ui_store.py`, `web/tests/agent-ui-history.test.cjs`, `web/tests/agent-ui-surfaces.test.cjs`, voice integration tests.

- [ ] Write failing tests for two producers/tabs, source/state revision conflict, disconnect after checkpoint, revoked resource on reopen, old library version and workspace switch.
- [ ] Implement storage within existing message/run architecture and unique idempotency/lease guarantees. Propose only necessary additive DB changes to A; never apply production migrations from a worker lane.
- [ ] Implement fetch/SSE replay with fragmented UTF-8 handling, seq deduplication, cache invalidation, interrupted fallback and explicit UI-only retry.
- [ ] Mount the same artifact in full chat/panel/expanded/mobile and separately authorized founder surface; preserve existing native cards/approvals/navigation.
- [ ] Feed speakable summary and selected entity references into the existing browser voice path; retain phone regression coverage without live outbound calls.
- [ ] Verify reload does not invoke a model and switches clear private state; commit owned files and migration proposals.

## R6 — One integrated acceptance candidate

**Owner:** G; A integrates and routes repairs to B–F. **Produces:** populated acceptance matrix for exact SHA with reproducible evidence.

- [ ] Build the automated harness early, using every gate in `04-ACCEPTANCE.md`.
- [ ] Run contract/unit/DB tests, then deployed integration, all nine real journeys, real provider generation/edits, faults, existing agent/voice/library/credits regressions and responsive/accessibility tests.
- [ ] Verify actual iPhone Safari via available device/ORC; label emulation as emulation. Never claim phone validation from a desktop WebKit run.
- [ ] Measure source/render/interaction/cost behavior using the matrix's fixed sample plan; save raw metadata (no secrets).
- [ ] Review the final integrated diff, negative authorization cases and rollback; rerun affected tests after each repair. No serial reviewer cascade.
- [ ] Report pass/fail/blocked with SHA and evidence paths; A may not convert blocked into pass.

## R7 — Commit, PR, CI, production activation and receipt

**Owner:** A only. Follow `05-RELEASE-RUNBOOK.md`. Integrate latest production changes safely, rerun affected gates, open/update the feature PR, use existing protected merge workflow, verify deployed SHA, activate eligible production users after controlled smoke, and deliver evidence. No separate 'please ask me to deploy' stop.

## Worker status and handoff contract

Each role writes a small `evidence/lanes/<role>.json` in its own worktree: role, branch, base_sha, head_sha, owned_paths, completed_tasks, interfaces_produced, tests[{command,exit_code,artifact_path,sha}], blockers[{kind,exact_dependency,independent_work_remaining}], next_action. No secret values.

A is the only writer of shared coordination state. Agents announce ready commits/interfaces to A through the available orchestration/task channel; do not require James to ferry prompts or merge patches. When actual tooling cannot spawn another session, continue the highest-priority unblocked lane and leave explicit role instructions rather than falsely claiming agents were launched.

## Ready-to-use role instructions

**A:** You own this release end-to-end. Read the full packet, freeze contracts and worktree ownership, dispatch B–F with G testing independently, integrate tested commits continuously, resolve shared blockers, and complete the production runbook. Do not ask for another architecture/implementation decision that the packet already settles. Do not reduce scope or relax gates to meet the date.

**B:** Read START-HERE, spec, contracts and R1. Implement the real presentation/stream/ledger path in B-owned files with passing negative/cancel/retry tests; preserve Manager business authority. Send A tested commits and narrow shared-file patches. Never stop at a mocked stream.

**C:** Read START-HERE, spec, contracts and R2. Implement the official OpenUI-based library/renderer/parser and reactive/edit behavior with Rafii visuals, stable form state and no uncontrolled write provider. Own only C's paths; coordinate bridge interfaces with D and source/state with F. Send A verified commits.

**D:** Read START-HERE, spec, contracts and R3. Build real authorized query/action/data projections for every required journey. Prove cross-scope denial, safe proposal application, no writes on mount and exactly-once domain effects. Give E real schemas, not placeholders, and A tested shared-route patches.

**E:** Read START-HERE, spec, contracts and R4. Deliver all J01–J09 user journeys using C/D/F interfaces, grounded data, source/coverage states and polished responsive UX. No fixture-only feature, 'phase two', or three-demo substitute. Send tested incremental commits and identify genuine upstream blockers precisely.

**F:** Read START-HERE, spec, contracts and R5. Implement durable artifacts, CAS/history/replay and all surfaces/voice continuity without a second conversation system. Prove zero model calls on passive reopen, zero duplicated actions and zero cross-workspace state leakage. Send A any additive migration need for central allocation.

**G:** Read the packet and own independent test evidence for the integrated SHA. Test real provider, real DB, deployed stream, iPhone, security negatives, cost and rollback; report missing evidence as missing. Report defects to their owners; do not independently edit their production files or declare local preview production-ready.
