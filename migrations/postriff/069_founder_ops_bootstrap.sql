-- Founder ops workspace (CONTRACTS §8.H, PRD §4.5). Public schema only; additive and idempotent (apply twice).
-- The founder owns a second, internal workspace ("Rafii Ops (founder)") that holds Founder Rafii's conversations, runs, ledger
-- rows and founder calls. pr_bootstrap answered "the user's workspace" with an unordered LIMIT 1 over memberships, so a second
-- membership could become someone's default after sign-in. It now prefers the workspace of the user's own trial (the one
-- bootstrap created), then the lowest id: the same answer as before for every user with one workspace, and a fixed one for
-- users with more. Every other line is the live definition (004), unchanged.
begin;
create or replace function public.pr_bootstrap(p_user uuid, p_plan text) returns uuid language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  if p_plan not in ('studio','assist') then raise exception 'unavailable plan'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_account_tombstones where user_id=p_user) then raise exception 'deleted account'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select m.workspace_id into wid from public.pr_memberships m
    left join public.pr_trials t on t.user_id=m.user_id and t.workspace_id=m.workspace_id
   where m.user_id=p_user and m.status='active'
   order by (t.workspace_id is null), m.workspace_id limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections)
    values(wid,p_user,'owner','active',true,true,true,true);
  insert into public.pr_trials(user_id,workspace_id,plan) values(p_user,wid,p_plan);
  return wid;
end $$;
revoke all on function public.pr_bootstrap(uuid,text) from public,anon,authenticated;
grant execute on function public.pr_bootstrap(uuid,text) to service_role;
commit;
