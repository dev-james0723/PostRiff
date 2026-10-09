# Rollback — Founder Connections attention queue

## What the change does

- Adds a read-only Founder route, `GET /connections/attention`, plus a Settings panel that calls it. Neither writes anything: no tables, no actions, no provider calls, no credential reads.
- Changes the hourly `connection_health` cron stage. It now overlays the YouTube vault facts (`refresh_supported`, refresh presence, access expiry, revoked; metadata only) before it classifies connections. Refreshable YouTube connections are no longer reported `expired` or `expiring`. `client_binding_missing` now maps to `blocked` instead of falling through to `ok`.
- No migration, flag, environment variable or provider configuration is involved.

## Rollback steps

1. Revert the merge commit of this branch, or deploy the previous compatible SHA. No schema or credential state needs to be undone.
2. The next hourly `connection_health` run (≤ 1 h) rewrites `public.pr_connection_health` with the old classification. Rows are fully recomputed each run, so no backfill or cleanup is needed.
3. The Settings panel disappears with the frontend revert. If only the backend is reverted, the panel shows "Connections unavailable" (a 503 from a missing slice), not a false all-clear.

## What rollback does not do

- It does not touch connections, grants, jobs, incidents, follow-ups or the AI ledger. This change never wrote to any of them.
- It does not revoke anything, delete posts or change provider consoles.

## Rehearsal status

NOT_RUN. No deploy has happened, so there is nothing to roll back yet. Rehearse on a preview after an approved deploy: open the route, revert, and confirm the next stage run.
