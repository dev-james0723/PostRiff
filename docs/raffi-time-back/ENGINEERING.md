# Raffi Time Back / Time Saved — Engineering Spec

Date: 2026-09-25
Project: Raffi / formerly PostRiff
Canonical repository: dev-james0723/PostRiff
Canonical branch inspected: consumer-saas
Inspected HEAD: b5de49f98a0091c2d395748b771ca65e3c9f6d3a
Intended local project root: /Users/ouxianxing/Documents/James-Au-Studio
Intended repo destination after local access is available: docs/raffi-time-back/ENGINEERING.md

## 1. Product goal

Give each Raffi user a credible, inspectable estimate of how much human work time Raffi has returned to them across social-media workflows.

Primary UI language:
- Headline metric: **Time back**
- Supporting language: **Estimated time saved**
- Never describe an estimate as exact measured time.
- Never count AI activity merely because it happened. Count completed user outcomes.

Example:
> 8h 42m back this month
> 47 completed workflows
> Personalized estimate

The feature must remain useful even before enough personal calibration exists, while clearly distinguishing default estimates, personalized estimates, and directly measured workflow time.

## 2. Trust principles

1. Completed outcomes only.
   - Generating ten unused drafts saves 0 minutes.
   - A proactive suggestion saves 0 minutes until it leads to a supported completed outcome.
   - A failed or uncertain publish saves 0 publishing minutes.

2. No double counting.
   - Do not count both a parent campaign completion and all of its child drafting/adaptation/publishing work for the same human task.
   - Each atomic human task has one immutable ledger row and one dedupe key.

3. Provenance is first-class.
   Every savings row must state:
   - task kind
   - baseline duration
   - actual active user duration
   - saved duration
   - baseline source
   - calculator version
   - confidence label
   - source outcome / workflow reference
   - occurred_at

4. Missing is not zero.
   If activity time or a valid baseline cannot be established, do not invent savings.

5. User interaction telemetry is minimal.
   Do not record text, keystrokes, pointer coordinates, DOM paths, draft contents, prompts, or social content in the Time Back subsystem.

## 3. Calculation model

Canonical formula for one atomic task:

saved_seconds = max(0, baseline_seconds - active_user_seconds)

A task is eligible only when:
- a supported outcome is completed;
- the outcome belongs to the same workspace and beneficiary;
- a valid baseline exists;
- active time is known or the calculator explicitly marks the row as baseline-only estimate.

Public display should round conservatively:
- under 60 minutes: nearest whole minute
- 60 minutes or more: hours + minutes
- never show seconds

Internal values remain integer seconds.

### 3.1 Baseline precedence

Highest priority wins:

1. `user_override`
   - Explicit baseline chosen in Time Back settings.
   - Effective immediately.

2. `personalized`
   - Median of the user's latest confirmed calibration samples for that task kind.
   - Promote to personalized after at least 3 confirmed calibration samples.
   - Keep a bounded window, recommended latest 7 samples.

3. `raffi_default`
   - Versioned conservative default table.

Never silently rewrite historical ledger rows when a baseline changes. New baseline versions affect future rows only.

### 3.2 Initial conservative defaults

These are product defaults, not factual claims about every user:

| task_kind | unit | v1 default |
| --- | --- | ---: |
| draft | accepted draft | 8 min |
| adapt | each additional platform adaptation | 4 min |
| publish | each verified platform publication | 3 min |
| campaign_plan | activated campaign plan | 15 min |
| recurring_setup | activated recurring workflow | 10 min |

Do not add reporting until Raffi has a real reporting workflow with a completion boundary.

Defaults must live in a versioned server-side registry, not hard-coded separately in UI components.

## 4. Atomic task taxonomy for MVP

### A. `draft`
Count when a generated draft/variant reaches an accepted/approved state that the user actually uses in the workflow.

Do not count:
- raw generations
- abandoned drafts
- drafts rejected before use

### B. `adapt`
Count one task for each additional platform-specific adaptation that reaches accepted/approved use.

Do not count the original platform as an adaptation.

### C. `publish`
Count only when provider outcome becomes `verified`.

