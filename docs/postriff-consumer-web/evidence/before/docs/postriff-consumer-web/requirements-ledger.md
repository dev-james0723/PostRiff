# PostRiff Consumer Web — Requirements Ledger

**Status:** Living ledger. Created 2026-09-15 before any application change. Updated after each milestone.
**Governing spec:** `docs/superpowers/specs/2026-09-14-postriff-saas-product-architecture.md` (sections 1–32).
**Precedence when documents conflict:** latest explicit user decision → verified current code/receipts → consumer plan (`/Users/ouxianxing/Documents/Codex/2026-09-14/ok-just-to-continue-from-the/postriff-product-plan/`) for phase numbering/packaging → architecture spec for web requirements. See `decisions.md`.

**Status vocabulary:** `implemented_and_verified` · `partially_implemented` · `blocked_external_gate` · `deferred_by_first_sellable_scope` · `not_applicable_to_web`.
A row is `implemented_and_verified` only when the code exists **and** its validation ran in this round **and** the observed execution state matches the claim. Historical receipts are evidence of the past, not of now.

## Baseline (observed 2026-09-15, this round)

| Check | Result |
|---|---|
| Git history/diff | `validation_unavailable`: installed source has no `.git`. Standing rule: do not initialize Git (`docs/postriff-improvement-20260914/DECISIONS.md:27`). Substitute: `evidence/before/` backups + SHA-256 + `source-diff.patch` (see `decisions.md` D1). |
| Python suite | `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` → **152 pass / 0 fail** (Python 3.14.5 in venv; Vercel pin `.python-version` = 3.12 — D7). |
| Web | `npx tsc --noEmit` → 0; `npm test` → **75/75**; `vite build --config vite.alpha.config.ts` → OK (>500 kB chunk advisory). |
| Postgres suites (`tests/phase2/postgres_*.py`, `tests/phase3/postgres.py`) | `validation_unavailable` this pass: need disposable local PostgreSQL (`initdb`, port 55438/55439). Will run in Milestone A. |
| Live hosted validation (`scripts/validate_postriff_hosted_preview.py`) | Not run: network + Keychain; last recorded run 2026-09-14 was synthetic (`docs/postriff-phase-2/evidence/hosted-lifecycle-validation.jsonl`, `externalExecution:false`). Production state today = **unknown** (`DECISIONS.md:25`). |
| `.env.local` | Contains only `VERCEL_OIDC_TOKEN`; none of the 5 `.env.example` keys (`POSTRIFF_SUPABASE_URL`, `POSTRIFF_SUPABASE_PUBLISHABLE_KEY`, `POSTRIFF_DATABASE_URL`, `POSTRIFF_SUPABASE_SECRET_KEY`, `CRON_SECRET`). Hosted values live in Vercel project env; local `/api/health` → `configured:false`. |
| Running local processes | Legacy Studio `scripts/studio.py _serve/_worker`, `scripts/postriff_alpha.py`, 10 `studio/broker/*.mjs` brokers, xiaohongshu MCP. Not touched. |

## Section map (architecture spec §1–§32)

