-- Rafii Account Protection v2, P1 item 4: "This wasn't me" incidents.
--
-- One row per incident a person reports from their own signed-in Security settings (POST /api/auth/security/incidents).
-- The incident can only cite a ledger event of the same person: composite FK (user_id, source_event_id) →
-- pr_security_login_events (user_id, id) (preflight §5). Idempotency keys are scoped to the person. Rows change state
-- (open → user_confirmed → recovering → resolved) but are never deleted, except by the account deletion purge.
-- Server-only: FORCE RLS, no anon/authenticated access, service_role only.
--
-- Additive. Nothing reads or writes it unless RAFII_SECURITY_INCIDENT_HOLD is on (default off).
begin;

create table public.pr_security_incidents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  source_event_id uuid,
  state text not null default 'open' check (state in ('open', 'user_confirmed', 'recovering', 'resolved')),
  summary_code text not null check (summary_code ~ '^[a-z0-9_.]{3,80}$'),
  resolution_code text check (resolution_code is null or resolution_code ~ '^[a-z0-9_.]{3,80}$'),
  hold_epoch bigint check (hold_epoch is null or hold_epoch > 0),
  sessions_revoked integer not null default 0 check (sessions_revoked >= 0),
  idempotency_key text check (idempotency_key is null or length(idempotency_key) between 16 and 120),
  request_digest text check (request_digest is null or request_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  confirmed_at timestamptz,
  resolved_at timestamptz,
  check (state <> 'resolved' or resolved_at is not null),
  check (state = 'open' or confirmed_at is not null),
  check ((idempotency_key is null) = (request_digest is null)),
  unique (user_id, id),
  unique (user_id, idempotency_key),
  foreign key (user_id, source_event_id) references public.pr_security_login_events (user_id, id) on delete restrict
);
create index pr_security_incidents_recent_user on public.pr_security_incidents (user_id, created_at desc);

create or replace function postriff_private.rapv2_incidents_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    if current_setting('rapv2.purge_user', true) = old.user_id::text
       and exists (select 1 from public.pr_account_tombstones t where t.user_id = old.user_id) then
      return old;
    end if;
  end if;
  raise exception 'security incidents are never deleted' using errcode = '42501';
end $$;
create trigger pr_security_incidents_no_delete
  before delete on public.pr_security_incidents
  for each row execute function postriff_private.rapv2_incidents_guard();
create trigger pr_security_incidents_no_truncate
  before truncate on public.pr_security_incidents
  for each statement execute function postriff_private.rapv2_incidents_guard();

create or replace function public.pr_security_purge(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.pr_account_tombstones where user_id = p_user) then
    raise exception 'security state is purged only for a deleted account' using errcode = '42501';
  end if;
  perform set_config('rapv2.purge_user', p_user::text, true);
  delete from public.pr_security_incidents where user_id = p_user;
  delete from public.pr_security_login_events where user_id = p_user;
  delete from public.pr_session_security where user_id = p_user;
  delete from public.pr_security_devices where user_id = p_user;
  delete from public.pr_security_account_controls where user_id = p_user;
  perform set_config('rapv2.purge_user', '', true);
end $$;
revoke all on function public.pr_security_purge(uuid) from public, anon, authenticated;
grant execute on function public.pr_security_purge(uuid) to service_role;

alter table public.pr_security_incidents enable row level security;
alter table public.pr_security_incidents force row level security;
revoke all on public.pr_security_incidents from public, anon, authenticated;
grant select, insert, update on public.pr_security_incidents to service_role;
create policy rapv2_service_only on public.pr_security_incidents for all to service_role using (true) with check (true);

commit;
