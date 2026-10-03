-- James Daily Call: env-only destination reference, read-only Google Calendar connector,
-- bounded one-retry orchestration, and post-call/fallback state. Never stores a raw phone number.
begin;

alter table public.pr_phone_calls add column if not exists destination_ref text;
alter table public.pr_phone_calls drop constraint if exists pr_phone_calls_destination_ref_check;
alter table public.pr_phone_calls add constraint pr_phone_calls_destination_ref_check
  check (destination_ref is null or destination_ref in ('james_env'));
create index if not exists pr_phone_calls_destination on public.pr_phone_calls(destination_ref,requested_at desc)
  where destination_ref is not null;

alter table public.pr_connector_oauth_transactions drop constraint if exists pr_connector_oauth_transactions_provider_check;
alter table public.pr_connector_oauth_transactions add constraint pr_connector_oauth_transactions_provider_check
  check (provider in ('notion','gmail','google_calendar'));
alter table public.pr_connector_credentials drop constraint if exists pr_connector_credentials_provider_check;
alter table public.pr_connector_credentials add constraint pr_connector_credentials_provider_check
  check (provider in ('notion','gmail','google_calendar'));
alter table public.pr_connector_selections drop constraint if exists pr_connector_selections_provider_check;
alter table public.pr_connector_selections add constraint pr_connector_selections_provider_check
  check (provider in ('notion','gmail','google_calendar'));
alter table public.pr_connector_fetches drop constraint if exists pr_connector_fetches_providers_check;
alter table public.pr_connector_fetches add constraint pr_connector_fetches_providers_check
  check (providers <@ array['notion','gmail','google_calendar']::text[]);

create table if not exists public.pr_james_daily_call_runs (
  id uuid primary key default gen_random_uuid(),
  slot_key text not null unique check(length(slot_key) between 8 and 160),
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid references public.pr_conversations(id) on delete set null,
  state text not null check(state in ('preparing','ready','dialing','retry_wait','push_fallback','completed','failed','blocked')),
  origin text not null check(origin in ('acceptance','scheduled')),
  masked_destination text not null check(length(masked_destination) between 4 and 32),
  context jsonb not null default '{}'::jsonb check(jsonb_typeof(context)='object' and pg_column_size(context)<=65536),
  source_ids text[] not null default '{}' check(cardinality(source_ids)<=30),
  first_call_id uuid references public.pr_phone_calls(id) on delete set null,
  retry_call_id uuid references public.pr_phone_calls(id) on delete set null,
  attempt_count integer not null default 0 check(attempt_count between 0 and 2),
  retry_at timestamptz,
  fallback_sent boolean not null default false,
  summary text check(summary is null or length(summary)<=4000),
  follow_ups jsonb not null default '[]'::jsonb check(jsonb_typeof(follow_ups)='array' and pg_column_size(follow_ups)<=16384),
  failure_class text check(failure_class is null or length(failure_class)<=80),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists pr_james_daily_call_due on public.pr_james_daily_call_runs(state,retry_at)
  where state in ('dialing','retry_wait','ready');

alter table public.pr_james_daily_call_runs enable row level security;
alter table public.pr_james_daily_call_runs force row level security;
revoke all on public.pr_james_daily_call_runs from public,anon,authenticated;
grant all on public.pr_james_daily_call_runs to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_james_daily_call_runs' and policyname='service_only') then
    create policy service_only on public.pr_james_daily_call_runs for all to service_role using(true) with check(true);
  end if;
end $$;

commit;