This repo already provides the correct server boundary:
- `src/postriff_phase2/hosted_worker.py`
- `PostgresWorker(..., on_verified=...)`
- the hook runs only after normalized provider state is `verified`

The current app wires:
`PostgresWorker(..., on_verified=service.audience.on_post_verified)`

Do not replace the audience hook. Compose verified hooks or introduce a small fan-out callback so both audience ingestion and Time Back recording run independently inside the existing verified transaction boundary.

### D. `campaign_plan`
Count when a campaign moves to a genuinely active state after required user input/approval.

Do not count a generated plan preview.

### E. `recurring_setup`
Count once when a recurring task is activated.

Do not count every future recurrence as another setup saving.
Future verified publishes may still earn their own `publish` task rows.

## 5. Beneficiary

Time Back is primarily a per-user metric, with an optional workspace total later.

Each ledger row must have:
- `workspace_id`
- `beneficiary_user_id`

Rules:
- direct user workflow -> acting principal
- human-approved publish -> approving principal
- owner standing authorization / recurring automation -> user who granted the current standing authority
- if beneficiary cannot be established safely -> do not create a user Time Back row

Do not assign savings to whichever worker process happened to execute the job.

## 6. Database design

Add an additive migration:
`migrations/postriff/023_time_savings.sql`

### 6.1 `public.pr_time_savings_ledger`

Suggested columns:

```sql
id uuid primary key default gen_random_uuid(),
workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
beneficiary_user_id uuid not null references public.pr_profiles(user_id),
task_kind text not null,
outcome_kind text not null,
outcome_ref text not null,
dedupe_key text not null check (dedupe_key ~ '^[0-9a-f]{64}$'),
baseline_seconds integer not null check (baseline_seconds >= 0),
active_seconds integer,
saved_seconds integer not null check (saved_seconds >= 0),
baseline_source text not null check (baseline_source in ('raffi_default','personalized','user_override')),
baseline_version text not null,
confidence text not null check (confidence in ('estimated','personalized','measured')),
calculator_version text not null,
occurred_at timestamptz not null,
created_at timestamptz not null default now(),
metadata jsonb not null default '{}',
unique(workspace_id, dedupe_key)
```

Constraints:
- `active_seconds` may be null for baseline-only estimates.
- If active_seconds is present, saved_seconds must equal `greatest(0, baseline_seconds - active_seconds)` at service validation level.
- Metadata is allowlisted and bounded. No content body, prompt, caption, token, email, or provider secret.

Indexes:
- `(workspace_id, beneficiary_user_id, occurred_at desc)`
- `(workspace_id, task_kind, occurred_at desc)`

### 6.2 `public.pr_time_savings_calibrations`

```sql
id uuid primary key default gen_random_uuid(),
workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
user_id uuid not null references public.pr_profiles(user_id),
task_kind text not null,
baseline_seconds integer not null check (baseline_seconds between 60 and 14400),
source text not null check (source in ('prompt','settings_override')),
created_at timestamptz not null default now()
```

Use median of recent confirmed `prompt` samples after >=3.
A settings override is handled as explicit current preference and may be modeled in this table or a separate compact preferences table if existing account-preference infrastructure is a cleaner fit.

### 6.3 `public.pr_active_work_sessions`

Store aggregate activity only.

```sql
id uuid primary key default gen_random_uuid(),
workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
user_id uuid not null references public.pr_profiles(user_id),
workflow_key text not null,
client_session_key text not null,
task_kind text not null,
active_seconds integer not null default 0 check (active_seconds >= 0),
sequence integer not null default 0 check (sequence >= 0),
started_at timestamptz not null,
last_active_at timestamptz not null,
closed_at timestamptz,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now(),
unique(workspace_id, user_id, client_session_key)
```

Heartbeat payload is cumulative:
`{ clientSessionKey, workflowKey, taskKind, activeSeconds, sequence }`

Server rule:
- accept only increasing sequence
- persist `max(existing.active_seconds, incoming.active_seconds)`
- retry is idempotent
- cap one session at a sane maximum, recommended 4 hours
- reject free-form workflow keys longer than the bounded format

