-- Rafii Intelligent Library (2026-10-08 package, engineering spec §4). Additive only.
-- Server-only tables: membership, purpose and grant checks run in library_intelligence before SQL access.
-- Rollback: disable RAFII_LIBRARY_* flags; these tables may remain. Originals, chunks and legacy media are untouched.
-- Asset keys are 32-hex strings so legacy photo/video ids (workspace JSON) and normalized rows share one identity.
begin;

-- Version identity. Each normalized row is one immutable content version; lineage_id is the stable asset identity.
alter table public.pr_library_assets add column if not exists lineage_id uuid;
alter table public.pr_library_assets add column if not exists version_no integer not null default 1 check (version_no between 1 and 10000);
alter table public.pr_library_assets add column if not exists source_kind text not null default 'upload';
alter table public.pr_library_assets drop constraint if exists pr_library_assets_source_kind_check;
alter table public.pr_library_assets add constraint pr_library_assets_source_kind_check check (source_kind in ('upload','link','note','artifact'));
alter table public.pr_library_assets add column if not exists media jsonb not null default '{}'::jsonb;
alter table public.pr_library_assets drop constraint if exists pr_library_assets_media_check;
alter table public.pr_library_assets add constraint pr_library_assets_media_check check (jsonb_typeof(media) = 'object');
create index if not exists pr_library_assets_lineage on public.pr_library_assets(workspace_id, lineage_id, version_no) where lineage_id is not null;

-- Per-workspace revisions: grants (consent), index generation and organization. Bumped in the same transaction as the change.
create table if not exists public.pr_library_policy (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  grant_revision bigint not null default 0 check (grant_revision >= 0),
  index_generation integer not null default 1 check (index_generation >= 1),
  organization_revision bigint not null default 0 check (organization_revision >= 0),
  updated_at timestamptz not null default now()
);

-- Explicit, scoped, revocable grants. grant_type 'purpose' covers browse/answer/draft_evidence/voice/memory/public_use;
-- 'processing' covers a location (local/cloud) and provider category. Collection grants snapshot their members.
create table if not exists public.pr_library_grants (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  grant_type text not null check (grant_type in ('purpose','processing')),
  scope_kind text not null check (scope_kind in ('workspace','asset','collection')),
  scope_key text not null check (scope_key = '*' or scope_key ~ '^[0-9a-f]{32}$'),
  member_keys text[] not null default '{}' check (cardinality(member_keys) <= 5000),
  purpose text check (purpose is null or purpose in ('browse','answer','draft_evidence','voice','memory','public_use')),
  location text check (location is null or location in ('local','cloud')),
  category text check (category is null or category in ('extract','ocr','asr','vision','embedding','llm')),
  attestation jsonb not null default '{}'::jsonb check (jsonb_typeof(attestation) = 'object'),
  granted_by uuid not null,
  granted_revision bigint not null,
  granted_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoked_by uuid,
  revoked_revision bigint,
  check ((grant_type = 'purpose' and purpose is not null and location is null and category is null)
      or (grant_type = 'processing' and purpose is null and location is not null and category is not null))
);
create index if not exists pr_library_grants_active on public.pr_library_grants(workspace_id, grant_type, scope_kind) where revoked_at is null;

-- Per-capability truth. Stored/playable is never collapsed into "understood".
create table if not exists public.pr_library_capabilities (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  capability text not null check (capability in ('preview','extract','transcribe','visual','embed_text','embed_visual','understand')),
  state text not null check (state in ('not_requested','queued','processing','ready','partial','unsupported','failed','cancelled','blocked_permission','blocked_budget')),
  progress jsonb check (progress is null or jsonb_typeof(progress) = 'object'),
  error_code text check (error_code is null or length(error_code) <= 80),
  detail text check (detail is null or length(detail) <= 300),
  retryable boolean not null default false,
  job_id uuid,
  processor_version text check (processor_version is null or length(processor_version) <= 80),
  provider jsonb check (provider is null or jsonb_typeof(provider) = 'object'),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  primary key (workspace_id, asset_key, capability)
);

