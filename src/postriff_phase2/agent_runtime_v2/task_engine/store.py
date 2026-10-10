"""The task engine's rows (migration 108): tasks, steps, attempts, approvals, receipts, compensations (CF-3 §3, §4, §8).

Every function takes a cursor inside a transaction the caller opened: a request transaction (`repository.transaction`,
which re-verifies the session and locks the workspace row) or a service bookkeeping transaction (`service_tx`, which
locks the workspace row and grants nothing new). Frozen lock order: workspace row → per-run event advisory lock →
pr_agent_tasks → pr_agent_steps → attempts / receipts / compensations / approvals. `lock_task` takes the first three.

Rows hold ids, states, reason codes and the person's own plan labels; never prompts, tokens or provider bodies.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError, uid

from ...agent_runtime import safe_event
from ...contracts import digest as content_digest
from . import errors, model

log = logging.getLogger("postriff.agent_tasks")
ANCHOR_PREFIX = "task:"
TASK_MODEL = "rafii-task"
ANCHOR_EPOCH = content_digest({"taskState": 1})          # = task_state.EPOCH (the anchor row's existing policy_epoch value)
EVENT_SOFT_LIMIT = 1900                                     # step_attempt events stop first near MAX_EVENTS (2000)

TASK_COLUMNS = ("t.id::text,t.workspace_id::text,t.conversation_id::text,t.parent_task_id::text,t.created_by::text,t.origin,t.title,t.state,"
                "t.partial,t.reason_code,t.version,t.autonomy_mode,t.authz_token,t.budget_ceiling_usd_micro,t.spent_usd_micro,t.spend_unknown,"
                "t.attempts_left,t.request_key,t.request_digest,t.root_trace_id,extract(epoch from t.cancel_requested_at),t.cancel_requested_by::text,"
                "extract(epoch from t.next_wake_at),extract(epoch from t.expires_at),extract(epoch from t.hard_expires_at),"
                "extract(epoch from t.created_at),extract(epoch from t.updated_at),extract(epoch from t.finished_at)")
_TASK_KEYS = ("taskId", "workspaceId", "conversationId", "parentTaskId", "createdBy", "origin", "title", "state", "partial", "reasonCode", "version",
              "autonomyMode", "authzToken", "budgetCeilingUsdMicro", "spentUsdMicro", "spendUnknown", "attemptsLeft", "requestKey", "requestDigest",
              "rootTraceId", "cancelRequestedAt", "cancelRequestedBy", "nextWakeAt", "expiresAt", "hardExpiresAt", "createdAt", "updatedAt", "finishedAt")
STEP_COLUMNS = ("s.id::text,s.task_id::text,s.workspace_id::text,s.step_key,s.label,s.kind,s.capability_id,s.capability_version,s.risk_class,s.effect,"
                "s.background_allowed,s.depends_on,s.inputs,s.input_digest,s.target_refs,s.planned_run_id::text,s.state,s.reason_code,s.reason,s.verified,"
                "s.retry_class,s.max_attempts,s.attempts,s.generation,s.timeout_seconds,extract(epoch from s.next_attempt_at),s.effect_key,s.delegate_type,"
                "s.delegate_id,s.observes_external,extract(epoch from s.wait_until),s.outputs,s.entities,extract(epoch from s.started_at),"
                "extract(epoch from s.finished_at),extract(epoch from s.created_at),extract(epoch from s.updated_at)")
_STEP_KEYS = ("stepId", "taskId", "workspaceId", "stepKey", "label", "kind", "capabilityId", "capabilityVersion", "riskClass", "effect",
              "backgroundAllowed", "dependsOn", "inputs", "inputDigest", "targetRefs", "plannedRunId", "state", "reasonCode", "reason", "verified",
              "retryClass", "maxAttempts", "attempts", "generation", "timeoutSeconds", "nextAttemptAt", "effectKey", "delegateType", "delegateId",
              "observesExternal", "waitUntil", "outputs", "entities", "startedAt", "finishedAt", "createdAt", "updatedAt")
APPROVAL_COLUMNS = ("a.id::text,a.workspace_id::text,a.task_id::text,a.step_id::text,a.generation,a.requested_for::text,a.kind,a.proposal_id,a.proposal_type,"
                    "a.conversation_id::text,a.message_id::text,a.run_id::text,a.capability_id,a.risk_class,a.confirmation,a.input_digest,a.inputs,"
                    "a.target_refs,a.digest,a.summary,a.required_permission,a.approver_policy,a.requires_step_up,a.authz_token,a.state,"
                    "extract(epoch from a.expires_at),a.decided_by::text,extract(epoch from a.decided_at),a.decision_surface,a.decision_key,"
                    "a.decision_outcome,extract(epoch from a.consumed_at),extract(epoch from a.created_at)")
_APPROVAL_KEYS = ("approvalId", "workspaceId", "taskId", "stepId", "generation", "requestedFor", "kind", "proposalId", "proposalType", "conversationId",
                  "messageId", "runId", "capabilityId", "riskClass", "confirmation", "inputDigest", "inputs", "targetRefs", "digest", "summary",
                  "requiredPermission", "approverPolicy", "requiresStepUp", "authzToken", "state", "expiresAt", "decidedBy", "decidedAt",
                  "decisionSurface", "decisionKey", "decisionOutcome", "consumedAt", "createdAt")


def _f(value):
    return float(value) if value is not None else None


def _task(row) -> dict:
    task = dict(zip(_TASK_KEYS, row))
    for key in ("cancelRequestedAt", "nextWakeAt", "expiresAt", "hardExpiresAt", "createdAt", "updatedAt", "finishedAt"):
        task[key] = _f(task[key])
    return task


def _step(row) -> dict:
    step = dict(zip(_STEP_KEYS, row))
    for key in ("nextAttemptAt", "waitUntil", "startedAt", "finishedAt", "createdAt", "updatedAt"):
        step[key] = _f(step[key])
    step["dependsOn"] = list(step["dependsOn"] or [])
    step["outputs"] = list(step["outputs"] or [])
    step["entities"] = list(step["entities"] or [])
    step["targetRefs"] = list(step["targetRefs"] or [])
    return step


def _approval(row) -> dict:
    item = dict(zip(_APPROVAL_KEYS, row))
    for key in ("expiresAt", "decidedAt", "consumedAt", "createdAt"):
        item[key] = _f(item[key])
    item["summary"] = item["summary"] or {}
    item["targetRefs"] = list(item["targetRefs"] or [])
    return item


# --- transactions --------------------------------------------------------------------------------------------------------
@contextmanager
def service_tx(service, workspace_id: str, *, skip_locked: bool = False):
    """Bookkeeping that must not depend on the caller's session still being valid (a finished attempt, recovery, expiry):
    a fresh connection, the workspace row locked first (frozen lock order), committed on success. Grants nothing new.
    With skip_locked, yields None when a request holds the workspace (the next tick retries)."""
    factory = service.repository.connection_factory
    db = factory()
    try:
        cur = db.cursor()
        cur.execute("SELECT 1 FROM public.pr_workspaces WHERE id=%s FOR UPDATE" + (" SKIP LOCKED" if skip_locked else ""), (workspace_id,))
        held = cur.fetchone() is not None
        yield cur if held else None
        db.commit()
    except BaseException:
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


def lock_task(cur, ideas, workspace_id: str, task_id: str) -> dict | None:
    """Event lock of the anchor run, then the task row (frozen order after the workspace row)."""
    if not _uuid(task_id):
        return None
    ideas._lock_run_events(cur, workspace_id, task_id)
    cur.execute(f"SELECT {TASK_COLUMNS} FROM public.pr_agent_tasks t WHERE t.id::text=%s AND t.workspace_id=%s FOR UPDATE", (task_id, workspace_id))
    row = cur.fetchone()
    return _task(row) if row else None


def _uuid(value) -> bool:
    text = str(value or "")
    return len(text) == 36 and text.count("-") == 4 and all(c in "0123456789abcdefABCDEF-" for c in text)


def load_task(cur, workspace_id: str, task_id: str) -> dict | None:
    if not _uuid(task_id):
        return None
    cur.execute(f"SELECT {TASK_COLUMNS} FROM public.pr_agent_tasks t WHERE t.id::text=%s AND t.workspace_id=%s", (task_id, workspace_id))
    row = cur.fetchone()
    return _task(row) if row else None


def load_steps(cur, workspace_id: str, task_id: str, *, lock: bool = False) -> list[dict]:
    cur.execute(f"SELECT {STEP_COLUMNS} FROM public.pr_agent_steps s WHERE s.task_id::text=%s AND s.workspace_id=%s "
                "ORDER BY substring(s.step_key from 2)::int" + (" FOR UPDATE" if lock else ""), (task_id, workspace_id))
    return [_step(r) for r in cur.fetchall()]


def load_step(cur, workspace_id: str, task_id: str, step_key: str, *, lock: bool = False) -> dict | None:
    if not model.valid_step_key(step_key):
        return None
    cur.execute(f"SELECT {STEP_COLUMNS} FROM public.pr_agent_steps s WHERE s.task_id::text=%s AND s.workspace_id=%s AND s.step_key=%s"
                + (" FOR UPDATE" if lock else ""), (task_id, workspace_id, step_key))
    row = cur.fetchone()
    return _step(row) if row else None


def facts(steps: list[dict]) -> list[model.StepFacts]:
    return [model.StepFacts(key=s["stepKey"], state=s["state"], kind=s["kind"], depends_on=tuple(s["dependsOn"]), reason_code=s["reasonCode"],
                            retry_class=s["retryClass"], generation=int(s["generation"]), observes_external=bool(s["observesExternal"])) for s in steps]


def emit(cur, ideas, task: dict, stage: str, **body) -> None:
    """A content-free progress.updated event on the anchor run (§16). Never fails the transition it reports."""
    from . import flags
    if not flags.enabled_for(task["workspaceId"]):
        return
    body = {k: v for k, v in body.items() if k not in ("reason", "outputs", "entities", "approvals", "receipt", "payload")}
    try:
        if stage == "step_attempt":
            cur.execute("SELECT coalesce(max(seq),0) FROM public.pr_agent_events WHERE run_id::text=%s", (task["taskId"],))
            if cur.fetchone()[0] >= EVENT_SOFT_LIMIT:
                return
        ideas._insert_event(cur, task["workspaceId"], task["taskId"], safe_event("progress.updated", stage=stage, taskId=task["taskId"], **body))
    except AlphaError:
        pass   # the event log is full: the state change still stands (the task row is the authority)


def log_event(name: str, **fields) -> None:
    """One content-free JSON log line (ids, states and counts only)."""
    safe = {k: v for k, v in fields.items() if isinstance(v, (str, int, float, bool)) or v is None}
    log.info(json.dumps({"event": f"agent_task.{name}", **safe}, default=str))


# --- derivation, the anchor mirror and the legacy projection (EX-6, EX-9) -------------------------------------------------
_ANCHOR_STATUS = {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}


def refresh(cur, ideas, task: dict, steps: list[dict] | None = None, *, extend_expiry: bool = False) -> dict:
    """Derive the task's state from its steps and save it with the anchor mirror (caller holds the task row lock)."""
    steps = load_steps(cur, task["workspaceId"], task["taskId"]) if steps is None else steps
    state, reason, partial = model.derive(facts(steps), cancel_requested=task["cancelRequestedAt"] is not None, attempts_left=int(task["attemptsLeft"]))
    wake = min((s["nextAttemptAt"] for s in steps if s["state"] == "queued" and s["nextAttemptAt"] is not None), default=None)
    changed = (state, reason, bool(partial)) != (task["state"], task["reasonCode"], bool(task["partial"]))
    cur.execute("UPDATE public.pr_agent_tasks SET state=%s,reason_code=%s,partial=%s,version=version+%s,updated_at=now(),"
                "finished_at=CASE WHEN %s THEN coalesce(finished_at,now()) ELSE NULL END,"
                "next_wake_at=CASE WHEN %s THEN NULL ELSE to_timestamp(%s::float8) END,"
                "expires_at=CASE WHEN %s THEN least(hard_expires_at, now()+make_interval(secs => %s)) ELSE expires_at END "
                f"WHERE id::text=%s AND workspace_id=%s RETURNING {TASK_COLUMNS.replace('t.', '')}",
                (state, reason, bool(partial), 1 if changed else 0, state in model.TERMINAL_STATES, state in model.TERMINAL_STATES or wake is None,
                 wake, bool(extend_expiry), model.TTL_SECONDS, task["taskId"], task["workspaceId"]))
    updated = _task(cur.fetchone())
    mirror_anchor(cur, updated, steps)
    if changed:
        emit(cur, ideas, updated, "task_state", state=state, reasonCode=reason, partial=bool(partial), version=updated["version"])
        log_event("state", taskId=updated["taskId"], state=state, reasonCode=reason, partial=bool(partial), traceId=updated["rootTraceId"])
    return updated


