"""What an asset in `state.phase2.assets` is, derived the same way everywhere (chat-context SPEC §5.13, §7.6).

`kind` comes from `mime` (never from a client), `category` defaults to `media`, and readiness depends on the kind:
an image once it was decoded, a video once the server verified the upload. `web/src/lib/media/asset-kinds.ts`
mirrors these predicates.
"""
from __future__ import annotations

VIDEO_MIMES = ("video/mp4", "video/quicktime")
READY = {"image": "decoded", "video": "ready"}


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
    """Images a post can be scheduled with: decoded and not deleted. Videos never are in Phase 1."""
    return kind_of(asset) == "image" and is_ready(asset)


def is_library_asset(asset):
    """Photos and videos the Library lists (posters and frames live inside their video, never as assets)."""
    return _live(asset) and kind_of(asset) in ("image", "video")
