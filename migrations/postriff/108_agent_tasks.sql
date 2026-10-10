-- Rafii durable agent execution: the shared task engine (contract CF-3, "EX"). PROPOSED DDL, docs copy only: this file is
-- not in the runner's sequence. Lane J creates migrations/postriff/108_agent_tasks.sql byte-identical to it (a test
-- enforces that). The number is proposed; J re-checks base and every open PR before creating the file, and renames this
-- copy with it if the number moved. After either copy is applied anywhere, every change is a new forward migration.
--
-- Additive only; no existing table is altered. A task's anchor stays its existing `task:<uuid>` pr_agent_runs row (same id
-- = the taskId clients already hold); its client-visible log stays pr_agent_events (progress.updated stages, so that
-- CHECK is unchanged). These service-only tables hold the authoritative state, leases, private checkpoints, the ONE
-- approvals table (amendment X1), receipts and compensations.
--
-- Ownership tree: conversation -> anchor run -> task -> steps -> attempts / checkpoints / approvals / receipts /
-- compensations. Every child carries its parent's composite (id, workspace_id) key and is deleted with it (ON DELETE
-- CASCADE); the server has no DELETE privilege, so rows leave only with their conversation or workspace.
-- Every task belongs to exactly one person: created_by is the anchor run's actor (guard trigger), one open chat task
-- exists per person per conversation, and every attempt, receipt and approval is bound to that person.
-- Background (cron) attempts can only run R0 reads, delegate polls and waits (CHECK + guard trigger). A poll of a step that
-- observes an external effect (publish job, automation item) may record the read-only verdict 'observe': it keeps
-- observing after a cancel or a membership end, never acts, and still records the creator as actor (guard).
-- No foreign key into the permissions DDL (109), so 108 can ship (in shadow) before or after it.
begin;