def mirror_anchor(cur, task: dict, steps: list[dict]) -> None:
    """pr_agent_runs.status and artifact.task for old readers (task_state.active, active_run, the founder projection)."""
    from . import flags
    if not flags.enabled_for(task["workspaceId"]):
        return
    cur.execute("SELECT artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (task["taskId"], task["workspaceId"]))
    row = cur.fetchone()
    if not row:
        return
    artifact = row[0] or {}
    previous = artifact.get("task") if isinstance(artifact.get("task"), dict) else {}
    approvals = proposal_ids_by_step(cur, task["workspaceId"], task["taskId"])
    artifact["task"] = projection(task, steps, previous, approvals)
    status = _ANCHOR_STATUS.get(task["state"], "running")
    artifact.pop("pendingRun", None)
    cur.execute("UPDATE public.pr_agent_runs SET artifact=%s::jsonb,status=%s,updated_at=now() WHERE id::text=%s AND workspace_id=%s",
                (json.dumps(artifact, ensure_ascii=False, default=str), status, task["taskId"], task["workspaceId"]))


def projection(task: dict, steps: list[dict], previous: dict, approvals: dict | None = None) -> dict:
    """TaskPlan v1's artifact.task: the Manager's own steps as the plan wrote them; engine steps from the engine rows, flagged
    `engine: true` so the legacy plan never changes them."""
    # The anchor is member-readable. Keep execution details exclusively in service-only rows.
    out = [{"id": step["stepKey"], "label": step["label"],
            "state": model.legacy_state(step["state"], step["reasonCode"]),
            "kind": step["capabilityId"] or step["kind"], "dependsOn": list(step["dependsOn"]),
            "verified": bool(step["verified"]), "startedAt": step["startedAt"], "updatedAt": step["updatedAt"],
            **({"engine": True} if step["kind"] != "model" else {})} for step in steps]
    return {"title": task["title"], "version": int(previous.get("version") or 0), "createdBy": task["createdBy"], "steps": out}



def private_projection(cur, task: dict, steps: list[dict], previous: dict | None = None) -> dict:
    out = projection(task, steps, previous or {})
    approvals = proposal_ids_by_step(cur, task["workspaceId"], task["taskId"])
    by_key = {s["stepKey"]: s for s in steps}
    for item in out["steps"]:
        step = by_key[item["id"]]
        item.update(outputs=list(step["outputs"]), entities=list(step["entities"]),
                    approvals=approvals.get(step["stepKey"], []), reason=step["reason"])
    return out

def proposal_ids_by_step(cur, workspace_id: str, task_id: str) -> dict:
    cur.execute("SELECT s.step_key, a.proposal_id FROM public.pr_agent_approvals a JOIN public.pr_agent_steps s ON s.id=a.step_id "
                "WHERE a.task_id::text=%s AND a.workspace_id=%s AND a.proposal_id IS NOT NULL ORDER BY a.created_at", (task_id, workspace_id))
    found: dict = {}
    for key, proposal_id in cur.fetchall():
        found.setdefault(key, []).append(proposal_id)
    return found


# --- creation (L1, L2, L3) ------------------------------------------------------------------------------------------------
def new_anchor(cur, ideas, workspace_id: str, conversation_id: str, actor: str, title: str, trace_id: str) -> str:
    """The `task:` pr_agent_runs row a task is anchored on (same shape as task_state.create)."""
    task_key = ANCHOR_PREFIX + uid()
    cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                "VALUES(%s,%s,%s,'running',%s,'standard',%s,%s,%s,%s::jsonb) RETURNING id::text",
                (conversation_id, workspace_id, actor, TASK_MODEL, content_digest({"title": title, "trace": trace_id}), ANCHOR_EPOCH, task_key,
                 json.dumps({"task": {"title": title, "version": 0, "createdBy": actor, "traceIds": [trace_id], "steps": []}})))
    anchor_id = cur.fetchone()[0]
    ideas._insert_event(cur, workspace_id, anchor_id, safe_event("run.started", agent="task", model=TASK_MODEL, reasoning="standard", traceId=trace_id))
    return anchor_id


