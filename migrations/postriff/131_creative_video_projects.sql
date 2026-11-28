-- Editorial data only. Library objects, media upload cleanup, jobs, approvals and costs retain their native owners.
begin;
create table if not exists public.pr_creative_video_projects (
    workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
    id uuid not null,
    request_key text not null,
    request_digest text not null,
    revision integer not null check (revision > 0),
    brief jsonb not null,
    created_by uuid not null,
    created_at timestamptz not null default now(),
    primary key (workspace_id, id),
    unique (workspace_id, request_key)
);
create table if not exists public.pr_creative_video_revisions (
    workspace_id uuid not null,
    project_id uuid not null,
    revision integer not null check (revision > 0),
    scenes jsonb not null check (jsonb_typeof(scenes) = 'array'),
    export jsonb,
    created_by uuid not null,
    created_at timestamptz not null default now(),
    primary key (workspace_id, project_id, revision),
    foreign key (workspace_id, project_id) references public.pr_creative_video_projects(workspace_id, id) on delete cascade
);
create index if not exists pr_creative_video_projects_recent
    on public.pr_creative_video_projects(workspace_id, created_at desc, id);
do $$
declare tab text;
begin
    foreach tab in array array['pr_creative_video_projects','pr_creative_video_revisions'] loop
        execute format('alter table public.%I enable row level security',tab);
        execute format('alter table public.%I force row level security',tab);
        execute format('revoke all on public.%I from public, anon, authenticated',tab);
        execute format('grant all on public.%I to service_role',tab);
        if not exists (select 1 from pg_policies where schemaname='public' and tablename=tab and policyname='service_only') then
            execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',tab);
        end if;
    end loop;
end $$;
commit;
