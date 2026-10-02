-- RAFII Product Growth G2-OUT (PRD R-OUT-01..03): the customer's own business results.
-- Additive and idempotent. These are a workspace's leads, bookings, sign-ups, sales and clicks with one provenance class
-- each (provider_native | first_party_reported | user_declared); they are never Rafii's subscription revenue.
-- Every cross-record reference is a composite (workspace_id, id) foreign key, so a row can never point at another
-- workspace's connection, link or result. Browser roles read their own workspace's rows only and never write.
begin;

-- One signed first-party webhook connection (an approved, user-controlled form/booking/newsletter/store producer).
-- Secrets are stored only encrypted (CredentialVault); removal destroys them. The previous secret stays usable until
-- previous_expires_at (rotation grace).
create table if not exists public.pr_result_connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  label text not null check (char_length(label) between 1 and 80),
  producer text not null check (producer in ('form','booking','newsletter','store','other')),
  status text not null default 'active' check (status in ('active','paused','removed')),
  secret_ciphertext text,
  secret_key_id text,
  secret_fingerprint text check (secret_fingerprint is null or secret_fingerprint ~ '^[0-9a-f]{12}$'),
  previous_ciphertext text,
  previous_key_id text,
  previous_fingerprint text check (previous_fingerprint is null or previous_fingerprint ~ '^[0-9a-f]{12}$'),
  previous_expires_at timestamptz,
  rate_per_minute integer not null default 60 check (rate_per_minute between 1 and 600),
  rate_per_day integer not null default 5000 check (rate_per_day between 1 and 100000),
  last_received_at timestamptz,
  last_event_at timestamptz,
  last_error_code text check (last_error_code is null or last_error_code ~ '^[a-z][a-z0-9_]{0,59}$'),
  last_error_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  removed_at timestamptz,
  revision integer not null default 1 check (revision >= 1),
  unique (workspace_id, id),
  constraint pr_result_connections_secret check (status = 'removed' or (secret_ciphertext is not null and secret_key_id is not null and secret_fingerprint is not null)),
  constraint pr_result_connections_removed check (status <> 'removed' or (secret_ciphertext is null and previous_ciphertext is null and removed_at is not null)),
  constraint pr_result_connections_previous check ((previous_ciphertext is null) = (previous_expires_at is null))
);
create index if not exists pr_result_connections_workspace_idx on public.pr_result_connections (workspace_id, created_at, id);

-- A server-created opaque tracking link: binds workspace, campaign label and one approved public HTTPS destination.
create table if not exists public.pr_tracking_links (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  slug text not null unique check (slug ~ '^[A-Za-z0-9_-]{10,32}$'),
  destination text not null check (char_length(destination) between 12 and 2048 and destination ~ '^https://'),
  campaign_ref text check (campaign_ref is null or campaign_ref ~ '^[A-Za-z0-9_:-]{1,80}$'),
  label text not null check (char_length(label) between 1 and 80),
  status text not null default 'active' check (status in ('active','disabled')),
  association_window_days integer not null default 30 check (association_window_days between 1 and 90),
  definition_version text not null default 'rafii.result-link-association.v1' check (definition_version ~ '^[a-z0-9._-]{1,60}$'),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  disabled_at timestamptz,
  revision integer not null default 1 check (revision >= 1),
  unique (workspace_id, id)
);
create index if not exists pr_tracking_links_workspace_idx on public.pr_tracking_links (workspace_id, created_at, id);

