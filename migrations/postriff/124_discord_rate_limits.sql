-- DRAFT ONLY. No execution/migration approval is implied by this source file.
-- Canonical target, if separately approved: postriff-phase2-private / buoyhkbodnhzngaotoel.
-- Additive, default-off P4. Existing approvals, credentials and scheduler own publishing.
BEGIN;

CREATE TABLE public.pr_discord_rate_state (
    scope_key text PRIMARY KEY CHECK (scope_key ~ '^[0-9]{2}:[a-f0-9]{64}$'),
    kind text NOT NULL CHECK (kind IN ('policy','global','credential','invalid','discovery','resource','route')),
    limit_count integer CHECK (limit_count BETWEEN 1 AND 100000),
    remaining integer CHECK (remaining BETWEEN 0 AND 100000),
    window_seconds double precision CHECK (window_seconds >= 0.05 AND window_seconds <= 253402300799),
    reset_at timestamptz NOT NULL,
    blocked_until timestamptz,
    circuit_until timestamptz,
    error_streak integer NOT NULL DEFAULT 0 CHECK (error_streak BETWEEN 0 AND 100000),
    manual_hold boolean NOT NULL DEFAULT false,
    learned boolean NOT NULL DEFAULT false,
    fresh_after timestamptz,
    observation_seq bigint NOT NULL DEFAULT 0 CHECK (observation_seq>=0),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision>=0),
    policy_revision text NOT NULL CHECK (policy_revision ~ '^[A-Za-z0-9_.:-]{1,64}$'),
    policy_expires_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (kind='route' OR (NOT learned AND fresh_after IS NULL)),
    CHECK (fresh_after IS NULL OR learned),
    CHECK ((limit_count IS NULL AND remaining IS NULL AND window_seconds IS NULL AND kind IN ('global','credential','resource'))
        OR (limit_count IS NOT NULL AND remaining IS NOT NULL AND window_seconds IS NOT NULL AND kind IN ('policy','invalid','discovery','route')))
);
CREATE INDEX pr_discord_rate_state_expiry ON public.pr_discord_rate_state(updated_at);

