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
DAY = {"type": "string", "maxLength": 10, "format": "date"}
KINDS = ("all", "image", "video", "audio", "document", "file")
INVALIDATES = ["library_search", "library_item", "library_lineage", "drafts_list"]
PICK_MAX = 25        # library_search `ids`: the items a Manager turn found (ui_projection suggests them), in that order
PAGING_NOTE = "The Library does not report a total; more pages follow while a cursor is returned."
EMPTY_FILTERED = "Nothing in your Library matches these filters."
EMPTY_LIBRARY = "Your Library has no items yet."
EMPTY_PICKED = "This answer didn't list any Library items."   # `ids: []`: the turn found nothing (never the whole Library)
PARTIAL_WINDOW = "This page searched part of your Library; matching items may remain. Continue with the next page."
BOUNDED_WINDOW = "This search reached its scan limit; matching items may remain. Narrow the filters to continue."
END_WINDOW = "No more matching items in the remaining part of your Library."


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


def _browse():
    from .. import library_browse   # the agent's Library tool: same date window, video dates and scan (one filter system)
    return library_browse


def _filtered(inputs) -> bool:
    return any(inputs.get(k) for k in ("q", "tag", "collection", "addedFrom", "addedTo")) or (inputs.get("kind") or "all") != "all" or inputs.get("ids") is not None


def _empty_note(inputs) -> str:
    return EMPTY_FILTERED if _filtered(inputs) else EMPTY_LIBRARY


def _dated(dctx, assets: list) -> tuple[list, dict]:
    """Media-store videos get the added date of their committed upload row; photos keep none (nothing records it)."""
    browse = _browse()
    dates = browse.video_dates(dctx.cur, dctx.workspace_id, [a.get("id") for a in assets if not _is_file(a) and (a.get("assetKind") or a.get("kind")) == "video"])
    return [{**a, "createdAt": dates[a.get("id")]} if a.get("id") in dates else a for a in assets], dates


def _windowed(assets: list, dates: dict, window, warnings: list) -> list:
    """Items with a recorded added date inside the window (photos have none, and are counted in a warning)."""
    if not window:
        return assets
    browse = _browse()
    epochs = {id(a): browse.added_epoch(a, dates) for a in assets}
    undated = sum(1 for a in assets if epochs[id(a)] is None)
    if undated:
        warnings.append(f"{undated} item(s) have no recorded added date (photos never do), so a date range can't include them.")
    return [a for a in assets if epochs[id(a)] is not None and window[0] <= epochs[id(a)] < window[1]]


def _picked(dctx, library, ids: list) -> list:
    """Exactly these items of this workspace, in the order given, however large the Library: the non-deleted media-store
    photos/videos of this member's workspace state, and ONE workspace-scoped read of pr_library_assets for the rest (deleting
    and duplicate rows excluded, as list() excludes them), decorated with their labels and collections as list() decorates
    them. Another workspace's, deleted and unknown ids are simply not returned."""
    from ...library_assets import _asset
    wanted = set(ids)
    legacy = {}
    for a in (dctx.state.get("phase2") or {}).get("assets") or []:
        if isinstance(a, dict) and a.get("id") in wanted and not a.get("deleted") and not a.get("deletionPending") and a["id"] not in legacy:
            legacy[a["id"]] = {**a, "assetKind": "video" if str(a.get("mime") or "").startswith("video/") else "image"}
    rest = [i for i in ids if i not in legacy and re.match(HEX, i)]
    files = {}
    if rest:
        dctx.cur.execute("SELECT to_jsonb(a)||jsonb_build_object('epoch',extract(epoch from a.created_at)) FROM public.pr_library_assets a "
                         "WHERE a.workspace_id=%s AND a.id=ANY(%s::uuid[]) AND a.processing_status NOT IN ('deleting','duplicate')",
                         (dctx.workspace_id, rest))
        for (record,) in dctx.cur.fetchall() or []:
            asset = _asset(record)
            files[asset["id"]] = asset
    picked = [legacy.get(i) or files.get(i) for i in ids]
    picked = [a for a in picked if a is not None]
    if picked and callable(getattr(library, "_decorate", None)):
        library._decorate(dctx.cur, dctx.workspace_id, picked)
    return picked


def _keeps(asset: dict, inputs: dict) -> bool:
    """The other filters, applied to an `ids` selection: kind, tag, collection and q (title, filename and tags words)."""
    kind = inputs.get("kind") or "all"
    if kind != "all" and (asset.get("assetKind") or asset.get("kind")) != kind:
        return False
    if inputs.get("tag") and inputs["tag"] not in (asset.get("tags") or []):
        return False
    if inputs.get("collection") and inputs["collection"] not in (asset.get("collections") or []):
        return False
    words = str(inputs.get("q") or "").casefold().split()
    hay = " ".join(str(x) for x in [asset.get("displayTitle") or "", asset.get("originalFilename") or "", *(asset.get("tags") or [])]).casefold()
    return all(word in hay for word in words)


