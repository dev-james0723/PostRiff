"""Task Center shapes and visibility (CF-3 §17.2, §17.3; DP-10, correction 10). Zero model calls; content-free beyond the
person's own plan labels and server-built approval summaries.

    the task's creator           list scope=mine (default); full TaskV1; may cancel, retry, continue, undo; diagnostics
    owner class                  may list scope=workspace (TaskSummaryV1 without outputs, entities or receipts); full TaskV1;
                                 may cancel (never retry/continue/undo); diagnostics
    a member who may decide one  view=needs_me lists it as TaskRefV1; detail = {taskId, title, state, approvals:[that one]}
    of its pending approvals
    any other member             not listed; detail = {taskId, title, state}
Spend appears only for the owner class (the existing owner-only USD rule). `can.*` never offers what the caller can't do.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone

from . import errors, model, store, targets


def iso(epoch) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def task_ref(task: dict) -> dict:
    return {"taskId": task["taskId"], "title": task["title"], "state": task["state"]}


def _owner(member) -> bool:
    return member is not None and member.allows("owner")


def _may_decide(approval: dict, principal: str, member) -> bool:
    from .approvals import _may_decide as decide
    return member is not None and decide(approval, principal, member)


def needs_me(task: dict, steps: list[dict], approvals: list[dict], principal: str, member) -> dict | None:
    if task["state"] not in model.OPEN_STATES:
        return None
    creator = task["createdBy"] == principal
    by_id = {s["stepId"]: s for s in steps}
    for approval in approvals:
        if approval["state"] == "pending" and _may_decide(approval, principal, member) and (creator or approval["approverPolicy"] != "task_owner"):
            step = by_id.get(approval["stepId"]) or {}
            return {"kind": "approval", "approvalId": approval["approvalId"], "stepKey": step.get("stepKey")}
    if not creator:
        return None
    for step in steps:
        if step["kind"] == "continuation" and step["state"] == "blocked":
            return {"kind": "continue", "stepKey": step["stepKey"]}
    facts = store.facts(steps)
    for step, fact in zip(steps, facts):
        if model.retryable(fact, int(task["attemptsLeft"])):
            return {"kind": "step_failed", "stepKey": step["stepKey"], "reasonCode": step["reasonCode"]}
    for step in steps:
        if step["state"] == "blocked":
            return {"kind": "blocked", "stepKey": step["stepKey"], "reasonCode": step["reasonCode"]}
    return None


def summary(task: dict, steps: list[dict], approvals: list[dict], principal: str, member) -> dict:
    creator = task["createdBy"] == principal
    counts = {"total": len(steps), "queued": 0, "running": 0, "awaitingApproval": 0, "blocked": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for step in steps:
        key = "awaitingApproval" if step["state"] == "awaiting_approval" else step["state"]
        counts[key] = counts.get(key, 0) + 1
    current = next((s for s in steps if s["state"] == "running"), None) or next((s for s in steps if s["state"] == "awaiting_approval"), None) \
        or next((s for s in steps if s["state"] in ("queued", "blocked")), None)
    is_open = task["state"] in model.OPEN_STATES
    return {**task_ref(task), "partial": bool(task["partial"]), "reasonCode": task["reasonCode"], "version": int(task["version"]), "origin": task["origin"],
            "createdBy": {"userId": task["createdBy"], "isMe": creator}, "conversationId": task["conversationId"], "parentTaskId": task["parentTaskId"],
            "needsMe": needs_me(task, steps, approvals, principal, member), "progress": counts,
            "current": {"stepKey": current["stepKey"], "label": current["label"], "state": current["state"]} if current else None,
            "spend": {"spentUsdMicro": int(task["spentUsdMicro"] or 0), "unknown": bool(task["spendUnknown"])} if _owner(member) else None,
            "can": {"cancel": is_open and (creator or _owner(member)), "retry": creator and any(model.can_retry(s, task) for s in steps),
                    "continue": creator and is_open},
            "nextWakeAt": iso(task["nextWakeAt"]), "expiresAt": iso(task["expiresAt"]), "createdAt": iso(task["createdAt"]), "updatedAt": iso(task["updatedAt"]),
            "finishedAt": iso(task["finishedAt"]), "href": f"/app/agent/{task['conversationId']}?task={task['taskId']}"}


def approval_view(approval: dict, steps_by_id: dict, principal: str, member) -> dict:
    may = _may_decide(approval, principal, member) and approval["state"] == "pending"
    why = None if may else ("closed" if approval["state"] != "pending" else "only_task_owner" if approval["approverPolicy"] == "task_owner" else "permission")
    return {"approvalId": approval["approvalId"], "stepKey": (steps_by_id.get(approval["stepId"]) or {}).get("stepKey"), "kind": approval["kind"],
            "proposalId": approval["proposalId"], "proposalType": approval["proposalType"], "conversationId": approval["conversationId"],
            "messageId": approval["messageId"], "riskClass": approval["riskClass"], "digest": approval["digest"], "summary": approval["summary"],
            "requiredPermission": approval["requiredPermission"], "requiresStepUp": bool(approval["requiresStepUp"]), "state": approval["state"],
            "expiresAt": iso(approval["expiresAt"]), "decidedAt": iso(approval["decidedAt"]), "decisionSurface": approval["decisionSurface"],
            "can": {"decide": may, "why": why}}


def step_view(cur, task: dict, step: dict, steps: list[dict], compensations: dict, principal: str, state_cache: dict, *, member=None, config=None) -> dict:
    creator = task["createdBy"] == principal
    fact = store.facts([step])[0]
    delegate = None
    if step["delegateType"]:
        live = None
        if step["delegateType"] == "publish_job":
            if "state" not in state_cache:
                state_cache["state"] = targets.workspace_state(cur, task["workspaceId"])
            job = next((j for j in (state_cache["state"].get("phase2") or {}).get("jobs") or [] if isinstance(j, dict) and j.get("id") == step["delegateId"]), None)
            live = (job or {}).get("state")   # read live from the queue (a later `verified` is shown truthfully)
        delegate = {"type": step["delegateType"], "id": step["delegateId"], "state": live or next((o.get("state") for o in step["outputs"] if isinstance(o, dict)
                                                                                                   and o.get("id") == step["delegateId"]), None) or step["state"],
                    "href": f"/app/queue?job={step['delegateId']}" if step["delegateType"] == "publish_job" else None}
    comp = compensations.get(step["stepKey"])
    undo = {"compensationId": comp["compensationId"], "undoUntil": iso(comp["undoUntil"])} if comp and comp["state"] == "available" and comp["undoUntil"] > time.time() else None
    can_undo = False
    if creator and undo is not None:
        from . import undo as undo_plan
        from postriff_alpha.domain import AlphaError
        if "state" not in state_cache:
            state_cache["state"] = targets.workspace_state(cur, task["workspaceId"])
        record = store.compensation(cur, task["workspaceId"], comp["compensationId"])
        try:
            undo_plan.prepare(cur, task, step, record, principal, member, state_cache["state"], now=time.time(), config=config)
            can_undo = True
        except AlphaError:
            pass
    return {"stepKey": step["stepKey"], "label": step["label"], "state": step["state"], "legacyState": model.legacy_state(step["state"], step["reasonCode"]),
            "kind": step["kind"], "capabilityId": step["capabilityId"], "riskClass": step["riskClass"], "dependsOn": list(step["dependsOn"]),
            "waitingOn": model.waiting_on(fact, store.facts(steps)), "attempts": int(step["attempts"]), "maxAttempts": int(step["maxAttempts"]),
            "generation": int(step["generation"]), "retryClass": step["retryClass"], "nextAttemptAt": iso(step["nextAttemptAt"]),
            "timeoutSeconds": int(step["timeoutSeconds"]), "reasonCode": step["reasonCode"], "reason": step["reason"], "verified": bool(step["verified"]),
            "outputs": step["outputs"], "entities": step["entities"], "delegate": delegate, "undo": undo,
            "can": {"retry": creator and model.can_retry(step, task),
                    "undo": can_undo}}


def receipt_view(item: dict, steps_by_key: dict, state_cache: dict, cur, task) -> dict:
    result = item.get("result") or {}
    provider = result.get("providerReceipt")
    return {"effectKey": item["effectKey"], "stepKey": item["stepKey"], "capabilityId": item["capabilityId"],
            "outcome": item["outcome"] or "unknown", "verified": item["verified"], "checks": result.get("checks") or [], "changedRefs": result.get("changedRefs") or [],
            "providerReceipt": provider, "costState": result.get("costState") or "none", "evidenceRefs": result.get("evidenceRefs") or [],
            "cannotRecall": result.get("cannotRecall") or [], "compensation": result.get("compensation") or {"available": False}, "at": iso(item["at"])}


def full(cur, task: dict, principal: str, member, *, config=None) -> dict:
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
    approvals = store.approvals_for(cur, task["workspaceId"], task["taskId"])
    compensations = store.compensations_for(cur, task["workspaceId"], task["taskId"])
    by_id = {s["stepId"]: s for s in steps}
    cache: dict = {}
    receipts = [receipt_view(r, {s["stepKey"]: s for s in steps}, cache, cur, task) for r in store.receipts_for(cur, task["workspaceId"], task["taskId"])
                if r["state"] == "done"]
    return {**summary(task, steps, approvals, principal, member), "autonomyMode": task["autonomyMode"],
            "steps": [step_view(cur, task, s, steps, compensations, principal, cache, member=member, config=config) for s in steps],
            "approvals": [approval_view(a, by_id, principal, member) for a in approvals], "receipts": receipts}


def engine_block(cur, task: dict, principal: str, member, *, config=None) -> dict:
    """GET tasks/{task}: the `engine` key by caller (§17.2). The legacy keys are unchanged and keep today's `read` rule."""
    if task["createdBy"] == principal or _owner(member):
        return full(cur, task, principal, member, config=config)
    approvals = store.approvals_for(cur, task["workspaceId"], task["taskId"], state="pending")
    mine = [a for a in approvals if a["approverPolicy"] != "task_owner" and _may_decide(a, principal, member)]
    if mine:
        steps = {s["stepId"]: s for s in store.load_steps(cur, task["workspaceId"], task["taskId"])}
        return {**task_ref(task), "approvals": [approval_view(a, steps, principal, member) for a in mine]}
    return task_ref(task)


