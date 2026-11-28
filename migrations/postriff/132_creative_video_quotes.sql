begin;
-- One live estimate per actor and shot bounds slider traffic. Consumed authority is recorded on
-- the immutable approval and the native ledger. Replacing a quote always assigns a fresh ID.
create table if not exists public.pr_creative_video_quotes (
    workspace_id uuid not null,
    project_id uuid not null,
    actor uuid not null,
    scene_id text not null,
    id uuid not null default gen_random_uuid(),
    expires_at timestamptz not null,
    binding jsonb not null,
    primary key (workspace_id, project_id, actor, scene_id),
    unique (workspace_id, id),
    foreign key (workspace_id, project_id) references public.pr_creative_video_projects on delete cascade
);
alter table public.pr_creative_video_quotes enable row level security;
alter table public.pr_creative_video_quotes force row level security;
revoke all on public.pr_creative_video_quotes from public, anon, authenticated;
grant all on public.pr_creative_video_quotes to service_role;
drop policy if exists service_only on public.pr_creative_video_quotes;
create policy service_only on public.pr_creative_video_quotes for all to service_role using (true) with check (true);
create table if not exists public.pr_creative_video_model_policy (
    environment text not null check(environment in ('local','staging','production')),
    model text not null, paused boolean not null, updated_at timestamptz not null default now(), actor uuid not null,
    primary key(environment,model)
);
alter table public.pr_creative_video_model_policy enable row level security;
alter table public.pr_creative_video_model_policy force row level security;
revoke all on public.pr_creative_video_model_policy from public, anon, authenticated, service_role;
grant select on public.pr_creative_video_model_policy to service_role;
drop policy if exists service_read on public.pr_creative_video_model_policy;
create policy service_read on public.pr_creative_video_model_policy for select to service_role using(true);
create index if not exists pr_creative_video_recent_jobs on public.pr_jobs(workspace_id,created_at desc)
    where body->>'kind'='creative_video_scene';
commit;
