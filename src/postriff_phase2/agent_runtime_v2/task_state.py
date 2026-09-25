"""First-class multi-step task state (spec §16), persisted on the existing run tables — no new table.

A task is a conversation-scoped `pr_agent_runs` row with idempotency key `task:<uuid>`: its `artifact.task` holds
the plan, its status is `running` until every step is terminal, and every step change is a `progress.updated`
event (`stage: "task_step"`), so the panel and Voice Mode follow progress with the same cursor replay they use for
runs. Text and voice read the same row, so a task started by voice continues by text (§3.1, WP03).

Invariants (tested):
- `done` is set only by the tool that did the work and re-read the state (`complete`); a model can plan steps, say a
  step is blocked, needs the person, or was cancelled, but never that its own work is done.
- A compound request never silently drops a step: at the end of a turn every step that was not attempted is reported
  as it stands (`summary`), and an impossible step is failed with its own reason instead of hiding it.
"""
from __future__ import annotations

import json
import time

from postriff_alpha.domain import AlphaError, uid

from ..agent_runtime import safe_event
from ..contracts import digest
from . import contracts

KEY_PREFIX = "task:"
TASK_MODEL = "rafii-task"
MAX_STEPS = 12
MODEL_SETTABLE = ("running", "blocked", "needs_user", "canceled")
EPOCH = digest({"taskState": 1})


