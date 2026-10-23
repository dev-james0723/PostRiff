"""Save original text as new, unapproved drafts without a writer or provider call.

This is a trusted state command, invoked by the normal authenticated repository
transaction. It never refreshes an existing draft or changes the shared brief.
"""
import copy
import re

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError, uid
from . import creation_capabilities, intent, locales
from .contracts import digest

ACTION = "manual_draft_create"
MAX_TEXT = 10000
MAX_DESTINATIONS = 20
_REQUEST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FIELDS = {"text", "destinations", "requestId", "capabilityRevision"}
_DESTINATION_FIELDS = {"platform", "language", "channelId", "format"}


def create(state, actor, payload, at):
    """Append only, with server-side destinations and retry identity validation."""
    if state.get("workspace", {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403)
    if not isinstance(payload, dict) or set(payload) - _FIELDS:
        raise AlphaError("Save only original text and its selected destinations.")
    text = payload.get("text")
    # Validate without domain.clean(): spaces and line endings are authored content.
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
        raise AlphaError("Enter original text, up to 10,000 characters.")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise AlphaError("Use valid Unicode text.") from error
    request_id = payload.get("requestId")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise AlphaError("Start a new save request.")
    revision = payload.get("capabilityRevision")
    if revision is not None and (not isinstance(revision, str) or not revision or len(revision) > 128):
        raise AlphaError("Reload the destination list before saving.")
    raw = payload.get("destinations")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_DESTINATIONS:
        raise AlphaError("Choose 1–20 destinations for this text.")
    destinations = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - _DESTINATION_FIELDS:
            raise AlphaError("Choose valid destinations for this text.")
        channel_id = item.get("channelId")
        if channel_id is not None and (not isinstance(channel_id, str) or not channel_id or len(channel_id) > 200):
            raise AlphaError("Choose an account in this workspace.")
        destinations.append({**item, "language": locales.canonical(item.get("language"))})
    # The same rollout, native-format, locale and channel ownership checks used by
    # IdeasService; validation completes before any part of stored state changes.
    projection = creation_capabilities.projection()
    creation_capabilities.validate_destinations(destinations, revision=revision, proj=projection)
    for destination in destinations:
        row = projection.by_platform.get(destination["platform"])
        # The legacy publisher represents these platforms' default post with no
        # explicit format. Only normalize the registry-confirmed default; other
        # native formats stay explicit and retain the normal export-only gate.
        if (destination["platform"] not in creation_capabilities.DEFAULT_FORMATS and row
                and destination.get("format") == row["defaultFormat"]):
            destination.pop("format")
    # An explicit default and an omitted default are the same destination.
    creation_capabilities.validate_destinations(destinations, revision=revision, proj=projection)
    fingerprint = digest({"text": text, "destinations": destinations})
    destinations = intent.bind_accounts(destinations, state)
    prior = [v for v in state.get("variants", []) if v.get("manualRequestId") == request_id]
    if prior:
        if any(v.get("manualRequestDigest") != fingerprint or v.get("manualAuthorId") != actor for v in prior):
            raise AlphaError("This save request already belongs to different content. Start a new save.", 409,
                             code="manual_draft_request_conflict")
        return state

    created = []
    style_revision = learning.revision(copy.deepcopy(state))
    for destination in destinations:
        created.append({
            "id": uid(), **{k: v for k, v in destination.items() if k in (_DESTINATION_FIELDS | {"account"}) and v is not None},
            "text": text, "revision": 1, "createdAt": at,
            "voiceRevision": state["speaker"].get("activeRevision"),
            "speakerId": state["speaker"].get("id"),
            "styleRevision": style_revision,
            "briefRevision": state["brief"]["revision"],
            "sourceIds": [], "voiceSourceIds": [], "voiceBindings": [],
            "warnings": [], "unknowns": [], "openings": [], "media": [],
            "customized": True, "needsReview": True, "blockedByRetraction": False,
            "selectedOpening": 0, "localPreferences": {}, "proposedUpdate": None,
            # Editorial classification is independent of the destination's native
            # format. Never inherit a previous research draft's selected template.
            "contentTypeId": "unclassified", "contentTypeVersion": "legacy", "formatId": None,
            "contentSkillRouteIds": [],
            "revisions": [{"revision": 1, "text": text, "origin": "author-written", "at": at}],
            "provenance": {"origin": "author-written", "model": None},
            "manualRequestId": request_id, "manualRequestDigest": fingerprint, "manualAuthorId": actor,
        })
    state["variants"].extend(created)
    state["savedAt"] = None
    return state
