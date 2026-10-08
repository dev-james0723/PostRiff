"""J03 — Universal Library / Living Archive over the existing production Library (`UniversalLibrary.list/detail/collections/
as_source`, run on the request's own transaction) plus the legacy photo/video records.

Privacy (A-DECISIONS D-A17): results go to the browser only. Signed storage URLs are never returned or stored; a preview
names the existing authenticated route the browser's Library thumbnail component already uses, fetched at display time.
`createdBy`, provenance, raw hashes and raw extraction errors are dropped. A Library document becomes draft material only
through the existing "use as source" import (reviewable, never auto-approved for AI or publication); photos/videos are
handed to a follow-up turn as attachment chips (`library_selection`), where the turn's own media-consent check applies.

The adapter only calls the Library service, so it keeps working when the Library Intelligence API lands (swap the
service calls; the binding names and result shapes stay).
"""
from __future__ import annotations

import re

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

HEX = r"^[0-9a-f]{32}$"
ASSET = {"type": "string", "maxLength": 32, "pattern": HEX}
KINDS = ("all", "image", "video", "audio", "document", "file")
INVALIDATES = ["library_search", "library_item", "library_lineage", "drafts_list"]


def _library(dctx):
    library = getattr(dctx.service, "library", None)
    if library is None:
        raise AlphaError("The Library isn't available here.", 503, code="library_unavailable")
    return library


def _is_file(asset: dict) -> bool:
    return "processingStatus" in asset and "originalFilename" in asset


def _preview(dctx, asset: dict) -> dict:
    """How the browser shows it (the existing authenticated routes; never a signed URL)."""
    w = dctx.workspace_id
    if not _is_file(asset):
        video = str(asset.get("mime") or "").startswith("video/")
        return {"previewKind": "video_poster" if video else "image", "previewRoute": f"/api/workspaces/{w}/media/{asset.get('id')}"}
    kind, ext = asset.get("kind"), str(asset.get("extension") or "").lower()
    server = hasattr(_library(dctx), "preview")
    if kind == "audio":
        preview = "audio_cover"
    elif ext == "pdf":
        preview = "pdf_page"
    elif kind == "document":
        preview = "server_page" if server else "document_cover"
    else:
        preview = "file_cover"
    return {"previewKind": preview, "previewRoute": f"/api/workspaces/{w}/library/files/{asset.get('id')}/{'preview' if server and preview == 'server_page' else 'url'}"}


def _row(dctx, asset: dict) -> dict:
    is_file = _is_file(asset)
    kind = asset.get("assetKind") or asset.get("kind")
    ident = asset.get("id")
    row = {"ref": common.ref("library_file" if is_file else "media", ident), "assetId": ident, "store": "file" if is_file else "media", "kind": kind,
           "title": str(asset.get("displayTitle") or asset.get("originalFilename") or asset.get("alt") or "")[:200] or None,
           "mime": asset.get("mime"), "extension": asset.get("extension"), "bytes": asset.get("bytes"),
           "createdAt": common.iso(asset.get("createdAt")), "tags": list(asset.get("tags") or [])[:30], "collections": list(asset.get("collections") or [])[:30],
           "processing": asset.get("processingStatus") or asset.get("processing"), "indexingStatus": asset.get("indexingStatus"),
           "transcriptionStatus": asset.get("transcriptionStatus"), "hasSource": bool(asset.get("sourceId")), "sourceId": asset.get("sourceId"),
           "duplicateOf": asset.get("duplicateOf"), "extractionProblem": "extraction_failed" if asset.get("extractionError") else None,
           "width": asset.get("width"), "height": asset.get("height"), "duration": asset.get("duration"), "alt": str(asset.get("alt") or "")[:300] or None,
           "href": f"/app/library?asset={ident}"}
    row.update(_preview(dctx, asset))
    return row


def library_search(dctx, inputs, cursor):
    library = _library(dctx)
    size = common.page_size(inputs, 50)
    query_inputs = {k: v for k, v in inputs.items() if k != "limit"}
    position = common.decode_cursor("library_search", query_inputs, cursor)
    args = dict(query=inputs.get("q") or "", kind=inputs.get("kind") or "all", tag=inputs.get("tag") or "", collection=inputs.get("collection") or "",
                sort=inputs.get("sort") or "newest")
    # The Library lists legacy photos/videos on its first page only, unbounded: re-bound them to this page size here.
    first = library.list(dctx.workspace_id, None, limit=max(size, 1), offset=0, **args)
    legacy = [a for a in first["assets"] if not _is_file(a)]
    files_first = [a for a in first["assets"] if _is_file(a)]
    if position < len(legacy):
        page = legacy[position:position + size]
        need = size - len(page)
        page += files_first[:need]
        more = position + size < len(legacy) or len(files_first) > need or first.get("nextOffset") is not None
    else:
        offset = position - len(legacy)
        listed = first if offset == 0 else library.list(dctx.workspace_id, None, limit=size, offset=offset, **args)
        files = [a for a in listed["assets"] if _is_file(a)]
        page = files[:size]
        more = len(files) > size or listed.get("nextOffset") is not None
    rows = [_row(dctx, a) for a in page]
    next_cursor = common.encode_cursor("library_search", query_inputs, position + size) if more else None
    storage = first.get("storage") or {}
    data = {"items": rows, "offset": position, "storage": {"usedBytes": storage.get("usedBytes"), "limitBytes": storage.get("limitBytes")},
            "capabilities": first.get("capabilities") or {}, "legacyMedia": len(legacy)}
    return ui_contracts.query_result("available" if rows else ("empty" if position == 0 else "available"), data, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(rows), total=None,
                                     note="The Library does not report a total; more pages follow while a cursor is returned.")


