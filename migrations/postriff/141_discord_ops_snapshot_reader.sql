-- 141: a read-only Discord operations snapshot for a dedicated monitoring login (H-07; independent review M9).
-- ADDITIVE AND NOT APPLIED. Applying it to Production is an owner decision (APPROVAL-PACKET-3 row, docs/ops/H07-EVIDENCE.md
-- section 6); nothing in the application calls it.
--
-- Why: GET /api/ops/discord/health accepts only CRON_SECRET, so a poller or watchdog would have to hold the secret that
-- also starts every cron route. This gives monitoring its own narrow path instead:
-- - public.pr_discord_ops_snapshot() returns the SQL twin of the health payload (docs/ops/discord-ops-snapshot.sql, the
--   same statement; a test keeps them identical): counts, ages, booleans and kinds, never an identifier or a token.
-- - It runs as SECURITY DEFINER with an empty search_path, owned by rafii_discord_ops_projection: NOLOGIN, no BYPASSRLS,
--   SELECT on the listed columns only (no ciphertext, no workspace state), through read-only policies of its own.
-- - rafii_discord_ops_reader (NOLOGIN) has EXECUTE on that one function and nothing else: no table SELECT.
-- - The login itself is a deployment step for the owner, not this file (a password is a secret):
--     CREATE ROLE rafii_discord_ops_monitor LOGIN PASSWORD '<generated, kept in the monitor's secret store>'
--       NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION IN ROLE rafii_discord_ops_reader;
--     ALTER ROLE rafii_discord_ops_monitor SET default_transaction_read_only = on;
--     ALTER ROLE rafii_discord_ops_monitor SET statement_timeout = '5s';
--   The monitor then runs: SELECT public.pr_discord_ops_snapshot();  and feeds the JSON to
--   python3 scripts/discord_ops_check.py evaluate - --phase <phase>
-- Idempotent: roles and policies are created only when missing; the function is replaced in place.
BEGIN;
SET LOCAL lock_timeout = '2s';
DO $roles$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_discord_ops_projection') THEN
    CREATE ROLE rafii_discord_ops_projection NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_discord_ops_reader') THEN
    CREATE ROLE rafii_discord_ops_reader NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END $roles$;
GRANT USAGE ON SCHEMA public TO rafii_discord_ops_projection, rafii_discord_ops_reader;
GRANT SELECT (workspace_id, next_at, last_claimed_at) ON public.pr_discord_worker_projection TO rafii_discord_ops_projection;
GRANT SELECT (request_seq, is_publish, state, status_code, rate_scope, route_key, reserved_at, sent_at, outcome_at, expires_at)
  ON public.pr_discord_request_admissions TO rafii_discord_ops_projection;
GRANT SELECT (kind, manual_hold, blocked_until, circuit_until, remaining, limit_count, window_seconds, reset_at, updated_at,
              policy_expires_at) ON public.pr_discord_rate_state TO rafii_discord_ops_projection;
GRANT SELECT (provider, provider_account_id, scopes) ON public.pr_encrypted_credentials TO rafii_discord_ops_projection;
GRANT SELECT (provider, scopes, consumed_at, expires_at, outcome) ON public.pr_oauth_transactions TO rafii_discord_ops_projection;
DO $policies$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['pr_discord_worker_projection', 'pr_discord_request_admissions', 'pr_discord_rate_state',
                           'pr_encrypted_credentials', 'pr_oauth_transactions'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = t
                   AND policyname = 'pr_discord_ops_projection_read') THEN
      EXECUTE format('CREATE POLICY pr_discord_ops_projection_read ON public.%I FOR SELECT TO rafii_discord_ops_projection USING (true)', t);
    END IF;
  END LOOP;
