-- Rafii Account Protection v2, P1 item 3: account holds and fences.
--
-- pr_security_account_controls is one row per person: whether a security hold is active and a monotonic hold_epoch
-- that every placement and release bumps. Workers and API tokens re-read it at claim and immediately before an
-- external publish or call (security_holds.py); a job that captured an epoch at claim refuses to act if it changed.
-- The hold is person-level on purpose: it applies in every workspace the person belongs to.
--
-- Writes go through public.pr_security_set_hold only, which always bumps the epoch; a trigger refuses any write that
-- does not increase it (owner included) and any delete outside the account deletion purge. Server-only: FORCE RLS,
-- no anon/authenticated access, service_role only. Nothing reads it unless RAFII_SECURITY_INCIDENT_HOLD is on.
--
-- Additive. Rollback: turn the flag off (holds stop being read). Do not drop the table while a hold is active.
begin;

create table public.pr_security_account_controls (
  user_id uuid primary key,
  hold_active boolean not null default false,
  hold_epoch bigint not null default 0 check (hold_epoch >= 0),
  hold_reason text check (hold_reason is null or hold_reason ~ '^[a-z0-9_.]{3,80}$'),
  placed_at timestamptz,
  released_at timestamptz,
  updated_at timestamptz not null default now(),
  check (not hold_active or placed_at is not null)
);

create or replace function postriff_private.rapv2_account_controls_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'TRUNCATE' then
    raise exception 'account controls are never truncated' using errcode = '42501';
  end if;
  if tg_op = 'DELETE' then
    if current_setting('rapv2.purge_user', true) = old.user_id::text
       and exists (select 1 from public.pr_account_tombstones t where t.user_id = old.user_id) then
      return old;
    end if;
    raise exception 'account controls are never deleted' using errcode = '42501';
  end if;
  if tg_op = 'INSERT' then
    if new.hold_epoch <> 1 then
      raise exception 'a new account control starts at hold_epoch 1' using errcode = '42501';
    end if;
  elsif new.hold_epoch <> old.hold_epoch + 1 or new.user_id <> old.user_id then
    raise exception 'hold_epoch only moves forward, one step per change' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger pr_security_account_controls_monotonic
  before insert or update or delete on public.pr_security_account_controls
  for each row execute function postriff_private.rapv2_account_controls_guard();
create trigger pr_security_account_controls_no_truncate
  before truncate on public.pr_security_account_controls
  for each statement execute function postriff_private.rapv2_account_controls_guard();

-- Place (p_active) or release a hold; returns the new epoch. Idempotent in effect, never in epoch: a repeated
-- placement still bumps it, so any job that captured the old epoch revalidates.
create or replace function public.pr_security_set_hold(p_user uuid, p_active boolean, p_reason text) returns bigint
language plpgsql security definer set search_path = '' as $$
declare epoch bigint;
begin
  insert into public.pr_security_account_controls as c (user_id, hold_active, hold_epoch, hold_reason, placed_at, released_at)
  values (p_user, p_active, 1, p_reason, case when p_active then now() end, case when not p_active then now() end)
  on conflict (user_id) do update set
    hold_active = excluded.hold_active,
    hold_epoch = c.hold_epoch + 1,
    hold_reason = coalesce(excluded.hold_reason, c.hold_reason),
    placed_at = case when excluded.hold_active then now() else c.placed_at end,
    released_at = case when excluded.hold_active then c.released_at else now() end,
    updated_at = now()
  returning hold_epoch into epoch;
  return epoch;
end $$;
revoke all on function public.pr_security_set_hold(uuid, boolean, text) from public, anon, authenticated;
grant execute on function public.pr_security_set_hold(uuid, boolean, text) to service_role;

-- The account deletion purge now also removes the person's account control row.
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
  delete from public.pr_security_account_controls where user_id = p_user;
  perform set_config('rapv2.purge_user', '', true);
end $$;
revoke all on function public.pr_security_purge(uuid) from public, anon, authenticated;
grant execute on function public.pr_security_purge(uuid) to service_role;

alter table public.pr_security_account_controls enable row level security;
alter table public.pr_security_account_controls force row level security;
revoke all on public.pr_security_account_controls from public, anon, authenticated;
grant select on public.pr_security_account_controls to service_role;
create policy rapv2_service_only on public.pr_security_account_controls for all to service_role using (true) with check (true);

commit;
