-- Additive: provider price binding for plan terms + server-only notification ledger.
-- Apply after 007. Adds no PII columns; user emails are fetched from Supabase Auth at send time.
begin;

-- Live provider price id (e.g. Stripe price_…). Set together with status='active' by an explicit
-- commercial decision in SQL; checkout refuses any row whose status is not 'active'.
alter table public.pr_plan_terms add column if not exists provider_price_id text;

-- One row per (workspace, kind, dedupe_key): welcome, trial-ending, trial-ended, payment-failed,
-- subscription-activated. `sent` records the transport outcome; meta never holds addresses or bodies.
create table public.pr_notifications (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid,
  kind text not null,
  dedupe_key text not null unique,
  sent boolean not null default false,
  meta jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index on public.pr_notifications (workspace_id, created_at desc);

-- Server-only, mirroring 007's treatment of pr_budgets / pr_billing_events.
do $$
declare t text;
begin
  foreach t in array array['pr_notifications'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;
