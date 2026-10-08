"""One server-validated entry for Library mutations from the deterministic UI and generated task interfaces.

The envelope never carries identity: workspace and actor come from the verified context. Every target ref is
re-resolved in this workspace; the expected revision is compared server-side; a replayed idempotency key returns the
original receipt instead of applying twice; a reused key with a different request is refused. Handlers return
(status, result, revision, warnings) and never auto-retry.
"""
from __future__ import annotations

import importlib
import json

from postriff_alpha.domain import AlphaError

from ..contracts import digest
from . import contracts as c
from . import versions

# actionType -> (module, function, requirement)
HANDLERS = {
    "collection.preview": ("collections", "preview_action", "read"),
    "collection.save": ("collections", "save_action", "edit"),
    "collection.override": ("collections", "override_action", "edit"),
    "collection.undo": ("collections", "undo_action", "edit"),
    "sources.select": ("source_packs", "select_action", "read"),
    "source_pack.create": ("source_packs", "create_action", "edit"),
    "source_pack.attach": ("source_packs", "attach_action", "edit"),
    "version.link": ("relations", "link_action", "edit"),
    "version.accept_replacement": ("relations", "accept_replacement_action", "edit"),
    "annotation.correct": ("understanding", "correct_action", "edit"),
    "suggestion.set_state": ("suggestions", "set_state_action", "read"),
    "moment.save": ("media", "save_moment_action", "edit"),
    "voice.approve_span": ("voice", "approve_span_action", "owner"),
    "voice.revoke": ("voice", "revoke_action", "owner"),
    "metadata.update": ("understanding", "metadata_action", "edit"),
}
READ_ONLY = {"collection.preview", "sources.select"}


def apply(ctx, envelope: dict) -> dict:
    envelope = c.action_envelope(envelope)
    module_name, function_name, requirement = HANDLERS[envelope["actionType"]]
    if not ctx.allows(requirement):
        return c.action_result("denied", warnings=["Your role can't do this."])
    request_hash = digest({k: envelope[k] for k in ("actionType", "targetRefs", "expectedRevision", "payload")})
    if envelope["actionType"] not in READ_ONLY:
        ctx.cur.execute("SELECT actor::text,request_hash,status,result FROM public.pr_library_action_receipts WHERE workspace_id=%s AND idempotency_key=%s",
                        (ctx.workspace_id, envelope["idempotencyKey"]))
        prior = ctx.cur.fetchone()
        if prior:
            if prior[0] != ctx.actor or prior[1] != request_hash:
                return c.action_result("denied", warnings=["This action key was already used for a different request."])
            replay = prior[3] or {}
            return {**replay, "replayed": True}
    targets = []
    for ref in envelope["targetRefs"]:
        try:
            targets.append(versions.resolve(ctx, ref))
        except AlphaError as error:
            # Forged, foreign or deleted targets are denied without saying whether they exist elsewhere.
            status = "conflict" if error.code == "library_version_mismatch" else "denied"
            return c.action_result(status, warnings=[str(error) if status == "conflict" else "One of these items is unavailable."])
    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
        handler = getattr(module, function_name)
    except (ImportError, AttributeError):
        return c.action_result("denied", warnings=["This Library action is not available in this build."])
    try:
        outcome = handler(ctx, envelope, targets)
    except AlphaError as error:
        if error.status == 409:
            outcome = c.action_result("conflict", warnings=[str(error)])
        elif error.status in (401, 403, 404):
            outcome = c.action_result("denied", warnings=[str(error)])
        else:
            raise
    if envelope["actionType"] not in READ_ONLY and outcome.get("status") in ("applied", "requires_confirmation"):
        ctx.cur.execute("INSERT INTO public.pr_library_action_receipts(workspace_id,idempotency_key,actor,action_type,request_hash,status,result) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
                        (ctx.workspace_id, envelope["idempotencyKey"], ctx.actor, envelope["actionType"], request_hash, outcome["status"], json.dumps(outcome)))
    return outcome


def apply_http(ctx, request):
    return apply(ctx, request["body"])