-- Durable jobs keyed by workspace/version/capability/processor/consent revision; leased with heartbeat.
create table if not exists public.pr_library_jobs (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  capability text not null check (capability in ('preview','extract','transcribe','visual','embed_text','embed_visual','understand')),
  processor_version text not null check (length(processor_version) between 1 and 80),
  consent_revision bigint not null,
  idempotency_key text not null check (length(idempotency_key) between 16 and 300),
  status text not null default 'queued' check (status in ('queued','processing','completed','partial','failed','cancelled','blocked')),
  attempts integer not null default 0 check (attempts between 0 and 20),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  lease_token uuid,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  next_attempt_at timestamptz not null default now(),
  reservation jsonb check (reservation is null or jsonb_typeof(reservation) = 'object'),
  cost jsonb check (cost is null or jsonb_typeof(cost) = 'object'),
  error_category text check (error_category is null or error_category in ('retryable','permanent','permission','budget','cancelled','corrupt','timeout','unsupported')),
  error_code text check (error_code is null or length(error_code) <= 80),
  timings jsonb not null default '{}'::jsonb,
  cleanup text check (cleanup is null or length(cleanup) <= 80),
  requested_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (workspace_id, idempotency_key)
);
create index if not exists pr_library_jobs_due on public.pr_library_jobs(next_attempt_at, lease_expires_at) where status in ('queued','processing');
create index if not exists pr_library_jobs_asset on public.pr_library_jobs(workspace_id, asset_key, capability);

-- Normalized segments with structural locators. search_terms is the versioned multilingual normalization (CJK bigrams,
-- Traditional/Simplified folding, Latin casefold) computed in Python; corrections create new rows and supersede old ones.
create table if not exists public.pr_library_segments (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  version_key text not null check (version_key ~ '^[0-9a-f]{32}$'),
  ordinal integer not null check (ordinal between 0 and 1000000),
  kind text not null check (kind in ('text','page','slide','sheet','transcript','ocr','caption','scene','moment','note','metadata')),
  text text not null check (length(text) <= 20000),
  language text check (language is null or language ~ '^[a-z]{2,3}(-[A-Za-z]{2,4})?$'),
  locator jsonb check (locator is null or jsonb_typeof(locator) = 'object'),
  extractor text not null check (length(extractor) between 1 and 80),
  extractor_version text not null check (length(extractor_version) between 1 and 80),
  text_hash text not null check (text_hash ~ '^[0-9a-f]{64}$'),
  source_sha256 text check (source_sha256 is null or source_sha256 ~ '^[0-9a-f]{64}$'),
  speaker_label text check (speaker_label is null or length(speaker_label) <= 60),
  origin text not null check (origin in ('extracted','ocr','transcript','user','ai_suggested')),
  uncertainty text check (uncertainty is null or length(uncertainty) <= 200),
  correction_of uuid,
  superseded_at timestamptz,
  created_by uuid,
  normalizer_version integer not null default 1,
  search_terms text not null default '',
  search_vector tsvector generated always as (to_tsvector('simple', search_terms)) stored,
  created_at timestamptz not null default now()
);
create index if not exists pr_library_segments_asset on public.pr_library_segments(workspace_id, asset_key, version_key, ordinal) where superseded_at is null;
create index if not exists pr_library_segments_search on public.pr_library_segments using gin(search_vector) where superseded_at is null;
create index if not exists pr_library_segments_workspace on public.pr_library_segments(workspace_id) where superseded_at is null;
create index if not exists pr_library_segments_version on public.pr_library_segments(workspace_id, version_key) where superseded_at is null;

-- Understanding annotations. Human confirmations are separate rows that reprocessing never overwrites.
create table if not exists public.pr_library_annotations (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  version_key text not null check (version_key ~ '^[0-9a-f]{32}$'),
  segment_id uuid,
  field text not null check (field ~ '^[a-z][a-z0-9_]{0,40}$'),
  value jsonb not null,
  evidence jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence) = 'array'),
  origin text not null check (origin in ('extracted','ai_suggested','user_confirmed')),
  confidence real check (confidence is null or (confidence >= 0 and confidence <= 1)),
  model text check (model is null or length(model) <= 120),
  processor_version text check (processor_version is null or length(processor_version) <= 80),
  active boolean not null default true,
  supersedes uuid,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists pr_library_annotations_asset on public.pr_library_annotations(workspace_id, asset_key, field) where active;

