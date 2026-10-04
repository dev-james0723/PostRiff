# Ordinary paid Studio: Growth Studio and Trending

**Goal:** An ordinary paid Studio workspace can use each independently qualified Growth and Trending feature without Founder privileges or a Meta app role.
**Architecture:** Reuse existing `studio` / `assist` versioned billing terms. Introduce an opt-in, read-only customer admission policy shared by interactive Growth, metric collection, and Trending. Keep each provider's rights, OAuth review, source entitlements, model consent, reservation, chronology, cohort and revocation checks at its existing boundary. Fix independent gaps before requesting external activation.
**Tech Stack:** Python hosted service, PostgreSQL with forced RLS, Next.js 16 / React 19, Playwright Chromium and WebKit, existing Vercel Python cron.
**Spec:** Current user request; historical Stage 3 `acceptance-matrix.json` (139 rows, 5 PASS / 134 BLOCKED) is immutable historical evidence. `docs/design/studio-customer-growth/requirements.json` maps the full inventory to actual dependencies.

## Global constraints

- Base: `fc29af29482fb28e1acbd42a62700b0db7e51829`, fresh `codex/rafii-studio-product-finish-20261004` worktree. Preserve all existing checkouts and evidence, including PR105/106/107/120 and separate PR121.
- "Pro Studio" is a user label for existing Studio / Studio Assist, not a new plan. Commercial terms and provider payment stay explicitly approved; credentials and Founder exemptions are not proof of an ordinary paid customer.
- No paid dispatch, public post, permission expansion, review submission, env mutation or production deployment without its required specific approval/evidence. Local tests use synthetic providers and a private PostgreSQL instance; they prove code behavior only.
- Every matrix row persists. Separate code verification, production activation and data qualification. Unsupported is unavailable. Observations are native; late collection must not manufacture historic horizons. No reduced sample/shadow thresholds.
- Current production alias/project is canonical. Vercel env-list access returned 403; do not bypass this denial. A visible Meta dashboard and a real grant do not prove public advanced access.
- The user explicitly asked for execution after updating the plan: proceed inline without another plan approval. This supersedes the writing-plans handoff pause. Keep the SDD ledger and all requested acceptance artifacts.

## Review focus

1. Billing admission cannot accept trial, manual grants, fixture/test invoices, internal/Founder capacity or expired/revoked subscriptions.
2. Provider + connection + owned post identity stays tenant-bound; importing or mining Instagram cannot relabel Threads evidence.
3. Payment, membership, consent and provider revocation remain fenced at dispatch and completion, including retries.
4. Late counter snapshots and imported historical posts cannot qualify as missing 1h/24h/7d observations; existing minimum samples and shadow gates remain intact.
5. One unavailable lane cannot hide independent writing or source-qualified Trends features; browser claims must identify fixture vs real production, account role, engine and viewport.

## Execution tasks

### Task 1 — Preserve the inventory and define dependency-based acceptance

- [x] Add all 139 original IDs/functions with explicit dependency IDs, separate evidence axes and earliest-observation rules.
- [x] Add a validator that rejects missing/duplicate rows and false real PASS claims; write failing behavioral tests first.
- [x] Save fresh remote/production/grant/flag/review observations separately from the historical baseline.
- [x] Validate: `PYTHONPATH=src:tests python -m unittest test_product_acceptance -v`; validate the full inventory with the script.

Files: `docs/design/studio-customer-growth/requirements.json`, `scripts/rafii_product_acceptance.py`, `tests/test_product_acceptance.py`; private receipts under `.codex/studio-finish/`.

### Task 2 — Make Audience Miner consume qualified Instagram comments

- [x] Add PostgreSQL RED scenarios for mixed providers, owned-post identity, revoked/Unsupported capability, tombstones and another workspace.
- [x] Fix `ClosedLoop._comments` and truthful coverage. Preserve redaction, independent comment consent, model approval, limits and cluster invalidation.
- [x] Run private PostgreSQL Growth Phase 2 plus the new regression script, synthetic provider only.

Files: `src/postriff_phase2/growth/closed_loop.py`, `tests/phase2/postgres_studio_customer.py`.

### Task 3 — Reuse billing for ordinary customer admission and onboarding readiness

- [x] RED tests for current live paid Studio/Assist vs all disallowed states; no new plan or entitlement mutation.
- [x] Add shared customer qualification with explicit opt-in, useful catalog readiness and fail-closed missing schema.
- [x] Wire Growth, metric scheduler enumeration/retries and all Trends workspace fences to the same policy. Keep provider/source/AI permissions separate; recheck expiry/revocation before model/provider work and completion.
- [x] Validate real SQL billing/tenant/rollback scenarios and existing beta compatibility tests.