def _legacy(state, asset_id):
    return next((a for a in (state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict) and a.get("id") == asset_id and not a.get("deleted")
                 and not a.get("deletionPending")), None)


def library_item(dctx, inputs, _cursor):
    from ... import media_consent
    asset_id = inputs["assetId"]
    legacy = _legacy(dctx.state, asset_id)
    consent = {"modelMayView": bool(media_consent.decision(dctx.state).get("cloud")) if hasattr(media_consent, "decision") else None}
    if legacy is not None:
        data = {**_row(dctx, {**legacy, "assetKind": "video" if str(legacy.get("mime") or "").startswith("video/") else "image"}), "excerpt": None, "chunkCount": 0,
                "lineage": legacy.get("lineage") or None, "mediaConsent": consent}
        return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("media", asset_id)], known=1, total=1)
    detail = _library(dctx).detail(dctx.workspace_id, None, asset_id)
    text = detail.get("extractedText") or ""
    data = {**_row(dctx, detail["asset"]), "excerpt": text[:2000] or None, "excerptTruncated": len(text) > 2000, "chunkCount": len(detail.get("chunks") or []),
            "summary": str(detail["asset"].get("summary") or "")[:400] or None, "mediaConsent": consent}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("library_file", asset_id)], known=1, total=1,
                                     note=None if text else "No extracted text: add a transcript (audio) or use a text document.")


def library_lineage(dctx, inputs, _cursor):
    from .. import graph
    asset_id = inputs["assetId"]
    legacy = _legacy(dctx.state, asset_id)
    if legacy is not None:
        found = graph.neighbours(dctx.state, "asset", asset_id)
        return ui_contracts.query_result("available", {"assetId": asset_id, "store": "media", "edges": found.get("edges") or []}, as_of=common.iso(dctx.now),
                                         source_refs=[common.ref("media", asset_id)], known=len(found.get("edges") or []), total=len(found.get("edges") or []),
                                         note="Each relationship names the stored field it comes from.")
    detail = _library(dctx).detail(dctx.workspace_id, None, asset_id)["asset"]
    edges = []
    source_id = detail.get("sourceId")
    if source_id:
        edges.append({"relation": "imported_as", "type": "source", "id": source_id, "via": "pr_library_assets.source_id"})
        edges.extend((graph.neighbours(dctx.state, "source", source_id).get("edges") or [])[:60])
    if detail.get("duplicateOf"):
        edges.append({"relation": "duplicate_of", "type": "library_file", "id": detail["duplicateOf"], "via": "pr_library_assets.duplicate_of"})
    return ui_contracts.query_result("available" if edges else "empty", {"assetId": asset_id, "store": "file", "edges": edges}, as_of=common.iso(dctx.now),
                                     source_refs=[common.ref("library_file", asset_id)], known=len(edges), total=len(edges))


def library_collections(dctx, _inputs, _cursor):
    found = _library(dctx).collections(dctx.workspace_id, None)
    rows = [{"collectionId": c["id"], "name": c["name"], "count": c["count"]} for c in found.get("collections") or []]
    return ui_contracts.query_result("available" if rows else "empty", {"collections": rows}, as_of=common.iso(dctx.now), known=len(rows), total=len(rows))


