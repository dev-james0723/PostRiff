-- Rafii notification core (adaptive coworker spec §14-§18; architecture lock N1-N5, E1-E2).
-- Forward-only and idempotent. Rollback = RAFII_NOTIFICATIONS_V2_ENABLED / RAFII_WEB_PUSH_ENABLED off (the tables
-- stay empty); dropping them needs a new forward migration and an owner decision. 008's pr_notifications stays
-- the legacy email ledger, untouched.
-- User ids are bare uuids (no FK to pr_profiles; the 018 FK already blocks account deletion) and are removed by
-- account_deletion explicitly. No address, draft body, DM or secret is stored in any column here.
begin;

-- One row per domain event. scope_key is the workspace id, or 'user:<uuid>' for person-level events
-- (security.*) that belong to no workspace. (scope_key, dedupe_key) makes a replayed event a no-op.
create table if not exists public.pr_notification_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  scope_key text not null check (length(scope_key) between 1 and 80),
  event_type text not null check (event_type ~ '^[a-z_]+\.[a-z_]+$' and length(event_type) <= 80),
  category text not null check (length(category) between 1 and 40),
  entity_type text check (entity_type is null or length(entity_type) <= 40),
  entity_id text check (entity_id is null or length(entity_id) <= 200),
  severity text not null check (severity in ('info','action','warning','critical','security')),
  actor uuid,
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object'),
  dedupe_key text not null check (length(dedupe_key) between 1 and 300),
  grouping_key text check (grouping_key is null or length(grouping_key) <= 200),
  correlation_id text check (correlation_id is null or length(correlation_id) <= 80),
  occurred_at timestamptz not null default now(),
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  unique (scope_key, dedupe_key)
);
create index if not exists pr_notification_events_workspace on public.pr_notification_events (workspace_id, occurred_at desc);

-- One row per (event, person, channel): the durable queue. A claimed row carries a lease; a completion is
-- fenced on (id, lease_owner). Terminal: sent/delivered/read/acted/dismissed (outcome), failed/dead (after bounded
-- retries), suppressed (preference, quiet mute, unsubscribe, unconfigured transport), cancelled, digested.
create table if not exists public.pr_notification_deliveries (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.pr_notification_events(id) on delete cascade,
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null,
  channel text not null check (channel in ('in_app','email','push')),
  mode text not null check (mode in ('immediate','digest','in_app')),
  status text not null default 'pending' check (status in ('pending','claimed','sent','delivered','read','acted','dismissed','failed','dead','suppressed','cancelled','digested')),
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 6 check (max_attempts between 1 and 20),
  next_attempt_at timestamptz not null default now(),
  lease_owner text,
  lease_until timestamptz,
  idempotency_key text not null unique check (length(idempotency_key) between 8 and 120),
  provider text check (provider is null or length(provider) <= 40),
  provider_ref text check (provider_ref is null or length(provider_ref) <= 200),
  template_version text check (template_version is null or length(template_version) <= 40),
  failure_class text check (failure_class is null or failure_class in ('transient','permanent','config','uncertain','preference','membership','expired')),
  failure_detail text check (failure_detail is null or length(failure_detail) <= 300),
  digest_id uuid,
  sent_at timestamptz, delivered_at timestamptz, read_at timestamptz, acted_at timestamptz, dismissed_at timestamptz, failed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (event_id, user_id, channel)
);
create index if not exists pr_notification_deliveries_due on public.pr_notification_deliveries (next_attempt_at) where status in ('pending','claimed');
create index if not exists pr_notification_deliveries_center on public.pr_notification_deliveries (user_id, created_at desc) where channel = 'in_app';
create index if not exists pr_notification_deliveries_provider on public.pr_notification_deliveries (provider, provider_ref) where provider_ref is not null;

-- Preferences per person: scope_key '*' = the person's defaults, or a workspace id; category '*' = every
-- category. Missing rows fall back to the catalogue's deterministic defaults.
create table if not exists public.pr_notification_preferences (
  user_id uuid not null,
  scope_key text not null check (length(scope_key) between 1 and 80),
  category text not null check (length(category) between 1 and 40),
  in_app boolean,                         -- null = not set here (a broader row or the default decides)
  email_mode text check (email_mode is null or email_mode in ('immediate','digest','off')),
  push_mode text check (push_mode is null or push_mode in ('immediate','off')),
  digest_frequency text check (digest_frequency is null or digest_frequency in ('daily','weekly','off')),
  quiet_start smallint check (quiet_start is null or quiet_start between 0 and 1439),
  quiet_end smallint check (quiet_end is null or quiet_end between 0 and 1439),
  time_zone text check (time_zone is null or length(time_zone) <= 64),
  muted_until timestamptz,
  email_unsubscribed boolean,             -- null = not set here; false re-subscribes this scope explicitly
  updated_at timestamptz not null default now(),
  primary key (user_id, scope_key, category)
);

-- Explicit opt-in Web Push. The endpoint is a capability URL: stored only encrypted (CredentialVault, key_id), with
-- its sha256 for uniqueness. 404/410 from the push service revokes the row.
create table if not exists public.pr_push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  endpoint_sha256 text not null unique check (endpoint_sha256 ~ '^[0-9a-f]{64}$'),
  endpoint_ciphertext text not null,
  p256dh_ciphertext text not null,
  auth_ciphertext text not null,
  key_id text not null check (length(key_id) <= 80),
  client_label text check (client_label is null or length(client_label) <= 60),
  expiration_time timestamptz,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  last_success_at timestamptz,
  failure_count integer not null default 0 check (failure_count >= 0),
  revoked_at timestamptz,
  revoked_reason text check (revoked_reason is null or length(revoked_reason) <= 80)
);
create index if not exists pr_push_subscriptions_user on public.pr_push_subscriptions (user_id) where revoked_at is null;

-- Email/push provider webhooks: (provider, event_id) makes a replay a duplicate, like pr_billing_events but
-- separate so billing health signals stay accurate.
create table if not exists public.pr_notification_provider_events (
  provider text not null check (length(provider) <= 40),
  event_id text not null check (length(event_id) between 1 and 200),
  delivery_id uuid,
  kind text not null check (length(kind) <= 60),
  event_at timestamptz,
  payload_digest text not null check (payload_digest ~ '^[0-9a-f]{64}$'),
  outcome text not null check (outcome in ('applied','duplicate','ignored','rejected','unmatched')),
  received_at timestamptz not null default now(),
  primary key (provider, event_id)
);

-- The detector's watermark: a workspace whose revision has not moved since the last scan is skipped.
create table if not exists public.pr_notification_scan (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  revision bigint not null,
  scanned_at timestamptz not null default now()
);

do $$
declare t text;
begin
  -- Server-only tables (the API filters by workspace and person itself; browsers never read them).
  foreach t in array array['pr_notification_events','pr_push_subscriptions','pr_notification_provider_events','pr_notification_scan'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
  -- Own rows only: a member sees their own deliveries (inside workspaces they still belong to) and their own preferences.
  foreach t in array array['pr_notification_deliveries','pr_notification_preferences'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_notification_deliveries' and policyname='own_read') then
    create policy own_read on public.pr_notification_deliveries for select to authenticated
      using (user_id = (select auth.uid()) and (workspace_id is null or postriff_private.member(workspace_id)));
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_notification_preferences' and policyname='own_read') then
    create policy own_read on public.pr_notification_preferences for select to authenticated using (user_id = (select auth.uid()));
  end if;
end $$;

commit;