create table if not exists public.pr_agent_tasks (
  id uuid primary key references public.pr_agent_runs(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  parent_task_id uuid,                                                        -- depth <= 1, enforced in code
  created_by uuid not null,                                                   -- the only person whose authority it runs under
  origin text not null check (origin in ('chat','voice','genui','task_center','recipe','opportunity','adopted')),
  title text not null check (length(title) between 1 and 140),
  state text not null default 'queued'
    check (state in ('queued','running','awaiting_approval','blocked','completed','failed','cancelled')),
  partial boolean not null default false,
  reason_code text check (reason_code is null or reason_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  version integer not null default 0 check (version >= 0),
  autonomy_mode text not null default 'ask' check (autonomy_mode in ('ask','assist','autopilot')),
  autopilot_policy_id uuid,                                                   -- 109 pr_agent_autopilot_policies.id (P2); no FK
  authz_token text not null check (authz_token ~ '^[0-9a-f]{64}$'),          -- Grants.token() at the last decision; compared with <>
  budget_ceiling_usd_micro bigint check (budget_ceiling_usd_micro is null or budget_ceiling_usd_micro >= 0),
  spent_usd_micro bigint not null default 0 check (spent_usd_micro >= 0),
  spend_unknown boolean not null default false,
  attempts_left integer not null default 24 check (attempts_left between 0 and 100),
  request_key text not null check (length(request_key) between 16 and 120),
  request_digest text not null check (request_digest ~ '^[0-9a-f]{64}$'),    -- sha256(created_by, canonical payload)
  dedupe_key text check (dedupe_key is null or dedupe_key ~ '^[0-9a-f]{64}$'),
  root_trace_id text not null check (root_trace_id ~ '^trace_[0-9a-f]{32}$'),
  cancel_requested_at timestamptz,
  cancel_requested_by uuid,
  next_wake_at timestamptz,
  expires_at timestamptz not null,
  hard_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint pr_agent_tasks_id_workspace unique (id, workspace_id),
  -- Workspace-wide on purpose: a key replayed by another member conflicts (409) instead of creating a second task.
  constraint pr_agent_tasks_request unique (workspace_id, request_key),
  constraint pr_agent_tasks_parent foreign key (parent_task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_tasks_not_own_parent check (parent_task_id is null or parent_task_id <> id),
  constraint pr_agent_tasks_ttl check (expires_at <= hard_expires_at and hard_expires_at <= created_at + interval '14 days'),
  constraint pr_agent_tasks_finished check ((state in ('completed','failed','cancelled')) = (finished_at is not null)),
  constraint pr_agent_tasks_cancel check ((cancel_requested_at is null) = (cancel_requested_by is null)),
  constraint pr_agent_tasks_autopilot check (autonomy_mode <> 'autopilot' or autopilot_policy_id is not null)
);
-- Correction 1: one open chat task per person per conversation, so a second member never extends someone else's task.
create unique index if not exists pr_agent_tasks_one_open_chat on public.pr_agent_tasks (workspace_id, conversation_id, created_by)
  where origin in ('chat','voice','adopted') and parent_task_id is null and state in ('queued','running','awaiting_approval','blocked');
create unique index if not exists pr_agent_tasks_dedupe on public.pr_agent_tasks (workspace_id, created_by, dedupe_key)
  where dedupe_key is not null and state in ('queued','running','awaiting_approval','blocked');
create index if not exists pr_agent_tasks_mine on public.pr_agent_tasks (workspace_id, created_by, updated_at desc, id);
create index if not exists pr_agent_tasks_open on public.pr_agent_tasks (workspace_id, state, updated_at desc)
  where state in ('queued','running','awaiting_approval','blocked');
create index if not exists pr_agent_tasks_wake on public.pr_agent_tasks (next_wake_at)
  where next_wake_at is not null and state in ('queued','running','awaiting_approval','blocked');
create index if not exists pr_agent_tasks_expiry on public.pr_agent_tasks (expires_at)
  where state in ('queued','running','awaiting_approval','blocked');
create index if not exists pr_agent_tasks_by_parent on public.pr_agent_tasks (parent_task_id) where parent_task_id is not null;

create table if not exists public.pr_agent_steps (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  step_key text not null check (step_key ~ '^s([1-9]|1[0-2])$'),            -- = existing Step.id s1..s12
  label text not null check (length(label) between 1 and 140),
  kind text not null check (kind in ('tool','model','approval','delegate','continuation','wait')),
  capability_id text check (capability_id is null or capability_id ~ '^[a-z][a-z0-9_.:-]{0,95}$'),
  capability_version integer check (capability_version is null or capability_version >= 1),
  risk_class text not null default 'R0' check (risk_class in ('R0','R1','R2','R3')),
  effect text not null default 'READ' check (effect in ('READ','CREATE_DRAFT','MUTATE_REVERSIBLE','PREPARE_EXTERNAL')),
  background_allowed boolean not null default false,                          -- may the cron executor claim it (P0: reads/observers)
  depends_on text[] not null default '{}' check (cardinality(depends_on) <= 11),
  inputs jsonb check (inputs is null or (jsonb_typeof(inputs) = 'object' and octet_length(inputs::text) <= 16384)),
  input_digest text check (input_digest is null or input_digest ~ '^[0-9a-f]{64}$'),
  target_refs jsonb not null default '[]'                                      -- [{type,id,revision}], validated at plan time
    check (jsonb_typeof(target_refs) = 'array' and octet_length(target_refs::text) <= 8192),
  planned_run_id uuid references public.pr_agent_runs(id) on delete set null, -- the turn whose ledger validated the targets
  state text not null default 'queued'
    check (state in ('queued','running','awaiting_approval','blocked','completed','failed','cancelled')),
  reason_code text check (reason_code is null or reason_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  reason text check (reason is null or length(reason) <= 300),
  verified boolean not null default false,
  retry_class text not null default 'manual' check (retry_class in ('auto','manual','never')),
  max_attempts smallint not null default 1 check (max_attempts between 1 and 5),
  -- Delegate polls last until the hard TTL; they are not limited to twenty work attempts.
  attempts integer not null default 0 check (attempts >= 0 and (kind = 'delegate' or attempts <= 20)),
  generation smallint not null default 1 check (generation between 1 and 4),
  timeout_seconds integer not null default 30 check (timeout_seconds between 5 and 240),
  next_attempt_at timestamptz,
  effect_key text check (effect_key is null or length(effect_key) between 16 and 120),
  delegate_type text check (delegate_type is null or delegate_type in
    ('proposal','ui_action','ui_attempt','publish_job','automation_item','library_job','weekly_slot','agent_task')),
  delegate_id text check (delegate_id is null or length(delegate_id) <= 120),  -- adapters resolve it inside step.workspace_id only
  observes_external boolean generated always as (coalesce(delegate_type in ('publish_job','automation_item'), false)) stored,
  wait_until timestamptz,
  outputs jsonb not null default '[]' check (jsonb_typeof(outputs) = 'array' and octet_length(outputs::text) <= 16384),
  entities jsonb not null default '[]' check (jsonb_typeof(entities) = 'array' and octet_length(entities::text) <= 16384),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_agent_steps_id_task_workspace unique (id, task_id, workspace_id),
  constraint pr_agent_steps_key unique (task_id, step_key),
  constraint pr_agent_steps_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_steps_tool check (kind <> 'tool' or (capability_id is not null and inputs is not null and input_digest is not null)),
  constraint pr_agent_steps_delegate check (kind <> 'delegate' or (delegate_type is not null and delegate_id is not null)),
  constraint pr_agent_steps_wait check (kind <> 'wait' or wait_until is not null),
  constraint pr_agent_steps_r3 check (risk_class <> 'R3' or kind in ('approval','delegate')),
  constraint pr_agent_steps_no_auto_external check (risk_class not in ('R2','R3') or retry_class <> 'auto'),
  -- Correction 9: cron may claim only R0 read tools, delegate polls and waits; never R1+ tools, models or continuations.
  constraint pr_agent_steps_background check (not background_allowed
    or (kind = 'tool' and risk_class = 'R0' and effect = 'READ') or kind in ('delegate','wait')),
  constraint pr_agent_steps_finished check (state not in ('completed','failed','cancelled') or finished_at is not null),
  constraint pr_agent_steps_verified check (state <> 'completed' or verified or kind in ('wait','continuation'))
);
create index if not exists pr_agent_steps_due on public.pr_agent_steps (next_attempt_at)
  where state = 'queued' and kind in ('tool','delegate','continuation','wait');
create index if not exists pr_agent_steps_due_background on public.pr_agent_steps (next_attempt_at)
  where state = 'queued' and background_allowed;
create index if not exists pr_agent_steps_delegate_target on public.pr_agent_steps (workspace_id, delegate_type, delegate_id)
  where delegate_id is not null;

create table if not exists public.pr_agent_step_attempts (
  id uuid primary key default gen_random_uuid(),
  step_id uuid not null,
  task_id uuid not null,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  actor uuid not null,                                                        -- always the task's created_by (guard trigger)
  attempt_no integer not null check (attempt_no >= 1),
  generation smallint not null check (generation between 1 and 4),
  executor text not null check (executor in ('inline','cron')),
  run_id uuid references public.pr_agent_runs(id) on delete set null,       -- the agent: turn that ran it (GenUI parent, ledger)
  state text not null default 'running' check (state in ('running','succeeded','failed','cancelled','interrupted')),
  lease_owner text not null check (length(lease_owner) between 1 and 80),   -- 'req:<request id>' | 'cron:<uuid hex>'
  lease_expires_at timestamptz not null,
  heartbeat_at timestamptz not null default now(),
  deadline_at timestamptz not null,
  authz_token text not null check (authz_token ~ '^[0-9a-f]{64}$'),          -- decide_for_step ran at this claim (every claim)
  -- 'observe': the read-only external-effect observer (CF-3 §6.1); allowed only on observes_external steps (guard), by cron.
  authz_verdict text not null check (authz_verdict in ('allow','approve','step_up','deny','observe')),
  authz_reason text check (authz_reason is null or authz_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  trace_id text not null check (trace_id ~ '^trace_[0-9a-f]{32}$'),
  request_id text check (request_id is null or length(request_id) <= 80),
  reservation_id text check (reservation_id is null or length(reservation_id) <= 120),
  cost_state text not null default 'none' check (cost_state in ('none','known','unknown','estimated')),
  cost_usd_micro bigint check (cost_usd_micro is null or cost_usd_micro >= 0),
  provider_requests smallint not null default 0 check (provider_requests between 0 and 20),
  error_category text check (error_category is null or error_category in
    ('retryable','permanent','permission','budget','cancelled','corrupt','timeout','unsupported','revoked','outcome_unknown','conflict')),
  error_code text check (error_code is null or error_code ~ '^[a-z][a-z0-9_]{0,79}$'),
  timings jsonb not null default '{}' check (jsonb_typeof(timings) = 'object' and octet_length(timings::text) <= 4096),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint pr_agent_step_attempts_id_workspace unique (id, workspace_id),
  constraint pr_agent_step_attempts_subject_key unique (id, step_id, task_id, workspace_id),
  constraint pr_agent_step_attempts_no unique (step_id, attempt_no),
  constraint pr_agent_step_attempts_step foreign key (step_id, task_id, workspace_id)
    references public.pr_agent_steps(id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_step_attempts_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_step_attempts_lease_owner check ((executor = 'inline' and lease_owner like 'req:%')
                                               or (executor = 'cron' and lease_owner like 'cron:%')),
  constraint pr_agent_step_attempts_observer check (authz_verdict <> 'observe' or executor = 'cron'),
  constraint pr_agent_step_attempts_finished check ((state = 'running') = (finished_at is null))
);
create unique index if not exists pr_agent_step_attempts_one_live on public.pr_agent_step_attempts (step_id) where state = 'running';
create index if not exists pr_agent_step_attempts_lease on public.pr_agent_step_attempts (lease_expires_at) where state = 'running';
create index if not exists pr_agent_step_attempts_by_task on public.pr_agent_step_attempts (task_id, started_at desc);
create index if not exists pr_agent_step_attempts_live_cron on public.pr_agent_step_attempts (workspace_id)
  where state = 'running' and executor = 'cron';

-- Private model state (SDK RunState) moved out of the member-readable pr_agent_runs.artifact.
create table if not exists public.pr_agent_checkpoints (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  step_id uuid,
  kind text not null check (kind in ('sdk_run_state','step_progress')),
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) <= 1048576),
  payload_hash text check (payload_hash is null or payload_hash ~ '^[0-9a-f]{64}$'),
  runtime_version text not null check (length(runtime_version) between 1 and 40),   -- service.RUNTIME_VERSION
  sdk_version text not null check (length(sdk_version) between 1 and 40),           -- openai-agents package version
  writer_model text check (writer_model is null or length(writer_model) <= 80),
  approval_ids uuid[] not null default '{}',
  state text not null default 'available' check (state in ('available','claimed','consumed','discarded')),
  claimed_by text check (claimed_by is null or length(claimed_by) <= 80),
  claim_expires_at timestamptz,
  expires_at timestamptz not null,
  discard_reason text check (discard_reason is null or discard_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_agent_checkpoints_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_checkpoints_step foreign key (step_id, task_id, workspace_id)
    references public.pr_agent_steps(id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_checkpoints_claim check (state <> 'claimed' or (claimed_by is not null and claim_expires_at is not null)),
  constraint pr_agent_checkpoints_cleared check (state not in ('consumed','discarded') or payload = '{}'::jsonb)
);
create unique index if not exists pr_agent_checkpoints_one_live on public.pr_agent_checkpoints (task_id)
  where kind = 'sdk_run_state' and state in ('available','claimed');
create index if not exists pr_agent_checkpoints_expiry on public.pr_agent_checkpoints (expires_at) where state in ('available','claimed');

-- The ONE approvals table (X1): legacy proposals and every new agent confirmation. Decided only through the engine's
-- resolve_approval (route POST agent/approvals/{approvalId}/decide, or the unchanged legacy body on approvals/decide).
create table if not exists public.pr_agent_approvals (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  task_id uuid not null,
  step_id uuid not null,
  generation smallint not null check (generation between 1 and 4),
  requested_for uuid not null,                                                -- = the task's created_by (guard trigger)
  approver uuid,                                                              -- named approver: always null in P0
  kind text not null check (kind in ('proposal','agent_action','spend','step_up_action')),
  proposal_id text check (proposal_id is null or length(proposal_id) <= 80),          -- site-agent proposal on pr_messages
  proposal_type text check (proposal_type is null or proposal_type ~ '^[a-z][a-z0-9_]{0,39}$'),
  conversation_id uuid references public.pr_conversations(id) on delete cascade,
  message_id uuid references public.pr_messages(id) on delete cascade,
  run_id uuid references public.pr_agent_runs(id) on delete set null,
  trace_id text check (trace_id is null or trace_id ~ '^trace_[0-9a-f]{32}$'),
  capability_id text check (capability_id is null or capability_id ~ '^[a-z][a-z0-9_.:-]{0,95}$'),
  capability_version integer check (capability_version is null or capability_version >= 1),
  risk_class text not null check (risk_class in ('R1','R2','R3')),
  confirmation text not null check (confirmation in ('native','proposal','approval_step_up')),
  input_digest text check (input_digest is null or input_digest ~ '^[0-9a-f]{64}$'),
  inputs jsonb check (inputs is null or (jsonb_typeof(inputs) = 'object' and octet_length(inputs::text) <= 16384)),   -- server-held
  target_refs jsonb not null default '[]' check (jsonb_typeof(target_refs) = 'array' and octet_length(target_refs::text) <= 8192),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),   -- new kinds: sha256(capability, input_digest, sorted targets, risk, generation)
  summary jsonb not null default '{}' check (jsonb_typeof(summary) = 'object' and octet_length(summary::text) <= 8192),
  required_permission text not null check (required_permission in ('edit','approve','owner')),
  approver_policy text not null check (approver_policy in ('task_owner','role_approve','role_owner')),
  requires_step_up boolean not null default false,
  authz_token text not null check (authz_token ~ '^[0-9a-f]{64}$'),          -- Grants.token() when requested
  state text not null default 'pending'
    check (state in ('pending','approved','consumed','rejected','expired','superseded','revoked')),
  expires_at timestamptz not null,
  decided_by uuid,
  decided_at timestamptz,
  decision_surface text check (decision_surface is null or decision_surface in ('panel','text','voice','genui','task_center','system')),
  decision_key text check (decision_key is null or length(decision_key) between 16 and 120),
  decision_outcome jsonb check (decision_outcome is null or jsonb_typeof(decision_outcome) = 'object'),
  step_up jsonb not null default '{}' check (jsonb_typeof(step_up) = 'object'),            -- {method, at, aal}; never a credential
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_agent_approvals_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_approvals_step foreign key (step_id, task_id, workspace_id)
    references public.pr_agent_steps(id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_approvals_proposal check (kind <> 'proposal'
    or (proposal_id is not null and proposal_type is not null and conversation_id is not null and message_id is not null)),
  constraint pr_agent_approvals_capability check (kind = 'proposal' or (capability_id is not null and input_digest is not null and inputs is not null)),
  constraint pr_agent_approvals_r3 check (risk_class <> 'R3' or (requires_step_up and confirmation = 'approval_step_up' and kind = 'step_up_action')),
  constraint pr_agent_approvals_step_up check (kind <> 'step_up_action' or requires_step_up),
  -- Correction 2 / EX-D8: only the task's creator decides new agent confirmations and spend in P0.
  constraint pr_agent_approvals_owner_kinds check (kind not in ('agent_action','spend') or approver_policy = 'task_owner'),
  constraint pr_agent_approvals_owner_decider check (kind not in ('agent_action','spend')
    or decided_by is null or decided_by = requested_for),
  -- Correction 17 / DP-5: a typed or spoken "yes" decides only the legacy schedule and automation proposals.
  constraint pr_agent_approvals_yes check (decision_surface not in ('text','voice')
    or (kind = 'proposal' and proposal_type in ('schedule_draft','reschedule_post','automation_change'))),
  -- Correction 4: every transition out of pending records when, including system expiry/revocation/supersession.
  constraint pr_agent_approvals_decided check ((state = 'pending') = (decided_at is null)),
  constraint pr_agent_approvals_decider check (state = 'pending' or decided_by is not null or decision_surface = 'system'),
  constraint pr_agent_approvals_system check (decision_surface is distinct from 'system' or state in ('expired','superseded','revoked')),
  constraint pr_agent_approvals_consumed check ((state = 'consumed') = (consumed_at is not null))
);
create unique index if not exists pr_agent_approvals_one_per_proposal on public.pr_agent_approvals (workspace_id, proposal_id) where proposal_id is not null;
create unique index if not exists pr_agent_approvals_decision on public.pr_agent_approvals (workspace_id, decision_key) where decision_key is not null;
create index if not exists pr_agent_approvals_pending on public.pr_agent_approvals (workspace_id, requested_for, expires_at) where state = 'pending';
create index if not exists pr_agent_approvals_by_task on public.pr_agent_approvals (task_id);
create index if not exists pr_agent_approvals_run on public.pr_agent_approvals (run_id) where run_id is not null;

-- Effect receipts for engine-bound steps (pr_ui_actions stays authoritative for GenUI; #144 keeps its own receipts).
create table if not exists public.pr_agent_receipts (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  effect_key text not null check (length(effect_key) between 16 and 120),
  task_id uuid not null,
  step_id uuid not null,
  attempt_id uuid,
  principal uuid not null,                                                    -- = the task's created_by (guard trigger)
  capability_id text not null check (capability_id ~ '^[a-z][a-z0-9_.:-]{0,95}$'),
  input_digest text not null check (input_digest ~ '^[0-9a-f]{64}$'),
  state text not null default 'pending' check (state in ('pending','done')),
  outcome text check (outcome is null or outcome in ('applied','prepared','rejected','conflict','failed','unknown')),
  verified boolean,
  result jsonb not null default '{}' check (jsonb_typeof(result) = 'object' and octet_length(result::text) <= 16384),
  ui_action_key text check (ui_action_key is null or length(ui_action_key) between 16 and 120),
  trace_id text not null check (trace_id ~ '^trace_[0-9a-f]{32}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, effect_key),
  constraint pr_agent_receipts_subject_key unique (workspace_id, effect_key, task_id, step_id),
  constraint pr_agent_receipts_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_receipts_step foreign key (step_id, task_id, workspace_id)
    references public.pr_agent_steps(id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_receipts_attempt foreign key (attempt_id, step_id, task_id, workspace_id)
    references public.pr_agent_step_attempts(id, step_id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_receipts_done check ((state = 'done') = (outcome is not null))
);
create index if not exists pr_agent_receipts_by_task on public.pr_agent_receipts (task_id, created_at);

create table if not exists public.pr_agent_compensations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  task_id uuid not null,
  step_id uuid not null,
  effect_key text not null check (length(effect_key) between 16 and 120),
  inverse_capability_id text not null check (inverse_capability_id ~ '^[a-z][a-z0-9_.:-]{0,95}$'),
  target_type text not null check (target_type ~ '^[a-z][a-z0-9_]{0,31}$'),
  target_id text not null check (length(target_id) between 1 and 120),
  post_image_digest text not null check (post_image_digest ~ '^[0-9a-f]{64}$'),
  inverse_inputs jsonb not null check (jsonb_typeof(inverse_inputs) = 'object' and octet_length(inverse_inputs::text) <= 16384),
  state text not null default 'available' check (state in ('available','applied','expired','conflict')),
  undo_until timestamptz not null,
  applied_effect_key text check (applied_effect_key is null or length(applied_effect_key) between 16 and 120),
  applied_by uuid,
  applied_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_agent_compensations_effect unique (workspace_id, effect_key),
  constraint pr_agent_compensations_task foreign key (task_id, workspace_id)
    references public.pr_agent_tasks(id, workspace_id) on delete cascade,
  constraint pr_agent_compensations_step foreign key (step_id, task_id, workspace_id)
    references public.pr_agent_steps(id, task_id, workspace_id) on delete cascade,
  constraint pr_agent_compensations_receipt foreign key (workspace_id, effect_key, task_id, step_id)
    references public.pr_agent_receipts(workspace_id, effect_key, task_id, step_id) on delete cascade,
  constraint pr_agent_compensations_window check (undo_until <= created_at + interval '7 days'),   -- product default 24 h (DP-13)
  constraint pr_agent_compensations_applied check ((state = 'applied')
    = (applied_at is not null and applied_by is not null and applied_effect_key is not null))
);
create index if not exists pr_agent_compensations_open on public.pr_agent_compensations (undo_until) where state = 'available';

-- Guards. Invoker functions (the 105 pattern): they only read rows the server can already read.
-- A task is anchored on its creator's own `task:` run in the same workspace and conversation; its identity is immutable.
create or replace function postriff_private.agent_task_anchor_guard()
returns trigger language plpgsql set search_path='' as $body$
begin
  if tg_op = 'UPDATE' then
    if (new.id, new.workspace_id, new.conversation_id, new.created_by, new.origin, new.request_key)
         is distinct from (old.id, old.workspace_id, old.conversation_id, old.created_by, old.origin, old.request_key) then
      raise exception 'an agent task''s identity cannot change' using errcode = '55000';
    end if;
  end if;
  if not exists (select 1 from public.pr_agent_runs r join public.pr_conversations c on c.id = r.conversation_id
                  where r.id = new.id and r.workspace_id = new.workspace_id and c.workspace_id = new.workspace_id
                    and r.conversation_id = new.conversation_id and r.actor = new.created_by
                    and r.idempotency_key like 'task:%') then
    raise exception 'an agent task must be anchored on its creator''s task run in the same workspace' using errcode = '23514';
  end if;
  return new;
end $body$;

-- Plan-time turns must belong to the step's workspace. SET NULL on deletion remains allowed.
create or replace function postriff_private.agent_step_plan_guard()
returns trigger language plpgsql set search_path='' as $body$
begin
  if new.planned_run_id is not null and not exists (
    select 1 from public.pr_agent_runs r where r.id = new.planned_run_id and r.workspace_id = new.workspace_id
  ) then
    raise exception 'a planned run must belong to the step workspace' using errcode = '23514';
  end if;
  return new;
end $body$;
revoke all on function postriff_private.agent_step_plan_guard() from public, anon, authenticated;
grant execute on function postriff_private.agent_step_plan_guard() to service_role;
drop trigger if exists pr_agent_steps_plan_guard on public.pr_agent_steps;
create trigger pr_agent_steps_plan_guard before insert or update of planned_run_id, workspace_id on public.pr_agent_steps
  for each row execute function postriff_private.agent_step_plan_guard();

-- Attempts run as the task's creator; cron attempts only on background-allowed steps; the read-only 'observe' verdict
-- only on a step that observes an external effect; the turn row is in the workspace.
-- On UPDATE only the identity is checked: the run_id ON DELETE SET NULL action fires while its conversation (and so the
-- task) is being deleted, and must not be refused.
create or replace function postriff_private.agent_attempt_guard()
returns trigger language plpgsql set search_path='' as $body$
declare creator uuid; may_background boolean; observer boolean; step_kind text; previous_run uuid;
begin
  if tg_op = 'UPDATE' then
    previous_run := old.run_id;
    if (new.step_id, new.task_id, new.workspace_id, new.actor, new.executor, new.authz_verdict, new.attempt_no)
         is distinct from (old.step_id, old.task_id, old.workspace_id, old.actor, old.executor, old.authz_verdict, old.attempt_no) then
      raise exception 'an agent step attempt''s identity cannot change' using errcode = '55000';
    end if;
  else
    select t.created_by into creator from public.pr_agent_tasks t where t.id = new.task_id and t.workspace_id = new.workspace_id;
    select s.background_allowed, s.observes_external, s.kind into may_background, observer, step_kind from public.pr_agent_steps s
     where s.id = new.step_id and s.task_id = new.task_id and s.workspace_id = new.workspace_id;
    if creator is null or new.actor is distinct from creator then
      raise exception 'an agent step attempt runs only as the task''s creator' using errcode = '23514';
    end if;
    if step_kind <> 'delegate' and new.attempt_no > 20 then
      raise exception 'a work step cannot exceed twenty lifetime attempts' using errcode = '23514';
    end if;
    if new.executor = 'cron' and may_background is not true then
      raise exception 'the background executor may only claim background-allowed steps' using errcode = '23514';
    end if;
    if new.authz_verdict = 'observe' and observer is not true then
      raise exception 'only a step that observes an external effect may record the observe verdict' using errcode = '23514';
    end if;
  end if;
  if new.run_id is not null and new.run_id is distinct from previous_run
     and not exists (select 1 from public.pr_agent_runs r where r.id = new.run_id and r.workspace_id = new.workspace_id) then
    raise exception 'an attempt''s run must belong to the same workspace' using errcode = '23514';
  end if;
  return new;
end $body$;

-- Approvals are requested for the task's creator; their conversation, message and run stay in the workspace.
-- On UPDATE only the subject is checked (same reason as the attempt guard: run_id is SET NULL during a cascade).
create or replace function postriff_private.agent_approval_guard()
returns trigger language plpgsql set search_path='' as $body$
declare creator uuid; previous_run uuid;
begin
  if tg_op = 'UPDATE' then
    previous_run := old.run_id;
    if (new.task_id, new.step_id, new.requested_for, new.kind, new.digest, new.conversation_id, new.message_id)
         is distinct from (old.task_id, old.step_id, old.requested_for, old.kind, old.digest, old.conversation_id, old.message_id) then
      raise exception 'an approval''s subject cannot change' using errcode = '55000';
    end if;
  else
    select t.created_by into creator from public.pr_agent_tasks t where t.id = new.task_id and t.workspace_id = new.workspace_id;
    if creator is null or new.requested_for is distinct from creator then
      raise exception 'an approval is requested for the task''s creator' using errcode = '23514';
    end if;
    if new.conversation_id is not null and not exists (select 1 from public.pr_conversations c
         where c.id = new.conversation_id and c.workspace_id = new.workspace_id
           and c.id = (select t.conversation_id from public.pr_agent_tasks t where t.id = new.task_id and t.workspace_id = new.workspace_id)) then
      raise exception 'an approval''s conversation must be its task conversation' using errcode = '23514';
    end if;
    if new.message_id is not null and not exists (select 1 from public.pr_messages m
         where m.id = new.message_id and m.workspace_id = new.workspace_id and m.conversation_id = new.conversation_id) then
      raise exception 'an approval''s message must belong to its conversation' using errcode = '23514';
    end if;
  end if;
  if new.run_id is not null and new.run_id is distinct from previous_run
     and not exists (select 1 from public.pr_agent_runs r where r.id = new.run_id and r.workspace_id = new.workspace_id) then
    raise exception 'an approval''s run must belong to the same workspace' using errcode = '23514';
  end if;
  return new;
end $body$;

-- Receipts record the creator as principal.
create or replace function postriff_private.agent_receipt_guard()
returns trigger language plpgsql set search_path='' as $body$
begin
  if tg_op = 'UPDATE' then
    if (new.task_id, new.step_id, new.principal, new.workspace_id, new.effect_key)
         is distinct from (old.task_id, old.step_id, old.principal, old.workspace_id, old.effect_key) then
      raise exception 'an agent receipt''s subject cannot change' using errcode = '55000';
    end if;
    return new;
  end if;
  if not exists (select 1 from public.pr_agent_tasks t where t.id = new.task_id and t.workspace_id = new.workspace_id
                   and t.created_by = new.principal) then
    raise exception 'an agent receipt''s principal is the task''s creator' using errcode = '23514';
  end if;
  return new;
end $body$;

revoke all on function postriff_private.agent_task_anchor_guard(), postriff_private.agent_attempt_guard(),
  postriff_private.agent_approval_guard(), postriff_private.agent_receipt_guard() from public, anon, authenticated;
grant execute on function postriff_private.agent_task_anchor_guard(), postriff_private.agent_attempt_guard(),
  postriff_private.agent_approval_guard(), postriff_private.agent_receipt_guard() to service_role;
drop trigger if exists pr_agent_tasks_anchor_guard on public.pr_agent_tasks;
create trigger pr_agent_tasks_anchor_guard before insert or update of id, workspace_id, conversation_id, created_by, origin, request_key
  on public.pr_agent_tasks for each row execute function postriff_private.agent_task_anchor_guard();
drop trigger if exists pr_agent_step_attempts_guard on public.pr_agent_step_attempts;
create trigger pr_agent_step_attempts_guard before insert or update of step_id, task_id, workspace_id, actor, executor, authz_verdict, attempt_no, run_id
  on public.pr_agent_step_attempts for each row execute function postriff_private.agent_attempt_guard();
drop trigger if exists pr_agent_approvals_guard on public.pr_agent_approvals;
create trigger pr_agent_approvals_guard before insert or update of task_id, step_id, requested_for, kind, digest, conversation_id, message_id, run_id
  on public.pr_agent_approvals for each row execute function postriff_private.agent_approval_guard();
drop trigger if exists pr_agent_receipts_guard on public.pr_agent_receipts;
create trigger pr_agent_receipts_guard before insert or update of task_id, step_id, principal, workspace_id, effect_key
  on public.pr_agent_receipts for each row execute function postriff_private.agent_receipt_guard();

-- Service-only: forced RLS, no browser role, server may read/insert/update but never delete (rows leave by cascade only).
do $$
declare t text;
begin
  foreach t in array array['pr_agent_tasks','pr_agent_steps','pr_agent_step_attempts','pr_agent_checkpoints',
                           'pr_agent_approvals','pr_agent_receipts','pr_agent_compensations'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated, service_role', t);
    execute format('grant select, insert, update on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