def library_selection(dctx, inputs, _cursor):
    """Validate a selection for the next drafting turn: photos/videos become attachment chips, documents with an imported
    source become source references. Read only; selection is never approval."""
    from ... import asset_kinds
    chips, references, refused = [], [], []
    for asset_id in inputs["assetIds"]:
        legacy = _legacy(dctx.state, asset_id)
        if legacy is not None:
            if not asset_kinds.is_ready(legacy):
                refused.append({"assetId": asset_id, "reason": "not_ready"})
            else:
                chips.append({"assetId": asset_id, "role": inputs.get("role") or "reference"})
            continue
        try:
            asset = _library(dctx).detail(dctx.workspace_id, None, asset_id)["asset"]
        except AlphaError:
            refused.append({"assetId": asset_id, "reason": "not_found"})
            continue
        if asset.get("sourceId"):
            references.append({"kind": "source", "id": asset["sourceId"]})
        else:
            refused.append({"assetId": asset_id, "reason": "needs_source_import"})
    data = {"attachments": chips[:4], "references": references[:12], "refused": refused,
            "note": "Send these with your next message. A document needs 'Use as source' first; a model looks at a photo only if the owner allowed it."}
    return ui_contracts.query_result("available" if chips or references else "empty", data, as_of=common.iso(dctx.now),
                                     source_refs=[common.ref("media", c["assetId"]) for c in chips] + [common.ref("source", r["id"]) for r in references],
                                     known=len(chips) + len(references), total=len(inputs["assetIds"]),
                                     warnings=[f"{len(refused)} item(s) can't be used yet."] if refused else [])


# --- use a document as a draft source ------------------------------------------------------------------------------------
def source_confirm(dctx, inputs):
    if _legacy(dctx.state, inputs["assetId"]) is not None:
        raise AlphaError("Photos and videos are attached to a message instead.", 409, code="not_a_document")
    detail = _library(dctx).detail(dctx.workspace_id, None, inputs["assetId"])
    asset = detail["asset"]
    text = detail.get("extractedText") or ""
    if asset.get("sourceId"):
        lines = ["This file is already a source; nothing changes."]
    elif not text.strip():
        raise AlphaError("This asset has no extracted text. Add an audio transcript or choose a text document.", 409, code="no_text")
    else:
        lines = [f"Import up to 19,000 characters of this file's text ({min(len(text), 19000)} now) as a draft source.",
                 "It stays 'needs review': its facts are not approved for AI or publishing until you review them."]
    return {"title": "Use as source", "summary": lines, "target": str(asset.get("displayTitle") or asset.get("originalFilename") or "Library file")[:200],
            "timeZone": None, "cost": "No AI cost"}


def source_execute(dctx, inputs, _key):
    source_confirm(dctx, inputs)
    out = _library(dctx).as_source(dctx.workspace_id, None, inputs["assetId"], {"expectedRevision": dctx.revision})
    state = dctx.refresh_state()
    source = next((s for s in state.get("sources") or [] if isinstance(s, dict) and s.get("id") == out.get("sourceId")), None)
    verified = source is not None and (source.get("origin") or {}).get("assetId") == inputs["assetId"]
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"source:{out.get('sourceId')}", changed_refs=[common.ref("source", out.get("sourceId")),
                                                                                                           common.ref("library_file", inputs["assetId"])],
                   invalidation_keys=INVALIDATES, next_context={"references": [{"type": "source", "id": out.get("sourceId")}], "status": "needs_review"},
                   message="Imported as a source. Review its facts before Rafii uses them." if verified else "Imported, but the re-read didn't find the source; reload.")


query("library_search", "J03", "Search or filter the Library (photos, videos, audio, documents, files): title, kind, size, tags, collections, processing state and how "
      "the browser previews it. Paged; the Library gives no total.",
      {"q": {"type": "string", "maxLength": 120}, "kind": {"type": "string", "enum": list(KINDS)}, "tag": {"type": "string", "maxLength": 40},
       "collection": ASSET, "sort": {"type": "string", "enum": ["newest", "stored", "largest"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      library_search, page=50, refresh=60, search=True, tool="library.search", invalidated_by=("library_search",))
query("library_item", "J03", "One Library item: metadata, preview kind, a bounded text excerpt and chunk count for documents, and whether a model may look at media.",
      {"assetId": ASSET}, library_item, required=("assetId",), refresh=None, tool="library.read")
query("library_lineage", "J03", "Where a Library item came from and what was made from it (source import, drafts, duplicates, edits), each with the stored field.",
      {"assetId": ASSET}, library_lineage, required=("assetId",), refresh=None, tool="relationships")
query("library_collections", "J03", "The Library's collections with item counts.", {}, library_collections, refresh=None)
query("library_selection", "J03", "Check a selection of up to 4 Library items for the next drafting message: attachment chips for photos/videos, source references for "
      "imported documents, and why anything can't be used yet. Read only.",
      {"assetIds": {"type": "array", "minItems": 1, "maxItems": 4, "items": ASSET, "uniqueItems": True}, "role": {"type": "string", "enum": ["post", "reference"]}},
      library_selection, required=("assetIds",), refresh=None, also=("J01",))
action("library_use_as_source", "J03", "Use as source", "Imports this document's text as a reviewable draft source (not approved for AI or publishing until you review it).",
       "MUTATE_REVERSIBLE", "edit", {"assetId": ASSET}, source_confirm, source_execute, required=("assetId",), dedupe="natural", also=("J01",))
_ = re
