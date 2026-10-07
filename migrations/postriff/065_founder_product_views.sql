-- Founder Admin P1 product slice (CONTRACTS §8.C): read-only founder projections for product analytics and customer
-- risk. Additive; apply after 054 and 059. Reapplication must be safe. No operator gains a capability here and no role
-- membership is granted to anyone. Every view is a column-allowlisted security_barrier projection owned by the
-- non-login business projection role (054 pattern) and readable only by rafii_control_reader. Product event properties
-- appear only as allowlisted enum-shaped values (anything else reads NULL); no payloads, drafts, prompts, URLs or emails.
begin;
grant select(id,workspace_id,user_id,event,properties,occurred_at) on public.pr_product_events to rafii_control_business_projection;
grant select(workspace_id,kind,created_at) on public.pr_learning_events to rafii_control_business_projection;
-- pr_workspaces(id,created_at) and pr_audit_events(workspace_id,kind,at) are already granted by 053/054.

-- PRD §8.6 taxonomy and the earlier coworker events: event name, workspace, person, time and the allowlisted enums.
create or replace view rafii_control.business_product_events with(security_barrier=true) as
 select e.id::text as id,e.event,e.workspace_id::text as "workspaceId",e.user_id::text as "userId",e.occurred_at as "occurredAt",
 case when e.properties->>'feature' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'feature' end as feature,
 case when e.properties->>'voice' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'voice' end as voice,
 case when e.properties->>'surface' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'surface' end as surface,
 case when e.properties->>'outcome' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'outcome' end as outcome,
 case when e.properties->>'source' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'source' end as source,
 case when e.properties->>'provider' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'provider' end as provider,
 case when e.properties->>'cause' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'cause' end as cause,
 case when e.properties->>'via' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'via' end as via,
 case when e.properties->>'kind' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'kind' end as kind,
 case when e.properties->>'schedule' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'schedule' end as schedule,
 case when e.properties->>'plan' ~ '^[a-z][a-z0-9_-]{0,39}$' then e.properties->>'plan' end as plan,
 case when e.properties->>'platform' ~ '^[A-Za-z][A-Za-z0-9 ._-]{0,39}$' then e.properties->>'platform' end as platform
 from public.pr_product_events e;
-- Learning events (010) as activation transition proxies: kind, workspace and time only (no subject, scope or features).
create or replace view rafii_control.business_learning_events with(security_barrier=true) as
 select l.kind,l.workspace_id::text as "workspaceId",l.created_at as at from public.pr_learning_events l;
-- Signup anchor (pr_profiles has no created_at): the workspace's creation.
create or replace view rafii_control.business_workspace_starts with(security_barrier=true) as
 select w.id::text as "workspaceId",w.created_at as "createdAt" from public.pr_workspaces w;
-- Channel connect/disconnect audit rows as the channel step's transition proxy (kind and time only; never the subject).
create or replace view rafii_control.business_channel_audit with(security_barrier=true) as
 select a.workspace_id::text as "workspaceId",a.kind,a.at from public.pr_audit_events a
 where a.kind in ('channel.connected','channel.disconnected') and a.workspace_id is not null;

do $$ declare n text; begin
 foreach n in array array['business_product_events','business_learning_events','business_workspace_starts','business_channel_audit'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
 -- The learning rollup projection exists only where 059 created its table.
 if to_regclass('public.pr_learning_daily_rollups') is not null then
  grant select(day,workspace_id,kind,events,first_at) on public.pr_learning_daily_rollups to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_learning_rollups with(security_barrier=true) as select r.day,r.workspace_id::text as "workspaceId",r.kind,r.events,r.first_at as "firstAt" from public.pr_learning_daily_rollups r';
  alter view rafii_control.business_learning_rollups owner to rafii_control_business_projection;
  revoke all on rafii_control.business_learning_rollups from public,anon,authenticated,service_role;
  grant select on rafii_control.business_learning_rollups to rafii_control_reader;
 end if;
end $$;
commit;
