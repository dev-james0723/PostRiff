-- Verifier-only native registry projections. This is not native execution proof.
begin;
create table if not exists public.pr_agent_team_mission_registry (
  mission_id text not null,
  actor_id uuid not null references public.pr_profiles(user_id),
  workspace_id uuid not null references public.pr_workspaces(id),
  registration_sha256 text not null check(registration_sha256 ~ '^[0-9a-f]{64}$'),
  execution_sha256 text not null check(execution_sha256 ~ '^[0-9a-f]{64}$'),
  ordinal integer not null check(ordinal>=0),
  registration_document jsonb not null check(jsonb_typeof(registration_document)='object'),
  execution_document jsonb not null check(jsonb_typeof(execution_document)='object'),
  attestation_document jsonb not null check(jsonb_typeof(attestation_document)='object'),
  attestation_sha256 text not null check(attestation_sha256 ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key(mission_id,attestation_sha256)
);
create index if not exists pr_agent_team_registry_current
  on public.pr_agent_team_mission_registry(mission_id,actor_id,workspace_id,ordinal desc,observed_at desc);
alter table public.pr_agent_team_mission_registry enable row level security;
alter table public.pr_agent_team_mission_registry force row level security;
revoke all on public.pr_agent_team_mission_registry from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_mission_registry to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_mission_registry' and policyname='service_registry_read') then
    create policy service_registry_read on public.pr_agent_team_mission_registry for select to service_role using(true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_mission_registry' and policyname='service_registry_insert') then
    create policy service_registry_insert on public.pr_agent_team_mission_registry for insert to service_role with check(true);
  end if;
end $$;
create or replace function postriff_private.agent_team_immutable_registry() returns trigger
language plpgsql set search_path=pg_catalog as $$ begin
  raise exception 'Immutable Agent Team registry projection';
end $$;
drop trigger if exists pr_agent_team_immutable_registry on public.pr_agent_team_mission_registry;
create trigger pr_agent_team_immutable_registry before update or delete on public.pr_agent_team_mission_registry
  for each row execute function postriff_private.agent_team_immutable_registry();
revoke all on function postriff_private.agent_team_immutable_registry() from public,anon,authenticated;
create table if not exists public.pr_agent_team_native_receipts (
  decision_key text not null references public.pr_agent_team_decisions(decision_key) on delete restrict,
  resume_request_id text,
  receipt_sha256 text not null check(receipt_sha256 ~ '^[0-9a-f]{64}$'),
  execution_state text not null check(execution_state in ('blocked','unknown','resumed','turn_started','wait','needs_human')),
  document jsonb not null check(jsonb_typeof(document)='object'),
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key(decision_key,receipt_sha256),
  unique(decision_key,resume_request_id),
  unique(receipt_sha256)
);
alter table public.pr_agent_team_native_receipts enable row level security;
alter table public.pr_agent_team_native_receipts force row level security;
revoke all on public.pr_agent_team_native_receipts from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_native_receipts to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_native_receipts' and policyname='service_native_receipt_read') then
    create policy service_native_receipt_read on public.pr_agent_team_native_receipts for select to service_role using(true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_native_receipts' and policyname='service_native_receipt_insert') then
    create policy service_native_receipt_insert on public.pr_agent_team_native_receipts for insert to service_role with check(true);
  end if;
end $$;
drop trigger if exists pr_agent_team_immutable_native_receipt on public.pr_agent_team_native_receipts;
create trigger pr_agent_team_immutable_native_receipt before update or delete on public.pr_agent_team_native_receipts
  for each row execute function postriff_private.agent_team_immutable_registry();
commit;