-- Append-only result evidence. Corrections (amendment, reversal) are new rows that point at their original.
create table if not exists public.pr_result_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  provenance text not null check (provenance in ('provider_native','first_party_reported','user_declared')),
  result_type text not null check (result_type in ('click','lead','booking','newsletter_signup','sale')),
  connection_id uuid,
  provider_event_id text not null check (provider_event_id ~ '^[A-Za-z0-9._:-]{1,120}$'),
  kind text not null default 'event' check (kind in ('event','reversal','amendment')),
  corrects_id uuid,
  occurred_at timestamptz not null,
  received_at timestamptz not null default now(),
  amount_minor bigint check (amount_minor is null or amount_minor between 0 and 100000000000),
  currency text check (currency is null or currency ~ '^[a-z]{3}$'),
  quantity integer not null default 1 check (quantity between 1 and 1000),
  link_id uuid,
  campaign_ref text check (campaign_ref is null or campaign_ref ~ '^[A-Za-z0-9_:-]{1,80}$'),
  attribution text not null default 'unattributed' check (attribution in ('associated','unattributed','expired_window','not_this_workspace')),
  attribution_definition text not null default 'rafii.result-link-association.v1' check (attribution_definition ~ '^[a-z0-9._-]{1,60}$'),
  payload_digest text not null check (payload_digest ~ '^[0-9a-f]{64}$'),
  declared_by uuid,
  note text check (note is null or char_length(note) <= 500),
  test boolean not null default false,
  created_at timestamptz not null default now(),
  unique (workspace_id, id),
  constraint pr_result_events_money check ((amount_minor is null) = (currency is null)),
  constraint pr_result_events_money_type check (amount_minor is null or result_type in ('booking','sale')),
  constraint pr_result_events_correction check ((kind = 'event') = (corrects_id is null)),
  constraint pr_result_events_source check ((provenance = 'first_party_reported') = (connection_id is not null)),
  constraint pr_result_events_declared check (provenance <> 'user_declared' or declared_by is not null),
  constraint pr_result_events_note check (note is null or provenance = 'user_declared'),
  constraint pr_result_events_corrects_fk foreign key (workspace_id, corrects_id) references public.pr_result_events (workspace_id, id),
  constraint pr_result_events_connection_fk foreign key (workspace_id, connection_id) references public.pr_result_connections (workspace_id, id),
  constraint pr_result_events_link_fk foreign key (workspace_id, link_id) references public.pr_tracking_links (workspace_id, id)
);
create index if not exists pr_result_events_occurred_idx on public.pr_result_events (workspace_id, occurred_at, id);
create unique index if not exists pr_result_events_first_party_uidx on public.pr_result_events (workspace_id, connection_id, provider_event_id)
  where provenance = 'first_party_reported';
create unique index if not exists pr_result_events_declared_uidx on public.pr_result_events (workspace_id, provider_event_id)
  where provenance = 'user_declared';
create unique index if not exists pr_result_events_one_reversal_uidx on public.pr_result_events (workspace_id, corrects_id)
  where kind = 'reversal';
create index if not exists pr_result_events_corrects_idx on public.pr_result_events (workspace_id, corrects_id, received_at)
  where corrects_id is not null;
create index if not exists pr_result_events_connection_idx on public.pr_result_events (workspace_id, connection_id, received_at)
  where connection_id is not null;
create index if not exists pr_result_events_link_idx on public.pr_result_events (workspace_id, link_id)
  where link_id is not null;

-- Evidence is never rewritten: only a workspace/account deletion (cascade) removes it.
create or replace function postriff_private.pr_result_events_append_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'pr_result_events is append-only; record a correction instead' using errcode = 'restrict_violation';
end $$;
revoke all on function postriff_private.pr_result_events_append_only() from public, anon, authenticated;
do $$
begin
  if not exists (select 1 from pg_trigger where tgrelid = 'public.pr_result_events'::regclass and tgname = 'pr_result_events_append_only') then
    create trigger pr_result_events_append_only before update on public.pr_result_events
      for each row execute function postriff_private.pr_result_events_append_only();
  end if;
end $$;