def _request_key(value) -> str:
    key = str(value or "")
    if not (16 <= len(key) <= 120) or any(c.isspace() for c in key):
        raise AlphaError("Send an idempotency key of 16 to 120 characters.", 400, code="tool_input")
    return key


def existing_request(cur, workspace_id: str, request_key: str, created_by: str, request_digest: str) -> dict | None:
    """L1: same creator + same digest → that task; anything else under the key → 409 that reveals nothing about it."""
    cur.execute("SELECT id::text,created_by::text,request_digest FROM public.pr_agent_tasks WHERE workspace_id=%s AND request_key=%s",
                (workspace_id, request_key))
    row = cur.fetchone()
    if not row:
        return None
    if row[1] != str(created_by) or row[2] != request_digest:
        raise errors.error("idempotency_conflict")
    return load_task(cur, workspace_id, row[0])


def create_task(cur, ideas, *, workspace_id: str, conversation_id: str, created_by: str, origin: str, title: str, request_key: str, payload,
                steps: list[dict], trace_id: str, anchor_id: str | None = None, dedupe_key: str | None = None, parent_task_id: str | None = None,
                autonomy_mode: str = "ask", authz_token: str | None = None, budget_ceiling_usd_micro: int | None = None) -> tuple[dict, bool]:
    """Create a task with its steps, or return the one this creator already made with this key (deduplicated=True)."""
    if origin not in model.ORIGINS:
        raise ValueError("unknown task origin")
    title = model.clip(title, 140) or "Task"
    request_key = _request_key(request_key)
    request_digest = model.request_digest(created_by, payload)
    found = existing_request(cur, workspace_id, request_key, created_by, request_digest)
    if found is not None:
        return found, True
    if dedupe_key:
        cur.execute("SELECT id::text FROM public.pr_agent_tasks WHERE workspace_id=%s AND created_by=%s AND dedupe_key=%s "
                    "AND state IN ('queued','running','awaiting_approval','blocked')", (workspace_id, created_by, dedupe_key))
        open_one = cur.fetchone()
        if open_one:
            return load_task(cur, workspace_id, open_one[0]), True
    from . import authz_seam
    token = authz_token or authz_seam.legacy_token(authz_seam.membership(cur, workspace_id, created_by))
    cur.execute("SAVEPOINT agent_task_create")
    try:
        anchor = anchor_id or new_anchor(cur, ideas, workspace_id, conversation_id, created_by, title, trace_id)
        cur.execute("INSERT INTO public.pr_agent_tasks(id,workspace_id,conversation_id,parent_task_id,created_by,origin,title,autonomy_mode,authz_token,"
                    "budget_ceiling_usd_micro,attempts_left,request_key,request_digest,dedupe_key,root_trace_id,expires_at,hard_expires_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs => %s),now()+make_interval(secs => %s)) "
                    "ON CONFLICT (workspace_id, request_key) DO NOTHING RETURNING id::text",
                    (anchor, workspace_id, conversation_id, parent_task_id, created_by, origin, title, autonomy_mode, token, budget_ceiling_usd_micro,
                     model.TASK_ATTEMPTS, request_key, request_digest, dedupe_key, trace_id, model.TTL_SECONDS, model.HARD_TTL_SECONDS))
        row = cur.fetchone()
    except Exception as error:  # noqa: BLE001 — the open-task index or a guard refused it: nothing of this attempt remains
        cur.execute("ROLLBACK TO SAVEPOINT agent_task_create")
        if getattr(error, "sqlstate", None) == "23505":
            raise errors.error("task_conflict", "You already have an open task in this conversation.") from None
        raise
    if not row:
        cur.execute("ROLLBACK TO SAVEPOINT agent_task_create")
        found = existing_request(cur, workspace_id, request_key, created_by, request_digest)
        if found is None:
            raise errors.error("task_conflict")
        return found, True
    cur.execute("RELEASE SAVEPOINT agent_task_create")
    task = load_task(cur, workspace_id, row[0])
    ideas._lock_run_events(cur, workspace_id, task["taskId"])
    add_steps(cur, task, steps)
    task = refresh(cur, ideas, task)
    emit(cur, ideas, task, "task_created", origin=origin, steps=len(steps))
    log_event("created", taskId=task["taskId"], origin=origin, steps=len(steps), traceId=trace_id)
    return task, False


