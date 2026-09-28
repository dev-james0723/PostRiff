-- One-time web-to-telephone admission. Raw codes, caller numbers and audio are never stored.
alter table public.pr_phone_calls add column if not exists direction text not null default 'outbound'
  check (direction in ('outbound','inbound'));
create table if not exists public.pr_phone_inbound_codes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid references public.pr_conversations(id) on delete cascade,
  code_hash text not null unique check(code_hash ~ '^[0-9a-f]{64}$'),
  maximum_millicredits bigint check(maximum_millicredits between 0 and 100000000),
  created_at timestamptz not null default now(), expires_at timestamptz not null,
  consumed_at timestamptz, revoked_at timestamptz,
  call_id uuid unique references public.pr_phone_calls(id) on delete cascade
);
create index if not exists pr_phone_inbound_codes_user on public.pr_phone_inbound_codes(user_id,created_at desc);
create table if not exists public.pr_phone_inbound_sessions (
  provider_call_ref text primary key check(length(provider_call_ref) between 1 and 100),
  caller_hash text not null check(caller_hash ~ '^[0-9a-f]{64}$'),
  started_at timestamptz not null default now(), ended_at timestamptz,
  attempts integer not null default 0 check(attempts between 0 and 3),
  call_id uuid unique references public.pr_phone_calls(id) on delete set null
);
create index if not exists pr_phone_inbound_sessions_started on public.pr_phone_inbound_sessions(started_at);
do $$ declare t text; begin
  foreach t in array array['pr_phone_inbound_codes','pr_phone_inbound_sessions'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
    end if;
  end loop;
end $$;