-- Embeddings. The vector column exists only where pgvector is installed; otherwise semantic/visual modes report
-- themselves unavailable and lexical search continues. Never mix models: model_id + dims + generation are explicit.
create table if not exists public.pr_library_embeddings (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  version_key text not null check (version_key ~ '^[0-9a-f]{32}$'),
  segment_id uuid,
  modality text not null check (modality in ('text','visual')),
  model_id text not null check (length(model_id) between 1 and 120),
  dims integer not null check (dims between 8 and 4096),
  index_generation integer not null,
  consent_revision bigint not null,
  status text not null default 'active' check (status in ('active','revoked','superseded')),
  created_at timestamptz not null default now()
);
create index if not exists pr_library_embeddings_asset on public.pr_library_embeddings(workspace_id, asset_key, modality) where status = 'active';
create index if not exists pr_library_embeddings_version on public.pr_library_embeddings(workspace_id, version_key, modality) where status = 'active';
alter table public.pr_library_embeddings add column if not exists superseded_at timestamptz;
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'vector') then
    create extension if not exists vector;
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='pr_library_embeddings' and column_name='embedding') then
      execute 'alter table public.pr_library_embeddings add column embedding vector';
    end if;
    execute 'create index if not exists pr_library_embeddings_text_1024 on public.pr_library_embeddings using hnsw ((embedding::vector(1024)) vector_cosine_ops) where status = ''active'' and modality = ''text'' and dims = 1024';
    execute 'create index if not exists pr_library_embeddings_visual_256 on public.pr_library_embeddings using hnsw ((embedding::vector(256)) vector_cosine_ops) where status = ''active'' and modality = ''visual'' and dims = 256';
  end if;
end $$;

