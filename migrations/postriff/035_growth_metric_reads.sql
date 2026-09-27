-- Growth intelligence Phase 0: scheduled post metric readings, owned-post history, import runs and the AI usage
-- ledger (docs/design/growth-phase0/CONTRACTS.md). Additive, forward-only and idempotent; it references only tables
-- from 004 and 007, so it applies after 025 in tests/phase2/rls.sql and after the full chain alike.
-- Rollback = POSTRIFF_METRIC_READS / POSTRIFF_HISTORY_IMPORT / POSTRIFF_POST_DOCTOR off; the tables stay empty.
-- Number 035: 032 is productivity connectors, 033 phone mode, and 034 unified notifications on consumer-saas (docs/postriff-migration-numbering.md).
begin;

-- One row per planned reading of one post: t0/1h/24h/7d after verification, or a single 'backfill' reading for a
-- post found by history import or an older verified job. The unique key is per post, so every path is idempotent
-- and a crash-recovered re-claim cannot double-write (completion is fenced on lease_owner).
create table if not exists public.pr_metric_reads (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  job_id text check (job_id is null or length(job_id) <= 200),
  connection_id text not null check (length(connection_id) <= 200),
  provider text not null check (provider in ('threads','instagram')),
  provider_post_id text not null check (length(provider_post_id) between 1 and 200),
  read_offset text not null check (read_offset in ('t0','1h','24h','7d','backfill')),
  source text not null check (source in ('verification','backfill','history_import')),
  anchor_at timestamptz not null,
  due_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','claimed','done','unavailable','cancelled','dead')),
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 5 check (max_attempts between 1 and 20),
  lease_owner text check (lease_owner is null or length(lease_owner) <= 80),
  lease_until timestamptz,
  last_http_status integer,
  failure_class text check (failure_class is null or length(failure_class) <= 40),
  observed_at timestamptz,
  scheduled_at timestamptz not null default now(),   -- when this reading was (re)scheduled; a revival resets it
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, provider, provider_post_id, read_offset)
);
-- MetricScheduler.claim takes expired leases, then due fresh verification readings, then due backfill readings; each
-- step is a range scan on its own partial index that stops at its LIMIT, whatever the size of the future queue.
create index if not exists pr_metric_reads_due_fresh on public.pr_metric_reads (due_at) where status='pending' and source='verification';
create index if not exists pr_metric_reads_due_backfill on public.pr_metric_reads (due_at) where status='pending' and source<>'verification';
create index if not exists pr_metric_reads_lease on public.pr_metric_reads (lease_until) where status='claimed';

-- The account's own posts found by history import (and, optionally, Rafii's verified ones). Metadata only: neither
-- caption text nor a hash of it is retained in Phase 0 (a hash of a short caption can be guessed); only its length.
create table if not exists public.pr_owned_posts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (length(connection_id) <= 200),
  provider text not null check (provider in ('threads','instagram')),
  provider_post_id text not null check (length(provider_post_id) between 1 and 200),
  published_at timestamptz,
  media_type text check (media_type is null or length(media_type) <= 40),
  media_product_type text check (media_product_type is null or length(media_product_type) <= 40),
  permalink text check (permalink is null or (length(permalink) <= 500 and permalink like 'https://%')),
  caption_chars integer check (caption_chars is null or caption_chars >= 0),
  source text not null check (source in ('history_import','verification')),
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, provider, provider_post_id)
);
create index if not exists pr_owned_posts_recent on public.pr_owned_posts (workspace_id, connection_id, published_at desc);

-- One history import per connection at a time (a partial unique index), claimed by the cron step with a lease.
create table if not exists public.pr_history_imports (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (length(connection_id) <= 200),
  provider text not null check (provider in ('threads','instagram')),
  status text not null default 'pending' check (status in ('pending','running','done','failed','cancelled')),
  window_days integer not null default 90 check (window_days between 1 and 90),
  cursor text check (cursor is null or length(cursor) <= 500),
  pages integer not null default 0 check (pages >= 0),
  posts integer not null default 0 check (posts >= 0),
  attempts integer not null default 0 check (attempts >= 0),
  lease_owner text check (lease_owner is null or length(lease_owner) <= 80),
  lease_until timestamptz,
  failure_class text check (failure_class is null or length(failure_class) <= 40),
  requested_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists pr_history_imports_active on public.pr_history_imports (workspace_id, connection_id)
  where status in ('pending','running');

-- A disconnected connection whose imported history must be purged. oauth.disconnect inserts it (history_import.
-- mark_for_purge) and purges right after its commit (purge_after_disconnect), which deletes the row; a row that stays
-- means that purge failed. While it exists the connection imports nothing and its import readings are cancelled; the
-- cron retries the purge whatever the growth flags say, so a rollback never strands a disconnected account's data.
create table if not exists public.pr_growth_purges (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (length(connection_id) <= 200),
  requested_at timestamptz not null default now(),
  next_attempt_at timestamptz not null default now(),
  attempts integer not null default 0 check (attempts >= 0),
  failure_class text check (failure_class is null or length(failure_class) <= 80),
  primary key (workspace_id, connection_id)
);

-- One row per model or evaluation attempt (growth/usage.py). Opaque ids and numbers only, never prompt or post text.
-- cost_usd_micro is NULL when the provider reported no cost: unknown, never zero.
create table if not exists public.pr_model_usage_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  task text not null check (length(task) <= 60),
  stage text check (stage is null or length(stage) <= 60),
  model text not null check (length(model) <= 120),
  route text not null check (route in ('primary','fallback')),
  provider text check (provider is null or length(provider) <= 60),
  generation_id text check (generation_id is null or length(generation_id) <= 200),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  cost_usd_micro bigint check (cost_usd_micro is null or cost_usd_micro >= 0),
  cost_source text not null check (cost_source in ('gateway','unknown') or cost_source ~ '^table:[A-Za-z0-9._-]{1,60}$'),
  latency_ms integer not null check (latency_ms >= 0),
  status text not null check (length(status) <= 40),
  subject text check (subject is null or subject ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  check (cost_source <> 'unknown' or cost_usd_micro is null)
);
create index if not exists pr_model_usage_events_workspace on public.pr_model_usage_events (workspace_id, created_at desc);

-- Readings taken on a schedule say which offset they were (NULL for every older row and for other writers), so
-- comparisons can hold read age constant.
alter table public.pr_metric_observations add column if not exists read_offset text;
-- Added only when missing: a re-run must not re-validate every observation under an exclusive lock.
do $$
begin
  if not exists (select 1 from pg_constraint where conname='pr_metric_observations_read_offset_check'
                 and conrelid='public.pr_metric_observations'::regclass) then
    alter table public.pr_metric_observations add constraint pr_metric_observations_read_offset_check
      check (read_offset is null or read_offset in ('t0','1h','24h','7d','backfill'));
  end if;
end $$;

do $$
declare t text;
begin
  foreach t in array array['pr_metric_reads','pr_owned_posts','pr_history_imports'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='tenant_read') then
      execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    end if;
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
  foreach t in array array['pr_model_usage_events','pr_growth_purges'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
