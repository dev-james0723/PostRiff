"""The workspace default writer ("Auto"): the managed model a request that names no writer drafts with.

Stored in workspace state as writerDefaults = {"model": id|None, "decidedBy", "decidedAt"}. Only an owner changes it
(permissions.ACTION_CLASSES), with an explicit confirmation, because it decides which AI provider receives the sources
the workspace allowed for the cloud. None means Rafii's default for this deployment (POSTRIFF_MODEL_ID). A choice is
checked against what the deployment offers when it is made and again every time it is used: POSTRIFF_MODEL_IDS or the
price table can drop a model later, and Auto then writes with the deployment's default and says so, never silently.
Hosted only: the local SQLite store does not dispatch this action.
"""
from postriff_alpha.domain import AlphaError

ACTION = "writer_defaults"
KEY = "writerDefaults"
UNOFFERED = "Choose a writer this workspace offers."


def settings(state):
    """The stored decision, normalised: a missing or malformed value reads as Rafii's default."""
    raw = (state or {}).get(KEY)
    if not isinstance(raw, dict):
        return {"model": None, "decidedBy": None, "decidedAt": None}
    model = raw.get("model") if isinstance(raw.get("model"), str) and raw.get("model") else None
    return {"model": model, "decidedBy": raw.get("decidedBy"), "decidedAt": raw.get("decidedAt")}


def _priced(runtime, model):
    priced = getattr(runtime, "priced", None)
    return bool(priced(model)) if callable(priced) else True


def _offers(runtime, model):
    """The managed writer owns this model, lists it as qualified and has a price for it."""
    if not runtime.owns(model) or not _priced(runtime, model):
        return False
    listed = next((m for m in runtime.list_supported_models() if m.get("id") == model), None)
    return bool(listed and listed.get("qualified"))


def apply_action(state, action, payload, actor, now, writers):
    """Handle `writer_defaults` (owner only); return True when consumed. `writers` returns the mounted managed paid
    cloud writer, or None where there is none (then only clearing the default is possible)."""
    if action != ACTION:
        return False
    if payload.get("confirmed") is not True or "model" not in payload:
        raise AlphaError("Choose the workspace's default writer, and confirm it.", 400)
    model = payload.get("model")
    if model is not None:
        if not isinstance(model, str) or not model:
            raise AlphaError(UNOFFERED, 400)
        runtime = writers() if callable(writers) else None
        if runtime is None:
            raise AlphaError("No managed writer is available here.", 409)
        if not _offers(runtime, model):
            raise AlphaError(UNOFFERED, 400)
    state[KEY] = {"model": model, "decidedBy": actor, "decidedAt": now}
    return True


def resolve(state, runtime):
    """(model id, source "workspace"|"deployment", note|None) for a request on Auto, with the managed `runtime`: the
    workspace default while that writer still owns and prices it, else the deployment default with a note."""
    chosen = settings(state)["model"]
    if chosen is None:
        return runtime.model, "deployment", None
    if runtime.owns(chosen) and _priced(runtime, chosen):
        return chosen, "workspace", None
    return runtime.model, "deployment", f"The workspace default writer {chosen} is no longer offered, so Rafii used {runtime.model}."
