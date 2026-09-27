-- Server-owned Phone Mode identity and lifecycle. No audio, raw numbers, provider payloads or reusable auth tokens.
create table if not exists public.pr_phone_numbers (
  user_id uuid primary key references public.pr_profiles(user_id) on delete cascade,
  phone_ciphertext text not null, phone_hash text not null check (phone_hash ~ '^[0-9a-f]{64}$'), key_id text not null,
  last_four text not null check (last_four ~ '^[0-9]{4}$'), verified_at timestamptz,
  verification_ref text, verification_started_at timestamptz, verification_attempts integer not null default 0,
  verification_day date, verification_sends integer not null default 0,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.pr_phone_preferences (
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  preferences jsonb not null default '{}'::jsonb check (jsonb_typeof(preferences)='object' and pg_column_size(preferences)<=2048),
  updated_at timestamptz not null default now(), primary key(user_id,workspace_id)
);
-- Cost/rate limits survive number revocation without retaining a phone number.
create table if not exists public.pr_phone_verification_limits (
  user_id uuid primary key references public.pr_profiles(user_id) on delete cascade,
  last_sent_at timestamptz not null, sent_day date not null default current_date,
  sends integer not null check(sends between 1 and 5)
);
create table if not exists public.pr_phone_calls (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid references public.pr_conversations(id) on delete cascade,
  voice_run_id uuid references public.pr_agent_runs(id) on delete set null,
  kind text not null check(kind in ('explicit','scheduled','proactive')), reason_key text not null check(length(reason_key)<=200),
  provider text not null check(provider in ('fake','twilio','telnyx')), provider_call_ref text check(length(provider_call_ref)<=100),
  state text not null check(state in ('requested','dialing','ringing','answered','live','ending','completed','busy','declined','no_answer','voicemail','failed','ambiguous','cancelled')),
  idempotency_key text not null check(length(idempotency_key) between 8 and 100),
  number_hash text not null, max_seconds integer not null check(max_seconds between 60 and 600),
  live_reservation_id uuid, telephony_reservation_id uuid,
  reserved_usd_micro bigint not null check(reserved_usd_micro>=0), telephony_cost_usd_micro bigint, live_cost_usd_micro bigint,
  billing_basis text, failure_class text check(length(failure_class)<=80),
  requested_at timestamptz not null default now(), dialing_at timestamptz, ringing_at timestamptz, answered_at timestamptz, ended_at timestamptz,
  duration_seconds integer check(duration_seconds between 0 and 86400), live_usage_seconds numeric,
  media_claimed_at timestamptz, unique(user_id,idempotency_key), unique(provider,provider_call_ref)
);
create index if not exists pr_phone_calls_daily on public.pr_phone_calls(user_id,requested_at desc);
create index if not exists pr_phone_calls_due on public.pr_phone_calls(requested_at) where state in ('requested','dialing','ambiguous','ending');
create table if not exists public.pr_phone_provider_events (
  provider text not null, event_id text not null check(length(event_id) between 1 and 200),
  call_id uuid not null references public.pr_phone_calls(id) on delete cascade,
  state text not null, received_at timestamptz not null default now(), primary key(provider,event_id)
);
create table if not exists public.pr_phone_delegations (
  call_id uuid not null references public.pr_phone_calls(id) on delete cascade,
  delegation_id text not null check(length(delegation_id) between 1 and 120),
  state text not null check(state in ('running','completed','failed')), run_id uuid,
  summary text check(length(summary)<=1200), created_at timestamptz not null default now(), primary key(call_id,delegation_id)
);
-- Use the existing cron and campaigns.next_occurrence scheduling policy; no separate scheduler.
create table if not exists public.pr_phone_schedules (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid references public.pr_conversations(id) on delete cascade,
  schedule jsonb not null check(jsonb_typeof(schedule)='object' and pg_column_size(schedule)<=1024),
  enabled boolean not null default true, next_at timestamptz not null, created_at timestamptz not null default now()
);
do $$ declare t text; begin
  foreach t in array array['pr_phone_numbers','pr_phone_preferences','pr_phone_verification_limits','pr_phone_calls','pr_phone_provider_events','pr_phone_delegations','pr_phone_schedules'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
    end if;
  end loop;
end $$;
alter table public.pr_notification_deliveries drop constraint if exists pr_notification_deliveries_channel_check;
alter table public.pr_notification_deliveries add constraint pr_notification_deliveries_channel_check check(channel in ('in_app','email','push','phone'));