-- Smart Collections: an allowlisted rule AST, never SQL or prompt text. Membership stays in collection_items (no byte copies).
alter table public.pr_library_collections add column if not exists kind text not null default 'manual';
alter table public.pr_library_collections drop constraint if exists pr_library_collections_kind_check;
alter table public.pr_library_collections add constraint pr_library_collections_kind_check check (kind in ('manual','smart'));
alter table public.pr_library_collections add column if not exists rule jsonb;
alter table public.pr_library_collections add column if not exists rule_schema integer;
alter table public.pr_library_collections add column if not exists explanation text;
alter table public.pr_library_collections add column if not exists revision bigint not null default 1;
alter table public.pr_library_collections add column if not exists last_evaluated_revision bigint;
alter table public.pr_library_collections add column if not exists updated_at timestamptz not null default now();
alter table public.pr_library_collection_items add column if not exists origin text not null default 'manual';
alter table public.pr_library_collection_items drop constraint if exists pr_library_collection_items_origin_check;
alter table public.pr_library_collection_items add constraint pr_library_collection_items_origin_check check (origin in ('manual','rule','include'));
alter table public.pr_library_collection_items add column if not exists added_at timestamptz not null default now();
create table if not exists public.pr_library_collection_overrides (
  workspace_id uuid not null,
  collection_id uuid not null,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  mode text not null check (mode in ('include','exclude')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  primary key (workspace_id, collection_id, asset_key),
  foreign key (workspace_id, collection_id) references public.pr_library_collections(workspace_id, id) on delete cascade
);
create table if not exists public.pr_library_collection_revisions (
  workspace_id uuid not null,
  collection_id uuid not null,
  revision bigint not null,
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  primary key (workspace_id, collection_id, revision),
  foreign key (workspace_id, collection_id) references public.pr_library_collections(workspace_id, id) on delete cascade
);

-- Explicit relations. derived_from/version_of/supersedes are kept acyclic by the service; similar_to is a suggestion.
create table if not exists public.pr_library_relations (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  from_key text not null check (from_key ~ '^[0-9a-f]{32}$'),
  from_version text not null check (from_version ~ '^[0-9a-f]{32}$'),
  from_segment uuid,
  to_kind text not null check (to_kind in ('asset','draft','post','source_pack','idea')),
  to_key text not null check (length(to_key) between 1 and 120),
  to_version text check (to_version is null or to_version ~ '^[0-9a-f]{32}$'),
  relation text not null check (relation in ('derived_from','version_of','similar_to','used_in','supersedes')),
  status text not null default 'active' check (status in ('active','suggested','dismissed','stale')),
  origin text not null check (origin in ('system','user','ai_suggested')),
  evidence jsonb not null default '{}'::jsonb check (jsonb_typeof(evidence) = 'object'),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists pr_library_relations_identity on public.pr_library_relations(workspace_id, from_key, from_version, relation, to_kind, to_key, coalesce(to_version, ''), coalesce(from_segment::text, ''));
create index if not exists pr_library_relations_to on public.pr_library_relations(workspace_id, to_kind, to_key);
create index if not exists pr_library_relations_from_version on public.pr_library_relations(workspace_id, from_version, relation);
create index if not exists pr_library_relations_to_version on public.pr_library_relations(workspace_id, to_version) where to_kind = 'asset';
create index if not exists pr_library_collections_smart_due on public.pr_library_collections(updated_at) where kind = 'smart';

-- Voice spans: an index of author-attested Library spans. The canonical sample, its grants, revocation and the derived
-- speaker profile stay in the existing voice system (state.sources kind 'voice_sample'); voice_source_id links to it.
-- Negative examples and persona/language scope live here. No automatic admission; no second profile store.
create table if not exists public.pr_library_voice_samples (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  voice_source_id text check (voice_source_id is null or length(voice_source_id) <= 80),
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  version_key text not null check (version_key ~ '^[0-9a-f]{32}$'),
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{64}$'),
  locator jsonb not null check (jsonb_typeof(locator) = 'object'),
  text text check (text is null or length(text) between 1 and 4000),
  text_hash text not null check (text_hash ~ '^[0-9a-f]{64}$'),
  persona_id text not null check (length(persona_id) between 1 and 80),
  brand text check (brand is null or length(brand) <= 80),
  language text not null check (language ~ '^[a-z]{2,3}(-[A-Za-z]{2,4})?$'),
  polarity text not null check (polarity in ('positive','negative')),
  attestation jsonb not null check (jsonb_typeof(attestation) = 'object'),
  consent_revision bigint not null,
  status text not null default 'approved' check (status in ('approved','revoked')),
  revision bigint not null default 1,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoked_by uuid,
  check (status = 'revoked' or text is not null)
);
create index if not exists pr_library_voice_samples_scope on public.pr_library_voice_samples(workspace_id, persona_id, language) where status = 'approved';

-- Task source packs: evidence and style refs kept apart; grant/source revisions snapshotted and revalidated on use.
create table if not exists public.pr_library_source_packs (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  revision integer not null default 1,
  task_context jsonb not null check (jsonb_typeof(task_context) = 'object'),
  evidence_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence_refs) = 'array'),
  style_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(style_refs) = 'array'),
  rationale jsonb not null default '[]'::jsonb check (jsonb_typeof(rationale) = 'array'),
  gaps jsonb not null default '[]'::jsonb check (jsonb_typeof(gaps) = 'array'),
  rights_warnings jsonb not null default '[]'::jsonb check (jsonb_typeof(rights_warnings) = 'array'),
  grant_revision bigint not null,
  status text not null default 'draft' check (status in ('draft','attached','superseded','revoked')),
  draft_id text check (draft_id is null or length(draft_id) <= 120),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Final agent deliverables registered once per run/output; scratch never reaches this table.
create table if not exists public.pr_library_artifacts (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  run_id text not null check (length(run_id) between 1 and 80),
  output_id text not null check (length(output_id) between 1 and 80),
  idempotency_key text not null check (length(idempotency_key) between 16 and 160),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  asset_key text check (asset_key is null or asset_key ~ '^[0-9a-f]{32}$'),
  source_pack_id uuid,
  status text not null check (status in ('registering','registered','failed')),
  error_code text check (error_code is null or length(error_code) <= 80),
  attempts integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, run_id, output_id),
  unique (workspace_id, idempotency_key)
);

