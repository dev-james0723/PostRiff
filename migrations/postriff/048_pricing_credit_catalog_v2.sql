-- Additive v2 catalog only. No checkout, experiment, pack, price or wallet activation.
-- Apply after the current hosted chain, including credit scaffolding 020--022.
begin;

alter table public.pr_plan_terms drop constraint if exists pr_plan_terms_plan_check;
alter table public.pr_plan_terms add constraint pr_plan_terms_plan_check
  check (plan in ('trial','free','starter','creator','studio','assist'));
alter table public.pr_plan_terms add column if not exists catalog_state text not null default 'legacy'
  check (catalog_state in ('public','hidden','legacy'));
alter table public.pr_plan_terms add column if not exists new_checkout_enabled boolean not null default false;

-- Preserve historical prices, provider bindings, statuses, allowances and subscriptions.
update public.pr_plan_terms set catalog_state='legacy', new_checkout_enabled=false
  where id in ('trial-v1','studio-v1','assist-v1','assist-bounded-v1')
    and (catalog_state <> 'legacy' or new_checkout_enabled);

insert into public.pr_plan_terms
  (id,plan,version,label,price_cents,currency,status,catalog_state,new_checkout_enabled,entitlements,source)
values
  ('free-v1','free',1,'Free',0,'USD','active','public',false,
   '{"members":1,"connectedAccounts":1,"brands":1,"writingBatches":0,"mediaCredits":0,"storageMb":200,"overage":"stop"}',
   'pricing credits v2 spec 2026-09-28 sections 7,9; zero managed credits; no automatic assignment'),
  ('starter-v1','starter',1,'Starter',2900,'USD','proposed','hidden',false,
   '{"members":1,"connectedAccounts":3,"brands":1,"writingBatches":0,"mediaCredits":0,"storageMb":1000,"creditPolicy":"credits-v2-2026-09-28","monthlyCredits":1000,"overage":"stop"}',
   'pricing credits v2 spec 2026-09-28 sections 7,9; proposed, no commercial activation'),
  ('creator-v1','creator',1,'Creator',5900,'USD','proposed','public',false,
   '{"members":1,"connectedAccounts":6,"brands":2,"writingBatches":0,"mediaCredits":0,"storageMb":1000,"creditPolicy":"credits-v2-2026-09-28","monthlyCredits":3500,"overage":"stop"}',
   'pricing credits v2 spec 2026-09-28 sections 7,9; same package for 49/59/79, no commercial activation'),
  ('studio-v2','studio',2,'Studio',14900,'USD','proposed','hidden',false,
   '{"members":3,"connectedAccounts":10,"brands":3,"writingBatches":0,"mediaCredits":0,"storageMb":1000,"creditPolicy":"credits-v2-2026-09-28","monthlyCredits":8000,"overage":"stop"}',
   'pricing credits v2 spec 2026-09-28 sections 7,9; proposed, no commercial activation')
on conflict (id) do nothing;

-- Prices vary independently of the one Creator entitlement package.
create table if not exists public.pr_plan_price_variants (
  id text primary key,
  plan_terms_id text not null references public.pr_plan_terms(id),
  variant_key text not null check (length(variant_key) between 1 and 80),
  amount_cents integer not null check (amount_cents >= 0),
  currency text not null default 'USD' check (currency in ('USD')),
  provider_price_id text,
  status text not null default 'proposed' check (status in ('proposed','active','retired')),
  experiment_key text check (experiment_key is null or length(experiment_key) between 1 and 80),
  created_at timestamptz not null default now(),
  unique (plan_terms_id,variant_key),
  unique (id,plan_terms_id),
  check (status <> 'active' or nullif(btrim(provider_price_id),'') is not null)
);
insert into public.pr_plan_price_variants
  (id,plan_terms_id,variant_key,amount_cents,currency,provider_price_id,status,experiment_key)
