# Shared contracts and lane ownership (integrator-owned)

These are frozen for the lanes. A lane that needs a change asks the integrator;
it does not edit these files.

## 1. FeatureReadiness

- Server: `src/postriff_phase2/feature_readiness.py`. Build with `blocker()` and
  `resolve()`. `validate()` before returning. Never hand-build the dict.
- Browser: `web/src/lib/feature-readiness.ts` (`parseReadiness`,
  `readinessOrUnverified`, `readinessCopy`) and
  `web/src/components/feature-readiness-notice.tsx`.
- Payload keys are exactly `state, reasonCodes, canRead, canRun,
  lastSuccessfulReadAt, nextStep`.
- Precedence: feature_disabled > unsupported > not_entitled > setup_required >
  temporarily_unavailable > insufficient_data > ready.
- `canRun` only decides which controls render. Every action still checks role,
  consent, rights, budget and revision on the server.
- An outage (`temporarily_unavailable`) offers only `retry`/`wait`; it never says
  reconnect.
- Consent/plan steps are owner steps: use `owner_step(..., role=role)` so
  non-owners get `contact_owner`. `connect` needs `manage_connections`
  (owner/admin or the can_manage_connections flag).
- Computing readiness must not call a provider or a model, and must not write.
- Reason codes are bounded identifiers (`^[a-z][a-z0-9_]{1,63}$`). Each
  feature keeps its own reason copy next to its UI.

### Where it is exposed (backward compatible)

- Growth: `GET /api/workspaces/{wid}/growth/catalog` adds `readiness:
  {studio, results, audience, patterns, measurement}`. Existing keys stay.
- Trends: `GET /api/workspaces/{wid}/coworker/status` adds a sibling key
  `trend_readiness`. `trend_beta` stays byte-compatible (its Zod schema is
  strict).

### Canonical reason codes

Growth: `growth_off`, `postmortem_off`, `audience_off`, `genome_off`,
`growth_schema_unavailable`, `analytics_connection_required`,
`analytics_permission_required`, `comments_permission_required`,
`measurement_enrollment_required`, `measurement_paused`,
`no_verified_publications`, `sample_below_minimum`, `growth_consent_required`,
`role_edit_required`, `growth_budget_unconfigured`, `growth_daily_limit`.

Trends: `trends_off`, `enrollment_required`, `self_serve_paused`,
`cohort_full`, `workspace_not_eligible`, `source_rights_pending`,
`provider_unavailable`, `provider_stale`, `coverage_gap`,
`no_projections_yet`, `lifecycle_stage_unqualified`,
`model_budget_unconfigured`, `role_edit_required`.

Add a new code only in the lane that owns the feature, and document it here in
the integration commit.

## 2. Admission versus egress

- `src/postriff_phase2/feature_enrollment.py` is the only writer of
  `public.pr_feature_enrollments` (migration `103_feature_enrollments.sql`).
  Features: `trend_radar`, `growth_measurement`.
- Env (new; absent means closed):
  - `RAFII_TREND_SELF_SERVE_ENABLED`, `RAFII_TREND_SELF_SERVE_MAX_WORKSPACES`
  - `POSTRIFF_METRIC_SELF_SERVE_ENABLED`, `POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES`
  - `RAFII_FEATURE_WORKSPACE_DENYLIST` (explicit UUIDs)
  - Turning a switch off stops new enrollments and un-admits enrolled
    workspaces at once (cohort rollback without a DB write). Legacy allowlists
    are untouched. The cap has no wildcard.
- Trends: `growth/trends/admission.py`
  - `admitted(cur, wid, values)`: legacy `RAFII_TREND_WORKSPACE_ALLOWLIST` OR
    active `trend_radar` enrollment. Use it for READ paths only (status,
    readiness, list/get/stored, watches, saved Ideas, nav).
  - `egress_allowed(wid, values)`: legacy allowlist only. Planner, worker,
    frontier, enrichment, generation, media and other provider/model work keep
    `config.workspace_allowed` / `egress_allowed`. Enrollment never creates
    ingestion, source policies or model budgets.