def task_for_decider(cur, task: dict, principal: str, member) -> dict:
    """The decision response's task: the creator (and owners) get the summary; another decider only {taskId, title, state}."""
    if task is None:
        return None
    if task["createdBy"] == principal or _owner(member):
        steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
        return summary(task, steps, store.approvals_for(cur, task["workspaceId"], task["taskId"]), principal, member)
    return task_ref(task)


def diagnostics(cur, task: dict, principal: str, member) -> dict:
    """Content-free: ids, states, reason codes, verdicts and times; never inputs, outputs, prompts or the checkpoint payload."""
    from . import checkpoints
    if not (task["createdBy"] == principal or _owner(member)):
        raise errors.error("task_forbidden")
    attempts = store.attempts_for(cur, task["workspaceId"], task["taskId"])
    steps = store.load_steps(cur, task["workspaceId"], task["taskId"])
    last = next((a for a in reversed(attempts)), None)
    cur.execute("SELECT coalesce(max(seq),0) FROM public.pr_agent_events WHERE run_id::text=%s", (task["taskId"],))
    last_seq = int(cur.fetchone()[0])
    out = {"task": {"taskId": task["taskId"], "rootTraceId": task["rootTraceId"], "state": task["state"], "reasonCode": task["reasonCode"],
                    "partial": bool(task["partial"]), "version": int(task["version"]), "attemptsLeft": int(task["attemptsLeft"]),
                    "authz": {"tokenAtStart": attempts[0]["authzToken"] if attempts else None, "currentToken": task["authzToken"],
                              "lastCheck": {"stepKey": last["stepKey"], "verdict": last["authzVerdict"], "reasonCode": last["authzReason"], "at": iso(last["startedAt"])}
                              if last else None},
                    "expiresAt": iso(task["expiresAt"]), "hardExpiresAt": iso(task["hardExpiresAt"])},
           "steps": [{"stepKey": s["stepKey"], "kind": s["kind"], "state": s["state"], "reasonCode": s["reasonCode"], "generation": int(s["generation"]),
                      "attempts": [{"attemptId": a["attemptId"], "attemptNo": a["attemptNo"], "generation": a["generation"], "executor": a["executor"],
                                    "state": a["state"], "authzVerdict": a["authzVerdict"], "authzReason": a["authzReason"], "errorCategory": a["errorCategory"],
                                    "errorCode": a["errorCode"], "costState": a["costState"], "traceId": a["traceId"], "requestId": a["requestId"],
                                    "startedAt": iso(a["startedAt"]), "finishedAt": iso(a["finishedAt"])} for a in attempts if a["stepKey"] == s["stepKey"]]}
                     for s in steps],
           "approvals": [{"approvalId": a["approvalId"], "state": a["state"], "expiresAt": iso(a["expiresAt"]), "decisionSurface": a["decisionSurface"]}
                         for a in store.approvals_for(cur, task["workspaceId"], task["taskId"])],
           "checkpoint": (lambda c: None if c is None else {k: c[k] for k in ("checkpointId", "state", "runtimeVersion", "sdkVersion", "approvals")}
                          | {"expiresAt": iso(c["expiresAt"])})(checkpoints.live(cur, task["workspaceId"], task["taskId"])),
           "lastEventSeq": last_seq}
    if _owner(member):
        cur.execute("SELECT reservation_id,cost_state FROM public.pr_agent_step_attempts WHERE task_id::text=%s AND reservation_id IS NOT NULL", (task["taskId"],))
        out["ledger"] = [{"reservationId": r[0], "costState": r[1]} for r in cur.fetchall()]
    return out


