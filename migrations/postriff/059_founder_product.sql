-- Founder Admin P1 product slice (CONTRACTS §8.C, PRD §7.1 M23, §8.6): public-schema instrumentation only.
-- Additive and idempotent; nothing here refers to the rafii_control schema, so it can ship to production before the
-- Control schema exists. The founder projections over these tables live in 065_founder_product_views.sql.
-- Writers record ids, enums, counts and timestamps only: no drafts, prompts, message bodies, emails or URLs.
begin;

-- Founder reads of the product taxonomy (per-workspace first events) and of the learning-event transition proxies.
create index if not exists pr_product_events_workspace_event on public.pr_product_events (workspace_id, event, occurred_at);
create index if not exists pr_learning_events_kind_created on public.pr_learning_events (kind, created_at);

-- pr_learning_events expire after 180 days (010) and a learning reset deletes them, while activation and time-to-value
-- cohorts read their draft.approved / post.published rows as transition proxies. This daily rollup keeps how many
-- events of each kind a workspace had per report-time-zone day and the first one's timestamp. Written only by the
-- founder cron stage `product_rollups` over the consumer connection (idempotent recompute of the last three local days);
-- rows expire after 400 days (expires_at) and the same stage purges them.
create table if not exists public.pr_learning_daily_rollups (
  day date not null,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  kind text not null check (kind ~ '^[a-z_]+\.[a-z_]+$' and length(kind) <= 60),
  events integer not null check (events >= 0),
  first_at timestamptz not null,
  computed_at timestamptz not null default now(),
  expires_at date generated always as (day + 400) stored,
  primary key (day, workspace_id, kind)
);
create index if not exists pr_learning_daily_rollups_kind_first on public.pr_learning_daily_rollups (kind, first_at);
create index if not exists pr_learning_daily_rollups_expires on public.pr_learning_daily_rollups (expires_at);

alter table public.pr_learning_daily_rollups enable row level security;
alter table public.pr_learning_daily_rollups force row level security;
revoke all on public.pr_learning_daily_rollups from public, anon, authenticated;
grant select, insert, update, delete on public.pr_learning_daily_rollups to service_role;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_learning_daily_rollups' and policyname='service_only') then
    create policy service_only on public.pr_learning_daily_rollups for all to service_role using (true) with check (true);
  end if;
end $$;

commit;