class TaskPlan:
    def __init__(self, task_id: str | None, title: str, steps: list[contracts.Step] | None = None, version: int = 0, status: str = "running",
                 created_by: str | None = None, trace_ids: list[str] | None = None):
        self.task_id, self.title, self.steps, self.version, self.status = task_id, title, list(steps or []), version, status
        self.created_by = created_by
        self.trace_ids = list(trace_ids or [])
        self.changes: list[dict] = []    # step changes made this turn, emitted as events on save

    # --- construction ------------------------------------------------------------------------------------------------
    @classmethod
    def from_artifact(cls, task_id: str, artifact: dict, status: str) -> "TaskPlan":
        body = (artifact or {}).get("task") or {}
        steps = [contracts.Step(id=s["id"], label=s["label"], state=s.get("state", "planned"), kind=s.get("kind"), depends_on=list(s.get("dependsOn") or []),
                                entities=list(s.get("entities") or []), outputs=list(s.get("outputs") or []), approvals=list(s.get("approvals") or []),
                                reason=s.get("reason"), verified=bool(s.get("verified")), started_at=s.get("startedAt"), updated_at=s.get("updatedAt"))
                 for s in body.get("steps") or [] if isinstance(s, dict) and s.get("id") and s.get("label")]
        return cls(task_id, body.get("title") or "Task", steps, int(body.get("version") or 0), "running" if status == "running" else status,
                   body.get("createdBy"), body.get("traceIds"))

    def artifact(self) -> dict:
        return {"task": {"title": self.title, "version": self.version, "createdBy": self.created_by, "traceIds": self.trace_ids[-20:],
                         "steps": [s.view() for s in self.steps]}}

    def view(self) -> dict:
        return {"taskId": self.task_id, "title": self.title, "status": self.status, "version": self.version, "steps": [s.view() for s in self.steps],
                "counts": {state: sum(1 for s in self.steps if s.state == state) for state in contracts.STEP_STATES}}

    # --- steps -------------------------------------------------------------------------------------------------------
    def step(self, step_id: str) -> contracts.Step:
        found = next((s for s in self.steps if s.id == step_id), None)
        if found is None:
            raise AlphaError("That step is not part of this task.", 404, code="step_unknown")
        return found

    def add(self, label: str, *, kind: str | None = None, depends_on=(), now: float) -> contracts.Step:
        if len(self.steps) >= MAX_STEPS:
            raise AlphaError(f"A task holds at most {MAX_STEPS} steps.", 400, code="task_too_long")
        label = " ".join(str(label or "").split())[:140]
        if not label:
            raise AlphaError("Name the step.", 400, code="step_label")
        known = {s.id for s in self.steps}
        deps = [d for d in dict.fromkeys(depends_on or ()) if d in known]
        step = contracts.Step(id=f"s{len(self.steps) + 1}", label=label, kind=(kind or None), depends_on=deps, updated_at=now)
        self.steps.append(step)
        self._changed(step, now)
        return step

    def _set(self, step: contracts.Step, state: str, now: float, *, reason=None, verified=None) -> contracts.Step:
        if state not in contracts.STEP_STATES:
            raise AlphaError("Unknown step state.", 400, code="step_state")
        if step.state in contracts.TERMINAL_STEP_STATES and state != step.state:
            # A finished step is not reopened; a new request becomes a new step (and a rejected proposal is never retried).
            raise AlphaError(f"That step is already {step.state}.", 409, code="step_closed")
        previous = step.state
        step.state = state
        # A new state gets its own reason; repeating the same state keeps the old one when none is given.
        step.reason = " ".join(str(reason).split())[:300] if reason else (step.reason if previous == state else None)
        if verified is not None:
            step.verified = bool(verified)
        if state == "running" and step.started_at is None:
            step.started_at = now
        step.updated_at = now
        self._changed(step, now)
        return step

    def model_set(self, step_id: str, state: str, reason: str | None, now: float) -> contracts.Step:
        """What a model may say about a step: never done or failed (tools decide those)."""
        if state not in MODEL_SETTABLE:
            raise AlphaError("A step is marked done or failed only by the tool that did it.", 400, code="step_state_forbidden")
        if state in ("blocked", "needs_user", "canceled") and not reason:
            raise AlphaError("Say why.", 400, code="step_reason")
        return self._set(self.step(step_id), state, now, reason=reason)

    def start(self, step_id: str | None, now: float) -> contracts.Step | None:
        if not step_id:
            return None
        step = self.step(step_id)
        return self._set(step, "running", now) if step.state in ("planned", "blocked", "needs_user") else step

    def complete(self, step_id: str | None, now: float, *, outputs=(), entities=(), verified: bool) -> contracts.Step | None:
        """Tool-only: the work happened and was re-read. An unverified outcome is failed, not done."""
        if not step_id:
            return None
        step = self.step(step_id)
        step.outputs.extend(o for o in outputs if o not in step.outputs)
        step.entities.extend(e for e in entities if e not in step.entities)
        if not verified:
            return self._set(step, "failed", now, reason="The change could not be confirmed by re-reading the workspace.", verified=False)
        return self._set(step, "done", now, verified=True)

    def fail(self, step_id: str | None, reason: str, now: float) -> contracts.Step | None:
        if not step_id:
            return None
        return self._set(self.step(step_id), "failed", now, reason=reason, verified=False)

    def wait_for_person(self, step_id: str | None, reason: str, now: float, *, approvals=()) -> contracts.Step | None:
        if not step_id:
            return None
        step = self.step(step_id)
        step.approvals.extend(a for a in approvals if a not in step.approvals)
        return self._set(step, "needs_user", now, reason=reason)

    def resolve_approval(self, proposal_id: str, outcome: str, now: float, *, verified: bool, outputs=(), reason: str | None = None) -> list[contracts.Step]:
        """An approval was decided outside the model (panel click or bound spoken confirmation)."""
        touched = []
        for step in self.steps:
            if proposal_id in step.approvals and step.state == "needs_user":
                if outcome == "applied":
                    self.complete(step.id, now, outputs=outputs, verified=verified)
                elif outcome in ("dismissed", "rejected"):
                    self._set(step, "canceled", now, reason=reason or "You dismissed the proposal; I won't retry it unless you ask again.")
                else:
                    self._set(step, "failed", now, reason=reason or f"The proposal was {outcome}.")
                touched.append(step)
        return touched

    def cancel_open(self, reason: str, now: float) -> list[contracts.Step]:
        touched = []
        for step in self.steps:
            if step.state in ("planned", "running", "blocked", "needs_user"):
                self._set(step, "canceled", now, reason=reason)
                touched.append(step)
        return touched

    def ready(self) -> list[contracts.Step]:
        """Planned steps whose dependencies are all done: safe independent work runs without waiting (§16)."""
        done = {s.id for s in self.steps if s.state == "done"}
        return [s for s in self.steps if s.state == "planned" and all(d in done for d in s.depends_on)]

    def refresh_status(self) -> str:
        if self.steps and all(s.state in contracts.TERMINAL_STEP_STATES for s in self.steps):
            self.status = "cancelled" if all(s.state == "canceled" for s in self.steps) else "completed"
        else:
            self.status = "running"
        return self.status

    def summary(self) -> dict:
        """Every step with its real state. Nothing is summarised away."""
        buckets = {state: [s for s in self.steps if s.state == state] for state in contracts.STEP_STATES}
        done = len(buckets["done"])
        lines = []
        for step in self.steps:
            word = {"planned": "not started", "running": "in progress", "done": "done", "needs_user": "needs you", "blocked": "blocked",
                    "failed": "failed", "canceled": "cancelled"}[step.state]
            lines.append(f"{step.label}: {word}" + (f" — {step.reason}" if step.reason and step.state != "done" else ""))
        return {"done": done, "total": len(self.steps), "lines": lines, "open": [s.id for s in self.steps if s.state not in contracts.TERMINAL_STEP_STATES]}

    def _changed(self, step: contracts.Step, now: float) -> None:
        self.changes.append({"stepId": step.id, "state": step.state, "label": step.label, "reason": step.reason, "at": now})


