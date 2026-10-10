"""Lane D — the one guarded action dispatcher (spec §6.3; G06-G09).

Frozen entry points:
- activate_ui_action(cur, auth, artifact, manifest, request) -> dict UiActivationV1 (60 s, single use, input-digest bound, native
  confirmation copy from the server)
- execute_ui_action(cur, auth, artifact, manifest, request) -> dict UiActionResultV1 (activation + durable idempotency in
  pr_ui_actions in the same transaction as the original domain command; re-read; verified only from executor + re-read)
- activate_http(runtime, workspace_id, token, request) -> dict ; execute_http(runtime, workspace_id, token, request) -> dict

Authority is the static allowlist in `ui_domain` (actionId → original domain command, permission class, effect class).
Generated names are never classified: an id that isn't there is refused (404) before anything else runs.

Two calls, both inside one `ui_transaction` each (verified session + active membership + workspace row lock):

activate — a registered Rafii control was clicked. The server checks the artifact is the current accepted revision,
  the control is in the current manifest, the member's role allows it *now*, the inputs fit its schema, and the domain
  target exists. It computes `input_digest(actionId, inputs)` itself and stores a one-use activation that expires in 60 s,
  bound to principal, artifact revision, binding version, action and digest. It returns native confirmation copy built
  from the current record (target, time zone, cost, the exact change), never model text.

execute — the person confirmed. In the same transaction:
  1. `pr_ui_actions` is read by (workspace, idempotencyKey): same digest → the stored result (a double click, a second
     tab or a retry after a lost reply never runs the command twice); different digest → 409 conflict.
  2. the activation is checked (exists, this principal, artifact, current revision, binding version, action, digest, not
     expired) and consumed.
  3. the original domain command runs through a service view bound to this transaction (ui_domain.common.bind), so the
     command, its audit row, its effects hooks and the receipt below commit or roll back together.
  4. the outcome is re-read from the workspace; `verified` is true only when the executor's own re-read matches.
  5. the receipt (outcome, refs, invalidation keys, selection context) is stored under the idempotency key.
A domain refusal (stale revision, closed proposal, missing permission) is a stored `conflict`/`rejected` receipt: retrying
the same key returns it, and a new attempt needs a fresh activation after the person reloads.

Prepared ≠ applied: scheduling/automation proposals return `prepared` with the proposal's id; they are applied only by the
original `POST agent/approvals/decide` from the native proposal card. Publishing, sending, buying, deleting,
disconnecting, secrets and OAuth have no entry here at all.
"""
from __future__ import annotations

import json
import logging
import time

from postriff_alpha.domain import AlphaError

from . import ui_capabilities, ui_contracts, ui_domain
from .ui_domain import common

log = logging.getLogger("postriff.agent_ui")
ACTIVATIONS_PER_MINUTE = 30
REFUSAL_OUTCOMES = {409: "conflict", 403: "rejected", 400: "rejected", 404: "rejected", 422: "rejected", 413: "rejected", 402: "rejected", 429: "failed", 503: "failed"}


def _now() -> float:
    return time.time()


def _binding(effective: dict, action_id: str, manifest: dict | None = None, member=None):
    """The control, as the caller may use it now. A control this view offers but the caller's current role can't use is 403
    (NC02: a viewer, or a member demoted since the view was made); an id the view never offered is 404, so nothing is probed."""
    entry = ui_capabilities.action_binding(effective, action_id)
    if entry is None:
        issued = ui_capabilities.action_binding(manifest, action_id) if manifest is not None else None
        if issued is not None and member is not None and not ui_capabilities._allows(member, issued["binding"].requirement):
            raise AlphaError("Your role in this workspace can't do this.", 403, code="ui_forbidden")
        raise AlphaError("Unknown action.", 404, code="ui_action")
    return entry["binding"]


def _require_drawable(artifact: dict, supported: dict | None = None) -> None:
    ui_capabilities.require_drawable(artifact, supported)