RLS:
- authenticated user may read own Time Back rows in a workspace where membership is active
- client must not insert ledger outcome rows
- service_role writes ledger rows
- authenticated user may submit only own active-session aggregate and calibrations through authorized server endpoints
- keep existing project convention: force RLS and explicit grants

## 7. Active user time

Create a client helper:
`web/src/lib/time-back/active-time.ts`

Create a hook:
`useActiveWorkTimer({ workflowKey, taskKind, enabled })`

Rules:
- document must be visible
- user is considered active only while there has been keyboard, pointer, touch, scroll, or focus activity within the last 75 seconds
- do not record which key, pointer location, field, component, or text
- update an in-memory cumulative counter
- send bounded cumulative heartbeat at most every 30-60 seconds
- flush with keepalive on pagehide when possible
- stop when workflow completes or component unmounts
- background AI execution is not counted unless the user is still actively interacting with the workflow
- a tab left open while the user walks away must stop accumulating after the idle threshold

The server, not the browser, determines whether a completed outcome is eligible for a savings ledger row.

## 8. Server module

Add:
`src/postriff_phase2/time_savings.py`

Responsibilities:
- versioned default baseline registry
- calibration lookup and median calculation
- active-session aggregation
- beneficiary resolution
- outcome-to-task mapping
- immutable ledger insertion
- dedupe-key construction
- summary projection

Suggested public functions:

```python
record_outcome(cur, workspace_id, beneficiary_user_id, task_kind, outcome_kind, outcome_ref, workflow_key, occurred_at, metadata=None)
record_verified_publish(cur, workspace_id, job, occurred_at)
upsert_active_session(cur, workspace_id, principal, payload, now)
record_calibration(cur, workspace_id, principal, payload, now)
summary(cur, workspace_id, principal, now, range_key="30d")
```

### 8.1 Dedupe key

Server only:

`sha256(workspace_id + beneficiary_user_id + task_kind + outcome_kind + stable_outcome_ref + calculator_version)`

Never trust a client-provided dedupe key.

### 8.2 Publish integration

Current verified hook:
`src/postriff_phase2/hosted_worker.py`

Current app composition:
`src/postriff_phase2/hosted_app.py`
currently creates:
`PostgresWorker(database, social=social, on_verified=service.audience.on_post_verified)`

Change to a composed callback, e.g.:

```python
def on_verified(cur, workspace_id, job):
    service.audience.on_post_verified(cur, workspace_id, job)
    service.time_savings.record_verified_publish(cur, workspace_id, job, service.clock())
```

Failure isolation:
- Time Back failure must not downgrade a successfully verified publication.
- Log/record an operational diagnostic and allow a repair/rebuild path.
- Ledger insertion is idempotent, so reconciliation can safely retry.

If running both hooks in the exact transaction would make Time Back failure capable of rolling back publication bookkeeping, isolate the Time Back call with guarded error handling and a repairable event/outbox mechanism.

## 9. HTTP API

Follow the existing workspace route pattern in:
- `src/postriff_phase2/hosted_app.py`
- `src/postriff_phase2/hosted.py`
- `web/src/lib/api/client.ts`
- `web/src/lib/api/hooks.ts`

### GET `/api/workspaces/{workspaceId}/time-savings?range=30d`

Allowed ranges:
- `7d`
- `30d`
- `year`
- `all`

Response:

```json
{
  "range": "30d",
  "totalSavedSeconds": 31320,
  "completedTasks": 47,
  "basis": "personalized",
  "breakdown": [
    {"taskKind":"draft","savedSeconds":11880,"count":12},
    {"taskKind":"adapt","savedSeconds":8040,"count":18},
    {"taskKind":"publish","savedSeconds":5400,"count":15},
    {"taskKind":"campaign_plan","savedSeconds":4000,"count":2}
  ],
  "confidence": {
    "estimated": 7,
    "personalized": 34,
    "measured": 6
  },
  "calculatorVersion": "time-back-v1",
  "hasCalibrationPrompt": false
}
```

Do not return other users' per-user rows to ordinary members.

