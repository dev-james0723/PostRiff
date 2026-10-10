-- Rafii agent permissions (rafii-agent-authz/1, contract CF-2). PROPOSED DDL, docs copy only: this file is not in the
-- runner's sequence. Lane J creates migrations/postriff/107_agent_permissions.sql byte-identical to it (a test enforces
-- that). Once either copy has been applied anywhere (staging, a shared disposable database or production), the runner's
-- checksum ledger forbids editing it: every later change is a new forward migration (109+).
--
-- Additive only. NO BACKFILL: a member without a pr_agent_permission_state row resolves in code to LEGACY_BASELINE_V1,
-- which is exactly today's behaviour; nothing in this file grants anything. Service-role only (the 102/105 pattern);
-- browsers read through /api/workspaces/{id}/agent/permissions. pr_agent_approvals is NOT created here: one approvals
-- table lives in 108 (amendment X1).
--
-- History is append-only for the server: receipts are insert/select only, grants only ever gain revoked_* values, and
-- state rows are never deleted by the server. Ending a membership is an UPDATE (pr_memberships.status='revoked'), which
-- leaves every row here in place (ended_at marks it). The only delete path is postriff_private.agent_permissions_erase,
-- callable during account deletion only. The state row references the membership ON DELETE RESTRICT, and grants and
-- autopilot policies reference the state row ON DELETE RESTRICT, so no foreign-key cascade can silently erase history.
--
-- Rollback: turn the RAFII_AGENT_PERMISSIONS_* flags off; the tables stay (no destructive downgrade).
begin;

-- Account-deletion erase function and the guard trigger below live in postriff_private (already used by 001/105).
grant usage on schema postriff_private to service_role;

-- One row per person and workspace once that person has made a choice. No row = legacy (today's behaviour).
create table if not exists public.pr_agent_permission_state (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null,
  epoch bigint not null check (epoch >= 1),                                  -- bumped on every change; missing row = 0
  preset text not null check (preset in ('none','recommended','full','custom')),
  preset_version integer not null check (preset_version >= 1),
  baseline text check (baseline is null or baseline = 'legacy_v1'),          -- 'legacy_v1': still limited to LEGACY_BASELINE_V1
  spend_confirmation text not null check (spend_confirmation in ('none','media','all')),
  consent_version text not null check (consent_version ~ '^agent-permissions/[1-9][0-9]{0,3}$'),
  copy_digest text not null check (copy_digest ~ '^[0-9a-f]{64}$'),
  catalogue_generation integer not null check (catalogue_generation >= 1),
  catalogue_digest text not null check (catalogue_digest ~ '^[0-9a-f]{64}$'),
  decided_by uuid not null,
  decided_at timestamptz not null default now(),
  step_up_at timestamptz,                                                    -- verified sign-in time behind the last step-up change
  ended_at timestamptz,                                                      -- membership ended: load() treats the row as no choice
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id),
  constraint pr_agent_permission_state_member foreign key (workspace_id, user_id)
    references public.pr_memberships(workspace_id, user_id) on delete restrict,
  constraint pr_agent_permission_state_ended check (ended_at is null or (preset = 'none' and baseline is null)),
  constraint pr_agent_permission_state_full_step_up check (preset <> 'full' or step_up_at is not null)
);