def add_steps(cur, task: dict, specs: list[dict]) -> list[dict]:
    """Validate and insert steps (L3: unique (task_id, step_key)). Raises 400 on an invalid plan; nothing runs by planning."""
    existing = load_steps(cur, task["workspaceId"], task["taskId"])
    keys = [s["stepKey"] for s in existing]
    if len(existing) + len(specs) > model.MAX_STEPS:
        raise errors.error("task_too_long")
    rows, specs_by_key = [], {}
    for spec in specs:
        key = spec.get("key") or f"s{len(keys) + 1}"
        if not model.valid_step_key(key) or key in keys:
            raise AlphaError("Steps are numbered s1 to s12, each once.", 400, code="tool_input")
        row = build_step(task, spec, key, keys)
        keys.append(key)
        rows.append(row)
        specs_by_key[key] = spec
    known = {s["stepKey"]: s for s in existing} | {r["stepKey"]: r for r in rows}
    for row in rows:
        if row["kind"] == "approval":
            bind_approval_step(row, specs_by_key[row["stepKey"]], known)
    created = []
    for row in rows:
        cur.execute("INSERT INTO public.pr_agent_steps(task_id,workspace_id,step_key,label,kind,capability_id,capability_version,risk_class,effect,"
                    "background_allowed,depends_on,inputs,input_digest,target_refs,planned_run_id,state,reason_code,reason,verified,retry_class,max_attempts,"
                    "generation,timeout_seconds,next_attempt_at,effect_key,delegate_type,delegate_id,wait_until,outputs,entities,started_at,finished_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,1,%s,to_timestamp(%s::float8),%s,%s,%s,to_timestamp(%s::float8),"
                    "%s::jsonb,%s::jsonb,CASE WHEN %s THEN now() END,CASE WHEN %s THEN now() END) RETURNING id::text",
                    (task["taskId"], task["workspaceId"], row["stepKey"], row["label"], row["kind"], row["capabilityId"], row["capabilityVersion"],
                     row["riskClass"], row["effect"], row["backgroundAllowed"], row["dependsOn"],
                     json.dumps(row["inputs"]) if row["inputs"] is not None else None, row["inputDigest"], json.dumps(row["targetRefs"]),
                     row["plannedRunId"], row["state"], row["reasonCode"], row["reason"], row["verified"], row["retryClass"], row["maxAttempts"],
                     row["timeoutSeconds"], row["nextAttemptAt"], row["effectKey"], row["delegateType"], row["delegateId"], row["waitUntil"],
                     json.dumps(row["outputs"]), json.dumps(row["entities"]), row["state"] == "running", row["state"] in model.TERMINAL_STATES))
        created.append(cur.fetchone()[0])
    return created


