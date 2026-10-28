-- 140: the H-07 on-call engine's tables (src/rafii_control/oncall/store.py, PostgresStore). ADDITIVE AND NOT APPLIED.
-- Applying it anywhere shared is an owner decision (docs/ops/H07-EVIDENCE.md section 6); nothing in the application
-- writes these tables until the engine is wired into the founder cron behind RAFII_ONCALL_ENGINE_ENABLED.
--
-- Needs 049 (schema rafii_control, roles rafii_control_session and rafii_control_reader). Creates rafii_control_watchdog
-- if 066 has not (same attributes). Four tables, all environment-scoped through the rafii_control.environment GUC with
-- forced row-level security, like 055:
-- - oncall_incidents: one row per incident episode; at most one live (not resolved) row per dedupe key; optimistic version.
-- - oncall_events: the audit trail, append-only (no UPDATE, DELETE or TRUNCATE grant, and triggers that refuse them);
--   once_key makes "happens once" events (a step starting, a storm summary) idempotent.
-- - oncall_deliveries: one row per notification, claimed by its unique dedupe key BEFORE the provider is called, so two
--   engines never send the same notification; outcomes are codes, never provider text, addresses or numbers.
-- - oncall_heartbeat: the engine's own heartbeat, readable by rafii_control_watchdog only for the dead-man's switch.
-- Person ids are roster labels; destinations (addresses, numbers, push subscriptions) are never stored here.
-- Idempotent: every object is created only when missing; re-running changes nothing.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

DO $requirements$ BEGIN
  IF to_regnamespace('rafii_control') IS NULL
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_control_session')
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_control_reader') THEN
    RAISE EXCEPTION 'migration 140 needs 049: schema rafii_control and roles rafii_control_session, rafii_control_reader';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_control_watchdog') THEN
    CREATE ROLE rafii_control_watchdog NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END $requirements$;

CREATE TABLE IF NOT EXISTS rafii_control.oncall_incidents (
  id uuid PRIMARY KEY,
  environment text NOT NULL CHECK (environment IN ('local', 'staging', 'production')),
  dedupe_key text NOT NULL CHECK (dedupe_key ~ '^[A-Z][A-Z0-9_]{1,63}(:[A-Za-z0-9_.:-]{1,80})?$'),
  rule text NOT NULL CHECK (rule ~ '^[A-Z][A-Z0-9_]{1,63}$'),
  alert_class text CHECK (alert_class IS NULL OR alert_class ~ '^[A-Z_]{1,20}$'),
  severity text NOT NULL CHECK (severity IN ('page', 'warn', 'info')),
  priority text NOT NULL CHECK (priority IN ('P0', 'P1', 'P2')),
  state text NOT NULL CHECK (state IN ('open', 'acknowledged', 'resolved')),
  opened_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  chain_started_at timestamptz,
  suppressed_by text CHECK (suppressed_by IS NULL OR suppressed_by ~ '^(maintenance|inhibit:[A-Z][A-Z0-9_]{1,63})$'),
  forced_step integer NOT NULL DEFAULT -1 CHECK (forced_step >= -1),
  clear_count integer NOT NULL DEFAULT 0 CHECK (clear_count >= 0),
  seen_count integer NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
  notified text[] NOT NULL DEFAULT '{}' CHECK (cardinality(notified) <= 20),
  steps jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(steps) = 'object' AND pg_column_size(steps) <= 4096),
  message text NOT NULL DEFAULT '' CHECK (length(message) <= 500),
  acknowledged_at timestamptz,
  acknowledged_by text CHECK (acknowledged_by IS NULL OR acknowledged_by ~ '^[A-Za-z0-9_.:-]{1,80}$'),
  ack_channel text CHECK (ack_channel IS NULL OR ack_channel IN ('push', 'email', 'phone', 'dashboard')),
  resolved_at timestamptz,
  resolution text CHECK (resolution IS NULL OR resolution IN ('auto', 'manual')),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  CHECK ((state = 'resolved') = (resolved_at IS NOT NULL)),
  CHECK (state <> 'acknowledged' OR acknowledged_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS oncall_incidents_live_key ON rafii_control.oncall_incidents(environment, dedupe_key)
  WHERE state <> 'resolved';
CREATE INDEX IF NOT EXISTS oncall_incidents_recent ON rafii_control.oncall_incidents(environment, dedupe_key, opened_at DESC);
CREATE INDEX IF NOT EXISTS oncall_incidents_live ON rafii_control.oncall_incidents(environment, opened_at)
  WHERE state <> 'resolved';

CREATE TABLE IF NOT EXISTS rafii_control.oncall_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  environment text NOT NULL CHECK (environment IN ('local', 'staging', 'production')),
  incident_id uuid REFERENCES rafii_control.oncall_incidents(id),
  at timestamptz NOT NULL,
  kind text NOT NULL CHECK (kind ~ '^[a-z_]{2,40}$'),
  actor text CHECK (actor IS NULL OR actor ~ '^[A-Za-z0-9_.:-]{1,80}$'),
  once_key text CHECK (once_key IS NULL OR length(once_key) BETWEEN 1 AND 240),
  detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object' AND pg_column_size(detail) <= 4096)
);
CREATE UNIQUE INDEX IF NOT EXISTS oncall_events_once ON rafii_control.oncall_events(environment, once_key)
  WHERE once_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS oncall_events_incident ON rafii_control.oncall_events(environment, incident_id, id);

