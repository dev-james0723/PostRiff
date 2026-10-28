-- Candidate only. Rollback of 142_discord_admission_retention_index.sql.
-- Dropping the index loses no data and changes no decision: the purge (SharedPostgresBudget.purge_settled) still works, by
-- scanning the table, which is slow on a large one. Every other statement uses its own indexes (migration 124).
BEGIN;
SET LOCAL lock_timeout='2s';
DROP INDEX IF EXISTS public.pr_discord_admission_purge;
COMMIT;