CREATE TABLE public.pr_discord_route_buckets (
    auth_key text NOT NULL CHECK (auth_key ~ '^[a-f0-9]{64}$'),
    route_key text NOT NULL CHECK (route_key ~ '^[a-f0-9]{64}$'),
    major_key text NOT NULL CHECK (major_key ~ '^[a-f0-9]{64}$'),
    bucket_key text CHECK (bucket_key ~ '^[a-f0-9]{64}$'),
    observation_seq bigint NOT NULL DEFAULT 0 CHECK (observation_seq>=0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(auth_key,route_key,major_key)
);
CREATE INDEX pr_discord_route_buckets_expiry ON public.pr_discord_route_buckets(updated_at);

CREATE TABLE public.pr_discord_request_admissions (
    id uuid PRIMARY KEY,
    request_seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    application_key text NOT NULL CHECK (application_key ~ '^[a-f0-9]{64}$'),
    auth_key text NOT NULL CHECK (auth_key ~ '^[a-f0-9]{64}$'),
    credential_key text NOT NULL CHECK (credential_key ~ '^[a-f0-9]{64}$'),
    credential_kind text NOT NULL CHECK (credential_kind IN ('bot','user','oauth')),
    method text NOT NULL CHECK (method IN ('GET','POST','DELETE','PUT','PATCH')),
    path_key text NOT NULL CHECK (path_key ~ '^[a-f0-9]{64}$'),
    route_key text NOT NULL CHECK (route_key ~ '^[a-f0-9]{64}$'),
    major_key text NOT NULL CHECK (major_key ~ '^[a-f0-9]{64}$'),
    bucket_key text CHECK (bucket_key ~ '^[a-f0-9]{64}$'),
    scope_keys text[] NOT NULL CHECK (cardinality(scope_keys) BETWEEN 6 AND 16 AND array_position(scope_keys,NULL) IS NULL),
    is_publish boolean NOT NULL DEFAULT false,
    binding_hash text CHECK (binding_hash ~ '^[a-f0-9]{64}$'),
    -- No cascading workspace FK: deletion cannot erase unresolved app-wide quota evidence.
    -- These are non-content operational identifiers, unavailable to customer roles.
    workspace_id uuid,
    publication_id text CHECK (length(publication_id) BETWEEN 1 AND 128),
    manifest_digest text CHECK (manifest_digest ~ '^[a-f0-9]{64}$'),
    authorization_digest text CHECK (authorization_digest ~ '^[a-f0-9]{64}$'),
    approval_digest text CHECK (approval_digest ~ '^[a-f0-9]{64}$'),
    worker_key text CHECK (worker_key ~ '^[a-f0-9]{64}$'),
    lease_key text CHECK (lease_key ~ '^[a-f0-9]{64}$'),
    channel_key text CHECK (channel_key ~ '^[a-f0-9]{64}$'),
    intent_id text CHECK (length(intent_id) BETWEEN 1 AND 128),
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','sealed','sent','observed','uncertain','blocked')),
    reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    sealed_at timestamptz,
    sent_at timestamptz,
    outcome_at timestamptz,
    status_code integer CHECK (status_code BETWEEN 100 AND 599),
    rate_scope text CHECK (rate_scope IN ('global','shared','user','unknown')),
    CHECK (expires_at>reserved_at),
    CHECK ((is_publish AND method='POST' AND binding_hash IS NOT NULL AND workspace_id IS NOT NULL
        AND publication_id IS NOT NULL AND manifest_digest IS NOT NULL AND authorization_digest IS NOT NULL
        AND approval_digest IS NOT NULL AND worker_key IS NOT NULL AND lease_key IS NOT NULL AND channel_key IS NOT NULL)
        OR (NOT is_publish AND binding_hash IS NULL AND workspace_id IS NULL AND publication_id IS NULL
        AND manifest_digest IS NULL AND authorization_digest IS NULL AND approval_digest IS NULL
        AND worker_key IS NULL AND lease_key IS NULL AND channel_key IS NULL AND intent_id IS NULL AND sealed_at IS NULL)),
    CHECK (state NOT IN ('sealed','sent','observed','uncertain') OR NOT is_publish OR intent_id IS NOT NULL)
);
CREATE UNIQUE INDEX pr_discord_admission_binding ON public.pr_discord_request_admissions(binding_hash) WHERE is_publish;
CREATE UNIQUE INDEX pr_discord_admission_intent ON public.pr_discord_request_admissions(workspace_id,publication_id,intent_id)
    WHERE is_publish AND intent_id IS NOT NULL;
CREATE INDEX pr_discord_admission_scopes ON public.pr_discord_request_admissions USING gin(scope_keys);
CREATE INDEX pr_discord_admission_unresolved ON public.pr_discord_request_admissions(state,expires_at)
    WHERE state IN ('reserved','sealed','sent','uncertain');
CREATE INDEX pr_discord_admission_route ON public.pr_discord_request_admissions(auth_key,route_key,major_key,state);
CREATE INDEX pr_discord_admission_sample ON public.pr_discord_request_admissions(application_key,request_seq DESC);

ALTER TABLE public.pr_discord_rate_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_rate_state FORCE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_route_buckets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_route_buckets FORCE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_request_admissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_request_admissions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_discord_rate_state,public.pr_discord_route_buckets,public.pr_discord_request_admissions FROM PUBLIC,anon,authenticated;
REVOKE ALL ON SEQUENCE public.pr_discord_request_admissions_request_seq_seq FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.pr_discord_rate_state,public.pr_discord_route_buckets,public.pr_discord_request_admissions TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.pr_discord_request_admissions_request_seq_seq TO service_role;
CREATE POLICY pr_discord_rate_service ON public.pr_discord_rate_state FOR ALL TO service_role USING(true) WITH CHECK(true);
CREATE POLICY pr_discord_route_service ON public.pr_discord_route_buckets FOR ALL TO service_role USING(true) WITH CHECK(true);
CREATE POLICY pr_discord_admission_service ON public.pr_discord_request_admissions FOR ALL TO service_role USING(true) WITH CHECK(true);
COMMIT;

-- Rollback is operational: stop Discord forward work, disable the approved flags,
-- preserve admissions/intents/receipts and restore the approved source delta.
-- No automatic DROP/TRUNCATE/quota reset. Retention/purging needs a separately
-- reviewed policy; unresolved records must be reconciled before deletion.
