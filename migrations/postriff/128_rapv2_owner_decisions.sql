-- Rafii Account Protection v2: the schema for James's decisions of 2026-10-16 (docs/rapv2/blocked-features-decisions-2026-10-15.md).
-- Numbered 128: 124-126 are taken by the Discord release branch and 127 is RAPv2 retention.
--
-- 1. Decision 5, the incident banner. pr_security_incidents gains reported_session_id (the session that filed the
--    report, which never needs the banner) and notice_dismissed_at (when the person dismissed the in-app banner shown at
--    their next sign-in). Both nullable; existing rows read "not dismissed, reporter unknown".
-- 2. Decision 6, step-up notices. pr_security_login_events may record 'session.step_up_challenged' (one row per session,
--    capability and minute at most) so repeated failed step-ups can be counted, and 'session.step_up_failed' /
--    'session.sign_in_blocked' (the facts a security notice is sent for). Successful step-ups keep their existing
--    'session.step_up_verified' row and send nothing.
-- 3. Decision 7, notices to the previous address. pr_security_contact_changes keeps the address an account had before an
--    email change, for 14 days, so security notices can also go there. A trigger on auth.users records it when the
--    confirmed address changes; it never raises (an email change must never fail because of this table) and it deletes
--    every row older than 14 days on each write. The account deletion purge removes a person's rows.
--
-- Nothing here changes behaviour on its own: the routes and notices that use these columns are off until
-- RAFII_SECURITY_INCIDENT_HOLD (banner, previous address) or RAFII_ACCOUNT_PROTECTION_V2_MODE=enforce (step-up notices).
-- Server-only: FORCE RLS on the new table, no anon/authenticated access, service_role may only read it.
--
-- Rollback, in one transaction:
--   drop trigger rapv2_contact_change on auth.users;
--   drop function postriff_private.rapv2_record_contact_change();
--   restore public.pr_security_purge exactly as migration 122 defines it;
--   drop table public.pr_security_contact_changes;
--   restore the pr_security_login_events event_type check from migration 120 (first delete or keep any rows of the
--     three new types: the check cannot be re-added while they exist; they are security evidence, so keeping the wider
--     check is the safer rollback);
--   alter table public.pr_security_incidents drop column notice_dismissed_at, drop column reported_session_id;
begin;

-- 1. Incident banner ---------------------------------------------------------------------------------------------------
alter table public.pr_security_incidents
  add column if not exists reported_session_id text check (reported_session_id is null or length(reported_session_id) between 16 and 160),
  add column if not exists notice_dismissed_at timestamptz;

-- 2. Step-up notices ---------------------------------------------------------------------------------------------------
alter table public.pr_security_login_events drop constraint if exists pr_security_login_events_event_type_check;
alter table public.pr_security_login_events add constraint pr_security_login_events_event_type_check check (event_type in (
  'session.observed', 'device.first_observed', 'device.trusted', 'device.revoked',
  'session.step_up_verified', 'session.risk_reassessed', 'session.revoked',
  'account.hold_placed', 'account.hold_released', 'incident.reported', 'incident.resolved',
  'session.step_up_challenged', 'session.step_up_failed', 'session.sign_in_blocked'
));
create index if not exists pr_security_login_events_challenges on public.pr_security_login_events (user_id, session_id, occurred_at desc)
  where event_type = 'session.step_up_challenged';

-- 3. Previous address for 14 days ----------------------------------------------------------------------------------------
create table if not exists public.pr_security_contact_changes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  previous_email text not null check (length(previous_email) between 3 and 320 and previous_email like '%@%'),
  changed_at timestamptz not null default now()
);
create index if not exists pr_security_contact_changes_user on public.pr_security_contact_changes (user_id, changed_at desc);
create index if not exists pr_security_contact_changes_age on public.pr_security_contact_changes (changed_at);

create or replace function postriff_private.rapv2_record_contact_change() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if old.email is not null and new.email is not null and lower(old.email) <> lower(new.email) then
    begin
      delete from public.pr_security_contact_changes where changed_at < now() - interval '14 days';
      insert into public.pr_security_contact_changes (user_id, previous_email) values (new.id, left(old.email, 320));
    exception when others then
      -- Never let this record stop the identity provider from changing an address.
      raise warning 'rapv2 contact change not recorded: %', sqlstate;
    end;
  end if;
  return new;
end $$;
revoke all on function postriff_private.rapv2_record_contact_change() from public, anon, authenticated, service_role;
drop trigger if exists rapv2_contact_change on auth.users;
create trigger rapv2_contact_change after update of email on auth.users
  for each row execute function postriff_private.rapv2_record_contact_change();

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
  delete from public.pr_security_contact_changes where user_id = p_user;
  perform set_config('rapv2.purge_user', '', true);
end $$;
revoke all on function public.pr_security_purge(uuid) from public, anon, authenticated;
grant execute on function public.pr_security_purge(uuid) to service_role;

alter table public.pr_security_contact_changes enable row level security;
alter table public.pr_security_contact_changes force row level security;
revoke all on public.pr_security_contact_changes from public, anon, authenticated;
-- Supabase's default privileges grant service_role ALL on new tables: take that back, then grant only the design.
revoke all on public.pr_security_contact_changes from service_role;
grant select on public.pr_security_contact_changes to service_role;
drop policy if exists rapv2_service_only on public.pr_security_contact_changes;
create policy rapv2_service_only on public.pr_security_contact_changes for select to service_role using (true);

commit;
