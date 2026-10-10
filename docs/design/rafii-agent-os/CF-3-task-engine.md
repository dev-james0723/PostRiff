# CF-3 — Durable task engine ("EX"), amended

**Status:** PROPOSED, amended; independent review and recorded validation required before freeze. The critical and high corrections are folded into this text and into the one DDL file [`migrations/108_agent_tasks.sql`](migrations/108_agent_tasks.sql), which also holds the single merged approvals table (X1).
**Depends on:** CF-1 (capability fields: `risk`, `effect`, `idempotency`, `retry_class`, `max_attempts`, `timeout_seconds`, `paid`, `background_eligible`, `inverse`), CF-2 (`decide_for_step`, `Grants.token()`, the error table §13, the approval rules §9). **Consumed by:** lanes C, H (Task Center), E (journeys), G (recipes, notifications), I (fault injection).
**Base verified:** `origin/consumer-saas` `de4e5907`. Paths relative to `src/postriff_phase2/` unless they start with `migrations/`, `web/`, `tests/` or `docs/`.
**James decisions applied (2026-10-09):** DP-10 (task list "mine" by default; owners may see workspace scope; only the task owner and workspace owners can cancel), DP-5 ("yes" only for legacy proposals), DP-8 (332ed6e6 for ordinary-user evidence).

---

## 0. The decision in one paragraph (amended)

