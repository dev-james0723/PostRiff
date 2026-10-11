# Isolated YouTube workers

Execution state: **IMPLEMENTED / CLOUD SYNTHETIC CONCURRENCY PASS / NOT ACTIVATED**. No scheduler, additional paid runtime, Google quota or production throughput is provisioned by these entrypoints. `RELEASE-VALIDATION.json` and the coordinating release receipt retain source-bound test results separately from real provider acceptance.

The existing Vercel application provides three server-only `GET` routes:

| Route | Work performed |
| --- | --- |
| `/api/cron/youtube/uploads` | Only due YouTube upload/publication jobs; one existing bounded resumable step per lease |
| `/api/cron/youtube/identity` | Bounded distinct connected-channel checks and at most one authorized notification renewal |
| `/api/cron/youtube/planner` | Bounded distinct workspaces with exact active finite Autopilot plans; queues approved work only |

Each route checks the existing `CRON_SECRET` with constant-time comparison before initializing the application. Customer sessions and API tokens cannot authorize these routes. Unknown lanes/methods are rejected. Query parameters cannot alter budgets or select authority. Receipts contain counts, budget state and interventions, without credentials or channel/workspace identifiers. A successful worker request is not a verified publication.

Both `POSTRIFF_YOUTUBE_FLEET_ENABLED=1` and `POSTRIFF_YOUTUBE_CREATOR_ENABLED=1` are required. The planner also requires `POSTRIFF_YOUTUBE_AGENTIC_ENABLED=1`. Flags require the exact string `1`. Defaults are off. Existing public-upload/project evidence, independent OAuth grants, tenant membership, exact reviews, finite policy authority, queue limits and shared project admission still apply.

Server-only limits use `POSTRIFF_YOUTUBE_FLEET_{UPLOAD,IDENTITY,PLANNER}_{MAX_ITEMS,MAX_SECONDS,MAX_REQUESTS}`. Defaults are ten items, 20 seconds and 60 API admission attempts per invocation; ceilings are 25 items, 45 seconds and 200 attempts. Invalid limits fail closed. The elapsed budget stops new work and API admissions; it cannot interrupt an already running database/OAuth/network operation. OAuth token transport retains its own timeout. Request counts cover YouTube API admission hooks and a conservative notification-renewal slot, not a claim of complete network billing measurement.

With effective fleet ownership enabled, the shared `/api/cron/worker` excludes YouTube jobs and dispatch, while retaining YouTube data cleanup and every existing unrelated product task. When ownership is off its established dispatch behavior remains. Dedicated upload workers never claim or invalidate another platform's jobs or reviews. Do not enable ownership before the isolated schedulers are configured and validated; doing so alone would stop the shared cron from advancing YouTube jobs.

Upload claims retain the existing 45-second fenced lease, encrypted journal, immutable operation identity, tenant rotation and short shared claim lock. Identity checks atomically claim the existing five-minute authorization-check cache lease before I/O; concurrent stale selections cannot replace an unexpired lease. Planners claim a 120-second workspace lease in existing JSON state under a row lock. Only the exact lease and captured policy authorization generation may queue or pause a policy. Each activation mints a new generation, including same-owner reactivation; an expired worker cannot clear a replacement lease. Crashes leave the same recoverable work; transient verification or invocation-budget exhaustion defers a plan without revoking its finite authority. Selection excludes already attempted accounts/workspaces within the invocation.

No new migration is required beyond reviewed 089/097. Missing creator/capacity tables hold isolated lanes before provider work. Retention remains active after a feature rollback. The production cron configuration remains unchanged; these routes are not added to Vercel's schedule in this release.

## Activation and acceptance gates

1. Obtain required Google approvals, inspect actual quotas and reconcile current-day usage across all clients. Record fresh project/client-bound quota evidence. Obtain every affected account's actual consent.
2. Approve the storage plan and a concrete runtime/egress operating budget. The current 50 MB provider ceiling still prevents the 500 MiB forecast. Do not infer paid-runtime consent from an existing credential.
3. Review an existing-infrastructure scheduler configuration with staggered lane invocations and concurrency appropriate to measured latency. Configure authenticated scheduler delivery before switching ownership. Avoid synchronized claim-lock contention and duplicate shared/isolated schedulers.
4. Retain the source-bound cloud-only `postgres_youtube_fleet.py` acceptance (JCB `cfj6vg03bh`, exit 0): eight workers acquired 64 distinct claims in each lane, left 108 unrelated jobs untouched, and admitted exactly seven of 24 attempts against a shared seven-unit budget. Re-run affected checks after changes. The fixture covers concurrent mixed-platform upload claims, immutable operation recovery, stale completion rejection, identity/planner claim deduplication and one shared quota budget. Its transports are synthetic; real provider calls remain zero.
5. Execute account-owner-approved private upload/process/schedule/reschedule/cancel/Autopilot acceptance and sustained provider-backed load tests. Measure backlog age, accepted bytes/second, token/identity latency, API reservations, retries, lease expiry and fair tenant service. Size the fleet from these measurements, not the arithmetic minima in the quota forecast.
6. Enable the reviewed isolated schedulers and ownership together under controlled rollout. Verify each lane's receipts and actual Google state; keep public/agentic flags off until their independent gates pass. Pausing Autopilot does not cancel schedules already accepted by YouTube.

The 10,000-tenant serial query fixture and the concurrent fleet fixture cover separate database risks. Neither establishes sustainable production fleet capacity, independently authorized users, Google quota approval or a production SLA. Workspace capacity controls display Rafii's reservations, delays and configured limits while explicitly keeping Google's actual remaining allocation unknown.
