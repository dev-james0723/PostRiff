-- Additive billing/entitlement/usage, privacy requests, analytics observations, audience.
-- Apply after 006. Prices here are PROPOSED decision records, never charged by this code.
begin;

-- Versioned plan terms (decision records). status='proposed' until an explicit commercial decision.
create table public.pr_plan_terms (
  id text primary key,
  plan text not null check (plan in ('trial','studio','assist')),
  version integer not null,
  label text not null,
  price_cents integer not null check (price_cents >= 0),
  currency text not null default 'USD' check (currency in ('USD')),
  status text not null check (status in ('proposed','active','retired')),
  entitlements jsonb not null check (jsonb_typeof(entitlements)='object'),
  source text not null default '',
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (plan, version)
);
insert into public.pr_plan_terms(id,plan,version,label,price_cents,status,entitlements,source) values
 ('trial-v1','trial',1,'14-day trial',0,'proposed','{"members":1,"connectedAccounts":2,"writingBatches":10,"mediaCredits":1,"storageMb":200,"autoConvert":false,"overage":"stop"}','consumer plan product-spec.md:358-360; pr_trials'),
 ('studio-v1','studio',1,'Studio',1900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":0,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','consumer plan pricing-and-economics.md (PROPOSAL, not implemented)'),
 ('assist-v1','assist',1,'Studio Assist',3900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":100,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','consumer plan pricing-and-economics.md (PROPOSAL, not implemented)'),
 ('assist-bounded-v1','assist',2,'Studio Assist (bounded-batch experiment)',3900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":8,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','improvement DECISIONS.md:15 beta experiment; not an invisible rewrite');

create table public.pr_subscriptions (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  plan_terms_id text not null references public.pr_plan_terms(id),
  provider text not null default 'fixture',
  provider_customer_id text,
  provider_subscription_id text,
  status text not null check (status in ('trial','active','past_due','grace','cancelled','expired')),
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  grace_until timestamptz,
  last_event_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.pr_entitlements (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  plan_terms_id text not null references public.pr_plan_terms(id),
  writing_batches_remaining integer not null check (writing_batches_remaining >= 0),
  media_credits_remaining integer not null check (media_credits_remaining >= 0),
  connected_accounts integer not null,
  members integer not null,
  storage_mb integer not null,
  resets_at timestamptz,
  source text not null check (source in ('trial','subscription','manual')),
  version integer not null default 1,
  updated_at timestamptz not null default now()
);

-- Append-only, idempotent usage/cost ledger. No update/delete grants exist for any role.
create table public.pr_usage_ledger (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid,
  run_id uuid,
  job_id text,
  reservation_id uuid,
  kind text not null check (kind in ('reserve','settle','release','adjust')),
  dimension text not null check (dimension in ('text_model','image_generation','tool','storage','action')),
  provider text not null default '',
  model text not null default '',
  quantity numeric not null default 1,
  unit text not null default 'request',
  estimated_usd_micro bigint not null default 0 check (estimated_usd_micro >= 0),
  actual_usd_micro bigint check (actual_usd_micro >= 0),
  cost_state text not null check (cost_state in ('estimated','actual','estimated_unknown','released')),
  charge_batch boolean not null default false,
  idempotency_key text not null,
  meta jsonb not null default '{}' check (jsonb_typeof(meta)='object'),
  at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);
create index on public.pr_usage_ledger (workspace_id, at desc);

-- Budget rows are the lock points for reserve/settle. Candidate ceilings, flagged as such.
create table public.pr_budgets (
  scope text primary key,
  window_kind text not null check (window_kind in ('day','month')),
  window_start timestamptz not null default date_trunc('day', now()),
  warn_usd_micro bigint not null,
  stop_usd_micro bigint not null,
  spent_usd_micro bigint not null default 0 check (spent_usd_micro >= 0),
  reserved_usd_micro bigint not null default 0 check (reserved_usd_micro >= 0),
  status text not null default 'candidate' check (status in ('candidate','approved')),
  updated_at timestamptz not null default now()
);

-- Billing webhook events: signature-verified by the adapter, unique per provider event id.
create table public.pr_billing_events (
  provider text not null,
  event_id text not null,
  kind text not null,
  event_at timestamptz not null,
  payload_digest text not null check (length(payload_digest)=64),
  outcome text not null check (outcome in ('applied','duplicate','stale','ignored','rejected')),
  processed_at timestamptz not null default now(),
  primary key (provider, event_id)
);

-- Customer data requests with receipts (export, deletion, diagnostics-by-consent).
create table public.pr_data_requests (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete set null,
  requested_by uuid not null,
  kind text not null check (kind in ('export','deletion','diagnostics','retraction')),
  status text not null check (status in ('requested','completed','failed')),
  receipt jsonb not null default '{}' check (jsonb_typeof(receipt)='object'),
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);
create index on public.pr_data_requests (workspace_id, requested_at desc);

-- Native metric definitions (global) and per-post observations (tenant). Missing is 'unavailable', never 0.
create table public.pr_metric_definitions (
  provider text not null, metric text not null, native_name text not null, definition_version text not null,
  unit text not null, scope text not null, definition_url text not null default '',
  primary key (provider, metric, definition_version)
);
insert into public.pr_metric_definitions values
 ('threads','views','views','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','likes','likes','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','replies','replies','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','reposts','reposts','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','quotes','quotes','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','shares','shares','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('instagram','reach','reach','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','views','views','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','likes','likes','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','comments','comments','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','saved','saved','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','shares','shares','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights');

create table public.pr_metric_observations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  provider text not null,
  provider_post_id text not null,
  job_id text,
  metric text not null,
  definition_version text not null,
  value numeric,
  unit text not null,
  availability text not null check (availability in ('available','unavailable','suppressed','not_supported')),
  observed_at timestamptz not null,
  period_start timestamptz,
  period_end timestamptz,
  ingested_at timestamptz not null default now(),
  source_endpoint text not null default '',
  check ((availability='available' and value is not null) or (availability<>'available' and value is null))
);
create index on public.pr_metric_observations (workspace_id, provider_post_id, metric, observed_at desc);

-- Audience: original thread context + reply drafts with exact approval and separate send/verify receipts.
create table public.pr_audience_threads (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  provider text not null,
  provider_post_id text not null,
  provider_comment_id text not null,
  author_handle text not null default '',
  text text not null,
  created_at_provider timestamptz,
  ingested_at timestamptz not null default now(),
  tombstoned_at timestamptz,
  unique (workspace_id, provider, provider_comment_id)
);
create table public.pr_reply_drafts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  thread_id uuid not null references public.pr_audience_threads(id) on delete cascade,
  author uuid not null,
  origin text not null check (origin in ('manual','ai_fixture')),
  text text not null,
  status text not null check (status in ('draft','approved','submitting','submitted','verified','failed','uncertain','cancelled')),
  approval jsonb,
  provider_reference text,
  events jsonb not null default '[]',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
declare t text;
begin
  foreach t in array array['pr_subscriptions','pr_entitlements','pr_data_requests','pr_metric_observations','pr_audience_threads','pr_reply_drafts'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  -- Ledger: tenant read; service_role may only insert and select (immutable rows).
  alter table public.pr_usage_ledger enable row level security;
  alter table public.pr_usage_ledger force row level security;
  revoke all on public.pr_usage_ledger from public, anon, authenticated, service_role;
  grant select on public.pr_usage_ledger to authenticated;
  grant select, insert on public.pr_usage_ledger to service_role;
  create policy ledger_tenant_read on public.pr_usage_ledger for select to authenticated using (postriff_private.member(workspace_id));
  create policy ledger_service_insert on public.pr_usage_ledger for insert to service_role with check (true);
  create policy ledger_service_read on public.pr_usage_ledger for select to service_role using (true);
  foreach t in array array['pr_budgets','pr_billing_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  foreach t in array array['pr_plan_terms','pr_metric_definitions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy catalog_read on public.%I for select to authenticated using (true)', t);
    execute format('create policy catalog_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;