-- Every change a person (or a cascade) makes is one receipt, written before the grant rows it explains.
create table if not exists public.pr_agent_consent_receipts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid,                                    -- whose permissions; null only for a workspace-wide consent narrowing
  actor uuid not null,                             -- who acted: the person, the remover, or the owner for a cascade
  kind text not null check (kind in ('preset_applied','custom_changed','revoked','revoked_all','autopilot_enabled',
                                     'autopilot_revoked','autopilot_expired','membership_ended','workspace_consent_narrowed')),
  source text not null check (source in ('onboarding','settings','reminder','chat_link','system')),   -- never GenUI (PI-7)
  epoch_before bigint not null check (epoch_before >= 0),
  epoch_after bigint not null check (epoch_after >= epoch_before),
  preset_before text check (preset_before is null or preset_before in ('legacy','none','recommended','full','custom')),
  preset_after text check (preset_after is null or preset_after in ('legacy','none','recommended','full','custom')),
  scopes_before jsonb not null check (jsonb_typeof(scopes_before) = 'object'),
  scopes_after jsonb not null check (jsonb_typeof(scopes_after) = 'object'),
  widened boolean not null,                        -- computed by a decide() diff over the public catalogue (correction 5)
  consent_version text not null check (consent_version ~ '^agent-permissions/[1-9][0-9]{0,3}$'),
  copy_digest text check (copy_digest is null or copy_digest ~ '^[0-9a-f]{64}$'),
  catalogue_digest text not null check (catalogue_digest ~ '^[0-9a-f]{64}$'),
  step_up jsonb not null default '{}' check (jsonb_typeof(step_up) = 'object'),            -- {method, at, aal}; never a credential
  invalidated jsonb not null default '{}' check (jsonb_typeof(invalidated) = 'object'),    -- {handlerName: count}
  not_recallable jsonb not null default '[]' check (jsonb_typeof(not_recallable) = 'array'),
  idempotency_key text not null check (length(idempotency_key) between 16 and 120),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),      -- same key + other body = 409
  created_at timestamptz not null default now(),
  constraint pr_agent_consent_receipts_id_workspace unique (id, workspace_id),
  constraint pr_agent_consent_receipts_subject check (user_id is not null or kind = 'workspace_consent_narrowed'),
  constraint pr_agent_consent_receipts_widening check (not widened or kind in ('preset_applied','custom_changed','autopilot_enabled')),
  constraint pr_agent_consent_receipts_full_step_up check (preset_after is distinct from 'full' or not widened or step_up ? 'at')
);
create unique index if not exists pr_agent_consent_receipts_key on public.pr_agent_consent_receipts (workspace_id, actor, idempotency_key);
create index if not exists pr_agent_consent_receipts_feed on public.pr_agent_consent_receipts (workspace_id, user_id, created_at desc);

-- One row per granted scope; a change revokes the old row and inserts a new one in the same transaction.
create table if not exists public.pr_agent_grants (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null,
  scope text not null check (scope ~ '^(category:(read_analyze|navigate_interact|create_edit|manage_settings|manage_connected_services|execute_automations)|domain:[a-z_]{2,32}|capability:[a-z][a-z0-9_.]{1,95})$'),
  mode text,
  granted_epoch bigint not null check (granted_epoch >= 1),
  granted_by uuid not null,
  granted_at timestamptz not null default now(),
  receipt_id uuid not null,
  revoked_epoch bigint,
  revoked_by uuid,
  revoked_at timestamptz,
  revoke_reason text check (revoke_reason is null or revoke_reason in ('changed','revoked','revoked_all','membership_ended','system')),
  constraint pr_agent_grants_mode check ((scope like 'category:%' and mode in ('ask','assist'))
                                      or (scope like 'domain:%' and mode is null)
                                      or (scope like 'capability:%' and mode in ('off','ask','assist'))),
  constraint pr_agent_grants_revoked check ((revoked_at is null) = (revoked_epoch is null)
                                         and (revoked_at is null) = (revoked_by is null)
                                         and (revoked_at is null) = (revoke_reason is null)),
  constraint pr_agent_grants_epochs check (revoked_epoch is null or revoked_epoch >= granted_epoch),
  constraint pr_agent_grants_state foreign key (workspace_id, user_id)
    references public.pr_agent_permission_state(workspace_id, user_id) on delete restrict,
  constraint pr_agent_grants_receipt foreign key (receipt_id, workspace_id)
    references public.pr_agent_consent_receipts(id, workspace_id)
);
create unique index if not exists pr_agent_grants_active on public.pr_agent_grants (workspace_id, user_id, scope) where revoked_at is null;
create index if not exists pr_agent_grants_history on public.pr_agent_grants (workspace_id, user_id, granted_at desc);

-- Workspace-level epoch (bumped when an owner narrows a workspace consent) and an optional category ceiling.
-- The ceiling has no API in P0 (DP-22); decide() already honours it when present.
create table if not exists public.pr_agent_workspace_policy (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  epoch bigint not null default 1 check (epoch >= 1),
  ceiling jsonb check (ceiling is null or jsonb_typeof(ceiling) = 'object'),   -- {category: 'off'|'ask'|'assist'}
  updated_by uuid,
  updated_at timestamptz not null default now()
);