BACKGROUND_READS = frozenset({
    # R0 workspace reads with no provider call and no egress: the only tool steps the cron executor may claim (correction 9).
    "workspace_summary", "queue_summary", "publishing_summary", "calendar_range", "campaign_get", "campaign_items", "campaign_list",
    "campaign_membership", "draft_get", "job_get", "entity_status", "pending_approvals", "reviews_list", "notification_list", "automation_get",
    "automation_list", "channels_capabilities", "entitlements_summary", "image_list", "record_attribution", "relationships", "attention_summary",
})
SUPPORTED_DELEGATES = model.DELEGATE_TYPES
RECEIPT_TX: set = {"campaign_link", "campaign_unlink", "draft_edit"}      # capabilities whose executor commits the engine receipt in its own domain transaction (receipts.commit_in)


def build_step(task: dict, spec: dict, key: str, earlier: list[str]) -> dict:
    kind = spec.get("kind") or ("tool" if spec.get("capabilityId") else "model")
    if kind not in model.KINDS or kind == "continuation":
        raise AlphaError("Unknown step kind.", 400, code="tool_input")
    label = model.clip(spec.get("label"), 140)
    if not label:
        raise AlphaError("Name the step.", 400, code="step_label")
    depends = list(dict.fromkeys(d for d in (spec.get("dependsOn") or []) if isinstance(d, str)))
    if any(d not in earlier for d in depends):
        raise AlphaError("A step depends only on earlier steps.", 400, code="tool_input")
    row = {"stepKey": key, "label": label, "kind": kind, "capabilityId": None, "capabilityVersion": None, "riskClass": "R0", "effect": "READ",
           "backgroundAllowed": False, "dependsOn": depends, "inputs": None, "inputDigest": None, "targetRefs": _targets(spec.get("targetRefs")),
           "plannedRunId": spec.get("plannedRunId") if _uuid(spec.get("plannedRunId")) else None, "state": spec.get("state") or "queued",
           "reasonCode": spec.get("reasonCode"), "reason": model.clip(spec.get("reason"), 300), "verified": bool(spec.get("verified")),
           "retryClass": "never", "maxAttempts": 1, "timeoutSeconds": 30, "nextAttemptAt": time.time() if kind in ("tool", "approval", "delegate") else None, "effectKey": None, "delegateType": None,
           "delegateId": None, "waitUntil": None, "outputs": list(spec.get("outputs") or [])[:20], "entities": list(spec.get("entities") or [])[:20]}
    if row["state"] not in model.STATES:
        raise AlphaError("Unknown step state.", 400, code="tool_input")
    if kind == "tool":
        from .. import domain_tools, tool_adapter
        domain_tools.ensure_registered()
        capability = spec.get("capabilityId")
        tool = tool_adapter.REGISTRY.get(capability or "") if model.valid_capability(capability) else None
        if tool is None or tool.spec.tenant != "workspace":
            raise AlphaError("That capability isn't available to Rafii's tasks.", 400, code="tool_input")
        if tool.spec.effect not in ("READ", "CREATE_DRAFT", "MUTATE_REVERSIBLE") or tool.spec.approval:
            # R2 prepares a proposal stored on an answer: it runs inside the Manager's own turn (a `model` step), never here.
            raise AlphaError("That capability runs only inside a conversation turn.", 400, code="tool_input")
        inputs = spec.get("inputs") if isinstance(spec.get("inputs"), dict) else {}
        if "stepId" in inputs or len(json.dumps(inputs, default=str)) > 16000:
            raise AlphaError("Invalid tool input.", 400, code="tool_input")
        tool_adapter._check_schema(tool.schema, inputs)     # 400 tool_input when the inputs don't validate (never at run time)
        risk = model.EFFECT_RISK[tool.spec.effect]
        paid = capability in model.PAID_CAPABILITIES
        rules = model.defaults("tool", risk, paid=paid, receipt_tx=capability in RECEIPT_TX)
        background = bool(spec.get("background")) and risk == "R0" and capability in BACKGROUND_READS
        row.update({"capabilityId": capability, "capabilityVersion": 1, "riskClass": risk, "effect": tool.spec.effect, "backgroundAllowed": background,
                    "inputs": inputs, "inputDigest": model.input_digest(capability, inputs), "retryClass": rules.retry_class,
                    "maxAttempts": max(1, min(rules.max_attempts, int(spec.get("maxAttempts") or rules.max_attempts))),
                    "timeoutSeconds": max(5, min(rules.timeout_seconds, int(spec.get("timeoutSeconds") or rules.timeout_seconds))),
                    "effectKey": model.effect_key(task["taskId"], key, 1) if tool.spec.effect != "READ" else None})
    elif kind == "delegate":
        delegate = spec.get("delegate") if isinstance(spec.get("delegate"), dict) else {}
        if delegate.get("type") not in SUPPORTED_DELEGATES or not isinstance(delegate.get("id"), str) or not (1 <= len(delegate["id"]) <= 120):
            raise AlphaError("That step can't follow this record yet.", 400, code="tool_input")
        rules = model.defaults("delegate", "R0")
        row.update({"delegateType": delegate["type"], "delegateId": delegate["id"], "backgroundAllowed": True, "retryClass": rules.retry_class,
                    "maxAttempts": rules.max_attempts, "timeoutSeconds": rules.timeout_seconds,
                    "riskClass": "R2" if delegate["type"] in ("publish_job", "automation_item", "proposal") else "R0",
                    "inputs": {"goal": delegate.get("goal")} if delegate.get("goal") in ("scheduled", "published") else None})
        if row["riskClass"] == "R2":
            row["retryClass"] = "manual"     # 108: R2/R3 never retry automatically; a poll that is still waiting is not a retry
    elif kind == "wait":
        until = spec.get("waitUntil")
        if not isinstance(until, (int, float)):
            raise AlphaError("Say until when to wait.", 400, code="tool_input")
        rules = model.defaults("wait", "R0")
        row.update({"waitUntil": float(until), "nextAttemptAt": float(until), "backgroundAllowed": True, "retryClass": rules.retry_class,
                    "maxAttempts": rules.max_attempts, "timeoutSeconds": rules.timeout_seconds})
    elif kind == "approval":
        row.update({"retryClass": "never", "maxAttempts": 1, "timeoutSeconds": 10})   # bound to its gated step after the whole plan is read
    return row