END $policies$;
CREATE OR REPLACE FUNCTION public.pr_discord_ops_snapshot() RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $snapshot$
WITH observed AS MATERIALIZED (SELECT clock_timestamp() AS at, extract(epoch FROM clock_timestamp())::double precision AS epoch),
queue AS (
    SELECT count(p.workspace_id) FILTER (WHERE p.next_at <= o.epoch) AS due,
           count(p.workspace_id) FILTER (WHERE p.next_at > o.epoch AND p.next_at <= o.epoch + 300) AS soon,
           count(p.workspace_id) FILTER (WHERE p.next_at IS NOT NULL) AS pending,
           coalesce(max(o.epoch - p.next_at) FILTER (WHERE p.next_at <= o.epoch), 0) AS lag,
           max(nullif(p.last_claimed_at, 0)) AS last_claim
    FROM observed o LEFT JOIN public.pr_discord_worker_projection p ON true
    GROUP BY o.epoch
), sample AS MATERIALIZED (
    SELECT is_publish, state, status_code, rate_scope, route_key, reserved_at, sent_at, outcome_at,
           coalesce(outcome_at, sent_at, reserved_at) AS last_at
    FROM public.pr_discord_request_admissions ORDER BY request_seq DESC LIMIT 20000
), ledger AS (
    SELECT count(*) AS sampled,
           extract(epoch FROM min(s.reserved_at))::double precision AS oldest,
           extract(epoch FROM max(s.reserved_at))::double precision AS newest,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds') AS creates,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'observed' AND s.status_code BETWEEN 200 AND 299) AS accepted,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'observed' AND s.status_code IN (403, 404)) AS customer,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'observed' AND s.status_code NOT BETWEEN 200 AND 299
                              AND s.status_code NOT IN (403, 404, 429)) AS system,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'observed' AND s.status_code = 429) AS limited,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'uncertain') AS uncertain,
           count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - interval '900 seconds'
                              AND s.state = 'blocked') AS blocked,
           count(*) FILTER (WHERE s.is_publish AND s.state IN ('reserved', 'sealed', 'sent')
                              AND s.last_at > o.at - interval '120 seconds') AS in_flight,
           count(*) FILTER (WHERE s.is_publish AND s.state = 'sent' AND s.last_at <= o.at - interval '120 seconds'
                              AND s.last_at > o.at - interval '900 seconds') AS stuck_new,
           count(*) FILTER (WHERE s.is_publish AND s.state = 'sent' AND s.last_at <= o.at - interval '120 seconds') AS stuck_all,
           count(*) FILTER (WHERE s.status_code = 429 AND s.last_at > o.at - interval '900 seconds') AS r429,
           count(*) FILTER (WHERE s.status_code = 429 AND s.rate_scope = 'global'
                              AND s.last_at > o.at - interval '900 seconds') AS r429_global,
           count(*) FILTER (WHERE s.last_at > o.at - interval '600 seconds'
                              AND (s.status_code IN (401, 403)
                                   OR (s.status_code = 429 AND coalesce(s.rate_scope, 'unknown') <> 'shared'))) AS invalid,
           count(*) FILTER (WHERE s.outcome_at > o.at - interval '300 seconds' AND s.status_code IS NOT NULL) AS responses,
           count(*) FILTER (WHERE s.outcome_at > o.at - interval '300 seconds' AND s.status_code >= 500) AS server_errors,
           count(*) FILTER (WHERE s.reserved_at > o.at - interval '60 seconds') AS admitted,
           count(*) FILTER (WHERE NOT s.is_publish AND s.state = 'uncertain'
                              AND s.last_at > o.at - interval '900 seconds') AS uncertain_reads,
           count(*) FILTER (WHERE s.status_code = 401 AND s.last_at > o.at - interval '900 seconds') AS unauthorized,
           extract(epoch FROM max(s.outcome_at) FILTER (WHERE s.is_publish AND s.state = 'observed'
                                                          AND s.status_code BETWEEN 200 AND 299))::double precision AS last_accepted,
           -- the reconciliation read-back route, stored as the SHA-256 of its template (ops.READBACK_ROUTE_KEY)
           extract(epoch FROM max(s.outcome_at) FILTER (WHERE s.route_key = encode(sha256(convert_to('GET:/channels/{id}/messages/{id}', 'UTF8')), 'hex')
                                                          AND s.state = 'observed' AND s.status_code BETWEEN 200 AND 299))::double precision AS last_readback
    FROM sample s CROSS JOIN observed o
), unresolved AS (
    SELECT (SELECT count(*) FROM public.pr_discord_request_admissions WHERE state = 'uncertain' AND is_publish) AS uncertain,
           (SELECT count(*) FROM public.pr_discord_request_admissions
             WHERE state = 'sent' AND is_publish AND sent_at <= clock_timestamp() - interval '120 seconds') AS stuck,
           (SELECT count(*) FROM public.pr_discord_request_admissions
             WHERE state IN ('reserved', 'sealed') AND expires_at > clock_timestamp() AND is_publish) AS live,
           (SELECT extract(epoch FROM min(coalesce(sent_at, reserved_at)))::double precision
              FROM public.pr_discord_request_admissions
             WHERE is_publish AND (state = 'uncertain'
                                   OR state = 'sent' AND sent_at <= clock_timestamp() - interval '120 seconds')) AS oldest
), guard_rows AS (
    SELECT DISTINCT ON (r.kind) r.kind,
           jsonb_build_object(
               'present', true, 'hold', r.manual_hold,
               'blocked', coalesce(r.blocked_until > o.at, false), 'circuit', coalesce(r.circuit_until > o.at, false),
               'embargoSeconds', round(greatest(0, extract(epoch FROM greatest(r.blocked_until, r.circuit_until) - o.at))::numeric, 1),
               'remaining', r.remaining, 'limit', r.limit_count, 'windowSeconds', r.window_seconds,
               'remainingRatio', CASE WHEN r.limit_count IS NULL THEN NULL
                                      WHEN r.reset_at <= o.at AND r.kind = 'invalid' THEN 1.0
                                      ELSE round(greatest(0, coalesce(r.remaining, 0))::numeric / r.limit_count, 4) END,
               'resetSeconds', round(greatest(0, extract(epoch FROM r.reset_at - o.at))::numeric, 1),
               'unchangedSeconds', round(greatest(0, extract(epoch FROM o.at - r.updated_at))::numeric, 1),
               'policyDaysLeft', round((extract(epoch FROM r.policy_expires_at - o.at) / 86400)::numeric, 2)) AS guard
    FROM public.pr_discord_rate_state r CROSS JOIN observed o
    WHERE r.kind IN ('policy', 'invalid')
    ORDER BY r.kind, r.updated_at DESC
), kinds AS (
    SELECT r.kind,
           jsonb_build_object('holds', count(*) FILTER (WHERE r.manual_hold),
                              'blocks', count(*) FILTER (WHERE r.blocked_until > o.at),
                              'circuits', count(*) FILTER (WHERE r.circuit_until > o.at),
                              'persistentCircuits', count(*) FILTER (WHERE r.circuit_until > o.at
                                                                       AND r.circuit_until >= r.policy_expires_at - interval '1 second'),
                              'openOver5Min', count(*) FILTER (WHERE greatest(r.circuit_until, r.blocked_until) > o.at
                                                                 AND r.updated_at < o.at - interval '5 minutes')) AS counts
    FROM public.pr_discord_rate_state r CROSS JOIN observed o
    WHERE r.manual_hold OR r.blocked_until > o.at OR r.circuit_until > o.at
    GROUP BY r.kind
), servers AS (
    SELECT (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials
             WHERE provider = 'discord' AND 'bot' = ANY(scopes)) AS counted,
           (SELECT count(*) FROM public.pr_oauth_transactions
             WHERE provider = 'discord' AND 'bot' = ANY(scopes)
               AND ((consumed_at IS NULL AND expires_at > now())
                    OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))) AS in_flight
)
SELECT jsonb_build_object(
    'version', 1, 'kind', 'rafii.discord.ops.health', 'source', 'sql', 'observedAt', round(o.epoch::numeric, 3),
    'queue', jsonb_build_object('status', 'observed', 'dueWorkspaces', q.due, 'dueWithin5Min', q.soon,
                                'pendingWorkspaces', q.pending, 'oldestDueLagSeconds', round(q.lag::numeric, 1)),
    'progress', jsonb_build_object(
        'status', 'observed',
        'lastClaimAgeSeconds', CASE WHEN q.last_claim > 0 THEN round(greatest(0, o.epoch - q.last_claim)::numeric, 1) END,
        'lastAdmissionAgeSeconds', CASE WHEN l.newest > 0 THEN round(greatest(0, o.epoch - l.newest)::numeric, 1) END,
        'lastAcceptedCreateAgeSeconds', CASE WHEN l.last_accepted > 0 THEN round(greatest(0, o.epoch - l.last_accepted)::numeric, 1) END,
        'lastReadbackAgeSeconds', CASE WHEN l.last_readback > 0 THEN round(greatest(0, o.epoch - l.last_readback)::numeric, 1) END,
        'sampleSpanSeconds', CASE WHEN l.sampled > 0 THEN round(greatest(0, o.epoch - l.oldest)::numeric, 1) END),
    'deliveries', jsonb_build_object(
        'status', 'observed', 'windowSeconds', 900, 'sampled', l.sampled, 'sampleLimit', 20000,
        'windowCovered', l.sampled < 20000 OR o.epoch - l.oldest >= 900,
        'creates', l.creates, 'accepted', l.accepted, 'rejectedCustomer', l.customer, 'rejectedSystem', l.system,
        'rateLimited', l.limited, 'uncertain', l.uncertain, 'blocked', l.blocked, 'inFlight', l.in_flight,
        'stuckSent', l.stuck_new, 'stuckSentTotal', l.stuck_all),
    'unresolved', jsonb_build_object(
        'status', 'observed', 'uncertainPublishes', u.uncertain, 'stuckSentPublishes', u.stuck, 'livePermits', u.live,
        'oldestUnresolvedAgeSeconds', CASE WHEN u.oldest > 0 THEN round(greatest(0, o.epoch - u.oldest)::numeric, 1) END),
    'coordinator', jsonb_build_object(
        'status', 'observed_by_kind',
        'guards', coalesce((SELECT jsonb_object_agg(g.kind, g.guard) FROM guard_rows g), '{}'::jsonb),
        'kinds', coalesce((SELECT jsonb_object_agg(k.kind, k.counts) FROM kinds k), '{}'::jsonb),
        'traffic', jsonb_build_object(
            'responses429', l.r429, 'responses429Global', l.r429_global, 'invalid10m', l.invalid,
            'invalidWindowCovered', l.sampled < 20000 OR o.epoch - l.oldest >= 600,
            'responses5m', l.responses, 'serverErrors5m', l.server_errors, 'admissions60s', l.admitted,
            'uncertainReads', l.uncertain_reads, 'unauthorized', l.unauthorized)),
    'servers', jsonb_build_object('status', 'observed', 'counted', sv.counted, 'inFlight', sv.in_flight,
                                  'used', sv.counted + sv.in_flight),
    'errors', '[]'::jsonb) AS snapshot
FROM observed o CROSS JOIN queue q CROSS JOIN ledger l CROSS JOIN unresolved u CROSS JOIN servers sv
$snapshot$;
ALTER FUNCTION public.pr_discord_ops_snapshot() OWNER TO rafii_discord_ops_projection;
REVOKE ALL ON FUNCTION public.pr_discord_ops_snapshot() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pr_discord_ops_snapshot() TO rafii_discord_ops_reader;
COMMIT;