-- Bounded autopilot (shape frozen now, used only by the P2 runner behind its own flag; no rows in P0).
create table if not exists public.pr_agent_autopilot_policies (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  user_id uuid not null,
  capability_ids text[] not null check (cardinality(capability_ids) between 1 and 20),
  constraints jsonb not null check (jsonb_typeof(constraints) = 'object'),    -- {connectionIds, campaignIds, platforms, window}
  limits jsonb not null check (jsonb_typeof(limits) = 'object'),              -- {actionsPerDay 1..50, usdMicroPerDay, actionsTotal}
  usage jsonb not null default '{}' check (jsonb_typeof(usage) = 'object'),
  created_epoch bigint not null check (created_epoch >= 1),
  receipt_id uuid not null,
  step_up_at timestamptz not null,
  starts_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  revoked_epoch bigint,
  revoke_reason text check (revoke_reason is null or revoke_reason in ('revoked','expired','permission_changed','limit','membership_ended','system')),
  constraint pr_agent_autopilot_window check (expires_at > starts_at and expires_at <= starts_at + interval '30 days'),
  constraint pr_agent_autopilot_revoked check ((revoked_at is null) = (revoke_reason is null)),
  constraint pr_agent_autopilot_state foreign key (workspace_id, user_id)
    references public.pr_agent_permission_state(workspace_id, user_id) on delete restrict,
  constraint pr_agent_autopilot_receipt foreign key (receipt_id, workspace_id)
    references public.pr_agent_consent_receipts(id, workspace_id)
);
create index if not exists pr_agent_autopilot_active on public.pr_agent_autopilot_policies (workspace_id, user_id, expires_at) where revoked_at is null;

-- Reminder cadence for people still on the legacy baseline ("Not now", existing members). Not consent: it never grants or
-- narrows anything, so it is not history and follows the membership row away.
create table if not exists public.pr_agent_permission_reminders (
  workspace_id uuid not null,
  user_id uuid not null,
  last_prompted_at timestamptz not null,
  last_response text check (last_response is null or last_response in ('not_now','dismissed')),
  prompts integer not null default 1 check (prompts >= 1),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id),
  constraint pr_agent_permission_reminders_member foreign key (workspace_id, user_id)
    references public.pr_memberships(workspace_id, user_id) on delete cascade
);

-- A revoked grant stays revoked: its revoked_* values can be written once and never changed or cleared.
create or replace function postriff_private.agent_grant_revocation_once()
returns trigger language plpgsql set search_path='' as $body$
begin
  if old.revoked_at is not null then
    raise exception 'agent permission grants are append-only once revoked' using errcode = '55000';
  end if;
  return new;
end $body$;
revoke all on function postriff_private.agent_grant_revocation_once() from public, anon, authenticated;
grant execute on function postriff_private.agent_grant_revocation_once() to service_role;
drop trigger if exists pr_agent_grants_revocation_once on public.pr_agent_grants;
create trigger pr_agent_grants_revocation_once before update on public.pr_agent_grants
  for each row execute function postriff_private.agent_grant_revocation_once();

-- Account deletion only: removes this workspace's agent permission history, children first, inside the deletion
-- transaction, before the membership rows go (account_deletion.py deletes pr_memberships, then pr_workspaces).
create or replace function postriff_private.agent_permissions_erase(wid uuid)
returns integer language plpgsql security definer set search_path='' as $erase$
declare removed integer := 0; n integer;
begin
  if wid is null then return 0; end if;
  perform 1 from public.pr_workspaces where id = wid and state ? 'accountDeletion' for update;
  if not found then
    raise exception 'agent permission history is erased only during account deletion' using errcode = '55000';
  end if;
  delete from public.pr_agent_autopilot_policies where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  delete from public.pr_agent_grants where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  delete from public.pr_agent_permission_state where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  delete from public.pr_agent_consent_receipts where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  delete from public.pr_agent_permission_reminders where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  delete from public.pr_agent_workspace_policy where workspace_id = wid; get diagnostics n = row_count; removed := removed + n;
  return removed;
end $erase$;
revoke all on function postriff_private.agent_permissions_erase(uuid) from public, anon, authenticated;
grant execute on function postriff_private.agent_permissions_erase(uuid) to service_role;

-- Service-only: forced RLS, no browser role, and explicit per-table server privileges (no table-wide grant all).
do $$
declare t text;
begin
  foreach t in array array['pr_agent_permission_state','pr_agent_consent_receipts','pr_agent_grants','pr_agent_workspace_policy',
                           'pr_agent_autopilot_policies','pr_agent_permission_reminders'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated, service_role', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;
grant select, insert, update on public.pr_agent_permission_state to service_role;
grant select, insert on public.pr_agent_consent_receipts to service_role;
grant select, insert, update (revoked_epoch, revoked_by, revoked_at, revoke_reason) on public.pr_agent_grants to service_role;
grant select, insert, update on public.pr_agent_workspace_policy to service_role;
grant select, insert, update (usage, revoked_at, revoked_epoch, revoke_reason) on public.pr_agent_autopilot_policies to service_role;
grant select, insert, update, delete on public.pr_agent_permission_reminders to service_role;

commit;
