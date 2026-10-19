# Rafii Functions / Cron Cost Optimization — 2026-10-19

**Status: Instrumented for diagnosis in an isolated branch; NOT merged or deployed.** No Production, cron schedule, OAuth, provider, database, customer data, or payment setting changed.

## Objective and current economic evidence

- Billing cycle 2026-10-13 to 2026-11-13, Vercel Pro. Team `team_PgXY5VdAYKcsv0RLoDPHscNq`, main `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`), additional staging `rafii-consumer-staging` (`prj_4bfvSc0AC6am9FdknFWcwNYgmcnN`).
- Up to the observed 2026-10-19 dashboard snapshot: Fluid Active CPU `postriff-phase2-private` **92.6% (20h 6m)**, staging **4.1% (53m 26s)**, D Festival **3.0% (39m 42s)**. Teamwide metered Fluid Active CPU approximately **US$2.76**, provisioned memory approximately **US$0.75**. Project percentages represent CPU usage, **not** a project-invoice USD breakdown.
- Historical metered Build CPU Minutes approximately US$16.46 in same cycle, the largest cost. Git auto-preview and duplicate builds are now off; don't undo them for this investigation.
- Live main `/api/cron/worker` scheduled once per minute with wall time about 7–9 seconds in short sample; staging also once per minute, about 1.2–1.4 seconds. Main and staging `READY` deployments were read through Vercel API. Cron telemetry has many Vercel-owned `/_vercel/ping` log lines: 66,369 log entries over 24h for main's cron path does **NOT** mean 66,369 billable invocations.
- Vercel Fluid **Active CPU is active code CPU time**, not whole request wall time while waiting on DB/network. Provisioned memory is charged for elapsed in-flight time. New phase timings measure *wall latency*, not directly invoice dollars; verify them against Vercel CPU/memory after release.

## Confirmed chronic failure, not yet root-caused

- Production Supabase canonical project `buoyhkbodnhzngaotoel` is ACTIVE_HEALTHY.
- Read-only aggregate snapshot of `public.pr_trend_jobs`: about **7,830 failed_terminal Bluesky Trend ingestion jobs** with reason `provider_attempts_exhausted`; from Oct 7–17 roughly **576 new terminal failures/day** and Oct 18 **574**. Last `succeeded` job was created Oct 5 at ~13:45 UTC. Counts may change; do not infer exact failed outbound calls or Vercel bill from them.
- Live `trend.job_failed` logs report `provider_or_commit_failure dispatched=True`, which conflates stream transport, protocol folding, usage ledger accounting and DB commit. Public official Jetstream v2 `/xrpc/network.bsky.jetstream.subscribeEvents` plus `xrpc.v1.json` are still documented. Do not assume the endpoint is bad, use unofficial APIs, or reboot the service.
- Main operational snapshot still reported `publicationUncertain=2`, `publicationHeld=1`, `costUnsettled=52` and `notificationsUnsent=3`; staging also had pending/held counts. Never silently disable either cron, change it to 5 minutes, or wipe the old queue to save pennies.

## Code changes (not behavioral rollout)

1. `src/postriff_phase2/hosted_app.py`: emit bounded `phaseMs` numbers (setup, publishingWorker, trends, operationsSnapshot, total) within the already-existing `cron.completed` log line. Use monotonic clock and report milliseconds only; do not log tenant data. Existing cron handler, retry, provider execution and response remain unchanged.
2. `src/postriff_phase2/growth/trends/worker.py`: enrich the **existing** `trend.job_failed` warning with static stage name (claim_preflight/provider_io/batch_validation/usage_accounting/database_commit) and exception **class name only**. Never emit exception text, response bodies, URL, raw headers, workspace/customer IDs, or tokens. No new extra log event, outbound request or job.
3. Two source files passed Python `ast.parse` against the exact GitHub branch snapshot using the user's Mac with no dependencies installed. This is **syntax and static contract only**, not end-to-end production acceptance or savings proof.

## Next acceptance gate — use next planned release, NOT an emergency paid Build

- Run the existing lightweight unit/integration/CI and affected Vercel hosted tests against exact pinned SHA with no additional paid services. Validate no changes to cron response structure, external posting, reminders, retention, and no secrets in logs.
- Include telemetry patch in the next normally authorized batch Release Candidate; do not build an extra Vercel Preview/Production merely for a diagnostic. Protect `rafii.io` and callbacks; stage production target with `--prod --skip-domain` as governed by the repo root `AGENTS.md`.
- Over at least 20 consecutive real scheduled ticks, compare p50/p95 total and phases. Cross-check Active CPU, in-flight memory, errors, timely publish and database load before authorizing an optimization to a particular phase.
- Classify Bluesky failure stage and exception class. If `provider_io`, reproduce in bounded official Jetstream API tests and repair the correct protocol/timeout or approved provider access. If `database_commit`, inspect transaction and ledger; preserve idempotency and unknown-billing semantics. Review any new provider retry deferral for per-workspace consent, max coverage gap, durable cursor and cancellation/rollback safety. Do not restart the 576/day terminal loop blindly.
- Assess whether *Staging* cron can be paused only after proving there is no real owed publication, purge, customer usage, auth callback dependency or current acceptance task. The measured 4.1% team CPU share sets a low savings ceiling.

## Rollback, limits and source pointers

- Revert only the two profiling source commits (or discard the branch) if local CI or test fails; instrumentation does not alter migrations or configs. Do not touch operational cron or production deployments to roll back telemetry.
- A "save" is not verified until before/after Vercel metered usage is measured for comparable traffic; don't extrapolate total $20 budget from a 7-second wall-clock Cron.
- Vercel cost docs: https://vercel.com/docs/functions/usage-and-pricing
- Official Jetstream v2 docs: https://github.com/bluesky-social/jetstream/blob/main/docs/README.md
- Vercel Usage: https://vercel.com/jamesau0723-6572s-projects/~/usage/vercel-functions-fluid-cpu-duration
- Other cost controls: `docs/operations/VERCEL-ON-DEMAND-COST-CONTROL-20261018.md` and root `AGENTS.md`.
