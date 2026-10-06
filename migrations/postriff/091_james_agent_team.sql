-- Mission-scoped observations, report versions, fenced leases and external-effect receipts.
-- Kynlo missions and Token Pilot remain the task and continuity authorities.
begin;
create table if not exists public.pr_agent_team_events (
  event_key text primary key check(length(event_key)=64),
  source text not null check(source in ('luci','typeless','codex','claude','browser','health','mission','git','token_pilot','acceptance','incident')),
  source_id text not null, revision text not null, happened_at timestamptz not null,
  observed_at timestamptz not null, received_at timestamptz not null default now(),
  mission_id text, project_id text, document jsonb not null, immutable_digest text not null,
  check(observed_at>=happened_at)
);
create index if not exists pr_agent_team_events_cutoff on public.pr_agent_team_events(happened_at,observed_at);
create table if not exists public.pr_agent_team_reports (
  report_key text not null, fingerprint text not null, kind text not null check(kind in ('half_day','whole_day')),
  workday date not null, cutoff timestamptz not null, generated_at timestamptz not null,
  document jsonb not null, primary key(report_key,fingerprint)
);
create index if not exists pr_agent_team_reports_latest on public.pr_agent_team_reports(report_key,generated_at desc);
create table if not exists public.pr_agent_team_effects (
  effect_key text primary key, report_key text, kind text not null,
  state text not null check(state in ('reserved','submitted','confirmed','failed','unknown','disabled')),
  external_id text, failure_class text, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.pr_agent_team_leases (
  scope text primary key, owner text not null, generation bigint not null check(generation>0),
  expires_at timestamptz not null, updated_at timestamptz not null default now()
);
create table if not exists public.pr_agent_team_decisions (
  decision_key text primary key, mission_id text not null, scope_version text not null,
  call_run_id uuid references public.pr_james_daily_call_runs(id),
  question_version text not null, choice text not null check(choice in ('continue','wait','needs_human')),
  authenticated_user_id uuid not null, received_at timestamptz not null default now(),
  execution_state text not null default 'recorded' check(execution_state in ('recorded','consumed','rejected'))
);
alter table public.pr_james_daily_call_runs drop constraint if exists pr_james_daily_call_runs_origin_check;
alter table public.pr_james_daily_call_runs add constraint pr_james_daily_call_runs_origin_check
  check(origin in ('acceptance','scheduled','agent_team_report'));
do $$ declare t text; begin
  foreach t in array array['pr_agent_team_events','pr_agent_team_reports','pr_agent_team_effects','pr_agent_team_leases','pr_agent_team_decisions'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
    end if;
  end loop;
end $$;
commit;
