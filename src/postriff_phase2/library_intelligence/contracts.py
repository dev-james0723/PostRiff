"""Library Intelligence v1 contracts (engineering spec §5).

Typed, validated shapes shared by the UI, the Agent tools, source packs and background work. Validation
raises AlphaError(400, code='library_contract') with a bounded message; nothing here touches the database.
Public ids are opaque 32-hex strings; `asset_key`/`asset_uuid` are the only dashed/undashed conversion.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from postriff_alpha.domain import AlphaError

CONTRACT_VERSION = "rafii-library/1"
KEY = re.compile(r"^[0-9a-f]{32}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PURPOSES = ("browse", "answer", "draft_evidence", "voice", "memory", "public_use")
PROCESSING_LOCATIONS = ("local", "cloud")
PROVIDER_CATEGORIES = ("extract", "ocr", "asr", "vision", "embedding", "llm")
CAPABILITIES = ("preview", "extract", "transcribe", "visual", "embed_text", "embed_visual", "understand")
CAPABILITY_STATES = ("not_requested", "queued", "processing", "ready", "partial", "unsupported", "failed", "cancelled",
                     "blocked_permission", "blocked_budget")
SEARCH_MODES = ("lexical", "semantic", "visual")
SCOPE_KINDS = ("workspace", "collection", "selection")
LOCATOR_KINDS = ("page", "time", "text", "slide", "sheet", "imageRegion")
ANNOTATION_ORIGINS = ("extracted", "ai_suggested", "user_confirmed")
RELATIONS = ("derived_from", "version_of", "similar_to", "used_in", "supersedes")
ACTION_STATUSES = ("applied", "requires_confirmation", "conflict", "denied")
SUPPORT = ("supported", "conflicting", "insufficient")
DEFAULT_LIMIT, MAX_LIMIT = 30, 100
MAX_SELECTION = 200
MAX_QUERY = 500


def fail(message: str, status: int = 400, code: str = "library_contract"):
    raise AlphaError(message[:300], status, code=code)


# --- identity -------------------------------------------------------------------------------------------------------
def asset_key(value) -> str:
    """The one adapter between UUIDs (database) and opaque 32-hex keys (contracts, legacy media ids)."""
    if isinstance(value, uuid.UUID):
        return value.hex
    text = str(value or "").strip().lower()
    if KEY.fullmatch(text):
        return text
    try:
        return uuid.UUID(text).hex
    except (ValueError, AttributeError):
        fail("Choose a valid Library item.", 404, "library_unavailable")


def asset_uuid(value) -> uuid.UUID:
    return uuid.UUID(hex=asset_key(value))


def _key(value, label="item") -> str:
    if not isinstance(value, str) or not KEY.fullmatch(value):
        fail(f"Choose a valid Library {label}.")
    return value


def asset_ref(value) -> dict:
    """AssetRef {assetId, versionId, sha256}. sha256 may be '' for a version still being verified."""
    if not isinstance(value, dict) or not set(value) <= {"assetId", "versionId", "sha256"}:
        fail("Use an asset reference with assetId, versionId and sha256.")
    asset = _key(value.get("assetId"), "item")
    version = _key(value.get("versionId") or asset, "version")
    sha = value.get("sha256") or ""
    if sha and (not isinstance(sha, str) or not SHA256.fullmatch(sha)):
        fail("Use a valid content hash.")
    return {"assetId": asset, "versionId": version, "sha256": sha}


def ref_key(ref: dict) -> str:
    return f"{ref['assetId']}:{ref['versionId']}"


# --- locators -------------------------------------------------------------------------------------------------------
def _int(value, label, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        fail(f"{label} is out of range.")
    return value


def _unit(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        fail(f"{label} must be between 0 and 1.")
    return float(value)


def locator(value, *, text_length: int | None = None, duration_ms: int | None = None, pages: int | None = None,
            slides: int | None = None) -> dict:
    """Validate a Locator. Optional bounds come from the referenced version; out-of-bounds locators are refused,
    never clamped, so a citation cannot silently point somewhere else."""
    if not isinstance(value, dict) or value.get("kind") not in LOCATOR_KINDS:
        fail("Use a page, time, text, slide, sheet or image-region locator.")
    kind = value["kind"]
    allowed = {"page": {"kind", "page", "section", "textStart", "textEnd"}, "time": {"kind", "startMs", "endMs"},
               "text": {"kind", "start", "end"}, "slide": {"kind", "slide"}, "sheet": {"kind", "sheetName", "cellRange"},
               "imageRegion": {"kind", "frameTimeMs", "x", "y", "width", "height"}}[kind]
    if not set(value) <= allowed:
        fail("This locator has unexpected fields.")
    out: dict[str, Any] = {"kind": kind}
    if kind == "page":
        out["page"] = _int(value.get("page"), "Page", 1, pages or 100000)
        if value.get("section") is not None:
            section = value["section"]
            if not isinstance(section, str) or not 1 <= len(section) <= 200:
                fail("Use a short section label.")
            out["section"] = section
        if "textStart" in value or "textEnd" in value:
            start, end = _int(value.get("textStart"), "Text start"), _int(value.get("textEnd"), "Text end")
            if end < start:
                fail("Text end must follow its start.")
            out.update(textStart=start, textEnd=end)
    elif kind == "time":
        start, end = _int(value.get("startMs"), "Start time"), _int(value.get("endMs"), "End time")
        if end <= start:
            fail("A moment must end after it starts.")
        if duration_ms is not None and end > duration_ms:
            fail("This moment ends after the recording.")
        out.update(startMs=start, endMs=end)
    elif kind == "text":
        start, end = _int(value.get("start"), "Text start"), _int(value.get("end"), "Text end")
        if end < start:
            fail("Text end must follow its start.")
        if text_length is not None and end > text_length:
            fail("This passage is outside the source text.")
        out.update(start=start, end=end)
    elif kind == "slide":
        out["slide"] = _int(value.get("slide"), "Slide", 1, slides or 100000)
    elif kind == "sheet":
        name, cells = value.get("sheetName"), value.get("cellRange")
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            fail("Use a sheet name.")
        if not isinstance(cells, str) or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}(:[A-Z]{1,3}[1-9][0-9]{0,6})?", cells):
            fail("Use a cell range such as B4 or B4:C9.")
        out.update(sheetName=name, cellRange=cells)
    else:
        if value.get("frameTimeMs") is not None:
            out["frameTimeMs"] = _int(value["frameTimeMs"], "Frame time")
        x, y = _unit(value.get("x"), "x"), _unit(value.get("y"), "y")
        w, h = _unit(value.get("width"), "width"), _unit(value.get("height"), "height")
        if w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            fail("An image region must stay inside the image.")
        out.update(x=x, y=y, width=w, height=h)
    return out


def locator_label(loc: dict | None) -> str:
    """Plain words for a locator; never invents a page number that the locator does not carry."""
    if not loc:
        return "whole item"
    kind = loc["kind"]
    if kind == "page":
        return f"page {loc['page']}" + (f", {loc['section']}" if loc.get("section") else "")
    if kind == "time":
        return f"{_clock(loc['startMs'])}–{_clock(loc['endMs'])}"
    if kind == "text":
        return f"characters {loc['start']}–{loc['end']}"
    if kind == "slide":
        return f"slide {loc['slide']}"
    if kind == "sheet":
        return f"{loc['sheetName']}!{loc['cellRange']}"
    return "image region" + (f" at {_clock(loc['frameTimeMs'])}" if loc.get("frameTimeMs") is not None else "")


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


# --- purposes and requests ------------------------------------------------------------------------------------------
def purpose(value) -> str:
    if value not in PURPOSES:
        fail("Choose browse, answer, draft evidence, voice, memory or public use.")
    return value


def processing_grant(value) -> dict | None:
    """ProcessingGrant request {location, category}; None means no processing (browse/local lexical only)."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("location") not in PROCESSING_LOCATIONS or value.get("category") not in PROVIDER_CATEGORIES:
        fail("Name a processing location (local or cloud) and provider category.")
    return {"location": value["location"], "category": value["category"]}


