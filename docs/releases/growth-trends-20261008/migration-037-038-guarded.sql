-- Guarded production apply: 037_growth_phase1 + 038_growth_closed_loop (additive, one transaction).
-- Reviewed file bodies with only the outer begin/commit removed; sha256 pinned in the ledger.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM postriff_private.schema_migrations WHERE name IN ('037_growth_phase1.sql','038_growth_closed_loop.sql')) THEN
    RAISE EXCEPTION '037/038 already recorded in the ledger';
  END IF;
  IF to_regclass('public.pr_post_doctor_runs') IS NOT NULL OR to_regclass('public.pr_postmortems') IS NOT NULL
     OR to_regclass('public.pr_genome_versions') IS NOT NULL OR to_regclass('public.pr_audience_clusters') IS NOT NULL
     OR to_regclass('public.pr_post_history') IS NOT NULL OR to_regclass('public.pr_growth_budgets') IS NOT NULL THEN
    RAISE EXCEPTION 'growth tables already exist without a ledger row; refusing';
  END IF;
  IF to_regclass('public.pr_workspaces') IS NULL OR to_regclass('public.pr_audience_threads') IS NULL THEN
    RAISE EXCEPTION 'dependency missing';
  END IF;
END
$guard$;
-- ===== 037_growth_phase1.sql sha256 7e9be37ec035407025328b5f26443898435d8958cb17d3caf1a7db8a331dde42
-- v3 Phase 1. Local additive migration; all routes default off. No browser writes.
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
-- ===== 038_growth_closed_loop.sql sha256 ac6e52d5a3265bf3b88b56a17976e0f165b66acaedacd1dc240dc527865e2ac0
-- V3 Phase 2: private, additive, default-off closed-loop records.
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
INSERT INTO postriff_private.schema_migrations(name, sha256) VALUES
  ('037_growth_phase1.sql', '7e9be37ec035407025328b5f26443898435d8958cb17d3caf1a7db8a331dde42'),
  ('038_growth_closed_loop.sql', 'ac6e52d5a3265bf3b88b56a17976e0f165b66acaedacd1dc240dc527865e2ac0');
