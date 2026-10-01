-- Rafii Control v2 Phase 0/1. Additive; no operators, credentials or external integrations are activated.
-- Apply only after a reviewed staging/production authorization. No consumer table is modified.
begin;
create schema if not exists rafii_control;
revoke all on schema rafii_control from public, anon, authenticated, service_role;
do $$ begin
  if not exists(select 1 from pg_roles where rolname='rafii_control_session') then create role rafii_control_session nologin nosuperuser nobypassrls; end if;
  if not exists(select 1 from pg_roles where rolname='rafii_control_reader') then create role rafii_control_reader nologin nosuperuser nobypassrls; end if;
  if not exists(select 1 from pg_roles where rolname='rafii_control_ingest') then create role rafii_control_ingest nologin nosuperuser nobypassrls; end if;
  -- This non-login projection owner can bypass tenant RLS, but has SELECT on explicit safe columns only.
  -- Never grant membership in this role to an application or browser principal.
  if not exists(select 1 from pg_roles where rolname='rafii_control_projection') then create role rafii_control_projection nologin nosuperuser bypassrls; end if;
end $$;
grant usage on schema rafii_control to rafii_control_session, rafii_control_reader, rafii_control_projection;
grant usage on schema rafii_control to rafii_control_ingest;
grant usage on schema public to rafii_control_projection;

