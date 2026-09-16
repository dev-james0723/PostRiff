# Phase 2 acceptance results

**Outcome: Phase 2 incomplete.** The local foundation and complete synthetic Production lifecycle pass, including the one-minute remote worker; live image generation and live social-provider qualification remain incomplete.

## Commands and evidence

| Check | Result | Evidence |
|---|---|---|
| `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | pass · 146 tests | [phase2-python.txt](evidence/phase2-python.txt) |
| `cd studio/web && npm test` | pass · 72 tests | [frontend-tests.txt](evidence/frontend-tests.txt) |
| `cd studio/web && npm run typecheck` | pass | [typecheck.txt](evidence/typecheck.txt) |
| `cd studio/web && npx vite build --config vite.alpha.config.ts` | pass | [build.txt](evidence/build.txt) |
| `cd studio/web && npm run build:hosted` | pass | [hosted preparation results](evidence/hosted-preparation-results.json) |
| `vercel dev -L --listen 127.0.0.1:4330` and routed HTTP smoke | pass · Vite + Python services, API and SPA | [hosted preparation results](evidence/hosted-preparation-results.json) |
| Protected Vercel Preview, Supabase migration and two-user synthetic validation | pass · Ready, isolation/media/worker/cleanup verified | [hosted preparation results](evidence/hosted-preparation-results.json) |
| `psql -h 127.0.0.1 -p 55438 -d postgres -f tests/phase2/rls.sql` | pass · disposable schema/roles | [rls-results.txt](evidence/rls-results.txt) |
| Isolated Python: `tests/phase2/postgres_repository.py` | pass · actual PostgreSQL | [postgres-repository.json](evidence/postgres-repository.json) |
| Browser: visible flows, 1440px desktop and 390px mobile | pass for tested local flows | [browser-results.json](evidence/browser-results.json) |
| Content types, guided builder, proposal, private template, public APIs | pass · local deterministic | [increment receipt](content-type-template-results.md) |
| Scoped source, credential-pattern and link audit | pass within recorded scope | [local-audit.json](evidence/local-audit.json) |
| Git status/diff/history | validation_unavailable | Installed source tree has no `.git`; backup/hash/diff alternative recorded |

## Criterion ledger

“Pass” below means the specified local/deterministic boundary only. No row promotes a fixture to a real account, generated model image or real publication.

| Required criterion | Status | Evidence or precise limitation |
|---|---|---|
| Phase 0 truthfully recorded and Phase 2 specifically authorized | pass | Readiness report quotes exception; 0/5 full interviews unchanged; no contact |
| Phase 1 baseline before code | pass | 49 Python + 70 frontend tests, typecheck/build baseline logs |
| Four modes, new/experienced AI onboarding, voice review, generalized skills, editing/memory, persistence, export | pass | Original regressions retained in the 146-test Python suite |
| You graph/list use the same approved structured fields | pass | Existing tests plus browser node-ID parity; keyboard End reaches Account & Privacy |
| Two users/workspaces cannot read/mutate/export/delete/approve/schedule others' data | pass, local | Command-level identity/object-ID tests; real local RLS object-family checks |
| Actual hosted isolation and private bucket behavior | pass, synthetic Production | Two temporary users; own 200, cross-workspace 403, private media 200, cross-media 403, delete and cleanup pass |
| Browser role cannot run service-only operations | pass, local SQL | Bootstrap, direct CRUD, forged Storage writes denied |
| Successful/failed/cancelled/expired/replayed/wrong-account callback contracts | pass, fixture | Auth state/PKCE/proof/expiry tests; stable workspace and grant |
| Linking, collision, final recovery method, logout, expiry, recovery, deletion/export | pass, fixture | Python tests and visible link/export/logout/re-sign-in |
| Real hosted callback/session/refresh/unlink/delete route composition | hosted pass, synthetic | Refresh, same-workspace restore, private export, logout/refresh denial and account deletion/tombstone retention pass on Production; synthetic cleanup verified |
| Every available trial/plan includes all released neutral skills and four modes | pass, local | Studio/Assist; Business rejects trial; 3 neutral skills |
| Plan switch preserves 14-day expiry and shared nonrenewing 10-request grant | pass, local | Trial tests and browser plan switch; no billing |
| No founder-specific private skill/customer content in generated customer artifacts | pass, bounded scope | Neutral template hashes and bounded source/bundle audit; synthetic fixtures only |
| ArtBrief excludes private/hostile/sensitive raw values | pass | Profile and provider-candidate allowlist tests |
| Consent/refusal/cache/three-preview cap/selection/focal/replace/download/delete | pass, fixture | Tests, desktop/mobile selection, persisted selection after restart |
| Actual image-provider integration with private Storage and returned-rendition lifecycle | fail | Request adapter candidate exists; running application is procedural-only; full live adapter wiring unfinished |
| Authorized live-image cost gate | blocked by provider minimum | Vercel rejected the approved `$0.08` project budget before mutation because its minimum is `$1`; zero budgets and zero image requests confirmed in [external gate evidence](evidence/external-gate-attempt.json) |
| No model generation claimed from procedural assets | pass | Persistent fixture labels; zero model requests |
| Capability readiness cannot follow callback/login alone | pass, fixture | Identity/capability checks separately required; live providers remain unqualified |
| Identity/capability/media/source/language/voice/schedule preflight | pass, local contract | Scoped state validation, decoded JPEG and rights/alt tests; conservative versioned limits |
| Current official provider-limit qualification | pending external validation | LinkedIn docs checked; Meta full page retrieval failed; exact live API version/account not qualified |
| Content/account/speaker/media/operation/timing invalidates approval | pass, local | Immutable server-built manifests, no update endpoint, changed bindings tests, timing changes create new reviews |
| IANA/DST ambiguous/nonexistent/past times | pass | Fold choices and UTC conversion tests; visible original time/zone/UTC review |
| One multi-destination request produces separate atomic jobs | pass, local API | approve_many rollback/idempotency tests; UI currently reviews individual destinations |
| Duplicate requests/deliveries/claims are idempotent | pass, local | Stable manifest key, transactional enqueue, claim and fencing tests |
| Before/after submit/after acceptance crash recovery | pass, local | Saved leases, single attempt after recovery, separate-process worker test |
| Uncertain responses reconcile before retry | pass, fixture | Five bounded lookups; no blind resubmission; visible uncertain receipt |
| Rate limits/outages/malformed responses/denial/expiry/capability loss isolate destinations | pass, fixture | Scenario tests, three-attempt bound, verified/failed/uncertain browser outcomes |
| Cancel before claim and during submission are truthful | pass, fixture | Before-submit makes no request; during-submit remains uncertain/reconciles |
| Decode media rather than trusting filenames, retain immutable rendition hashes | pass | Magic signature plus full ffmpeg local decode or pinned Pillow hosted decode; source/rendition hash, dimensions/type/size/aspect/rights/alt checks |
| Trial expiry/disconnection holds future jobs; reconnect never silently releases | pass, local | Expiry and disconnect/reconnect tests |
| Browser refresh/process restart/stale edits preserve or reject state | pass, tested local flows | Re-sign-in restores three receipts/artwork; separate-process worker; stale revision tests. Unsubmitted scheduling form is not persisted. |
| PostgreSQL repository can exercise existing domain logic without SQLite | pass | Actual PostgreSQL command, membership, viewer and rollback test |
| Complete Phase 2 routing on hosted Postgres + private Storage | pass, synthetic Production | Vercel Services route to Python, Postgres and private Storage; two-user mutation and media lifecycle pass |
| Remotely deployed durable worker executes with browser closed/laptop offline | pass, synthetic Production | Five successive one-minute cron invocations on the final deployment returned HTTP 200; worker reported `externalExecution: false` and processed no live post |
| Live LinkedIn/Instagram OAuth, identity, capability, media, submit, publication and recovery | partial · local Instagram qualification pass | Instagram tester/callback accepted; local OAuth verified `@jamesaucreates` as Media Creator and read-only quota test returned `publish_ready`. LinkedIn remains locally identity/capability verified. Hosted token vault, grants, transport, publication and recovery remain incomplete; no social post was submitted |
| Credential/log/export isolation | pass, bounded local scope | No token/principal key in export; no access logs; source/bundle patterns and browser error check. Real provider logs are untested. |
| No unapproved external actions | pass | Approved Preview/Supabase foundation, Production credential scope and deployment executed; no outreach, paid request, customer-data upload, publication or billing |

## Visual evidence

[Channels](evidence/channels-desktop.png), [artwork desktop](evidence/artwork-selection-desktop.png), [artwork mobile](evidence/artwork-mobile-detail.png), [partial outcomes](evidence/partial-outcomes-desktop.png), [mobile Kanban](evidence/kanban-mobile.png). Browser test data was seeded as a fictional workshop after testing visible sign-in; it is not evidence that a real user completed onboarding. The original onboarding regression suite supplies that local functional coverage.

No performance/load, production security, compliance or customer-demand claim is made from these tests. Complete the failed integration rows before calling the local Phase 2 execution prompt fully implemented; complete authorized hosted/live gates before claiming Phase 2 complete.
