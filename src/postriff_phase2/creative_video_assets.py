"""Resolve approved private inputs and commit generated outputs through Rafii's Library and cleanup registry."""
import hashlib
from copy import deepcopy
import uuid

from postriff_alpha.domain import AlphaError

from . import asset_kinds
from .creative_video_media import analyze_reference


def validate_generated_clip(raw, profile):
    """Inspect the actual returned bytes before reserving a private object or publishing a clip ID."""
    try:
        analysis = analyze_reference(raw, count_frames=True, include_audio_rhythm=False)
    except AlphaError as error:
        if error.status >= 500:
            raise  # Worker unavailability can be retried against the same provider operation.
        raise AlphaError("The provider returned an unreadable video.", 422, code="creative_video_provider_output_unusable") from error
    # The model's duration is a target. Allow one 24fps frame of container rounding.
    expected_frames = round(profile["durationMs"] * profile["fps"] / 1000)
    if (abs(analysis["durationMs"] - profile["durationMs"]) > 42
            or abs(analysis["decodedFrameCount"] - expected_frames) > 1
            or analysis["decodedFrameCount"] < profile.get("minFrames", 1)
            or (profile["hasAudio"] and all(s["measurements"]["audioRms"] is None for s in analysis["scenes"]))
            or any(analysis[k] != profile[k] for k in ("width", "height", "fps", "hasAudio"))):
        raise AlphaError("The returned video does not match the approved duration, format or audio request.", 422,
                         code="creative_video_provider_output_unusable")
    if (not analysis["measured"]["hasChangingFrames"]
            or not any(s["measurements"]["meanFrameChange"] > 0 for s in analysis["scenes"])):
        raise AlphaError("The clip needs visible movement within a shot.", 422,
                         code="creative_video_provider_output_unusable")
    if profile.get("strictQuality"):
        from .creative_video_strategy import validate_quality_observations
        validate_quality_observations(analysis, profile)
    return {k: analysis[k] for k in ("width", "height", "durationMs", "fps", "hasAudio", "sha256", "decodedFrameCount")}


def asset(state, asset_id):
    item = next((a for a in (state.get("phase2") or {}).get("assets", []) if a.get("id") == asset_id), None)
    if not asset_kinds.is_postable_video(item):
        raise AlphaError("This verified video is unavailable in this workspace.", 404)
    return item


def identity(item):
    return (item["id"], item["objectName"], item["etag"], item["bytes"], item["mime"])


def read_video(service, workspace, item):
    if item["bytes"] > 64 * 1024 * 1024:
        raise AlphaError("Use a video no larger than 64 MiB for creative work.", 413)
    store = service.video_uploads.storage
    if store is None:
        raise AlphaError("Private video storage is unavailable.", 503)
    return store.get_verified_video(workspace, item["objectName"], expected_bytes=item["bytes"],
                                    expected_etag=item["etag"], expected_mime=item["mime"])


class OutputVideo:
    """The stable output address includes the actual bytes; ambiguous writes are compared before re-use."""
    def __init__(self, service, workspace, scope, raw):
        self.service = service
        self.workspace = workspace
        self.raw = raw
        self.sha = hashlib.sha256(raw).hexdigest()
        self.id = uuid.uuid5(uuid.UUID(workspace), scope + ":" + self.sha).hex
        self.name = self.id + ".mp4"
        self.uploads = service.video_uploads

    def reserve(self, cur, state, actor, limit):
        if not 0 < len(self.raw) <= min(limit, 64 * 1024 * 1024):
            raise AlphaError("This output exceeds the private video size limit.", 413)
        existing = self.uploads.rows.get(cur, self.workspace, self.id)
        if existing is None:
            self.uploads.reserve_slot(cur, state, self.workspace, actor, self.id, "video/mp4", len(self.raw))
            return
        if existing["status"] not in ("pending", "committed") or existing["declaredBytes"] != len(self.raw):
            raise AlphaError("This video upload needs reconciliation.", 409)
        if existing["status"] == "committed":
            asset(state, self.id)

    def stage(self, limit):
        store = self.uploads.storage
        try:
            store.object_info(self.workspace, "video", self.name)
        except AlphaError as missing:
            if missing.status != 404:
                raise
            try:
                store.put_reserved_video(self.workspace, self.name, self.raw)
            except AlphaError as error:
                if error.status != 409 and error.status < 500:
                    raise
                # Successful concurrent writes and lost PUT acknowledgements can use the same verified object.
        self._match()
        upload = {"objectName": self.name, "declaredBytes": len(self.raw)}
        info, error = self.uploads._inspect(self.workspace, upload, limit)
        if error or not info["locationChecked"] or info["durationSource"] != "container" or not info["duration"]:
            raise AlphaError(error or "The generated MP4 could not be verified.", 422,
                             code="creative_video_storage_output_unusable")
        return info

    def _match(self):
        store = self.uploads.storage
        info = store.object_info(self.workspace, "video", self.name)
        if info["bytes"] != len(self.raw) or info["mime"] != "video/mp4":
            raise AlphaError("Stored footage differs from the generated result.", 409,
                             code="creative_video_storage_output_unusable")
        content = store.get_verified_video(self.workspace, self.name, expected_bytes=info["bytes"],
                                           expected_mime=info["mime"], expected_etag=info["etag"])
        if hashlib.sha256(content).hexdigest() != self.sha:
            raise AlphaError("Stored footage differs from the generated result.", 409,
                             code="creative_video_storage_output_unusable")

    def abort(self, cur, reason):
        slot = self.uploads.rows.get(cur, self.workspace, self.id)
        if slot and slot["status"] == "pending":
            self.uploads.rows.set_status(cur, self.workspace, self.id, "aborted", reason)

    def commit(self, cur, state, actor, info, provenance):
        slot = self.uploads.rows.get(cur, self.workspace, self.id)
        if not slot or slot["status"] not in ("pending", "committed"):
            raise AlphaError("The output slot expired. Render the project again.", 409)
        if slot["status"] == "committed":
            asset(state, self.id)
            return state
        item = {"id": self.id, "kind": "video", "mime": "video/mp4", "category": "video",
                "objectName": self.name, "bucket": slot["bucket"], "storagePath": f"{self.workspace}/video/{self.name}",
                "bytes": info["bytes"], "duration": info["duration"], "durationSource": "container",
                "width": info["width"], "height": info["height"], "etag": info["etag"], "hash": self.sha,
                "displayTitle": provenance["title"], "verified": {"container": True, "locationChecked": True},
                "processing": "ready", "frames": [], "uploadedBy": actor, "deleted": False, "provenance": provenance}
        next_state = self.service.commands.add_asset(deepcopy(state), actor, item)
        self.service.repository.save_state(cur, self.workspace, state, next_state, actor)
        self.uploads.rows.set_status(cur, self.workspace, self.id, "committed")
        return next_state
