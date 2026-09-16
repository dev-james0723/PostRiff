-- Additive hosted account lifecycle controls for the approved private Preview.
begin;

create table public.pr_account_tombstones (
  user_id uuid primary key,
  plan text not null check (plan in ('studio','assist')),
  trial_started_at timestamptz not null,
  deleted_at timestamptz not null default now(),
  auth_deleted_at timestamptz,
  reason text not null default 'user_requested' check (reason = 'user_requested')
);

create table public.pr_session_revocations (
  user_id uuid not null,
  session_id text not null check (length(session_id) between 16 and 160),
  revoked_at timestamptz not null default now(),
  primary key (user_id, session_id)
);

alter table public.pr_account_tombstones enable row level security;
alter table public.pr_account_tombstones force row level security;
alter table public.pr_session_revocations enable row level security;
alter table public.pr_session_revocations force row level security;
revoke all on public.pr_account_tombstones, public.pr_session_revocations from public, anon, authenticated;
grant all on public.pr_account_tombstones, public.pr_session_revocations to service_role;

create or replace function public.pr_bootstrap(p_user uuid, p_plan text) returns uuid language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  if p_plan not in ('studio','assist') then raise exception 'unavailable plan'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_account_tombstones where user_id=p_user) then raise exception 'deleted account'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select workspace_id into wid from public.pr_memberships where user_id=p_user and status='active' limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships values(wid,p_user,'owner','active');
  insert into public.pr_trials(user_id,workspace_id,plan) values(p_user,wid,p_plan);
  return wid;
end $$;
revoke all on function public.pr_bootstrap(uuid,text) from public,anon,authenticated;
grant execute on function public.pr_bootstrap(uuid,text) to service_role;

commit;
