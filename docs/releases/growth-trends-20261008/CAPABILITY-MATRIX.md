# Capability matrix — /app/growth and /app/trends (T0, base a522482e)

Status vocabulary: SOURCE_PRESENT (code exists, not proven live), LIVE_BROKEN
(proven not working in production), LIVE_UNVERIFIED (should work, no live proof
yet), NOT_IMPLEMENTED, VERIFIED (live proof recorded in ACCEPTANCE.md).
Evidence: read-only production SQL 2026-10-09T00:09–00:20Z, Vercel env names
(values never read), runtime logs, source at a522482e. Lane columns show which
lane owns the repair. Statuses are updated in ACCEPTANCE.md as proof lands.

## Trends data chain (lane A)

| Capability | Backend / tables | Gates | T0 status | Root cause |
|---|---|---|---|---|
| Bluesky live_sample ingestion | `/api/cron/worker` → TrendWorker → providers/bluesky (Jetstream v2) → pr_trend_jobs/cursors/batches/observations | INTELLIGENCE+RADAR+PROVIDER_OPERATIONS, `bluesky:live_sample`, env allowlist (founder), policy `stage2-full-20261003-v2` (to 2026-11-03) | LIVE_BROKEN | A record-level validation failure after seq 26613419375 was quarantined, then `fold_frames` stopped without advancing; the inclusive cursor re-read the same frame ~876 times. At ~36h the cursor fell below the Jetstream lookback window (HTTP 400 CursorTooOld) and every job since 2026-10-05T13:50Z fails |
| Source circuit breaker | retry.fail_attempt, source_health | next_allowed_at | LIVE_BROKEN | Terminal failure writes `next_allowed_at = NULL`; 576 failing jobs/day keep spawning |
| Account deactivation → revoke_author | bluesky.normalize_frame, worker | v2 `#account` marker | SOURCE_PRESENT (broken by shape) | v2 nests `active/status` under `account`; code reads them flat |
| Observation → projection → receipt | pipeline._sources, trend_node_valid, store._statuses | contract row validity | LIVE_BROKEN | The 10-03 renewal stores the runtime protocol as the contract version; the pipeline join needs the policy's renewed row, so every event returns `no_current_sources` (manifests/projections/receipts = 0) |
| Pipeline outcome visibility | outbox.consume | — | LIVE_BROKEN | Suppression reasons are discarded; "done" hides "suppressed" |

## Trends product (lane C)

