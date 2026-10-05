-- Opt-in writer audit only. No browser capability; no credential values here.
-- The trusted application login must already be allowed to SET ROLE; this migration
-- grants capability to its installer, never to service_role/anon/authenticated.
begin;
do $$ begin
  if not exists(select 1 from pg_roles where rolname='pr_capture_owner') then
    create role pr_capture_owner nologin nosuperuser nobypassrls noinherit;
  end if;
  if not exists(select 1 from pg_roles where rolname='pr_capture_runtime') then
    create role pr_capture_runtime nologin nosuperuser nobypassrls noinherit;
  end if;
  if exists(select 1 from pg_roles where rolname in ('pr_capture_owner','pr_capture_runtime') and (rolsuper or rolbypassrls or rolcanlogin)) then
    raise exception 'capture roles must be restricted';
  end if;
  execute format('grant pr_capture_runtime to %I', current_user);
  -- Temporary ownership capability permits ALTER FUNCTION OWNER on non-superuser installers.
  execute format('grant pr_capture_owner to %I', current_user);
end $$;
create schema if not exists audit_private;
revoke all on schema audit_private from public,anon,authenticated,service_role;
grant usage on schema audit_private to pr_capture_runtime,pr_capture_owner;
grant create on schema audit_private to pr_capture_owner;

create table audit_private.model_capture_grants (
 id uuid primary key, workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 actor_id uuid not null references public.pr_profiles(user_id) on delete cascade,
 run_id uuid unique references public.pr_agent_runs(id) on delete cascade,
 server_nonce text unique not null check(length(server_nonce) between 40 and 80),
 route text not null check(route like 'https://%' and length(route)<=2048),
 reader_ids uuid[] not null, consent_version text not null check(consent_version='rafii-exact-request-v1'),
 capture_mode text not null check(capture_mode='encrypted_exact_body'),
 confirmed_at timestamptz not null default now(), start_before timestamptz not null,
 expires_at timestamptz not null, revoked_at timestamptz,
 workspace_revision bigint, policy_epoch text,
 used_attempts integer not null default 0 check(used_attempts between 0 and 3),
 used_bytes integer not null default 0 check(used_bytes between 0 and 1572864),
 check(start_before<=confirmed_at+interval '10 minutes'),
 check(expires_at>confirmed_at and expires_at<=confirmed_at+interval '1 hour'),
 check(reader_ids=array[actor_id])
);
create table audit_private.model_request_captures (
 id uuid primary key, grant_id uuid not null references audit_private.model_capture_grants(id) on delete cascade,
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 run_id uuid not null references public.pr_agent_runs(id) on delete cascade,
 logical_call_id uuid not null, attempt_no integer not null check(attempt_no between 1 and 3),
 created_at timestamptz not null default now(), expires_at timestamptz not null,
 state text not null default 'prepared' check(state in ('prepared','network_started','response_observed','dispatch_unknown')),
 record jsonb not null check(jsonb_typeof(record)='object'),
 unique(grant_id,logical_call_id,attempt_no)
);
create index on audit_private.model_request_captures(expires_at);
create index on audit_private.model_capture_grants(expires_at);
alter table audit_private.model_capture_grants enable row level security;
alter table audit_private.model_capture_grants force row level security;
alter table audit_private.model_request_captures enable row level security;
alter table audit_private.model_request_captures force row level security;
revoke all on all tables in schema audit_private from public,anon,authenticated,service_role,pr_capture_runtime;
grant select,insert,update,delete on all tables in schema audit_private to pr_capture_owner;
create policy capture_owner on audit_private.model_capture_grants for all to pr_capture_owner using(true) with check(true);
create policy capture_owner on audit_private.model_request_captures for all to pr_capture_owner using(true) with check(true);
-- The non-owner/non-bypass function role can only read source identity/scope data.
grant select on public.pr_profiles,public.pr_memberships,public.pr_workspaces,public.pr_agent_runs to pr_capture_owner;
create policy capture_scope_read on public.pr_profiles for select to pr_capture_owner using(true);
create policy capture_scope_read on public.pr_memberships for select to pr_capture_owner using(true);
create policy capture_scope_read on public.pr_workspaces for select to pr_capture_owner using(true);
create policy capture_scope_read on public.pr_agent_runs for select to pr_capture_owner using(true);

