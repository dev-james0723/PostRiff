-- Voice import (Integrated Brand Intelligence, spec 4.1): the person's own posts kept as text evidence for voice
-- analysis, the runs that read them, and the AI corpus analyses built on them. Additive, forward-only and idempotent;
-- it references public.pr_workspaces and postriff_private.member (001, 004) and postriff_private.browser_session_ok()
-- (119, RAPv2 H-1), so it applies on any chain that has 119.
-- Rollback = POSTRIFF_VOICE_IMPORT off: no route, no import step and no analysis touches these tables; only removal
-- still runs (a disconnect, and the cron's sweep of disconnected accounts, delete posts read through them). Dropping
-- the three tables removes all imported text.
-- Number 140: 131-135 are held by open pull requests and 136-139 by the Pricing V2 port (docs/postriff-migration-numbering.md).
begin;

-- One row per import run: a connector run that pages through a provider (official_api), or an export upload whose
-- records the browser parsed and sent (platform_export). One active run per account (the partial unique index).
-- `consent` is the voice-import.v1 record: whose writing it is, whether it blends into the brand voice, who agreed.
-- `removed` counts posts a complete newest-to-oldest pass no longer found at the provider and therefore deleted here.
create table if not exists public.pr_voice_imports (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  route text not null check (route in ('official_api','platform_export')),
  provider text not null check (provider ~ '^[a-z][a-z0-9_-]{0,31}$'),   -- one letter is a real id: X is `x`
  connection_id text,
  account_key text not null check (length(account_key) between 1 and 200),
  account_label text not null default '',
  status text not null default 'pending'
    check (status in ('pending','receiving','running','done','failed','cancelled')),
  consent jsonb not null,
  requested_since timestamptz,
  observed_oldest timestamptz,
  observed_newest timestamptz,
  discovered integer not null default 0,
  retrieved integer not null default 0,
  duplicates integer not null default 0,
  excluded integer not null default 0,
  unsupported integer not null default 0,
  failed_items integer not null default 0,
  removed integer not null default 0,
  pages integer not null default 0,
  more_remaining boolean,
  total_known boolean not null default false,
  cursor text,
  watermark text,
  attempts integer not null default 0,
  lease_owner text,
  lease_until timestamptz,
  retry_at timestamptz,
  failure_class text,
  requested_by text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_sync_at timestamptz,
  check ((route = 'official_api') = (connection_id is not null))
);
create unique index if not exists pr_voice_imports_one_active
  on public.pr_voice_imports (workspace_id, provider, account_key)
  where status in ('pending','receiving','running');
create index if not exists pr_voice_imports_claim
  on public.pr_voice_imports (status, retry_at) where status in ('pending','running');

-- One row per post of one account, whatever route supplied it (`routes` lists every one). `body` is the post's text;
-- `norm_hash` groups the same text across routes and platforms (`duplicate_of` points at the earliest copy).
create table if not exists public.pr_voice_posts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  provider text not null,
  account_key text not null,
  provider_post_id text not null check (length(provider_post_id) between 1 and 300),
  import_id uuid references public.pr_voice_imports(id) on delete set null,
  routes text[] not null default '{}',
  connection_id text,
  permalink text,
  published_at timestamptz,
  body text not null check (length(body) between 1 and 20000),
  body_hash text not null,
  norm_hash text not null,
  language text not null default 'und',
  content_type text not null default 'post',
  originality text not null default 'unknown'
    check (originality in ('original','reply','quote','repost','unknown')),
  authorship text not null default 'unknown'
    check (authorship in ('self','team','guest','unknown')),
  generation_origin text not null default 'unknown'
    check (generation_origin in ('rafii_published','unknown')),
  label text check (label in ('representative','outdated','aspirational')),
  voice_scope text not null default 'brand' check (voice_scope in ('brand','separate')),
  duplicate_of uuid,
  status text not null default 'retrieved'
    check (status in ('retrieved','eligible','excluded','gone')),
  exclusion_reason text,
  revision integer not null default 1,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (workspace_id, provider, account_key, provider_post_id)
);
create index if not exists pr_voice_posts_eligible
  on public.pr_voice_posts (workspace_id, status, provider, account_key);
create index if not exists pr_voice_posts_norm on public.pr_voice_posts (workspace_id, norm_hash);

-- One row per AI corpus analysis of one voice group (voice_corpus.py). Observations are abstract and carry post ids
-- as evidence, never post wording; the receipt records route, prompt version and corpus digest.
create table if not exists public.pr_voice_analyses (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  group_key text not null,
  status text not null default 'queued'
    check (status in ('queued','running','done','failed','cancelled','blocked')),
  route text,
  prompt_version text not null,
  corpus_digest text not null,
  eligible integer not null default 0,
  analysed integer not null default 0,
  batches integer not null default 0,
  batches_done integer not null default 0,
  cursor text,
  observations jsonb not null default '[]'::jsonb,
  receipt jsonb not null default '{}'::jsonb,
  failure_class text,
  attempts integer not null default 0,
  lease_owner text,
  lease_until timestamptz,
  requested_by text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists pr_voice_analyses_one_active
  on public.pr_voice_analyses (workspace_id, group_key) where status in ('queued','running');

-- Row security as in 035_growth_metric_reads: members may read their own workspace's rows; only the server writes.
do $$
declare t text;
begin
  foreach t in array array['pr_voice_imports','pr_voice_posts','pr_voice_analyses'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='tenant_read') then
      execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    end if;
    -- RAPv2 H-1 (119): every table the browser role can read also carries the restrictive session guard, so a revoked,
    -- deleted-account or under-assured session reads nothing here either.
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='rapv2_browser_session') then
      execute format('create policy rapv2_browser_session on public.%I as restrictive for select to authenticated using ((select postriff_private.browser_session_ok()))', t);
    end if;
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