create table if not exists rafii_control.platform_operators (
  user_id uuid not null references auth.users(id), environment text not null check(environment in ('local','staging','production')),
  role text not null check(role='founder'), status text not null check(status in ('active','revoked')),
  capabilities text[] not null default '{}', auth_epoch bigint not null default 1 check(auth_epoch>0),
  created_at timestamptz not null default now(), primary key(user_id,environment),
  check(capabilities <@ array['control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use']::text[])
);
create table if not exists rafii_control.founder_sessions (
  id uuid primary key, user_id uuid not null, environment text not null,
  token_hash text not null unique check(token_hash ~ '^[0-9a-f]{64}$'), auth_epoch bigint not null,
  assurance text not null check(assurance='aal2'), upstream_session text not null check(length(upstream_session) between 16 and 160),
  mfa_at double precision not null, created_at double precision not null, last_seen_at double precision not null,
  expires_at double precision not null, revoked_at double precision,
  foreign key(user_id,environment) references rafii_control.platform_operators(user_id,environment),
  check(expires_at=created_at+28800), check(last_seen_at>=created_at), check(mfa_at<=created_at and mfa_at>=created_at-300)
);
create index if not exists rc_session_actor on rafii_control.founder_sessions(user_id,environment,expires_at);
create table if not exists rafii_control.admin_audit_log (
  id uuid primary key default gen_random_uuid(), request_id uuid not null, actor uuid, session uuid,
  environment text not null check(environment in ('local','staging','production')),
  action text not null check(action in ('session.exchange','control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','prohibited')),
  result text not null check(result in ('allowed','denied')), occurred_at timestamptz not null default now()
);
create index if not exists rc_audit_environment_time on rafii_control.admin_audit_log(environment,occurred_at desc);
create table if not exists rafii_control.query_receipts (
  id uuid primary key, operator_id uuid not null, environment text not null, request_id uuid not null,
  query_digest text not null check(query_digest ~ '^[0-9a-f]{64}$'), metric_versions jsonb not null,
  data_state text not null check(data_state in ('measured','partial','stale','unavailable','not_applicable','suppressed')),
  source_watermarks jsonb not null, row_count integer not null check(row_count between 0 and 1000),
  created_at timestamptz not null default now(), expires_at timestamptz not null default now()+interval '90 days'
);
create table if not exists rafii_control.source_health (
  source_id text not null, environment text not null, state text not null check(state in ('measured','partial','stale','unavailable','not_applicable','suppressed')),
  watermark timestamptz, checked_at timestamptz not null default now(), reason_code text not null check(reason_code in ('qualified','not_configured','scope_missing','lagging','reconciliation_required','provider_unavailable')),
  primary key(source_id,environment)
);
-- Evidence is a projection, never the raw provider payload, Sentry message, source code, log body or customer conversation.
create table if not exists rafii_control.engineering_evidence (
  id uuid primary key, environment text not null, kind text not null check(kind in ('error','log','deployment','check','security')),
  provider text not null check(provider in ('sentry','vercel','github','local')), external_id text not null check(length(external_id)<=160),
  exact_sha text check(exact_sha ~ '^[0-9a-f]{40}$'), state text not null check(state in ('suspected','reproduced','candidate_fix','checks_passed','merged','deployed','production_verified')),
  conclusion text check(conclusion in ('success','failure','cancelled','skipped','neutral','timed_out','action_required','unknown')),
  failure_class text check(failure_class in ('product','test','infrastructure','security','unknown')),
  attested boolean not null default false, required boolean not null default false, observed_at timestamptz not null,
  unique(environment,provider,kind,external_id),
  check(state not in ('checks_passed','merged','deployed','production_verified') or (attested and exact_sha is not null))
);
create table if not exists rafii_control.founder_runs (
  id uuid primary key, operator_id uuid not null, environment text not null, conversation_id uuid not null,
  principal_namespace text not null default 'founder' check(principal_namespace='founder'),
  request_id uuid not null, request_digest text not null check(request_digest ~ '^[0-9a-f]{64}$'),
  result jsonb not null, created_at timestamptz not null default now(), unique(operator_id,environment,request_id)
);
create table if not exists rafii_control.recommendations (
  id uuid primary key, operator_id uuid not null, environment text not null, evidence_ids uuid[] not null,
  proposal jsonb not null, state text not null default 'draft' check(state in ('draft','dismissed','expired')),
  created_at timestamptz not null default now(), expires_at timestamptz not null,
  check(jsonb_array_length(proposal->'facts')>0), check(proposal#>>'{proposedAction,requiresHumanApproval}'='true')
);
create table if not exists rafii_control.request_budgets (
  bucket text not null check(bucket ~ '^[0-9a-f]{64}$'), environment text not null,
  window_start bigint not null, attempts integer not null check(attempts>0), primary key(bucket,environment)
);
-- Analytical event copies carry lineage/digests; canonical domain receipts remain authoritative.
create table if not exists rafii_control.normalized_events (
  event_id uuid primary key, environment text not null check(environment in ('local','staging','production')),
  source text not null, source_event_id text not null, event_type text not null, dedupe_key text not null,
  event_time timestamptz not null, received_at timestamptz not null, projected_at timestamptz not null default now(),
  subject_type text not null, subject_id text not null, classification text not null check(classification in ('internal_metadata','customer_metadata')),
  payload jsonb not null, payload_digest text not null check(payload_digest ~ '^[0-9a-f]{64}$'), fixture boolean not null,
  unique(environment,source,source_event_id),unique(environment,dedupe_key),check(environment<>'production' or not fixture)
);
create table if not exists rafii_control.ingestion_cursors (
  environment text not null, source text not null, received_watermark timestamptz not null,
  projected_at timestamptz not null default now(), primary key(environment,source)
);
create table if not exists rafii_control.metric_rollups (
  environment text not null, metric_id text not null, definition_version integer not null check(definition_version>0),
  interval_start timestamptz not null, interval_end timestamptz not null, grain text not null,
  dimension_digest text not null check(dimension_digest ~ '^[0-9a-f]{64}$'), dimensions jsonb not null,
  value numeric, currency text check(currency ~ '^[A-Z]{3}$'), sample_count integer check(sample_count>=0),
  source_watermark timestamptz, source_receipt_ids uuid[] not null, policy_approval_ref uuid,
  data_state text not null check(data_state in ('measured','partial','stale','unavailable','not_applicable','suppressed')),
  fixture boolean not null default false, primary key(environment,metric_id,definition_version,interval_start,dimension_digest),
  check(interval_end>interval_start),check(environment<>'production' or not fixture),
  check(data_state<>'measured' or (value is not null and source_watermark is not null and policy_approval_ref is not null))
);

do $$ declare t text; begin
  foreach t in array array['platform_operators','founder_sessions','admin_audit_log','query_receipts','source_health','engineering_evidence','founder_runs','recommendations','request_budgets'] loop
    execute format('alter table rafii_control.%I enable row level security',t);
    execute format('alter table rafii_control.%I force row level security',t);
    execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',t);
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_session_read') then
      execute format('create policy control_session_read on rafii_control.%I for select to rafii_control_session using (environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
    execute format('grant select on rafii_control.%I to rafii_control_session',t);
  end loop;
  foreach t in array array['founder_sessions','admin_audit_log','query_receipts','founder_runs','recommendations','request_budgets'] loop
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_session_insert') then
      execute format('create policy control_session_insert on rafii_control.%I for insert to rafii_control_session with check (environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
    execute format('grant insert on rafii_control.%I to rafii_control_session',t);
  end loop;
  foreach t in array array['source_health','engineering_evidence','query_receipts','recommendations'] loop
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_reader') then
      execute format('create policy control_reader on rafii_control.%I for select to rafii_control_reader using (environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
    execute format('grant select on rafii_control.%I to rafii_control_reader',t);
  end loop;
end $$;
do $$ declare t text; begin
  foreach t in array array['normalized_events','ingestion_cursors','metric_rollups'] loop
    execute format('alter table rafii_control.%I enable row level security',t);
    execute format('alter table rafii_control.%I force row level security',t);
    execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',t);
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_ingest') then
      execute format('create policy control_ingest on rafii_control.%I for all to rafii_control_ingest using(environment=current_setting(''rafii_control.environment'',true)) with check(environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
    execute format('grant select,insert on rafii_control.%I to rafii_control_ingest',t);
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_reader') then
      execute format('create policy control_reader on rafii_control.%I for select to rafii_control_reader using(environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
    execute format('grant select on rafii_control.%I to rafii_control_reader',t);
  end loop;
end $$;
grant update(received_watermark,projected_at) on rafii_control.ingestion_cursors to rafii_control_ingest;
grant update(last_seen_at,revoked_at) on rafii_control.founder_sessions to rafii_control_session;
grant update(window_start,attempts) on rafii_control.request_budgets to rafii_control_session;
grant update(result) on rafii_control.founder_runs to rafii_control_session;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_sessions' and policyname='control_session_update') then
    create policy control_session_update on rafii_control.founder_sessions for update to rafii_control_session
      using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
  end if;
end $$;
do $$ declare t text; begin
  foreach t in array array['request_budgets','founder_runs'] loop
    if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=t and policyname='control_session_update') then
      execute format('create policy control_session_update on rafii_control.%I for update to rafii_control_session using(environment=current_setting(''rafii_control.environment'',true)) with check(environment=current_setting(''rafii_control.environment'',true))',t);
    end if;
  end loop;
end $$;

grant select(user_id,deleted_at) on public.pr_profiles to rafii_control_projection;
grant select(user_id) on public.pr_account_tombstones to rafii_control_projection;
grant select(user_id,session_id) on public.pr_session_revocations to rafii_control_projection;
grant select(user_id,workspace_id,role,status) on public.pr_memberships to rafii_control_projection;
grant select(id,created_at) on public.pr_workspaces to rafii_control_projection;
grant select(workspace_id,status,plan_terms_id) on public.pr_subscriptions to rafii_control_projection;
grant select(id,plan,version) on public.pr_plan_terms to rafii_control_projection;
grant select(user_id,last_seen) on public.pr_sessions to rafii_control_projection;
create or replace view rafii_control.safe_users with(security_barrier=true) as
  select p.user_id, p.deleted_at is not null as deleted,
    (select count(*) from public.pr_memberships m where m.user_id=p.user_id and m.status='active') as workspace_count,
    (select max(s.last_seen) from public.pr_sessions s where s.user_id=p.user_id) as last_seen_at
  from public.pr_profiles p;
create or replace view rafii_control.safe_workspaces with(security_barrier=true) as
  select w.id, w.created_at,
    (select count(*) from public.pr_memberships m where m.workspace_id=w.id and m.status='active') as member_count,
    s.status as subscription_status, t.plan, t.version as terms_version
  from public.pr_workspaces w left join public.pr_subscriptions s on s.workspace_id=w.id left join public.pr_plan_terms t on t.id=s.plan_terms_id;
create or replace view rafii_control.safe_memberships with(security_barrier=true) as
  select user_id,workspace_id,role,status from public.pr_memberships;
-- A fixed boolean check reuses the authoritative account tombstone/session revocation sources.
create or replace function rafii_control.identity_active(p_user uuid,p_session text) returns boolean
  language sql stable security definer set search_path='' as $$
    select exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is null)
      and not exists(select 1 from public.pr_account_tombstones where user_id=p_user)
      and not exists(select 1 from public.pr_session_revocations where user_id=p_user and session_id=p_session)
  $$;
-- Ownership transfer requires CREATE only during migration, then removes it.
grant create on schema rafii_control to rafii_control_projection;
alter view rafii_control.safe_users owner to rafii_control_projection;
alter view rafii_control.safe_workspaces owner to rafii_control_projection;
alter view rafii_control.safe_memberships owner to rafii_control_projection;
alter function rafii_control.identity_active(uuid,text) owner to rafii_control_projection;
revoke create on schema rafii_control from rafii_control_projection;
revoke all on function rafii_control.identity_active(uuid,text) from public,anon,authenticated,service_role,rafii_control_reader;
grant execute on function rafii_control.identity_active(uuid,text) to rafii_control_session;
grant select on rafii_control.safe_users,rafii_control.safe_workspaces,rafii_control.safe_memberships to rafii_control_reader;
commit;
