-- Rafii Generative UI (rafii-genui/1): persisted presentation artifacts attached to existing agent runs.
--
-- Additive only. Business state, approvals, memory and credits stay in their existing tables; these rows hold the
-- presentation (canonical OpenUI source per revision), the producer lease/attempt with its usage, the private replay
-- events, and the durable idempotency/activation records of guarded UI actions. Raw source is private conversation
-- content: service-role only (the 031/093 pattern), never in pr_agent_events (SAFE_EVENTS) or pr_agent_runs.artifact.
-- Old readers ignore these tables; rollback of the application leaves them in place (no destructive downgrade).
begin;

create table if not exists public.pr_ui_artifacts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  scope text not null default 'workspace' check (scope in ('workspace','founder')),
  scope_key text not null default '' check (length(scope_key) <= 120),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  parent_run_id uuid not null references public.pr_agent_runs(id) on delete cascade,
  message_id uuid references public.pr_messages(id) on delete set null,
  slot text not null default 'main' check (slot in ('main')),
  actor uuid not null,
  surface text not null check (surface in ('chat','panel','expanded','mobile','browser_voice','founder')),
  journey_ids text[] not null default '{}',
  revision integer not null default 0 check (revision >= 0),
  source_hash text check (source_hash is null or length(source_hash) = 64),
  generation_state text not null default 'queued'
    check (generation_state in ('queued','streaming','validating','ready','failed','canceled','interrupted')),
  validation_state text not null default 'pending' check (validation_state in ('pending','accepted','rejected')),
  current_attempt_id uuid,
  reason text check (reason is null or length(reason) <= 64),
  contract_version text not null default 'rafii-genui/1',
  language_version text not null default '',
  library_version text not null default '',
  library_hash text not null default '',
  prompt_hash text not null default '',
  manifest jsonb not null default '{}' check (jsonb_typeof(manifest) = 'object'),
  manifest_id text not null default '',
  binding_version integer not null default 1 check (binding_version >= 1),
  fallback_text text not null default '' check (length(fallback_text) <= 12000),
  safe_state jsonb not null default '{}' check (jsonb_typeof(safe_state) = 'object' and octet_length(safe_state::text) <= 16384),
  state_revision integer not null default 0 check (state_revision >= 0),
  next_seq integer not null default 1 check (next_seq >= 1),
  as_of timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, parent_run_id, slot)
);
create index if not exists pr_ui_artifacts_conversation on public.pr_ui_artifacts (workspace_id, conversation_id, created_at desc);
create index if not exists pr_ui_artifacts_message on public.pr_ui_artifacts (message_id) where message_id is not null;