def _require_current(artifact: dict, revision: int) -> None:
    ui_capabilities.require_accepted(artifact, revision)
    if revision != int(artifact.get("revision") or 0):
        raise AlphaError("This view changed since you opened it. Reload it and try again.", 409, code="ui_revision_stale")


def _context(runtime, cur, auth, artifact, effective, inputs, now):
    from .ui_queries import domain_context
    return domain_context(runtime, cur, auth, artifact, effective, inputs, now=now)


def _confirmation(binding, copy: dict) -> dict:
    summary = [str(line)[:240] for line in (copy.get("summary") or []) if line][:12]
    return {"required": bool(binding.requires_confirmation), "title": str(copy.get("title") or binding.label)[:120], "summary": summary,
            "target": (str(copy["target"])[:200] if copy.get("target") else None), "timeZone": copy.get("timeZone"),
            "cost": (str(copy["cost"])[:120] if copy.get("cost") else None)}


def activate_ui_action(cur, auth, artifact, manifest, request, *, runtime=None, now=None, supported=None):
    now = now if now is not None else _now()
    issued = ui_capabilities.action_binding(manifest, request.get("actionId"))
    decision = ui_capabilities.permission_decision(auth, issued["binding"], kind="action", inputs=request.get("inputs")) if issued else None
    if decision is not None and decision.outcome == "deny":
        raise AlphaError("Rafii is not allowed to do this with your current permissions.", 403, code="agent_permission_denied")
    effective = ui_capabilities.current(cur, auth, manifest)
    _require_drawable(artifact, supported)
    binding = _binding(effective, request.get("actionId"), manifest, auth.member)
    if not ui_capabilities._allows(auth.member, binding.requirement):
        raise AlphaError("Your role in this workspace can't do this.", 403, code="ui_forbidden")
    revision = int(request.get("artifactRevision") or 0)
    _require_current(artifact, revision)
    from ..hosted import throttle
    throttle(cur, f"ui-activate:{auth.principal}:{artifact['id']}", ACTIVATIONS_PER_MINUTE, 60)
    inputs = ui_domain.validate(binding.inputs, request.get("inputs") or {})
    dctx = _context(runtime, cur, auth, artifact, effective, inputs, now)
    # The confirmation reads the current record (and refuses a missing/foreign target) without changing anything.
    cur.execute("SAVEPOINT ui_activation_read")
    try:
        copy = binding.confirm(dctx, inputs)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ui_activation_read")
        cur.execute("RELEASE SAVEPOINT ui_activation_read")
    digest = ui_contracts.input_digest(binding.action_id, inputs)
    activation_id = ui_contracts.new_activation_id()
    expires = now + ui_contracts.BOUNDS["activationSeconds"]
    cur.execute("INSERT INTO public.pr_ui_activations(id,workspace_id,principal,artifact_id,artifact_revision,action_id,input_digest,binding_version,expires_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s))",
                (activation_id, auth.workspace_id, auth.principal, artifact["id"], revision, binding.action_id, digest, int(effective.get("bindingVersion") or 1), expires))
    confirmation = _confirmation(binding, copy or {})
    if getattr(auth, "authz_mode", "off") == "enforce" and decision is not None:
        confirmation["required"] = decision.required != "none"
    return {"activationId": activation_id, "inputDigest": digest, "expiresAt": common.iso(expires), "confirmation": confirmation}


def _stored(cur, workspace_id, key):
    cur.execute("SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,activation_id,state,outcome FROM public.pr_ui_actions "
                "WHERE workspace_id=%s AND idempotency_key=%s FOR UPDATE", (workspace_id, key))
    row = cur.fetchone()
    if not row:
        return None
    outcome = row[7]
    if isinstance(outcome, str):
        outcome = json.loads(outcome)
    return {"principal": row[0], "artifactId": row[1], "artifactRevision": row[2], "actionId": row[3], "inputDigest": row[4], "activationId": row[5],
            "state": row[6], "outcome": outcome}