def _search_ids(dctx, library, inputs, cursor, window):
    """`ids`: exactly those items of this workspace, in that order (the rest are counted, never explained), resolved directly
    rather than through a bounded scan, so an item past the scan bound is still listed. `ids: []` is the turn's own empty
    result: an empty view, never the whole Library."""
    ids = list(inputs.get("ids") or [])
    warnings = []
    picked = _picked(dctx, library, ids) if ids else []
    if len(picked) < len(ids):
        warnings.append(f"{len(ids) - len(picked)} of the chosen items aren't available here.")
    assets, dates = _dated(dctx, picked)
    assets = [a for a in _windowed(assets, dates, window, warnings) if _keeps(a, inputs)]
    page, next_cursor, start = common.paginate("library_search", inputs, cursor, assets, default=50)
    rows = [_row(dctx, a) for a in page]
    data = {"items": rows, "offset": start, "storage": {"usedBytes": None, "limitBytes": None}, "capabilities": {},
            "legacyMedia": len([a for a in assets if not _is_file(a)])}
    note = (EMPTY_PICKED if not ids else EMPTY_FILTERED) if not rows and start == 0 else None
    return ui_contracts.query_result("available" if rows else ("empty" if start == 0 else "available"), data, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(rows),
                                     total=len(assets), note=note, warnings=warnings)


def _window_cursor(inputs, cursor):
    """A signed (file scan offset, match offset) pair. Both positions are needed: matches can be empty for an entire scan
    segment while later files still match. The scan offset is included in the signed input hash, never trusted alone."""
    query_inputs = {k: v for k, v in inputs.items() if k != "limit"}
    if cursor is None:
        return 0, 0, query_inputs
    try:
        prefix, raw_start, signed = cursor.split(".", 2)
        start = int(raw_start)
    except (ValueError, TypeError, AttributeError):
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor") from None
    browse = _browse()
    if prefix != "lw1" or not 0 <= start <= browse.MAX_START or start % browse.SEGMENT:
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor")
    offset = common.decode_cursor("library_search_window", {**query_inputs, "scanStart": start}, signed)
    return start, offset, query_inputs


def _next_window_cursor(query_inputs, start, offset):
    return f"lw1.{start}." + common.encode_cursor("library_search_window", {**query_inputs, "scanStart": start}, offset)


def _selected(dctx, binding):
    """The parent answer's selection, from the persisted server manifest; absence keeps ordinary Library queries intact."""
    constraint = ((dctx.manifest or {}).get("queryConstraints") or {}).get(binding) or {}
    if "ids" not in constraint:
        return None
    ids = constraint["ids"]
    return [i for i in ids if isinstance(i, str) and re.fullmatch(HEX, i)][:PICK_MAX] if isinstance(ids, list) else []


def _require_selected(dctx, binding, asset_id):
    selected = _selected(dctx, binding)
    if selected is not None and asset_id not in selected:
        raise AlphaError("That item isn't in this answer's Library selection.", 404, code="not_found")


def _search_scanned(dctx, library, inputs, cursor, args, window):
    """One bounded date scan, with pagination inside its matches and continuation into the next file segment. An incomplete
    scan is partial (never an exact empty result); subsequent segments cannot claim a whole-Library total."""
    browse = _browse()
    scan_start, offset, query_inputs = _window_cursor(inputs, cursor)
    found = browse.scan(library, dctx.workspace_id, query=args["query"], kind=args["kind"], tag=args["tag"], collection=args["collection"],
                        sort=args["sort"], stop_before=window[0] if window else None, start=scan_start)
    assets, dates = _dated(dctx, found["legacy"] + found["files"])
    warnings = []
    assets = _windowed(assets, dates, window, warnings)
    page = assets[offset:offset + common.page_size(inputs, 50)]
    following = offset + len(page)
    complete = bool(found["complete"])
    upcoming = found.get("next")
    if following < len(assets):
        next_cursor = _next_window_cursor(query_inputs, scan_start, following)
    elif not complete and type(upcoming) is int and scan_start < upcoming <= browse.MAX_START and upcoming % browse.SEGMENT == 0:
        next_cursor = _next_window_cursor(query_inputs, upcoming, 0)
    else:
        next_cursor = None
    rows = [_row(dctx, a) for a in page]
    first = found["first"]
    storage = first.get("storage") or {}
    data = {"items": rows, "offset": offset, "storage": {"usedBytes": storage.get("usedBytes"), "limitBytes": storage.get("limitBytes")},
            "capabilities": first.get("capabilities") or {}, "legacyMedia": len([a for a in assets if not _is_file(a)])}
    exact = complete and scan_start == 0
    if not complete:
        note = PARTIAL_WINDOW if next_cursor else BOUNDED_WINDOW
    elif not rows:
        note = _empty_note(inputs) if exact and offset == 0 else END_WINDOW
    else:
        note = None
    state = "partial" if not complete else ("empty" if exact and not rows and offset == 0 else "available")
    return ui_contracts.query_result(state, data, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(rows),
                                     total=len(assets) if exact else None, note=note, warnings=warnings)


