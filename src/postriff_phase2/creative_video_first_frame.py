"""An approved, decoded Library rendition used as the opening image of one Veo take."""
import hashlib
import re

from postriff_alpha.domain import AlphaError
from . import asset_kinds, media_consent


ASSET_ID = re.compile(r"[0-9a-f]{32}")
MAX_BYTES = 8 * 1024 * 1024


def manifest(state, workspace, asset_id):
    grant = media_consent.first_frame_grant(state)
    if not grant:
        raise AlphaError("The workspace owner must allow Library first frames for Google Cloud Veo.", 403,
                         code="creative_video_first_frame_consent")
    item = next((a for a in (state.get("phase2") or {}).get("assets", [])
                 if isinstance(a, dict) and a.get("id") == asset_id), None)
    if (not asset_kinds.is_postable_image(item) or item.get("sourceId") or item.get("mime") != "image/jpeg" or
            asset_kinds.category(item) != "media" or not ASSET_ID.fullmatch(asset_id) or
            not re.fullmatch(r"[0-9a-f]{64}", str(item.get("hash") or ""))):
        raise AlphaError("Choose a decoded private Library photo from this workspace.", 404)
    name = f"{asset_id}-{item['hash']}.jpg"
    if (item.get("objectName") != name or item.get("storagePath") != f"{workspace}/media/{name}" or
            type(item.get("bytes")) is not int or not 0 < item["bytes"] <= MAX_BYTES or
            any(type(item.get(d)) is not int or not 320 <= item[d] <= 4096 for d in ("width", "height"))):
        raise AlphaError("The selected photo has no verified private rendition in this workspace.", 409)
    return {"assetId": asset_id, "sha256": item["hash"], "mime": item["mime"], "bytes": item["bytes"],
            "width": item["width"], "height": item["height"], "grantId": grant}


def verify(raw, approved):
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES or approved.get("mime") != "image/jpeg"
            or len(raw) != approved.get("bytes") or not raw.startswith(b"\xff\xd8\xff")
            or hashlib.sha256(raw).hexdigest() != approved.get("sha256")):
        raise AlphaError("The private first frame no longer matches this quote. Review the photo again.", 409)


def read(service, workspace, approved):
    store = getattr(getattr(service, "assets", None), "storage", None)
    if store is None:
        raise AlphaError("Private photo storage is unavailable.", 503)
    name = f"{approved['assetId']}-{approved['sha256']}.jpg"
    raw = store.get(workspace, "media", name)
    verify(raw, approved)
    return raw
