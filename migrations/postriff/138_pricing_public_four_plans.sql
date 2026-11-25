-- User amendment 2026-10-03: display existing Starter $29 and Studio v2 $149.
-- Visibility only: preserve prices, quotas, provider bindings and checkout activation gates.
UPDATE public.pr_plan_terms
SET catalog_state='public'
WHERE id IN ('starter-v1','studio-v2') AND catalog_state='hidden';
