-- v3 Phase 1. Local additive migration; all routes default off. No browser writes.
begin;
create table if not exists public.pr_post_history (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  source_id text not null,
  source_revision integer not null,
  platform text not null,
  connection_id text not null default '',
  provider_post_id text not null default '',
  language text not null,
  format text not null default 'text',
  time_bucket text not null default 'unknown',
  labels jsonb not null default '{}',
  judgment jsonb not null default '{}',
  supplied_metrics jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique(workspace_id,source_id)
);
create table if not exists public.pr_genome_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  body jsonb not null,
  status text not null default 'proposed' check(status in ('proposed','approved','superseded','stale')),
  created_by uuid not null,
  approved_by uuid,
  created_at timestamptz not null default now(),
  approved_at timestamptz
);
create index if not exists pr_genome_versions_workspace on public.pr_genome_versions(workspace_id,created_at desc);
create table if not exists public.pr_post_doctor_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  request_key text not null check(length(request_key) between 16 and 100),
  kind text not null check(kind in ('check','rewrite','genome')),
  status text not null check(status in ('running','completed','failed','cancelled','unknown')),
  fingerprint text not null,
  context_fingerprint text not null,
  body jsonb not null default '{}',
  accepted_changes jsonb not null default '[]',
  helpful boolean,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '12 months',
  unique(workspace_id,request_key)
);
create index if not exists pr_post_doctor_runs_expiry on public.pr_post_doctor_runs(expires_at);
create table if not exists public.pr_predictions (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  job_id text not null,
  body jsonb not null,
  verified_at timestamptz not null,
  primary key(workspace_id,job_id)
);
create table if not exists public.pr_share_cards (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  genome_id uuid not null references public.pr_genome_versions(id) on delete cascade,
  token_hash text not null unique,
  labels jsonb not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
create table if not exists public.pr_public_checks (
  id uuid primary key default gen_random_uuid(),
  subject_hash text not null,
  status text not null default 'running',
  result jsonb not null default '{}',
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '24 hours'
);
create index if not exists pr_public_checks_expiry on public.pr_public_checks(expires_at);
-- Monetary/work reservations survive uncertain paid attempts; unknown costs never release a reservation.
create table if not exists public.pr_growth_budgets (
  scope text not null,
  day date not null,
  reserved_micro bigint not null default 0 check(reserved_micro>=0),
  calls integer not null default 0 check(calls>=0),
  primary key(scope,day)
);
do $$ declare t text; begin
  foreach t in array array['pr_post_history','pr_genome_versions','pr_post_doctor_runs','pr_predictions','pr_share_cards','pr_public_checks','pr_growth_budgets'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
  end loop;
end $$;
commit;