CREATE OR REPLACE FUNCTION rafii_control.oncall_events_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $append_only$
BEGIN
  RAISE EXCEPTION 'rafii_control.oncall_events is append-only';
END $append_only$;
DO $triggers$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'oncall_events_no_change'
                 AND tgrelid = 'rafii_control.oncall_events'::regclass) THEN
    CREATE TRIGGER oncall_events_no_change BEFORE UPDATE OR DELETE ON rafii_control.oncall_events
      FOR EACH ROW EXECUTE FUNCTION rafii_control.oncall_events_append_only();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'oncall_events_no_truncate'
                 AND tgrelid = 'rafii_control.oncall_events'::regclass) THEN
    CREATE TRIGGER oncall_events_no_truncate BEFORE TRUNCATE ON rafii_control.oncall_events
      FOR EACH STATEMENT EXECUTE FUNCTION rafii_control.oncall_events_append_only();
  END IF;
END $triggers$;

CREATE TABLE IF NOT EXISTS rafii_control.oncall_deliveries (
  environment text NOT NULL CHECK (environment IN ('local', 'staging', 'production')),
  dedupe_key text NOT NULL CHECK (length(dedupe_key) BETWEEN 1 AND 240),
  incident_id uuid REFERENCES rafii_control.oncall_incidents(id),
  person text NOT NULL CHECK (person ~ '^[A-Za-z0-9_.:-]{1,80}$'),
  channel text NOT NULL CHECK (channel IN ('push', 'email', 'phone')),
  kind text NOT NULL CHECK (kind IN ('page', 'record', 'summary')),
  step text CHECK (step IS NULL OR length(step) <= 60),
  status text NOT NULL CHECK (status IN ('pending', 'accepted', 'failed', 'unconfigured', 'refused')),
  claimed_at timestamptz NOT NULL,
  finished_at timestamptz,
  reference text CHECK (reference IS NULL OR length(reference) <= 200),
  reason text CHECK (reason IS NULL OR reason ~ '^[a-z0-9_:.-]{1,80}$'),
  PRIMARY KEY (environment, dedupe_key)
);
CREATE INDEX IF NOT EXISTS oncall_deliveries_recent ON rafii_control.oncall_deliveries(environment, person, channel, claimed_at DESC);
CREATE INDEX IF NOT EXISTS oncall_deliveries_status ON rafii_control.oncall_deliveries(environment, status, claimed_at DESC);

CREATE TABLE IF NOT EXISTS rafii_control.oncall_heartbeat (
  environment text PRIMARY KEY CHECK (environment IN ('local', 'staging', 'production')),
  at timestamptz NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object' AND pg_column_size(payload) <= 8192)
);

-- Forced RLS with the environment GUC (055 pattern); remove inherited defaults before the exact grants.
DO $access$ DECLARE n text; r text; BEGIN
  FOREACH n IN ARRAY ARRAY['oncall_incidents', 'oncall_events', 'oncall_deliveries', 'oncall_heartbeat'] LOOP
    EXECUTE format('ALTER TABLE rafii_control.%I ENABLE ROW LEVEL SECURITY', n);
    EXECUTE format('ALTER TABLE rafii_control.%I FORCE ROW LEVEL SECURITY', n);
    EXECUTE format('REVOKE ALL ON rafii_control.%I FROM PUBLIC', n);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role', 'rafii_control_reader', 'rafii_control_watchdog'] LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
        EXECUTE format('REVOKE ALL ON rafii_control.%I FROM %I', n, r);
      END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'rafii_control' AND tablename = n
                   AND policyname = 'oncall_environment_session') THEN
      EXECUTE format('CREATE POLICY oncall_environment_session ON rafii_control.%I FOR ALL TO rafii_control_session '
                     'USING (environment = current_setting(''rafii_control.environment'', true)) '
                     'WITH CHECK (environment = current_setting(''rafii_control.environment'', true))', n);
    END IF;
  END LOOP;
  FOREACH n IN ARRAY ARRAY['oncall_incidents', 'oncall_events'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'rafii_control' AND tablename = n
                   AND policyname = 'oncall_environment_reader') THEN
      EXECUTE format('CREATE POLICY oncall_environment_reader ON rafii_control.%I FOR SELECT TO rafii_control_reader '
                     'USING (environment = current_setting(''rafii_control.environment'', true))', n);
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'rafii_control' AND tablename = 'oncall_heartbeat'
                 AND policyname = 'oncall_heartbeat_watchdog') THEN
    CREATE POLICY oncall_heartbeat_watchdog ON rafii_control.oncall_heartbeat FOR SELECT TO rafii_control_watchdog
      USING (environment = current_setting('rafii_control.environment', true));
  END IF;
END $access$;
GRANT USAGE ON SCHEMA rafii_control TO rafii_control_session, rafii_control_reader, rafii_control_watchdog;
GRANT SELECT, INSERT, UPDATE ON rafii_control.oncall_incidents, rafii_control.oncall_deliveries, rafii_control.oncall_heartbeat
  TO rafii_control_session;
GRANT SELECT, INSERT ON rafii_control.oncall_events TO rafii_control_session;
GRANT SELECT ON rafii_control.oncall_incidents, rafii_control.oncall_events TO rafii_control_reader;
GRANT SELECT ON rafii_control.oncall_heartbeat TO rafii_control_watchdog;
REVOKE ALL ON FUNCTION rafii_control.oncall_events_append_only() FROM PUBLIC;
COMMIT;