# --- persistence -------------------------------------------------------------------------------------------------------
def create(cur, ideas, workspace_id: str, conversation_id: str, principal: str, title: str, trace_id: str) -> TaskPlan:
    title = " ".join(str(title or "").split())[:140] or "Task"
    task_key = KEY_PREFIX + uid()
    cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                "VALUES(%s,%s,%s,'running',%s,'standard',%s,%s,%s,%s::jsonb) RETURNING id::text",
                (conversation_id, workspace_id, principal, TASK_MODEL, digest({"title": title, "trace": trace_id}), EPOCH, task_key,
                 json.dumps({"task": {"title": title, "version": 0, "createdBy": principal, "traceIds": [trace_id], "steps": []}})))
    task_id = cur.fetchone()[0]
    ideas._insert_event(cur, workspace_id, task_id, safe_event("run.started", agent="task", model=TASK_MODEL, reasoning="standard", traceId=trace_id))
    return TaskPlan(task_id, title, [], 0, "running", principal, [trace_id])


def load(cur, workspace_id: str, task_id: str, *, lock: bool = False) -> TaskPlan:
    cur.execute("SELECT status,artifact,idempotency_key FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s" + (" FOR UPDATE" if lock else ""), (task_id, workspace_id))
    row = cur.fetchone()
    if not row or not str(row[2]).startswith(KEY_PREFIX):
        raise AlphaError("Task unavailable.", 404)
    return TaskPlan.from_artifact(task_id, row[1] or {}, row[0])


def active(cur, workspace_id: str, conversation_id: str) -> TaskPlan | None:
    """The conversation's newest open task (text continues what voice started, and back)."""
    cur.execute("SELECT id::text,status,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND conversation_id::text=%s AND idempotency_key LIKE 'task:%%' "
                "AND status='running' ORDER BY created_at DESC LIMIT 1", (workspace_id, conversation_id))
    row = cur.fetchone()
    return TaskPlan.from_artifact(row[0], row[2] or {}, row[1]) if row else None


def latest(cur, workspace_id: str, conversation_id: str) -> TaskPlan | None:
    """The conversation's most recent task, finished or not ("what's left?" after the last step closed it)."""
    cur.execute("SELECT id::text,status,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND conversation_id::text=%s AND idempotency_key LIKE 'task:%%' "
                "ORDER BY created_at DESC LIMIT 1", (workspace_id, conversation_id))
    row = cur.fetchone()
    return TaskPlan.from_artifact(row[0], row[2] or {}, row[1]) if row else None


def save(cur, ideas, workspace_id: str, plan: TaskPlan, *, trace_id: str | None = None) -> TaskPlan:
    """Write the plan under the row lock, emit one event per step change, close the run when every step is terminal."""
    if plan.task_id is None:
        raise AlphaError("Create the task first.", 500)
    ideas._lock_run_events(cur, workspace_id, plan.task_id)
    cur.execute("SELECT artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (plan.task_id, workspace_id))
    row = cur.fetchone()
    if not row:
        raise AlphaError("Task unavailable.", 404)
    stored_version = int((((row[0] or {}).get("task") or {}).get("version")) or 0)
    if stored_version > plan.version:
        raise AlphaError("The task changed while this request ran. Ask again to continue it.", 409, code="task_conflict")
    plan.version = stored_version + 1
    if trace_id and trace_id not in plan.trace_ids:
        plan.trace_ids.append(trace_id)
    status = plan.refresh_status()
    for change in plan.changes:
        ideas._insert_event(cur, workspace_id, plan.task_id, safe_event("progress.updated", stage="task_step", taskId=plan.task_id, **change))
    if status != "running":
        ideas._insert_event(cur, workspace_id, plan.task_id, safe_event("run.completed", usage={"provenance": "task", "steps": len(plan.steps)}))
    # The plan owns its own keys; anything else on the row (a paused Manager run waiting for an approval) is kept.
    merged = {**(row[0] or {}), **plan.artifact()}
    cur.execute("UPDATE public.pr_agent_runs SET artifact=%s::jsonb,status=%s,updated_at=now() WHERE id::text=%s",
                (json.dumps(merged, ensure_ascii=False, default=str), status, plan.task_id))
    plan.changes = []
    return plan


def now() -> float:
    return time.time()
