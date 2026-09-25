-- Time Back (docs/raffi-time-back/ENGINEERING.md §6): an estimate of the human work time Raffi returned to a person.
-- One immutable ledger row per completed outcome, the person's calibration answers and current preferences, and
-- aggregate active seconds in Raffi workflows. Additive; apply after 022. Service-role writes only; a person reads only
-- their own rows, and only in a workspace where they are an active member. Nothing here stores text, keys, pointer
-- positions, page structure, prompts, captions, tokens, emails or browsing outside Raffi.
begin;

create table if not exists public.pr_time_savings_ledger (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  -- Account deletion removes the profile row: the person's Time Back goes with it, in every workspace.
  beneficiary_user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  task_kind text not null check (task_kind in ('draft','adapt','publish','campaign_plan','recurring_setup')),
  outcome_kind text not null check (outcome_kind ~ '^[a-z][a-z_]{1,39}$'),
  outcome_ref text not null check (outcome_ref ~ '^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$'),
  dedupe_key text not null check (dedupe_key ~ '^[0-9a-f]{64}$'),
  baseline_seconds integer not null check (baseline_seconds between 0 and 14400),
  active_seconds integer check (active_seconds between 0 and 14400),
  saved_seconds integer not null check (saved_seconds >= 0),
  baseline_source text not null check (baseline_source in ('raffi_default','personalized','user_override')),
  baseline_version text not null check (baseline_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'),
  confidence text not null check (confidence in ('estimated','personalized','measured')),
  calculator_version text not null check (calculator_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'),
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  metadata jsonb not null default '{}' check (jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 512),
  -- Saved time is the baseline minus measured active time, never below zero; a baseline-only estimate saves the baseline.
  constraint pr_time_savings_ledger_saved check (
    saved_seconds = case when active_seconds is null then baseline_seconds else greatest(0, baseline_seconds - active_seconds) end),
  -- Provenance follows from the row itself: measured Raffi time, else the source of the baseline.
  constraint pr_time_savings_ledger_confidence check (
    confidence = case when active_seconds is not null then 'measured' when baseline_source = 'raffi_default' then 'estimated' else 'personalized' end),
  unique (workspace_id, dedupe_key)
);
-- One row per completed outcome, whichever calculator or backfill version wrote it: a replay can never count twice.
create unique index if not exists pr_time_savings_ledger_one_outcome on public.pr_time_savings_ledger (workspace_id, task_kind, outcome_kind, outcome_ref);
create index if not exists pr_time_savings_ledger_person on public.pr_time_savings_ledger (workspace_id, beneficiary_user_id, occurred_at desc);
create index if not exists pr_time_savings_ledger_kind on public.pr_time_savings_ledger (workspace_id, task_kind, occurred_at desc);
create index if not exists pr_time_savings_ledger_beneficiary on public.pr_time_savings_ledger (beneficiary_user_id);

-- Ledger rows never change once written; only deletion (account or workspace removal) takes them away.
create or replace function postriff_private.time_savings_ledger_immutable() returns trigger language plpgsql set search_path='' as $$
begin
  raise exception 'Time Back ledger rows are immutable' using errcode = '42501';
end $$;
create or replace trigger pr_time_savings_ledger_immutable before update on public.pr_time_savings_ledger
  for each row execute function postriff_private.time_savings_ledger_immutable();

-- A person's answers to "Before Raffi, about how long would this usually take you?" and explicit settings.
-- The personalized baseline is the median of the latest confirmed prompt answers once there are three.
create table if not exists public.pr_time_savings_calibrations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  task_kind text not null check (task_kind in ('draft','adapt','publish','campaign_plan','recurring_setup')),
  baseline_seconds integer not null check (baseline_seconds between 60 and 14400),
  source text not null check (source in ('prompt','settings_override')),
  created_at timestamptz not null default now()
);
create index if not exists pr_time_savings_calibrations_recent on public.pr_time_savings_calibrations (workspace_id, user_id, task_kind, created_at desc);
create index if not exists pr_time_savings_calibrations_person on public.pr_time_savings_calibrations (user_id);

-- The current per-kind choice: an explicit baseline override, and when a calibration prompt was last answered or dismissed.
create table if not exists public.pr_time_savings_preferences (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  task_kind text not null check (task_kind in ('draft','adapt','publish','campaign_plan','recurring_setup')),
  override_seconds integer check (override_seconds between 60 and 14400),
  prompted_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id, task_kind)
);
create index if not exists pr_time_savings_preferences_person on public.pr_time_savings_preferences (user_id);

-- Aggregate active seconds only: a bounded workflow key, a counter and timestamps. Heartbeats are cumulative and
-- idempotent; an outcome is credited with the seconds its workflow has not already credited to an earlier outcome.
create table if not exists public.pr_active_work_sessions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workflow_key text not null check (workflow_key ~ '^[a-z][a-z_]{1,23}:[A-Za-z0-9_-]{1,64}$'),
  client_session_key text not null check (client_session_key ~ '^[A-Za-z0-9_-]{16,64}$'),
  task_kind text not null check (task_kind in ('draft','adapt','publish','campaign_plan','recurring_setup')),
  active_seconds integer not null default 0 check (active_seconds between 0 and 14400),
  consumed_seconds integer not null default 0 check (consumed_seconds between 0 and active_seconds),
  sequence integer not null default 0 check (sequence >= 0),
  started_at timestamptz not null,
  last_active_at timestamptz not null,
  closed_at timestamptz,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, user_id, client_session_key)
);
create index if not exists pr_active_work_sessions_workflow on public.pr_active_work_sessions (workspace_id, user_id, workflow_key);
create index if not exists pr_active_work_sessions_person on public.pr_active_work_sessions (user_id);
create index if not exists pr_active_work_sessions_idle on public.pr_active_work_sessions (last_active_at);

do $$
declare t text;
begin
  foreach t in array array['pr_time_savings_ledger','pr_time_savings_calibrations','pr_time_savings_preferences','pr_active_work_sessions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='own_read') then
      execute format('create policy own_read on public.%I for select to authenticated using (%I = (select auth.uid()) and postriff_private.member(workspace_id))',
        t, case when t = 'pr_time_savings_ledger' then 'beneficiary_user_id' else 'user_id' end);
    end if;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;
-- No UPDATE on the ledger for anyone; the other tables change through the service only.
grant select, insert, delete on public.pr_time_savings_ledger to service_role;
grant select, insert, update, delete on public.pr_time_savings_calibrations, public.pr_time_savings_preferences, public.pr_active_work_sessions to service_role;

commit;
