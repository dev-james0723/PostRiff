-- Rafii Discord P4 — PROPOSAL ONLY. NOT APPLIED TO ANY DATABASE.
-- Must be reviewed, numbered through the repository's migration process and
-- explicitly approved before execution. Keep Discord rate admission OFF meanwhile.
-- Required atomic coordination across workspaces and worker replicas.
BEGIN;

CREATE TABLE IF NOT EXISTS postriff_private.discord_rate_budgets (
    application_id text NOT NULL CHECK (application_id ~ '^[0-9]{5,25}$'),
    budget_key text NOT NULL CHECK (length(budget_key) BETWEEN 2 AND 128),
    limit_count integer NOT NULL CHECK (limit_count BETWEEN 1 AND 100000),
    remaining integer NOT NULL CHECK (remaining BETWEEN 0 AND 100000),
    window_seconds double precision NOT NULL CHECK (window_seconds >= 0.05 AND window_seconds <= 86400),
    reset_at timestamptz NOT NULL,
    blocked_until timestamptz,
    error_streak integer NOT NULL DEFAULT 0 CHECK (error_streak BETWEEN 0 AND 100000),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (application_id, budget_key)
);
CREATE INDEX IF NOT EXISTS discord_budget_expiry_idx
    ON postriff_private.discord_rate_budgets (updated_at);

CREATE TABLE IF NOT EXISTS postriff_private.discord_rate_routes (
    application_id text NOT NULL CHECK (application_id ~ '^[0-9]{5,25}$'),
    route_key text NOT NULL CHECK (length(route_key) BETWEEN 3 AND 500),
    bucket_id text NOT NULL CHECK (bucket_id ~ '^[A-Za-z0-9_-]{1,128}$'),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (application_id, route_key)
);

ALTER TABLE postriff_private.discord_rate_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff_private.discord_rate_budgets FORCE ROW LEVEL SECURITY;
ALTER TABLE postriff_private.discord_rate_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff_private.discord_rate_routes FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE postriff_private.discord_rate_budgets FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE postriff_private.discord_rate_routes FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA postriff_private TO service_role;
GRANT SELECT, INSERT, UPDATE ON postriff_private.discord_rate_budgets TO service_role;
GRANT SELECT, INSERT, UPDATE ON postriff_private.discord_rate_routes TO service_role;
CREATE POLICY discord_rate_service_only ON postriff_private.discord_rate_budgets
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY discord_route_service_only ON postriff_private.discord_rate_routes
    FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;

-- Review before rollout:
--   (1) Confirm canonical project and db role grants, RLS, CREATE privileges.
--   (2) Test shared application-scoped row locking across 8 worker processes
--       and multiple workspace users on disposable PostgreSQL 17.x.
--   (3) Verify that a missing coordinator fails closed before any Discord POST.
--   (4) Cap retention and purge aged route/budget rows only via reviewed
--       maintenance; no background deletion in P4.
--   (5) Activate P4 and require the P0/P1/P2/P3 gates before public publishing.
--
-- Rollback: pause all new Discord sends FIRST, keep authorizations, intents and
-- receipts, leave these rate rows until a reviewed safe migration. NEVER
-- restore the mutable-channel transport or ungated POSTs.