Files: `src/postriff_phase2/customer_access.py`, Growth service/metric scheduler, hosted wiring, Trends config/frontier, disposable PostgreSQL and unit tests.

### Task 4 — Preserve observation chronology and durable retry evidence

- [x] Identify existing schedule timing contract; write RED tests for overdue collection and historical import.
- [x] Persist unavailable/missed horizons explicitly without creating native readings at those horizons. Keep bounded retries, lease fencing, exact anchor, revocation and independent cron lanes.
- [x] Expose next due time and precise failure/evidence state through existing Growth windows and acceptance receipts.
- [x] Validate private metric/history PostgreSQL suites and unit schedule/performance tests.

Files: metric scheduler / performance / beta window projections; tests and collection runbook.

### Task 5 — Independent UI lanes and desktop/mobile WebKit acceptance

- [x] RED browser cases: Post Doctor/Genome usable when native Postmortem/Audience lanes are unavailable; entitlement readiness, owner/editor/read and second workspace.
- [x] Implement lane-specific UI without changing the selected visual system; preserve keyboard URL tabs, errors, caps and consent.
- [x] Run local browser/API fixtures with Chromium + WebKit, desktop + mobile, failure/expiry/revocation/purge/rollback and no external egress. Label fixture evidence precisely.
- [ ] Run affected web tests, typecheck, lint, copy audit and build; reuse successful checks for unchanged inputs.

Files: Growth UI/types, browser harness, affected workflows only if required for these tests.

### Task 6 — Integrate, review, and prepare external completion

- [ ] Run relevant full Python/PG/CI suites. Obtain fresh independent final code review as required by executing-plans; repair findings and rerun affected checks.
- [x] Prepare provider review scope/demo/data-deletion materials, ordinary paid acceptance scenario, explicit model/publication previews and rollback; leave unapproved external actions pending.
- [x] Recheck PR121, remote SHA and canonical deployment. Create a reviewable PR and attach it; preserve unrelated branches.
- [ ] Update all 139 evidence rows with actual results and earliest real acceptance time. Complete eligible authenticated production browser/API checks. Canonical deployment requires the user-specified gates; READY or Founder success cannot satisfy them.
- [ ] Once independent work is finished, list only precise remaining external approval/MFA/action blockers together. Checkpoint Token Pilot and include observed/estimated/unknown usage.

Files: `.codex/studio-finish/{HANDOFF.md,acceptance-matrix.json,acceptance-matrix.md,activation-preview.md}`, provider review runbook under `docs/design/studio-customer-growth/`.

## Source-bound progress receipt

Core implementation and all139 dependency mappings are complete locally.94 private PG scripts exit0,3751 pinned Python tests OK (370 skips covered separately where PostgreSQL applies),669 current web contracts PASS, current typecheck PASS and lint0 errors/3 existing warnings. Browser fixtures include 2-engine version-bound Calibration approval/restore and Genome prior-version restore with the unchanged daily cap. Independent final source review approved the repaired consent and fixture boundaries. Exact-source Linux CI is still required; no running CI or production qualification is declared passed.

Production and real-data portions of Task6 remain open: canonical env read403/schema unavailable, existing visible plans proposed, Founder-only expired fixture trial, public Meta/client mapping/review and source/method qualification, exact ordinary-account/MFA, approved paid dispatch/publication/import/share/notification effects and actual native horizons. `ACTIVATION.md` contains concrete materials. All139 rows retain these separate axes in the private matrix; S14/S15 only have real anonymous production401 proof. Local full Trends build rerun600-second timeout is preserved as validation_unavailable. TokenPilot checkpoint is unavailable because existing registry capacity256/1MiB is full; pending payload and durable handoff are saved without touching other task memory.

## Fresh remote integration

Remote consumer-saas and canonical production advanced to676397a205de065f6962fb6c3f6a9204681c31b4 (PR123) during execution. This candidate merges that commit without rewriting its prior three commits or touching PR121/other branches. Its native insights canary shares the customer billing policy even while metric cron is off; public review remains mandatory for ordinary customers. RED tests reproduced revocation/expiry during identity lookup before media dispatch; an additional current-rights check and grant/credential expiry fences suppress subsequent calls and late values.49 focused units pass; targeted PostgreSQL and exact-source Linux CI remain explicitly pending until results exist. History failures retain diagnostics; no runtime error is excluded from acceptance.