def _consume_activation(cur, auth, artifact, request, digest, binding_version, now) -> None:
    cur.execute("SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version,extract(epoch from expires_at),used_at IS NOT NULL "
                "FROM public.pr_ui_activations WHERE id=%s AND workspace_id=%s FOR UPDATE", (request["activationId"], auth.workspace_id))
    row = cur.fetchone()
    refused = AlphaError("This confirmation is no longer valid. Confirm again.", 409, code="ui_activation")
    if not row:
        raise refused
    principal, artifact_id, revision, action_id, input_digest, version, expires, used = row
    if principal != auth.principal or artifact_id != artifact["id"] or action_id != request["actionId"] or input_digest != digest:
        raise refused
    if revision != request["artifactRevision"] or revision != int(artifact.get("revision") or 0) or int(version) != int(binding_version):
        raise AlphaError("This view changed since you confirmed. Reload it and try again.", 409, code="ui_revision_stale")
    if used:
        raise AlphaError("This confirmation was already used. Confirm again.", 409, code="ui_activation_used")
    if float(expires) <= now:
        raise AlphaError("This confirmation expired. Confirm again.", 409, code="ui_activation_expired")
    cur.execute("UPDATE public.pr_ui_activations SET used_at=now() WHERE id=%s AND workspace_id=%s", (request["activationId"], auth.workspace_id))


def _result_of(binding, key, receipt: ui_domain.Receipt) -> dict:
    verified = bool(receipt.verified) and receipt.outcome == "applied"
    result = ui_contracts.action_result(binding.action_id, key, receipt.outcome, verified=verified, receipt_ref=receipt.receipt_ref, proposal_ref=receipt.proposal_ref,
                                        changed_refs=receipt.changed_refs, invalidation_keys=receipt.invalidation_keys, next_context=receipt.next_context)
    if receipt.message:
        result["nextContext"] = {**result["nextContext"], "message": str(receipt.message)[:300]}
    return result


def _refusal(error: AlphaError) -> ui_domain.Receipt:
    outcome = REFUSAL_OUTCOMES.get(error.status, "failed")
    return ui_domain.Receipt(outcome=outcome, message=str(error)[:300], next_context={"code": (error.code or "")[:60] or None})


class Deferred:
    """execute_ui_action's answer for a two-phase action: the receipt row is pending (committed with the consumed activation);
    execute_http runs the original service OUTSIDE the workspace lock, then finalizes the receipt (or reconciles it)."""

    def __init__(self, binding, key, inputs, *, reconcile: bool):
        self.binding, self.key, self.inputs, self.reconcile = binding, key, inputs, reconcile


def _replay_intent(cur, auth, artifact, binding, request, digest, key, now, binding_version):
    """Creates and prepares are deduplicated per artifact revision + exact inputs: a second tab (another key) confirming the
    same thing gets the first result, and no second campaign/proposal/profile is made."""
    cur.execute("SELECT idempotency_key,outcome FROM public.pr_ui_actions WHERE workspace_id=%s AND artifact_id=%s AND artifact_revision=%s AND action_id=%s "
                "AND input_digest=%s AND state='done' AND outcome->>'outcome' IN ('prepared','applied') ORDER BY created_at LIMIT 1",
                (auth.workspace_id, artifact["id"], request["artifactRevision"], binding.action_id, digest))
    row = cur.fetchone()
    if not row:
        return None
    first = row[1] if isinstance(row[1], dict) else json.loads(row[1])
    _consume_activation(cur, auth, artifact, request, digest, binding_version, now)
    result = {**first, "idempotencyKey": key, "nextContext": {**(first.get("nextContext") or {}), "sameAs": row[0]}}
    cur.execute("INSERT INTO public.pr_ui_actions(workspace_id,idempotency_key,principal,artifact_id,artifact_revision,action_id,input_digest,activation_id,state,outcome) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'done',%s::jsonb)",
                (auth.workspace_id, key, auth.principal, artifact["id"], request["artifactRevision"], binding.action_id, digest, request["activationId"],
                 json.dumps(result, ensure_ascii=False, default=str)))
    return result


