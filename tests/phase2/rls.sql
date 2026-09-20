\set ON_ERROR_STOP on
-- Disposable local PostgreSQL only. Minimal Supabase-role harness, not hosted proof.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth to authenticated,service_role;
grant execute on function auth.uid() to authenticated,service_role;
create schema storage;
create table storage.buckets(id text primary key,name text,public boolean);
create table storage.objects(id uuid primary key default gen_random_uuid(),bucket_id text,name text);
alter table storage.objects enable row level security;
grant usage on schema storage to authenticated,service_role;
grant select,insert,update,delete on storage.objects to authenticated;
grant all on storage.objects,storage.buckets to service_role;
\ir ../../migrations/postriff/001_phase2.sql
\ir ../../migrations/postriff/002_hosted_account_lifecycle.sql
\ir ../../migrations/postriff/004_consumer_web_tenancy.sql
\ir ../../migrations/postriff/005_consumer_web_ideas.sql
\ir ../../migrations/postriff/006_consumer_web_channels.sql
\ir ../../migrations/postriff/007_consumer_web_billing.sql
\ir ../../migrations/postriff/008_billing_provider_notifications.sql
\ir ../../migrations/postriff/009_account_security.sql
\ir ../../migrations/postriff/010_preference_learning.sql
\ir ../../migrations/postriff/011_account_preferences.sql
\ir ../../migrations/postriff/012_channel_pictures.sql
\ir ../../migrations/postriff/018_raffi_planning.sql
insert into auth.users values('00000000-0000-0000-0000-000000000001'),('00000000-0000-0000-0000-000000000002');
select public.pr_bootstrap('00000000-0000-0000-0000-000000000001','studio') as one \gset
select public.pr_bootstrap('00000000-0000-0000-0000-000000000002','assist') as two \gset
select public.pr_bootstrap('00000000-0000-0000-0000-000000000001','assist');
do $$ begin
 if (select count(*) from public.pr_trials) <> 2 or (select count(*) from public.pr_workspaces) <> 2 then raise exception 'replay created a grant or workspace'; end if;
end $$;
insert into storage.objects(bucket_id,name) values('postriff-private',:'one'||'/a.jpg'),('postriff-private',:'two'||'/b.jpg');
do $$ declare t text; wid uuid; begin
 foreach t in array array['pr_voice_profiles','pr_skills','pr_sources','pr_assets','pr_devices','pr_channels','pr_approvals','pr_jobs','pr_receipts'] loop
  for wid in select id from public.pr_workspaces loop
   execute format('insert into public.%I(workspace_id,body) values($1,$2)',t) using wid,'{"synthetic":true}'::jsonb;
  end loop;
 end loop;
end $$;
select set_config('test.foreign_workspace',:'two',false);
set role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',false);
do $$ declare t text; n integer; begin
 foreach t in array array['pr_workspaces','pr_memberships','pr_profiles','pr_trials','pr_voice_profiles','pr_skills','pr_sources','pr_assets','pr_devices','pr_channels','pr_approvals','pr_jobs','pr_receipts'] loop
  execute format('select count(*) from public.%I',t) into n;
  if n<>1 then raise exception 'tenant enumeration leaked %: %',t,n; end if;
 end loop;
 foreach t in array array['pr_voice_profiles','pr_skills','pr_sources','pr_assets','pr_devices','pr_channels','pr_approvals','pr_jobs','pr_receipts'] loop
  execute format('select count(*) from public.%I where workspace_id=$1',t) into n using current_setting('test.foreign_workspace')::uuid;
  if n<>0 then raise exception 'direct object read leaked %',t; end if;
  begin
   execute format('insert into public.%I(workspace_id,body) values($1,$2)',t) using current_setting('test.foreign_workspace')::uuid,'{}'::jsonb;
   raise exception 'forged insert accepted %',t;
  exception when insufficient_privilege then null; end;
  begin
   execute format('update public.%I set body=$1',t) using '{}'::jsonb;
   raise exception 'browser mutation accepted %',t;
  exception when insufficient_privilege then null; end;
  begin
   execute format('delete from public.%I',t);
   raise exception 'browser deletion accepted %',t;
  exception when insufficient_privilege then null; end;
 end loop;
 if (select count(*) from storage.objects)<>1 then raise exception 'storage leaked'; end if;
 begin
  insert into storage.objects(bucket_id,name) values('postriff-private',current_setting('test.foreign_workspace')||'/forged.jpg');
  raise exception 'storage forged upload accepted';
 exception when insufficient_privilege then null; end;
 begin
  perform public.pr_bootstrap('00000000-0000-0000-0000-000000000002','studio');
  raise exception 'browser bootstrap accepted';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000002',false);
do $$ begin
 if (select count(*) from public.pr_workspaces)<>1 or (select count(*) from storage.objects)<>1 then raise exception 'second user isolation failed'; end if;
 if exists(select 1 from public.pr_profiles where user_id='00000000-0000-0000-0000-000000000001') then raise exception 'second user profile leaked'; end if;
end $$;
set role anon;
do $$ begin
 begin
  perform * from public.pr_workspaces;
  raise exception 'anonymous access accepted';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
insert into public.pr_account_tombstones(user_id,plan,trial_started_at) values('00000000-0000-0000-0000-000000000002','assist',now());
do $$ begin
 begin
  perform public.pr_bootstrap('00000000-0000-0000-0000-000000000002','assist');
  raise exception 'deleted account recreated a workspace or trial';
 exception when raise_exception then
  if sqlerrm <> 'deleted account' then raise; end if;
 end;
end $$;
update public.pr_memberships set status='revoked' where user_id='00000000-0000-0000-0000-000000000002';
set role authenticated;
do $$ begin
 if (select count(*) from public.pr_workspaces)<>0 or (select count(*) from storage.objects)<>0 then raise exception 'revoked member access'; end if;
end $$;
reset role;
select 'PASS: two-user RLS, 9 object families, forged IDs, CRUD denials, private storage, revoked membership, service-only bootstrap, trial replay and deletion tombstone' as result;
