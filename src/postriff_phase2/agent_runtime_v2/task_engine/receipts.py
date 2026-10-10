"""The receipt protocol inside a domain command's own transaction (CF-3 §8.2, EX-19).

A step-bound executor (`ctx.step_binding` is set by the engine) may commit the engine receipt together with its domain change:
call `replayed(cur, ctx)` first (a done receipt means the effect already happened: return its result instead of repeating)
and `commit_in(cur, ctx, ...)` before its transaction commits. `commit_in` succeeds only while this attempt still owns its
lease, so a producer that was reaped (a zombie still running after a restart) fails and its domain change rolls back: a losing
producer writes nothing. Capabilities that do this are registered in `store.RECEIPT_TX` (they may then retry automatically).
"""
from __future__ import annotations

import json

from postriff_alpha.domain import AlphaError

from . import store


def binding(ctx) -> dict | None:
    value = getattr(ctx, "step_binding", None)
    return value if isinstance(value, dict) and value.get("effectKey") else None


def replayed(cur, ctx) -> dict | None:
    b = binding(ctx)
    if b is None:
        return None
    found = store.receipt(cur, b["workspaceId"], b["effectKey"], lock=True)
    if found and found["state"] == "done" and found["outcome"] == "applied" and found["inputDigest"] == b["inputDigest"]:
        return found
    return None


def commit_in(cur, ctx, *, verified: bool, result: dict | None = None) -> None:
    """Mark the receipt done in the caller's transaction. Raises 409 when this attempt no longer owns its lease (rolls back)."""
    b = binding(ctx)
    if b is None:
        return
    cur.execute("UPDATE public.pr_agent_receipts r SET state='done',outcome='applied',verified=%s,result=%s::jsonb,attempt_id=%s,updated_at=now() "
                "WHERE r.workspace_id=%s AND r.effect_key=%s AND r.state='pending' AND r.input_digest=%s AND EXISTS (SELECT 1 FROM "
                "public.pr_agent_step_attempts a WHERE a.id::text=%s AND a.state='running' AND a.lease_owner=%s AND a.lease_expires_at>now()) RETURNING 1",
                (bool(verified), json.dumps(store.receipt_result(result or {}), ensure_ascii=False, default=str), b["attemptId"], b["workspaceId"],
                 b["effectKey"], b["inputDigest"], b["attemptId"], b["leaseOwner"]))
    if cur.fetchone() is None:
        raise AlphaError("This step is no longer being run here; nothing was changed.", 409, code="lease_lost")
    from ...hosted import audit
    audit(cur, b["workspaceId"], b["principal"], "agent.task.effect", b["stepKey"],
          {"taskId": b["taskId"], "stepKey": b["stepKey"], "effectKey": b["effectKey"]})


def commit_command(cur, ctx, *, verified, changed_refs, compensation_result=None):
    """Domain after-hook: effect, verification, inverse pointer and receipt commit together."""
    b = binding(ctx)
    if b is None:
        return
    from . import compensation
    task = store.load_task(cur, b["workspaceId"], b["taskId"])
    step = next(s for s in store.load_steps(cur, b["workspaceId"], b["taskId"]) if s["stepId"] == b["stepId"])
    if b.get("modelCall"):
        step = {**step, "effectKey": b["effectKey"], "capabilityId": b["capabilityId"], "inputDigest": b["inputDigest"], "riskClass": b["riskClass"], "inputs": b["inputs"]}
    undo = compensation.capture(cur, task, step, compensation_result or {}, changed_refs) if verified else {"available": False}
    commit_in(cur, ctx, verified=verified, result={"checks": [{"name": "domain_state_re_read", "ok": verified}],
                                                 "changedRefs": changed_refs, "compensation": undo, "costState": "none"})