def bind_approval_step(row: dict, spec: dict, known: dict) -> None:
    """An `approval` step (journey C s2) carries what it approves: the gated tool step's capability, inputs digest and targets,
    so the approval's digest covers exactly what will run. The gated step must depend on it."""
    gated = known.get(spec.get("approves") or "")
    if gated is None or gated.get("kind") != "tool":
        raise AlphaError("An approval step names the tool step it approves.", 400, code="tool_input")
    if row["stepKey"] not in (gated.get("dependsOn") or []):
        raise AlphaError("The approved step must depend on its approval step.", 400, code="tool_input")
    row.update({"capabilityId": gated["capabilityId"], "capabilityVersion": gated.get("capabilityVersion") or 1, "riskClass": gated["riskClass"],
                "effect": gated["effect"], "inputs": {"approves": gated["stepKey"]}, "inputDigest": gated["inputDigest"],
                "targetRefs": list(gated.get("targetRefs") or [])})


def _targets(value) -> list:
    out = []
    for item in value or []:
        if isinstance(item, dict) and isinstance(item.get("type"), str) and isinstance(item.get("id"), str):
            out.append({"type": item["type"][:32], "id": item["id"][:120], **({"revision": item["revision"]} if isinstance(item.get("revision"), (int, str)) else {})})
    return out[:40]


# --- step updates ---------------------------------------------------------------------------------------------------------
_STEP_UPDATABLE = {"state", "reason_code", "reason", "verified", "attempts", "generation", "next_attempt_at", "effect_key", "outputs", "entities",
                   "started_at", "finished_at", "retry_class", "max_attempts", "label", "inputs", "input_digest", "depends_on"}


def set_step(cur, step: dict, **changes) -> None:
    """Update one step (caller holds the task row lock). Terminal states stamp finished_at; open states clear it."""
    columns, values = [], []
    for name, value in changes.items():
        if name not in _STEP_UPDATABLE:
            raise ValueError(name)
        if name == "next_attempt_at":
            columns.append("next_attempt_at=CASE WHEN %s::float8 IS NULL THEN NULL ELSE to_timestamp(%s::float8) END")
            values.extend([value, value])
            continue
        if name in ("outputs", "entities", "inputs"):
            columns.append(f"{name}=%s::jsonb")
            values.append(json.dumps(value, ensure_ascii=False, default=str))
            continue
        if name in ("started_at", "finished_at"):
            columns.append(f"{name}=" + ("now()" if value == "now" else "NULL"))
            continue
        columns.append(f"{name}=%s")
        values.append(model.clip(value, 300) if name == "reason" else value)
    state = changes.get("state")
    if state in model.TERMINAL_STATES and "finished_at" not in changes:
        columns.append("finished_at=coalesce(finished_at,now())")
    elif state in model.OPEN_STATES and "finished_at" not in changes:
        columns.append("finished_at=NULL")
    if state == "running" and "started_at" not in changes:
        columns.append("started_at=coalesce(started_at,now())")
    columns.append("updated_at=now()")
    cur.execute(f"UPDATE public.pr_agent_steps SET {','.join(columns)} WHERE id::text=%s AND workspace_id=%s", (*values, step["stepId"], step["workspaceId"]))
    step.update({_camel(k): v for k, v in changes.items() if k not in ("started_at", "finished_at")})


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


def cancel_dependents(cur, steps: list[dict], key: str, reason_code: str = "dependency_failed") -> list[str]:
    """A non-retryable failure cancels its transitive dependents in the same transaction (EX-7)."""
    keys = model.dependents(facts(steps), key)
    by_key = {s["stepKey"]: s for s in steps}
    done = []
    for k in keys:
        step = by_key[k]
        if step["state"] in ("queued", "blocked", "awaiting_approval"):
            set_step(cur, step, state="cancelled", reason_code=reason_code, reason="An earlier step it needs failed.")
            done.append(k)
    return done


# --- approvals (X1: the one table) ---------------------------------------------------------------------------------------
def insert_approval(cur, *, task: dict, step: dict, kind: str, risk: str, confirmation: str, digest: str, summary: dict, required_permission: str,
                    approver_policy: str, authz_token: str, ttl_seconds: int, capability_id: str | None = None, input_digest: str | None = None,
                    inputs: dict | None = None, target_refs: list | None = None, proposal_id: str | None = None, proposal_type: str | None = None,
                    conversation_id: str | None = None, message_id: str | None = None, run_id: str | None = None, trace_id: str | None = None,
                    requires_step_up: bool = False, expires_at: float | None = None) -> str:
    cur.execute("INSERT INTO public.pr_agent_approvals(workspace_id,task_id,step_id,generation,requested_for,kind,proposal_id,proposal_type,conversation_id,"
                "message_id,run_id,trace_id,capability_id,capability_version,risk_class,confirmation,input_digest,inputs,target_refs,digest,summary,"
                "required_permission,approver_policy,requires_step_up,authz_token,expires_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,"
                "least((SELECT hard_expires_at FROM public.pr_agent_tasks WHERE id::text=%s), "
                "CASE WHEN %s::float8 IS NULL THEN now()+make_interval(secs => %s) ELSE to_timestamp(%s::float8) END)) RETURNING id::text",
                (task["workspaceId"], task["taskId"], step["stepId"], int(step["generation"]), task["createdBy"], kind, proposal_id, proposal_type,
                 conversation_id, message_id, run_id, trace_id, capability_id, 1 if capability_id else None, risk, confirmation, input_digest,
                 json.dumps(inputs) if inputs is not None else None, json.dumps(target_refs or []), digest, json.dumps(summary, ensure_ascii=False, default=str),
                 required_permission, approver_policy, requires_step_up, authz_token, task["taskId"], expires_at, int(ttl_seconds), expires_at))
    return cur.fetchone()[0]


def load_approval(cur, workspace_id: str, approval_id: str, *, lock: bool = False) -> dict | None:
    if not _uuid(approval_id):
        return None
    cur.execute(f"SELECT {APPROVAL_COLUMNS} FROM public.pr_agent_approvals a WHERE a.id::text=%s AND a.workspace_id=%s" + (" FOR UPDATE" if lock else ""),
                (approval_id, workspace_id))
    row = cur.fetchone()
    return _approval(row) if row else None