def library_search(dctx, inputs, cursor):
    library = _library(dctx)
    selected = _selected(dctx, "library_search")
    if selected is not None:
        requested = inputs.get("ids")
        inputs = {**inputs, "ids": [i for i in selected if requested is None or i in requested]}
    window = _browse().added_window(inputs.get("addedFrom"), inputs.get("addedTo"), dctx.zone, dctx.now, code="ui_window")
    if inputs.get("ids") is not None:
        return _search_ids(dctx, library, inputs, cursor, window)
    if window is not None:
        args = dict(query=inputs.get("q") or "", kind=inputs.get("kind") or "all", tag=inputs.get("tag") or "", collection=inputs.get("collection") or "",
                    sort=inputs.get("sort") or "newest")
        return _search_scanned(dctx, library, inputs, cursor, args, window)
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
    page, _dates = _dated(dctx, page)
    rows = [_row(dctx, a) for a in page]
    next_cursor = common.encode_cursor("library_search", query_inputs, position + size) if more else None
    storage = first.get("storage") or {}
    data = {"items": rows, "offset": position, "storage": {"usedBytes": storage.get("usedBytes"), "limitBytes": storage.get("limitBytes")},
            "capabilities": first.get("capabilities") or {}, "legacyMedia": len(legacy)}
    return ui_contracts.query_result("available" if rows else ("empty" if position == 0 else "available"), data, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(rows), total=None,
                                     note=_empty_note(inputs) if not rows and position == 0 else PAGING_NOTE)


def _legacy(state, asset_id):
    return next((a for a in (state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict) and a.get("id") == asset_id and not a.get("deleted")
                 and not a.get("deletionPending")), None)


def library_item(dctx, inputs, _cursor):
    from ... import media_consent
    asset_id = inputs["assetId"]
    _require_selected(dctx, "library_item", asset_id)
    legacy = _legacy(dctx.state, asset_id)
    consent = {"modelMayView": bool(media_consent.decision(dctx.state).get("cloud")) if hasattr(media_consent, "decision") else None}
    if legacy is not None:
        data = {**_row(dctx, {**legacy, "assetKind": "video" if str(legacy.get("mime") or "").startswith("video/") else "image"}), "excerpt": None, "excerptTruncated": False,
                "chunkCount": 0, "summary": None, "lineage": legacy.get("lineage") or None, "mediaConsent": consent}
        return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("media", asset_id)], known=1, total=1)
    detail = _library(dctx).detail(dctx.workspace_id, None, asset_id)
    text = detail.get("extractedText") or ""
    data = {**_row(dctx, detail["asset"]), "excerpt": text[:2000] or None, "excerptTruncated": len(text) > 2000, "chunkCount": len(detail.get("chunks") or []),
            "summary": str(detail["asset"].get("summary") or "")[:400] or None, "lineage": None, "mediaConsent": consent}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("library_file", asset_id)], known=1, total=1,
                                     note=None if text else "No extracted text: add a transcript (audio) or use a text document.")


def library_lineage(dctx, inputs, _cursor):
    from .. import graph
    asset_id = inputs["assetId"]
    _require_selected(dctx, "library_lineage", asset_id)
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
        _require_selected(dctx, "library_selection", asset_id)
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
      "the browser previews it. ids lists exactly those items, in that order; addedFrom/addedTo keep items added in that range. Paged; the Library gives no total.",
      {"q": {"type": "string", "maxLength": 120}, "kind": {"type": "string", "enum": list(KINDS)}, "tag": {"type": "string", "maxLength": 40},
       "collection": ASSET, "sort": {"type": "string", "enum": ["newest", "stored", "largest"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
       "ids": {"type": "array", "maxItems": PICK_MAX, "items": ASSET, "uniqueItems": True}, "addedFrom": DAY, "addedTo": DAY},
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
