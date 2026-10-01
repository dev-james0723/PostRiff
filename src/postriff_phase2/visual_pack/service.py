"""Visual Pack service (PRD R-VIS-01..03 · plan G3-VIS · AC22/AC23).

prepare (a draft → revision 1) → edit (each edit a new revision; the previous one is superseded, so its acceptance and
exports stop applying) → render (six verified PNGs in private storage; no paid I/O; idempotent per revision) → accept
(this exact rendered revision) → export (a deterministic zip: six PNGs, caption, alt text, manifest) → download
(authenticated; recorded) → the person's own "I used these" confirmation. `export_ready`, `downloaded` and
`user_confirmed_used` are separate facts, never a publication. A Queue handoff is refused with its reason while no
publisher has verified multi-image support; the assisted export is offered instead.

Authority: every call runs in the workspace repository transaction (session principal, membership, path id selects
only); `edit` for pack changes and exports, `approve` for a Queue handoff. Storage I/O and rendering never hold that
transaction. Audit and analytics carry ids, enums and counts only.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError

from .. import asset_kinds, growth_events
from ..contracts import digest
from ..permissions import require
from . import checks, render, slides as slide_copy

FLAG = "RAFII_VISUAL_PACK_ENABLED"
DEFINITION = "rafii.visual-pack.v1"
PAGE, PAGE_MAX, HISTORY = 25, 50, 20
MAX_REVISIONS = 200
EXPORTED = ("export_ready", "downloaded", "user_confirmed_used")
ACCEPTED = ("accepted",) + EXPORTED + ("queued",)
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_REF = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
HANDOFF = ("Rafii Visual Pack · assisted export\n"
           "These files were prepared for you to post yourself. Rafii has not published them, and this export is not a "
           "publication receipt.\nUpload slide-01.png to slide-06.png in this order, use caption.txt as the caption and "
           "alt-text.txt for each image's alt text.\n\n"
           "這些檔案由 Rafii 準備，請你自行發佈。Rafii 沒有發佈它們，這份匯出也不是發佈證明。\n"
           "請依序上傳 slide-01.png 至 slide-06.png，以 caption.txt 作為貼文文字，並以 alt-text.txt 填寫每張圖片的替代文字。\n")
RECEIPTS = {
    "draft": "Draft: nothing is rendered, exported or published.",
    "rendered": "Six slides rendered for review. Nothing is exported or published.",
    "accepted": "Accepted. Export the files to post them yourself; nothing is published.",
    "export_ready": "Files ready to download. Rafii has not published anything.",
    "downloaded": "Downloaded. Rafii has not published anything; confirm here once you have posted it yourself.",
    "user_confirmed_used": "You confirmed you used these files. Rafii did not publish them and has not verified a post.",
    "queued": "Handed to Queue. Publication is confirmed only by Queue's own receipt.",
    "superseded": "An earlier version: its acceptance and export no longer apply.",
}
_PACK = ("id::text,source_variant_id,source_campaign_id,status,current_revision,settings,language,idempotency_key,request_digest,"
         "created_by::text,extract(epoch from created_at),extract(epoch from updated_at)")
_REV = ("id::text,revision_no,slides,caption,settings,source,content_digest,checks,state,render_manifest,render_digest,"
        "extract(epoch from rendered_at),approval_digest,extract(epoch from accepted_at),export_digest,export_sha256,export_bytes,"
        "extract(epoch from export_ready_at),extract(epoch from downloaded_at),download_count,extract(epoch from confirmed_used_at),"
        "extract(epoch from queued_at),extract(epoch from superseded_at),extract(epoch from purged_at),purge_reason,edit_key,edit_digest,"
        "extract(epoch from created_at)")


def enabled(values=None) -> bool:
    """`RAFII_VISUAL_PACK_ENABLED`, read like every coworker flag (isolated environment; off unless 1/true/yes/on)."""
    from ..coworker import flags
    return flags._truthy(flags._source(values).get(FLAG, ""))


def ensure(hosted):
    if not hasattr(hosted, "visual_packs"):
        hosted.visual_packs = VisualPackService(hosted)
    return hosted.visual_packs


# --- small helpers ------------------------------------------------------------------------------------------------

def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _num(value):
    return float(value) if value is not None else None


def _sha(text) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def _key(value) -> str:
    if not isinstance(value, str) or not _KEY.match(value):
        raise AlphaError("Send an idempotency key of 8–80 letters, digits or -_.: characters.", 400, code="unsupported_input")
    return value


def _expected(body) -> int:
    value = (body or {}).get("expectedRevision")
    if type(value) is not int or value < 1:
        raise AlphaError("Send the pack revision you are working on (expectedRevision).", 400, code="unsupported_input")
    return value


def _pack_id(value) -> str:
    if not isinstance(value, str) or not _UUID.match(value):
        raise AlphaError("That visual pack is not in this workspace.", 404, code="not_found")
    return value


def _text(value, limit, what):
    try:
        return checks.normalize_text(value, limit)
    except ValueError:
        raise AlphaError(f"Use plain {what} of at most {limit} characters.", 400, code="unsupported_input") from None


def _pack(row) -> dict:
    return {"id": row[0], "sourceVariantId": row[1], "sourceCampaignId": row[2], "status": row[3], "currentRevision": row[4],
            "settings": _json(row[5]), "language": row[6], "idempotencyKey": row[7], "requestDigest": row[8], "createdBy": row[9],
            "createdAt": _num(row[10]), "updatedAt": _num(row[11])}


def _rev(row) -> dict:
    return {"id": row[0], "revision": row[1], "slides": _json(row[2]), "caption": row[3], "settings": _json(row[4]), "source": _json(row[5]),
            "contentDigest": row[6], "checks": _json(row[7]), "state": row[8], "manifest": _json(row[9]), "renderDigest": row[10],
            "renderedAt": _num(row[11]), "approvalDigest": row[12], "acceptedAt": _num(row[13]), "exportDigest": row[14], "exportSha256": row[15],
            "exportBytes": row[16], "exportReadyAt": _num(row[17]), "downloadedAt": _num(row[18]), "downloadCount": row[19],
            "confirmedUsedAt": _num(row[20]), "queuedAt": _num(row[21]), "supersededAt": _num(row[22]), "purgedAt": _num(row[23]),
            "purgeReason": row[24], "editKey": row[25], "editDigest": row[26], "createdAt": _num(row[27])}


def _assets(state) -> dict:
    return {a["id"]: a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and isinstance(a.get("id"), str)}


def _images(state, pack_slides) -> dict:
    """Each referenced image → its asset record while it is a live, decoded Library image of this workspace, else None."""
    assets = _assets(state)
    return {s["imageAssetId"]: (assets.get(s["imageAssetId"]) if asset_kinds.is_postable_image(assets.get(s["imageAssetId"])) else None)
            for s in pack_slides if s.get("imageAssetId")}


def _variant(state, variant_id):
    return next((v for v in state.get("variants") or [] if isinstance(v, dict) and v.get("id") == variant_id), None)


def _campaign_for(state, variant_id, requested=None):
    campaigns = (((state.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns")) or []
    for campaign in campaigns:
        if not isinstance(campaign, dict) or campaign.get("status") == "cancelled":
            continue
        if requested is not None and campaign.get("id") != requested:
            continue
        if any(isinstance(i, dict) and i.get("kind") == "draft" and i.get("variantId") == variant_id for i in campaign.get("items") or []):
            return campaign["id"]
    return None


def source_status(state, source) -> str:
    """`current` while the draft is unchanged since the pack bound to it; `changed` after any edit to the draft (a
    changed claim or call to action must reach the slides first); `unavailable` once the draft is gone."""
    variant = _variant(state, source.get("variantId"))
    if variant is None:
        return "unavailable"
    if variant.get("revision") != source.get("variantRevision") or _sha(variant.get("text")) != source.get("textSha256"):
        return "changed"
    return "current"


def _language_enum(tag) -> str:
    value = re.sub(r"[^a-z0-9-]", "", str(tag or "").lower())[:40]
    return value if re.match(r"^[a-z]", value) else "und"


def queue_capability(channel) -> dict:
    """Whether this exact connected account can take a six-image carousel through Queue. Only a publisher with verified
    multi-image support qualifies (hosted_social.CAROUSEL_VERIFIED); today none does, so the answer is always no."""
    from ..hosted_social import CAROUSEL_VERIFIED
    platform = channel.get("platform") if isinstance(channel, dict) else None
    if platform in CAROUSEL_VERIFIED:   # pragma: no cover - no publisher qualifies yet; kept honest for when one does
        return {"supported": False, "reason": f"{platform} carousel publishing is verified, but the Queue handoff for packs is not built yet."}
    return {"supported": False, "reason": f"{platform or 'This account'} can't receive a six-image carousel from Rafii: no publisher has verified multi-image support."}


def build_zip(manifest: dict, files: dict) -> bytes:
    """The assisted export, byte-identical for the same revision: six PNGs in order, caption, alt text, manifest."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        def put(name, data, deflate):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compresslevel=9 if deflate else None)
        for slide in manifest["slides"]:
            put(slide["file"], files[slide["position"]], False)
        put("caption.txt", (manifest["caption"] + "\n").encode(), True)
        put("alt-text.txt", "".join(f"{slide['file']}\n{slide['altText']}\n\n" for slide in manifest["slides"]).encode(), True)
        put("manifest.json", (json.dumps(public_manifest(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), True)
        put("HANDOFF.txt", HANDOFF.encode(), True)
    return out.getvalue()


def public_manifest(manifest: dict) -> dict:
    """The manifest as exported: storage locations removed; the handoff and its meaning stated."""
    slides = [{k: v for k, v in slide.items() if k not in ("objectName", "storagePath")} for slide in manifest["slides"]]
    return {**{k: v for k, v in manifest.items() if k != "slides"}, "slides": slides, "handoff": "assisted_export",
            "publication": "not_published_by_rafii"}


def handoff_counts(cur, workspace_id, start, end) -> dict:
    """Distinct pack revisions that reached each handoff fact in [start, end) (datetimes or epoch seconds). `queued`
    and `verifiedPublished` count recorded Queue handoffs, which no qualifying provider allows yet. Values are None
    (unknown, never zero) when this deployment has no visual pack tables."""
    keys = {"exportReady": "export_ready", "downloaded": "downloaded", "userConfirmedUsed": "user_confirmed_used",
            "queued": "queued", "verifiedPublished": "verified_published"}
    cur.execute("SELECT to_regclass('public.pr_visual_pack_events') IS NOT NULL")
    if not cur.fetchone()[0]:
        return {name: None for name in keys}
    bound = "to_timestamp(%s)" if isinstance(start, (int, float)) else "%s"
    cur.execute("SELECT kind,count(DISTINCT (pack_id,revision_no)) FROM public.pr_visual_pack_events WHERE workspace_id=%s "
                f"AND occurred_at>={bound} AND occurred_at<{bound} AND kind = ANY(%s) GROUP BY kind",
                (workspace_id, start, end, list(keys.values())))
    found = dict(cur.fetchall())
    return {name: int(found.get(kind, 0)) for name, kind in keys.items()}


def purge_workspace(hosted, workspace_id) -> int:
    """Account deletion: remove every rendered slide object of the workspace (rows cascade with the workspace). The
    rows name the objects; a prefix sweep catches anything they don't. Not-found is success; failure raises."""
    names = set()
    with hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_visual_packs') IS NOT NULL")
        if not cur.fetchone()[0]:
            return 0
        cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_visual_packs WHERE workspace_id=%s)", (workspace_id,))
        if not cur.fetchone()[0]:
            return 0   # never used here: no rows, no objects, no storage request
        cur.execute("SELECT render_manifest FROM public.pr_visual_pack_revisions WHERE workspace_id=%s AND render_manifest IS NOT NULL", (workspace_id,))
        for (manifest,) in cur.fetchall():
            names.update(slide["objectName"] for slide in _json(manifest)["slides"])
    storage = getattr(getattr(hosted, "assets", None), "storage", None)
    if storage is None:
        raise AlphaError("Private storage deletion is unavailable.", 503)
    if hasattr(storage, "list_prefix"):   # a render that stored files but died before recording them
        names.update(path.rsplit("/", 1)[-1] for path in storage.list_prefix(f"{workspace_id}/visual-pack"))
    for name in sorted(names):
        storage.delete(workspace_id, "visual-pack", name)
    return len(names)


class VisualPackService:
    def __init__(self, hosted):
        self.hosted = hosted

    # --- authority -------------------------------------------------------------------------------------------------
    @contextmanager
    def _tx(self, token, workspace_id, requirement):
        if not enabled():
            raise AlphaError("This feature is not available.", 404, code="feature_disabled")
        from ..hosted import _membership
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), requirement)
            yield cur, principal, _json(row[1])

    def _storage(self):
        storage = getattr(getattr(self.hosted, "assets", None), "storage", None)
        if storage is None:
            raise AlphaError("Private media storage is not configured, so slides can't be rendered or exported here.", 503, code="media_storage_not_configured")
        return storage

    @staticmethod
    def _audit(cur, workspace_id, principal, kind, pack_id, meta):
        from ..hosted import audit
        audit(cur, workspace_id, principal, kind, pack_id, meta)

    @staticmethod
    def _fact(cur, workspace_id, pack_id, revision, kind, actor, meta=None) -> bool:
        cur.execute("INSERT INTO public.pr_visual_pack_events(workspace_id,pack_id,revision_no,kind,actor,meta) VALUES(%s,%s,%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT (workspace_id,pack_id,revision_no,kind) DO NOTHING", (workspace_id, pack_id, revision, kind, actor, json.dumps(meta or {})))
        return getattr(cur, "rowcount", 1) == 1

    def _load(self, cur, workspace_id, pack_id, revision=None, lock=False):
        cur.execute(f"SELECT {_PACK} FROM public.pr_visual_packs WHERE workspace_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""), (workspace_id, _pack_id(pack_id)))
        row = cur.fetchone()
        if not row:
            raise AlphaError("That visual pack is not in this workspace.", 404, code="not_found")
        pack = _pack(row)
        number = pack["currentRevision"] if revision is None else revision
        cur.execute(f"SELECT {_REV} FROM public.pr_visual_pack_revisions WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s" + (" FOR UPDATE" if lock else ""),
                    (workspace_id, pack["id"], number))
        found = cur.fetchone()
        if not found:
            raise AlphaError("That pack revision does not exist.", 404, code="not_found")
        return pack, _rev(found)

    @staticmethod
    def _current(pack, rev, expected):
        if expected != pack["currentRevision"] or rev["revision"] != pack["currentRevision"]:
            raise AlphaError("This pack changed since you loaded it. Reload it and try again.", 409, code="revision_conflict")

    @staticmethod
    def _ready_inputs(state, rev):
        """The draft and every image this revision uses must still be what it was bound to."""
        status = source_status(state, rev["source"])
        if status == "unavailable":
            raise AlphaError("The draft this pack came from is gone, so the pack can't be accepted or exported.", 409, code="source_unavailable")
        if status == "changed":
            raise AlphaError("The draft changed after this pack was made. Update the slides from the draft (or keep them) first.", 409, code="revision_conflict")
        missing = [k for k, v in _images(state, rev["slides"]).items() if v is None]
        if missing or rev["purgedAt"]:
            raise AlphaError("An image on these slides was deleted from the Library. Replace it and render again.", 409, code="source_unavailable")

    # --- reads -----------------------------------------------------------------------------------------------------
    def list(self, workspace_id, token, cursor=None, limit=PAGE):
        if type(limit) is not int or not 1 <= limit <= PAGE_MAX:
            raise AlphaError(f"Choose a page size from 1 to {PAGE_MAX}.", 400, code="unsupported_input")
        before = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 200:
                    raise ValueError
                decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if not isinstance(decoded, list) or len(decoded) != 2:
                    raise ValueError
                before = (float(decoded[0]), str(uuid.UUID(decoded[1])))
            except (ValueError, TypeError, UnicodeDecodeError):
                raise AlphaError("This page cursor is invalid.", 400, code="unsupported_input") from None
        with self._tx(token, workspace_id, "read") as (cur, _principal, state):
            sql = (f"SELECT p.id::text,p.language,p.current_revision,r.state,r.slides,r.render_manifest IS NOT NULL,r.purged_at IS NOT NULL,"
                   f"extract(epoch from p.created_at),extract(epoch from p.updated_at),r.source FROM public.pr_visual_packs p "
                   f"JOIN public.pr_visual_pack_revisions r ON r.workspace_id=p.workspace_id AND r.pack_id=p.id AND r.revision_no=p.current_revision "
                   f"WHERE p.workspace_id=%s AND p.status='active'")
            params = [workspace_id]
            if before:
                sql += " AND (p.created_at,p.id)<(to_timestamp(%s),%s::uuid)"
                params += list(before)
            cur.execute(sql + " ORDER BY p.created_at DESC,p.id DESC LIMIT %s", (*params, limit + 1))
            rows = cur.fetchall()
            more, rows = len(rows) > limit, rows[:limit]
            items = []
            for pack_id, language, revision, rstate, slides_json, rendered, purged, created, updated, source in rows:
                first = (_json(slides_json) or [{}])[0]
                items.append({"id": pack_id, "language": language, "revision": revision, "state": rstate, "rendered": bool(rendered and not purged),
                              "title": " ".join((first.get("text") or "").split())[:80], "createdAt": float(created), "updatedAt": float(updated),
                              "sourceStatus": source_status(state, _json(source)),
                              "cover": f"/api/workspaces/{workspace_id}/visual-packs/{pack_id}/revisions/{revision}/slides/1" if rendered and not purged else None})
            next_cursor = None
            if more and rows:
                next_cursor = base64.urlsafe_b64encode(json.dumps([float(rows[-1][7]), rows[-1][0]]).encode()).decode().rstrip("=")
            return {"items": items, "nextCursor": next_cursor, "definitionVersion": DEFINITION, "asOf": time.time(), "dataState": "available"}

    def get(self, workspace_id, token, pack_id):
        with self._tx(token, workspace_id, "read") as (cur, _principal, state):
            view = self._view(cur, workspace_id, state, pack_id)
            stale = self._stale_renders(cur, workspace_id, state, view["pack"]["id"])
        if stale:
            self._purge(workspace_id, token, stale)
        return view

    def _view(self, cur, workspace_id, state, pack_id, revision=None):
        pack, rev = self._load(cur, workspace_id, pack_id, revision)
        lang = pack["language"]
        images = _images(state, rev["slides"])
        live = render.public_checks(render.layout(rev["slides"], rev["settings"], images, lang))
        cur.execute("SELECT revision_no,state,extract(epoch from created_at),extract(epoch from superseded_at),render_digest IS NOT NULL FROM public.pr_visual_pack_revisions "
                    "WHERE workspace_id=%s AND pack_id=%s ORDER BY revision_no DESC LIMIT %s", (workspace_id, pack["id"], HISTORY))
        history = [{"revision": n, "state": s, "createdAt": float(c), "supersededAt": _num(x), "rendered": bool(r)} for n, s, c, x, r in cur.fetchall()]
        base = f"/api/workspaces/{workspace_id}/visual-packs/{pack['id']}/revisions/{rev['revision']}"
        rendered = None
        if rev["manifest"]:
            rendered = {"renderDigest": rev["renderDigest"], "renderedAt": rev["renderedAt"], "renderer": rev["manifest"]["renderer"],
                        "available": rev["purgedAt"] is None,
                        "slides": [{k: s[k] for k in ("position", "key", "file", "width", "height", "mime", "bytes", "sha256", "altText")}
                                   | {"href": f"{base}/slides/{s['position']}"} for s in rev["manifest"]["slides"]]}
        channels = [c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
        status = source_status(state, rev["source"])
        current = rev["revision"] == pack["currentRevision"]
        assisted = current and rev["state"] in ("accepted",) + EXPORTED and status == "current" and live["ok"] and rev["purgedAt"] is None
        return {
            "definitionVersion": DEFINITION, "dataState": "available", "asOf": time.time(),
            "pack": {k: pack[k] for k in ("id", "language", "currentRevision", "createdAt", "updatedAt", "status")}
                    | {"format": checks.FORMAT, "source": {"variantId": pack["sourceVariantId"], "campaignId": pack["sourceCampaignId"]}},
            "revision": {"revision": rev["revision"], "state": rev["state"], "current": current, "createdAt": rev["createdAt"],
                         "slides": [{"position": i, "role": checks.ROLES[i - 1], **{k: s.get(k) for k in ("key", "text", "altText", "imageAssetId", "plannedRole")},
                                     "altCustom": s.get("altCustom") is True} for i, s in enumerate(rev["slides"], start=1)],
                         "caption": rev["caption"], "settings": rev["settings"], "checks": live, "sourceStatus": status,
                         "contentDigest": rev["contentDigest"], "approvalDigest": rev["approvalDigest"], "render": rendered,
                         "facts": {"renderedAt": rev["renderedAt"], "acceptedAt": rev["acceptedAt"], "exportReadyAt": rev["exportReadyAt"],
                                   "downloadedAt": rev["downloadedAt"], "downloadCount": rev["downloadCount"],
                                   "userConfirmedUsedAt": rev["confirmedUsedAt"], "queuedAt": rev["queuedAt"], "supersededAt": rev["supersededAt"],
                                   "purgedAt": rev["purgedAt"]},
                         "export": ({"handoff": "assisted_export", "sha256": rev["exportSha256"], "bytes": rev["exportBytes"], "href": f"{base}/export",
                                     "filename": f"rafii-carousel-{pack['id'][:8]}-r{rev['revision']}.zip"} if rev["exportDigest"] else None)},
            "receipt": RECEIPTS[rev["state"]],
            "handoff": {"assistedExport": {"available": assisted, "state": rev["state"] if rev["state"] in EXPORTED else None,
                                           "nextStep": "Download the files and post them yourself; Rafii will not mark anything published."},
                        "queue": {"available": False, "channels": [{"channelId": c.get("id"), "platform": c.get("platform"), **queue_capability(c)} for c in channels[:20]],
                                  "reason": "No connected account can publish a six-image carousel from Rafii yet."}},
            "history": history,
            "options": {"palettes": [{"id": k, "label": v["label"], **{c: v[c] for c in ("background", "text", "accent")}} for k, v in checks.PALETTES.items()],
                        "weights": list(render.fonts.WEIGHTS), "slides": checks.SLIDES, "size": [checks.WIDTH, checks.HEIGHT],
                        "limits": {"text": slide_copy.TEXT_LIMIT, "altText": checks.ALT_MAX, "caption": slide_copy.CAPTION_LIMIT}},
        }

    # --- prepare / edit ----------------------------------------------------------------------------------------------
    def prepare(self, workspace_id, token, body):
        body = body if isinstance(body, dict) else {}
        key = _key(body.get("idempotencyKey"))
        variant_id = body.get("variantId")
        if not isinstance(variant_id, str) or not _REF.match(variant_id):
            raise AlphaError("Choose a draft in this workspace.", 404, code="not_found")
        campaign = body.get("campaignId")
        if campaign is not None and (not isinstance(campaign, str) or not _REF.match(campaign)):
            raise AlphaError("That campaign is not in this workspace.", 404, code="not_found")
        try:
            settings = checks.settings(body.get("settings"))
        except ValueError:
            raise AlphaError("Choose one of the offered palettes and weights.", 400, code="unsupported_input") from None
        request = digest({"variantId": variant_id, "campaignId": campaign, "settings": settings})
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            cur.execute("SELECT id::text,request_digest FROM public.pr_visual_packs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
            found = cur.fetchone()
            if found:
                if found[1] != request:
                    raise AlphaError("This request key was already used for a different pack.", 409, code="idempotency_conflict")
                return {**self._view(cur, workspace_id, state, found[0]), "replayed": True}
            variant = _variant(state, variant_id)
            if variant is None:
                raise AlphaError("Choose a draft in this workspace.", 404, code="not_found")
            if not (variant.get("text") or "").strip():
                raise AlphaError("This draft has no text to turn into slides.", 409, code="unsupported_input")
            campaign_id = _campaign_for(state, variant_id, campaign)
            if campaign is not None and campaign_id is None:
                raise AlphaError("That campaign is not in this workspace or doesn't include this draft.", 404, code="not_found")
            prepared = slide_copy.from_draft(state, variant)
            source = {"variantId": variant_id, "variantRevision": variant.get("revision"), "textSha256": _sha(variant.get("text")),
                      "campaignId": campaign_id, "plan": prepared["plan"]}
            content = {"slides": prepared["slides"], "caption": prepared["caption"], "settings": settings, "source": source}
            measured = render.public_checks(render.layout(prepared["slides"], settings, {}, prepared["language"]))
            pack_id = str(uuid.uuid4())
            cur.execute("INSERT INTO public.pr_visual_packs(id,workspace_id,source_variant_id,source_campaign_id,settings,language,idempotency_key,request_digest,created_by) "
                        "VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)", (pack_id, workspace_id, variant_id, campaign_id, json.dumps(settings), prepared["language"], key, request, principal))
            cur.execute("INSERT INTO public.pr_visual_pack_revisions(workspace_id,pack_id,revision_no,slides,caption,settings,source,content_digest,checks,created_by) "
                        "VALUES(%s,%s,1,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)",
                        (workspace_id, pack_id, json.dumps(prepared["slides"], ensure_ascii=False), prepared["caption"], json.dumps(settings),
                         json.dumps(source, ensure_ascii=False), digest(content), json.dumps(measured, ensure_ascii=False), principal))
            self._fact(cur, workspace_id, pack_id, 1, "prepared", principal, {"slides": checks.SLIDES, "blocking": measured["blocking"]})
            self._audit(cur, workspace_id, principal, "visual_pack.prepared", pack_id, {"revision": 1, "blocking": measured["blocking"]})
            return self._view(cur, workspace_id, state, pack_id)

    def edit(self, workspace_id, token, pack_id, body):
        body = body if isinstance(body, dict) else {}
        key = _key(body.get("idempotencyKey"))
        expected = _expected(body)
        request = digest({k: v for k, v in body.items() if k != "idempotencyKey"})
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id, lock=True)
            cur.execute("SELECT edit_digest FROM public.pr_visual_pack_revisions WHERE workspace_id=%s AND pack_id=%s AND edit_key=%s", (workspace_id, pack["id"], key))
            replay = cur.fetchone()
            if replay:
                if replay[0] != request:
                    raise AlphaError("This request key was already used for a different edit.", 409, code="idempotency_conflict")
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}
            self._current(pack, rev, expected)
            if pack["currentRevision"] >= MAX_REVISIONS:
                raise AlphaError(f"This pack has {MAX_REVISIONS} revisions, the most one pack keeps. Start a new pack from the draft.", 409, code="unsupported_input")
            lang, assets = pack["language"], _assets(state)
            slides = [dict(s) for s in rev["slides"]]
            by_key = {s["key"]: s for s in slides}
            caption, settings, source, changed = rev["caption"], dict(rev["settings"]), dict(rev["source"]), set()
            mode = body.get("source")
            if mode is not None:
                if mode not in ("keep", "resplit"):
                    raise AlphaError("Choose to keep the slides or update them from the draft.", 400, code="unsupported_input")
                variant = _variant(state, source.get("variantId"))
                if variant is None:
                    raise AlphaError("The draft this pack came from is gone.", 409, code="source_unavailable")
                source.update(variantRevision=variant.get("revision"), textSha256=_sha(variant.get("text")))
                changed.add("source")
                if mode == "resplit":
                    prepared = slide_copy.from_draft(state, variant)
                    for slide, fresh in zip(slides, prepared["slides"]):
                        slide["text"], slide["plannedRole"] = fresh["text"], fresh["plannedRole"]
                        slide.pop("altCustom", None)
                    caption, source["plan"] = prepared["caption"], prepared["plan"]
                    changed.update(("text", "caption"))
            patches = body.get("slides") or []
            if not isinstance(patches, list) or len(patches) > checks.SLIDES:
                raise AlphaError("Send at most six slide changes.", 400, code="unsupported_input")
            for patch in patches:
                if not isinstance(patch, dict) or patch.get("key") not in by_key:
                    raise AlphaError("Each slide change names one of this pack's slides.", 400, code="unsupported_input")
                slide = by_key[patch["key"]]
                if "text" in patch:
                    slide["text"] = _text(patch["text"], slide_copy.TEXT_LIMIT, "slide text")
                    changed.add("text")
                if "altText" in patch:
                    slide["altText"] = _text(patch["altText"], checks.ALT_MAX, "alt text")
                    slide["altCustom"] = True
                    changed.add("alt")
                if "imageAssetId" in patch:
                    image = patch["imageAssetId"]
                    if image is not None and (not isinstance(image, str) or not asset_kinds.is_postable_image(assets.get(image))):
                        # Same answer for another workspace's image and a missing one.
                        raise AlphaError("Choose an image from this workspace's Library.", 404, code="not_found")
                    slide["imageAssetId"] = image
                    changed.add("image")
            if "order" in body:
                order = body["order"]
                if not isinstance(order, list) or sorted(order) != sorted(by_key):
                    raise AlphaError("A new order lists each of the six slides once.", 400, code="unsupported_input")
                if order != [s["key"] for s in slides]:
                    slides = [by_key[k] for k in order]
                    changed.add("order")
            if "caption" in body:
                caption = _text(body["caption"], slide_copy.CAPTION_LIMIT, "caption text")
                changed.add("caption")
            if "settings" in body:
                try:
                    settings = checks.settings({**settings, **(body["settings"] if isinstance(body["settings"], dict) else {"palette": None})})
                except ValueError:
                    raise AlphaError("Choose one of the offered palettes and weights.", 400, code="unsupported_input") from None
                changed.add("settings")
            for position, slide in enumerate(slides, start=1):   # default alt text follows what the slide now shows
                if slide.get("altCustom") is not True:
                    slide["altText"] = slide_copy.default_alt(position, slide["text"], assets.get(slide.get("imageAssetId")) if slide.get("imageAssetId") else None, lang)
            content = {"slides": slides, "caption": caption, "settings": settings, "source": source}
            if digest(content) == rev["contentDigest"]:
                return {**self._view(cur, workspace_id, state, pack["id"]), "unchanged": True}
            measured = render.public_checks(render.layout(slides, settings, _images(state, slides), lang))
            number = rev["revision"] + 1
            cur.execute("INSERT INTO public.pr_visual_pack_revisions(workspace_id,pack_id,revision_no,slides,caption,settings,source,content_digest,checks,created_by,edit_key,edit_digest) "
                        "VALUES(%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s)",
                        (workspace_id, pack["id"], number, json.dumps(slides, ensure_ascii=False), caption, json.dumps(settings), json.dumps(source, ensure_ascii=False),
                         digest(content), json.dumps(measured, ensure_ascii=False), principal, key, request))
            # The replaced revision keeps its content and facts but its acceptance and exports stop applying.
            cur.execute("UPDATE public.pr_visual_pack_revisions SET state='superseded',superseded_at=now() WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s",
                        (workspace_id, pack["id"], rev["revision"]))
            cur.execute("UPDATE public.pr_visual_packs SET current_revision=%s,settings=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id=%s",
                        (number, json.dumps(settings), workspace_id, pack["id"]))
            self._fact(cur, workspace_id, pack["id"], number, "edited", principal, {"changes": len(changed)})
            self._fact(cur, workspace_id, pack["id"], rev["revision"], "superseded", principal, {"previousState": rev["state"]})
            self._audit(cur, workspace_id, principal, "visual_pack.edited", pack["id"], {"revision": number, "changes": sorted(changed),
                                                                                         "invalidated": rev["state"] if rev["state"] in ACCEPTED else None})
            return self._view(cur, workspace_id, state, pack["id"])

    # --- render ------------------------------------------------------------------------------------------------------
    def render(self, workspace_id, token, pack_id, body):
        expected = _expected(body)
        with self._tx(token, workspace_id, "edit") as (cur, _principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id)
            self._current(pack, rev, expected)
            if rev["manifest"] is not None:
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}   # one render per revision
            images = _images(state, rev["slides"])
            measured = render.layout(rev["slides"], rev["settings"], images, pack["language"])
            if not measured["ok"]:
                raise _blocking_error(measured)
            storage = self._storage()
            snapshot = {"images": images, "sourceStatus": source_status(state, rev["source"])}
        image_bytes = {}
        for asset_id, asset in snapshot["images"].items():
            raw = storage.get(workspace_id, "media", asset.get("objectName") or "")
            if hashlib.sha256(raw).hexdigest() != asset.get("hash"):
                raise AlphaError("A Library image changed in storage. Replace it on the slide and render again.", 409, code="source_unavailable")
            image_bytes[asset_id] = raw
        try:
            result = render.render(rev["slides"], rev["settings"], snapshot["images"], image_bytes, pack["language"])
        except render.RenderError as error:
            raise AlphaError(f"The slides could not be rendered safely: {error}.", 409, code="unsupported_input") from None
        stem = rev["id"].replace("-", "")
        for item in result["files"]:
            item["objectName"] = f"{stem}-{item['sha256']}.png"
            try:
                item["storagePath"] = storage.put_immutable(workspace_id, "visual-pack", item["objectName"], item["png"], content_type="image/png")
            except AlphaError as error:
                if error.status != 409:   # content-addressed and immutable: an existing object already holds these bytes
                    raise
                item["storagePath"] = f"{workspace_id}/visual-pack/{item['objectName']}"
        manifest = self._manifest(pack, rev, result)
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack2, rev2 = self._load(cur, workspace_id, pack["id"], rev["revision"], lock=True)
            if rev2["manifest"] is not None:
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}
            if rev2["state"] != "draft" or rev2["contentDigest"] != rev["contentDigest"] or pack2["currentRevision"] != rev["revision"]:
                stale = True
            else:
                stale = False
                cur.execute("UPDATE public.pr_visual_pack_revisions SET state='rendered',render_manifest=%s::jsonb,render_digest=%s,rendered_at=now(),checks=%s::jsonb "
                            "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND render_manifest IS NULL",
                            (json.dumps(manifest, ensure_ascii=False), digest(manifest), json.dumps(result["checks"], ensure_ascii=False), workspace_id, pack["id"], rev["revision"]))
                self._fact(cur, workspace_id, pack["id"], rev["revision"], "rendered", principal, {"slides": checks.SLIDES, "bytes": sum(f["bytes"] for f in result["files"])})
                self._audit(cur, workspace_id, principal, "visual_pack.rendered", pack["id"], {"revision": rev["revision"]})
                return self._view(cur, workspace_id, state, pack["id"])
        if stale:   # edited meanwhile: these files belong to nothing (no other render can have recorded them)
            for item in result["files"]:
                try:
                    storage.delete(workspace_id, "visual-pack", item["objectName"])
                except AlphaError:
                    pass
            raise AlphaError("This pack changed while it was rendering. Reload it and render the latest version.", 409, code="revision_conflict")

    @staticmethod
    def _manifest(pack, rev, result) -> dict:
        palette = checks.PALETTES[result["settings"]["palette"]]
        source = rev["source"]
        images = [s.get("imageAssetId") for s in rev["slides"] if s.get("imageAssetId")]
        return {"schema": "rafii.visual-pack-manifest.v1", "format": checks.FORMAT, "packId": pack["id"], "revision": rev["revision"],
                "revisionId": rev["id"], "contentDigest": rev["contentDigest"], "language": pack["language"], "caption": rev["caption"],
                "settings": result["settings"], "palette": {k: palette[k] for k in ("background", "text", "muted", "accent")},
                "safeArea": {k: checks.SAFE[k] for k in ("top", "bottom", "sides")}, "renderer": result["renderer"],
                "slides": [{"position": f["position"], "key": f["key"], "role": f["role"], "file": f"slide-{f['position']:02d}.png", "width": f["width"],
                            "height": f["height"], "mime": f["mime"], "bytes": f["bytes"], "sha256": f["sha256"], "pixelSha256": f["pixelSha256"],
                            "objectName": f["objectName"], "storagePath": f["storagePath"], "typography": f["typography"],
                            "text": rev["slides"][f["position"] - 1]["text"], "altText": rev["slides"][f["position"] - 1]["altText"],
                            "image": ({"assetId": rev["slides"][f["position"] - 1]["imageAssetId"], "label": f["label"]}
                                      if rev["slides"][f["position"] - 1].get("imageAssetId") else None)} for f in result["files"]],
                "lineage": {"sourceVariantId": source.get("variantId"), "sourceVariantRevision": source.get("variantRevision"),
                            "sourceTextSha256": source.get("textSha256"), "sourceCampaignId": source.get("campaignId"),
                            "plan": {k: (source.get("plan") or {}).get(k) for k in ("schema", "platform", "registryRelease")},
                            "imageAssetIds": images, "operation": "render", "paidCalls": 0},
                "generatedImagery": any(f["label"] for f in result["files"])}

    # --- accept / export / download / confirm -------------------------------------------------------------------------
    def accept(self, workspace_id, token, pack_id, body):
        expected = _expected(body)
        if (body or {}).get("confirmed") is not True:
            raise AlphaError("Confirm that you accept this exact revision.", 400, code="approval_required")
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id, lock=True)
            self._current(pack, rev, expected)
            if rev["state"] in ACCEPTED:
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}
            if rev["state"] != "rendered":
                raise AlphaError("Render the slides before accepting them.", 409, code="render_required")
            self._ready_inputs(state, rev)
            measured = render.layout(rev["slides"], rev["settings"], _images(state, rev["slides"]), pack["language"])
            if not measured["ok"]:
                raise _blocking_error(measured)
            approval = digest({"packId": pack["id"], "revision": rev["revision"], "renderDigest": rev["renderDigest"], "contentDigest": rev["contentDigest"],
                               "source": {k: rev["source"].get(k) for k in ("variantId", "variantRevision", "textSha256")}})
            cur.execute("UPDATE public.pr_visual_pack_revisions SET state='accepted',approval_digest=%s,accepted_by=%s,accepted_at=now() "
                        "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND state='rendered'", (approval, principal, workspace_id, pack["id"], rev["revision"]))
            self._fact(cur, workspace_id, pack["id"], rev["revision"], "accepted", principal)
            growth_events.emit(cur, workspace_id=workspace_id, event="visual_pack.accepted", entity_id=pack["id"], revision=rev["revision"], user_id=principal,
                               values={"format": "carousel", "language": _language_enum(pack["language"]), "slides": checks.SLIDES, "revision": rev["revision"]})
            self._audit(cur, workspace_id, principal, "visual_pack.accepted", pack["id"], {"revision": rev["revision"]})
            return self._view(cur, workspace_id, state, pack["id"])

    def _slide_files(self, workspace_id, manifest) -> dict:
        storage = self._storage()
        files = {}
        for slide in manifest["slides"]:
            raw = storage.get(workspace_id, "visual-pack", slide["objectName"])
            if hashlib.sha256(raw).hexdigest() != slide["sha256"]:
                raise AlphaError("A rendered slide no longer matches its recorded hash. Render the pack again.", 502, code="integrity_failed")
            files[slide["position"]] = raw
        return files

    def export(self, workspace_id, token, pack_id, body):
        expected = _expected(body)
        with self._tx(token, workspace_id, "edit") as (cur, _principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id)
            self._current(pack, rev, expected)
            if rev["state"] in EXPORTED:
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}   # exported once; downloads reuse it
            if rev["state"] != "accepted":
                raise AlphaError("Accept this exact revision before exporting it.", 409, code="approval_required")
            self._ready_inputs(state, rev)
        archive = build_zip(rev["manifest"], self._slide_files(workspace_id, rev["manifest"]))
        sha = hashlib.sha256(archive).hexdigest()
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack2, rev2 = self._load(cur, workspace_id, pack["id"], lock=True)
            self._current(pack2, rev2, expected)
            if rev2["state"] in EXPORTED:
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}
            if rev2["state"] != "accepted" or rev2["approvalDigest"] != rev["approvalDigest"]:
                raise AlphaError("This pack changed while it was exporting. Reload it and try again.", 409, code="revision_conflict")
            self._ready_inputs(state, rev2)
            cur.execute("UPDATE public.pr_visual_pack_revisions SET state='export_ready',export_digest=%s,export_sha256=%s,export_bytes=%s,export_ready_at=now(),exported_by=%s "
                        "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND state='accepted'",
                        (digest({"approvalDigest": rev["approvalDigest"], "sha256": sha, "bytes": len(archive)}), sha, len(archive), principal, workspace_id, pack["id"], rev["revision"]))
            self._fact(cur, workspace_id, pack["id"], rev["revision"], "export_ready", principal, {"bytes": len(archive)})
            growth_events.emit(cur, workspace_id=workspace_id, event="visual_pack.exported", entity_id=pack["id"], revision=rev["revision"], user_id=principal,
                               values={"handoff": "assisted_export", "slides": checks.SLIDES, "revision": rev["revision"]})
            self._audit(cur, workspace_id, principal, "visual_pack.exported", pack["id"], {"revision": rev["revision"], "handoff": "assisted_export"})
            return self._view(cur, workspace_id, state, pack["id"])

    def download(self, workspace_id, token, pack_id, revision):
        """The export of the current, exported revision as bytes, rebuilt from the stored slides and checked against the
        recorded hash; each download is counted, the first one recorded as the `downloaded` fact."""
        if type(revision) is not int or revision < 1:
            raise AlphaError("That pack revision does not exist.", 404, code="not_found")
        with self._tx(token, workspace_id, "edit") as (cur, _principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id, revision)
            self._downloadable(state, pack, rev)
        archive = build_zip(rev["manifest"], self._slide_files(workspace_id, rev["manifest"]))
        if hashlib.sha256(archive).hexdigest() != rev["exportSha256"] or len(archive) != rev["exportBytes"]:
            raise AlphaError("The export no longer matches what was recorded. Export the pack again.", 502, code="integrity_failed")
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack, rev = self._load(cur, workspace_id, pack["id"], revision, lock=True)
            self._downloadable(state, pack, rev)
            cur.execute("UPDATE public.pr_visual_pack_revisions SET download_count=download_count+1,downloaded_at=coalesce(downloaded_at,now()),"
                        "state=CASE WHEN state='export_ready' THEN 'downloaded' ELSE state END WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s",
                        (workspace_id, pack["id"], revision))
            if self._fact(cur, workspace_id, pack["id"], revision, "downloaded", principal):
                self._audit(cur, workspace_id, principal, "visual_pack.downloaded", pack["id"], {"revision": revision})
        return archive, f"rafii-carousel-{pack['id'][:8]}-r{revision}.zip"

    def _downloadable(self, state, pack, rev):
        if rev["revision"] != pack["currentRevision"] or rev["state"] == "superseded":
            raise AlphaError("This export belongs to an earlier version of the pack. Export the latest version.", 409, code="approval_expired")
        if rev["state"] not in EXPORTED:
            raise AlphaError("Export this revision before downloading it.", 409, code="approval_required")
        self._ready_inputs(state, rev)

    def confirm_used(self, workspace_id, token, pack_id, body):
        expected = _expected(body)
        if (body or {}).get("confirmed") is not True:
            raise AlphaError("Confirm that you posted these files yourself.", 400, code="approval_required")
        with self._tx(token, workspace_id, "edit") as (cur, principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id, lock=True)
            self._current(pack, rev, expected)
            if rev["state"] == "user_confirmed_used":
                return {**self._view(cur, workspace_id, state, pack["id"]), "replayed": True}
            if rev["downloadedAt"] is None or rev["state"] != "downloaded":
                raise AlphaError("Download the files before confirming you used them.", 409, code="approval_required")
            cur.execute("UPDATE public.pr_visual_pack_revisions SET state='user_confirmed_used',confirmed_used_at=now(),confirmed_by=%s "
                        "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND state='downloaded'", (principal, workspace_id, pack["id"], rev["revision"]))
            self._fact(cur, workspace_id, pack["id"], rev["revision"], "user_confirmed_used", principal)
            self._audit(cur, workspace_id, principal, "visual_pack.used_confirmed", pack["id"], {"revision": rev["revision"]})
            return self._view(cur, workspace_id, state, pack["id"])

    def queue(self, workspace_id, token, pack_id, body):
        """Queue handoff: only for an exact account whose publisher verified multi-image support. None has, so this
        always refuses before writing anything and points to the assisted export."""
        expected = _expected(body)
        channel_id = (body or {}).get("channelId")
        with self._tx(token, workspace_id, "approve") as (cur, _principal, state):
            pack, rev = self._load(cur, workspace_id, pack_id)
            self._current(pack, rev, expected)
            channel = next((c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and c.get("id") == channel_id), None)
            if channel is None:
                raise AlphaError("That account is not connected to this workspace.", 404, code="not_found")
            capability = queue_capability(channel)
        raise AlphaError(f"{capability['reason']} Nothing was queued. Export the files and post them yourself.", 409, code="unsupported_input")

    def slide(self, workspace_id, token, pack_id, revision, position):
        """One rendered slide (any revision that still has its files), verified against its recorded hash."""
        if type(revision) is not int or type(position) is not int or not 1 <= position <= checks.SLIDES:
            raise AlphaError("That slide does not exist.", 404, code="not_found")
        with self._tx(token, workspace_id, "read") as (cur, _principal, _state):
            _pack, rev = self._load(cur, workspace_id, pack_id, revision)
        if rev["manifest"] is None or rev["purgedAt"] is not None:
            raise AlphaError("That slide has no rendered file.", 404, code="not_found")
        slide = rev["manifest"]["slides"][position - 1]
        raw = self._storage().get(workspace_id, "visual-pack", slide["objectName"])
        if hashlib.sha256(raw).hexdigest() != slide["sha256"]:
            raise AlphaError("A rendered slide no longer matches its recorded hash. Render the pack again.", 502, code="integrity_failed")
        return raw, slide["sha256"]

    # --- deletion propagation --------------------------------------------------------------------------------------
    @staticmethod
    def _stale_renders(cur, workspace_id, state, pack_id=None, limit=50):
        """Rendered revisions whose slides embed a Library image that has since been deleted: their files must go."""
        live = {k for k, v in _assets(state).items() if asset_kinds.is_postable_image(v)}
        sql = ("SELECT pack_id::text,revision_no,render_manifest FROM public.pr_visual_pack_revisions WHERE workspace_id=%s "
               "AND render_manifest IS NOT NULL AND purged_at IS NULL AND jsonb_array_length(render_manifest->'lineage'->'imageAssetIds')>0")
        params = [workspace_id]
        if pack_id:
            sql += " AND pack_id=%s"
            params.append(pack_id)
        cur.execute(sql + " ORDER BY created_at LIMIT %s", (*params, limit))
        out = []
        for pid, number, manifest in cur.fetchall():
            manifest = _json(manifest)
            if any(i not in live for i in manifest["lineage"]["imageAssetIds"]):
                out.append({"packId": pid, "revision": number, "objects": [s["objectName"] for s in manifest["slides"]]})
        return out

    def _purge(self, workspace_id, token, stale):
        storage = getattr(getattr(self.hosted, "assets", None), "storage", None)
        if storage is None:
            return 0
        for item in stale:
            for name in item["objects"]:
                storage.delete(workspace_id, "visual-pack", name)
        with self._tx(token, workspace_id, "read") as (cur, _principal, _state):
            for item in stale:   # housekeeping by the system, not a decision of the person who happened to read
                cur.execute("UPDATE public.pr_visual_pack_revisions SET purged_at=now(),purge_reason='source_image_deleted' "
                            "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND purged_at IS NULL", (workspace_id, item["packId"], item["revision"]))
                self._fact(cur, workspace_id, item["packId"], item["revision"], "purged", None, {"reason": "source_image_deleted", "files": len(item["objects"])})
        return len(stale)


def _blocking_error(measured) -> AlphaError:
    """The first blocking finding (by severity of the fix it needs) as the error to raise."""
    order = {"needs_shorter_copy": ("Some slides have more text than fits at the smallest allowed size. Shorten those slides.", "needs_shorter_copy"),
             "missing_glyphs": ("Some slides use characters the slide font can't draw (for example emoji). Remove or replace them.", "unsupported_input"),
             "missing_image": ("An image on these slides was deleted from the Library. Replace or remove it.", "source_unavailable"),
             "empty_slide": ("Every slide needs text.", "unsupported_input"),
             "alt_text_missing": ("Every slide needs alt text.", "unsupported_input")}
    found = [f["code"] for s in measured["slides"] for f in s["findings"] if f["severity"] == "blocking"]
    code = next(c for c in order if c in found)
    message, error_code = order[code]
    return AlphaError(message, 409, code=error_code)