def scope(value) -> dict:
    value = value if value is not None else {"kind": "workspace"}
    if not isinstance(value, dict) or value.get("kind") not in SCOPE_KINDS:
        fail("Choose the entire Library, a collection or selected items.")
    kind = value["kind"]
    if kind == "workspace":
        return {"kind": "workspace"}
    if kind == "collection":
        return {"kind": "collection", "collectionId": _key(str(value.get("collectionId") or "").replace("-", ""), "collection")}
    refs = value.get("assetRefs")
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_SELECTION:
        fail(f"Select from 1 to {MAX_SELECTION} items.")
    parsed = [asset_ref(r) for r in refs]
    if len({ref_key(r) for r in parsed}) != len(parsed):
        fail("Each selected item may appear once.")
    return {"kind": "selection", "assetRefs": parsed}


FILTER_KEYS = {"kinds", "tags", "createdFrom", "createdTo", "timeZone", "rights", "usage", "orientation", "minDurationMs",
               "maxDurationMs", "collectionId", "languages", "capability", "capabilityState"}


def filters(value) -> dict:
    value = value or {}
    if not isinstance(value, dict) or not set(value) <= FILTER_KEYS:
        fail("Use supported Library filters.")
    out: dict[str, Any] = {}
    if "kinds" in value:
        kinds = value["kinds"]
        if not isinstance(kinds, list) or not set(kinds) <= {"image", "video", "audio", "document", "file"}:
            fail("Choose supported file types.")
        out["kinds"] = sorted(set(kinds))
    if "tags" in value:
        tags = value["tags"]
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or not 1 <= len(t) <= 40 for t in tags):
            fail("Choose up to 20 tags.")
        out["tags"] = list(dict.fromkeys(tags))
    zone = value.get("timeZone", "UTC")
    if not isinstance(zone, str) or not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}", zone):
        fail("Use an IANA time zone such as Asia/Hong_Kong.")
    for bound in ("createdFrom", "createdTo"):
        if bound in value:
            if not isinstance(value[bound], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[bound]):
                fail("Use dates such as 2026-10-08.")
            out[bound] = value[bound]
            out["timeZone"] = zone
    if "rights" in value:
        if value["rights"] not in ("approved_public", "needs_review", "internal", "unknown"):
            fail("Choose a rights filter.")
        out["rights"] = value["rights"]
    if "usage" in value:
        if value["usage"] not in ("used", "unused"):
            fail("Choose used or unused.")
        out["usage"] = value["usage"]
    if "orientation" in value:
        if value["orientation"] not in ("portrait", "landscape", "square"):
            fail("Choose an orientation.")
        out["orientation"] = value["orientation"]
    for bound in ("minDurationMs", "maxDurationMs"):
        if bound in value:
            out[bound] = _int(value[bound], "Duration", 0, 86_400_000)
    if "collectionId" in value:
        out["collectionId"] = _key(str(value["collectionId"]).replace("-", ""), "collection")
    if "languages" in value:
        langs = value["languages"]
        if not isinstance(langs, list) or len(langs) > 8 or any(not isinstance(x, str) or not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", x) for x in langs):
            fail("Use language codes such as yue, zh-Hant or en.")
        out["languages"] = langs
    if "capability" in value or "capabilityState" in value:
        if value.get("capability") not in CAPABILITIES or value.get("capabilityState") not in CAPABILITY_STATES:
            fail("Choose a processing capability and state.")
        out.update(capability=value["capability"], capabilityState=value["capabilityState"])
    return out


def search_request(value) -> dict:
    if not isinstance(value, dict):
        fail("Send a Library search request.")
    allowed = {"query", "scope", "purpose", "filters", "modes", "similarTo", "cursor", "limit"}
    if not set(value) <= allowed:
        fail("This search request has unexpected fields.")
    query = value.get("query", "")
    if not isinstance(query, str) or len(query) > MAX_QUERY or "\x00" in query:
        fail(f"Use a query of at most {MAX_QUERY} characters.")
    modes = value.get("modes") or ["lexical", "semantic"]
    if not isinstance(modes, list) or not modes or not set(modes) <= set(SEARCH_MODES):
        fail("Choose lexical, semantic or visual search.")
    limit = value.get("limit", DEFAULT_LIMIT)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        fail(f"Use a page size from 1 to {MAX_LIMIT}.")
    cursor = value.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 2000):
        fail("This page link is invalid. Refresh the results.", 409, "library_cursor_stale")
    similar = asset_ref(value["similarTo"]) if value.get("similarTo") is not None else None
    if similar and "visual" not in modes:
        modes = [*modes, "visual"]
    return {"query": query.strip(), "scope": scope(value.get("scope")), "purpose": purpose(value.get("purpose", "browse")),
            "filters": filters(value.get("filters")), "modes": sorted(set(modes), key=SEARCH_MODES.index), "similarTo": similar,
            "cursor": cursor, "limit": limit}


