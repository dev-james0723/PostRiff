"""Owner consent for sending workspace photos and video frames to a model (chat-context SPEC §5.12, §8.1).

One gate, `state.mediaEgress`, covers every path that shows a workspace photo or frame to a model. The consent is bound
to processors: the server names them from its own configuration, never the client, and a new provider or model family
needs the owner to confirm again. Absent means off.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

ACTION = "media_egress"
SCOPE = ("photo", "video_frames", "photo_edit")   # what the consent covers (SPEC §5.13)
PURPOSES = ("vision", "image")
PROVIDER_LABELS = {"openai": "OpenAI", "gateway": "Vercel AI Gateway"}
CONSENT_MESSAGE = "The workspace owner hasn't allowed Rafii to look at photos and videos."


def processor(provider, model):
    """{id, label} for a route: `openai` + `openai/gpt-6-sol` → `openai:gpt-6` ("OpenAI")."""
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        return None
    tail = model.split("/")[-1]
    family = tail.rsplit("-", 1)[0] if "-" in tail else tail
    return {"id": f"{provider}:{family}", "label": PROVIDER_LABELS.get(provider, provider)}


def _id(value):
    return value.get("id") if isinstance(value, dict) else value if isinstance(value, str) else None


def decision(state):
    found = (state or {}).get("mediaEgress")
    return found if isinstance(found, dict) else {"cloud": False, "processors": []}


def processor_ids(state):
    return [pid for pid in (_id(p) for p in decision(state).get("processors") or []) if pid]


def allowed(state, processor_or_id):
    """True only when photo reading is on and this exact processor was confirmed by the owner."""
    pid = _id(processor_or_id)
    return decision(state).get("cloud") is True and bool(pid) and pid in processor_ids(state)


def require(state, purpose, processor_or_id):
    if purpose not in PURPOSES:
        raise AlphaError("Unsupported media purpose.", 400)
    if not allowed(state, processor_or_id):
        raise AlphaError(CONSENT_MESSAGE, 403, code="consent_required")


def apply_action(state, action, payload, actor, now, processors=()):
    """Handle `media_egress` (owner only, see permissions); return True when consumed.

    `processors` are the server's current {id, label} routes. Turning on keeps earlier confirmed processors and adds
    the current ones; turning off clears them (the caller purges stored notes in the same transaction)."""
    if action != ACTION:
        return False
    payload = payload if isinstance(payload, dict) else {}
    if "processors" in payload:
        raise AlphaError("Invalid consent request.", 400)
    if not set(payload) <= {"cloud", "confirmed"} or not isinstance(payload.get("cloud"), bool) or payload.get("confirmed") is not True:
        raise AlphaError("Choose whether Rafii may look at photos and videos, and confirm it.", 400)
    current = [p for p in processors or () if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"]]
    if payload["cloud"] and not current:
        raise AlphaError("Photo reading isn't available here.", 409, code="reader_unavailable")
    kept = []
    if payload["cloud"]:
        earlier = [p for p in decision(state).get("processors") or [] if isinstance(p, dict)] if decision(state).get("cloud") is True else []
        for item in earlier + [{"id": p["id"], "label": str(p.get("label") or p["id"])} for p in current]:
            if item["id"] not in {k["id"] for k in kept}:
                kept.append({"id": item["id"], "label": item.get("label") or item["id"]})
    state["mediaEgress"] = {"cloud": payload["cloud"], "decidedBy": actor, "decidedAt": now, "processors": kept, "scope": list(SCOPE)}
    return True


def summary(state, current):
    """The Memory page row (SPEC §5.12). `current` = {"vision": {id, label} | None, "image": {id, label} | None}."""
    current = {purpose: (current or {}).get(purpose) for purpose in PURPOSES}
    found = decision(state)
    on = found.get("cloud") is True
    listed = processor_ids(state)
    reconfirm = on and any(p and _id(p) not in listed for p in current.values())
    return {"cloud": on, "decidedAt": found.get("decidedAt"), "decidedBy": found.get("decidedBy"),
            "processors": [{"id": p["id"], "label": p.get("label") or p["id"]} for p in found.get("processors") or [] if isinstance(p, dict) and p.get("id")] if on else [],
            "current": current, "reconfirm": bool(reconfirm), "available": current["vision"] is not None}
