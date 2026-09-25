-- Rafii coworker evidence, strategy and growth tables (adaptive coworker spec §9, §11, §23; architecture lock S1,
-- P1, G1, L1). Forward-only and idempotent. Rollback = the matching RAFII_* flags off; the tables stay empty.
begin;

-- Acquired research evidence with full provenance (the Research Broker). Bulky raw material stays here, out of the
-- workspace document. A search snippet is recorded as evidence_type 'search_snippet' and is never a verified fact.
create table if not exists public.pr_research_evidence (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  request_key text check (request_key is null or length(request_key) <= 200),
  provider text not null check (length(provider) <= 60),
  provider_kind text not null check (provider_kind in ('web_search','web_reader','official_api','mcp','local_agent_reach','fixture','user_supplied')),
  access_method text not null check (length(access_method) <= 40),
  query text check (query is null or length(query) <= 400),
  url text check (url is null or length(url) <= 2000),
  host text check (host is null or length(host) <= 200),
  platform text check (platform is null or length(platform) <= 60),
  retrieved_at timestamptz not null,
  published_at text check (published_at is null or length(published_at) <= 60),
  author text check (author is null or length(author) <= 200),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  represented_scope text not null check (length(represented_scope) <= 60),
  evidence_type text not null check (evidence_type in ('search_snippet','page_text','transcript','owned_post','user_supplied','social_post','image_text')),
  rights jsonb not null default '{}' check (jsonb_typeof(rights) = 'object'),
  injection_flags jsonb not null default '[]' check (jsonb_typeof(injection_flags) = 'array'),
  excerpt text check (excerpt is null or length(excerpt) <= 8000),
  claim_ids jsonb not null default '[]' check (jsonb_typeof(claim_ids) = 'array'),
  created_at timestamptz not null default now(),
  unique (workspace_id, content_sha256, url)
);
create index if not exists pr_research_evidence_request on public.pr_research_evidence (workspace_id, request_key);

-- Strategy hypotheses from account-specific performance. Never identity, never a writing rule, never causal:
-- the CHECK makes a causal claim impossible to store.
create table if not exists public.pr_strategy_hypotheses (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  platform text not null check (length(platform) <= 60),
  dimension text not null check (length(dimension) <= 40),
  cohort jsonb not null default '{}' check (jsonb_typeof(cohort) = 'object'),
  statement text not null check (length(statement) between 10 and 400),
  metric text not null check (length(metric) <= 60),
  arm_a text not null check (length(arm_a) <= 80),
  arm_b text not null check (length(arm_b) <= 80),
  sample_a integer not null check (sample_a >= 0),
  sample_b integer not null check (sample_b >= 0),
  effect numeric,
  date_from timestamptz,
  date_to timestamptz,
  evidence_ids jsonb not null default '[]' check (jsonb_typeof(evidence_ids) = 'array'),
  counter_evidence_ids jsonb not null default '[]' check (jsonb_typeof(counter_evidence_ids) = 'array'),
  confidence text not null check (confidence in ('low','moderate','high')),
  causal boolean not null default false check (causal = false),
  status text not null default 'candidate' check (status in ('candidate','experiment','supported','rejected','expired','dismissed')),
  experiment jsonb,
  revision integer not null default 1 check (revision >= 1),
  replaces_id uuid,
  created_at timestamptz not null default now(),
  last_supported_at timestamptz,
  expires_at timestamptz,
  decided_by uuid,
  decided_at timestamptz,
  unique (workspace_id, platform, dimension, arm_a, arm_b, metric, revision)
);

-- Product events for growth metrics: ids, counts and categories only (never text), with a TTL.
create table if not exists public.pr_product_events (
  id bigserial primary key,
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  user_id uuid,
  event text not null check (event ~ '^[a-z_]+(\.[a-z_]+)?$' and length(event) <= 60),
  properties jsonb not null default '{}' check (jsonb_typeof(properties) = 'object'),
  dedupe_key text check (dedupe_key is null or length(dedupe_key) <= 200),
  occurred_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '400 days')
);
create index if not exists pr_product_events_event on public.pr_product_events (event, occurred_at);
create index if not exists pr_product_events_workspace on public.pr_product_events (workspace_id, occurred_at);
create unique index if not exists pr_product_events_dedupe on public.pr_product_events (event, dedupe_key) where dedupe_key is not null;

-- Deterministic experiment assignment (hash bucketing) with exposure: no variant is hard-coded to win.
create table if not exists public.pr_experiment_assignments (
  experiment text not null check (length(experiment) <= 60),
  subject_key text not null check (length(subject_key) <= 120),
  variant text not null check (length(variant) <= 40),
  assigned_at timestamptz not null default now(),
  exposed_at timestamptz,
  primary key (experiment, subject_key)
);

-- Engagement Copilot drafts are labelled as such; approval and sending stay the existing reply path.
alter table public.pr_reply_drafts drop constraint if exists pr_reply_drafts_origin_check;
alter table public.pr_reply_drafts add constraint pr_reply_drafts_origin_check check (origin in ('manual','ai_fixture','copilot'));

do $$
declare t text;
begin
  foreach t in array array['pr_research_evidence','pr_strategy_hypotheses'] loop
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
  foreach t in array array['pr_product_events','pr_experiment_assignments'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;
grant usage, select on sequence public.pr_product_events_id_seq to service_role;

commit;
