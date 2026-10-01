-- RAFII Product Growth G4-LOOP (PRD R-BRF-01/02, R-PROOF-01/02): opportunity brief editions and item actions,
-- append-only Growth Loop proof revisions and versioned next-week strategy decisions.
-- Additive and idempotent; apply after 047/050. Workspace-owned rows with forced RLS; cross-record references are
-- composite (workspace_id, id) keys so a row can never point at another workspace's record. Rows hold ids, enums,
-- counts, titles and short permitted excerpts only: no source bodies, prompts, contact data or secrets.
begin;

-- One brief edition per recipient, ISO week (in the recipient's zone) and material revision. Items are 0–3 stored-only
-- opportunities with source references; a cosmetic change never creates a revision (material digest).
create table if not exists public.pr_brief_editions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  recipient_user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  edition_key text not null check (edition_key ~ '^[0-9]{4}-W[0-9]{2}$'),
  revision integer not null check (revision between 1 and 1000),
  cadence text not null default 'weekly' check (cadence in ('weekly','daily')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  time_zone text not null check (length(time_zone) between 1 and 64),
  material_digest text not null check (material_digest ~ '^[0-9a-f]{64}$'),
  data_state text not null check (data_state in ('available','partial','unavailable')),
  coverage jsonb not null default '[]'::jsonb check (jsonb_typeof(coverage) = 'array' and octet_length(coverage::text) <= 8192),
  items jsonb not null default '[]'::jsonb
    check (jsonb_typeof(items) = 'array' and jsonb_array_length(items) <= 3 and octet_length(items::text) <= 24576),
  delivered_at timestamptz,
  notification_event_id uuid,
  created_at timestamptz not null default now(),
  constraint pr_brief_editions_period check (period_end > period_start),
  unique (workspace_id, id),
  unique (workspace_id, recipient_user_id, edition_key, revision),
  unique (workspace_id, recipient_user_id, edition_key, material_digest)
);
create index if not exists pr_brief_editions_recipient on public.pr_brief_editions (workspace_id, recipient_user_id, created_at desc, id desc);
create index if not exists pr_brief_editions_occurred on public.pr_brief_editions (workspace_id, created_at, id);
create index if not exists pr_brief_editions_delivered on public.pr_brief_editions (recipient_user_id, delivered_at desc) where delivered_at is not null;

-- Material columns never change; only the one-time delivery receipt may be set.
create or replace function postriff_private.brief_edition_material_immutable() returns trigger language plpgsql set search_path='' as $$
begin
  if (new.workspace_id, new.recipient_user_id, new.edition_key, new.revision, new.material_digest, new.items, new.coverage, new.data_state,
      new.period_start, new.period_end, new.time_zone, new.cadence, new.created_at)
     is distinct from
     (old.workspace_id, old.recipient_user_id, old.edition_key, old.revision, old.material_digest, old.items, old.coverage, old.data_state,
      old.period_start, old.period_end, old.time_zone, old.cadence, old.created_at)
     or (old.delivered_at is not null and new.delivered_at is distinct from old.delivered_at) then
    raise exception 'Brief editions are immutable once stored' using errcode = '42501';
  end if;
  return new;
end $$;
create or replace trigger pr_brief_editions_immutable before update on public.pr_brief_editions
  for each row execute function postriff_private.brief_edition_material_immutable();

-- Bounded cron bookkeeping: when each recipient's brief was last checked (service only, never read by a browser).
create table if not exists public.pr_brief_schedule (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  recipient_user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  checked_at timestamptz not null,
  primary key (workspace_id, recipient_user_id)
);
create index if not exists pr_brief_schedule_due on public.pr_brief_schedule (checked_at);
alter table public.pr_brief_schedule enable row level security;
alter table public.pr_brief_schedule force row level security;
revoke all on public.pr_brief_schedule from public, anon, authenticated;
grant all on public.pr_brief_schedule to service_role;
drop policy if exists service_only on public.pr_brief_schedule;
create policy service_only on public.pr_brief_schedule for all to service_role using (true) with check (true);

-- Append-only actions on brief items: accept / save_idea (with outcome refs), dismiss / not_relevant (with a reason
-- code) and restore. The latest action per recipient and source item decides what later editions show.
create table if not exists public.pr_brief_actions (
  id uuid primary key default gen_random_uuid(),
  seq bigint generated always as identity,      -- total order of actions recorded at the same instant
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  edition_id uuid not null,
  item_id text not null check (item_id ~ '^bi_[0-9a-f]{20}$'),
  source text not null check (source in ('trends','listening','radar')),
  source_ref text not null check (length(source_ref) between 1 and 200),
  action text not null check (action in ('accept','save_idea','dismiss','not_relevant','restore')),
  reason_code text check (reason_code is null or reason_code ~ '^[a-z][a-z_]{1,39}$'),
  effort text check (effort is null or effort in ('quick','medium','deep')),
  outcome_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(outcome_refs) = 'array' and octet_length(outcome_refs::text) <= 2048),
  actor_user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  idempotency_key text not null check (idempotency_key ~ '^[A-Za-z0-9_-]{8,80}$'),
  request_digest text not null check (request_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (workspace_id, id),
  unique (workspace_id, idempotency_key),
  constraint pr_brief_actions_edition foreign key (workspace_id, edition_id) references public.pr_brief_editions(workspace_id, id) on delete cascade,
  constraint pr_brief_actions_reason check ((action in ('dismiss','not_relevant')) = (reason_code is not null))
);
create index if not exists pr_brief_actions_item on public.pr_brief_actions (workspace_id, actor_user_id, source, source_ref, created_at desc, seq desc);
create index if not exists pr_brief_actions_occurred on public.pr_brief_actions (workspace_id, created_at, id);
create index if not exists pr_brief_actions_edition on public.pr_brief_actions (workspace_id, edition_id);

-- Growth Loop proof revisions: a recomputation whose material figures changed appends a revision; earlier ones stay.
create table if not exists public.pr_proof_revisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  proof_id text not null check (proof_id ~ '^gp_[0-9a-f]{20}$'),
  revision integer not null check (revision between 1 and 10000),
  frequency text not null check (frequency in ('weekly','monthly')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  time_zone text not null check (length(time_zone) between 1 and 64),
  time_zone_source text not null check (time_zone_source in ('recipe','notification_preferences','profile','default_utc')),
  definition_version text not null check (definition_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  as_of timestamptz not null,
  source_watermark jsonb not null default '{}'::jsonb check (jsonb_typeof(source_watermark) = 'object'),
  data_state text not null check (data_state in ('available','partial','unavailable')),
  counts jsonb not null check (jsonb_typeof(counts) = 'object' and octet_length(counts::text) <= 65536),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  reason text not null check (reason in ('initial','late_data','definition_change')),
  correction jsonb not null default '[]'::jsonb check (jsonb_typeof(correction) = 'array' and octet_length(correction::text) <= 8192),
  trigger text not null default 'system' check (trigger in ('user','system')),
  created_at timestamptz not null default now(),
  constraint pr_proof_revisions_period check (period_end > period_start),
  unique (workspace_id, id),
  unique (workspace_id, proof_id, revision)
);
create index if not exists pr_proof_revisions_list on public.pr_proof_revisions (workspace_id, frequency, period_start desc, revision desc);
create index if not exists pr_proof_revisions_occurred on public.pr_proof_revisions (workspace_id, created_at, id);

-- Bounded cron bookkeeping for proof recomputation (service only).
create table if not exists public.pr_proof_schedule (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  checked_at timestamptz not null
);
create index if not exists pr_proof_schedule_due on public.pr_proof_schedule (checked_at);
alter table public.pr_proof_schedule enable row level security;
alter table public.pr_proof_schedule force row level security;
revoke all on public.pr_proof_schedule from public, anon, authenticated;
grant all on public.pr_proof_schedule to service_role;
drop policy if exists service_only on public.pr_proof_schedule;
create policy service_only on public.pr_proof_schedule for all to service_role using (true) with check (true);

-- Versioned next-week strategy decisions: one row per version (proposed → accepted | edited | rejected; accepted or
-- edited → edited | revoked). Scoped to goal/account/language/format. Never identity, voice or publishing authority.
create table if not exists public.pr_strategy_decisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  decision_id text not null check (decision_id ~ '^sd_[0-9a-f]{20}$'),
  revision integer not null check (revision between 1 and 1000),
  status text not null check (status in ('proposed','accepted','edited','rejected','revoked')),
  kind text not null check (kind in ('experiment_preference','brief_topic')),
  statement text not null check (length(statement) between 3 and 240),
  scope jsonb not null default '{}'::jsonb check (jsonb_typeof(scope) = 'object' and octet_length(scope::text) <= 1024),
  basis jsonb not null default '{}'::jsonb check (jsonb_typeof(basis) = 'object' and octet_length(basis::text) <= 2048),
  proof_revision_id uuid,
  applies_from timestamptz,
  decided_by uuid,
  idempotency_key text check (idempotency_key is null or idempotency_key ~ '^[A-Za-z0-9_-]{8,80}$'),
  request_digest text check (request_digest is null or request_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (workspace_id, id),
  unique (workspace_id, decision_id, revision),
  constraint pr_strategy_decisions_proof foreign key (workspace_id, proof_revision_id) references public.pr_proof_revisions(workspace_id, id) on delete cascade,
  constraint pr_strategy_decisions_decided check ((status = 'proposed') = (decided_by is null))
);
create unique index if not exists pr_strategy_decisions_key on public.pr_strategy_decisions (workspace_id, idempotency_key) where idempotency_key is not null;
create index if not exists pr_strategy_decisions_latest on public.pr_strategy_decisions (workspace_id, decision_id, revision desc);
create index if not exists pr_strategy_decisions_occurred on public.pr_strategy_decisions (workspace_id, created_at desc, id desc);

-- Proof revisions and decision versions never change once written; workspace deletion still removes them.
create or replace function postriff_private.growth_loop_rows_immutable() returns trigger language plpgsql set search_path='' as $$
begin
  raise exception 'Proof revisions and strategy decision versions are append-only' using errcode = '42501';
end $$;
create or replace trigger pr_proof_revisions_immutable before update on public.pr_proof_revisions
  for each row execute function postriff_private.growth_loop_rows_immutable();
create or replace trigger pr_strategy_decisions_immutable before update on public.pr_strategy_decisions
  for each row execute function postriff_private.growth_loop_rows_immutable();

do $$
declare t text;
begin
  foreach t in array array['pr_brief_editions','pr_brief_actions','pr_proof_revisions','pr_strategy_decisions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('drop policy if exists trusted_write on public.%I', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;
-- A brief and its actions belong to their recipient.
drop policy if exists own_read on public.pr_brief_editions;
create policy own_read on public.pr_brief_editions for select to authenticated
  using (recipient_user_id = (select auth.uid()) and postriff_private.member(workspace_id));
drop policy if exists own_read on public.pr_brief_actions;
create policy own_read on public.pr_brief_actions for select to authenticated
  using (actor_user_id = (select auth.uid()) and postriff_private.member(workspace_id));
-- Proof revisions carry provider cost figures: owners only, like the usage ledger (014).
drop policy if exists owner_read on public.pr_proof_revisions;
create policy owner_read on public.pr_proof_revisions for select to authenticated using (
  postriff_private.member(workspace_id) and exists (
    select 1 from public.pr_memberships m
    where m.workspace_id = pr_proof_revisions.workspace_id and m.user_id = (select auth.uid()) and m.status = 'active' and m.role = 'owner'));
drop policy if exists tenant_read on public.pr_strategy_decisions;
create policy tenant_read on public.pr_strategy_decisions for select to authenticated using (postriff_private.member(workspace_id));

commit;
