-- Founder Admin v2 P1/P2 (CONTRACTS §8.B; PRD §8.0, §8.1, §8.3, §8.8, §8.9): AI usage instrumentation, public schema only.
-- Additive and idempotent; reapplication must be safe. Nothing here references the rafii_control schema, so this file can be
-- applied to production before the Control schema exists and the metering write points start recording at once (until then
-- they skip silently: postriff_phase2.ai_call_events). The founder projections are 064_founder_ai_views.sql. No role-membership
-- grant is made to any migration runner.
--
-- Contents: ids, enums, counts, amounts and timestamps only. No prompt, output, provider payload, message or customer text.
-- Costs are micro-USD written when the attempt is recorded (never re-priced from today's prices); NULL is unknown, never zero.
-- Retention: call events and their settlements 400 days, rollups 400 days (founder cron stage ai_usage_purge).
begin;

-- One row per AI provider attempt, every feature (PRD §8.1). OpenAI semantics: input_tokens include cached_input_tokens and
-- output_tokens include reasoning_tokens (PRD §8.0). cost_source: gateway|provider (reported), table:<pr_price_versions.version>
-- (computed at write time) or unknown (cost NULL). dedupe_key = sha256 of the attempt's identity (workspace, feature, run,
-- reservation, workload, attempt number, physical attempt id, provider request id), so recording an attempt twice is a no-op;
-- it is unique on its own because the workspace is part of it (stronger than unique(workspace_id, dedupe_key) and valid for
-- workspace-less system calls). A cost learned later goes to pr_ai_call_settlements; this row never changes.
create table if not exists public.pr_ai_call_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  user_id uuid,
  feature text not null check (feature ~ '^[a-z][a-z0-9_]{0,39}$'),
  workload text check (workload is null or workload ~ '^[a-z][a-z0-9_.]{0,59}$'),
  run_id uuid,
  reservation_id uuid,
  attempt_no smallint not null default 1 check (attempt_no between 1 and 100),
  physical_attempt_id text check (physical_attempt_id is null or physical_attempt_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,119}$'),
  provider text not null check (provider ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,59}$'),
  model text not null check (model ~ '^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$'),
  route text not null default 'primary' check (route in ('primary','fallback')),
  provider_request_id text check (provider_request_id is null or provider_request_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,199}$'),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  cached_input_tokens integer check (cached_input_tokens is null or cached_input_tokens >= 0),
  reasoning_tokens integer check (reasoning_tokens is null or reasoning_tokens >= 0),
  images smallint check (images is null or images between 0 and 100),
  audio_seconds numeric(12,3) check (audio_seconds is null or audio_seconds >= 0),
  cost_usd_micro bigint check (cost_usd_micro is null or cost_usd_micro >= 0),
  cost_source text not null check (cost_source in ('gateway','provider','unknown') or cost_source ~ '^table:[A-Za-z0-9._-]{1,60}$'),
  price_version text check (price_version is null or price_version ~ '^[A-Za-z0-9._-]{1,60}$'),
  status text not null check (status in ('ok','failed','cancelled','rate_limited','timeout','unknown')),
  http_status smallint check (http_status is null or http_status between 100 and 599),
  latency_ms integer check (latency_ms is null or latency_ms >= 0),
  ai_usage_exempt boolean not null default false,
  started_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  dedupe_key text not null check (dedupe_key ~ '^[0-9a-f]{64}$'),
  constraint pr_ai_call_events_dedupe unique (dedupe_key),
  constraint pr_ai_call_events_cost_known check ((cost_usd_micro is null) = (cost_source = 'unknown'))
);
create index if not exists pr_ai_call_events_started on public.pr_ai_call_events(started_at);
create index if not exists pr_ai_call_events_workspace on public.pr_ai_call_events(workspace_id, started_at desc);
create index if not exists pr_ai_call_events_reservation on public.pr_ai_call_events(reservation_id) where reservation_id is not null;

-- Late cost (and audio seconds) for an attempt recorded with an unknown cost (PRD §8.1 late events): a sidecar, never an update.
create table if not exists public.pr_ai_call_settlements (
  id uuid primary key default gen_random_uuid(),
  call_event_id uuid not null references public.pr_ai_call_events(id) on delete cascade,
  cost_usd_micro bigint not null check (cost_usd_micro >= 0),
  source text not null check (source in ('gateway','provider','reconcile') or source ~ '^table:[A-Za-z0-9._-]{1,60}$'),
  audio_seconds numeric(12,3) check (audio_seconds is null or audio_seconds >= 0),
  at timestamptz not null default now(),
  constraint pr_ai_call_settlements_once unique (call_event_id, source)
);

