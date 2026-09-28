-- Routing hints only. Existing Supabase MFA owns all passkeys and biometric verification.
create table public.pr_phone_trusted_callers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  caller_hash text not null check(caller_hash ~ '^[0-9a-f]{64}$'),
  created_from_code_id uuid references public.pr_phone_inbound_codes(id) on delete set null,
  verified_at timestamptz not null, last_used_at timestamptz,
  revoked_at timestamptz, suppressed_until timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(user_id,workspace_id,caller_hash)
);
create index pr_phone_trusted_caller_lookup on public.pr_phone_trusted_callers(caller_hash) where revoked_at is null;
create table public.pr_phone_auth_challenges (
  id uuid primary key default gen_random_uuid(),
  provider_call_ref text not null unique references public.pr_phone_inbound_sessions(provider_call_ref) on delete cascade,
  trusted_caller_id uuid not null references public.pr_phone_trusted_callers(id) on delete cascade,
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  caller_hash text not null check(caller_hash ~ '^[0-9a-f]{64}$'),
  state text not null default 'pending' check(state in ('pending','approved','denied','expired','consumed','fallback')),
  created_at timestamptz not null, expires_at timestamptz not null,
  ceremony_attempts integer not null default 0 check(ceremony_attempts between 0 and 3),
  factor_id uuid, factor_challenge_id uuid unique, ceremony_session_id text,
  ceremony_started_at timestamptz, verification_used boolean not null default false,
  approved_at timestamptz, consumed_at timestamptz, approved_session_id text,
  approved_factor_kind text check(approved_factor_kind is null or approved_factor_kind='webauthn'),
  call_id uuid unique references public.pr_phone_calls(id) on delete set null,
  maximum_millicredits bigint check(maximum_millicredits between 0 and 100000000),
  use_available_credits boolean not null default false,
  check(expires_at>created_at)
);
create index pr_phone_auth_user_time on public.pr_phone_auth_challenges(user_id,created_at desc);
-- Each fallback gets one separate 45-second window, without resetting the three-attempt counter.
alter table public.pr_phone_inbound_sessions add column pairing_started_at timestamptz;
do $$ declare t text; begin
  foreach t in array array['pr_phone_trusted_callers','pr_phone_auth_challenges'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
  end loop;
end $$;