| Capability | Backend | Gates | T0 status | Notes |
|---|---|---|---|---|
| Page gate / admission | coworker status → trends/beta.status → config.workspace_allowed | INTELLIGENCE+RADAR+TRUST_RECEIPTS, env UUID allowlist | LIVE_BROKEN for ordinary users | No self-serve path; non-allowlisted workspaces see "outside the Trend Beta" |
| Shared corpus for other workspaces | pr_trend_scopes/entitlements, shared policy | `share_across_workspaces` rights | NOT_IMPLEMENTED (rights) | Policy denies sharing; 0 entitlements; needs James's rights review |
| Nav entry | coworker/nav.ts, nav-config.ts | global flags only | LIVE_BROKEN | Dead-end entry; replaces the separate /app/radar slot |
| For You | list view=for_you | read + admission | LIVE_UNVERIFIED | Not personalised; 0 projections |
| Picking up / Breaking out / Active now | list by `payload.stage` | STAGE_CLAIMS + production-qualified method | NOT_IMPLEMENTED | Pipeline writes stage=None; method is shadow-only → honest "unqualified" state needed |
| Niche / Platforms | list | — | NOT_IMPLEMENTED | No niche field; Platforms duplicates For You |
| Language & Slang / Whitespace / How this works | service.stored | MODEL_ENRICHMENT / WHITESPACE | LIVE_BROKEN | Zero rows → 503 "unavailable"/"claims removed"; no methodology producer |
| Filters | service.filters | enums | LIVE_BROKEN | `mastodon`, `mixed` → 400 |
| Pagination / exposure tokens | HMAC cursors | RAFII_TREND_CURSOR_SIGNING_KEY | LIVE_UNVERIFIED | Key presence by name to verify |
| Trust drawer | /{id}, /{id}/receipts/{rid} | TRUST_RECEIPTS (+GRAPH_GENOME, SATURATION) | LIVE_UNVERIFIED | Needs projections |
| Watch add/remove | /watches | edit + admission | LIVE_UNVERIFIED | Default stage_change never fires; no dedupe; no deep link |
| Angle generation | /opportunities/{id}/angles → trend.model_generation | MODEL_ENRICHMENT, reviewed policy, per-workspace budget rows, brand egress consent | LIVE_UNVERIFIED | No cost/consent confirm, no poll timeout, retry replays terminal job; budgets founder-only |
| Save to Ideas | /opportunities/{id}/accept | eligible/suggested state + angle | LIVE_BROKEN | Production candidates have no angles → unreachable without paid generation |
| Opportunity Lab | edit-draft-dialog → /opportunity-lab/runs | OPPORTUNITY_LAB | LIVE_UNVERIFIED | Silent stop after 120s |
| Forecast | /{id}/forecast | FORECASTS | LIVE_UNVERIFIED | Opt-in, honest Unknown |
| Multimodal | /media/* | MULTIMODAL | NOT_IMPLEMENTED (web) | No web caller |
| Methodology / calibration | /methodology, /calibration | — | NOT_IMPLEMENTED | No producer |

## Growth Studio (lane B)

| Capability | Backend | Gates | T0 status | Notes |
|---|---|---|---|---|
| Page shell / catalog | growth/catalog | POSTRIFF_GROWTH + sub-flags | LIVE_BROKEN | Flags absent in production → "not enabled here yet" |
| Growth schema | 037/038 tables | — | LIVE_BROKEN | Not applied in production; enabling flags alone would 500 |
| Results overview | growth/postmortems | POSTMORTEM | LIVE_BROKEN | Flags/tables; 0 Rafii publications |
| Result review (paid) | POST growth/postmortems | consent + caps + edit | LIVE_BROKEN | Caps absent → 503 growth_budget_unconfigured (needs spend approval) |
| Native reading scheduler | metric_reads.tick | POSTRIFF_METRIC_READS + env allowlist + Direct analytics | VERIFIED (runs, claimed 0) | Only founder Instagram has Direct analytics |
| Publish-linked t0/1h/24h/7d | metric_schedule.on_post_verified | verified job | LIVE_UNVERIFIED | No Rafii publication in production yet |
| History import backfill | history_import | POSTRIFF_HISTORY_IMPORT | VERIFIED (data) / NOT_IMPLEMENTED (UI) | 6 measured zeros not shown anywhere |
| Late read handling | metric_schedule.complete | — | LIVE_BROKEN (logic) | A late "1h" read is stored as 1h |
| Window state copy | beta.horizon_state, measurement-state.ts | — | SOURCE_PRESENT | Cancelled always shows "reconnect" |
| Retry after failed AI run | service._begin | requestKey | LIVE_BROKEN (logic) | Failed key can never be retried |
| Audience | growth/audience | AUDIENCE_MINER + consent + caps | LIVE_BROKEN | Threads-only, Threads not installed, comments ingested once |
| Patterns / Genome | overview + genome actions | GENOME, owner | SOURCE_PRESENT | Needs 50 comparable posts; truthful insufficient evidence |
| Measurement admission | POSTRIFF_METRIC_WORKSPACE_ALLOWLIST | env UUIDs | LIVE_BROKEN for ordinary users | Manual env edit per workspace |
| Ordinary-user native analytics | Meta/Threads providers | Meta Advanced Access, Threads credentials | BLOCKED (external) | Instagram works only for Meta app-role users |

## Cross-cutting (integrator)

| Capability | T0 status | Notes |
|---|---|---|
| FeatureReadiness contract | NOT_IMPLEMENTED → C0 `5038b16a` | Python + TS + notice |
| Self-serve enrollment | NOT_IMPLEMENTED → C0 `5038b16a` (migration 103) | Owner action, cap, kill switch, denylist |
| CI coverage of trend DSN tests / full Trends browser | Partial | Wrapper suites exist for some; full 8-tab browser not in CI |
| Production deploy path | VERIFIED | Merge to consumer-saas auto-deploys (~3 min) |
| Production DDL / env changes from this session | BLOCKED (permission) | Auto-mode classifier denies production-changing actions |
