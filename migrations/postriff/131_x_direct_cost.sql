-- Durable estimated-spend journal for X. No provider financial cap claim.
BEGIN;
CREATE SCHEMA IF NOT EXISTS postriff;
CREATE TABLE IF NOT EXISTS postriff.x_cost_windows (
    app_key text NOT NULL,
    window_id text NOT NULL,
    policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    approval_ref text NOT NULL CHECK (length(approval_ref) BETWEEN 1 AND 240),
    approval_expires_at timestamptz NOT NULL,
    price_evidence_ref text NOT NULL CHECK (length(price_evidence_ref) BETWEEN 1 AND 240),
    price_evidence_expires_at timestamptz NOT NULL,
    estimated_micros bigint NOT NULL DEFAULT 0 CHECK (estimated_micros >= 0),
    request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (app_key, window_id)
);
CREATE TABLE IF NOT EXISTS postriff.x_cost_workspaces (
    app_key text NOT NULL,
    window_id text NOT NULL,
    workspace_id text NOT NULL CHECK (length(workspace_id) BETWEEN 1 AND 240),
    estimated_micros bigint NOT NULL DEFAULT 0 CHECK (estimated_micros >= 0),
    request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    PRIMARY KEY (app_key, window_id, workspace_id),
    FOREIGN KEY (app_key, window_id) REFERENCES postriff.x_cost_windows(app_key, window_id)
);
CREATE TABLE IF NOT EXISTS postriff.x_cost_reservations (
    request_id text PRIMARY KEY,
    app_key text NOT NULL,
    window_id text NOT NULL,
    workspace_id text NOT NULL,
    connection_id text NOT NULL CHECK (length(connection_id) BETWEEN 1 AND 240),
    operation text NOT NULL CHECK (length(operation) BETWEEN 1 AND 240),
    method text NOT NULL CHECK (method IN ('GET','POST','PUT','PATCH','DELETE')),
    endpoint text NOT NULL CHECK (length(endpoint) BETWEEN 1 AND 200),
    price_key text NOT NULL CHECK (length(price_key) BETWEEN 1 AND 80),
    estimated_units integer NOT NULL CHECK (estimated_units BETWEEN 1 AND 10000),
    estimated_micros bigint NOT NULL CHECK (estimated_micros > 0),
    policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (app_key, window_id, workspace_id)
        REFERENCES postriff.x_cost_workspaces(app_key, window_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS x_cost_reservations_window_idx
    ON postriff.x_cost_reservations (app_key, window_id, admitted_at);
CREATE INDEX IF NOT EXISTS x_cost_reservations_workspace_idx
    ON postriff.x_cost_reservations (app_key, window_id, workspace_id, admitted_at);
ALTER TABLE postriff.x_cost_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff.x_cost_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff.x_cost_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON postriff.x_cost_windows, postriff.x_cost_workspaces, postriff.x_cost_reservations FROM PUBLIC;
DO $roles$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON postriff.x_cost_windows, postriff.x_cost_workspaces, postriff.x_cost_reservations FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON postriff.x_cost_windows, postriff.x_cost_workspaces, postriff.x_cost_reservations FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT USAGE ON SCHEMA postriff TO service_role;
        GRANT SELECT, INSERT, UPDATE ON postriff.x_cost_windows, postriff.x_cost_workspaces TO service_role;
        GRANT SELECT, INSERT ON postriff.x_cost_reservations TO service_role;
    END IF;
END
$roles$;
COMMIT;