| § | Title | Status | Evidence / exact missing work |
|---|---|---|---|
| 1 | Executive decision | `not_applicable_to_web` (decision, adopted) | Cloud = paying runtime, Remote = founder alpha. Recorded D2. Hosted stack exists and is fail-closed: `src/postriff_phase2/hosted_worker.py:14-26` `DisabledHostedSocial`. |
| 2 | Product boundary | `not_applicable_to_web` (constraint, adopted) | Enforced by: no agent→publish path (`src/postriff_phase2/store.py:338` worker-only execution); hosted blocks `SERVER_ACTIONS` (`src/postriff_phase2/hosted.py:72-75`). |
| 3 | Commercial hypothesis | `not_applicable_to_web` | 0/5 interviews (`docs/postriff-phase-0/evidence-matrix.md:3`). Not manufacturable by this work. |
| 4 | Product modes | `not_applicable_to_web` (adopted) | Remote/Cloud split exists in labels (`studio/web/src/founder/FounderApp.tsx:706-710`). Bridge deferred (§19). |
| 5 | Customer IA (six destinations) | `partially_implemented` | Six labels exist as untyped array `FounderApp.tsx:35-42`; **8** nav items rendered (extra `Skills library`, `You` at `:738-755`); Analytics/Audience have no content branch (`:601`); no utility/account menu; sidebar not collapsible (mobile hamburger only `:769-776`); no mobile bottom nav; no global `Create`. **Work:** Milestone E. |
| 6 | Core journeys | `partially_implemented` | 6.1 signup real via Supabase PKCE/OTP (`studio/web/src/founder/hosted-auth.ts:27-47`) but Ideas is a 6-step wizard not a conversation (`FounderApp.tsx:603-666`). 6.2 hosted OAuth **missing** (`hosted.py:72-75` blocks `channel_add/verify`; only local broker grants exist). 6.3 downstream chain done (`store.py:247 build_manifest` → `:214 approve` → `:338 worker_step`), upstream agent/brief conversation missing. 6.4 Audience missing. 6.5 Bridge deferred. |
| 7 | Deployment topology | `partially_implemented` | Vercel web+api+cron (`vercel.json:3-41`), Supabase Auth/Postgres/Storage. **Missing:** agent worker pool, connector worker pool, event stream, isolated Python tool runner. Phase 3 hosted runtime not mounted (`hosted_app.py` has no `/api/device/*`). |
| 8 | Tenancy & workspace model | `partially_implemented` | Workspace scoping enforced in service (`hosted.py:27-36` membership JOIN `FOR UPDATE`) and DB RLS (`migrations/postriff/001_phase2.sql:25-45`, forced). Roles only `owner/editor/viewer` (`001_phase2.sql:14`) — **missing** `admin`, `approver`, separate `can_publish/can_reply/can_moderate/can_manage_connections`, invitations, encrypted provider tokens. Job claims re-verify membership (`hosted_worker.py:58-64`). Cross-tenant negative proof last run only on disposable PG. **Work:** Milestone A. |
| 9 | Auth & account security | `partially_implemented` | Server-side Supabase JWT verify (`provider_candidates.py:204-218`), session-id binding (`hosted_identity.py:16-26`), tombstones/revocations (`hosted_app.py:53-63`). **Missing:** step-up auth, MFA/passkey enrollment, login throttling, device/session list + remote logout, expiring non-replayable invitations, separate service identities. **Work:** Milestone A. |
| 10 | PostRiff Agent & runtime | `partially_implemented` (mostly missing) | No `AgentRuntime` interface; duck-typed `inspect/health/start/cancel/resume` (`src/postriff_phase3/adapters.py:45-54`). Only `fixture` route can start (`contracts.py:179`). Zero real model routes qualified (`docs/postriff-phase-3/runtime-qualification.md:8-11`). No conversation/message/attachment model; no SSE. Event vocabulary mismatch: three vocabularies exist, none = §10.4 (D4). Server-side production runtime identity: **blocked_external_gate** (needs account/key/cost authorization). **Work:** Milestone B. |
| 11 | Skills & Python tools | `partially_implemented` | Three neutral skill templates with `configurationSchema` (`src/postriff_alpha/templates.py:3-47`); hash-verified. **Missing:** versioned registry with release IDs/fixtures, structured tool schemas, isolated bounded runner (a Python function in the request process is not isolation), effect classes, cost gate. **Work:** Milestone B. |
| 12 | Channel integration | `partially_implemented` | Versioned capability records `contracts.py:11 LIMITS`; per-channel `identityVerified/capabilityVerified/scopes/evidenceSource` (`store.py:54`). **Missing:** hosted PostRiff-owned OAuth callback, PKCE, state binding, encrypted token custody, refresh/revoke/scope-drift, Direct/Assisted/Bridge/Unsupported taxonomy in UI (`Phase2.tsx:131` is two-way). Grants exist only in local owner broker (`docs/postriff-phase-2/connector-qualification.md:3-11`). Provider audit + app review: **blocked_external_gate**. **Work:** Milestone C. |
| 13 | Scheduling, publication, receipts | `partially_implemented` (strongest area) | Manifest `store.py:247-287` (binds workspace, actor, account, revisions, media hashes, alt, timing, preflight, expiry, idempotency); `invalidate()` `:315`; states `:17-18`; lease/fencing `hosted_worker.py:38-98`; `outcomes.py:8-27` fail-closed normalization; reconciliation-before-retry `store.py:357-415`; DST `fold` `contracts.py:30`. Verified locally 152/152 this round. **Missing:** tz database version field, multi-destination per schedule, list/calendar views (Calendar is a grouped list `Phase2.tsx:660-688`), hosted execution never observed with a real provider. **Work:** Milestone C. |
| 14 | Media & source storage | `partially_implemented` | Private bucket, workspace-scoped keys, immutable, signed URLs 60–600 s, Pillow full-decode (`hosted_storage.py:18-120`). **Missing:** renditions, transformation chain, rights/AI-label declaration, generated-media provenance, cost gate; image generation blocked by Vercel $1 budget minimum (`docs/postriff-phase-2/acceptance-results.md:45`). **Work:** Milestone B. |
| 15 | Analytics | `partially_implemented` | UI is Placeholder (`FounderApp.tsx:2739`). Comparison logic exists but non-tenant (`src/james_au_social/analytics.py:51-73`; flagged non-reusable schema at `docs/superpowers/specs/2026-09-14-postriff-admin-analytics-design.md:45`). **Work:** Milestone D — truthful limited state; `Unavailable` ≠ 0. |
| 16 | Audience | `deferred_by_first_sellable_scope` (truthful limited state required) | Not in §27 list. Nothing implemented (`FounderApp.tsx:2741`). Milestone D delivers a truthful limited surface only; manual reply only if a qualified connector supports it. |
| 17 | Billing & entitlements | `partially_implemented` | `pr_trials` real (14-day, 10 writing grants, no auto-convert; `001_phase2.sql:18-24`); Plan surface says "Billing unavailable" (`YouProfile.tsx:46`). **Missing:** subscription state, append-only usage ledger, reserve/settle, webhooks, quotas. Live charge: **blocked_external_gate**. Prices: proposed, not evidence (D3). **Work:** Milestone D. |
| 18 | Mobile & PWA | `partially_implemented` | Breakpoints 1180/980/700/360 (`founder.css:18-25`); 44 px partial (`runtime.css`). **Missing:** manifest, service worker, bottom nav, Chat/Edit/Preview segments, offline drafts, share-sheet, push. **Work:** Milestone E. |
| 19 | PostRiff Bridge | `deferred_by_first_sellable_scope` | Desktop pairing exists locally (`src/postriff_phase3/contracts.py:216-251`) but hosted service not mounted. Not required for core promise (§31.4). Web shows truthful "not configured" (`RuntimePanel.tsx:65`). |
| 20 | Data model | `partially_implemented` | Have: `pr_profiles/workspaces/memberships/trials` + 9 object tables (`001_phase2.sql`), `pr_account_tombstones/session_revocations` (002), `pr_runtime` (003, local-only). Workspace state is one JSON blob + CAS revision (`store.py:73-99`). **Missing:** conversations, messages, attachments, agent_runs/events, skill/tool_releases, invitations, subscriptions, usage_ledger, oauth_transactions, encrypted_credentials, metric_*, audience_*. Additive migrations planned per milestone. |
| 21 | API surface | `partially_implemented` | Single mutation channel `POST /api/workspaces/{id}/actions` (`hosted_app.py:192-201`) plus health/catalog/auth/media/export/account (`:148-213`). Not the §21 route surface. Server derives workspace from membership, never body (`hosted.py:29`). **Work:** additive routes per milestone, backward-compatible. |
| 22 | Security/privacy/compliance | `partially_implemented` | CSRF-style header + same-origin check (`hosted_app.py:136-146`), 12 MB body cap, security headers (`vercel.json:27-37`), cron HMAC (`:164-170`), no secrets in bundle (`scripts/verify_postriff_phase2.py:29-36`). **Missing:** rate limiting, audit_events table, privacy notice/rights declaration, retention classes, dependency scanning, malware scanning, backup-restore test on real cloud. Legal review: **blocked_external_gate**. |
| 23 | Reliability & operations | `partially_implemented` | Stateless request; lease/fencing; bounded tick (`hosted_worker.py:139-145`). **Missing:** customer-visible status, observability metrics, feature flags, dead-letter surface, sanitized logs policy, runbooks. **Work:** Milestone E. |
| 24 | Onboarding & support | `partially_implemented` | One-question profile intake (`AgentOnboarding.tsx`); guided type creation one-question (`content_types.py:387`). **Missing:** source-first activation (D10; current path forces mode→profile→source→runtime, `DECISIONS.md:40`), sample workspace, support paths, diagnostics consent. |
| 25 | Migration from local Studio | `partially_implemented` | Workspace + profile export zips exist (`hosted_app.py:202-209`). Import: missing. Provider tokens correctly not exported. |
| 26 | Delivery phases | `not_applicable_to_web` (numbering superseded) | Consumer plan controls: P3 runtime/desktop, P4 paid beta, P5 expansion (`…/postriff-product-plan/implementation-plan.md:94-96`). D2. This objective = P4 web scope. |
| 27 | First sellable scope | see per-bullet table below | — |
| 28 | Acceptance criteria | see per-bullet table below | — |
| 29 | Success metrics | `not_applicable_to_web` | Requires real cohorts; none exist. Metric contract must show n/d (`ROADMAP.md:23`). |
| 30 | Risks & mitigations | `not_applicable_to_web` (adopted) | Mitigations tracked via §8/§10/§13/§17 rows. |
| 31 | Decisions required | `partially_implemented` | 1–4 adopted (D2). 5 launch connectors: **blocked_external_gate** pending fresh provider audit (D9). 6 vendors: Vercel+Supabase us-east-1 in use (adopted by prior rounds). 7 runtime baseline: **blocked_external_gate**. 8 packaging: proposed (D3). 9 retention/legal: **blocked_external_gate**. 10 Analytics/Audience: transparent limited previews at first sale (D5). |
| 32 | Evidence notes | `not_applicable_to_web` | Provider docs must be re-verified at connector implementation (Milestone C audit). |

