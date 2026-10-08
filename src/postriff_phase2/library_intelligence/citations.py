"""Source viewers for citations bound to immutable versions (engineering spec §5 AnswerResult source refs, §6, §8; T05; A034).

`resolve_locator(ctx, ref, locator)` turns a citation into an authorized viewer target at request time:
- browse is re-authorized for the verified member, and the exact `versionId` is resolved in this workspace. A citation
  made against an old version keeps opening that old version; the newest version is reported, never substituted.
- the content hash must still match, and when the citation names a passage its quote hash must still match, so an
  altered source is a 409 conflict rather than a silently different page;
- the locator is validated against the version's bounds (pages, slides, duration, text length) and never clamped;
- the target is minted per request: a private signed link of at most 300 s for normalized files (and legacy videos),
  or the authenticated media proxy path for legacy photos, which re-authorizes every fetch. Nothing persistent is
  stored or returned for a model; an expired link is refreshed by calling again, which re-checks access.

A deleted, deleting or foreign item is the same 404 as a missing one.
"""
from __future__ import annotations

import json
import uuid
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, segments, versions

VIEWER_SECONDS = 300
SEGMENTS_SQL = ("/* lib:answer-segments */ SELECT replace(id::text,'-',''),version_key,text,locator,kind,language,(superseded_at IS NULL) "
                "FROM public.pr_library_segments WHERE workspace_id=%(w)s AND id=ANY(%(ids)s::uuid[])")
OBJECT_SQL = ("/* lib:viewer-object */ SELECT object_name,processing_status,kind,extension,original_filename,mime FROM public.pr_library_assets "
              "WHERE workspace_id=%(w)s AND id=%(id)s")
OPENABLE = ("ready", "unsupported", "failed")


def _locator_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def load_segments(ctx, ids) -> dict:
    """{segmentId: {versionKey, text, locator, kind, language, active}} for these ids in this workspace only."""
    keys = list(dict.fromkeys(c.asset_key(i) for i in ids if i))
    if not keys:
        return {}
    ctx.cur.execute(SEGMENTS_SQL, {"w": ctx.workspace_id, "ids": [str(uuid.UUID(hex=k)) for k in keys]})
    return {sid: {"versionKey": vk, "text": text, "locator": _locator_value(loc), "kind": kind, "language": language, "active": bool(active)}
            for sid, vk, text, loc, kind, language, active in ctx.cur.fetchall()}


def _legacy_record(ctx, key):
    return next((a for a in (ctx.state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and a.get("id") == key), None)


def _target(ctx, version: dict) -> dict:
    if version.get("legacy"):
        if version.get("kind") == "video":
            record = _legacy_record(ctx, version["versionId"]) or {}
            storage = getattr(getattr(ctx.service, "assets", None), "storage", None)
            if storage is not None and record.get("objectName"):
                url = storage.signed_url(ctx.workspace_id, "video", record["objectName"], VIEWER_SECONDS)
                return {"kind": "signedUrl", "url": url, "expiresIn": VIEWER_SECONDS, "expiresAt": ctx.now + VIEWER_SECONDS, "refresh": True,
                        "mime": version.get("mime")}
        # Legacy photos (and video posters) go through the authenticated proxy, which checks membership on every fetch.
        return {"kind": "proxy", "href": f"/api/workspaces/{ctx.workspace_id}/media/{version['versionId']}", "expiresIn": None, "refresh": True}
    ctx.cur.execute(OBJECT_SQL, {"w": ctx.workspace_id, "id": str(uuid.UUID(hex=version["versionId"]))})
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    object_name, status, kind, extension, filename, mime = row
    if status not in OPENABLE:
        raise AlphaError("This file isn't ready to open yet.", 409, code="library_not_ready")
    storage = getattr(getattr(ctx.service, "library", None), "storage", None)
    if storage is None:
        raise AlphaError("File viewing isn't available here.", 503, code="library_storage_not_configured")
    url = storage.signed_url(ctx.workspace_id, "file", object_name, VIEWER_SECONDS)
    if kind == "file" or extension in ("html", "htm", "json"):  # active document types always download, as in library.url
        url += "&" + urlencode({"download": filename})
    return {"kind": "signedUrl", "url": url, "expiresIn": VIEWER_SECONDS, "expiresAt": ctx.now + VIEWER_SECONDS, "refresh": True, "mime": mime}


def resolve_locator(ctx, ref, locator=None, *, segment_id=None, quote_hash=None) -> dict:
    """Authorized viewer target for one cited version and location. See the module docstring."""
    ctx.require("read")
    if not policy.enabled("retrieval"):
        raise AlphaError("Library citations are not enabled in this environment.", 503, code="library_retrieval_disabled")
    ref = c.asset_ref(ref)
    version = versions.resolve(ctx, ref)  # 404 for deleted/foreign/missing, 409 when the content hash changed
    policy.require(policy.authorize_source(ctx, version, "browse"))
    limits = segments.bounds(ctx.cur, ctx.workspace_id, version)
    loc = c.locator(locator, **limits) if locator is not None else None
    passage = None
    if segment_id is not None:
        sid = c.asset_key(segment_id)
        row = load_segments(ctx, [sid]).get(sid)
        if row is None or row["versionKey"] != version["versionId"]:
            raise AlphaError("This passage is unavailable.", 404, code="library_unavailable")
        if quote_hash is not None and c.quote_hash(row["text"]) != quote_hash:
            raise AlphaError("This passage changed since it was cited. Open the item to review it.", 409, code="library_citation_changed")
        stored = c.locator(row["locator"], **limits) if row["locator"] else None
        if loc is not None and stored is not None and loc != stored:
            raise AlphaError("This passage moved since it was cited. Open the item to review it.", 409, code="library_citation_changed")
        loc = loc or stored
        from .search import plain_text
        passage = {"segmentId": sid, "text": plain_text(row["text"])[:4000], "kind": row["kind"], "language": row["language"],
                   "superseded": not row["active"]}
    target = _target(ctx, version)
    try:
        current = versions.current(ctx, version["assetId"])
    except AlphaError:
        current = version
    return {"assetRef": versions.ref(version), "versionNo": version.get("versionNo", 1), "isCurrentVersion": current["versionId"] == version["versionId"],
            "currentAssetRef": versions.ref(current), "displayTitle": version.get("title") or version.get("filename"), "kind": version.get("kind"),
            "mime": version.get("mime"), "locator": loc, "locatorLabel": c.locator_label(loc) if loc else None, "passage": passage, "target": target}


def viewer_http(ctx, request) -> dict:
    """POST …/library/intelligence/viewer — body {sourceRef} or {assetRef, locator}. Call again for a fresh link."""
    body = request.get("body") or {}
    if not isinstance(body, dict) or not set(body) <= {"sourceRef", "assetRef", "locator"}:
        c.fail("Send a source reference to open.")
    if body.get("sourceRef") is not None:
        ref = c.source_ref(body["sourceRef"])
        return resolve_locator(ctx, ref["assetRef"], ref.get("locator"), segment_id=ref.get("segmentId"), quote_hash=ref.get("quoteHash"))
    return resolve_locator(ctx, body.get("assetRef"), body.get("locator"))
