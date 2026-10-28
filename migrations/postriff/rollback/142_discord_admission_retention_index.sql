-- Candidate only. Rollback of 142_discord_admission_retention_index.sql.
-- It is in this folder, not beside the migration, on purpose: scripts/postriff_migrate.py reads every [0-9][0-9][0-9]_*.sql of
-- migrations/postriff as a migration and refuses two with one number.
-- Dropping the index loses no data and changes no decision: the purge (SharedPostgresBudget.purge_settled) still works, by
-- scanning the table, which is slow on a large one. Every other statement uses its own indexes (migration 124).
BEGIN;
SET LOCAL lock_timeout='2s';
DROP INDEX IF EXISTS public.pr_discord_admission_purge;
COMMIT;
