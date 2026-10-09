# Growth Studio + Trends release baseline (T0)

Owner: integrator session (Claude Code, Opus 5.5). Worktree:
`.agent-worktrees/rafii-growth-trends-20261008`, branch
`claude/growth-trends-launch-20261008`, base `a522482e`.

All values below are point-in-time snapshots. Re-read before acting on them.

## Release identity (re-verified 2026-10-09T00:09Z)

| Item | Value | How verified |
|---|---|---|
| Repo / production branch | dev-james0723/PostRiff / consumer-saas | `git fetch` |
| origin/consumer-saas | `a522482ebeb69706f6a27c9e79f04a8bb7e76f3b` (PR #136 merge) | `git rev-parse` |
| Production deployment | `dpl_HE8oWvF5TMF7xo63rgS26NSVB3WR` READY, created 2026-10-08T23:05:49Z | Vercel `get_deployment rafii.io` |
| Production SHA | `a522482e` (same as origin) | deployment meta `githubCommitSha` |
| Aliases | rafii.io, www.rafii.io, postriff-phase2-private.vercel.app (+2 team aliases) | deployment `alias` |
| Note | `dpl_HPRcYu9…` (65b1ea83, created 23:07:15Z) is a later READY production build of the older SHA but does NOT own the aliases | Vercel list + alias read |
| Database | Supabase `buoyhkbodnhzngaotoel` (postriff-phase2-private, ACTIVE_HEALTHY, PG 17.6) | `get_project` |
| Latest migration file at base | `migrations/postriff/097_youtube_capacity.sql` | worktree listing |

The audit's older SHA (`65b1ea83`) is superseded: PR #136 (YouTube creator
publishing) is now live. It did not touch Growth/Trends pipeline files
(to be confirmed by lane review).

## Production data snapshot (read-only, 2026-10-09T00:09:51Z)

Queried inside `BEGIN TRANSACTION READ ONLY … ROLLBACK`; aggregates only.

| Quantity | Observed | Change vs audit (22:15–22:30Z) |
|---|---|---|
| pr_trend_projections | 0 | unchanged |
| pr_trend_trust_receipts | 0 | unchanged |
| pr_trend_input_manifests | 0 | new evidence |
| pr_trend_nodes / pr_trend_dependencies | 4,631 / 2,858 | new evidence |
| pr_trend_entitlements | 0 | unchanged |
| trend.ingest bluesky failed_terminal (provider_attempts_exhausted, 3/3 attempts) | 1,974; first 2026-10-05T13:50:19Z; last 2026-10-09T00:00:24Z | +42 in ~1.7h — failures still being created |
| trend.ingest bluesky succeeded | 875 (+4 with provider_transient); last created 2026-10-05T13:45:20Z | unchanged |
| Ingestion batches | 879; Σitem_count 1,337; last commit 2026-10-05T13:45:24.890629Z | unchanged |
| Observations (raw_post/create) | 344, all retained; latest received 2026-10-04T01:25:20Z | unchanged — stopped ~36h before batches stopped |
| Outbox trend.ingested | 879 (875 completeness=gap without marker_counts) | new evidence |
| Outbox trend.quarantined | 876; every entry reason `invalid_record`; Σaccepted 1,045, Σquarantined 876 | new evidence |
| Outbox trend.frontier.decision | 4,284 (576 `admitted/independent_sample` since 2026-10-08T00:15Z) | new evidence |
| Consumer trend.pipeline.v1 done | 6,039 = 879 + 876 + 4,284 (every event consumed) | consumer is live |
| Source health bluesky | unavailable / provider_transient, observed 2026-10-09T00:09:22Z | unchanged |
| Bluesky cursors | 2 partitions, generation 439/440, coverage `gap`, updated 2026-10-05T13:45Z | new evidence |
| Provider contracts | `jetstream-v2-json@3fa54fdb…` expired 2026-10-05T00:00Z; `stage2-full-20261003-v2` valid to 2026-11-03, not revoked | new evidence — expiry ≠ failure time (13:50Z), so not yet a proven cause |
| Trend scopes | one founder workspace scope + `shared:rafii`, both enabled | new evidence |
| Method versions | `trend.workspace_fit` qualification `shadow` | new evidence |
| pr_metric_reads | 1 row: instagram / backfill / history_import / done | unchanged |
| Analytics capability | Direct 1 (1 workspace); Unsupported 6 (3 workspaces) | unchanged |
| RLS | every pr_trend_*, pr_metric_reads, pr_channel_capabilities: rls=true, force_rls=true | metadata only, not a tenancy test |

## Browser baseline (from audit, not yet re-run)

- `/app/growth` (founder workspace, Owner): "Growth Studio is not enabled here yet."
- `/app/trends`: "This workspace is outside the Trend Beta".
- Both sidebar entries are visible.

Re-verification with a real session on rafii.io is part of T7 and is
UNVERIFIED until recorded in ACCEPTANCE.md.

## Workspace protection

- Canonical checkout `/Users/ouxianxing/Documents/James-Au-Studio` is dirty
  (other agents' social/channel work); read-only for this task.
- `/Users/ouxianxing/Documents/James-Au-Studio-growth` (`claude/growth-phase0`,
  efc62a1d) — read-only; no reset/clean/merge.
- ~100 other worktrees exist (OpenUI, Library, domain migration, YouTube,
  Threads, LinkedIn). Only this worktree is written to.
