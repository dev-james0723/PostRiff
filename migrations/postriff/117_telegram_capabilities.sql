-- Candidate only: deploy separately after reviewing and validating RLS/worker compatibility.
begin;
create table public.pr_telegram_destinations (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  bot_id bigint not null,
  chat_id bigint not null,
  mode text not null check (mode in ('bot','business')),
  snapshot jsonb not null,
  verified_at timestamptz not null,
  revoked_at timestamptz,
  primary key(workspace_id,connection_id),
  foreign key(workspace_id,connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade
);
create index telegram_destination_route on public.pr_telegram_destinations(bot_id,chat_id) where revoked_at is null;
create table public.pr_telegram_bot_grants (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  bot_id bigint not null unique,
  username text not null,
  token_ciphertext text not null,
  webhook_ciphertext text not null,
  key_id text not null,
  connected_at timestamptz not null default now(),
  revoked_at timestamptz
);
create table public.pr_telegram_updates (
  bot_id bigint not null,
  update_id bigint not null,
  digest text not null check(length(digest)=64),
  update_type text not null,
  received_at timestamptz not null default now(),
  primary key(bot_id,update_id)
);
create table public.pr_telegram_messages (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  chat_id bigint not null,
  message_id bigint not null,
  bot_id bigint not null,
  date bigint not null,
  edit_date bigint,
  message_thread_id bigint,
  direct_messages_topic_id bigint,
  reply_to_message_id bigint,
  discussion_chat_id bigint,
  discussion_message_id bigint,
  media_group_id text,
  business_connection_id text,
  poll_id text,
  rafii_job_id text,
  source_variant_id text,
  api_path text,
  url text,
  message_ciphertext text not null,
  key_id text not null,
  source_update_id bigint,
  deleted boolean not null default false,
  primary key(workspace_id,connection_id,chat_id,message_id),
  foreign key(workspace_id,connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade
);
create index telegram_inbox on public.pr_telegram_messages(workspace_id,connection_id,date desc);
create index telegram_polls on public.pr_telegram_messages(bot_id,poll_id) where poll_id is not null;
create table public.pr_telegram_engagement (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  chat_id bigint not null,
  message_id bigint not null,
  metric text not null,
  value jsonb not null,
  observed_at bigint not null,
  source text not null check(source in ('bot_observed','rafii_derived')),
  primary key(workspace_id,connection_id,chat_id,message_id,metric),
  foreign key(workspace_id,connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade
);
create table public.pr_telegram_business_connections (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  bot_id bigint not null,
  business_connection_id text not null,
  user_id bigint not null,
  identity jsonb not null,
  enabled boolean not null,
  rafii_consented boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key(workspace_id,bot_id,business_connection_id)
);
create table public.pr_telegram_business_inbox (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  bot_id bigint not null,
  business_connection_id text not null,
  chat_id bigint not null,
  message_id bigint not null,
  date bigint not null,
  edit_date bigint,
  message_ciphertext text not null,
  key_id text not null,
  deleted boolean not null default false,
  primary key(workspace_id,bot_id,business_connection_id,chat_id,message_id)
);
create table public.pr_telegram_topics (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  thread_id bigint not null,
  kind text not null check(kind in ('forum','channel_dm')),
  title text,
  closed boolean not null default false,
  observed_at bigint not null,
  primary key(workspace_id,connection_id,thread_id,kind),
  foreign key(workspace_id,connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade
);
create table public.pr_telegram_dm_access (
  workspace_id uuid not null,
  parent_connection_id text not null,
  bot_id bigint not null,
  parent_chat_id bigint not null,
  enabled boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key(workspace_id,parent_connection_id),
  foreign key(workspace_id,parent_connection_id) references public.pr_encrypted_credentials(workspace_id,connection_id) on delete cascade
);
create table public.pr_telegram_dm_inbox (
  workspace_id uuid not null,
  parent_connection_id text not null,
  chat_id bigint not null,
  topic_id bigint not null,
  message_id bigint not null,
  date bigint not null,
  edit_date bigint,
  chat_identity jsonb not null,
  message_ciphertext text not null,
  key_id text not null,
  primary key(workspace_id,parent_connection_id,chat_id,message_id),
  foreign key(workspace_id,parent_connection_id) references public.pr_telegram_dm_access(workspace_id,parent_connection_id) on delete cascade
);
create table public.pr_telegram_files (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  bot_id bigint not null,
  file_id text not null,
  kind text not null,
  descriptor jsonb not null,
  created_at timestamptz not null default now(),
  unique(workspace_id,bot_id,file_id)
);
create table public.pr_telegram_operations (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  id text not null,
  connection_id text not null,
  actor_id uuid not null,
  payload_digest text not null check(length(payload_digest)=64),
  state text not null check(state in ('prepared','started','confirmed','failed','uncertain')),
  api_method text not null,
  payload_ciphertext text not null,
  key_id text not null,
  result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key(workspace_id,id)
);
do $$ declare t text; begin
  foreach t in array array['pr_telegram_destinations','pr_telegram_bot_grants','pr_telegram_updates','pr_telegram_messages','pr_telegram_engagement','pr_telegram_business_connections','pr_telegram_business_inbox','pr_telegram_topics','pr_telegram_dm_access','pr_telegram_dm_inbox','pr_telegram_files','pr_telegram_operations'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
  end loop;
end $$;
commit;
