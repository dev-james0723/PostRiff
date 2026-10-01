-- Founder Admin v2 P1/P2 (CONTRACTS §8.D): the rafii_control side of the reliability slice. Apply after 049-056 and 060.
-- Additive and idempotent; reapplication must be safe. Hosted application is a separate owner-approved step; no
-- role-membership grant is made to any migration runner here.
--
-- 1. Founder projections over the 060 tables, following 054: column-allowlisted security_barrier views owned by the non-login
--    rafii_control_business_projection role, column-level grants on the public tables to that role, SELECT to
--    rafii_control_reader. Each is created only where its 060 table exists, so a partial apply leaves the metric
--    'source_not_configured' instead of failing.
-- 2. rafii_control_watchdog: a NOLOGIN role with SELECT on rafii_control.source_health only, scoped by the environment GUC
--    like the reader. The independent watchdog (.github/workflows/founder-watchdog.yml) reads the cron heartbeat through a
--    dedicated login that is a member of this role; creating and enabling that login is a deployment step, not this file.
begin;
do $$ begin
 if not exists(select 1 from pg_roles where rolname='rafii_control_business_projection') then
  create role rafii_control_business_projection nologin nosuperuser bypassrls;
 end if;
 if not exists(select 1 from pg_roles where rolname='rafii_control_watchdog') then
  create role rafii_control_watchdog nologin nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
 end if;
end $$;
grant usage on schema public,rafii_control to rafii_control_business_projection;

do $$ begin
 if to_regclass('public.pr_request_metrics') is not null then
  grant select(minute,route_pattern,status_class,request_count,duration_sum_ms,duration_buckets) on public.pr_request_metrics to rafii_control_business_projection;
  -- Route patterns carry no identifier; the histogram is the bounded latency sample (bounds documented in 060).
  execute 'create or replace view rafii_control.business_request_metrics with(security_barrier=true) as select minute,route_pattern as "routePattern",status_class as "statusClass",request_count as "requestCount",duration_sum_ms as "durationSumMs",duration_buckets as "durationBuckets" from public.pr_request_metrics';
 end if;
 if to_regclass('public.pr_operational_snapshots') is not null then
  grant select(minute,observed_at,status,notification_delivery,counts) on public.pr_operational_snapshots to rafii_control_business_projection;
  -- counts is the server-written flat object of non-negative integer counters (060 check); no other payload exists.
  execute 'create or replace view rafii_control.business_operational_snapshots with(security_barrier=true) as select minute,observed_at as "observedAt",status,notification_delivery as "notificationDelivery",counts from public.pr_operational_snapshots';
 end if;
 if to_regclass('public.pr_connection_health') is not null then
  grant select(workspace_id,connection_id,capability,provider,level,state,connection_state,expires_at,last_sync_at,refreshed_at) on public.pr_connection_health to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_connection_health with(security_barrier=true) as select workspace_id::text as "workspaceId",connection_id as "connectionId",provider,capability,level,state,connection_state as "connectionState",expires_at as "expiresAt",last_sync_at as "lastSyncAt",refreshed_at as "refreshedAt" from public.pr_connection_health';
 end if;
end $$;

do $$ declare n text; begin
 foreach n in array array['business_request_metrics','business_operational_snapshots','business_connection_health'] loop
  if to_regclass('rafii_control.'||n) is not null then
   execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
   execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
   execute format('grant select on rafii_control.%I to rafii_control_reader',n);
  end if;
 end loop;
end $$;

-- The watchdog sees source ids, states, reason codes and timestamps of one environment, and nothing else in rafii_control.
grant usage on schema rafii_control to rafii_control_watchdog;
grant select on rafii_control.source_health to rafii_control_watchdog;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='source_health' and policyname='watchdog_read') then
  create policy watchdog_read on rafii_control.source_health for select to rafii_control_watchdog
   using(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;

commit;
