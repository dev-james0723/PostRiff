-- Rafii Account Protection v2, P1 item 1: device registry.
--
-- Three server-only tables that tell a new *session* apart from a new *browser*:
--   pr_security_devices       one row per person per first-party browser instance. The instance is identified by the
--                             opaque __Host-rafii_device cookie, stored only as HMAC-SHA-256(key, user || cookie) with
--                             the key version; never the raw cookie, IP or full User-Agent.
--   pr_session_security       per-session security state (risk level, enforcement mode, policy version, device link).
--                             It mirrors pr_session_revocations and never replaces it: the verifier still refuses a
--                             revoked session from that table alone.
--   pr_security_login_events  an append-only ledger: `session.observed` once per session, `device.first_observed`
--                             once per device, and the later P1 events.
--
-- Reviewed against the preflight (§5): composite FKs so a session or event can only point at the same person's
-- device; no ON DELETE CASCADE that could silently drop enforcement state; FORCE RLS with no anon/authenticated
-- access at all (service_role only); the ledger is append-only for every role, the table owner included, enforced by
-- a trigger rather than by grants alone (the hosted API connects as the owner). The one exception is the account
-- deletion purge, which only works for a person who already has a deletion tombstone.
--
-- Additive. Nothing reads or writes these tables unless RAFII_DEVICE_TRUST_V2 is on (default off). Rollback: turn the
-- flag off; the tables can stay (they hold no secrets). Dropping them is a separate, reviewed decision because the
-- ledger is security evidence.
begin;

create table public.pr_security_devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  token_hash text not null check (token_hash ~ '^[0-9a-f]{64}$'),
  hmac_key_version smallint not null check (hmac_key_version between 1 and 100),
  state text not null default 'observed' check (state in ('observed', 'trusted', 'revoked')),
  surface text not null default 'web' check (surface in ('web', 'pwa', 'native', 'unknown')),
  display_label text not null default 'Unrecognized browser' check (length(display_label) between 1 and 80),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  trusted_at timestamptz,
  trust_expires_at timestamptz,
  revoked_at timestamptz,
  revoke_reason text check (revoke_reason is null or length(revoke_reason) <= 80),
  last_proof_method text check (last_proof_method is null or last_proof_method in ('totp', 'webauthn_mfa', 'passkey_fresh', 'manual_recovery')),
  check (state <> 'trusted' or trusted_at is not null),
  check (state <> 'revoked' or revoked_at is not null),
  check (trust_expires_at is null or trusted_at is not null),
  -- A revoked instance never comes back under the same token: a new cookie makes a new row.
  unique (user_id, token_hash),
  unique (user_id, id)
);
create index pr_security_devices_recent_user on public.pr_security_devices (user_id, last_seen_at desc);

create table public.pr_session_security (
  user_id uuid not null,
  session_id text not null check (length(session_id) between 16 and 160),
  device_id uuid,
  risk_level text not null default 'low' check (risk_level in ('low', 'medium', 'high', 'critical')),
  enforcement text not null default 'allow' check (enforcement in ('allow', 'challenge', 'blocked', 'revoked')),
  risk_reasons jsonb not null default '[]'::jsonb check (jsonb_typeof(risk_reasons) = 'array' and pg_column_size(risk_reasons) <= 2048),
  policy_version integer not null default 1 check (policy_version > 0),
  first_seen_at timestamptz not null default now(),
  last_evaluated_at timestamptz not null default now(),
  step_up_at timestamptz,
  step_up_method text check (step_up_method is null or step_up_method in ('totp', 'webauthn_mfa', 'passkey_fresh', 'manual_recovery')),
  version bigint not null default 1 check (version > 0),
  primary key (user_id, session_id),
  -- RESTRICT, not CASCADE: cleaning up pr_sessions must never silently drop a session's enforcement state.
  foreign key (user_id, session_id) references public.pr_sessions (user_id, session_id) on delete restrict,
  foreign key (user_id, device_id) references public.pr_security_devices (user_id, id) on delete restrict,
  check (step_up_method is null or step_up_at is not null)
);
create index pr_session_security_device on public.pr_session_security (user_id, device_id);

