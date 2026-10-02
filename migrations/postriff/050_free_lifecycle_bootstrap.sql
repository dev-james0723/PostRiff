-- Free acquisition/lifecycle support; additive after 048, no commercial activation.
begin;

alter table public.pr_entitlements drop constraint if exists pr_entitlements_source_check;
alter table public.pr_entitlements add constraint pr_entitlements_source_check
  check (source in ('trial','subscription','manual','free'));

-- Separate service-only entry point: the legacy bootstrap and trial ledger remain intact.
create or replace function public.pr_bootstrap_free(p_user uuid) returns uuid
language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_account_tombstones where user_id=p_user) then raise exception 'deleted account'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select workspace_id into wid from public.pr_memberships where user_id=p_user and status='active' limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections)
    values(wid,p_user,'owner','active',true,true,true,true);
  insert into public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,source)
    select wid,id,0,0,(entitlements->>'connectedAccounts')::integer,(entitlements->>'members')::integer,(entitlements->>'storageMb')::integer,'free'
    from public.pr_plan_terms where id='free-v1' and plan='free';
  if not found then raise exception 'Free terms unavailable'; end if;
  return wid;
end $$;
revoke all on function public.pr_bootstrap_free(uuid) from public,anon,authenticated;
grant execute on function public.pr_bootstrap_free(uuid) to service_role;

commit;