# --- the list ---------------------------------------------------------------------------------------------------------------
def _cursor(value) -> tuple[float, str] | None:
    if not value:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(str(value).encode() + b"=" * (-len(str(value)) % 4)).decode())
        return float(raw[0]), str(raw[1])
    except Exception:  # noqa: BLE001
        raise errors.AlphaError("Invalid cursor.", 400) from None


def _encode(updated_at: float, task_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([updated_at, task_id]).encode()).decode().rstrip("=")


def list_tasks(cur, workspace_id: str, principal: str, member, *, view: str = "open", scope: str = "mine", limit: int = 20, cursor=None) -> dict:
    if view not in ("open", "needs_me", "recent") or scope not in ("mine", "workspace"):
        raise errors.AlphaError("Choose view open, needs_me or recent and scope mine or workspace.", 400)
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise errors.AlphaError("Choose a limit from 1 to 50.", 400)
    if scope == "workspace" and not _owner(member):
        raise errors.error("task_forbidden")
    position = _cursor(cursor)
    items, next_cursor = [], None
    if view == "needs_me":
        items = _needs_me(cur, workspace_id, principal, member, limit)
    else:
        where = ["t.workspace_id=%s"]
        params: list = [workspace_id]
        if scope == "mine":
            where.append("t.created_by=%s")
            params.append(principal)
        if view == "open":
            where.append("t.state IN ('queued','running','awaiting_approval','blocked')")
        if position:
            where.append("(t.updated_at, t.id::text) < (to_timestamp(%s::float8), %s)")
            params.extend(position)
        cur.execute(f"SELECT {store.TASK_COLUMNS} FROM public.pr_agent_tasks t WHERE {' AND '.join(where)} ORDER BY t.updated_at DESC, t.id::text DESC LIMIT %s",
                    (*params, limit + 1))
        rows = [store._task(r) for r in cur.fetchall()]
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = _encode(rows[-1]["updatedAt"], rows[-1]["taskId"])
        for task in rows:
            steps = store.load_steps(cur, workspace_id, task["taskId"])
            approvals = store.approvals_for(cur, workspace_id, task["taskId"])
            items.append(summary(task, steps, approvals, principal, member))
    cur.execute("SELECT count(*) FROM public.pr_agent_tasks WHERE workspace_id=%s AND created_by=%s AND state IN ('queued','running','awaiting_approval','blocked')",
                (workspace_id, principal))
    open_count = int(cur.fetchone()[0])
    needs = len(_needs_me(cur, workspace_id, principal, member, 50)) if view != "needs_me" else len(items)
    return {"items": items, "nextCursor": next_cursor, "counts": {"open": open_count, "needsMe": needs}, "asOf": iso(time.time()), "engine": "enabled"}