create table public.pr_security_login_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  session_id text check (session_id is null or length(session_id) between 16 and 160),
  device_id uuid,
  event_type text not null check (event_type in (
    'session.observed', 'device.first_observed', 'device.trusted', 'device.revoked',
    'session.step_up_verified', 'session.risk_reassessed', 'session.revoked',
    'account.hold_placed', 'account.hold_released', 'incident.reported', 'incident.resolved'
  )),
  event_key text not null check (length(event_key) between 16 and 180),
  occurred_at timestamptz not null default now(),
  details jsonb not null default '{}'::jsonb check (jsonb_typeof(details) = 'object' and pg_column_size(details) <= 4096),
  risk_level text check (risk_level is null or risk_level in ('low', 'medium', 'high', 'critical')),
  unique (user_id, event_key),
  -- Lets a later table reference an event of the same person only: (user_id, source_event_id).
  unique (user_id, id),
  foreign key (user_id, device_id) references public.pr_security_devices (user_id, id) on delete restrict
);
-- Exactly one first observation per session and per device; repeatable events use their own event_key.
create unique index pr_security_first_session_once on public.pr_security_login_events (user_id, session_id)
  where event_type = 'session.observed' and session_id is not null;
create unique index pr_security_first_device_once on public.pr_security_login_events (user_id, device_id)
  where event_type = 'device.first_observed' and device_id is not null;
create index pr_security_login_events_recent_user on public.pr_security_login_events (user_id, occurred_at desc);

-- Append-only for every role, the owner included. The only delete is the purge below, for a deleted account.
create or replace function postriff_private.rapv2_login_events_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    if current_setting('rapv2.purge_user', true) = old.user_id::text
       and exists (select 1 from public.pr_account_tombstones t where t.user_id = old.user_id) then
      return old;
    end if;
  end if;
  raise exception 'pr_security_login_events is append-only' using errcode = '42501';
end $$;
create trigger pr_security_login_events_append_only
  before update or delete on public.pr_security_login_events
  for each row execute function postriff_private.rapv2_login_events_immutable();
create trigger pr_security_login_events_no_truncate
  before truncate on public.pr_security_login_events
  for each statement execute function postriff_private.rapv2_login_events_immutable();

-- Account deletion (account_deletion.py) erases a person's security state in its own transaction, after it has
-- written the tombstone. Refuses for anyone without one, so it cannot be used to wipe a live account's evidence.
create or replace function public.pr_security_purge(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.pr_account_tombstones where user_id = p_user) then
    raise exception 'security state is purged only for a deleted account' using errcode = '42501';
  end if;
  perform set_config('rapv2.purge_user', p_user::text, true);
  delete from public.pr_security_login_events where user_id = p_user;
  delete from public.pr_session_security where user_id = p_user;
  delete from public.pr_security_devices where user_id = p_user;
  perform set_config('rapv2.purge_user', '', true);
end $$;
revoke all on function public.pr_security_purge(uuid) from public, anon, authenticated;
grant execute on function public.pr_security_purge(uuid) to service_role;

alter table public.pr_security_devices enable row level security;
alter table public.pr_security_devices force row level security;
alter table public.pr_session_security enable row level security;
alter table public.pr_session_security force row level security;
alter table public.pr_security_login_events enable row level security;
alter table public.pr_security_login_events force row level security;
revoke all on public.pr_security_devices, public.pr_session_security, public.pr_security_login_events from public, anon, authenticated;
-- Supabase's default privileges grant service_role ALL on new tables: take that back, then grant only the design.
revoke all on public.pr_security_devices, public.pr_session_security, public.pr_security_login_events from service_role;
grant select, insert, update on public.pr_security_devices, public.pr_session_security to service_role;
grant select, insert on public.pr_security_login_events to service_role;
create policy rapv2_service_only on public.pr_security_devices for all to service_role using (true) with check (true);
create policy rapv2_service_only on public.pr_session_security for all to service_role using (true) with check (true);
create policy rapv2_service_only on public.pr_security_login_events for all to service_role using (true) with check (true);

commit;
