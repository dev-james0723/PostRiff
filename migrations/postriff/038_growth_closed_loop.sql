-- V3 Phase 2: private, additive, default-off closed-loop records.
begin;
alter table public.pr_post_doctor_runs drop constraint if exists pr_post_doctor_runs_kind_check;
alter table public.pr_post_doctor_runs add constraint pr_post_doctor_runs_kind_check
  check(kind in ('check','rewrite','genome','postmortem','audience'));
create table public.pr_postmortems (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  job_id text not null,
  horizon text not null check(horizon in ('1h','24h','7d')),
  basis_digest text not null,
  body jsonb not null,
  status text not null default 'observed' check(status in ('observed','approved','dismissed','stale')),
  genome_id uuid references public.pr_genome_versions(id) on delete set null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '12 months',
  unique(workspace_id,job_id,horizon,basis_digest)
);
create table public.pr_comment_judgments (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  thread_id uuid not null references public.pr_audience_threads(id) on delete cascade,
  input_digest text not null,
  body jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '90 days',
  primary key(workspace_id,thread_id)
);
create table public.pr_audience_clusters (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  run_id uuid not null references public.pr_post_doctor_runs(id) on delete cascade,
  basis_digest text not null,
  body jsonb not null,
  source_id text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '90 days'
);
create table public.pr_creator_calibrations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  basis_digest text not null,
  body jsonb not null,
  status text not null default 'proposed' check(status in ('proposed','approved','superseded','stale')),
  approved_by uuid,
  created_at timestamptz not null default now(),
  approved_at timestamptz
);
do $$ declare t text; begin
  foreach t in array array['pr_postmortems','pr_comment_judgments','pr_audience_clusters','pr_creator_calibrations'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    execute format('create index %I on public.%I(workspace_id,created_at desc)',t||'_workspace',t);
  end loop;
end $$;
create index pr_postmortems_expiry on public.pr_postmortems(expires_at);
create index pr_comment_judgments_expiry on public.pr_comment_judgments(expires_at);
create index pr_audience_clusters_expiry on public.pr_audience_clusters(expires_at);
commit;