Rafii gets **one** task engine, switched per workspace through `task_engine_for(ws)` = `off | shadow | on` (§21.1); only `on` changes anything a person sees. A task is anchored on the `task:<uuid>` row that already exists in `pr_agent_runs` (same id, so every `taskId` the web, voice and GenUI `task_progress` code holds stays valid); its client log stays `pr_agent_events` (`progress.updated` stages, no CHECK change). Seven service-only tables hold the authoritative state; no existing table is altered. **Every task belongs to one person** (`created_by` = the anchor run's actor): nobody else's request can extend, advance, retry, continue or execute it, and an approval by someone else completes only the approved step — the owner continues. Steps run **inline** inside the owner's own request, or on the **cron executor**, which in P0 may run only R0 reads, delegate polls, waits, recovery and expiry. Every claim re-runs CF-2's `decide_for_step`. Durable executors that already exist (publish queue, automations, GenUI attempts, Library jobs, weekly slots) are not moved: a step *delegates* to them and mirrors their state. Vercel Queues is not adopted.

## 1. What exists today (IMPLEMENTED, verified at `de4e5907`)

| Piece | Where | Engine use |
|---|---|---|
| `pr_agent_runs`: `actor`, status `running/completed/failed/cancelled/applied`, `unique(workspace_id, idempotency_key)`, member-readable (`tenant_read`) | `migrations/postriff/005_consumer_web_ideas.sql:40-58, 82-96` | The task anchor; status mirrored from the engine (§4.5). `policy_epoch` is a source digest and is **not** reused for authorization. |
| `pr_agent_events` (11 kinds, cursor replay) | `005:60-68`; `ideas.py` event helpers | Client log; new `progress.updated` stages (§16). |
| TaskPlan v1 (steps `planned…canceled`, `MAX_STEPS=12`, model may not set done, CAS → `task_conflict`) | `agent_runtime_v2/task_state.py`; `contracts.py:23-27` | In mode `on`, a view over `pr_agent_steps`; `artifact.task` is still written for old readers, as the redacted projection (§4.5). |
| `task_state.active()` returns the newest running task **of any member** in the conversation | `task_state.py:204-209` | **Amended (correction 1):** filters `actor = principal` (§4.6). |
| `task_plan` / `task_update` hooks, `_step_done`/`_step_failed` | `agent_runtime_v2/domain_tools.py:36-100` | Inline hook points for attempts and effect keys. |
| SDK pause: `artifact.pendingRun`; `_store_pending_run` / `_claim_pending_run` / `_resume_pending_run` | `agent_runtime_v2/service.py:1063, 1081, 1095` | Copied into service-only checkpoints in `shadow`; held only there in `on` (§11); resume rule amended in `on` (correction 2). |
| Proposals (digest-bound, 24 h TTL, single use; bare "yes" within 600 s) | `site_agent/proposals.py:22, 38, 191-216`; `agent_runtime_v2/approvals.py:19, 73, 102, 136` | Wrapped by `pr_agent_approvals` rows; the apply path is reused unchanged. |
| Panel decide route (does not resume the paused run) | `agent_runtime_v2/http.py:78-79` → `service.py:1267` | Same request/response; internally calls `resolve_approval` (§10). |
| Turn cancel (actor-only, cooperative) | `service.py:392`; `tool_adapter.py:119-120` | Generalised to task cancel (§12). |
| Lazy agent-turn reaper | `service.py:656, 1034` | Called by the recovery step (§5.3). |
| GenUI producer lease/checkpoint/reaper; unknown cost held | `migrations/postriff/102_agent_ui_artifacts.sql:67-106`; `agent_runtime_v2/ui_store.py:56, 670-697, 832-921`; `hosted_app.py:685` | **The only source** for the shared `leases.py` semantics (correction 18). |
| GenUI action receipts (same transaction as the domain command; key+digest replay; 409 on a different digest) | `102:124-155`; `ui_actions.py:91-243` | Generalised as `pr_agent_receipts`; `pr_ui_actions` stays authoritative for GenUI. |
| Ledger: idempotent reserve by key, `run_id`/`job_id`, settle `completed/failed/unknown` | `billing.py:169-225, 261-267` | Every paid attempt reserves with `run_id = task id`, `job_id = attempt id`. |
| Worker identity `principal_repository` (membership + binding re-checked every transaction) | `automation_runs.py:38` | The only way a cron step acts as its owner. |
| Per-transaction re-authorisation, `FOR UPDATE OF w`, account block/deletion refusal | `hosted.py:113-133` | Covers membership end and account state for free. |
| Cron: one per-minute `/api/cron/worker` | `vercel.json` `crons`; `hosted_app.py` worker steps | Recovery and expiry run here in P0 (§5.3). |

**Not found anywhere, so built here:** task list and cancel endpoints, step leases, per-step checkpoints, first-class approval rows, compensation records, a cron reaper for `task:` rows, client discovery of in-flight tasks after navigation.

## 2. Vocabulary

**EX-1 States** (one spelling, `cancelled`): `queued | running | awaiting_approval | blocked | completed | failed | cancelled`; the first four are open. Legacy view mapping (`legacyState`): queued→planned, running→running, awaiting_approval→needs_user, blocked with `needs_input`→needs_user, other blocked→blocked, completed→done, failed→failed, cancelled→canceled. Attempt states `running | succeeded | failed | cancelled | interrupted`; approval states `pending | approved | consumed | rejected | expired | superseded | revoked`; checkpoint states `available | claimed | consumed | discarded`; compensation states `available | applied | expired | conflict`.

**EX-2 Risk → execution** (CF-1 decides the class; `FORBIDDEN_EFFECTS` unchanged):

| Risk | Step effect | Execution |
|---|---|---|
| R0 | `READ` | Inline, or cron when `background_allowed` (CF-1 `background_eligible`). |
| R1 | `CREATE_DRAFT`, `MUTATE_REVERSIBLE` | **Inline only**, in the owner's own request or after the owner's explicit action (approve, Continue, retry). Compensation record when an inverse exists. |
| R2 | `PREPARE_EXTERNAL` | The engine prepares a proposal inline; a person approves it on a native button; the existing executor performs the effect; a `delegate` step observes it. |
| R3 | none (kind `approval`/`delegate` only) | Never executed by Rafii; navigate/guide only with re-auth ≤ 5 min (DP-5); the engine only observes. |

**Codes.** Client-visible error codes are **only** those in CF-2 §13.1 (correction 16). Step/task `reason_code` values are CF-2 §13.3 (state data, never an HTTP `code`); `decide()` reasons map to them through CF-2 §8.4. Internal error categories for attempts: `retryable, permanent, permission, budget, cancelled, corrupt, timeout, unsupported, revoked, outcome_unknown, conflict`. `lease_lost` is internal (a losing producer writes nothing); it is never returned to a client.

**EX-4 Invariants kept from `task_state.py`:** `completed` only by the executor that did the work and re-read it (a CHECK in 108 requires `verified` except for `wait`/`continuation`); a model sets only `running`, `blocked` (`needs_input`) or `cancelled`, always with a reason; a terminal step is never reopened (an explicit retry creates a new generation); no step is silently dropped.

## 3. Migration 108 (full DDL in [`migrations/108_agent_tasks.sql`](migrations/108_agent_tasks.sql))

| Table | Notes and amendments |
|---|---|
| `pr_agent_tasks` | `unique (id, workspace_id)` for composite child keys (correction 13). `authz_token text` (64 hex) replaces `authz_epoch` (correction 3). `request_key` unique **per workspace** with `request_digest = sha256(created_by, payload)` so another member's replay conflicts (correction 11, §8.3). **Partial unique index `(workspace_id, conversation_id, created_by)`** for open chat tasks (correction 1). Guard trigger: the anchor must be the same workspace's `task:` run **whose actor is `created_by`**, in the same conversation; identity columns are immutable. |
| `pr_agent_steps` | `unique (id, task_id, workspace_id)`; composite FK to the task. `background_allowed` with CHECK: only R0 READ tools, delegates and waits (correction 9). `target_refs` and `planned_run_id` record the plan-time target validation (correction 9). `observes_external` (generated: `publish_job`, `automation_item`) drives the expiry exemption (correction 19). CHECK: completed ⇒ verified. |
| `pr_agent_step_attempts` | `actor` = the task's creator (guard); cron attempts only on background-allowed steps (guard); `authz_token`, `authz_verdict`, `authz_reason` recorded on **every** claim (correction 3); one live attempt per step (partial unique). Composite FKs to step and task. |
| `pr_agent_checkpoints` | Service-only private RunState; CHECK: payload cleared to `{}` when consumed or discarded; one live `sdk_run_state` per task. |
| `pr_agent_approvals` | **The** approvals table (X1): legacy proposals and every new kind. `requested_for` = the task's creator (guard; revocation handler H1 keys on it). CHECKs: new kinds (`agent_action`, `spend`) decided only under `task_owner` and `decided_by = requested_for` (system closes leave it NULL) (correction 2); text/voice decide only legacy proposal types (correction 17, DP-5); every close records `decided_at`, system closes use `decision_surface='system'` (correction 4); consumed ⇔ `consumed_at`. One digest (correction 4). |
| `pr_agent_receipts` | PK `(workspace_id, effect_key)`; `principal` = the creator (guard); composite FKs. |
| `pr_agent_compensations` | Composite FKs; FK to its receipt; `undo_until` ≤ 7 days (product default 24 h, DP-13). |

All seven tables: forced RLS, `service_only` policy, `REVOKE ALL` from `public, anon, authenticated, service_role`, then `select, insert, update` for the server — **no DELETE**: rows leave only with their conversation (anchor-run cascade) or workspace. Guards are invoker functions in `postriff_private`; on UPDATE they preserve identity; the task anchor is re-checked, while attempt/approval `run_id` clearing is permitted so the `run_id ON DELETE SET NULL` actions that fire while a conversation is being deleted are never refused (proved in AOS-12). Why new tables instead of columns: `pr_agent_runs` is member-readable (`005:94-97`) while leases and paused model state must be service-only; `pr_ui_attempts` is bound to GenUI artifacts and frozen (D-A18/D-A39); `pr_library_jobs` belongs to #144.

## 4. State machines

### 4.1 Step transitions (the only legal edges)

```
queued ──claim──▶ running ──verified success──▶ completed
  ▲  ▲              │──retryable & attempts<max & attempts_left>0──▶ queued (next_attempt_at = now()+backoff)
  │  │              │──verdict approve/step_up─────────────────────▶ awaiting_approval
  │  │              │──deny / revoked / precondition───────────────▶ blocked
  │  │              │──permanent / corrupt / unsupported / outcome_unknown / unverified──▶ failed
  │  │              └──cancel observed───────────────────────────▶ cancelled
  │  └── approval approved (step needs execution) ◀── awaiting_approval ──rejected──▶ cancelled (approval_rejected)
  │                                                       ├──expired─▶ failed (approval_expired)
  │                                                       └──revoked/superseded─▶ blocked / cancelled
  └── explicit retry by the owner (generation+1) ◀── failed | blocked
```

`approval`-kind steps complete when the approval is applied and verified (`approvals.verify_applied`, `approvals.py:102`); `delegate` steps mirror their target (§7.3); `wait` steps are `queued` with `next_attempt_at = wait_until`.

### 4.2 Task state derivation (EX-6, `derive(task, steps)` on every save)

1. `cancel_requested_at` set, no step `running`, and no `observes_external` step open → `cancelled`. (An open external-effect observer keeps the task open; rules 2–5 then apply to it, §4.4.)
2. Any step `running` → `running`.
3. Any `awaiting_approval` → `awaiting_approval`.
4. Any `queued` step whose dependencies are not failed → `queued`.
5. Any `blocked`, or a `failed` step still retryable (`retry_class <> 'never'`, `generation < 4`, `attempts_left > 0`) → `blocked` (`step_failed` for the latter).
6. Otherwise terminal: `completed` if every step completed; `cancelled` if every step cancelled; else `failed`.
7. `partial = true` when terminal, not `completed`, and at least one step completed. (Replaces `TaskPlan.refresh_status()`, which reports `completed` with failed steps; the founder projection `054` counts change — X12 notice.)

### 4.3 Dependencies and partial failure (EX-7)

A step is claimable only when every `depends_on` step is completed. A non-retryable failure cancels its transitive dependents (`dependency_failed`) in the same transaction; a retryable one leaves them queued with `waitingOn`. Independent steps keep running.

### 4.4 TTL and the external-effect exemption (EX-8, correction 19)

- `expires_at = now() + 72 h` at creation, extended to `now() + 72 h` on each step completion, capped by `hard_expires_at = created_at + 14 d` (a CHECK in 108).
- When `expires_at` passes, the expiry phase sets open steps → `cancelled/task_expired`, pending approvals → `expired` (system), the checkpoint → `discarded`, and the task → its derived terminal state, **except** steps with `observes_external = true` (`publish_job`, `automation_item` delegates). Those keep observing the queue until the job is final or `hard_expires_at`; at the hard cap they end `failed/outcome_unknown` with the job link. The task is **never** `cancelled` while such a step is open, and the receipt's `providerReceipt` is read live from the queue job, so a later `verified` is shown truthfully.
- **The same exemption covers cancel and membership end.** A cancel (§12) and a membership end (§14) close every other open step but leave an open `observes_external` step queued. Its polls are still claimed (the claim SQL exempts it from the cancel filter, §5.2), run as the read-only observer (§6.1) and do not spend the task's `attempts_left`. When the job is final the step closes and the task takes its derived terminal state: `cancelled` with `partial = true` after a cancel if the step completed, `failed`/`partial` otherwise.

### 4.5 Anchor mirror (EX-9)

In mode `on`, `pr_agent_runs.status` for the anchor is written in the same transaction (open → `running`; terminal → `completed`/`failed`/`cancelled`, all values the existing CHECK allows), and `artifact.task` is re-written as the legacy projection, so `task_state.active()`, `active_run`, the founder projection and `ideas.recover_stalled`'s exclusion keep working.

**The legacy projection is redacted (correction 10).** `pr_agent_runs` is member-readable (`tenant_read`, `005:82-96`), so the projection the engine writes there is `{title, version, createdBy, steps: [{id, label, state, kind, dependsOn, verified, startedAt, updatedAt}]}`. It carries no `outputs`, `entities`, `approvals` or `reason`; those live only in the service-only engine rows. Step labels and the title stay, because legacy readers need them (`TaskPlan.from_artifact` drops steps without a label) and they are the task's own plan text that co-members already see as its title. Adoption (§21.2) replaces a pre-engine artifact's step detail with this projection once the workspace is `on`. In `off` and `shadow` the engine never writes `pr_agent_runs`.

### 4.6 One open chat task per person per conversation (EX-10, correction 1)

`pr_agent_tasks_one_open_chat` is `(workspace_id, conversation_id, created_by)`. `task_state.active(cur, workspace_id, conversation_id, principal)` and `latest(...)` filter `pr_agent_runs.actor = principal`. `task_plan` and `task_update` extend or advance **only** a task whose `created_by` equals the requesting principal; otherwise `task_plan` creates the caller's own task in that conversation. Supersede rule (unchanged otherwise): if the caller's open task has no pending approval and every open step is `blocked/needs_conversation`, a new plan supersedes it (`task_superseded`); pending approvals are never superseded this way.

## 5. Execution

### 5.1 Two executors (EX-11, correction 9)

| Executor | Trigger | Lease owner | May run |
|---|---|---|---|
| **inline** | A request **by the task's creator**: `POST agent/turns` (tool calls with `stepId`), `approvals/{id}/decide` or the legacy decide body when the decider is the creator, `tasks/{t}/steps/{s}/retry`, `tasks/{t}/continue` | `req:<postriff.request_id>` | Any kind except `wait`, inside `TURN_BUDGET_SECONDS = 240` (`service.py:39`); a step starts only if `timeout_seconds + 30 s` fits before the request deadline. |
| **cron** | `GET /api/cron/agent-tasks` (P0: code present, **unscheduled** until DP-12) and the recovery step inside `/api/cron/worker` | `cron:<uuid4 hex>` | **Only** steps with `background_allowed` (R0 READ tools, `delegate` polls, `wait`), plus recovery and expiry, and only in workspaces where `task_engine_for(ws) == 'on'`. Never R1+ tools, `model` steps or `continuation` steps (CHECK + guard trigger in 108). External-effect observers keep polling after a cancel or a membership end (§4.4, §6.1). |

Clients never drive execution; polling only reads. A request by anyone other than the creator never runs that task's steps.

### 5.2 Claim, heartbeat, finish (frozen SQL shape; `postriff_phase2/leases.py`)

`leases.py` is extracted **only from merged code** (correction 18): the `ui_store.py` lease semantics (lease = timeout + 30 s; renewal by a guarded UPDATE on `lease_owner` and live state; a closed attempt makes the producer stop; reaping marks `interrupted` and keeps unknown cost held) plus the backoff and classification written out in §9.2 below. PR #144's `library_intelligence/jobs.py` may adopt it after #144 merges, at its owner's choice; that is not a precondition for anything here.

```sql
-- claim (own transaction, committed alone; never takes the workspace row lock)
UPDATE public.pr_agent_steps s SET state='running', attempts=s.attempts+1, started_at=coalesce(s.started_at, now()), updated_at=now()
WHERE s.id = (
  SELECT d.id FROM public.pr_agent_steps d JOIN public.pr_agent_tasks t ON t.id = d.task_id AND t.workspace_id = d.workspace_id
  WHERE d.state='queued' AND d.next_attempt_at <= now() AND d.kind = ANY(%(kinds)s)
    AND (%(engine_all)s OR d.workspace_id = ANY(%(engine_workspaces)s::uuid[]))   -- only workspaces in mode 'on' (§21.1)
    AND (%(executor)s = 'inline' OR d.background_allowed)              -- cron: background-allowed steps only
    AND (%(executor)s = 'cron' OR t.created_by = %(principal)s)        -- inline: only the owner's own request
    AND t.state IN ('queued','running','blocked','awaiting_approval')
    AND t.hard_expires_at > now()                                    -- no poll or effect can outlive the hard TTL
    AND (t.cancel_requested_at IS NULL OR d.observes_external)         -- a cancel never stops an external-effect observer
    AND (t.attempts_left > 0 OR d.kind = 'delegate')                   -- a poll is an observation, not a retry
    AND d.timeout_seconds + 30 <= %(seconds_left)s
    AND NOT EXISTS (SELECT 1 FROM public.pr_agent_steps x WHERE x.task_id=d.task_id AND x.step_key = ANY(d.depends_on) AND x.state <> 'completed')
    AND EXISTS (SELECT 1 FROM public.pr_workspaces w WHERE w.id=d.workspace_id AND NOT (w.state ? 'accountBlock') AND NOT (w.state ? 'accountDeletion'))
    AND (%(executor)s = 'inline' OR (SELECT count(*) FROM public.pr_agent_step_attempts a
         WHERE a.workspace_id=d.workspace_id AND a.state='running' AND a.executor='cron') < 2)
  ORDER BY d.next_attempt_at, d.created_at LIMIT 1 FOR UPDATE OF d SKIP LOCKED)
RETURNING s.id, s.task_id, s.workspace_id, s.step_key, s.attempts, s.generation, s.timeout_seconds;
-- same transaction: decide_for_step (§6.2); INSERT pr_agent_step_attempts(actor = task.created_by, authz_token, authz_verdict, ...,
-- lease_expires_at = now()+(timeout+30 s), deadline_at = now()+timeout); UPDATE pr_agent_tasks SET
-- attempts_left = attempts_left - (CASE WHEN step.kind = 'delegate' THEN 0 ELSE 1 END), state = derive(...).
-- The partial unique index pr_agent_step_attempts_one_live rejects a second live attempt.
-- engine_workspaces / engine_all come from RuntimeConfig: the allowlist when RAFII_TASK_ENGINE_AUTHORITATIVE is on (engine_all
-- only for an explicit '*'), otherwise an empty array and false, so nothing is claimed in 'off' or 'shadow'.
```

When a runnable step is queued, set `next_attempt_at` to its due time (normally `now()`); `NULL` explicitly means unscheduled and is not claimable. Delegate polling uses a monotonic integer `attempts`/`attempt_no` for its lifetime, including polls beyond twenty; ordinary work steps remain capped at twenty. A successful non-final poll requeues no sooner than 60 seconds later. The hard TTL, rather than the work-attempt cap, ends observation.

Heartbeat renews only the attempt row (`lease_expires_at = greatest(lease_expires_at, now()+(timeout+30 s))`, guarded by `lease_owner` and `state='running'`), at least every 20 s for steps with `timeout_seconds > 60`. Finish happens in the work transaction and re-checks `lease_owner`/`state`; on mismatch nothing is written.

### 5.3 Cron tick and the P0 placement (EX-12)

Phases are isolated and never raise out (the `coworker/runtime.py` style); phases 1–3 make zero provider requests. **Every phase selects only workspaces where `task_engine_for(ws) == 'on'`** (the same `engine_workspaces` predicate as the claim), with one exception in phase 1 for rollback below. In `off` and `shadow` the tick changes no row.
1. **recover:** running attempts with an expired lease (`FOR UPDATE SKIP LOCKED LIMIT 50`) → `interrupted`, reservation settled `unknown` (hold kept). Step: receipt `done` → `completed` (re-read verified); `retry_class='auto'` and attempts left → `queued` with backoff; otherwise `failed/outcome_unknown` with manual retry offered. *Rollback exception:* an expired attempt in a workspace that has left `on` (attempts exist only where the engine was `on`) is still marked `interrupted` and its reservation settled `unknown` with the hold kept, but nothing else is written: no step or task re-derivation, no anchor mirror, no legacy row.
2. **expire:** approvals past `expires_at` → `expired` (system) and the step → `failed/approval_expired`; checkpoints past expiry → `discarded` (payload `{}`); compensations past `undo_until` → `expired`; tasks past `expires_at` → §4.4 (with the external-effect exemption).
3. **adopt and reap legacy** (≤ 50 rows, mode-`on` workspaces only): adopt running `task:` rows with no engine row (§21.2); run `_reap_stale_turns` for `agent:` turns stalled > 600 s (≤ 20 workspaces); settle orphaned engine reservations `unknown`.
4. **claim loop** (background-allowed steps only) while time is left; deferrals are counted.
5. **summary:** counts only, never workspace ids or text.

**P0:** phases 1–3 run as `result['agentTaskRecovery'] = task_engine.recover(...)` inside the existing `/api/cron/worker` (beside `uiRecovery`, `hosted_app.py:685`), with a ≤ 10 s budget. Phase 4 runs only on the dedicated `/api/cron/agent-tasks` route (auth before init, `CRON_SECRET`, `hmac.compare_digest`), which stays out of `vercel.json` until DP-12; `RAFII_TASK_ENGINE_BACKGROUND` stays off until then. Journey C (R1) needs no background claims. Revisit trigger for Vercel Queues (wake-up signal only, no schema change): p95 wait for background steps > 90 s for 7 days or `deferred` > 5 % of claims.

## 6. Running a claimed step (EX-14)

### 6.1 Identity (corrections 1 and 2)

- **cron:** `principal_repository(service, ws, task.created_by, capability.permission, check=...)`; membership, role and account state are re-checked in every transaction.
- **cron, read-only observer:** a poll of an `observes_external` delegate step on a task that is cancel-requested, or whose creator's membership has ended, cannot run as the creator (`principal_repository` refuses an ended membership). It runs as the read-only observer instead: `decide_for_step` returns `observe` (CF-2 §8.4) without loading grants; the poll uses a service transaction scoped to `step.workspace_id`, reads the one job or item by `delegate_id` through its delegate adapter (§7.3), and writes only that step's mirror, its attempt and the derived task state. It never runs a tool, reserves credits, creates an approval, writes the target or makes a provider request. The attempt still records `actor = created_by` (guard) and `authz_verdict = 'observe'`; 108 accepts that verdict only from cron on an `observes_external` step. Account-blocked and account-deletion workspaces are still never claimed.
- **inline:** the request's principal **must equal** `task.created_by` (the claim SQL enforces it). A decider who is not the creator never causes the creator's steps to run in the decider's request (§10.3).

### 6.2 Authorization on every claim (correction 3)

`verdict = authz.decide_for_step(cur, task, step, actor=Actor(kind, task.created_by, request_text=<the current human message only for an inline agent tool call, else "">, evidence=...))` runs **at every claim and every inline step start**, whatever the epochs say. It is pure and cheap; `Grants` may be cached by `token()`, and a changed token only invalidates the cache. The attempt records `authz_token`, `authz_verdict`, `authz_reason`; the task's `authz_token` is updated when it differs (`<>`).
- `allow` → execute.
- `observe` → the read-only observer poll (§6.1); nothing else runs.
- `approve` / `step_up` → `request_approval` (§10.1); the step becomes `awaiting_approval`; the attempt finishes `succeeded` with nothing executed.
- `deny` → `blocked` with the mapped reason (CF-2 §8.4); pending approvals of this task for that capability → `revoked` (system); the checkpoint → `discarded`; dependents wait.

### 6.3 The rest of the run

3. **Cancel check** before every non-READ effect and at each heartbeat.
4. **Target re-validation (correction 9):** every id in `target_refs`/`inputs` is re-resolved with `workspace_id = step.workspace_id`; a missing or foreign target → `blocked/target_changed`.
5. **Receipt guard:** a `done` receipt with the same digest replays its result; a different digest → `idempotency_conflict`.
6. **Execute** through the existing `tool_adapter.execute` with a worker `RafiiRunContext` bound to the step. No second tool path.
7. **Spend:** for paid steps, `Ledger.reserve(cur, ws, created_by, dimension, estimate, effect_key+':a'+n, run_id=task_id, job_id=attempt_id, meta={traceId, taskId, stepKey})`, after the task budget ceiling check (§9.3). Every `billing.reserve` stop still applies.
8. **Commit** receipt, compensation, step outputs and `progress.updated` events in one transaction with the domain command. **Verify** only from the executor's re-read.

**Lock order (frozen):** workspace row (`FOR UPDATE OF w`) → per-run event advisory lock → `pr_agent_tasks` row → `pr_agent_steps` → attempts, receipts, compensations. No transaction holds the workspace row across provider I/O (D-A8). Bookkeeping that may run while a request ends (heartbeat, checkpoint, terminal settle) uses a fresh connection that never grants anything new (`ui_stream._service_tx` pattern).

## 7. Step kinds and capability binding

### 7.1 Plan time (correction 9)

`task_plan` gains optional per-step `capability` and `inputs`, validated server-side. A step is `kind='tool'` only when the capability is registered, the inputs validate against its schema, `input_digest = sha256(canonical(capability_id, inputs))` is stored, and **every target id in `inputs` is in that turn's `ctx.ledger.known_ids ∪ ctx.chip_refs`** (recorded as `target_refs` and `planned_run_id`). `background_allowed` is set only when CF-1 `background_eligible` is true (R0 READ). Founder-tenant and native-only capabilities are refused. Without a capability a step is `kind='model'` and runs only through tool calls inside the owner's Manager turn; when a turn ends its unfinished `model` steps become `blocked/needs_conversation` ("Continue").

### 7.2 Context without a human message (correction 9)

Cron, continuation and retry contexts pass `request_text=""`, so `explicit_request` capabilities (the YouTube rule) deny there instead of replaying stale request text. A generic summary shows model-supplied strings only as labelled, quoted data.

### 7.3 Delegate adapters (EX-16; correction 13)

Read-only; each maps a target record to a step state, resolves `delegate_id` **only inside `step.workspace_id`**, runs with a 10 s timeout and `retry_class='auto'`, and never writes the target.

| `delegate_type` | Source of truth | completed when | failed when |
|---|---|---|---|
| `proposal` | `pr_messages` `siteAgent.proposals` | applied and `verify_applied` | dismissed / expired / superseded / failed |
| `publish_job` | publishing queue job (`store.py`; in-flight states at `store.py:22`) | `verified` | `failed` / `canceled`; `uncertain` stays running ("Rafii can't confirm yet") |
| `automation_item` | `lifecycle.py` item states | `published` / `scheduled` per goal | rejected / failed / approval_expired; platform_disconnected → blocked |
| `ui_action` | `pr_ui_actions.outcome` | `applied` + verified | rejected / conflict / failed |
| `ui_attempt` | `pr_ui_attempts.state` | `ready` | failed / canceled / interrupted (native fallback) |
| `library_job` | `pr_library_jobs.status` (#144, after merge) | completed / partial | failed / cancelled / blocked |
| `weekly_slot` | `coworker/weekly_operator.py` slot states | approved / scheduled | blocked states |
| `agent_task` | child `pr_agent_tasks.state` (same creator) | completed | failed / cancelled |

The provider receipt is the publish job's stored events: the engine copies `{jobId, state, providerAccepted, verifiedAt}` and never writes a receipt the queue did not record.

### 7.4 Continuation steps (EX-17)

A metered Manager run that resumes a task, created only by the creator's approval of a step whose task has an `sdk_run_state` checkpoint, or by the creator's explicit `POST tasks/{t}/continue`. `retry_class='manual'`, `timeout_seconds=200`, `max_turns=8`. It runs inline when the request has ≥ 215 s left; otherwise it stays queued and the task shows `needsMe.kind='continue'` to its creator. Never background in P0 (EX-D5 → P2 with budget ceiling and expiry).

## 8. Idempotency, receipts and duplicate prevention

### 8.1 Effect keys (EX-18)

`tool` step: `'tsk:' + task_id_hex32 + ':' + step_key + ':g' + generation`; a tool call inside a `model` step appends `':' + sha256(capability_id + '|' + input_digest)[:16]`; ledger key `effect_key + ':a' + attempt_no`. Stable across automatic reclaim (same generation), so a step that committed but crashed replays its receipt; it changes only on an explicit retry. `domain_tools.py` and `creative.py` switch to `ctx.effect_key(args)` when a step binding exists and keep their trace-based keys otherwise.

### 8.2 Receipt protocol (EX-19)

Inside the domain command's transaction: `SELECT … FOR UPDATE` the receipt (done + same digest → return it; different digest → 409 `idempotency_conflict`; absent → insert `pending`), run the command under a savepoint, re-read, mark `done`. `native_key` capabilities write the receipt right after the domain call. `result` holds only `checks[]`, `changedRefs[]`, `providerReceipt`, `costState`, `evidenceRefs[]`, `compensation{...}`, `cannotRecall[]` — never bodies, prompts or tokens. Audit rows carry `meta {taskId, stepKey, effectKey, traceId}`.

### 8.3 Five layers (EX-20; correction 11)

| Layer | Mechanism |
|---|---|
| L1 request | `unique (workspace_id, request_key)` with `request_digest = sha256(created_by, canonical payload)`. Same creator + same digest → the existing task (200, `deduplicated: true`); same creator + other digest → 409 `idempotency_conflict`; **another member** using the key → 409 `idempotency_conflict` that reveals nothing about the other task. (The critic's per-actor unique would let a replayed key silently create a parallel task instead of the required 409; the workspace-wide unique plus the creator in the digest gives both properties.) Creation uses `INSERT … ON CONFLICT DO NOTHING RETURNING`, then `SELECT`. The same rule applies to agent turns: `usage.request` stores the fingerprint with the principal, replacing the racy SELECT-then-INSERT (`service.py:113-128, 658`). |
| L2 intent | `pr_agent_tasks_dedupe (workspace_id, created_by, dedupe_key)` among open tasks for Task Center, recipe and opportunity origins. |
| L3 step | `unique (task_id, step_key)` + `pr_agent_step_attempts_one_live`. |
| L4 effect | `pr_agent_receipts` PK + domain keys (writing-run key, `Ledger.reserve` key, single-use proposal `proposal_closed`, `pr_ui_actions`). |
| L5 approval | `unique (workspace_id, proposal_id)`; `unique (workspace_id, decision_key)`: a repeated decide by the same decider returns the stored outcome; the key reused by anyone else → 409 `idempotency_conflict`. |

## 9. Timeouts, retries, budgets

### 9.1 Defaults (the registry may only lower `timeout_seconds` and `max_attempts`)

| Step | timeout | retry_class | max_attempts | Lease |
|---|---|---|---|---|
| R0 read tool | 20 s | auto | 3 | timeout + 30 s |
| R1 tool, `receipt_tx`/`native_key`, unpaid | 30 s | auto | 3 | timeout + 30 s |
| Paid generation (image, writing pipeline) | 180 s | manual | 1 | timeout + 30 s; heartbeat ≤ 20 s |
| R2 prepare | 30 s | manual | 1 | timeout + 30 s |
| `continuation` | 200 s | manual | 1 | 230 s |
| `delegate` poll | 10 s | auto | 5 consecutive read failures per wake; then defer ≥60 s | 40 s |
| `approval` | no attempt | — | — | `expires_at` = proposal TTL 24 h |
| `wait` | 10 s | auto | 3 | 40 s |

Delegate retry classification uses the consecutive failed polls since the most recent successful read, bounded by five per wake; cumulative `attempt_no` is identity only. A read failure never falsely marks a provider effect failed: after five failures the observer defers until the next wake, and only the target's final state or `hard_expires_at` closes it.

An inline step's deadline is `min(timeout, request deadline − 15 s)`. Provider calls keep `max_retries=0`; retries are only visible, counted engine attempts.

### 9.2 Backoff and classification (written out here; not copied from #144)

`delay = ceil(min(900, 30·2^(attempt−1)) · (1 + 0.25·rand))` seconds, then `max(delay, Retry-After capped at 3600 s)`. `retryable`/`timeout` → queued with backoff if `auto`, else failed; `conflict` (e.g. `workspace_revision_conflict`) → one immediate retry, then failed; `permission`/`revoked` → blocked (`permission_revoked`/`permission_missing`); `budget` → blocked (`budget`); `permanent`/`corrupt`/`unsupported` → failed; `cancelled` → cancelled; lease lost with no receipt on a `manual` step → `failed/outcome_unknown`, never re-run automatically.

### 9.3 Budgets (EX-22)

`attempts_left` starts at 24 per task and is decremented per non-delegate claim (0 → `failed/retry_budget_exhausted` for work steps; delegate observations remain claimable); at most 3 explicit retries per step (`generation ≤ 4`). Before a paid reserve, if `budget_ceiling_usd_micro` is set and `spent + estimate > ceiling`, the step is `blocked/budget_ceiling` and a `spend` approval is created; with no ceiling, the CF-2 verdict (spend confirmation) decides. `spent_usd_micro` changes only from settlements; any `unknown` settlement sets `spend_unknown`; unknown is never shown as zero.

## 10. Approvals: suspend and resume (corrections 2, 4, 17)

### 10.1 Suspend (EX-23)

`request_approval(cur, task, step, verdict, *, inputs, target_refs, summary, expires_at, proposal=None)` inserts a `pr_agent_approvals` row with `requested_for = task.created_by`, `authz_token`, `approver_policy`/`required_permission`/`requires_step_up` from the verdict, and moves the step to `awaiting_approval`. An E1 `confirm` outside an existing task attaches a step to the caller's open chat task in this conversation, or creates a one-step `origin='chat'` task (X1). When the Manager paused on `proposal_apply`, `RunState.to_json()` goes to a checkpoint bound to the approval ids.

| Kind | Digest | Summary | Expiry | Decider |
|---|---|---|---|---|
| `proposal` (`schedule_draft`, `reschedule_post`, `automation_change`) | the proposal digest | the proposal's own | the proposal's | `role_approve` (today) |
| `agent_action`, `spend` | `sha256(capability_id, input_digest, sorted target {type,id,revision}, risk, generation)` | server-built from the current record; model strings quoted | 24 h | `task_owner` only |
| `step_up_action` (R3) | same | server-built | 15 min | `task_owner`/`role_owner`, step-up 300 s |

### 10.2 `resolve_approval` — the one path for every surface (EX-24)

`resolve_approval(runtime, ws, token, *, approval_id | proposal_id, decision, digest, decision_key, surface)`:
1. Lock the approval row. Not visible to the caller (not the creator and not an approver-policy member) → 404 `approval_unavailable`. Not `pending`: the same decider with the same `decision_key` gets the stored outcome; otherwise 409 `approval_closed`. A `decision_key` already used by anyone else → 409 `idempotency_conflict`.
2. `surface in ('text','voice')` and the approval is not a legacy proposal type → turn result `needs_panel_confirmation`, **zero state change** (correction 17; also a CHECK in 108).
3. Past `expires_at` → `expired` (system, `decided_at`) → 409 `approval_expired`.
4. The client's `digest` differs from the stored one → 409 `approval_stale` (approval unchanged). A target revision drifted server-side → approval `revoked` (system), step `blocked/target_changed` → 409 `approval_stale`.
5. Approver policy (`permissions.py` classes): `task_owner` ⇒ caller is `created_by`; `role_approve` ⇒ approve class; `role_owner` ⇒ owner. Unsatisfied → 403 `approval_forbidden`. `requires_step_up` ⇒ `require_step_up(window=300)` → 403 `step_up_required`.
6. **Re-authorize the creator:** `decide_for_step(actor=Actor("approval", created_by, evidence={approvalId, digest}))`. Not allow → approval `revoked` (system), step blocked → 403 `agent_permission_revoked`.
7. **Apply.** Reject → `rejected`, step `cancelled/approval_rejected`. Approve: `proposal` → through the existing `approvals.decide(...)` (`approvals.py:136`, `site_agent/service.py` apply, re-read verified) under the decider's own approve right; the approval becomes `consumed`; the approval step `completed` if verified, else `failed`. `agent_action`/`spend` → approval `approved`; the gated step → `queued`.
8. **Continue** (§10.3), then respond `{approvalId, state, outcome, verified, checks, task: TaskRefV1 | TaskSummaryV1, resumed: 'inline'|'needs_continue'|'none', speakableSummary}`.

### 10.3 Who continues (correction 2, identical to CF-2 E7)

- **Decider is the creator:** the inline driver claims the queued gated step now (the approval → `consumed` at claim) if the request budget allows; then, if a checkpoint exists, the continuation runs inline (≥ 215 s left → `resumed:'inline'`) or waits for the creator's Continue (`resumed:'needs_continue'`).
- **Decider is not the creator** (possible for legacy proposals and role-owner step-up approvals under `role_approve`): the approved step completes; the continuation becomes `blocked/needs_input` with `needsMe.kind='continue'` **for the creator**; the response says `resumed:'none'`; the creator's model continuation never runs in the decider's request, nothing is reserved on the creator's credits there, and no continuation text or creator-private task detail is returned to the decider (`task` is a `TaskRefV1 {taskId, title, state}`).

| Surface | Entry |
|---|---|
| Panel ProposalCard / GenUI prepared action | legacy body `POST agent/approvals/decide` → `resolve_approval(proposal_id=…, surface='panel'\|'genui')`. **It now resumes the paused run for the creator** (fixes the panel never resuming). |
| Typed "yes/no" | `_decide_turn` (`service.py:244`) → `surface='text'`; legacy proposal types only. |
| Voice | same, `surface='voice'`; legacy proposal types only. |
| Task Center and the native approval card | `POST agent/approvals/{approvalId}/decide` → `surface='task_center'` (or `'panel'` from chat). |
| Notification | P1: deep link to the Task Center only; no one-tap approval in P0. |

Parity: button, text, voice and Task Center leave identical task, step and checkpoint state; a replay with the same key and digest applies once and resumes once.

### 10.4 R3

`kind='step_up_action'`, `requires_step_up`, 15-minute expiry, decider per verdict. The engine only observes: the action is the existing native endpoint, reached through Rafii's navigate/guide handoff with re-auth ≤ 5 min (DP-5); a delegate step reads the result.

## 11. Checkpoints (EX-25)

`_store_pending_run` writes `pr_agent_checkpoints(kind='sdk_run_state', payload, runtime_version=RUNTIME_VERSION (service.py:44), sdk_version, writer_model, approval_ids, expires_at = max(approval.expires_at))`. **In `shadow` the checkpoint is a copy:** `artifact.pendingRun` is still written exactly as today, because the authoritative legacy `_claim_pending_run`/`_resume_pending_run` (`service.py:1081, 1095`) read it there; the pending run is copied, never moved, until the workspace is `on`. **In `on`** `_store_pending_run` no longer writes `pr_agent_runs.artifact.pendingRun` (member-readable, fix 4), and adoption clears an existing `pendingRun` from the artifact in the same transaction that writes its checkpoint. Claim: `UPDATE … SET state='claimed', claimed_by, claim_expires_at=now()+230 s WHERE state='available' RETURNING payload` — nothing is deleted before the resume succeeds. A `runtime_version`/`sdk_version`/hash mismatch or expiry → `discarded/runtime_changed` and the deterministic "Done and checked" answer stands. Success → `consumed` with payload `{}`; failure → `discarded/resume_failed`; lease expiry mid-resume → back to `available` and the continuation `failed/outcome_unknown` with Continue offered (effects dedupe by effect key). Cap 1 MiB (over the cap, no checkpoint; deterministic path). Only the creator's request can claim a checkpoint.

## 12. Cancellation (EX-26; DP-10)

`POST agent/tasks/{task}/cancel {idempotencyKey, expectedVersion?, reason?≤200}`. **Authority: `created_by`, or an `owner`-class member** (DP-10); anyone else → 403 `task_forbidden`. In one transaction: set `cancel_requested_at/by`; `queued`, `awaiting_approval` and `blocked` steps → `cancelled/cancelled_by_person`, **except** an open `observes_external` step, which stays queued and keeps observing (§4.4); pending approvals → `superseded` (system); the checkpoint → `discarded/task_cancelled`; `cancel_running(only=<run ids of live attempts>)` and `ui_stream.cancel_presentation` for GenUI attempts of those runs. A model call already in flight is not aborted ("Rafii will stop after the current step; that step may still finish"); the running attempt checks cancel before every non-READ effect and at each heartbeat. Provider-accepted effects are not recalled; publish jobs follow the queue's own cancel rule, and an `observes_external` step keeps observing as the read-only observer (§4.4, §6.1), so the task stays open (not `cancelled`) until that job is final. The response's `stillRunning` lists such steps. Idempotent on a cancelled task (200, same body); 409 `task_terminal` on completed/failed. (The `ideas.cancel` actor guard is hotfix HF-1's, X8.)

## 13. Compensation and undo (EX-27)

For a `receipt_tx` R1 step whose capability names an inverse, `capture_compensation(...)` runs in the same transaction as the command, storing a pointer to the pre-image (for example a draft revision), never a copy of content. `POST agent/tasks/{task}/steps/{step}/undo {compensationId, idempotencyKey}` — **creator only** — runs the inverse as its own receipt (`'undo:' + effect_key`) with the original capability's permission: target digest ≠ `post_image_digest` → `conflict` → 409 `undo_conflict`; after `undo_until` → 409 `undo_expired`; success → `applied`, an event `stage='compensation'`. First inverses: `draft_edit` → restore the pre-edit revision as a new revision (the restore command must be built; `ui_domain/drafts.py` has the revisions query), the campaign link/unlink pair, trend watch create/disable, Library collection operations after #144 merges. Everything else records `compensation.available=false` with a reason; R2/R3 effects are never "undone" by Rafii. Default window 24 h (DP-13); the DDL ceiling is 7 days.

## 14. Revocation and authorization (EX-28; correction 3)

- **Every claim and inline start runs `decide_for_step`** (§6.2). There is no epoch comparison that could skip it.
- **In every work transaction** the cron `principal_repository` check and inline `ctx.workspace()` (CF-2 E2) re-decide inside the same transaction as the work → 403 `agent_permission_revoked` closes the check-then-act gap.
- **Paid two-phase steps** re-decide after the provider call and before derived results are written; on revocation nothing derived is written, the spend still settles, and the receipt lists `cannotRecall: ['sent_to_provider']`.
- **Push:** CF-2's revocation handler H3 `agent_tasks` runs in the revoking transaction: open steps whose capability is in `denied_now` → `blocked/permission_revoked`, their pending approvals → `revoked` (system), checkpoints → `discarded`; `next_wake_at=now()` on the person's other open tasks. On `membership_ended` the person's open tasks are cancelled (`cancelled_by_revocation`) except `observes_external` steps (the publish worker already holds jobs approved by removed members). Those keep polling as the read-only observer (§6.1) until the job is final or `hard_expires_at`, where they end `failed/outcome_unknown` with the job link; the observer never acts as the removed member.
- **Provider truth** (OAuth scopes, disconnects, the merged #138 YouTube fences) is re-read by `decide()` on every claim and by the domain commands' own readiness checks. The engine never repairs a connection: it shows `provider_disconnected` with the reconnect link and never starts OAuth.
- **Account state:** `accountBlock` and `accountDeletion` workspaces are never claimed (claim SQL); `hosted.py:113-133` refuses their transactions.

## 15. Recovery after navigation, and one client store (EX-29; correction 18)

The server needs no new transport: JSON polling with a cursor. Client contract in `web/src/lib/agent-runtime/`: on mount of `/app/agent/[conversationId]`, `GET conversations/{c}/active-run` (replay its events) and `GET conversations/{c}/state` for the caller's own task, then poll `GET tasks/{task}?cursor=<last seq>` — 2.5 s while running/queued, 10 s while awaiting approval/blocked, 30 s when hidden, stop at terminal. App-shell badge: `GET agent/tasks?view=needs_me&limit=5` every 30 s while visible. Deep link `/app/agent/{conversationId}?task={taskId}`; the `/app/tasks` page belongs to the P1 UX lane and joins both route-manifest twins.

**Proposed decision D-EX-1 (for J's A-DECISIONS):** PR #104 (open, head `fa6297b0`) adds the client live-run store `useLiveRunStore` (`web/src/features/notifications/live-state.ts`) and feeds it from `web/src/features/agent/use-run.ts`. EX-W6 adds **no second store**: it adds read hooks (`use-task-discovery.ts`) that report into #104's store, and waits for #104 to merge. If #104 is closed or still unmerged when EX-W6 is ready, J assigns that single store to EX-W6 at the same path and shape and #104 rebases onto it. Never both.

## 16. Observability and diagnostics

Correlation: HTTP `postriff.request_id` → `pr_agent_step_attempts.request_id`; `task.root_trace_id` → `attempt.trace_id` → SDK spans / `artifact.trace`; `attempt.run_id` → `pr_ui_artifacts.parent_run_id` → `pr_ui_attempts`; ledger `run_id = task id`, `job_id = attempt id`, `meta.traceId`; `pr_agent_receipts.effect_key` → `pr_audit_events.meta.{effectKey, traceId, taskId, stepKey}`; approvals `decision_key` → receipts/audit.

`progress.updated` stages on the anchor run (content-free; labels are the person's own plan text): `task_step` (existing shape), `task_state`, `step_attempt`, `approval`, `compensation`, `revocation`. If `MAX_EVENTS` (2000) is near, `step_attempt` events stop first. Logs (content-free JSON): `agent_task.created`, `.step_claimed`, `.step_finished`, `.step_reclaimed`, `.approval_requested|decided|expired`, `.cancelled`, `.revoked`, `.compensation_applied`, `.tick` (counts only), each with `traceId`, `taskId`, `stepKey`, `requestId`.

`GET agent/tasks/{task}/diagnostics` (creator or owner class; content-free): task `{taskId, rootTraceId, state, reasonCode, partial, version, authz:{tokenAtStart, currentToken, lastCheck:{stepKey, verdict, reasonCode, at}}}`, steps with attempts (no inputs), approvals `{approvalId, state, expiresAt, decisionSurface}`, checkpoint metadata (never the payload), ledger reservation ids/states (owner class only), `lastEventSeq`.

## 17. HTTP API for the Task Center (frozen)

All under `/api/workspaces/{w}/agent/`, session token only (`require_session_token`, `api_guard.py:5`), same Origin and guard checks, zero model calls on list/get/diagnostics. Error codes come only from CF-2 §13.1.

### 17.1 Routes

| Method & path | Body / query | 2xx | Errors |
|---|---|---|---|
| `GET tasks` | `view=open\|needs_me\|recent` (default `open`), `scope=mine\|workspace` (default `mine`; `workspace` needs the owner class), `limit` 1–50, `cursor` | `200 {items, nextCursor, counts:{open, needsMe}, asOf, engine:'enabled'\|'disabled'}` | `task_forbidden`; 400 on invalid query |
| `GET tasks/{task}?cursor=` (existing route) | — | `200 {task, events, cursor, engine}` — the first three keys unchanged; `engine` per §17.2 | `task_unavailable` |
| `POST tasks/{task}/cancel` | `{idempotencyKey, expectedVersion?, reason?}` | `200 {taskId, state, version, cancelledSteps[], stillRunning, supersededApprovals[], note}` | `task_unavailable`, `task_forbidden`, `task_conflict`, `task_terminal`, `idempotency_conflict` |
| `POST tasks/{task}/steps/{step}/retry` | `{idempotencyKey, expectedGeneration}` | `202 {taskId, stepKey, generation, state:'queued'\|'awaiting_approval', approvalId?, nextAttemptAt, runsInline}` | `step_unknown`, `step_not_retryable`, `retry_budget_exhausted`, `task_conflict`, `task_forbidden`, `agent_permission_denied`, `agent_permission_revoked`, `idempotency_conflict` |
| `POST tasks/{task}/continue` | `{idempotencyKey, modality?:'text'}` | `201`, the existing `POST turns` response (a turn bound to `taskId`, metered as a turn) | `task_terminal`, `task_forbidden`, `idempotency_conflict`, plus the turn route's errors |
| `POST approvals/{approvalId}/decide` (new, the one route) | `{decision:'approve'\|'reject', digest, idempotencyKey, timeZone?}` | `200 {approvalId, state, outcome, verified, checks, task, resumed:'inline'\|'needs_continue'\|'none', speakableSummary}` | `approval_unavailable`, `approval_closed`, `approval_expired`, `approval_stale`, `approval_forbidden`, `step_up_required`, `agent_permission_revoked`, `idempotency_conflict` |
| `POST approvals/decide` (existing legacy body) | unchanged `{conversationId, messageId, proposalId, digest, decision:'apply'\|'dismiss', timeZone?}` | unchanged response; internally `resolve_approval` | `proposal_closed`, `proposal_expired`, `proposal_stale`, `proposal_digest`, `approve_required`, `edit_required`, `owner_required` (unchanged), plus `agent_permission_revoked` in enforce mode |
| `POST tasks/{task}/steps/{step}/undo` | `{compensationId, idempotencyKey}` | `200 {outcome:'applied', verified, receipt, compensation:{state}}` | `undo_unavailable`, `undo_expired`, `undo_conflict`, `task_forbidden`, `idempotency_conflict` |
| `GET tasks/{task}/diagnostics` | — | §16 | `task_unavailable`, `task_forbidden` |

### 17.2 Visibility and permissions (DP-10, corrections 1 and 10)

| Caller | List | `GET tasks/{task}` `engine` block | cancel | retry / continue / undo | diagnostics |
|---|---|---|---|---|---|
| The task's creator | `scope=mine` (default) | full `TaskV1` | yes | yes | yes |
| Owner class (`permissions.CLASSES["owner"]`) | may use `scope=workspace`: `TaskSummaryV1` items without outputs, entities or receipts | full `TaskV1` | yes | **no** (creator only) | yes |
| A member who may decide one of its pending approvals | appears under `view=needs_me` as `TaskRefV1` | `{taskId, title, state, approvals:[that ApprovalV1]}` | no | no | no |
| Any other member | not listed | `{taskId, title, state}` | no | no | no |

The legacy keys (`task`, `events`, `cursor`) keep today's `read` requirement (`http.py:76-77`), but in mode `on` the `task` key is built per caller: the creator and the owner class get today's full shape (from the engine rows); every other member gets the redacted projection of §4.5 (steps without `outputs`, `entities`, `approvals` or `reason`). `events` are content-free `progress.updated` stages. Spend appears only for the owner class (the existing owner-only USD rule). `can.*` flags are computed per caller and never offer an action the caller cannot take.

**What correction 10 does and does not close.** It closes the task surfaces: the engine block, the legacy `task` key, and what the engine writes to the member-readable anchor. It does not hide the shared conversation itself: messages and the run trace in a workspace conversation stay visible to co-members as today, so an answer that quotes a step's result is still readable there. That is conversation privacy, DP-18 (deferred, CF-2 §12).

### 17.3 Shapes

```ts
type TaskState = 'queued'|'running'|'awaiting_approval'|'blocked'|'completed'|'failed'|'cancelled';
interface TaskRefV1 { taskId: string; title: string; state: TaskState }
interface TaskSummaryV1 extends TaskRefV1 {
  partial: boolean; reasonCode: string|null; version: number;
  origin: 'chat'|'voice'|'genui'|'task_center'|'recipe'|'opportunity'|'adopted';
  createdBy: { userId: string; isMe: boolean }; conversationId: string; parentTaskId: string|null;
  needsMe: null | { kind: 'approval'|'step_failed'|'blocked'|'continue'; approvalId?: string; stepKey?: string; reasonCode?: string };
  progress: { total: number; queued: number; running: number; awaitingApproval: number; blocked: number; completed: number; failed: number; cancelled: number };
  current: { stepKey: string; label: string; state: TaskState } | null;
  spend: { spentUsdMicro: number; unknown: boolean } | null;      // owner class only
  can: { cancel: boolean; retry: boolean; continue: boolean };
  nextWakeAt: string|null; expiresAt: string; createdAt: string; updatedAt: string; finishedAt: string|null;
  href: string;                                                    // /app/agent/{conversationId}?task={taskId}
}
interface StepV1 {
  stepKey: string; label: string; state: TaskState; legacyState: 'planned'|'running'|'done'|'needs_user'|'blocked'|'failed'|'canceled';
  kind: 'tool'|'model'|'approval'|'delegate'|'continuation'|'wait'; capabilityId: string|null; riskClass: 'R0'|'R1'|'R2'|'R3';
  dependsOn: string[]; waitingOn: string[]; attempts: number; maxAttempts: number; generation: number;
  retryClass: 'auto'|'manual'|'never'; nextAttemptAt: string|null; timeoutSeconds: number;
  reasonCode: string|null; reason: string|null; verified: boolean; outputs: unknown[]; entities: unknown[];
  delegate: { type: string; id: string; state: string; href: string|null } | null;
  undo: { compensationId: string; undoUntil: string } | null; can: { retry: boolean; undo: boolean };
}
interface ApprovalV1 {
  approvalId: string; stepKey: string; kind: 'proposal'|'agent_action'|'spend'|'step_up_action';
  proposalId: string|null; proposalType: string|null; conversationId: string|null; messageId: string|null;
  riskClass: 'R1'|'R2'|'R3'; digest: string; summary: Record<string, unknown>;      // server-built copy only
  requiredPermission: 'edit'|'approve'|'owner'; requiresStepUp: boolean; state: string; expiresAt: string;
  decidedAt: string|null; decisionSurface: string|null; can: { decide: boolean; why: string|null };
}
interface ReceiptV1 {
  effectKey: string; stepKey: string; capabilityId: string; outcome: 'applied'|'prepared'|'rejected'|'conflict'|'failed'|'unknown';
  verified: boolean|null; checks: {name: string; ok: boolean}[]; changedRefs: {type: string; id: string; change: string}[];
  providerReceipt: { kind: 'publish_job'; jobId: string; state: string; verifiedAt: string|null } | null;
  costState: 'none'|'known'|'unknown'|'estimated'; evidenceRefs: string[]; cannotRecall: string[];
  compensation: { available: boolean; compensationId?: string; undoUntil?: string; reason?: string }; at: string;
}
interface TaskV1 extends TaskSummaryV1 { autonomyMode: 'ask'|'assist'|'autopilot'; steps: StepV1[]; approvals: ApprovalV1[]; receipts: ReceiptV1[] }
```

Shapes and the error table are frozen in `tests/fixtures/agent_tasks/contracts/*.json` (lane A.2), mirrored by Python and TypeScript tests (the `tests/fixtures/agent_ui/contracts/` pattern). The cross-store Task Center projection (`GET agent/work`) is P1 and must reuse `needsMe`, `href` and `can`, acting only through existing endpoints.

## 18. Seams with sibling contracts

- **CF-2 (109):** owns `decide_for_step`, `Grants.token()`, the risk classes, autonomy, the "yes" and step-up rules, and the error table. No FK from 108 into 109, so 108 can ship first in shadow; until 109 lands a fallback adapter returns today's role check plus `ToolSpec.approval` as `approve` and a constant legacy token — exactly today's behaviour.
- **CF-1:** owns every per-capability field the engine reads; a CI test fails if a non-READ capability lacks `idempotency`/`retry_class`; a tool-count test guards against tools vanishing.
- **GenUI (GA-A):** presenter, library, prompts and contract hash `c4e2c3ae` untouched; `task_progress` keeps its shape via the legacy projection; `TaskPlan.conversation_id` makes the dead cross-conversation guard in `ui_domain/campaigns.py` live (a behaviour change needing GA-A's sign-off, X12); any new Task Center GenUI component goes through DP-1's gate.
- **Library (#144):** `pr_library_jobs` observed via `delegate_type='library_job'`; `pr_library_action_receipts` **stays** a domain receipt (X9; consolidation is post-GA cleanup agreed with the Library session); `leases.py` adoption is #144's choice after merge.
- **Notifications (#104):** "needs your approval" delivery is P1 through the existing catalogue; D-EX-1 governs the client store.
- **Founder tenant:** founder runs are out of scope; the engine refuses founder-tenant capabilities at plan time.

## 19. Reference journeys on the engine

**C (R1, first release candidate):** s1 R0 resolve on-screen ids (page context) → s2 `approval` (`agent_action`, server-built preview) under Ask, or no approval under Assist → s3 R1 `receipt_tx` with compensation (campaign link, draft edit) → s4 R0 verify by re-reading; Undo until `undo_until`. All inline in the owner's requests; no background claims.
**A (R2):** s1 R0 `library_browse` (truthful empty state) → s2..s4 R1 `draft_create` per platform (`native_key`; under Recommended a paid draft asks — SD-1) → s5 R1 campaign link → s6 R2 `schedule_propose` → s7 `approval` (proposal) → s8 `delegate` `publish_job` (needs DP-12 background polling; `uncertain` shown as such; exempt from expiry) → s9 R0 re-read.
**B (R2):** metric read (blocked `feature_unavailable` without admission) → evidence compile (`evidenceRefs`) → `model` recommendation → R2 `automation_change_propose` → `approval` → `delegate` `automation_item`.

All three work for an editor in a non-founder workspace (332ed6e6); viewers get R0 only.

## 20. Existing defects fixed by this lane

1. A panel/GenUI approval never resumes the paused run (`service.py:1267` vs the text path) → §10.2/§10.3.
2. `pendingRun` is popped before resume and lost on a crash (`service.py:1081`) → §11 claim states.
3. Confused deputy: resume runs under the approver (`service.py:1095`) → the creator continues (§10.3).
4. Paused model state in the member-readable artifact (`005:94-97`) → service-only checkpoints.
5. `RunState.from_json` has no version or expiry guard → `runtime_version`/`sdk_version`/`expires_at`.
6. Zombie tasks (expired proposals keep steps `needs_user`; `task:` excluded from reapers) → TTL + recovery.
7. The agent-turn reaper is lazy (`service.py:656`) → the recovery step calls it.
8. *(moved)* `ideas.cancel` actor guard → hotfix HF-1 (X8).
9. Turn idempotency has no fingerprint and races (`service.py:113-128, 658`) → L1 with the principal in the fingerprint.
10. Tool keys are trace-scoped (`domain_tools.py`, `creative.py:369, 388`) → effect keys.
11. `_resolve_task_steps` resolves only the newest active task → the approval row knows its task.
12. GenUI `task_progress` cross-conversation guard is dead → live (GA-A sign-off).
13. A task with failed steps ends `completed` → `failed` + `partial` (founder-lane notice).
14. **New:** another member's request could extend and execute a creator's task (`task_state.py:204-209`, correction 1) → per-person tasks end to end.

## 21. Flags, adoption, rollout, rollback

### 21.1 Flags (`agent_runtime_v2/config.py`, all requiring `RAFII_AGENT_V2_ENABLED`)

`RAFII_TASK_ENGINE_ENABLED` (store and shadow writes); `RAFII_TASK_ENGINE_AUTHORITATIVE` (the engine decides: API, inline attempts, approvals, receipts, checkpoints, recovery); `RAFII_TASK_ENGINE_BACKGROUND` (cron claims; **off in P0** until DP-12); `RAFII_TASK_ENGINE_WORKSPACES` (fail-closed: empty = no workspace; `*` explicit). `RuntimeConfig.task_engine_for(ws)` is:

| Mode | When | What it does |
|---|---|---|
| `off` | `ENABLED` off, or `ws` not in the allowlist | Nothing. Legacy `task_state` is authoritative; `GET tasks` returns `{items: [], engine:'disabled'}`. |
| `shadow` | `ENABLED` on, `ws` allowlisted, `AUTHORITATIVE` off | Engine rows are written **alongside** the legacy path, inside the same requests: tasks and steps mirror `task_state`, approvals mirror open proposals, the paused run is copied into a checkpoint. Every legacy behaviour is unchanged: `artifact.pendingRun` and `artifact.task` are written exactly as today, no legacy task or run status changes (no `task_superseded`, no anchor mirror), nothing is claimed, executed, expired, adopted by cron or recovered, and every response is today's. `GET tasks` still returns `engine:'disabled'`. |
| `on` | `ENABLED` and `AUTHORITATIVE` on, `ws` allowlisted | The engine is authoritative for that workspace (everything in this contract). |

Every adoption, recovery, expiry and claim path filters by this mode (the claim SQL carries the `engine_workspaces` predicate, §5.2). CF-2 enforce requires `on` in the same workspace.

### 21.2 Adoption (in code, no data migration; correction 1)

In a workspace in `shadow` or `on`, `task_state.load/active` adopts a `running` `task:` row: insert `pr_agent_tasks` (`origin='adopted'`, `created_by = pr_agent_runs.actor`) and its steps (legacy mapping §2), copy `pendingRun` into a checkpoint, create approval rows for proposals still open. Tasks of different actors are adopted separately, each to its own actor.
- **In `shadow`** adoption writes engine rows only. `pendingRun` stays in the artifact. When one conversation has several running legacy tasks of the same actor, only the newest gets an engine row (the per-person open-task index) and the older ones are left exactly as they are.
- **In `on`** adoption also clears `pendingRun` from the artifact and rewrites `artifact.task` as the redacted projection (§4.5). The older running legacy tasks of the same actor in that conversation close `failed/task_superseded`; this is the only adoption step that changes a legacy status, and it happens only in `on`.
- The recovery step adopts up to 50 rows per tick, in `on` workspaces only (§5.3).

### 21.3 Rollout and rollback

`shadow` on 332ed6e6, then 267f7d90 (engine rows written alongside; legacy authoritative and byte-for-byte unchanged, §21.1) → `on` on 332ed6e6 (ordinary users: owner dfestival.office, invited editor and viewer; non-founder proof per CF-2 §15) → `on` on 267f7d90 → 10 % → all. Rollback: `AUTHORITATIVE` off (back to `shadow`) or flags off; tables stay (additive, the 102 precedent); `artifact.task` is dual-written (redacted in `on`) so legacy readers keep working, without the step outputs; a paused run held only in a checkpoint (`on`) degrades to the deterministic answer (safe, not a lost effect); expired attempts are settled by the phase-1 rollback exception (§5.3).

## 22. Acceptance tests (all remote: `jcb test`/CI; PG tests in `tests/phase2/postgres_agent_task_engine.py` with real owner/editor/viewer roles, a second tenant and the founder)

1. **Crash recovery:** a kill between "domain committed" and "step finished" → the next recovery marks the step completed from its receipt with zero duplicate effects; a kill before commit → an auto step retries, a paid step becomes `failed/outcome_unknown` with the hold kept and zero automatic re-runs.
2. **Lease contention:** two ticks plus one inline request on one step → exactly one live attempt; the loser writes nothing.
3. **Approval parity:** button, text (legacy types), voice (legacy types) and Task Center leave identical states; a replay applies once and resumes once; an expired approval → `failed/approval_expired` within one tick.
4. **Resume safety (correction 2):** a kill during resume leaves the checkpoint `available` and Continue resumes it; a `RUNTIME_VERSION` bump → `discarded/runtime_changed`; **another member's approval completes the step and the owner continues**: `resumed:'none'`, no reservation on the owner, no continuation text in the decider's response, and the owner sees `needsMe.kind='continue'`.
5. **Cross-member isolation (correction 1):** B, in A's conversation, cannot add, advance, retry, continue, undo or decide-as-owner A's steps; B's `task_plan` creates B's own task; every executed attempt has `actor == created_by`.
6. **Revocation (correction 3):** revoking a scope while a 3-step task waits blocks the next step (`permission_revoked`), revokes its pending approval and discards the checkpoint; **disconnecting the provider between s1 and s2 blocks s2 (`provider_disconnected`) with zero epoch change**; demoting a member mid-step → `member_inactive`; an account block is never claimed. **Membership end with an `uncertain` publish job:** the member's other open steps cancel; the `publish_job` step keeps polling as the read-only observer (attempt `actor = created_by`, `authz_verdict = 'observe'`, no `principal_repository`, no reservation, no provider request); a later queue `verified` completes it; at `hard_expires_at` it ends `failed/outcome_unknown` with the job link.
7. **Background limits (correction 9):** the cron executor never claims an R1+ tool, `model` or `continuation` step; `explicit_request` capabilities deny in cron, continuation and retry contexts; a plan-time target outside `known_ids ∪ chip_refs` is refused; a target moved to another workspace blocks with `target_changed`.
8. **Duplicates (correction 11):** two concurrent identical `POST turns` → one run, no empty conversation; same key + other payload → 409; **another member's reuse of a key → 409 that reveals nothing**; two `task_plan` calls by one person in one conversation → one open task.
9. **Cancel (DP-10):** the creator and an owner can cancel; an editor co-member gets 403; queued and awaiting steps cancel immediately; the running step stops before its next non-READ effect; GenUI attempts of that run are cancelled. **Cancel with an `uncertain` publish job:** the observer step stays queued and is still claimed (claim SQL), the task is not `cancelled` while it is open, the polls do not decrement `attempts_left`, `stillRunning` lists it, and when the queue reports `verified` the step completes and the task ends `cancelled` with `partial = true`.
10. **Partial failure:** a non-retryable s2 failure cancels its dependents (`dependency_failed`), independent s3 completes, the task ends `failed` with `partial=true`.
11. **Undo:** restores the pre-image; an intervening edit → `undo_conflict`; expiry → `undo_expired`; a non-creator → 403.
12. **Navigation:** reload, another device and voice show the same state within one poll.
13. **Visibility (correction 10):** a co-member gets an `engine` block of `{taskId, title, state}` only, and a legacy `task` key whose steps carry no `outputs`, `entities`, `approvals` or `reason`; an authenticated co-member's direct `select` on the anchor `pr_agent_runs` row (PG, RLS, no service role) returns an `artifact.task` with none of those fields and no `pendingRun`; the seven engine tables return nothing to browser roles; a pending approval's decider gets only that approval; workspace scope omits outputs, entities and receipts; every route 404s for another workspace's ids; spend hidden from non-owners. The shared conversation's messages are out of scope (DP-18, §17.2).
14. **"Yes" (correction 17):** a typed or spoken "yes" against an `agent_action` approval returns `needs_panel_confirmation` with zero state change.
15. **External effects (correction 19):** a publish delegate in `uncertain` past `expires_at` is not cancelled and the task is not `cancelled`; at the hard cap it ends `failed/outcome_unknown` with the job link; a later queue `verified` is shown truthfully.
16. **Performance:** `GET tasks` p95 < 500 ms at 200 tasks per workspace; zero model calls on list, get and diagnostics.
17. **DDL:** `tests/phase2/postgres_agent_os_ddl.py` (this PR) — anchor/creator guard, per-person open-task index, composite keys, background CHECK and guard, approval CHECKs, no server DELETE, conversation cascade with SET NULL.
18. **GenUI:** the G03 matrix and `task_progress` shape unchanged in CI; DP-1's live gate before enforce on a GenUI workspace.
19. **Shadow is behaviour-preserving:** with the engine in `shadow`, a paused Manager run stores `artifact.pendingRun` as today and the legacy panel and text paths resume it exactly as with the engine `off`; two running legacy tasks of one actor in one conversation keep their statuses; the cron tick writes no row; every agent response is byte-identical to `off`. A workspace not in the allowlist is never adopted, recovered, expired or claimed.

## 23. Build plan (lane A.2; files in A's ownership per `A-DECISIONS.md`)

| WP | Scope | Files |
|---|---|---|
| EX-W1 | Migration 108 (J creates the file from this DDL); `leases.py` from merged `ui_store.py` semantics; `task_engine/store.py` (create, adopt per actor, derive, save + legacy projection); `task_state.active/latest` actor filter | `postriff_phase2/leases.py`, `agent_runtime_v2/task_engine/{__init__,store,views}.py`, `task_state.py` |
| EX-W2 | Approvals and checkpoints; the one `resolve_approval`; fixes 1–5, 11 | `task_engine/approvals.py`, `service.py` (decide, `_decide_turn`, pending-run functions; seams via J), `approvals.py` |
| EX-W3 | Inline driver; recovery step in `/api/cron/worker`; `/api/cron/agent-tasks` route (unscheduled); fixes 6–7 | `task_engine/{executor,cron}.py`, `hosted_app.py` (via J) |
| EX-W4 | Receipts, effect keys, compensation (campaign pair and draft restore first); fix 10 | `task_engine/{receipts,compensation}.py`, `domain_tools.py`, `creative.py`, the restore command |
| EX-W5 | HTTP API (cancel, retry, continue, undo, diagnostics, the approval route), visibility rules; fix 9 | `agent_runtime_v2/http.py` (J seam), `task_engine/http.py`, `service.py` (turn idempotency) |
| EX-W6 | Web client types and discovery hooks per D-EX-1 (no second store) | `web/src/lib/agent-runtime/{tasks.ts,use-task-discovery.ts,client.ts}`, `conversation-view.tsx` |
| EX-W7 | Contract fixtures (shapes and error codes), PG/unit/acceptance tests (§22) | `tests/fixtures/agent_tasks/contracts/`, `tests/test_agent_task_engine*.py`, `tests/phase2/postgres_agent_task_engine.py` |

EX-W1 lands first; EX-W2 and EX-W3 can run in parallel; EX-W4 needs CF-1's fields. No WP touches `ui_presenter.py`, `ui_contracts.py` or GenUI assets, so lanes C2/C3/D1 are unaffected.

## 24. Freeze checklist

- [x] Per-person tasks: index, `active()` filter, extension rule, adoption, inline identity, attempt/approval/receipt guards (correction 1).
- [x] One resume rule with CF-2 (correction 2).
- [x] `decide_for_step` on every claim; `authz_token` compared with `<>` (correction 3).
- [x] One approvals table, one route, one digest, system closes record `decided_at` (correction 4, X1).
- [x] Cron limited to R0/delegate/wait/recovery/expiry; plan-time target validation; empty request text outside human turns (correction 9).
- [x] Task visibility (correction 10, DP-10); idempotency 409 for another member (correction 11); composite keys and delegate scoping (correction 13).
- [x] Error codes only from CF-2 §13 (correction 16); "yes" only for legacy proposals (correction 17).
- [x] No duplicate infrastructure: `leases.py` from merged code, D-EX-1 for the client store, #144 receipts kept (correction 18, X9).
- [x] External-effect delegates exempt from expiry (correction 19), and from cancel and membership end: claim exemption, derive rule 1, the read-only observer and the `observe` verdict in 108 (review of #160).
- [x] Engine modes `off | shadow | on`; shadow copies `pendingRun` and changes no legacy state; every adoption, recovery and claim path carries the allowlist predicate (review of #160).
- [x] Redacted legacy projection in the member-readable anchor and a per-caller legacy `task` key; the conversation itself is DP-18 (review of #160).
- [ ] J records the freeze; GA-A signs off X12; the founder lane is told about `partial` tasks counting as `failed`.