def approval_by_proposal(cur, workspace_id: str, proposal_id: str, *, lock: bool = False) -> dict | None:
    cur.execute(f"SELECT {APPROVAL_COLUMNS} FROM public.pr_agent_approvals a WHERE a.workspace_id=%s AND a.proposal_id=%s" + (" FOR UPDATE" if lock else ""),
                (workspace_id, proposal_id))
    row = cur.fetchone()
    return _approval(row) if row else None


def approvals_for(cur, workspace_id: str, task_id: str, *, state: str | None = None) -> list[dict]:
    cur.execute(f"SELECT {APPROVAL_COLUMNS} FROM public.pr_agent_approvals a WHERE a.task_id::text=%s AND a.workspace_id=%s"
                + (" AND a.state=%s" if state else "") + " ORDER BY a.created_at", (task_id, workspace_id, *([state] if state else [])))
    return [_approval(r) for r in cur.fetchall()]


def close_approval(cur, approval: dict, state: str, *, surface: str, decided_by: str | None = None, decision_key: str | None = None,
                   outcome: dict | None = None) -> None:
    """Every transition out of pending records when (correction 4); system closes use surface 'system'."""
    if state not in model.APPROVAL_STATES or state == "pending":
        raise ValueError(state)
    cur.execute("UPDATE public.pr_agent_approvals SET state=%s,decided_by=coalesce(%s,decided_by),decided_at=coalesce(decided_at,now()),"
                "decision_surface=coalesce(%s,decision_surface),decision_key=coalesce(%s,decision_key),decision_outcome=coalesce(%s::jsonb,decision_outcome),"
                "consumed_at=CASE WHEN %s::text='consumed' THEN coalesce(consumed_at,now()) ELSE consumed_at END,updated_at=now() WHERE id::text=%s",
                (state, decided_by, surface if approval["state"] == "pending" else None, decision_key,
                 json.dumps(outcome) if outcome is not None else None, state, approval["approvalId"]))
    approval["state"] = state


def close_pending_approvals(cur, workspace_id: str, task_id: str, state: str, *, step_ids: set | None = None) -> list[str]:
    closed = []
    for item in approvals_for(cur, workspace_id, task_id, state="pending"):
        if step_ids is None or item["stepId"] in step_ids:
            close_approval(cur, item, state, surface="system")
            closed.append(item["approvalId"])
    return closed


# --- receipts (EX-19) and compensations (EX-27) ---------------------------------------------------------------------------
def receipt(cur, workspace_id: str, effect_key: str, *, lock: bool = False) -> dict | None:
    cur.execute("SELECT effect_key,task_id::text,step_id::text,attempt_id::text,principal::text,capability_id,input_digest,state,outcome,verified,result,"
                "ui_action_key,trace_id,extract(epoch from created_at),extract(epoch from updated_at) FROM public.pr_agent_receipts "
                "WHERE workspace_id=%s AND effect_key=%s" + (" FOR UPDATE" if lock else ""), (workspace_id, effect_key))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("effectKey", "taskId", "stepId", "attemptId", "principal", "capabilityId", "inputDigest", "state", "outcome", "verified", "result",
            "uiActionKey", "traceId", "createdAt", "updatedAt")
    found = dict(zip(keys, row))
    found["result"] = found["result"] or {}
    return found


def receipt_begin(cur, task: dict, step: dict, attempt_id: str, trace_id: str) -> tuple[str, dict | None]:
    """('replay', receipt) for a done receipt with the same digest; ('conflict', receipt) for a different digest; ('fresh',
    None) after inserting (or re-binding) a pending receipt."""
    found = receipt(cur, task["workspaceId"], step["effectKey"], lock=True)
    if found is not None:
        if found["inputDigest"] != step["inputDigest"]:
            return "conflict", found
        if found["state"] == "done":
            return "replay", found
        cur.execute("UPDATE public.pr_agent_receipts SET attempt_id=%s,trace_id=%s,updated_at=now() WHERE workspace_id=%s AND effect_key=%s",
                    (attempt_id, trace_id, task["workspaceId"], step["effectKey"]))
        return "fresh", None
    cur.execute("INSERT INTO public.pr_agent_receipts(workspace_id,effect_key,task_id,step_id,attempt_id,principal,capability_id,input_digest,trace_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (task["workspaceId"], step["effectKey"], task["taskId"], step["stepId"], attempt_id,
                                                        task["createdBy"], step["capabilityId"], step["inputDigest"], trace_id))
    return "fresh", None


def receipt_done(cur, workspace_id: str, effect_key: str, *, outcome: str, verified: bool | None, result: dict) -> None:
    cur.execute("UPDATE public.pr_agent_receipts SET state='done',outcome=%s,verified=%s,result=%s::jsonb,updated_at=now() "
                "WHERE workspace_id=%s AND effect_key=%s AND state='pending'",
                (outcome, verified, json.dumps(receipt_result(result), ensure_ascii=False, default=str), workspace_id, effect_key))


def receipt_result(result: dict) -> dict:
    """Only checks, changed refs, the provider receipt, cost state, evidence refs, compensation and what can't be recalled (§8.2)."""
    result = result if isinstance(result, dict) else {}
    checks = [{"name": str(c.get("what") or c.get("name") or c.get("type") or "check")[:80], "ok": bool(c.get("verified", c.get("ok")))}
              for c in result.get("checks") or [] if isinstance(c, dict)][:20]
    changed = [{"type": str(c.get("type"))[:32], "id": str(c.get("id"))[:120], "change": str(c.get("change") or "changed")[:80]}
               for c in result.get("changedRefs") or [] if isinstance(c, dict) and c.get("id")][:20]
    return {"checks": checks, "changedRefs": changed, "providerReceipt": result.get("providerReceipt") if isinstance(result.get("providerReceipt"), dict) else None,
            "costState": result.get("costState") if result.get("costState") in ("none", "known", "unknown", "estimated") else "none",
            "evidenceRefs": [str(e)[:120] for e in result.get("evidenceRefs") or []][:20],
            "compensation": result.get("compensation") if isinstance(result.get("compensation"), dict) else {"available": False},
            "cannotRecall": [str(e)[:40] for e in result.get("cannotRecall") or []][:10]}


