-- Candidate migration: personal workspace tokens. Never store or return the bearer secret again.
create table if not exists public.pr_api_tokens (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  created_by uuid not null,
  name text not null check (char_length(name) between 1 and 40),
  prefix text not null,
  token_hash text not null unique check (length(token_hash) = 64),
  scopes text[] not null check (scopes <@ array['read','draft']::text[] and 'read' = any(scopes)),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null check (expires_at > created_at and expires_at <= created_at + interval '366 days'),
  last_used_at timestamptz,
  last_used_client text,
  revoked_at timestamptz
);
create index if not exists pr_api_tokens_workspace on public.pr_api_tokens(workspace_id, revoked_at);
alter table public.pr_api_tokens enable row level security;
alter table public.pr_api_tokens force row level security;
revoke all on public.pr_api_tokens from public, anon, authenticated;
grant all on public.pr_api_tokens to service_role;
create policy api_tokens_service_only on public.pr_api_tokens for all to service_role using (true) with check (true);