-- Quiet proactive suggestions. In-app only by default; deduplicated per recipient.
create table if not exists public.pr_library_suggestions (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  recipient uuid not null,
  dedup_key text not null check (length(dedup_key) between 8 and 300),
  category text not null check (category in ('outdated_source','unused_relevant','missing_input','failed_processing','organization','permission','source_integrity')),
  critical boolean not null default false,
  trigger jsonb not null default '{}'::jsonb check (jsonb_typeof(trigger) = 'object'),
  candidate_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(candidate_refs) = 'array'),
  affected jsonb not null default '[]'::jsonb check (jsonb_typeof(affected) = 'array'),
  reason text not null check (length(reason) between 1 and 400),
  state text not null default 'new' check (state in ('new','seen','dismissed','snoozed','applied','expired','suppressed')),
  snooze_until timestamptz,
  consent_revision bigint not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz,
  unique (workspace_id, recipient, dedup_key)
);
create index if not exists pr_library_suggestions_inbox on public.pr_library_suggestions(workspace_id, recipient, state, created_at desc);
create table if not exists public.pr_library_suggestion_prefs (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  recipient uuid not null,
  category text not null,
  disabled boolean not null default false,
  snooze_days integer not null default 7 check (snooze_days between 1 and 90),
  external_opt_in boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, recipient, category)
);

-- Descriptive usage: asset/version/segment to draft/post/channel with available metrics; missing metrics stay null.
create table if not exists public.pr_library_usage_events (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
  version_key text check (version_key is null or version_key ~ '^[0-9a-f]{32}$'),
  segment_id uuid,
  event_type text not null check (event_type in ('source_pack','draft_attached','post_scheduled','post_published','agent_answer','downloaded')),
  draft_id text check (draft_id is null or length(draft_id) <= 120),
  post_id text check (post_id is null or length(post_id) <= 120),
  channel text check (channel is null or length(channel) <= 60),
  dedup_key text not null check (length(dedup_key) between 8 and 300),
  source jsonb not null default '{}'::jsonb check (jsonb_typeof(source) = 'object'),
  metrics jsonb check (metrics is null or jsonb_typeof(metrics) = 'object'),
  metrics_at timestamptz,
  at timestamptz not null default now(),
  unique (workspace_id, dedup_key)
);
create index if not exists pr_library_usage_asset on public.pr_library_usage_events(workspace_id, asset_key, at desc);

-- Idempotent action receipts for the deterministic Library and generated task UIs.
create table if not exists public.pr_library_action_receipts (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 16 and 120),
  actor uuid not null,
  action_type text not null check (length(action_type) between 1 and 60),
  request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
  status text not null check (status in ('applied','requires_confirmation','conflict','denied')),
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (workspace_id, idempotency_key)
);

-- Content-free feature metrics (counts, latencies, cost class). Never prompts, text or URLs.
create table if not exists public.pr_library_metrics (
  id bigserial primary key,
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  feature text not null check (feature ~ '^[a-z][a-z0-9_.]{0,60}$'),
  event text not null check (event ~ '^[a-z][a-z0-9_.]{0,60}$'),
  value double precision,
  dims jsonb not null default '{}'::jsonb check (jsonb_typeof(dims) = 'object'),
  at timestamptz not null default now()
);
create index if not exists pr_library_metrics_feature on public.pr_library_metrics(feature, event, at desc);

do $$ declare t text; begin
 foreach t in array array['pr_library_policy','pr_library_grants','pr_library_capabilities','pr_library_jobs','pr_library_segments',
   'pr_library_annotations','pr_library_embeddings','pr_library_collection_overrides','pr_library_collection_revisions',
   'pr_library_relations','pr_library_voice_samples','pr_library_source_packs','pr_library_artifacts',
   'pr_library_suggestions','pr_library_suggestion_prefs','pr_library_usage_events','pr_library_action_receipts','pr_library_metrics'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',t);
  end if;
 end loop;
end $$;
grant usage, select on sequence public.pr_library_metrics_id_seq to service_role;

commit;
