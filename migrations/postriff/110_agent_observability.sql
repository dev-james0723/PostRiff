-- Rafii agent observability (P0.7): content-free agent metrics, plus founder projections over the GenUI outcomes that already
-- exist (102). Additive and idempotent; reapplication must be safe. Applying this file to any shared or production database
-- is a separate owner-approved step (DP-9); the code ships first and treats a missing table as "not installed yet".
--
-- 1. public.pr_agent_metrics: one row per minute x metric x label, upserted by postriff_phase2.agent_metrics from a bounded
--    in-process buffer on a background thread, never inside a request's own transaction. Metric names are fixed in code
--    (agent_metrics.METRICS); labels are codes joined by ':' (path, status, tool, reason, provider, surface) and can never
--    carry an id, a name, a title or any text. No workspace, person, conversation, run or trace id is stored. UNLOGGED: a
--    crash may lose the latest minutes, which the founder view reports as a gap, never as zero. For millisecond metrics,
--    value_buckets is a fixed histogram: bucket i counts values <= the i-th upper bound (50, 100, 250, 500, 1000, 2000, 3000,
--    5000, 7500, 10000, 15000, 20000, 30000, 45000, 60000, 120000, 300000, 900000, 3600000 ms; the 20th is open-ended); other
--    metrics leave it zero. Retention: 30 days (the writer purges older minutes).
-- 2. Founder projections (the 066 pattern, created only where the rafii_control schema and its roles exist): column-allowlisted
--    security_barrier views owned by rafii_control_business_projection, readable only by rafii_control_reader:
--    business_agent_metrics, business_genui_artifacts and business_genui_attempts (states, kinds, reason codes, attempt
--    counts and times; never source, instruction, manifest, fallback text, state or usage payloads).
-- No role is created and no role membership is granted here.
begin;

create unlogged table if not exists public.pr_agent_metrics (
  minute timestamptz not null,
  metric text not null check (metric ~ '^agent[.][a-z][a-z0-9_.]{0,47}$'),
  label text not null check (label ~ '^[a-z0-9][a-z0-9_.:-]{0,119}$'),
  event_count bigint not null check (event_count > 0),
  value_sum double precision not null check (value_sum >= 0),
  value_buckets bigint[] not null check (array_ndims(value_buckets) = 1 and cardinality(value_buckets) = 20 and 0 <= all(value_buckets)),
  updated_at timestamptz not null default now(),
  primary key (minute, metric, label)
);

-- Consumer side: forced RLS, one service_only policy, grants to service_role only (060 pattern). Founder reads go through the
-- projection below, never this table.
alter table public.pr_agent_metrics enable row level security;
alter table public.pr_agent_metrics force row level security;
revoke all on public.pr_agent_metrics from public, anon, authenticated;
grant select, insert, update, delete on public.pr_agent_metrics to service_role;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_agent_metrics' and policyname='service_only') then
    create policy service_only on public.pr_agent_metrics for all to service_role using (true) with check (true);
  end if;
end $$;

do $$ declare n text; begin
  if to_regnamespace('rafii_control') is null
     or not exists (select 1 from pg_roles where rolname='rafii_control_business_projection')
     or not exists (select 1 from pg_roles where rolname='rafii_control_reader') then
    return;   -- the Control schema is not installed here; reapply after 049/054/066 to add the founder projections
  end if;
  grant usage on schema public, rafii_control to rafii_control_business_projection;

  grant select(minute,metric,label,event_count,value_sum,value_buckets) on public.pr_agent_metrics to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_agent_metrics with(security_barrier=true) as '
          'select minute,metric,label,event_count as "eventCount",value_sum as "valueSum",value_buckets as "valueBuckets" from public.pr_agent_metrics';

  if to_regclass('public.pr_ui_artifacts') is not null then
    grant select(id,workspace_id,scope,surface,generation_state,validation_state,reason,revision,created_at,updated_at) on public.pr_ui_artifacts to rafii_control_business_projection;
    -- reason is a validator or lifecycle code (<= 64 chars); anything not shaped like a code reads NULL.
    execute 'create or replace view rafii_control.business_genui_artifacts with(security_barrier=true) as '
            'select a.id::text as id,a.workspace_id::text as "workspaceId",a.scope,a.surface,a.generation_state as "generationState",'
            'a.validation_state as "validationState",case when a.reason ~ ''^[a-z][a-z0-9_.:-]{0,63}$'' then a.reason end as "reasonCode",'
            'a.revision,a.created_at as "createdAt",a.updated_at as "updatedAt" from public.pr_ui_artifacts a';
  end if;
  if to_regclass('public.pr_ui_attempts') is not null then
    grant select(id,artifact_id,workspace_id,kind,state,reason,provider_attempts,cost_state,created_at,ready_at,finished_at) on public.pr_ui_attempts to rafii_control_business_projection;
    execute 'create or replace view rafii_control.business_genui_attempts with(security_barrier=true) as '
            'select t.id::text as id,t.artifact_id::text as "artifactId",t.workspace_id::text as "workspaceId",t.kind,t.state,'
            'case when t.reason ~ ''^[a-z][a-z0-9_.:-]{0,63}$'' then t.reason end as "reasonCode",t.provider_attempts as "providerAttempts",'
            't.cost_state as "costState",t.created_at as "createdAt",t.ready_at as "readyAt",t.finished_at as "finishedAt" from public.pr_ui_attempts t';
  end if;

  foreach n in array array['business_agent_metrics','business_genui_artifacts','business_genui_attempts'] loop
    if to_regclass('rafii_control.'||n) is not null then
      execute format('alter view rafii_control.%I owner to rafii_control_business_projection', n);
      execute format('revoke all on rafii_control.%I from public, anon, authenticated, service_role', n);
      execute format('grant select on rafii_control.%I to rafii_control_reader', n);
    end if;
  end loop;
end $$;

commit;