def execute_ui_action(cur, auth, artifact, manifest, request, *, runtime=None, now=None, supported=None):
    now = now if now is not None else _now()
    issued = ui_capabilities.action_binding(manifest, request.get("actionId"))
    decision = ui_capabilities.permission_decision(auth, issued["binding"], kind="action", inputs=request.get("inputs")) if issued else None
    permission_denied = decision is not None and decision.outcome == "deny"
    effective = ui_capabilities.current(cur, auth, manifest)
    _require_drawable(artifact, supported)   # before the stored receipt, the activation and the command
    binding = issued["binding"] if permission_denied and issued else _binding(effective, request.get("actionId"), manifest, auth.member)
    key = request["idempotencyKey"]
    inputs = ui_domain.validate(binding.inputs, request.get("inputs") or {})
    digest = ui_contracts.input_digest(binding.action_id, inputs)
    stored = _stored(cur, auth.workspace_id, key)
    if stored is not None:
        if stored["inputDigest"] != digest or stored["actionId"] != binding.action_id or stored["artifactId"] != artifact["id"] or stored["principal"] != auth.principal:
            raise AlphaError("This request id was already used for a different action.", 409, code="ui_idempotency_conflict")
        if stored["state"] == "done" and isinstance(stored["outcome"], dict):
            return stored["outcome"]
        if binding.two_phase:
            return Deferred(binding, key, inputs, reconcile=True)
        # A one-phase pending row never survives a commit (it is written in the command's own transaction).
        raise AlphaError("This action is still being processed. Check again in a moment.", 409, code="ui_action_pending")
    if permission_denied:
        # A denied attempt still gets a stable receipt, but only for an activation
        # issued to this person and exact request. Revocation may already mark it used.
        cur.execute("SELECT 1 FROM public.pr_ui_activations WHERE id=%s AND workspace_id=%s AND principal=%s AND artifact_id=%s "
                    "AND action_id=%s AND input_digest=%s AND artifact_revision=%s", (request["activationId"], auth.workspace_id, auth.principal,
                    artifact["id"], binding.action_id, digest, request["artifactRevision"]))
        if not cur.fetchone():
            raise AlphaError("This confirmation is no longer valid.", 409, code="ui_activation")
        result = _result_of(binding, key, _refusal(AlphaError("Rafii's permission for this action was revoked.", 403, code="agent_permission_denied")))
        cur.execute("INSERT INTO public.pr_ui_actions(workspace_id,idempotency_key,principal,artifact_id,artifact_revision,action_id,input_digest,activation_id,state,outcome) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'done',%s::jsonb)", (auth.workspace_id, key, auth.principal, artifact["id"], request["artifactRevision"],
                    binding.action_id, digest, request["activationId"], json.dumps(result)))
        return result
    if not ui_capabilities._allows(auth.member, binding.requirement):
        raise AlphaError("Your role in this workspace can't do this.", 403, code="ui_forbidden")
    _require_current(artifact, int(request.get("artifactRevision") or 0))
    binding_version = effective.get("bindingVersion") or 1
    if binding.dedupe == "intent":
        replayed = _replay_intent(cur, auth, artifact, binding, request, digest, key, now, binding_version)
        if replayed is not None:
            return replayed
    _consume_activation(cur, auth, artifact, request, digest, binding_version, now)
    cur.execute("INSERT INTO public.pr_ui_actions(workspace_id,idempotency_key,principal,artifact_id,artifact_revision,action_id,input_digest,activation_id,state) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (auth.workspace_id, key, auth.principal, artifact["id"], request["artifactRevision"], binding.action_id, digest, request["activationId"]))
    if binding.two_phase:
        return Deferred(binding, key, inputs, reconcile=False)
    dctx = _context(runtime, cur, auth, artifact, effective, inputs, now)
    cur.execute("SAVEPOINT ui_action_command")
    try:
        receipt = binding.execute(dctx, inputs, key)
        cur.execute("RELEASE SAVEPOINT ui_action_command")
    except AlphaError as error:
        cur.execute("ROLLBACK TO SAVEPOINT ui_action_command")
        if error.status >= 500 and error.status != 503:
            raise
        receipt = _refusal(error)
    if not isinstance(receipt, ui_domain.Receipt) or receipt.outcome not in ui_contracts.ACTION_OUTCOMES:
        raise AlphaError("The action finished without a result Rafii can show.", 500, code="ui_action_shape")
    if binding.prepare_only and receipt.outcome == "applied":
        raise AlphaError("A prepared change can't be reported as applied.", 500, code="ui_action_shape")
    result = _result_of(binding, key, receipt)
    cur.execute("UPDATE public.pr_ui_actions SET state='done',outcome=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND idempotency_key=%s",
                (json.dumps(result, ensure_ascii=False, default=str), auth.workspace_id, key))
    log.info(json.dumps({"event": "ui.action", "action": binding.action_id, "outcome": result["outcome"], "verified": result["verified"]}))
    return result


def activate_http(runtime, workspace_id, token, request):
    from .ui_http import ui_transaction
    with ui_transaction(runtime, token, workspace_id, "read") as (cur, auth):
        artifact, manifest = ui_capabilities.load_artifact(cur, auth, request["artifactId"])
        return activate_ui_action(cur, auth, artifact, manifest, request, runtime=runtime)


def execute_http(runtime, workspace_id, token, request):
    from .ui_http import ui_transaction
    with ui_transaction(runtime, token, workspace_id, "read") as (cur, auth):
        artifact, manifest = ui_capabilities.load_artifact(cur, auth, request["artifactId"])
        out = execute_ui_action(cur, auth, artifact, manifest, request, runtime=runtime)
    if not isinstance(out, Deferred):
        return out
    return _second_phase(runtime, workspace_id, token, auth, out)


def _second_phase(runtime, workspace_id, token, auth, deferred: Deferred) -> dict:
    """Run (or reconcile) a two-phase action outside every lock, then store its receipt once. A reconcile that can't yet
    tell the outcome leaves the receipt pending and says so; it never re-runs the paid call."""
    binding = deferred.binding
    if deferred.reconcile:
        from .ui_domain import voice
        reconciler = getattr(voice, "ACTION_RECONCILERS", {}).get(binding.action_id)
        receipt = reconciler(runtime, token, auth, deferred.inputs, deferred.key) if reconciler else ui_domain.Receipt(
            outcome="pending", message="This action is still being processed. Check again in a moment.")
    else:
        try:
            from .ui_http import ui_transaction
            with ui_transaction(runtime, token, workspace_id, "read") as (cur, fresh_auth):
                decision = ui_capabilities.permission_decision(fresh_auth, binding, kind="action", inputs=deferred.inputs)
                if decision is not None and decision.outcome == "deny":
                    raise AlphaError("Rafii's permission changed before dispatch.", 403, code="agent_permission_revoked")
            receipt = binding.execute(runtime, token, fresh_auth, deferred.inputs, deferred.key)
        except AlphaError as error:
            if error.status >= 500 and error.status != 503:
                receipt = ui_domain.Receipt(outcome="failed", message="The action failed. Its cost, if any, is settled by the original service.")
            else:
                receipt = _refusal(error)
    result = _result_of(binding, deferred.key, receipt)
    if result["outcome"] != "pending":
        from .ui_http import ui_transaction
        with ui_transaction(runtime, token, workspace_id, "read") as (cur, _auth):
            cur.execute("UPDATE public.pr_ui_actions SET state='done',outcome=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND idempotency_key=%s AND state='pending'",
                        (json.dumps(result, ensure_ascii=False, default=str), workspace_id, deferred.key))
            if cur.rowcount == 0:
                stored = _stored(cur, workspace_id, deferred.key)
                if stored and stored["state"] == "done" and isinstance(stored["outcome"], dict):
                    return stored["outcome"]
    log.info(json.dumps({"event": "ui.action", "action": binding.action_id, "outcome": result["outcome"], "verified": result["verified"], "phase": 2}))
    return result