def coverage(*, scope_description: str, accessible: int, indexed: int, pending: int, failed: int, modes_applied: list[str],
             partial: bool, index_generation: int) -> dict:
    for count in (accessible, indexed, pending, failed):
        if type(count) is not int or count < 0:
            fail("Coverage counts must be whole numbers.", 500, "library_internal")
    return {"scopeDescription": scope_description, "accessibleAssetCount": accessible, "indexedAssetCount": indexed,
            "pendingAssetCount": pending, "failedAssetCount": failed, "modesApplied": list(modes_applied),
            "partial": bool(partial), "indexGeneration": index_generation}


def task_context(value) -> dict:
    if not isinstance(value, dict):
        fail("Describe the task for this source pack.")
    allowed = {"taskId", "draftId", "userGoal", "audience", "channels", "locale", "personaId", "selectedSourceRefs", "scope", "purpose"}
    if not set(value) <= allowed:
        fail("This task context has unexpected fields.")
    goal = value.get("userGoal")
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1000:
        fail("Describe the goal in up to 1,000 characters.")
    out: dict[str, Any] = {"userGoal": goal.strip(), "scope": scope(value.get("scope")), "purpose": purpose(value.get("purpose", "draft_evidence"))}
    for name, limit in (("taskId", 80), ("draftId", 80), ("audience", 300), ("locale", 20), ("personaId", 80)):
        if value.get(name) is not None:
            if not isinstance(value[name], str) or not 1 <= len(value[name]) <= limit:
                fail(f"{name} is invalid.")
            out[name] = value[name]
    if value.get("channels") is not None:
        channels = value["channels"]
        if not isinstance(channels, list) or len(channels) > 12 or any(not isinstance(c, str) or not 1 <= len(c) <= 40 for c in channels):
            fail("Choose up to 12 channels.")
        out["channels"] = channels
    refs = value.get("selectedSourceRefs") or []
    if not isinstance(refs, list) or len(refs) > 40:
        fail("Select at most 40 sources.")
    out["selectedSourceRefs"] = [source_ref(r) for r in refs]
    return out


