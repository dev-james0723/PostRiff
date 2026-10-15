-- Rafii Account Protection v2, RAP-137: retention for session-security records.
-- Numbered 127: 124-126 are taken by the Discord release branch (codex/rafii-discord-release-20261015).
--
-- public.pr_security_retention_purge(p_days, p_dry_run, p_limit) removes, for people with no open incident and no
-- active hold, the records older than p_days:
--   pr_security_login_events  events that occurred before the cutoff and that no incident cites;
--   pr_session_security       per-session state last evaluated before the cutoff;
--   pr_security_devices       browsers revoked, or last seen, before the cutoff that nothing above still references.
-- Incidents (pr_security_incidents) and account controls (pr_security_account_controls) are never removed here: they
-- are kept until account deletion (pr_security_purge). Everything of a person with an open incident or an active hold
-- is kept whatever its age (incident preservation). p_dry_run counts what would go and deletes nothing. Every run,
-- dry or not, leaves one row in pr_security_retention_runs with its counts only (no user ids).
--
-- The ledger stays append-only: its trigger now also lets a delete through when this function has set
-- rapv2.retention_cutoff for its own transaction, the row is older than that cutoff, the cutoff is at least 90 days
-- old, and the person has no open incident and no active hold. Any other update, delete or truncate still raises.
--
-- p_days is clamped to the approved floor: below 90 or above 3650 raises. The worker (security_retention.py) runs
-- only when RAFII_SECURITY_RETENTION is `dry_run` or `on` (default off) with RAFII_SECURITY_RETENTION_DAYS (default
-- 400); nothing calls this function otherwise.
--
-- Additive, server-only: FORCE RLS on the new table, no anon/authenticated access, service_role only.
--
-- Rollback, in one transaction: restore postriff_private.rapv2_login_events_immutable() exactly as migration 120
-- defines it (this file only adds the retention branch), then
--   drop function public.pr_security_retention_purge(integer, boolean, integer);
--   drop table public.pr_security_retention_runs;
-- Rows already deleted by a non-dry run are not restorable (that is the purpose of retention); the run table records
-- how many went.
begin;

create table public.pr_security_retention_runs (
  id uuid primary key default gen_random_uuid(),
  ran_at timestamptz not null default now(),
  dry_run boolean not null,
  retention_days integer not null check (retention_days between 90 and 3650),
  cutoff timestamptz not null,
  counts jsonb not null default '{}'::jsonb check (jsonb_typeof(counts) = 'object' and pg_column_size(counts) <= 2048)
);
create index pr_security_retention_runs_recent on public.pr_security_retention_runs (ran_at desc);

create or replace function postriff_private.rapv2_login_events_immutable() returns trigger
language plpgsql set search_path = '' as $$
declare cutoff timestamptz;
begin
  if tg_op = 'DELETE' then
    if current_setting('rapv2.purge_user', true) = old.user_id::text
       and exists (select 1 from public.pr_account_tombstones t where t.user_id = old.user_id) then
      return old;
    end if;
    if coalesce(current_setting('rapv2.retention_cutoff', true), '') <> '' then
      cutoff := current_setting('rapv2.retention_cutoff', true)::timestamptz;
      if cutoff <= now() - interval '90 days' and old.occurred_at < cutoff
         and not exists (select 1 from public.pr_security_incidents i where i.user_id = old.user_id and i.state <> 'resolved')
         and not exists (select 1 from public.pr_security_account_controls c where c.user_id = old.user_id and c.hold_active) then
        return old;
      end if;
    end if;
  end if;
  raise exception 'pr_security_login_events is append-only' using errcode = '42501';
end $$;

create or replace function public.pr_security_retention_purge(p_days integer, p_dry_run boolean default true, p_limit integer default 5000)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  cutoff timestamptz;
  events integer;
  sessions integer;
  devices integer;
  preserved integer;
  result jsonb;
