-- PostRiff hosted migrations 004 → 008 (additive). Generated 2026-09-16T06:43Z from migrations/postriff/*.sql.
-- Apply once, in order, against the Supabase project that already holds 001 + 002. Each file is its own transaction.

-- ===== 004_consumer_web_tenancy.sql =====
-- Additive consumer-web tenancy: five roles, separate action permissions, invitations,
-- audit events, session inventory, and auth throttling. Apply after 001 and 002.
-- Never grants browser writes; tokens and throttle buckets are service_role only.
begin;

-- Roles: owner/admin/editor/approver/viewer. Existing rows are unchanged.
alter table public.pr_memberships drop constraint if exists pr_memberships_role_check;
alter table public.pr_memberships add constraint pr_memberships_role_check
  check (role in ('owner','admin','editor','approver','viewer'));
alter table public.pr_memberships
  add column if not exists can_publish boolean not null default false,
  add column if not exists can_reply boolean not null default false,
  add column if not exists can_moderate boolean not null default false,
  add column if not exists can_manage_connections boolean not null default false,
  add column if not exists invited_by uuid,
  add column if not exists updated_at timestamptz not null default now();
-- Owners hold every action permission by definition.
update public.pr_memberships set can_publish=true, can_reply=true, can_moderate=true, can_manage_connections=true where role='owner';

-- Members may see their teammates (user ids and roles only; profiles stay self-only).
create policy team_membership on public.pr_memberships for select to authenticated using (postriff_private.member(workspace_id));

create table public.pr_invitations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  email text not null check (email = lower(email) and length(email) between 3 and 254 and position('@' in email) > 1),
  role text not null check (role in ('admin','editor','approver','viewer')),
  permissions jsonb not null default '{}' check (jsonb_typeof(permissions)='object'),
  token_hash text not null unique check (length(token_hash)=64),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  accepted_by uuid,
  accepted_at timestamptz,
  revoked_at timestamptz,
  check (expires_at > created_at)
);
create index on public.pr_invitations (workspace_id);
alter table public.pr_invitations enable row level security;
alter table public.pr_invitations force row level security;
revoke all on public.pr_invitations from public, anon, authenticated;
grant all on public.pr_invitations to service_role;
create policy invitations_service_only on public.pr_invitations for all to service_role using (true) with check (true);

-- Append-only, content-free audit trail. Members can read their workspace's rows.
create table public.pr_audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  actor uuid,
  kind text not null check (length(kind) between 3 and 80),
  subject text not null default '' check (length(subject) <= 200),
  at timestamptz not null default now(),
  meta jsonb not null default '{}' check (jsonb_typeof(meta)='object')
);
create index on public.pr_audit_events (workspace_id, at desc);
alter table public.pr_audit_events enable row level security;
alter table public.pr_audit_events force row level security;
revoke all on public.pr_audit_events from public, anon, authenticated;
grant select on public.pr_audit_events to authenticated;
grant insert, select on public.pr_audit_events to service_role;
create policy audit_tenant_read on public.pr_audit_events for select to authenticated using (workspace_id is not null and postriff_private.member(workspace_id));
create policy audit_service_write on public.pr_audit_events for all to service_role using (true) with check (true);
-- No update/delete grant exists for any role: rows are immutable.

-- Session inventory for the device list. Revocation uses pr_session_revocations.
create table public.pr_sessions (
  user_id uuid not null,
  session_id text not null check (length(session_id) between 16 and 160),
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  client_label text not null default '' check (length(client_label) <= 40),
  primary key (user_id, session_id)
);
alter table public.pr_sessions enable row level security;
alter table public.pr_sessions force row level security;
revoke all on public.pr_sessions from public, anon, authenticated;
grant all on public.pr_sessions to service_role;
create policy sessions_service_only on public.pr_sessions for all to service_role using (true) with check (true);

-- Fixed-window throttle buckets keyed by a hashed scope; never stores raw addresses.
create table public.pr_auth_throttle (
  bucket text primary key check (length(bucket)=64),
  window_start timestamptz not null default now(),
  count integer not null default 0 check (count >= 0)
);
alter table public.pr_auth_throttle enable row level security;
alter table public.pr_auth_throttle force row level security;
revoke all on public.pr_auth_throttle from public, anon, authenticated;
grant all on public.pr_auth_throttle to service_role;
create policy throttle_service_only on public.pr_auth_throttle for all to service_role using (true) with check (true);

-- Bootstrap now grants the owner every action permission explicitly.
create or replace function public.pr_bootstrap(p_user uuid, p_plan text) returns uuid language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  if p_plan not in ('studio','assist') then raise exception 'unavailable plan'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_account_tombstones where user_id=p_user) then raise exception 'deleted account'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select workspace_id into wid from public.pr_memberships where user_id=p_user and status='active' limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections)
    values(wid,p_user,'owner','active',true,true,true,true);
  insert into public.pr_trials(user_id,workspace_id,plan) values(p_user,wid,p_plan);
  return wid;
end $$;
revoke all on function public.pr_bootstrap(uuid,text) from public,anon,authenticated;
grant execute on function public.pr_bootstrap(uuid,text) to service_role;

commit;

-- ===== 005_consumer_web_ideas.sql =====
-- Additive Ideas/agent persistence: conversations, messages, attachments, runs, safe events,
-- and global skill/tool release catalogs. Apply after 004. Service_role writes only.
begin;

create table public.pr_conversations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  created_by uuid not null,
  title text not null default '' check (length(title) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
create index on public.pr_conversations (workspace_id, updated_at desc);

create table public.pr_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  seq integer not null check (seq >= 1),
  role text not null check (role in ('user','assistant','system')),
  body jsonb not null check (jsonb_typeof(body)='object'),
  run_id uuid,
  created_at timestamptz not null default now(),
  unique (conversation_id, seq)
);
create index on public.pr_messages (workspace_id, conversation_id, seq);

create table public.pr_attachments (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  kind text not null check (kind in ('source','asset','link')),
  ref jsonb not null check (jsonb_typeof(ref)='object'),
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index on public.pr_attachments (workspace_id, conversation_id);

create table public.pr_agent_runs (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  actor uuid not null,
  status text not null check (status in ('running','completed','failed','cancelled','applied')),
  model text not null,
  reasoning text not null check (reasoning in ('quick','standard','deep')),
  context_digest text not null check (length(context_digest)=64),
  policy_epoch text not null check (length(policy_epoch)=64),
  idempotency_key text not null,
  artifact jsonb,
  artifact_hash text,
  usage jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);
create index on public.pr_agent_runs (workspace_id, conversation_id, created_at desc);

create table public.pr_agent_events (
  run_id uuid not null references public.pr_agent_runs(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  seq integer not null check (seq >= 1),
  kind text not null check (kind in ('run.started','progress.updated','source.added','artifact.created','message.delta','message.completed','warning.created','action.proposed','run.completed','run.failed','run.cancelled')),
  body jsonb not null default '{}' check (jsonb_typeof(body)='object'),
  at timestamptz not null default now(),
  primary key (run_id, seq)
);

-- Global, reviewed catalogs: no customer content, readable by any signed-in member.
create table public.pr_skill_releases (
  id text not null, version text not null, sha256 text not null check (length(sha256)=64),
  state text not null check (state in ('released','deprecated')), released_at timestamptz not null default now(),
  primary key (id, version)
);
create table public.pr_tool_releases (
  id text not null, version text not null, sha256 text not null check (length(sha256)=64),
  effect_class text not null check (effect_class in ('read','creative_write','workspace_mutation','paid_generation')),
  cost_class text not null check (cost_class in ('none','metered','paid')),
  state text not null check (state in ('released','deprecated')), released_at timestamptz not null default now(),
  primary key (id, version)
);

do $$
declare t text;
begin
  foreach t in array array['pr_conversations','pr_messages','pr_attachments','pr_agent_runs','pr_agent_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  foreach t in array array['pr_skill_releases','pr_tool_releases'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy catalog_read on public.%I for select to authenticated using (true)', t);
    execute format('create policy catalog_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;

-- ===== 006_consumer_web_channels.sql =====
-- Additive channel integration persistence: OAuth transactions, encrypted credential custody,
-- and per-capability level records. Apply after 005. Tokens are never browser-readable.
begin;

-- One row per OAuth start. State is stored hashed; PKCE verifier is encrypted at rest.
create table public.pr_oauth_transactions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null,
  provider text not null check (length(provider) between 2 and 40),
  capability text not null check (capability in ('identity','publish','schedule','analytics','comments_read','reply','moderate')),
  redirect_uri text not null check (redirect_uri like 'https://%'),
  scopes text[] not null,
  state_hash text not null unique check (length(state_hash)=64),
  verifier_ciphertext text not null,
  key_id text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  outcome text check (outcome in ('exchanged','denied','expired','mismatch')),
  check (expires_at > created_at)
);
create index on public.pr_oauth_transactions (workspace_id, created_at desc);

-- Encrypted provider tokens bound to a workspace + connection. Application-layer encryption;
-- the key lives in server secrets (POSTRIFF_CREDENTIAL_KEY), never in this table.
create table public.pr_encrypted_credentials (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (length(connection_id) between 8 and 80),
  provider text not null,
  provider_account_id text not null,
  access_ciphertext text not null,
  refresh_ciphertext text,
  key_id text not null,
  scopes text[] not null,
  access_expires_at timestamptz,
  refresh_supported boolean not null default false,
  revoked_at timestamptz,
  rotated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, connection_id)
);

-- Capability levels per connection: Direct / Assisted / Bridge / Unsupported, each with evidence.
create table public.pr_channel_capabilities (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  capability text not null check (capability in ('identity','publish','schedule','analytics','comments_read','reply','moderate','media_types','webhooks')),
  level text not null check (level in ('Direct','Assisted','Bridge','Unsupported')),
  evidence text not null default '' check (length(evidence) <= 400),
  capability_version integer not null default 0,
  verified_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, connection_id, capability)
);

do $$
declare t text;
begin
  foreach t in array array['pr_oauth_transactions','pr_encrypted_credentials'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  alter table public.pr_channel_capabilities enable row level security;
  alter table public.pr_channel_capabilities force row level security;
  revoke all on public.pr_channel_capabilities from public, anon, authenticated;
  grant select on public.pr_channel_capabilities to authenticated;
  grant all on public.pr_channel_capabilities to service_role;
  create policy tenant_read on public.pr_channel_capabilities for select to authenticated using (postriff_private.member(workspace_id));
  create policy trusted_write on public.pr_channel_capabilities for all to service_role using (true) with check (true);
end $$;

commit;

-- ===== 007_consumer_web_billing.sql =====
-- Additive billing/entitlement/usage, privacy requests, analytics observations, audience.
-- Apply after 006. Prices here are PROPOSED decision records, never charged by this code.
begin;

-- Versioned plan terms (decision records). status='proposed' until an explicit commercial decision.
create table public.pr_plan_terms (
  id text primary key,
  plan text not null check (plan in ('trial','studio','assist')),
  version integer not null,
  label text not null,
  price_cents integer not null check (price_cents >= 0),
  currency text not null default 'USD' check (currency in ('USD')),
  status text not null check (status in ('proposed','active','retired')),
  entitlements jsonb not null check (jsonb_typeof(entitlements)='object'),
  source text not null default '',
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (plan, version)
);
insert into public.pr_plan_terms(id,plan,version,label,price_cents,status,entitlements,source) values
 ('trial-v1','trial',1,'14-day trial',0,'proposed','{"members":1,"connectedAccounts":2,"writingBatches":10,"mediaCredits":1,"storageMb":200,"autoConvert":false,"overage":"stop"}','consumer plan product-spec.md:358-360; pr_trials'),
 ('studio-v1','studio',1,'Studio',1900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":0,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','consumer plan pricing-and-economics.md (PROPOSAL, not implemented)'),
 ('assist-v1','assist',1,'Studio Assist',3900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":100,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','consumer plan pricing-and-economics.md (PROPOSAL, not implemented)'),
 ('assist-bounded-v1','assist',2,'Studio Assist (bounded-batch experiment)',3900,'proposed','{"members":1,"connectedAccounts":3,"writingBatches":8,"mediaCredits":0,"storageMb":1000,"overage":"stop"}','improvement DECISIONS.md:15 beta experiment; not an invisible rewrite');

create table public.pr_subscriptions (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  plan_terms_id text not null references public.pr_plan_terms(id),
  provider text not null default 'fixture',
  provider_customer_id text,
  provider_subscription_id text,
  status text not null check (status in ('trial','active','past_due','grace','cancelled','expired')),
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  grace_until timestamptz,
  last_event_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.pr_entitlements (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  plan_terms_id text not null references public.pr_plan_terms(id),
  writing_batches_remaining integer not null check (writing_batches_remaining >= 0),
  media_credits_remaining integer not null check (media_credits_remaining >= 0),
  connected_accounts integer not null,
  members integer not null,
  storage_mb integer not null,
  resets_at timestamptz,
  source text not null check (source in ('trial','subscription','manual')),
  version integer not null default 1,
  updated_at timestamptz not null default now()
);

-- Append-only, idempotent usage/cost ledger. No update/delete grants exist for any role.
create table public.pr_usage_ledger (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid,
  run_id uuid,
  job_id text,
  reservation_id uuid,
  kind text not null check (kind in ('reserve','settle','release','adjust')),
  dimension text not null check (dimension in ('text_model','image_generation','tool','storage','action')),
  provider text not null default '',
  model text not null default '',
  quantity numeric not null default 1,
  unit text not null default 'request',
  estimated_usd_micro bigint not null default 0 check (estimated_usd_micro >= 0),
  actual_usd_micro bigint check (actual_usd_micro >= 0),
  cost_state text not null check (cost_state in ('estimated','actual','estimated_unknown','released')),
  charge_batch boolean not null default false,
  idempotency_key text not null,
  meta jsonb not null default '{}' check (jsonb_typeof(meta)='object'),
  at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);
create index on public.pr_usage_ledger (workspace_id, at desc);

-- Budget rows are the lock points for reserve/settle. Candidate ceilings, flagged as such.
create table public.pr_budgets (
  scope text primary key,
  window_kind text not null check (window_kind in ('day','month')),
  window_start timestamptz not null default date_trunc('day', now()),
  warn_usd_micro bigint not null,
  stop_usd_micro bigint not null,
  spent_usd_micro bigint not null default 0 check (spent_usd_micro >= 0),
  reserved_usd_micro bigint not null default 0 check (reserved_usd_micro >= 0),
  status text not null default 'candidate' check (status in ('candidate','approved')),
  updated_at timestamptz not null default now()
);

-- Billing webhook events: signature-verified by the adapter, unique per provider event id.
create table public.pr_billing_events (
  provider text not null,
  event_id text not null,
  kind text not null,
  event_at timestamptz not null,
  payload_digest text not null check (length(payload_digest)=64),
  outcome text not null check (outcome in ('applied','duplicate','stale','ignored','rejected')),
  processed_at timestamptz not null default now(),
  primary key (provider, event_id)
);

-- Customer data requests with receipts (export, deletion, diagnostics-by-consent).
create table public.pr_data_requests (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete set null,
  requested_by uuid not null,
  kind text not null check (kind in ('export','deletion','diagnostics','retraction')),
  status text not null check (status in ('requested','completed','failed')),
  receipt jsonb not null default '{}' check (jsonb_typeof(receipt)='object'),
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);
create index on public.pr_data_requests (workspace_id, requested_at desc);

-- Native metric definitions (global) and per-post observations (tenant). Missing is 'unavailable', never 0.
create table public.pr_metric_definitions (
  provider text not null, metric text not null, native_name text not null, definition_version text not null,
  unit text not null, scope text not null, definition_url text not null default '',
  primary key (provider, metric, definition_version)
);
insert into public.pr_metric_definitions values
 ('threads','views','views','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','likes','likes','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','replies','replies','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','reposts','reposts','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','quotes','quotes','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('threads','shares','shares','2026-09','count','post','https://developers.facebook.com/docs/threads/insights'),
 ('instagram','reach','reach','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','views','views','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','likes','likes','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','comments','comments','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','saved','saved','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights'),
 ('instagram','shares','shares','2026-09','count','post','https://developers.facebook.com/docs/instagram-platform/insights');

create table public.pr_metric_observations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  provider text not null,
  provider_post_id text not null,
  job_id text,
  metric text not null,
  definition_version text not null,
  value numeric,
  unit text not null,
  availability text not null check (availability in ('available','unavailable','suppressed','not_supported')),
  observed_at timestamptz not null,
  period_start timestamptz,
  period_end timestamptz,
  ingested_at timestamptz not null default now(),
  source_endpoint text not null default '',
  check ((availability='available' and value is not null) or (availability<>'available' and value is null))
);
create index on public.pr_metric_observations (workspace_id, provider_post_id, metric, observed_at desc);

-- Audience: original thread context + reply drafts with exact approval and separate send/verify receipts.
create table public.pr_audience_threads (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  provider text not null,
  provider_post_id text not null,
  provider_comment_id text not null,
  author_handle text not null default '',
  text text not null,
  created_at_provider timestamptz,
  ingested_at timestamptz not null default now(),
  tombstoned_at timestamptz,
  unique (workspace_id, provider, provider_comment_id)
);
create table public.pr_reply_drafts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  thread_id uuid not null references public.pr_audience_threads(id) on delete cascade,
  author uuid not null,
  origin text not null check (origin in ('manual','ai_fixture')),
  text text not null,
  status text not null check (status in ('draft','approved','submitting','submitted','verified','failed','uncertain','cancelled')),
  approval jsonb,
  provider_reference text,
  events jsonb not null default '[]',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
declare t text;
begin
  foreach t in array array['pr_subscriptions','pr_entitlements','pr_data_requests','pr_metric_observations','pr_audience_threads','pr_reply_drafts'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  -- Ledger: tenant read; service_role may only insert and select (immutable rows).
  alter table public.pr_usage_ledger enable row level security;
  alter table public.pr_usage_ledger force row level security;
  revoke all on public.pr_usage_ledger from public, anon, authenticated, service_role;
  grant select on public.pr_usage_ledger to authenticated;
  grant select, insert on public.pr_usage_ledger to service_role;
  create policy ledger_tenant_read on public.pr_usage_ledger for select to authenticated using (postriff_private.member(workspace_id));
  create policy ledger_service_insert on public.pr_usage_ledger for insert to service_role with check (true);
  create policy ledger_service_read on public.pr_usage_ledger for select to service_role using (true);
  foreach t in array array['pr_budgets','pr_billing_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  foreach t in array array['pr_plan_terms','pr_metric_definitions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy catalog_read on public.%I for select to authenticated using (true)', t);
    execute format('create policy catalog_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;

-- ===== 008_billing_provider_notifications.sql =====
-- Additive: provider price binding for plan terms + server-only notification ledger.
-- Apply after 007. Adds no PII columns; user emails are fetched from Supabase Auth at send time.
begin;

-- Live provider price id (e.g. Stripe price_…). Set together with status='active' by an explicit
-- commercial decision in SQL; checkout refuses any row whose status is not 'active'.
alter table public.pr_plan_terms add column if not exists provider_price_id text;

-- One row per (workspace, kind, dedupe_key): welcome, trial-ending, trial-ended, payment-failed,
-- subscription-activated. `sent` records the transport outcome; meta never holds addresses or bodies.
create table public.pr_notifications (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid,
  kind text not null,
  dedupe_key text not null unique,
  sent boolean not null default false,
  meta jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index on public.pr_notifications (workspace_id, created_at desc);

-- Server-only, mirroring 007's treatment of pr_budgets / pr_billing_events.
do $$
declare t text;
begin
  foreach t in array array['pr_notifications'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;
