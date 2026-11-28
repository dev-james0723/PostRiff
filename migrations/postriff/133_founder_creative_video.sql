-- Optional Founder Control projection. Apply after 054, 131 and 132 in the intended environment.
begin;
-- Keep raw job bodies behind a migration-owner view. The reporting owner sees only
-- the job fields required to calculate the metrics, even across workspace RLS.
create or replace view rafii_control.creative_video_job_metrics with(security_barrier=true) as
select workspace_id, (body->>'reservationId')::uuid reservation,
    body->>'model' model, body->>'provider' provider, coalesce(body->>'planTerms','unattributed') plan,
    body->>'state' state, (body->>'reason') in ('provider_operation_failed','provider_output_unusable') provider_failure,
    (body->>'accepted')::boolean accepted, (body->>'estimatedUsdMicro')::bigint estimated,
    body->>'mediaKind'='composed' composed,
    greatest(0,(body->>'finishedAt')::numeric-extract(epoch from created_at)) elapsed,
    body ? 'finishedAt' timed
from public.pr_jobs
where body->>'kind'='creative_video_scene' and created_at >= now()-interval '30 days';
revoke all on rafii_control.creative_video_job_metrics from public,anon,authenticated,service_role,
    rafii_control_reader,rafii_control_session,rafii_control_business_projection;
grant select on rafii_control.creative_video_job_metrics to rafii_control_business_projection;
revoke select(body) on public.pr_jobs from rafii_control_business_projection;
grant select(id,workspace_id,reservation_id,kind,cost_state,actual_usd_micro,meta)
    on public.pr_usage_ledger to rafii_control_business_projection;
grant select(workspace_id,kind,environment) on rafii_control.workspace_classifications to rafii_control_business_projection;
create or replace view rafii_control.creative_video_usage with(security_barrier=true) as
with details as (
    select j.model, j.provider, j.plan,
        case when r.meta->>'actorClass'='founder' then 'internal'
             when r.meta->>'actorClass'='exempt' then 'exempt' else coalesce(c.kind,'customer') end usage_class,
        j.state, j.provider_failure, j.accepted, j.estimated,
        coalesce(t.actual_usd_micro,case when j.composed then 0 end) actual,
        case when j.reservation is not null and t.id is null then coalesce((r.meta->'credits'->>'maximum')::bigint,0) else 0 end held,
        coalesce((t.meta->'credits'->>'used')::bigint,0) consumed,
        j.reservation is not null and t.id is null and j.state in ('unknown','completed','failed','cancelled') unresolved,
        j.elapsed, j.timed
    from rafii_control.creative_video_job_metrics j
    left join public.pr_usage_ledger r on (r.workspace_id,r.id)=(j.workspace_id,j.reservation) and r.kind='reserve'
    left join rafii_control.workspace_classifications c on c.workspace_id=j.workspace_id
      and c.environment=current_setting('rafii_control.environment',true)
    left join lateral (
        select u.id,u.actual_usd_micro,u.meta from public.pr_usage_ledger u
        where (u.workspace_id,u.reservation_id)=(j.workspace_id,j.reservation)
        and u.kind in ('settle','release') and u.cost_state in ('actual','released') limit 1
    ) t on true
)
select model,provider,plan,usage_class as "usageClass",count(*)::integer jobs,
 count(*) filter(where state='completed')::integer completed, count(*) filter(where state='failed')::integer failed,
 count(*) filter(where state='cancelled')::integer cancelled, count(*) filter(where unresolved)::integer "pendingReconciliations",
 sum(estimated)::bigint "estimatedUsdMicro",sum(actual)::bigint "actualUsdMicro",sum(held)::bigint "reservedMilliCredits",
 sum(consumed)::bigint "consumedMilliCredits",round(avg(elapsed) filter(where timed),1)::float8 "averageLatencySeconds",
 case when count(accepted)>0 then count(*) filter(where accepted)::integer end accepted,
 count(*) filter(where state='completed')::float8/nullif(count(*) filter(where state='completed' or
    (state='failed' and provider_failure)),0) "technicalSuccessRate",
 case when count(actual)=count(*) then round(sum(actual)::numeric/nullif(count(*) filter(where accepted),0))::bigint end "costPerAcceptedUsdMicro"
from details group by model,provider,plan,usage_class;
-- PostgreSQL requires CREATE on the schema for the new owner during transfer.
do $$
declare needs_create boolean := not has_schema_privilege('rafii_control_business_projection','rafii_control','CREATE');
begin
    if needs_create then
        grant create on schema rafii_control to rafii_control_business_projection;
    end if;
    alter view rafii_control.creative_video_usage owner to rafii_control_business_projection;
    if needs_create then
        revoke create on schema rafii_control from rafii_control_business_projection;
    end if;
end $$;
revoke all on rafii_control.creative_video_usage from public,anon,authenticated,service_role;
grant select on rafii_control.creative_video_usage to rafii_control_reader;
grant select on public.pr_creative_video_model_policy to rafii_control_reader,rafii_control_session;
grant insert, update on public.pr_creative_video_model_policy to rafii_control_session;
drop policy if exists control_read on public.pr_creative_video_model_policy;
create policy control_read on public.pr_creative_video_model_policy for select to rafii_control_reader
using(environment=current_setting('rafii_control.environment',true));
drop policy if exists control_session on public.pr_creative_video_model_policy;
create policy control_session on public.pr_creative_video_model_policy for all to rafii_control_session
using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
commit;