values
  ('creator-49-v1','creator-v1','49',4900,'USD',null,'proposed','creator-beta-v1'),
  ('creator-59-v1','creator-v1','59',5900,'USD',null,'proposed','creator-beta-v1'),
  ('creator-79-v1','creator-v1','79',7900,'USD',null,'proposed','creator-beta-v1')
on conflict (id) do nothing;

create table if not exists public.pr_price_experiment_assignments (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  experiment_key text not null check (length(experiment_key) between 1 and 80),
  price_variant_id text not null references public.pr_plan_price_variants(id),
  assigned_at timestamptz not null default now(),
  assignment_source text not null check (length(assignment_source) between 1 and 200),
  primary key (workspace_id,experiment_key)
);
create index if not exists pr_price_experiment_assignments_variant_idx
  on public.pr_price_experiment_assignments(price_variant_id);

-- Insert-once assignments prevent re-bucketing. Workspace deletion still cascades.
create or replace function postriff_private.pr_price_assignment_immutable()
returns trigger language plpgsql set search_path='' as $$
begin
  if new is distinct from old then
    raise exception using errcode='23514', message='price experiment assignment is immutable';
  end if;
  return new;
end $$;
revoke all on function postriff_private.pr_price_assignment_immutable() from public,anon,authenticated;
do $$ begin
  if not exists (select 1 from pg_trigger where tgrelid='public.pr_price_experiment_assignments'::regclass
                 and tgname='pr_price_assignment_immutable') then
    create trigger pr_price_assignment_immutable before update on public.pr_price_experiment_assignments
      for each row execute function postriff_private.pr_price_assignment_immutable();
  end if;
end $$;

-- A Creator variant cannot be attached to another package. NULL preserves legacy records.
alter table public.pr_subscriptions add column if not exists price_variant_id text;
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid='public.pr_subscriptions'::regclass
                 and conname='pr_subscriptions_price_variant_terms_fkey') then
    alter table public.pr_subscriptions add constraint pr_subscriptions_price_variant_terms_fkey
      foreign key (price_variant_id,plan_terms_id) references public.pr_plan_price_variants(id,plan_terms_id);
  end if;
end $$;

-- Extend the existing pack scaffold to represent inactive proposals without fake provider IDs.
alter table public.pr_credit_packs alter column price_id drop not null;
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid='public.pr_credit_packs'::regclass
                 and conname='pr_credit_packs_active_price_check') then
    alter table public.pr_credit_packs add constraint pr_credit_packs_active_price_check
      check (not active or nullif(btrim(price_id),'') is not null);
  end if;
end $$;
insert into public.pr_credit_packs
  (id,label,policy_id,price_id,amount_cents,currency,millicredits,livemode,active)
values
  ('credits-1000-v2','1,000 credits','credits-v2-2026-09-28',null,1500,'usd',1000000,false,false),
  ('credits-2000-v2','2,000 credits','credits-v2-2026-09-28',null,2900,'usd',2000000,false,false)
on conflict (id) do nothing;

-- Raw provider mappings and experiment assignments remain server-only.
alter table public.pr_plan_price_variants enable row level security;
alter table public.pr_plan_price_variants force row level security;
alter table public.pr_price_experiment_assignments enable row level security;
alter table public.pr_price_experiment_assignments force row level security;
revoke all on public.pr_plan_price_variants,public.pr_price_experiment_assignments from public,anon,authenticated,service_role;
grant select,insert,update,delete on public.pr_plan_price_variants to service_role;
grant select,insert on public.pr_price_experiment_assignments to service_role;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_plan_price_variants'
                 and policyname='service_only') then
    create policy service_only on public.pr_plan_price_variants for all to service_role
      using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_price_experiment_assignments'
                 and policyname='service_read') then
    create policy service_read on public.pr_price_experiment_assignments for select to service_role using (true);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_price_experiment_assignments'
                 and policyname='service_insert') then
    create policy service_insert on public.pr_price_experiment_assignments for insert to service_role with check (true);
  end if;
end $$;

commit;