## §27 First sellable scope — per bullet

| Bullet | Status | Evidence / missing |
|---|---|---|
| Cloud signup and one workspace | `partially_implemented` | Supabase auth + `pr_bootstrap` (`001_phase2.sql:66-83`); last observed only synthetic 2026-09-14. Needs: re-observation, invitations, roles. |
| Ideas conversation with URL/document/media attachments | `partially_implemented` | Sources are text/URL entries with approve/retract (`domain.py:251-312`); no conversation, no document/media attachment on Ideas (image upload only in Scheduling `Phase2.tsx:290-303`). |
| Personalized catalog, starter packs, guided type creation, private/workspace templates | `implemented_and_verified` (local) | `src/postriff_phase2/content_types.py` full; `tests/test_postriff_content_types.py` 7/7 this round. Mobile verification pending (§28). |
| Relevant skill routing and controlled Python tools | `partially_implemented` | Static 3-template library; no routing, no isolated tool runner. |
| Canonical brief + ≥2 native variants | `partially_implemented` | Brief + variants with revisions/warnings/unknowns (`domain.py:52,509`); customized-variant protection tested. Generation is `FixtureAdapter` only. |
| Image upload/generation, alt text, preview | `partially_implemented` | Upload + alt + rights (`Phase2.tsx`); generation blocked (cost gate / provider minimum). |
| Smart preflight | `partially_implemented` | ~4 of 16 rules; split across `content_types.py:174` and `store.py:208-247`; no severity model or compact control. |
| Calendar and list scheduling | `partially_implemented` | List + grouped-by-date "Calendar" (`Phase2.tsx:634-688`); no real calendar grid. |
| Two or three verified direct integrations | `blocked_external_gate` | Candidates with any evidence: LinkedIn (local publish-capable), Instagram (local identity verified). Neither hosted. Fresh official audit + app review required (D9). |
| Exact approval + per-destination receipts | `implemented_and_verified` (local, single destination) | `store.py:214-227, 311, 405-417`; `tests/test_postriff_safety_regressions.py` 10/10. Hosted synthetic only. Multi-destination missing. |
| Basic post performance when provider data exists | `partially_implemented` | No ingestion; Milestone D truthful limited state. |
| Usage/credit meter, subscription state, export, disconnect, deletion | `partially_implemented` | Trial counters + export + delete-account (`hosted_app.py:202-212`) exist; usage ledger, subscription, disconnect (hosted) missing. |
| Responsive mobile PWA | `partially_implemented` | Responsive; not installable (no manifest/SW). |