-- Versioned price tables (PRD §8.3). A version is immutable once written (reapplication never changes a seeded row).
create table if not exists public.pr_price_versions (
  version text primary key check (version ~ '^[A-Za-z0-9._-]{1,60}$'),
  effective_from timestamptz not null,
  effective_to timestamptz,
  source_url text check (source_url is null or (source_url ~ '^https://' and length(source_url) <= 300)),
  fetched_at timestamptz,
  prices jsonb not null check (jsonb_typeof(prices) = 'object'),
  check (effective_to is null or effective_to > effective_from)
);
-- Seed: the tables the code prices with today (tests/test_founder_ai_call_events.py keeps each one equal to its constants).
insert into public.pr_price_versions(version,effective_from,source_url,fetched_at,prices) values
 ('gateway-list-2026-09-24','2026-09-24T00:00:00Z','https://ai-gateway.vercel.sh/v1/models','2026-09-24T00:00:00Z',
  '{"unit":"usd_per_million_tokens","cachedInput":"billed at the input price (no cached rate recorded)","source":"postriff_phase2.model_runtime.DEFAULT_PRICES","models":{"anthropic/claude-sonnet-5":{"input":2.0,"output":10.0},"anthropic/claude-opus-5.5":{"input":4.0,"output":20.0},"anthropic/claude-haiku-4.5":{"input":1.0,"output":5.0},"openai/gpt-6-sol":{"input":2.0,"output":10.0},"openai/gpt-4.1-mini":{"input":0.4,"output":1.6},"google/gemini-3.1-pro-preview":{"input":2.0,"output":12.0},"google/gemini-2.5-flash":{"input":0.3,"output":2.5}}}'::jsonb),
 ('agent-v2-2026-09-24','2026-09-24T00:00:00Z','https://developers.openai.com/','2026-09-24T00:00:00Z',
  '{"unit":"usd_per_million_tokens","cachedInput":"billed at the input price (no cached rate recorded)","source":"postriff_phase2.agent_runtime_v2.config.DEFAULT_PRICES","models":{"gpt-6-sol":{"input":2.0,"output":10.0},"gpt-6-luna":{"input":0.1,"output":0.5},"gpt-6-astra":{"input":10.0,"output":50.0},"gpt-5.6-terra":{"input":2.0,"output":12.0}}}'::jsonb),
 ('media-constants-2026-09-24','2026-09-24T00:00:00Z','https://developers.openai.com/','2026-09-24T00:00:00Z',
  '{"source":"agent_runtime_v2.config DEFAULT_IMAGE_ESTIMATE_USD_MICRO and DEFAULT_LIVE_USD_MICRO_PER_MINUTE; image_runtime.DEFAULT_ESTIMATE_USD_MICRO","images":{"image_fast":{"usdMicroPerImage":40000},"image_quality":{"usdMicroPerImage":190000},"openai/gpt-image-2.5-flare":{"usdMicroPerImage":100000}},"voice":{"usdMicroPerMinute":50000,"creationSeconds":15}}'::jsonb),
 ('pricing-provisional-2026-09-24','2026-09-24T00:00:00Z',null,'2026-09-24T00:00:00Z',
  '{"kind":"customer_pricing","status":"provisional: not active","source":"docs/launch-20260923/pricing-2026-09-24.json","creditPolicy":"credits-candidate-2026-09-23-v1","creditsPerProviderUsd":300}'::jsonb)
on conflict (version) do nothing;

-- Daily usage rollups (PRD §8.8), recomputed hourly for the last three report-time-zone days by the founder cron
-- (usage_rollups stage): calls, statuses and tokens from pr_ai_call_events (+ settlements), costs from the canonical ledger
-- (actual, unknown = held estimate of unreconciled unknown rows, estimated = reservation estimate of settled work).
-- actor_class is what the consumer connection can see (system = no workspace, exempt_developer = aiUsageExempt, else
-- customer); internal/test/demo classification is applied at read time by the founder views. Token sums are NULL when no
-- call of the group reported tokens; tokens_unreported counts calls without token counts (a partial sum, never zero-filled).
create table if not exists public.pr_usage_rollups (
  day date not null,
  workspace_id uuid,
  user_id uuid,
  feature text not null check (feature ~ '^[a-z][a-z0-9_]{0,39}$'),
  model text not null check (length(model) between 1 and 160),
  provider text not null check (length(provider) between 1 and 60),
  actor_class text not null check (actor_class in ('customer','exempt_developer','internal','test','demo','system')),
  calls integer not null default 0 check (calls >= 0),
  ok integer not null default 0 check (ok >= 0),
  failed integer not null default 0 check (failed >= 0),
  cancelled integer not null default 0 check (cancelled >= 0),
  unknown integer not null default 0 check (unknown >= 0),
  input_tokens bigint check (input_tokens is null or input_tokens >= 0),
  cached_tokens bigint check (cached_tokens is null or cached_tokens >= 0),
  output_tokens bigint check (output_tokens is null or output_tokens >= 0),
  reasoning_tokens bigint check (reasoning_tokens is null or reasoning_tokens >= 0),
  tokens_unreported integer not null default 0 check (tokens_unreported >= 0),
  images integer not null default 0 check (images >= 0),
  audio_seconds numeric(14,3) not null default 0 check (audio_seconds >= 0),
  estimated_usd_micro bigint not null default 0 check (estimated_usd_micro >= 0),
  actual_usd_micro bigint not null default 0 check (actual_usd_micro >= 0),
  unknown_usd_micro bigint not null default 0 check (unknown_usd_micro >= 0),
  rollup_version text not null check (rollup_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'),
  computed_at timestamptz not null default now()
);
create unique index if not exists pr_usage_rollups_key on public.pr_usage_rollups(day, coalesce(workspace_id,'00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(user_id,'00000000-0000-0000-0000-000000000000'::uuid), feature, model, provider, actor_class);
create index if not exists pr_usage_rollups_workspace on public.pr_usage_rollups(workspace_id, day);

-- Service-only consumer tables (045 pattern): forced RLS, one service_only policy, grants to service_role only.
do $$ declare t text; begin
 foreach t in array array['pr_ai_call_events','pr_ai_call_settlements','pr_price_versions','pr_usage_rollups'] loop
  execute format('alter table public.%I enable row level security', t);
  execute format('alter table public.%I force row level security', t);
  execute format('revoke all on public.%I from public, anon, authenticated', t);
  execute format('grant all on public.%I to service_role', t);
  if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end if;
 end loop;
end $$;
commit;