### POST `/api/workspaces/{workspaceId}/time-savings/activity`

Payload:
```json
{
  "clientSessionKey": "...",
  "workflowKey": "...",
  "taskKind": "draft",
  "activeSeconds": 126,
  "sequence": 4
}
```

### POST `/api/workspaces/{workspaceId}/time-savings/calibrations`

Payload:
```json
{
  "taskKind": "draft",
  "manualSeconds": 900,
  "source": "prompt"
}
```

Rate-limit calibration and activity writes.

## 10. Frontend types and hooks

Extend:
- `web/src/lib/api/types.ts`
- `web/src/lib/api/client.ts`
- `web/src/lib/api/hooks.ts`

Add:
- `TimeSavingsSummary`
- `TimeSavingsBreakdown`
- `useTimeSavings(range)`
- `useRecordActiveTime()`
- `useTimeSavingsCalibration()`

Keep Time Back query separate from social analytics.
Rationale: social analytics answers “how did posts perform?”; Time Back answers “what work did Raffi remove for this user?”

## 11. Overview UI

Existing overview headline strip currently shows:
1. Scheduled
2. Published · 30 days
3. Writing batches left
4. Channels connected

Recommended information architecture:
- replace **Writing batches left** in the headline strip with **Time back · 30 days**
- keep allowance/subscription information in Account/Billing
- surface low/empty allowance in `Needs your attention` when actionable

Target:
`web/src/features/overview/overview-view.tsx`

New stat:
- label: `Time back · 30 days`
- value: `8h 42m`
- hint: `47 completed workflows`
- optional badge: `Personalized` or `Estimated`
- if unavailable: literal `Unavailable`, not zero
- tooltip/info link: `How is this calculated?`

Do not create a fifth dense headline stat.

## 12. Detail UI

Do not mix Time Back directly into the existing post-performance table.

Add a compact Time Back section at the top of `/app/analytics`, visually separated from platform metrics, or a small subview reached from the Overview stat.

Recommended first release inside Analytics:
- date range selector: 7 days / 30 days / This year / All time
- large total time back
- completed task count
- breakdown by task kind
- provenance explanation
- calibration status
- no ROI dollar estimate in MVP

Copy examples:
- `Estimated with Raffi defaults`
- `Personalized from your answers`
- `Measured from your active Raffi workflow time`

“How this is calculated” must explain:
- only completed outcomes count
- inactive/background time is excluded
- estimates can be personalized
- rows are deduplicated
- platform-performance metrics are unrelated to this number

## 13. Calibration UX

Prompt only after a completed eligible workflow, never before the user receives value.

Example:
> Before Raffi, about how long would this usually take you?

Choices:
- 5 min
- 10 min
- 15 min
- 20 min
- 30 min
- 45 min
- 1 hour
- More than 1 hour

Rules:
- no more than one calibration prompt per task kind per 30 days unless user opens settings
- dismissible
- do not block publishing
- after 3 samples, switch label from `Estimated` to `Personalized`
- settings may provide explicit baseline overrides

## 14. Repair and historical backfill

Do not fabricate historical Time Back from all past drafts.

Permitted backfill:
- verified historical publishes can receive baseline-only `publish` rows if:
  - stable verified job identity exists
  - beneficiary can be derived deterministically
  - row is labeled `estimated`
  - a separate calculator/backfill version is recorded

Safer MVP recommendation:
- begin ledger accumulation from feature activation forward
- optionally backfill only verified publications after a later explicit product decision

Do not backfill drafting/adaptation time without reliable completion evidence.

## 15. Privacy and retention

Time Back data should be treated as user productivity metadata.

Never store:
- caption/post body
- prompts
- key values
- mouse coordinates
- DOM selector paths
- clipboard contents
- provider tokens
- browsing history outside Raffi

Store only aggregate active seconds and bounded workflow identifiers.

Account deletion must cascade or explicitly remove:
- Time Back ledger
- calibrations
- active work sessions

Exports should include Time Back summary/ledger only if product privacy policy says user productivity metadata belongs in account export.

## 16. Testing