def source_ref(value) -> dict:
    """{assetRef, segmentId?, locator?} — a passage or moment inside one immutable version."""
    if not isinstance(value, dict) or not set(value) <= {"assetRef", "segmentId", "locator", "quoteHash"}:
        fail("Use a source reference with assetRef and an optional segment and locator.")
    out = {"assetRef": asset_ref(value.get("assetRef"))}
    if value.get("segmentId") is not None:
        out["segmentId"] = _key(str(value["segmentId"]).replace("-", ""), "passage")
    if value.get("locator") is not None:
        out["locator"] = locator(value["locator"])
    if value.get("quoteHash") is not None:
        if not isinstance(value["quoteHash"], str) or not SHA256.fullmatch(value["quoteHash"]):
            fail("Use a valid quote hash.")
        out["quoteHash"] = value["quoteHash"]
    return out


ACTION_TYPES = ("collection.save", "collection.override", "collection.undo", "collection.preview", "sources.select",
                "source_pack.create", "source_pack.attach", "version.link", "version.accept_replacement", "annotation.correct",
                "suggestion.set_state", "moment.save", "voice.approve_span", "voice.revoke", "metadata.update")


def action_envelope(value) -> dict:
    """ActionEnvelope from a generated UI or the deterministic Library; auth context is never accepted from it."""
    if not isinstance(value, dict):
        fail("Send a Library action.")
    allowed = {"actionId", "uiInstanceId", "actionType", "targetRefs", "expectedRevision", "idempotencyKey", "payload"}
    extra = set(value) - allowed
    if extra:
        fail("This action carries fields the server does not accept.", 400, "library_action_rejected")
    if value.get("actionType") not in ACTION_TYPES:
        fail("This action is not available in Library.", 400, "library_action_rejected")
    for name, limit in (("actionId", 80), ("uiInstanceId", 80)):
        if not isinstance(value.get(name), str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,%d}" % limit, value[name]):
            fail(f"{name} is invalid.", 400, "library_action_rejected")
    key = value.get("idempotencyKey")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{16,120}", key):
        fail("Each action needs an idempotency key of 16 to 120 characters.", 400, "library_action_rejected")
    revision = value.get("expectedRevision")
    if revision is not None and (type(revision) is not int or revision < 0):
        fail("expectedRevision must be a whole number.", 400, "library_action_rejected")
    refs = value.get("targetRefs") or []
    if not isinstance(refs, list) or len(refs) > MAX_SELECTION:
        fail(f"Target at most {MAX_SELECTION} items.", 400, "library_action_rejected")
    payload = value.get("payload") or {}
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 20000:
        fail("The action payload is too large.", 400, "library_action_rejected")
    _reject_unsafe(payload)
    return {"actionId": value["actionId"], "uiInstanceId": value["uiInstanceId"], "actionType": value["actionType"],
            "targetRefs": [asset_ref(r) for r in refs], "expectedRevision": revision, "idempotencyKey": key, "payload": payload}