-- A conflicting payload for an event id that already exists. It never replaces the original.
create table if not exists public.pr_result_quarantine (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id uuid not null,
  provider_event_id text not null check (provider_event_id ~ '^[A-Za-z0-9._:-]{1,120}$'),
  payload_digest text not null check (payload_digest ~ '^[0-9a-f]{64}$'),
  reason text not null check (reason in ('conflicting_payload','reversal_duplicate')),
  existing_id uuid,
  received_at timestamptz not null default now(),
  unique (workspace_id, id),
  unique (workspace_id, connection_id, provider_event_id, payload_digest),
  constraint pr_result_quarantine_connection_fk foreign key (workspace_id, connection_id) references public.pr_result_connections (workspace_id, id),
  constraint pr_result_quarantine_existing_fk foreign key (workspace_id, existing_id) references public.pr_result_events (workspace_id, id)
);
create index if not exists pr_result_quarantine_connection_idx on public.pr_result_quarantine (workspace_id, connection_id, received_at);

-- Daily click aggregate per link. No address, user agent, fingerprint or person identifier is stored.
create table if not exists public.pr_link_clicks (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  link_id uuid not null,
  day date not null,
  clicks integer not null default 0 check (clicks >= 0),
  likely_bot integer not null default 0 check (likely_bot >= 0),
  primary key (link_id, day),
  constraint pr_link_clicks_link_fk foreign key (workspace_id, link_id) references public.pr_tracking_links (workspace_id, id) on delete cascade
);
create index if not exists pr_link_clicks_workspace_idx on public.pr_link_clicks (workspace_id, day);

-- Idempotency for the authenticated mutations: one intent per key; a replay returns the same subject.
create table if not exists public.pr_result_mutations (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  idempotency_key text not null check (idempotency_key ~ '^[A-Za-z0-9_-]{8,80}$'),
  operation text not null check (operation ~ '^[a-z_]{1,40}$'),
  request_digest text not null check (request_digest ~ '^[0-9a-f]{64}$'),
  subject_id uuid,
  created_at timestamptz not null default now(),
  primary key (workspace_id, idempotency_key)
);

do $$
declare t text;
begin
  foreach t in array array['pr_result_connections','pr_tracking_links','pr_result_events','pr_result_quarantine','pr_link_clicks','pr_result_mutations'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = 'trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
  -- Members read their own workspace's results, links and clicks. Connection secrets and the idempotency ledger stay
  -- service-only. The webhook endpoint (a connection's id) is the owner's to know: connections are owner-readable and
  -- members never get the connection_id column of events or quarantine rows.
  foreach t in array array['pr_tracking_links','pr_result_events','pr_result_quarantine','pr_link_clicks'] loop
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = 'tenant_read') then
      execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    end if;
  end loop;
  foreach t in array array['pr_tracking_links','pr_link_clicks'] loop
    execute format('grant select on public.%I to authenticated', t);
  end loop;
end $$;
drop policy if exists tenant_read on public.pr_result_connections;
drop policy if exists owner_read on public.pr_result_connections;
create policy owner_read on public.pr_result_connections for select to authenticated using (
  postriff_private.member(workspace_id) and exists (
    select 1 from public.pr_memberships m
    where m.workspace_id = pr_result_connections.workspace_id and m.user_id = (select auth.uid()) and m.status = 'active' and m.role = 'owner'));
grant select (id, workspace_id, label, producer, status, secret_fingerprint, previous_fingerprint, previous_expires_at,
              rate_per_minute, rate_per_day, last_received_at, last_event_at, last_error_code, last_error_at, created_by,
              created_at, updated_at, removed_at, revision)
  on public.pr_result_connections to authenticated;
grant select (id, workspace_id, provenance, result_type, provider_event_id, kind, corrects_id, occurred_at, received_at,
              amount_minor, currency, quantity, link_id, campaign_ref, attribution, attribution_definition, payload_digest,
              declared_by, note, test, created_at)
  on public.pr_result_events to authenticated;
grant select (id, workspace_id, provider_event_id, payload_digest, reason, existing_id, received_at)
  on public.pr_result_quarantine to authenticated;

commit;
