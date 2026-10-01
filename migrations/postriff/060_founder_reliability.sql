-- Founder Admin v2 P1/P2 (CONTRACTS §8.D, PRD §7.1 M25/M29, §8.7, §8.9): reliability instrumentation, public schema only.
-- Additive and idempotent; reapplication must be safe. Nothing here references the rafii_control schema, so this file can be
-- applied to production before the Control schema exists and the writers start collecting at once; the founder projections
-- over these tables are 066_founder_ops_views.sql. No role-membership grant is made to any migration runner.
--
-- Contents: route patterns with every identifier masked, enums, counts, durations, opaque connection ids and timestamps only.
-- No raw URL, query string, body, header, identity, address, handle, token or provider payload is stored. Every writer is
-- best-effort and treats a missing table as "not installed yet", so code may ship before this file is applied.
begin;

-- Request metrics: one row per minute x route pattern x status class, upserted by the consumer request hook
-- (postriff_phase2.request_metrics) from a bounded in-process buffer on a background thread, never inside a request's own
-- transaction. The route pattern keeps only known static route words (any other segment becomes ':id'; non-API paths are
-- '/:other'; an over-full buffer folds into '/:overflow'). UNLOGGED: a crash may lose the latest minutes, which the founder
-- metrics report as a gap, never as zero. Latency is a fixed log-scale histogram, the bounded p95 sample: bucket i counts
-- requests with duration <= the i-th upper bound (10, 25, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000,
-- 7500, 10000, 20000, 30000 ms; the 20th bucket is open-ended). Buckets add exactly across instances and minutes, so p50/p95 for
-- any window come from summed buckets and are never averages of per-minute percentiles. Retention: 30 days
-- (founder_metrics_ops reliability_purge).
create unlogged table if not exists public.pr_request_metrics (
  minute timestamptz not null,
  route_pattern text not null check (length(route_pattern) between 5 and 160
    and route_pattern ~ '^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|OTHER) /(:other|:overflow|api(/(:id|:more|[a-z][a-z0-9_.-]{0,23}))*)$'),
  status_class text not null check (status_class in ('1xx','2xx','3xx','4xx','5xx')),
  request_count bigint not null check (request_count > 0),
  duration_sum_ms double precision not null check (duration_sum_ms >= 0),
  duration_buckets bigint[] not null check (array_ndims(duration_buckets) = 1 and cardinality(duration_buckets) = 20 and 0 <= all(duration_buckets)),
  updated_at timestamptz not null default now(),
  primary key (minute, route_pattern, status_class)
);

-- The per-minute operational_signals.snapshot counts (queue delays, stuck/failed jobs, unsettled cost, notification backlog,
-- growth readings, SMS signals), written by the founder cron stage operational_snapshot. One row per minute; counts is a flat
-- object of non-negative integers keyed by counter name. Retention: 30 days.
create table if not exists public.pr_operational_snapshots (
  minute timestamptz primary key,
  observed_at timestamptz not null,
  status text not null check (status in ('ok','attention')),
  notification_delivery text not null default 'not_configured' check (notification_delivery in ('rafii_v2','not_configured')),
  counts jsonb not null default '{}'::jsonb check (jsonb_typeof(counts) = 'object' and octet_length(counts::text) <= 4000
    and not jsonb_path_exists(counts, 'strict $.* ? (@.type() != "number" || @ < 0)')),
  recorded_at timestamptz not null default now()
);

-- Connection health projection: workspace x connection x capability, recomputed hourly by the founder cron stage
-- connection_health from workspace channel state (the customer Channels card's connection_state) and
-- pr_channel_capabilities levels. state: ok | expiring (expires within 7 days) | expired | blocked (revoked, scopes missing,
-- identity unverified). No account handle, provider account id, scope list or token. Rows whose connection disappeared are
-- removed by the next refresh; reliability_purge drops rows not refreshed for 7 days.
create table if not exists public.pr_connection_health (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (connection_id ~ '^[A-Za-z0-9_.:-]{1,80}$'),
  capability text not null check (capability in ('identity','publish','schedule','analytics','comments_read','reply','moderate','media_types','webhooks')),
  provider text not null check (provider ~ '^[a-z0-9_]{1,40}$'),
  level text not null check (level in ('Direct','Assisted','Bridge','Unsupported','unknown')),
  state text not null check (state in ('ok','expiring','expired','blocked')),
  connection_state text not null check (connection_state in ('identity_known','scope_missing','token_expired','reauthorization_required','read_verified','publish_verified')),
  expires_at timestamptz,
  last_sync_at timestamptz,
  refreshed_at timestamptz not null default now(),
  primary key (workspace_id, connection_id, capability)
);
create index if not exists pr_connection_health_refreshed_idx on public.pr_connection_health(refreshed_at);

-- Founder source probes (founder_cron.probe) read the latest event of three consumer tables every minute; these indexes keep
-- each probe an index lookup instead of a scan. Conditional so a database without the notification core still applies.
create index if not exists pr_usage_ledger_settled_at_idx on public.pr_usage_ledger(at desc) where kind = 'settle' and cost_state = 'actual';
create index if not exists pr_billing_events_recency_idx on public.pr_billing_events(provider, processed_at desc);
do $$ begin
  if to_regclass('public.pr_notification_provider_events') is not null then
    create index if not exists pr_notification_provider_events_recency_idx on public.pr_notification_provider_events(provider, received_at desc);
  end if;
end $$;

-- Consumer-side tables: forced RLS, one service_only policy, grants to service_role only (045 pattern). Founder reads go
-- through the column-allowlisted projections of 066, never these tables.
do $$ declare t text; begin
  foreach t in array array['pr_request_metrics','pr_operational_snapshots','pr_connection_health'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public,anon,authenticated', t);
    execute format('grant select,insert,update,delete on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