### Unit tests
- default baseline lookup
- baseline precedence
- median personalized baseline
- saved time floor at zero
- dedupe key stable and scoped
- duplicate outcome inserts once
- active-session sequence replay is idempotent
- active time cap
- invalid task kind rejected
- unknown beneficiary creates no row
- suggestions alone create no row

### Publish tests
- `verified` publish -> exactly one publish savings row
- `published` but not verified -> zero rows
- `uncertain` -> zero rows
- worker retry after verified -> still one row
- audience hook failure does not create false savings
- Time Back failure does not make provider-verified publication appear failed

### Frontend tests
- visible active interaction increments
- background tab does not
- idle >75s does not
- activity heartbeat is cumulative
- Overview shows Unavailable on query failure
- Overview never renders fake zero for unavailable data
- correct badges: Estimated / Personalized / Measured
- keyboard and reduced-motion behavior remain intact

### Security tests
- member cannot submit activity for another user
- member cannot insert ledger outcome directly
- cross-workspace read denied
- arbitrary task kind/outcome ref rejected
- metadata allowlist strips free-form content
- calibration values bounded

## 17. Acceptance criteria

MVP is accepted only when all are true:

1. A provider-verified post produces exactly one publish Time Back ledger row.
2. Failed, uncertain, or merely generated work produces none.
3. Replaying the same verified outcome does not increase total time.
4. Active time excludes hidden tabs and idle periods.
5. Overview shows Time back for the signed-in user.
6. Breakdown totals reconcile exactly to the displayed total.
7. Every total can explain its baseline source.
8. A user with no data sees a truthful empty state, not 0h implying measurement.
9. RLS prevents cross-workspace/cross-user reads.
10. Existing publishing, audience ingestion, billing, analytics, and overview tests remain green.
11. No production migration or deployment happens without a separate explicit release instruction.

## 18. Recommended implementation order

WP1 — Data foundation
- migration 023
- baseline registry
- time_savings service
- server tests

WP2 — Verified publish
- compose existing `on_verified`
- immutable publish ledger row
- idempotency tests

WP3 — Read API + Overview
- summary endpoint
- TS types/client/hook
- replace headline `Writing batches left` with `Time back · 30 days`

WP4 — Active time
- minimal active timer
- aggregate heartbeat API
- attach to supported composer/adaptation/campaign workflows

WP5 — Draft/adapt/campaign outcome hooks
- only after exact completion boundaries are verified in current code
- no generic “AI call finished” counting

WP6 — Personal calibration
- calibration prompt
- baseline personalization
- provenance label

WP7 — Detail analytics UX
- range selector
- task breakdown
- explanation/provenance
- empty/error states

## 19. Non-goals for MVP

- dollar value / salary ROI
- team leaderboard
- “Raffi saved X% of your life” claims
- gamification streaks
- competitive benchmarks
- passive tracking outside Raffi
- raw event replay
- backfilling unverified draft work
- social performance attribution (“time saved caused more engagement”)
- production deployment

## 20. Repo-specific implementation targets

Expected files to add:
- `migrations/postriff/023_time_savings.sql`
- `src/postriff_phase2/time_savings.py`
- `web/src/lib/time-back/active-time.ts`
- focused tests beside existing Python/web test conventions

Expected files to modify:
- `src/postriff_phase2/hosted.py`
- `src/postriff_phase2/hosted_app.py`
- `src/postriff_phase2/hosted_worker.py` only if hook composition cannot be done entirely in hosted_app
- `web/src/lib/api/types.ts`
- `web/src/lib/api/client.ts`
- `web/src/lib/api/hooks.ts`
- `web/src/features/overview/overview-view.tsx`
- `web/src/features/analytics/analytics-view.tsx` or a dedicated child component
- relevant composer/adaptation/campaign surfaces after exact workflow-key boundaries are verified

Preserve:
- existing social analytics semantics
- `Unavailable` vs real zero
- current provider verification boundary
- audience `on_verified` behavior
- tenant/RLS patterns
- additive migration strategy
- reduced-motion and accessibility behavior
- current release branch state until a separate implementation/release workflow is authorized