-- One immutable row per ready revision. The previous ready revision stays the recoverable view.
create table if not exists public.pr_ui_revisions (
  artifact_id uuid not null references public.pr_ui_artifacts(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  revision integer not null check (revision >= 1),
  kind text not null check (kind in ('generate','repair','edit')),
  attempt_id uuid,
  base_revision integer check (base_revision is null or base_revision >= 1),
  source text not null check (octet_length(source) <= 131072),
  source_hash text not null check (length(source_hash) = 64),
  validation jsonb not null default '{}' check (jsonb_typeof(validation) = 'object'),
  library_version text not null default '',
  library_hash text not null default '',
  prompt_hash text not null default '',
  created_at timestamptz not null default now(),
  primary key (artifact_id, revision)
);

-- One physical generation attempt (initial, its single automatic repair, an explicit edit or an explicit retry) with its
-- producer lease, durable checkpoint and settled usage. The partial unique index enforces one live producer per
-- (artifact, target revision) across processes.
create table if not exists public.pr_ui_attempts (
  id uuid primary key default gen_random_uuid(),
  artifact_id uuid not null references public.pr_ui_artifacts(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  kind text not null check (kind in ('generate','repair','edit','retry')),
  target_revision integer not null check (target_revision >= 1),
  base_revision integer check (base_revision is null or base_revision >= 1),
  base_source_hash text check (base_source_hash is null or length(base_source_hash) = 64),
  state text not null default 'queued'
    check (state in ('queued','streaming','validating','ready','failed','canceled','interrupted')),
  reason text check (reason is null or length(reason) <= 64),
  idempotency_key text not null check (length(idempotency_key) between 16 and 120),
  retry_of uuid,
  instruction text check (instruction is null or length(instruction) <= 2000),
  lease_owner text not null check (length(lease_owner) <= 80),
  lease_expires_at timestamptz not null,
  reservation_id text,
  provider_attempts integer not null default 0 check (provider_attempts between 0 and 2),
  usage jsonb not null default '{}' check (jsonb_typeof(usage) = 'object'),
  cost_usd_micro bigint check (cost_usd_micro is null or cost_usd_micro >= 0),
  cost_state text not null default 'none' check (cost_state in ('none','known','unknown','estimated')),
  checkpoint_source text not null default '' check (octet_length(checkpoint_source) <= 131072),
  checkpoint_hash text check (checkpoint_hash is null or length(checkpoint_hash) = 64),
  checkpoint_bytes integer not null default 0 check (checkpoint_bytes >= 0),
  admitted_at timestamptz not null default now(),
  first_delta_at timestamptz,
  ready_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);
create unique index if not exists pr_ui_attempts_one_producer
  on public.pr_ui_attempts (artifact_id, target_revision)
  where state in ('queued','streaming','validating');
create index if not exists pr_ui_attempts_lease on public.pr_ui_attempts (lease_expires_at)
  where state in ('queued','streaming','validating');

-- Private replay log of one artifact (monotonic seq). Deltas are source text: same privacy as the conversation.
create table if not exists public.pr_ui_events (
  artifact_id uuid not null references public.pr_ui_artifacts(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  seq integer not null check (seq >= 1),
  attempt_id uuid,
  revision integer not null check (revision >= 0),
  kind text not null check (kind in ('ui.started','ui.delta','ui.checkpoint','ui.ready','ui.failed','ui.canceled','ui.interrupted',
                                     'ui.state_changed','ui.binding_changed','ui.heartbeat')),
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) <= 40000),
  at timestamptz not null default now(),
  primary key (artifact_id, seq)
);

-- Durable idempotency + receipt of a guarded UI action: same key and digest replays the stored result; same key with a
-- different digest is a conflict. Written in the same transaction as the domain command.
create table if not exists public.pr_ui_actions (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 16 and 120),
  principal uuid not null,
  artifact_id uuid not null references public.pr_ui_artifacts(id) on delete cascade,
  artifact_revision integer not null check (artifact_revision >= 0),
  action_id text not null check (length(action_id) <= 64),
  input_digest text not null check (length(input_digest) = 64),
  activation_id text,
  state text not null default 'pending' check (state in ('pending','done')),
  outcome jsonb check (outcome is null or jsonb_typeof(outcome) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, idempotency_key)
);
create index if not exists pr_ui_actions_artifact on public.pr_ui_actions (artifact_id, created_at desc);

-- One-use, 60-second activation bound to principal, artifact revision, action, binding version and exact input digest.
create table if not exists public.pr_ui_activations (
  id text primary key check (id like 'act\_%' and length(id) <= 80),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  principal uuid not null,
  artifact_id uuid not null references public.pr_ui_artifacts(id) on delete cascade,
  artifact_revision integer not null check (artifact_revision >= 0),
  action_id text not null check (length(action_id) <= 64),
  input_digest text not null check (length(input_digest) = 64),
  binding_version integer not null check (binding_version >= 1),
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists pr_ui_activations_artifact on public.pr_ui_activations (workspace_id, artifact_id);

do $$
declare t text;
begin
  foreach t in array array['pr_ui_artifacts','pr_ui_revisions','pr_ui_attempts','pr_ui_events','pr_ui_actions','pr_ui_activations'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists (
      select 1 from pg_policies
      where schemaname='public' and tablename=t and policyname='service_only'
    ) then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
