begin;
-- Direct search APIs report invoice metadata independently of AI Gateway.
alter table public.pr_model_usage_events drop constraint pr_model_usage_events_cost_source_check;
alter table public.pr_model_usage_events add constraint pr_model_usage_events_cost_source_check
  check(cost_source in ('gateway','provider','unknown') or cost_source ~ '^table:[A-Za-z0-9._-]{1,60}$');
create table public.pr_radar_runs (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 request_key text not null,
 created_by uuid not null,
 status text not null check(status in ('quoted','running','completed','partial','cancelled','unknown')),
 fingerprint text not null,
 context_digest text not null,
 body jsonb not null,
 lease_token text,
 lease_until timestamptz,
 created_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '30 days',
 unique(workspace_id,request_key)
);
alter table public.pr_radar_runs enable row level security;
alter table public.pr_radar_runs force row level security;
revoke all on public.pr_radar_runs from anon,authenticated;
grant all on public.pr_radar_runs to service_role;
create index pr_radar_runs_workspace on public.pr_radar_runs(workspace_id,created_at desc);
create index pr_radar_runs_expiry on public.pr_radar_runs(expires_at);
create table public.pr_radar_source_limits(source text primary key,next_at timestamptz not null);
alter table public.pr_radar_source_limits enable row level security;
alter table public.pr_radar_source_limits force row level security;
revoke all on public.pr_radar_source_limits from anon,authenticated;
grant all on public.pr_radar_source_limits to service_role;
create table public.pr_radar_watch_schedule (
 workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
 checked_at timestamptz not null
);
alter table public.pr_radar_watch_schedule enable row level security;
alter table public.pr_radar_watch_schedule force row level security;
revoke all on public.pr_radar_watch_schedule from anon,authenticated;
grant all on public.pr_radar_watch_schedule to service_role;
commit;