## §28 Acceptance criteria — per bullet

| Criterion | Status | Evidence / missing |
|---|---|---|
| **Tenant isolation** | | |
| A cannot enumerate/fetch/infer/mutate/stream/export/schedule/execute B | `partially_implemented` | RLS + membership JOIN; negative tests only in `tests/phase2/postgres_safety.py` on disposable PG (not run this round). Stream/export/job/error paths untested. Milestone A. |
| Signed object URLs cannot cross workspace or outlive policy | `partially_implemented` | Workspace-prefixed keys + 60–600 s TTL (`hosted_storage.py:50-53,104`); cross-workspace negative test missing. |
| Agent retrieval/tool mounts contain only selected workspace inputs | `partially_implemented` | `snapshot()` ≤20 selected sources (`postriff_phase3/contracts.py:35-72`); no cloud agent yet. |
| Job claims revalidate workspace and authorization | `implemented_and_verified` (local) | `hosted_worker.py:58-64`; `test_postriff_safety_regressions.py` revoked-approver case. |
| Errors do not reveal cross-tenant existence | `partially_implemented` | 403 on non-member (`hosted.py:36`); needs 404-vs-403 uniformity test. |
| **AI, skills, tools** | | |
| No production model key in browser/mobile bundles | `implemented_and_verified` | `scripts/verify_postriff_phase2.py:29-36` bundle scan (last run 09-14); re-run in Milestone B. |
| Usage attributable to workspace/member/run/model/tool | `partially_implemented` | Trial allowance charged per accepted artifact (`worker.py:101-105`); no ledger. |
| Skills selectable/auto-routed with version recorded | `partially_implemented` | `skillRouteIds` in manifest (`store.py:262`); no routing. |
| Python tools execute in isolated bounded jobs | `partially_implemented` → likely `blocked_external_gate` | No isolation on Vercel request process; must block public tool route if unavailable (Milestone B decision). |
| Unknown skills/tools cannot be invoked by client IDs | `partially_implemented` | `contracts.py:75` closed event allowlist; tool IDs not yet a surface. |
| Paid generation respects credits before execution | `partially_implemented` | Managed route gated by `max_cost` + qualification_id (`adapters.py:146-154`); no real credits ledger. |
| No hidden reasoning/raw runtime event reaches client | `partially_implemented` | Allowlist exists; SSE surface missing. |
| **Channels** | | |
| Each connected account belongs to one workspace | `partially_implemented` | `pr_channels.workspace_id` FK; no hosted connection path yet. |
| OAuth state/callback/confirm/scopes/persist/refresh/revoke/capability tested | `partially_implemented` | Local broker only; hosted OAuth absent. Milestone C. |
| Public capabilities reflect production app-review state | `blocked_external_gate` | No app review submitted. |
| identity/publish/schedule/analytics/comments/reply/moderation distinct | `partially_implemented` | identity+capability distinct (`store.py:54`); others not modeled. |
| Unsupported/Bridge-only states clear | `partially_implemented` | Two-way display only. |
| **Scheduling & external actions** | | |
| Schedules survive API/worker restarts | `implemented_and_verified` (local) + hosted synthetic | `tests/test_postriff_phase2.py` crash/lease recovery; Vercel cron worker observed 09-14 synthetic. |
| Timezone/DST tested | `implemented_and_verified` (local) | `contracts.py:30 resolve_time` fold handling; tests in phase2 suite. tz-db version field missing. |
| Content/account/timing changes invalidate approval | `implemented_and_verified` (local) | `store.py:294-325`. |
| Duplicate prevention + uncertain reconciliation tested | `implemented_and_verified` (local) | `outcomes.py`; `test_postriff_safety_regressions.py` 10/10. |
| Partial success per destination | `partially_implemented` | Single destination per job today. |
| Agent text cannot invoke publish/reply/connect/billing/delete | `implemented_and_verified` (structural) | No agent→executor path exists; publish never in tool registry (`integration.py:7-20`). Must be re-proven once conversation exists. |
| **Billing** | | |
| Webhooks signature-verified, replay-safe, idempotent | `partially_implemented` | Nothing built; fixture adapter planned. Live: `blocked_external_gate`. |
| Entitlements cannot be self-increased | `implemented_and_verified` (local) | `pr_trials` service_role-only writes (`001_phase2.sql:43-45,61-63`). |
| Usage ledger reconciles with events | `partially_implemented` | Missing. |
| Downgrade/grace/cancel/failed-payment/export/delete consistent | `partially_implemented` | Export/delete exist; rest missing. |
| Billing success never changes readiness/approval | `implemented_and_verified` (structural) | `templates.py:43` "Plan is never a billing entitlement"; approval path independent of plan. |
| **Mobile/PWA** | | |
| Six destinations reachable at 390×844, no horizontal overflow | `partially_implemented` | Not observed this round; browser check in Milestone E. |
| Ideas: prompt/URL/doc/image attach, preview, approval on mobile | `partially_implemented` | Attachments missing. |
| Ideas: catalog, guided creation, proposal review, private-template reuse on mobile | `partially_implemented` | Components exist; mobile layout unverified. |
| Keyboard/SR/focus/contrast/reduced-motion pass | `partially_implemented` | Primitives present (`FounderApp.tsx:678,723,773,812`; `runtime.css` reduced-motion); no acceptance run. |
| Push requires permission, never executes | `partially_implemented` | Not built. |
| Cellular acceptance independent of founder LAN | `blocked_external_gate` | Requires observed real device on cellular. |
| **Bridge** (all 6 bullets) | `deferred_by_first_sellable_scope` | §19. |
| **Launch truthfulness** | | |
| Local preview ≠ cloud deployment | `implemented_and_verified` (practice) | Labels `FounderApp.tsx:706-710, 797-803`; this ledger. |
| Submission ≠ verified publication | `implemented_and_verified` (local) | `outcomes.py:8-27`. |
| Design/tests ≠ public launch | `implemented_and_verified` (practice) | Banner "Phase 0 incomplete · demand unvalidated" (`FounderApp.tsx:797-803`). |
| Catalogued connector ≠ production-ready | `partially_implemented` | Two-way display; taxonomy pending Milestone C. |
| Analytics freshness/missing visible | `partially_implemented` | No Analytics yet. |

## Milestone log

| Milestone | State | Receipt |
|---|---|---|
| Audit & ledger | complete 2026-09-15 | this file; `decisions.md` |
| A — secure SaaS foundation | not started | — |
| B — cloud Ideas & agent | not started | — |
| C — channels/scheduling/receipts | not started | — |
| D — billing/privacy/analytics/audience | not started | — |
| E — web experience/ops/launch acceptance | not started | — |
