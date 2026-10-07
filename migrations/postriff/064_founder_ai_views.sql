-- Founder Admin v2 P1/P2 (CONTRACTS §8.B): founder projections over the 058 AI usage instrumentation. Apply after 054 and 058.
-- Additive only; reapplication must be safe. Every view is a column-allowlisted, security_barrier projection owned by the
-- non-login business projection role and readable only by rafii_control_reader (the 054 pattern). No dedupe key, physical
-- attempt id or payload is projected. No role-membership grant is made to any migration runner; hosted application is a
-- separate owner-approved step.
begin;

grant select(id,workspace_id,user_id,feature,workload,run_id,reservation_id,attempt_no,provider,model,route,provider_request_id,input_tokens,output_tokens,
  cached_input_tokens,reasoning_tokens,images,audio_seconds,cost_usd_micro,cost_source,price_version,status,http_status,latency_ms,ai_usage_exempt,started_at,created_at)
  on public.pr_ai_call_events to rafii_control_business_projection;
grant select(id,call_event_id,cost_usd_micro,source,audio_seconds,at) on public.pr_ai_call_settlements to rafii_control_business_projection;
grant select(version,effective_from,effective_to,source_url,fetched_at,prices) on public.pr_price_versions to rafii_control_business_projection;
grant select(day,workspace_id,feature,model,provider,actor_class,calls,ok,failed,cancelled,unknown,input_tokens,cached_tokens,output_tokens,reasoning_tokens,
  tokens_unreported,images,audio_seconds,estimated_usd_micro,actual_usd_micro,unknown_usd_micro,rollup_version,computed_at)
  on public.pr_usage_rollups to rafii_control_business_projection;

-- One row per provider attempt. costUsdMicro/costSource/audioSeconds are the effective values: the attempt's own, else its
-- latest late settlement (lateSettled says which); unknown stays NULL. `at` is when the attempt started.
create or replace view rafii_control.business_ai_calls with(security_barrier=true) as
 select e.id::text as id,e.workspace_id::text as "workspaceId",e.user_id::text as "userId",e.feature,e.workload,e.run_id::text as "runId",
 e.reservation_id::text as "reservationId",e.attempt_no as "attemptNo",e.provider,e.model,e.route,e.provider_request_id as "providerRequestId",e.status,
 e.http_status as "httpStatus",e.input_tokens as "inputTokens",e.output_tokens as "outputTokens",e.cached_input_tokens as "cachedInputTokens",
 e.reasoning_tokens as "reasoningTokens",e.images,coalesce(e.audio_seconds,s.audio_seconds) as "audioSeconds",
 coalesce(e.cost_usd_micro,s.cost_usd_micro) as "costUsdMicro",
 case when e.cost_usd_micro is not null then e.cost_source when s.cost_usd_micro is not null then s.source else 'unknown' end as "costSource",
 e.price_version as "priceVersion",(e.cost_usd_micro is null and s.cost_usd_micro is not null) as "lateSettled",e.latency_ms as "latencyMs",
 e.ai_usage_exempt as "aiUsageExempt",e.started_at as at,e.created_at as "createdAt"
 from public.pr_ai_call_events e
 left join lateral (select x.cost_usd_micro,x.source,x.audio_seconds from public.pr_ai_call_settlements x where x.call_event_id=e.id order by x.at desc,x.id desc limit 1) s on true;

create or replace view rafii_control.business_usage_rollups with(security_barrier=true) as
 select r.day,r.workspace_id::text as "workspaceId",r.feature,r.model,r.provider,r.actor_class as "actorClass",r.calls,r.ok,r.failed,r.cancelled,r.unknown,
 r.input_tokens as "inputTokens",r.cached_tokens as "cachedTokens",r.output_tokens as "outputTokens",r.reasoning_tokens as "reasoningTokens",
 r.tokens_unreported as "tokensUnreported",r.images,r.audio_seconds as "audioSeconds",r.estimated_usd_micro as "estimatedUsdMicro",
 r.actual_usd_micro as "actualUsdMicro",r.unknown_usd_micro as "unknownUsdMicro",r.rollup_version as "rollupVersion",r.computed_at as "computedAt"
 from public.pr_usage_rollups r;

create or replace view rafii_control.business_price_versions with(security_barrier=true) as
 select p.version,p.effective_from as "effectiveFrom",p.effective_to as "effectiveTo",p.source_url as "sourceUrl",p.fetched_at as "fetchedAt",p.prices
 from public.pr_price_versions p;

do $$ declare n text; begin
 foreach n in array array['business_ai_calls','business_usage_rollups','business_price_versions'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
end $$;
commit;
