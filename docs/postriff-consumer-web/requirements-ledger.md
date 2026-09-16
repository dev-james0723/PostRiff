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
| 5 | Customer IA (six destinations) | `implemented_and_verified` (local browser) | Milestone E: exactly six primary destinations; Skills/You/Usage/Export/Sign-out in the account (utility) menu; collapsible sidebar (persisted); mobile bottom nav Dashboard/Ideas/Scheduling/Audience + More (Channels/Analytics/utility); global `+ Create` → Ideas; workspace identity in the sidebar/header. Verified desktop + 375×812 on the dev harness (`receipts/milestone-e.md`). Infrastructure terms appear only in the DEV banner and the run log `details`. |
| 6 | Core journeys | `partially_implemented` | 6.1 signup real via Supabase PKCE/OTP (`studio/web/src/founder/hosted-auth.ts:27-47`) but Ideas is a 6-step wizard not a conversation (`FounderApp.tsx:603-666`). 6.2 hosted OAuth **missing** (`hosted.py:72-75` blocks `channel_add/verify`; only local broker grants exist). 6.3 downstream chain done (`store.py:247 build_manifest` → `:214 approve` → `:338 worker_step`), upstream agent/brief conversation missing. 6.4 Audience missing. 6.5 Bridge deferred. |
| 7 | Deployment topology | `partially_implemented` | Vercel web+api+cron (`vercel.json:3-41`), Supabase Auth/Postgres/Storage. **Missing:** agent worker pool, connector worker pool, event stream, isolated Python tool runner. Phase 3 hosted runtime not mounted (`hosted_app.py` has no `/api/device/*`). |
| 8 | Tenancy & workspace model | `implemented_and_verified` (local) / hosted apply **blocked_external_gate** | Milestone A (2026-09-15): five roles + four separate permissions (`migrations/postriff/004_consumer_web_tenancy.sql`, `src/postriff_phase2/permissions.py`); service-layer + RLS enforcement (`hosted.py` `transaction`/`command`); invitations single-use/hash-only; job claim re-authorizes approve authority (`hosted_worker.py`). Verified: `tests/phase2/postgres_isolation.py` 10/10 + `postgres_repository.py`/`postgres_safety.py` on disposable PG; unit 157/157. Foreign ≡ nonexistent (uniform 403). Encrypted provider tokens: Milestone C. Migration 004 not yet applied to hosted DB (receipt `receipts/milestone-a.md` gate 1). |
| 9 | Auth & account security | `partially_implemented` → mostly verified (local) | Milestone A: step-up (`verified_auth_time`, 600 s window) on invitations/member removal/session revoke/account delete; session inventory + remote revoke (`pr_sessions` + `pr_session_revocations`); login/verify throttling (`pr_auth_throttle`, 30/min per client, 60/min per user); expiring non-replayable invitations. Verified on disposable PG. **Still external:** MFA/passkey enrollment (Supabase Auth config), separate per-service machine identities (platform). |
| 10 | PostRiff Agent & runtime | `implemented_and_verified` (fixture runtime, local) / real model route **blocked_external_gate** | Milestone B: `AgentRuntime` interface + `FixtureAgentRuntime` (`src/postriff_phase2/agent_runtime.py`); §10.4 safe events only (DB CHECK in 005; `translate()` drops unknown kinds); persistent conversations/messages/attachments/runs/events with cursors + idempotency (`ideas.py`, 005); SSE replay with `Last-Event-ID`; `quick_start` source-first activation. Verified: unit 166/166, `tests/phase2/postgres_ideas.py` 8/8. Quick only; Standard/Deep honestly unavailable until a server-side production runtime identity is qualified (`receipts/milestone-b.md` gate 2). |
| 11 | Skills & Python tools | `partially_implemented` → registry verified; isolation **blocked** | Milestone B: versioned tool registry with schemas/effect/cost/bounds/release hashes (`tools.py`), fail-closed resolve, paid tools need credits (402), **public invoke blocked (503)** because no isolated runner exists on the platform — recorded, not hidden. Neutral templates unchanged. `pr_skill_releases`/`pr_tool_releases` tables (005). Missing: isolated bounded runner (platform gate), release-row seeding script, evaluation fixtures per skill. |
| 12 | Channel integration | `implemented_and_verified` (with provider doubles, local) / live providers **blocked_external_gate** | Milestone C: audit + selection (`connector-audit.md`, D12); PostRiff-owned HTTPS callback, state bound to workspace/member/provider/capability/redirect/expiry, PKCE, single-use, account confirmation, incremental scopes per capability, encrypted custody (D13), refresh/expiry/revocation/scope-drift, disconnect (`oauth.py`, 006); Direct/Assisted/Bridge/Unsupported per capability with evidence (`channels.py`); adapters for LinkedIn/Threads/Instagram (`providers.py`). Verified: `postgres_channels.py` 9/9, unit 182/182. **External:** provider apps, App Review/Business Verification, non-founder end-to-end tests; adapters are unmounted until credentialed + reviewed. UI card (Milestone E). |
| 13 | Scheduling, publication, receipts | `implemented_and_verified` (local; live provider **blocked_external_gate**) | Pre-existing manifest/lease/reconciliation model retained and re-verified (`postgres_safety.py`). Milestone C added: `HostedSocial` connector executor with provider-specific evidence rules (201+URN / container→publish; lookup match → `verified`; 401/403 `held`; 429 `scheduled`; else `uncertain`), `tzdb` in timing, `scheduleId` grouping for multi-destination approvals with per-destination state, official daily limits enforced at approval. **Missing:** real provider execution (never observed), list/calendar grid UI (E), LinkedIn image upload wiring. |
| 14 | Media & source storage | `partially_implemented` | Private bucket, workspace-scoped keys, immutable, signed URLs 60–600 s, Pillow full-decode (`hosted_storage.py:18-120`). **Missing:** renditions, transformation chain, rights/AI-label declaration, generated-media provenance, cost gate; image generation blocked by Vercel $1 budget minimum (`docs/postriff-phase-2/acceptance-results.md:45`). **Work:** Milestone B. |
| 15 | Analytics | `implemented_and_verified` (limited surface, local) / real data **blocked_external_gate** | Milestone D/E: tenant `pr_metric_definitions`/`pr_metric_observations` with native names, definition version, observed/ingested times, availability (CHECK: value iff available); ingestion hook on verified publication; `Unavailable` never 0; rates with n/d; cohort-compatible comparison; `< 3` insufficient. Screen shows explicit limited state and the rules. No real provider data yet. |
| 16 | Audience | `implemented_and_verified` (limited surface, local) / real data **blocked_external_gate** | Milestone D/E: `pr_audience_threads` + `pr_reply_drafts`; ingestion gated on Direct `comments_read`; manual or labelled AI-fixture draft; exact reply approval (account/thread/text digest) needing `can_reply` + Direct `reply`; separate submit/verify states. Bulk/auto reply and moderation explicitly unavailable. |
| 17 | Billing & entitlements | `implemented_and_verified` (fixture provider, local) / live provider **blocked_external_gate** | Milestone D: versioned `pr_plan_terms` (all `proposed`), `pr_subscriptions`, `pr_entitlements`, append-only `pr_usage_ledger` with reserve/settle/release, workspace + global stop-lines (candidate), replay-safe `pr_billing_events`, lifecycle (grace → cancelled keeps export). PG 8/8. `Usage & Plan` screen verified. No live charge; prices labelled proposed (D3). |
| 18 | Mobile & PWA | `implemented_and_verified` (local browser) / device install & cellular **blocked_external_gate** | Milestone E: manifest + icons + service worker (D15) + share target; bottom nav 4 + More; Chat/Edit/Preview segments; ≥44 px targets; offline snapshot cache; push handlers open-only. Verified at 375×812. Real-device install, push permission UI, cellular: not verified. |
| 19 | PostRiff Bridge | `deferred_by_first_sellable_scope` | Desktop pairing exists locally (`src/postriff_phase3/contracts.py:216-251`) but hosted service not mounted. Not required for core promise (§31.4). Web shows truthful "not configured" (`RuntimePanel.tsx:65`). |
| 20 | Data model | `partially_implemented` | Have: `pr_profiles/workspaces/memberships/trials` + 9 object tables (001), `pr_account_tombstones/session_revocations` (002), `pr_runtime` (003, local-only), **`pr_invitations/pr_audit_events/pr_sessions/pr_auth_throttle` + membership permissions (004, Milestone A)**. Workspace state is one JSON blob + CAS revision (`store.py:73-99`). **Missing:** conversations, messages, attachments, agent_runs/events, skill/tool_releases, subscriptions, usage_ledger, oauth_transactions, encrypted_credentials, metric_*, audience_*. Additive migrations planned per milestone. |
| 21 | API surface | `partially_implemented` | Single mutation channel `POST /api/workspaces/{id}/actions` plus health/catalog/auth/media/export/account. **Milestone A added** `GET /api/workspaces`, members (GET/PATCH/DELETE), invitations (GET/POST/DELETE + accept), sessions (GET/DELETE), audit (GET) — unit-tested via WSGI harness. Ideas/channels/analytics/audience/bridge routes pending their milestones. Server derives workspace from membership, never body. |
| 22 | Security/privacy/compliance | `partially_implemented` | CSRF-style header + same-origin check, 12 MB body cap, security headers, cron HMAC, no secrets in bundle. **Milestone A added:** immutable content-free `pr_audit_events` (auth, role, invitation, session events), verify/invite throttling, step-up. **Missing:** general per-route rate limiting, privacy notice/rights declaration, retention classes, dependency scanning, malware scanning, backup-restore test on real cloud. Legal review: **blocked_external_gate**. |
| 23 | Reliability & operations | `partially_implemented` | Stateless request; lease/fencing; bounded tick (`hosted_worker.py:139-145`). **Missing:** customer-visible status, observability metrics, feature flags, dead-letter surface, sanitized logs policy, runbooks. **Work:** Milestone E. |
| 24 | Onboarding & support | `partially_implemented` | One-question profile intake (`AgentOnboarding.tsx`); guided type creation one-question (`content_types.py:387`). **Milestone B added** source-first activation API: `POST …/ideas/quick-start` (thought/text/URL + `confirmUse` → preview, no channel, no profile step required) verified on PG. **Missing:** UI for it (Milestone E), sample workspace, support paths, diagnostics consent. |
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
| Ideas conversation with URL/document/media attachments | `implemented_and_verified` (API, local) / UI pending | Milestone B: persistent conversations + turns + attachments (`source` text/markdown ≤20 KB, existing private `asset`, `link`) with cursor replay (`ideas.py`; PG 8/8). Ideas UI (Chat/Edit/Preview) is Milestone E. |
| Personalized catalog, starter packs, guided type creation, private/workspace templates | `implemented_and_verified` (local) | `src/postriff_phase2/content_types.py` full; `tests/test_postriff_content_types.py` 7/7 this round. Mobile verification pending (§28). |
| Relevant skill routing and controlled Python tools | `partially_implemented` | Tool registry with schemas/effect/cost classes verified (`tools.py`); auto-routing of skills not built; isolated runner absent → public invoke blocked. |
| Canonical brief + ≥2 native variants | `implemented_and_verified` (fixture, local) | Milestone B: each turn yields ≥2 destination variants with `sourceIds`, `unknowns`, provenance (`runId`, `contextDigest`, `policyEpoch`); apply → reviewable variants (PG check 5). Real-model quality: `validation_unavailable`. |
| Image upload/generation, alt text, preview | `partially_implemented` | Upload + alt + rights (`Phase2.tsx`); native previews for text candidates (E); generation blocked (credits gate 402 + provider minimum). |
| Smart preflight | `partially_implemented` | Blocker/warning model bound to the manifest incl. source-policy rules; ~7 of 16 rules; compact severity control not built. |
| Calendar and list scheduling | `partially_implemented` | List + grouped-by-date "Calendar" (`Phase2.tsx`); multi-destination `scheduleId` in API; calendar grid UI not built. |
| Two or three verified direct integrations | code `implemented_and_verified` (doubles) / qualification **blocked_external_gate** | D12: LinkedIn member + Threads + Instagram implemented end-to-end in code (OAuth → custody → worker → reconcile). Each still needs its own provider app, review, and a non-founder end-to-end run before it can be called verified (§12.3). |
| Exact approval + per-destination receipts | `implemented_and_verified` (local) | Single and multi-destination (`approve_many` → `scheduleId`; per-destination events/attempts/verification). Hosted synthetic only. |
| Basic post performance when provider data exists | `implemented_and_verified` (mechanism, local) | Ingestion on verified publication + limited Analytics screen; real provider data pending a reviewed connector. |
| Usage/credit meter, subscription state, export, disconnect, deletion | `implemented_and_verified` (local) | `Usage & Plan` (entitlement, subscription state, ledger, budget), export with receipt, disconnect (C), deletion request + account delete. |
| Responsive mobile PWA | `implemented_and_verified` (local browser) | Installable manifest + SW; verified 375×812; real-device install not verified. |