- Growth measurement: `MetricScheduler` admits env allowlist OR active
  `growth_measurement` enrollment (`feature_enrollment.admitted_workspaces` for
  the claim SQL). `POSTRIFF_METRIC_READS` stays the global kill switch, and every
  read still needs Direct analytics, exact native scopes and no pending purge.
- HTTP (interactive session only, origin guard, owner role):
  - Lane C: `GET|POST|DELETE /api/workspaces/{wid}/coworker/trends/enrollment`
  - Lane B: `GET|POST|DELETE /api/workspaces/{wid}/growth/measurement/enrollment`
  - Responses never reveal other workspaces' enrollment or cohort counts. Return
    only `eligible`, `reason` and the caller's own `status`.

### Shared trend corpus (BLOCKED on a rights review)

Ordinary workspaces can only see trend evidence once there is a reviewed
`shared:` scope policy with `share_across_workspaces=allow` and a contract row
whose operations include it. Until James approves that review, an enrolled
workspace gets `unsupported / source_rights_pending`, never a fake list. Lane C
grants `pr_trend_entitlements` on enrollment **only** when such a reviewed
shared policy exists (`store.grant_entitlement`), and revokes on leave.

## 3. Product decisions taken by the integrator

1. Contract binding: observations store the authorizing policy's contract row
   (renewed review row); the runtime protocol goes into provenance. No DDL.
2. Lifecycle tabs (Picking up / Breaking out / Active now): stage claims stay
   unqualified (`method_state` is forced to shadow). The tabs show
   `lifecycle_stage_unqualified` honestly; they do not invent stages.
3. Save to Ideas: Option A. A person can save a verified candidate
   opportunity with their own written angle (no model call, no spend). It binds
   the same opportunity revision, trust receipt, context digest and idempotency
   key. Model angles stay available where a reviewed budget already exists.
4. `/app/radar` (POSTRIFF_RADAR) keeps its own nav slot; Trends is shown only
   when its readiness is not `feature_disabled`.
5. Primary name everywhere: **Trends**.
6. Growth paid actions (review, audience analysis) stay `canRun=false /
   growth_budget_unconfigured` until James approves daily USD caps. Reading,
   measurement windows, consent and enrollment work without spend.
7. A late metric read is never stored as the window it missed (`window_missed`).

## 4. File ownership

| Owner | Files |
|---|---|
| Integrator (C0) | `feature_readiness.py`, `feature_enrollment.py`, `growth/trends/admission.py`, `web/src/lib/feature-readiness.ts`, `web/src/components/feature-readiness-notice.tsx`, `migrations/postriff/103_*`, `docs/postriff-migration-numbering.md`, `tests/phase2/rls.sql`, `docs/releases/growth-trends-20261008/*` (except LANE-*.md), `.github/workflows/*`, `.james-cloud-build.json`, `permissions.py`, `hosted_app.py` |
| Lane A (Trends data) | `growth/trends/{providers/*,quarantine,contracts,retry,source_health,jobs,worker,planner,frontier,frontier_runtime,store,pipeline,outbox,receipts,membership,metrics,forecast_admission,forecast_evaluation}.py` and their tests |
| Lane B (Growth) | `growth/*.py` (not `growth/trends/*` except `beta.py` horizon/tracking), `audience.py`, `insights.py`, `web/src/features/growth/*`, `web/src/lib/growth/*`, `tests/test_growth_*`, `tests/phase2/postgres_growth_*`, `postgres_audience.py`, `web/tests/growth-*` |
| Lane C (Trends product) | `growth/trends/{service,http,readiness,enrollment,opportunities,generation,notifications,opportunity_lab,exposure_events,methods}.py`, `growth/trends/beta.py::status` only, `coworker/service.py`, `web/src/features/trends/*`, `web/src/lib/coworker/*`, `web/src/app/app/trends/*`, `web/src/features/coworker/nav.ts`, `web/src/config/nav-config.ts`, `web/src/components/layout/*` (nav only), `web/src/features/pipeline/edit-draft-dialog.tsx`, `scripts/trend_browser.py`, `tests/phase2/seed_trend_browser.py`, `tests/test_trend_{service,http,generation,opportunities,notifications,beta}.py`, `web/tests/trend-*` |

`growth/trends/beta.py` is shared: lane B owns `horizon_state`/`tracking`,
lane C owns `status`. Keep edits to separate functions.