UNSAFE = re.compile(r"(?i)(<\s*script|javascript:|\bselect\b[^\n]{0,40}\bfrom\b|\bdrop\s+table\b|https?://)")


def _reject_unsafe(value, depth=0):
    """Generated payloads carry identifiers and short text, never URLs, markup, SQL or tool names."""
    if depth > 8:
        fail("The action payload is nested too deeply.", 400, "library_action_rejected")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or k in ("url", "href", "sql", "tool", "mcp", "fetch", "workspaceId", "actor", "principal", "token"):
                fail("The action payload names a field the server does not accept.", 400, "library_action_rejected")
            _reject_unsafe(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _reject_unsafe(v, depth + 1)
    elif isinstance(value, str) and UNSAFE.search(value):
        fail("The action payload contains a link, markup or query text.", 400, "library_action_rejected")


def action_result(status: str, *, revision: int | None = None, result=None, warnings=()) -> dict:
    if status not in ACTION_STATUSES:
        fail("Unknown action status.", 500, "library_internal")
    out: dict[str, Any] = {"status": status, "warnings": [w for w in warnings if w]}
    if revision is not None:
        out["revision"] = revision
    if result is not None:
        out["result"] = result
    return out


def register_artifact(value) -> dict:
    if not isinstance(value, dict):
        fail("Send an artifact registration.")
    allowed = {"runId", "outputId", "sourcePackId", "contentSha256", "storageRef", "mime", "displayTitle", "originalFilename",
               "artifactRole", "parentRefs", "idempotencyKey"}
    if not set(value) <= allowed:
        fail("This registration has unexpected fields.")
    if value.get("artifactRole") != "final":
        fail("Only final deliverables are registered in Library.", 422, "library_artifact_not_final")
    for name in ("runId", "outputId"):
        if not isinstance(value.get(name), str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,80}", value[name]):
            fail(f"{name} is invalid.")
    sha = value.get("contentSha256")
    if not isinstance(sha, str) or not SHA256.fullmatch(sha):
        fail("Use the verified content hash.")
    storage = value.get("storageRef")
    if not isinstance(storage, dict) or set(storage) - {"category", "objectName"} or storage.get("category") not in ("media", "file", "video"):
        fail("Use a storage reference produced by Rafii storage.", 422, "library_artifact_storage")
    name = storage.get("objectName")
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{32}(-[0-9a-f]{8,64})?\.[a-z0-9]{1,12}", name):
        fail("Temporary, scratch or external storage paths are not registered.", 422, "library_artifact_storage")
    mime = value.get("mime")
    if not isinstance(mime, str) or not re.fullmatch(r"[a-z]+/[a-z0-9.+\-]{1,100}", mime):
        fail("Use a valid content type.")
    title = value.get("displayTitle") or ""
    filename = value.get("originalFilename") or ""
    if not isinstance(title, str) or len(title) > 160 or not isinstance(filename, str) or not 1 <= len(filename) <= 255 or "/" in filename:
        fail("Use a title and filename for the deliverable.")
    key = value.get("idempotencyKey")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{16,160}", key):
        fail("Use an idempotency key.")
    parents = value.get("parentRefs") or []
    if not isinstance(parents, list) or len(parents) > 40:
        fail("Name at most 40 parent sources.")
    pack = value.get("sourcePackId")
    if pack is not None:
        _key(pack, "source pack")
    return {"runId": value["runId"], "outputId": value["outputId"], "sourcePackId": pack, "contentSha256": sha,
            "storageRef": {"category": storage["category"], "objectName": name}, "mime": mime, "displayTitle": title.strip(),
            "originalFilename": filename, "artifactRole": "final", "parentRefs": [source_ref(p) for p in parents], "idempotencyKey": key}


# --- results ----------------------------------------------------------------------------------------------------------
def quote_hash(text: str) -> str:
    return hashlib.sha256(" ".join(str(text).split()).encode()).hexdigest()


def answer_result(answer: str, claims: list[dict], coverage_value: dict, warnings=()) -> dict:
    for claim in claims:
        if claim.get("support") not in SUPPORT or not isinstance(claim.get("text"), str):
            fail("Each claim needs text and a support state.", 500, "library_internal")
        if claim["support"] != "insufficient" and not claim.get("sourceRefs"):
            fail("A supported claim must cite a source.", 500, "library_internal")
    return {"contractVersion": CONTRACT_VERSION, "answer": answer, "claims": claims, "coverage": coverage_value,
            "warnings": [w for w in warnings if w]}


def capability_state(capability: str, state: str, **extra) -> dict:
    if capability not in CAPABILITIES or state not in CAPABILITY_STATES:
        fail("Unknown processing capability state.", 500, "library_internal")
    return {"capability": capability, "state": state, **{k: v for k, v in extra.items() if v is not None}}


# --- request context -------------------------------------------------------------------------------------------------
@dataclass
class LibraryContext:
    """Server-derived identity for one request. Never constructed from client or model input."""
    workspace_id: str
    actor: str
    membership: Any
    state: dict
    cur: Any
    now: float = field(default_factory=time.time)
    service: Any = None
    caches: dict = field(default_factory=dict)
    # Opens a fresh read context for the same verified identity (multi-phase handlers: retrieve, call a provider
    # outside the transaction, then recheck and record). None outside HTTP.
    reopen: Any = None
    # Opens the locked workspace write transaction for the same verified identity (read-mode handlers only). None elsewhere.
    open_write: Any = None

    def allows(self, requirement: str) -> bool:
        return bool(self.membership.allows(requirement))

    def require(self, requirement: str):
        if not self.allows(requirement):
            raise AlphaError("Your role can't do this.", 403, code="library_forbidden")
