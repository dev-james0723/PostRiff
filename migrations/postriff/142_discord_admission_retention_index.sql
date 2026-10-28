-- CANDIDATE ONLY: written, NOT APPLIED anywhere. Retention of the shared request coordinator's admissions.
-- Canonical target: postriff-phase2-private / buoyhkbodnhzngaotoel (the owner applies it; see docs/w02/AS-BUILT.md).
--
-- pr_discord_request_admissions got a row per request and nothing deleted any (3.7 to 6.5 KB a request with its indexes: 8 to
-- 14 GB a day at the reviewed 25 a second). SharedPostgresBudget.purge_settled() now deletes, a bounded batch at a time, the
-- settled rows (observed, blocked) the coordinator can no longer count: those that are not publications after an hour, the
-- publications after a day. This partial index is how it finds them, oldest first, without a scan: one entry is added when
-- a row settles and removed with it, and it holds nothing else (the unresolved rows have their own index, migration 124).
--
-- Cost. A plain CREATE INDEX takes a SHARE lock on the table for the build (inserts and updates wait, reads do not): on the
-- near-empty table of the first deployment that is milliseconds, with a million rows a few seconds (the statement timeout
-- below is 30 s). On a table already large, run the CONCURRENTLY form outside a transaction instead:
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS pr_discord_admission_purge ON public.pr_discord_request_admissions
--       (is_publish, reserved_at) WHERE state IN ('observed','blocked');
-- The purge works without the index (it scans), so applying this file late loses nothing but speed.
--
-- Privilege. The purge needs DELETE on the table for the role the application connects as. Migrations 124 and 125 give
-- service_role SELECT, INSERT and UPDATE only, and this file changes no grant. If the application connects as a role
-- without DELETE the purge reports 'denied' (health payload: oldestSettledReadAgeSeconds keeps growing) and deletes nothing.
-- The owner decides whether to grant it; for service_role that would be
--   GRANT DELETE ON public.pr_discord_request_admissions TO service_role;
-- (its policy pr_discord_admission_service already allows every command).
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='30s';
CREATE INDEX IF NOT EXISTS pr_discord_admission_purge ON public.pr_discord_request_admissions(is_publish,reserved_at)
    WHERE state IN ('observed','blocked');
COMMIT;