begin
  if p_days is null or p_days < 90 or p_days > 3650 then
    raise exception 'retention must be between 90 and 3650 days' using errcode = '22023';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 50000 then
    raise exception 'batch limit must be between 1 and 50000' using errcode = '22023';
  end if;
  cutoff := now() - make_interval(days => p_days);
  -- Scratch tables for this call only (a second call in the same transaction starts clean).
  drop table if exists pg_temp.rapv2_retention_kept, pg_temp.rapv2_retention_events, pg_temp.rapv2_retention_sessions, pg_temp.rapv2_retention_devices;

  create temporary table pg_temp.rapv2_retention_kept on commit drop as
    select user_id from public.pr_security_incidents where state <> 'resolved'
    union select user_id from public.pr_security_account_controls where hold_active;
  select count(*) into preserved from pg_temp.rapv2_retention_kept;

  create temporary table pg_temp.rapv2_retention_events on commit drop as
    select e.id from public.pr_security_login_events e
    where e.occurred_at < cutoff
      and not exists (select 1 from pg_temp.rapv2_retention_kept k where k.user_id = e.user_id)
      and not exists (select 1 from public.pr_security_incidents i where i.user_id = e.user_id and i.source_event_id = e.id)
    order by e.occurred_at limit p_limit;
  create temporary table pg_temp.rapv2_retention_sessions on commit drop as
    select s.user_id, s.session_id from public.pr_session_security s
    where s.last_evaluated_at < cutoff and not exists (select 1 from pg_temp.rapv2_retention_kept k where k.user_id = s.user_id)
    limit p_limit;
  select count(*) into events from pg_temp.rapv2_retention_events;
  select count(*) into sessions from pg_temp.rapv2_retention_sessions;

  if not p_dry_run then
    perform set_config('rapv2.retention_cutoff', cutoff::text, true);
    delete from public.pr_security_login_events e using pg_temp.rapv2_retention_events x where e.id = x.id;
    perform set_config('rapv2.retention_cutoff', '', true);
    delete from public.pr_session_security s using pg_temp.rapv2_retention_sessions x where s.user_id = x.user_id and s.session_id = x.session_id;
  end if;

  -- Browsers revoked or idle before the cutoff, once no session state or ledger event points at them.
  create temporary table pg_temp.rapv2_retention_devices on commit drop as
    select d.user_id, d.id from public.pr_security_devices d
    where coalesce(d.revoked_at, d.last_seen_at) < cutoff and d.last_seen_at < cutoff
      and not exists (select 1 from pg_temp.rapv2_retention_kept k where k.user_id = d.user_id)
      and not exists (select 1 from public.pr_session_security s where s.user_id = d.user_id and s.device_id = d.id
                      and not exists (select 1 from pg_temp.rapv2_retention_sessions x where x.user_id = s.user_id and x.session_id = s.session_id))
      and not exists (select 1 from public.pr_security_login_events e where e.user_id = d.user_id and e.device_id = d.id
                      and not exists (select 1 from pg_temp.rapv2_retention_events x where x.id = e.id))
    limit p_limit;
  select count(*) into devices from pg_temp.rapv2_retention_devices;
  if not p_dry_run then
    delete from public.pr_security_devices d using pg_temp.rapv2_retention_devices x where d.user_id = x.user_id and d.id = x.id;
  end if;

  result := jsonb_build_object('dryRun', p_dry_run, 'retentionDays', p_days, 'cutoff', cutoff, 'loginEvents', events,
                               'sessionSecurity', sessions, 'devices', devices, 'preservedPeople', preserved, 'incidents', 0);
  insert into public.pr_security_retention_runs (dry_run, retention_days, cutoff, counts)
    values (p_dry_run, p_days, cutoff, result - 'cutoff');
  return result;
end $$;
revoke all on function public.pr_security_retention_purge(integer, boolean, integer) from public, anon, authenticated, service_role;
grant execute on function public.pr_security_retention_purge(integer, boolean, integer) to service_role;

alter table public.pr_security_retention_runs enable row level security;
alter table public.pr_security_retention_runs force row level security;
revoke all on public.pr_security_retention_runs from public, anon, authenticated;
-- Supabase's default privileges grant service_role ALL on new tables: take that back, then grant only the design.
revoke all on public.pr_security_retention_runs from service_role;
grant select, insert on public.pr_security_retention_runs to service_role;
create policy rapv2_service_only on public.pr_security_retention_runs for all to service_role using (true) with check (true);

commit;
