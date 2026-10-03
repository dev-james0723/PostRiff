-- Direct user approval 2026-10-03: Starter US$29 and Studio v2 US$149 are purchasable.
-- No provider Price is fabricated or provisioned. Checkout still requires a verified
-- unique provider_price_id, active credits, pricing enablement and the workspace owner.
UPDATE public.pr_plan_terms SET status='active',new_checkout_enabled=true
WHERE id IN ('starter-v1','studio-v2') AND catalog_state='public' AND status IN ('proposed','active');
