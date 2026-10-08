"""What an asset in `state.phase2.assets` is, derived the same way everywhere (chat-context SPEC §5.13, §7.6).

`kind` comes from `mime` (never from a client), `category` defaults to `media`, and readiness depends on the kind:
an image once it was decoded, a video once the server verified the upload. `web/src/lib/media/asset-kinds.ts`
mirrors these predicates.
"""
from __future__ import annotations

import re

VIDEO_MIMES = ("video/mp4", "video/quicktime")
READY = {"image": "decoded", "video": "ready", "document": "validated"}


def kind_of(asset):
    if not isinstance(asset, dict):
        return None
    mime = str(asset.get("mime") or "").lower()
    if not mime:
        return "image"   # records from before video existed carry no mime; every one of them is an image
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime == "application/pdf":
        return "document"
    return None


def category(asset):
    value = asset.get("category") if isinstance(asset, dict) else None
    return value if isinstance(value, str) and value else "media"


def _live(asset):
    return isinstance(asset, dict) and not asset.get("deleted") and not asset.get("deletionPending")


def is_ready(asset):
    kind = kind_of(asset)
    return _live(asset) and kind is not None and asset.get("processing") == READY[kind]


def is_postable_image(asset):
    """Images a post can be scheduled with: decoded and not deleted."""
    return kind_of(asset) == "image" and is_ready(asset)


def is_postable_video(asset):
    """Only a fully inspected, immutable private upload may enter a video approval."""
    if kind_of(asset) != "video" or not is_ready(asset) or asset.get("mime") not in VIDEO_MIMES:
        return False
    verified = asset.get("verified") if isinstance(asset.get("verified"), dict) else {}
    duration = asset.get("duration")
    size = asset.get("bytes")
    extension = "mp4" if asset["mime"] == "video/mp4" else "mov"
    return (verified.get("container") is True and verified.get("locationChecked") is True
            and asset.get("durationSource") == "container" and type(duration) in (int, float) and 0 < duration <= 180
            and type(size) is int and 0 < size <= 100_000_000
            and isinstance(asset.get("etag"), str) and bool(asset["etag"])
            and isinstance(asset.get("bucket"), str) and bool(asset["bucket"])
            and re.fullmatch(r"[0-9a-f]{32}\." + extension, str(asset.get("objectName") or "")) is not None)


def is_library_asset(asset):
    """Photos and videos the Library lists (posters and frames live inside their video, never as assets)."""
    return _live(asset) and kind_of(asset) in ("image", "video", "document")