def _needs_me(cur, workspace_id: str, principal: str, member, limit: int) -> list[dict]:
    out = []
    cur.execute(f"SELECT {store.TASK_COLUMNS} FROM public.pr_agent_tasks t WHERE t.workspace_id=%s AND t.created_by=%s "
                "AND t.state IN ('queued','running','awaiting_approval','blocked') ORDER BY t.updated_at DESC LIMIT 50", (workspace_id, principal))
    for task in [store._task(r) for r in cur.fetchall()]:
        steps = store.load_steps(cur, workspace_id, task["taskId"])
        approvals = store.approvals_for(cur, workspace_id, task["taskId"])
        if needs_me(task, steps, approvals, principal, member):
            out.append(summary(task, steps, approvals, principal, member))
    # Another member's task appears only as a reference, and only for an approval this caller may decide (never task_owner kinds).
    cur.execute(f"SELECT DISTINCT {store.TASK_COLUMNS} FROM public.pr_agent_tasks t JOIN public.pr_agent_approvals a ON a.task_id=t.id AND a.workspace_id=t.workspace_id "
                "WHERE t.workspace_id=%s AND t.created_by<>%s AND a.state='pending' AND a.approver_policy<>'task_owner' AND a.expires_at > now() LIMIT 50",
                (workspace_id, principal))
    for task in [store._task(r) for r in cur.fetchall()]:
        approvals = store.approvals_for(cur, workspace_id, task["taskId"], state="pending")
        if any(a["approverPolicy"] != "task_owner" and _may_decide(a, principal, member) for a in approvals):
            out.append(task_ref(task))
    return out[:limit]