def receipts_for(cur, workspace_id: str, task_id: str) -> list[dict]:
    cur.execute("SELECT r.effect_key,s.step_key,r.capability_id,r.state,r.outcome,r.verified,r.result,extract(epoch from r.updated_at) "
                "FROM public.pr_agent_receipts r JOIN public.pr_agent_steps s ON s.id=r.step_id WHERE r.task_id::text=%s AND r.workspace_id=%s "
                "ORDER BY r.created_at", (task_id, workspace_id))
    keys = ("effectKey", "stepKey", "capabilityId", "state", "outcome", "verified", "result", "at")
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def insert_compensation(cur, *, task: dict, step: dict, effect_key: str, inverse_capability_id: str, target_type: str, target_id: str,
                        post_image_digest: str, inverse_inputs: dict, undo_seconds: int = model.UNDO_WINDOW_SECONDS) -> str:
    cur.execute("INSERT INTO public.pr_agent_compensations(workspace_id,task_id,step_id,effect_key,inverse_capability_id,target_type,target_id,"
                "post_image_digest,inverse_inputs,undo_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now()+make_interval(secs => %s)) "
                "ON CONFLICT (workspace_id, effect_key) DO NOTHING RETURNING id::text",
                (task["workspaceId"], task["taskId"], step["stepId"], effect_key, inverse_capability_id, target_type, target_id, post_image_digest,
                 json.dumps(inverse_inputs, ensure_ascii=False, default=str), min(int(undo_seconds), 7 * 24 * 3600)))
    row = cur.fetchone()
    return row[0] if row else ""


def compensation(cur, workspace_id: str, compensation_id: str, *, lock: bool = False) -> dict | None:
    if not _uuid(compensation_id):
        return None
    cur.execute("SELECT id::text,task_id::text,step_id::text,effect_key,inverse_capability_id,target_type,target_id,post_image_digest,inverse_inputs,state,"
                "extract(epoch from undo_until),(undo_until < now()) FROM public.pr_agent_compensations WHERE id::text=%s AND workspace_id=%s"
                + (" FOR UPDATE" if lock else ""), (compensation_id, workspace_id))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("compensationId", "taskId", "stepId", "effectKey", "inverseCapabilityId", "targetType", "targetId", "postImageDigest", "inverseInputs",
            "state", "undoUntil", "pastWindow")
    return dict(zip(keys, row))


def compensations_for(cur, workspace_id: str, task_id: str) -> dict:
    cur.execute("SELECT c.id::text,s.step_key,c.state,extract(epoch from c.undo_until),c.effect_key FROM public.pr_agent_compensations c "
                "JOIN public.pr_agent_steps s ON s.id=c.step_id WHERE c.task_id::text=%s AND c.workspace_id=%s", (task_id, workspace_id))
    return {r[1]: {"compensationId": r[0], "state": r[2], "undoUntil": float(r[3]), "effectKey": r[4]} for r in cur.fetchall()}


def attempts_for(cur, workspace_id: str, task_id: str) -> list[dict]:
    cur.execute("SELECT a.id::text,s.step_key,a.attempt_no,a.generation,a.executor,a.state,a.authz_verdict,a.authz_reason,a.authz_token,a.error_category,"
                "a.error_code,a.cost_state,a.trace_id,a.request_id,extract(epoch from a.started_at),extract(epoch from a.finished_at),"
                "extract(epoch from a.lease_expires_at) FROM public.pr_agent_step_attempts a JOIN public.pr_agent_steps s ON s.id=a.step_id "
                "WHERE a.task_id::text=%s AND a.workspace_id=%s ORDER BY a.started_at", (task_id, workspace_id))
    keys = ("attemptId", "stepKey", "attemptNo", "generation", "executor", "state", "authzVerdict", "authzReason", "authzToken", "errorCategory",
            "errorCode", "costState", "traceId", "requestId", "startedAt", "finishedAt", "leaseExpiresAt")
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def allowed_before(cur, workspace_id: str, task_id: str) -> bool:
    cur.execute("SELECT 1 FROM public.pr_agent_step_attempts WHERE task_id::text=%s AND workspace_id=%s AND authz_verdict='allow' LIMIT 1",
                (task_id, workspace_id))
    if cur.fetchone():
        return True
    cur.execute("SELECT 1 FROM public.pr_agent_steps WHERE task_id::text=%s AND workspace_id=%s AND state='completed' LIMIT 1", (task_id, workspace_id))
    return cur.fetchone() is not None


# --- person-action idempotency (cancel, retry, undo, continue, approval decide outside the approval row) ----------------
def remembered(cur, workspace_id: str, actor: str, kind: str, key: str, body_digest: str) -> dict | None:
    """A person's earlier action with this key: its stored response (same actor + same body), or 409 idempotency_conflict for
    anyone else or another body. Stored content-free in the audit log (ids and states only)."""
    hashed = model.sha256(f"{kind}|{key}")
    cur.execute("SELECT actor::text,meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind=%s AND meta->>'keyHash'=%s ORDER BY at DESC LIMIT 1",
                (workspace_id, kind, hashed))
    row = cur.fetchone()
    if not row:
        return None
    meta = row[1] or {}
    if row[0] != str(actor) or meta.get("bodyDigest") != body_digest:
        raise errors.error("idempotency_conflict")
    return meta.get("response") or {}


def remember(cur, workspace_id: str, actor: str, kind: str, key: str, body_digest: str, subject: str, response: dict, trace_id: str | None = None) -> None:
    from ...hosted import audit
    audit(cur, workspace_id, actor, kind, subject[:200], {"keyHash": model.sha256(f"{kind}|{key}"), "bodyDigest": body_digest, "response": response,
                                                          **({"traceId": trace_id} if trace_id else {})})