create function audit_private.capture_operation(action text,p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 g audit_private.model_capture_grants%rowtype;
 c audit_private.model_request_captures%rowtype;
 r public.pr_agent_runs%rowtype;
 wid uuid; aid uuid; gid uuid; cid uuid; revision_now bigint; result jsonb; n integer; created_now timestamptz:=clock_timestamp();
begin
 -- Fixed capability, no arbitrary SQL/filter/table access and no global trace list.
 if action='purge' then
   delete from audit_private.model_capture_grants where expires_at<=clock_timestamp() or revoked_at is not null;
   get diagnostics n=row_count;
   return jsonb_build_object('purged_grants',n);
 end if;
 wid:=(p->>'workspace_id')::uuid; aid:=(p->>'actor_id')::uuid;
 if not exists(select 1 from public.pr_memberships m join public.pr_profiles u on u.user_id=m.user_id
    where m.workspace_id=wid and m.user_id=aid and m.status='active' and (m.role='owner' or (action='revoke_workspace' and m.role in ('admin','editor'))) and u.deleted_at is null) then
   raise exception 'capture scope unavailable';
 end if;
 select revision into revision_now from public.pr_workspaces where id=wid;
 if action='revoke_workspace' then
   delete from audit_private.model_capture_grants where workspace_id=wid;
   get diagnostics n=row_count;
   return jsonb_build_object('purged_grants',n);
 end if;
 if action='create' then
   if p->>'confirmed'<>'true' or p->>'consent_version'<>'rafii-exact-request-v1'
      or (p->>'ttl_seconds')::integer not between 1 and 3600
      or p->'reader_ids'<>jsonb_build_array(aid::text) then
     raise exception 'explicit bounded consent required';
   end if;
   perform pg_advisory_xact_lock(hashtextextended('rafii-capture:'||wid::text,0));
   delete from audit_private.model_capture_grants where workspace_id=wid and (expires_at<=clock_timestamp() or revoked_at is not null);
   if exists(select 1 from audit_private.model_capture_grants where workspace_id=wid) then
     raise exception 'an active capture grant already exists';
   end if;
   insert into audit_private.model_capture_grants(id,workspace_id,actor_id,server_nonce,route,reader_ids,consent_version,capture_mode,confirmed_at,start_before,expires_at)
    values((p->>'id')::uuid,wid,aid,p->>'server_nonce',p->>'route',array[aid],p->>'consent_version','encrypted_exact_body',
           created_now,created_now+interval '10 minutes',created_now+make_interval(secs=>(p->>'ttl_seconds')::integer)) returning * into g;
   return to_jsonb(g);
 end if;
 if action='read' then
   cid:=(p->>'capture_id')::uuid;
   select * into c from audit_private.model_request_captures where id=cid and workspace_id=wid;
   if not found then raise exception 'capture unavailable'; end if;
   gid:=c.grant_id;
 else gid:=(p->>'grant_id')::uuid;
 end if;
 select * into g from audit_private.model_capture_grants where id=gid and workspace_id=wid and actor_id=aid for update;
 if not found or g.server_nonce<>p->>'server_nonce' or g.revoked_at is not null or g.expires_at<=clock_timestamp() then
   raise exception 'capture grant unavailable';
 end if;
 if action='revoke' then
   delete from audit_private.model_capture_grants where id=g.id;
   return jsonb_build_object('revoked',true);
 end if;
 if action='bind' then
   if g.start_before<=clock_timestamp() or g.run_id is not null then raise exception 'capture intent unavailable'; end if;
   select * into r from public.pr_agent_runs where id=(p->>'run_id')::uuid and workspace_id=wid and actor=aid;
   if not found or r.status<>'running' or r.idempotency_key<>p->>'idempotency_key' then raise exception 'capture run unavailable'; end if;
   update audit_private.model_capture_grants set run_id=r.id,workspace_revision=revision_now,policy_epoch=r.policy_epoch where id=g.id returning * into g;
   return to_jsonb(g);
 end if;
 if g.run_id is null then raise exception 'capture grant is not bound'; end if;
 select * into r from public.pr_agent_runs where id=g.run_id and workspace_id=wid and actor=aid;
 if not found then raise exception 'capture run unavailable'; end if;
 if r.policy_epoch<>g.policy_epoch or revision_now<>g.workspace_revision then raise exception 'capture policy changed'; end if;
 if action='list' then
   select coalesce(jsonb_agg(jsonb_build_object('capture_id',id,'state',state,'created_at',created_at,'expires_at',expires_at) order by created_at),'[]'::jsonb) into result
     from audit_private.model_request_captures where grant_id=g.id;
   return jsonb_build_object('captures',result);
 end if;
 if action='read' then
   if not aid=any(g.reader_ids) then raise exception 'capture reader unavailable'; end if;
   return c.record||jsonb_build_object('state',c.state);
 end if;
 if g.run_id<>(p->>'run_id')::uuid or g.route<>p->>'route' then raise exception 'capture run binding mismatch'; end if;
 if action in ('grant','prepare','start') then
   if r.status<>'running' or r.policy_epoch<>g.policy_epoch or revision_now<>g.workspace_revision then
     raise exception 'capture policy changed';
   end if;
   if exists(select 1 from audit_private.model_request_captures where grant_id=g.id and state in ('network_started','dispatch_unknown')) then
     raise exception 'prior dispatch outcome unresolved';
   end if;
 end if;
 if action='grant' and g.used_attempts=0 and g.start_before<=clock_timestamp() then raise exception 'capture start window expired'; end if;
 if action='grant' then return to_jsonb(g); end if;
 if action='prepare' then
   result:=p->'record'; cid:=(result->>'capture_id')::uuid;
   if g.used_attempts>=3 or g.used_bytes+(result#>>'{prepared,manifest,body_bytes}')::integer>1572864
       or (result#>>'{prepared,manifest,body_bytes}')::integer not between 1 and 524288
       or result#>>'{prepared,manifest,physical_attempt_id}'<>cid::text
       or result#>>'{prepared,manifest,grant_id}'<>g.id::text
       or result#>>'{prepared,manifest,workspace_id}'<>wid::text
       or result#>>'{prepared,manifest,run_id}'<>g.run_id::text
       or result#>>'{prepared,manifest,actor_id}'<>aid::text
       or result#>>'{prepared,manifest,endpoint}'<>g.route
       or (result#>>'{prepared,manifest,expires_at}')::timestamptz<>g.expires_at then
     raise exception 'capture quota or binding mismatch';
   end if;
   insert into audit_private.model_request_captures(id,grant_id,workspace_id,run_id,logical_call_id,attempt_no,expires_at,record)
     values(cid,g.id,wid,g.run_id,(result#>>'{prepared,manifest,logical_call_id}')::uuid,
            (result#>>'{prepared,manifest,attempt_no}')::integer,g.expires_at,result);
   update audit_private.model_capture_grants set used_attempts=used_attempts+1,used_bytes=used_bytes+(result#>>'{prepared,manifest,body_bytes}')::integer where id=g.id;
   select record into result from audit_private.model_request_captures where id=cid;
   return result;
 end if;
 cid:=(p->>'capture_id')::uuid;
 select * into c from audit_private.model_request_captures where id=cid and grant_id=g.id for update;
 if not found then raise exception 'capture unavailable'; end if;
 if p#>>'{receipt,manifest,physical_attempt_id}'<>c.id::text then raise exception 'capture receipt mismatch'; end if;
 if action='start' then
   if c.state<>'prepared' or p#>>'{receipt,manifest,kind}'<>'network_started' then raise exception 'capture dispatch already consumed'; end if;
   update audit_private.model_request_captures set state='network_started',record=record||jsonb_build_object('network_started',p->'receipt') where id=c.id;
   return jsonb_build_object('authorized',true);
 end if;
 if action='outcome' then
   if c.state<>'network_started' or p#>>'{receipt,manifest,kind}' not in ('response_observed','dispatch_unknown') then
     raise exception 'capture outcome is not appendable';
   end if;
   if p ? 'response' and (p#>>'{receipt,manifest,response_bytes}')::integer not between 0 and 524288 then raise exception 'capture response quota'; end if;
   update audit_private.model_request_captures set state=p#>>'{receipt,manifest,kind}',
     record=record||jsonb_build_object('outcome',p->'receipt')||case when p ? 'response' then jsonb_build_object('response',p->'response') else '{}'::jsonb end where id=c.id;
   return jsonb_build_object('recorded',true);
 end if;
 raise exception 'unsupported capture operation';
end $$;
alter function audit_private.capture_operation(text,jsonb) owner to pr_capture_owner;
revoke create on schema audit_private from pr_capture_owner;
do $$ begin execute format('revoke pr_capture_owner from %I', current_user); end $$;
revoke all on function audit_private.capture_operation(text,jsonb) from public,anon,authenticated,service_role;
grant execute on function audit_private.capture_operation(text,jsonb) to pr_capture_runtime;
-- No plaintext, secrets, keys, or public readers were provisioned. Five-minute
-- expiry cleanup must be enabled before activation; reads already deny expiry.
commit;
