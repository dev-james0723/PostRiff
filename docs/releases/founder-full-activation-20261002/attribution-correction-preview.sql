-- Read-only historical correction preview v1. No money movement or UPDATE.
-- Run through the approved reader/audit path only after access is restored.
-- Compare reserve attribution, not today's classification, with its settlement.
select r.id::text as reservation_id,s.id::text as settlement_id,s.cost_state,
 r.meta->>'aiUsageExempt' as reserve_exempt,
 s.meta->>'aiUsageExempt' as settlement_exempt,
 r.meta->>'costCenter' as reserve_cost_center,
 s.meta->>'costCenter' as settlement_cost_center,
 r.meta->>'attributionVersion' as reserve_writer_version,
 s.meta->>'attributionVersion' as settlement_writer_version,
 s.actual_usd_micro,s.estimated_usd_micro,
 'preview_only_no_financial_change'::text as disposition
from public.pr_usage_ledger r
join public.pr_usage_ledger s on s.workspace_id=r.workspace_id and s.reservation_id=r.id
where r.kind='reserve' and s.kind in ('settle','release')
 and ((r.meta->>'aiUsageExempt') is distinct from (s.meta->>'aiUsageExempt')
      or (r.meta->>'costCenter') is distinct from (s.meta->>'costCenter'))
order by r.at,r.id,s.at,s.id limit 1000;