## §28 Acceptance criteria — per bullet

| Criterion | Status | Evidence / missing |
|---|---|---|
| **Tenant isolation** | | |
| A cannot enumerate/fetch/infer/mutate/stream/export/schedule/execute B | `implemented_and_verified` (local, except stream) | Milestone A: `tests/phase2/postgres_isolation.py` proves enumerate (workspace list), fetch, mutate, export, media object path, members, audit, invitations, and job claim across two tenants on disposable PG; `postgres_safety.py` covers schedule/execute. **Stream:** n/a until Milestone B SSE. |
| Signed object URLs cannot cross workspace or outlive policy | `partially_implemented` | Workspace-prefixed keys + 60–600 s TTL; the media *route* is now proven tenant-bound (isolation check 2); signed-URL cross-workspace negative test still pending (needs storage stub with real signing). |
| Agent retrieval/tool mounts contain only selected workspace inputs | `implemented_and_verified` (local) | Milestone B: `project_context()` admits only explicitly selected, active, policy-permitted sources (≤20) of the caller's workspace; PG check 6 proves an `internal_reference` source's text never reaches events. |
| Job claims revalidate workspace and authorization | `implemented_and_verified` (local) | `hosted_worker.py` claim re-checks membership **and approve authority via the permission model**; isolation check 7 (flag revoked mid-job → `held`, zero attempts) + `postgres_safety.py`. |
| Errors do not reveal cross-tenant existence | `implemented_and_verified` (local) | Isolation check 2: identical `403 "Workspace unavailable."` for a foreign workspace and a random UUID across nine paths. |
| **AI, skills, tools** | | |
| No production model key in browser/mobile bundles | `implemented_and_verified` | `scripts/verify_postriff_phase2.py:29-36` bundle scan (last run 09-14); re-run in Milestone B. |
| Usage attributable to workspace/member/run/model/tool | `partially_implemented` | `pr_agent_runs` records workspace/actor/model/reasoning/usage per run (005); append-only USD ledger is Milestone D. |
| Skills selectable/auto-routed with version recorded | `partially_implemented` | `skillRouteIds` in manifest; run provenance records model; auto-routing not built. |
| Python tools execute in isolated bounded jobs | `blocked_external_gate` | No isolated runner on the platform; `tools.isolation_status()` reports it and public invoke returns 503 (unit-tested). |
| Unknown skills/tools cannot be invoked by client IDs | `implemented_and_verified` (local) | `tools.resolve()` fails closed on unknown id or version (unit-tested); event kinds CHECK-constrained. |
| Paid generation respects credits before execution | `partially_implemented` | `media.generate_image` refuses without a credit reservation (402, unit-tested); reservation ledger is Milestone D. |
| No hidden reasoning/raw runtime event reaches client | `implemented_and_verified` (local) | Only `SAFE_EVENTS` can be persisted (DB CHECK) or emitted (`safe_event`); `translate()` drops unknown adapter kinds (unit-tested). |
| **Channels** | | |
| Each connected account belongs to one workspace | `implemented_and_verified` (local) | `pr_encrypted_credentials` pk (workspace, connection); a second workspace needs its own explicit grant. PG channels check 4. |
| OAuth state/callback/confirm/scopes/persist/refresh/revoke/capability tested | `implemented_and_verified` (doubles) / real provider **blocked_external_gate** | PG channels 9/9 + unit adapter tests. |
| Public capabilities reflect production app-review state | `implemented_and_verified` (mechanism) / review itself **blocked_external_gate** | `production_reviewed` gates Direct; unreviewed → Assisted with evidence text; worker never mounts unreviewed providers. |
| identity/publish/schedule/analytics/comments/reply/moderation distinct | `implemented_and_verified` (local) | `pr_channel_capabilities` per capability (`channels.py`). |
| Unsupported/Bridge-only states clear | `implemented_and_verified` (API) / UI pending | Taxonomy + evidence in `GET …/channels`; card UI is Milestone E. |
| **Scheduling & external actions** | | |
| Schedules survive API/worker restarts | `implemented_and_verified` (local) + hosted synthetic | `tests/test_postriff_phase2.py` crash/lease recovery; Vercel cron worker observed 09-14 synthetic. |
| Timezone/DST tested | `implemented_and_verified` (local) | `contracts.py resolve_time` fold handling + `tzdb` provenance recorded in every manifest timing (Milestone C). |
| Content/account/timing changes invalidate approval | `implemented_and_verified` (local) | `store.py:294-325`. |
| Duplicate prevention + uncertain reconciliation tested | `implemented_and_verified` (local) | `outcomes.py`; `test_postriff_safety_regressions.py` 10/10. |
| Partial success per destination | `implemented_and_verified` (local) | `approve_many` → one `scheduleId`, one job per destination, independent states (unit-tested cancel of one leaves the other scheduled). |
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
| A — secure SaaS foundation | **complete locally 2026-09-15**; hosted apply of 004 = external gate | `receipts/milestone-a.md` |
| B — cloud Ideas & agent | **complete locally 2026-09-15** (fixture runtime); B7/B8/B9 partials carried; real model route + hosted 005 = external gates | `receipts/milestone-b.md` |
| C — channels/scheduling/receipts | **complete locally 2026-09-15** (provider doubles); provider apps/reviews/live runs = external gates | `receipts/milestone-c.md`, `connector-audit.md` |
| D — billing/privacy/analytics/audience | **complete locally 2026-09-16** (fixture payment provider); live provider + legal review + hosted 007 = external gates | `receipts/milestone-d.md` |
| E — web experience/ops/launch acceptance | **screens complete and browser-verified locally 2026-09-16**; ops surfaces partial; end-to-end cloud journey = external gate | `receipts/milestone-e.md` |
