"""Chat video uploads straight to private storage (chat-context SPEC §5.7, §7.2–7.4, §14.2).

The browser PUTs the file to a signed, single-object URL; video bytes never pass through a function. `begin` checks
role, caps and the declared size and length, records a pending row and mints the URL (the token is never stored).
`commit` believes only what storage reports: HEAD size/type/ETag, bounded range reads for the `ftyp` brand and
`moov` (duration, frame size, location tags), then decodes the browser's frames through the Pillow path and adds the
asset in one command. Anything wrong deletes the object (400); storage trouble keeps the row pending (503, retryable).
`sweep` removes objects of uploads that were never finished, 24 h after their token expired.

Phase 1 caps are locked: at most 100 MB and 3 minutes, whatever the environment asks for (the Free-plan bucket
uses POSTRIFF_VIDEO_MAX_BYTES=50000000). Everything is off unless RAFII_VIDEO_UPLOADS_ENABLED is set.
"""
from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from dataclasses import dataclass

from postriff_alpha.domain import AlphaError

from . import asset_kinds, mp4_boxes

PHASE1_MAX_BYTES = 100_000_000
PHASE1_MAX_SECONDS = 180
MIMES = {"video/mp4": "mp4", "video/quicktime": "mov"}
TOKEN_SECONDS = 2 * 3600
SWEEP_MARGIN = 24 * 3600
PENDING_PER_MEMBER = 3
PENDING_PER_WORKSPACE = 6
HEAD_BYTES = 64 * 1024
PREFLIGHT_TTL = 300
ASSET_ID = re.compile(r"^[0-9a-f]{32}$")

MSG = {
    "off": "Video uploads aren't available yet.",
    "format": "Use an MP4 or MOV video.",
    "location": "This video still has location data. Export it without location and try again.",
    "not_pending": "This upload isn't waiting to be finished.",
    "caps": "Finish or remove your other video uploads first.",
    "storage": "Couldn't check this video yet. Try again.",
    "ready": "Remove ready videos from the Library.",
    "not_video": "This isn't a video.",
    "sign_in": "Sign in to upload videos.",
}


def too_large(max_bytes):
    return f"This video is over {max_bytes // 1_000_000} MB."


def too_long(max_seconds):
    return f"This video is longer than {max_seconds // 60} minutes."


def _flag(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _int(values, name, default, low, high):
    try:
        value = int(values.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass(frozen=True)
class VideoPolicy:
    enabled: bool = False
    bucket: str = "postriff-video"
    max_bytes: int = PHASE1_MAX_BYTES
    max_seconds: int = PHASE1_MAX_SECONDS
    frames: int = 4
    daily_bytes: int = 1_000_000_000
    workspace_max_bytes: int = 2_000_000_000

    @classmethod
    def from_environment(cls, values):
        values = values or {}
        return cls(
            enabled=_flag(values.get("RAFII_VIDEO_UPLOADS_ENABLED")),
            bucket=str(values.get("POSTRIFF_VIDEO_BUCKET") or "postriff-video"),
            max_bytes=_int(values, "POSTRIFF_VIDEO_MAX_BYTES", PHASE1_MAX_BYTES, 1, PHASE1_MAX_BYTES),
            max_seconds=_int(values, "POSTRIFF_VIDEO_MAX_SECONDS", PHASE1_MAX_SECONDS, 1, PHASE1_MAX_SECONDS),
            frames=_int(values, "POSTRIFF_VIDEO_FRAMES", 4, 1, 4),
            daily_bytes=_int(values, "POSTRIFF_VIDEO_DAILY_BYTES", 1_000_000_000, 1, 10**12),
            workspace_max_bytes=_int(values, "POSTRIFF_VIDEO_WORKSPACE_MAX_BYTES", 2_000_000_000, 1, 10**13),
        )

    def catalog(self, bucket_limit=None):
        limit = self.max_bytes if not bucket_limit else min(self.max_bytes, int(bucket_limit))
        return {"enabled": self.enabled and bool(bucket_limit), "mimes": list(MIMES), "maxBytes": limit, "maxSeconds": self.max_seconds, "frames": self.frames}


class UploadRows:
    """`pr_media_uploads` (migration 031). Every method runs on the caller's cursor."""

    COLUMNS = "replace(id::text, '-', ''), workspace_id::text, created_by::text, bucket, object_name, mime, declared_bytes, status, extract(epoch from token_expires_at)::float8, delete_attempts"
    KEYS = ("id", "workspaceId", "createdBy", "bucket", "objectName", "mime", "declaredBytes", "status", "tokenExpiresAt", "deleteAttempts")

    def _dict(self, row):
        return dict(zip(self.KEYS, row)) if row else None

    def pending_counts(self, cur, workspace_id, member):
        cur.execute("SELECT count(*) FILTER (WHERE created_by=%s), count(*) FROM public.pr_media_uploads WHERE workspace_id=%s AND status='pending'", (member, workspace_id))
        mine, total = cur.fetchone()
        return int(mine), int(total)

    def bytes_since(self, cur, workspace_id, seconds):
        cur.execute("SELECT coalesce(sum(declared_bytes),0) FROM public.pr_media_uploads WHERE workspace_id=%s AND status IN ('pending','committed') AND created_at > now() - make_interval(secs => %s)",
                    (workspace_id, seconds))
        return int(cur.fetchone()[0])

    def pending_bytes(self, cur, workspace_id):
        cur.execute("SELECT coalesce(sum(declared_bytes),0) FROM public.pr_media_uploads WHERE workspace_id=%s AND status='pending'", (workspace_id,))
        return int(cur.fetchone()[0])

    def insert(self, cur, row):
        cur.execute("INSERT INTO public.pr_media_uploads(id, workspace_id, created_by, bucket, object_name, mime, declared_bytes, status, token_expires_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'pending', now() + make_interval(secs => %s)) RETURNING extract(epoch from token_expires_at)::float8",
                    (row["id"], row["workspaceId"], row["createdBy"], row["bucket"], row["objectName"], row["mime"], row["declaredBytes"], TOKEN_SECONDS))
        return float(cur.fetchone()[0])

    def get(self, cur, workspace_id, upload_id, lock=True):
        cur.execute(f"SELECT {self.COLUMNS} FROM public.pr_media_uploads WHERE workspace_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""), (workspace_id, upload_id))
        return self._dict(cur.fetchone())

    def set_status(self, cur, workspace_id, upload_id, status, error=None):
        cur.execute("UPDATE public.pr_media_uploads SET status=%s, last_error=%s, updated_at=now() WHERE workspace_id=%s AND id=%s", (status, (error or None) and str(error)[:300], workspace_id, upload_id))

    def due(self, cur, limit):
        cur.execute(f"SELECT {self.COLUMNS} FROM public.pr_media_uploads WHERE (status IN ('pending','aborted') AND token_expires_at + make_interval(secs => %s) < now()) "
                    "OR status='deleting' ORDER BY token_expires_at LIMIT %s FOR UPDATE SKIP LOCKED", (SWEEP_MARGIN, limit))
        return [self._dict(row) for row in cur.fetchall()]

    def failed_delete(self, cur, upload_id, error):
        cur.execute("UPDATE public.pr_media_uploads SET delete_attempts=delete_attempts+1, last_error=%s, updated_at=now() WHERE id=%s", (str(error)[:300], upload_id))

    def remove(self, cur, upload_id):
        cur.execute("DELETE FROM public.pr_media_uploads WHERE id=%s", (upload_id,))

    def all_for(self, cur, workspace_id):
        cur.execute(f"SELECT {self.COLUMNS} FROM public.pr_media_uploads WHERE workspace_id=%s", (workspace_id,))
        return [self._dict(row) for row in cur.fetchall()]

    def remove_workspace(self, cur, workspace_id):
        cur.execute("DELETE FROM public.pr_media_uploads WHERE workspace_id=%s", (workspace_id,))


def _member(row):
    from .permissions import Membership
    return Membership.from_row(*row[2:7])


def _state(row):
    import json
    return row[1] if isinstance(row[1], dict) else json.loads(row[1])


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class VideoUploads:
    """`service` is the HostedWorkspaceService: repository, assets (PrivateAssetService), commands, audit."""

    def __init__(self, service, policy=None, *, storage=None, rows=None, clock=None, audit=None):
        self.service = service
        self.policy = policy or VideoPolicy()
        self._storage = storage
        self.rows = rows or UploadRows()
        self.clock = clock or time.time
        self.audit = audit
        self._preflight = None

    @property
    def storage(self):
        """The explicit storage, else the service's private storage at call time (None when media isn't configured)."""
        return self._storage or getattr(getattr(self.service, "assets", None), "storage", None)

    # --- preflight ------------------------------------------------------------------------------------------------
    def bucket_limit(self):
        """The bucket's size limit when it is ready for video, else None (cached for five minutes)."""
        now = self.clock()
        if self._preflight and now - self._preflight[0] < PREFLIGHT_TTL:
            return self._preflight[1]
        limit = None
        try:
            info = self.storage.bucket_info(self.policy.bucket) if self.storage else None
        except AlphaError:
            info = None
        if info and not info["public"] and isinstance(info.get("fileSizeLimit"), int) and 0 < info["fileSizeLimit"] <= self.policy.max_bytes \
                and set(MIMES) <= set(info.get("allowedMimeTypes") or []):
            limit = info["fileSizeLimit"]
        self._preflight = (now, limit)
        return limit

    def catalog(self):
        return self.policy.catalog(self.bucket_limit() if self.policy.enabled else None)

    def _ready(self):
        if not self.policy.enabled or self.storage is None:
            raise AlphaError(MSG["off"], 503, code="video_uploads_off")
        limit = self.bucket_limit()
        if not limit:
            raise AlphaError(MSG["off"], 503, code="video_uploads_off")
        return limit

    @staticmethod
    def _session_only(token):
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError(MSG["sign_in"], 403)

    # --- begin ------------------------------------------------------------------------------------------------------
    def begin(self, workspace_id, token, body):
        from .permissions import require
        self._session_only(token)
        max_bytes = self._ready()
        if not isinstance(body, dict) or not set(body) <= {"mime", "bytes", "duration", "width", "height"}:
            raise AlphaError(MSG["format"], 400)
        mime = body.get("mime")
        if mime not in MIMES:
            raise AlphaError(MSG["format"], 400)
        size = body.get("bytes")
        if type(size) is not int or size <= 0:
            raise AlphaError(MSG["format"], 400)
        if size > max_bytes:
            raise AlphaError(too_large(max_bytes), 400)
        duration = _number(body.get("duration"))
        if duration is not None and duration > self.policy.max_seconds:
            raise AlphaError(too_long(self.policy.max_seconds), 400)
        upload_id = uuid.uuid4().hex
        object_name = f"{upload_id}.{MIMES[mime]}"
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "edit")
            state = _state(row)
            if (state.get("workspace") or {}).get("sample"):
                raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")
            if state.get("accountDeletion"):
                raise AlphaError("Account deletion is pending.", 409, code="account_deletion_pending")
            mine, total = self.rows.pending_counts(cur, workspace_id, principal)
            if mine >= PENDING_PER_MEMBER or total >= PENDING_PER_WORKSPACE:
                raise AlphaError(MSG["caps"], 429, code="video_pending_caps")
            if self.rows.bytes_since(cur, workspace_id, 24 * 3600) + size > self.policy.daily_bytes:
                raise AlphaError(MSG["caps"], 429, code="video_daily_bytes")
            stored = sum(int(a.get("bytes") or 0) for a in (state.get("phase2") or {}).get("assets", []) if asset_kinds.kind_of(a) == "video" and not a.get("deleted"))
            if stored + self.rows.pending_bytes(cur, workspace_id) + size > self.policy.workspace_max_bytes:
                raise AlphaError(MSG["caps"], 429, code="video_workspace_bytes")
            expires = self.rows.insert(cur, {"id": upload_id, "workspaceId": workspace_id, "createdBy": principal, "bucket": self.policy.bucket,
                                             "objectName": object_name, "mime": mime, "declaredBytes": size})
        try:
            url = self.storage.signed_upload_url(workspace_id, "video", object_name)
        except AlphaError:
            with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
                self.rows.set_status(cur, workspace_id, upload_id, "aborted", "could not mint the upload URL")
            raise AlphaError(MSG["off"], 503, code="video_uploads_off") from None
        return {"upload": {"assetId": upload_id, "method": "PUT", "uploadUrl": url, "headers": {"Content-Type": mime}, "expiresAt": expires, "maxBytes": max_bytes}}

    # --- commit -----------------------------------------------------------------------------------------------------
    def _reject(self, workspace_id, token, upload, message):
        """Bad content: the object goes, the row is aborted, the person gets the reason (400)."""
        try:
            self.storage.delete(workspace_id, "video", upload["objectName"])
        except AlphaError:
            pass   # the sweep retries the delete for aborted rows
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            self.rows.set_status(cur, workspace_id, upload["id"], "aborted", message)
        raise AlphaError(message, 400, code="video_rejected")

    def _inspect(self, workspace_id, upload, max_bytes):
        """(evidence, rejection message or None). Raises 503 when storage can't be read (the row stays pending)."""
        name = upload["objectName"]
        try:
            info = self.storage.object_info(workspace_id, "video", name)
        except AlphaError as error:
            raise AlphaError(MSG["storage"], 503, code="video_storage") from error
        if info["bytes"] is None or info["bytes"] != upload["declaredBytes"]:
            return None, MSG["format"] if (info["bytes"] or 0) <= max_bytes else too_large(max_bytes)
        if info["bytes"] > max_bytes:
            return None, too_large(max_bytes)
        if info["mime"] not in MIMES or not info["etag"]:
            return None, MSG["format"]
        try:
            head = self.storage.read_range(workspace_id, "video", name, 0, HEAD_BYTES)
            if not mp4_boxes.brand(head["data"][:64]):
                return None, MSG["format"]
            ranged = head["ranged"]
            parsed, moov_read = {"duration": None, "width": None, "height": None, "location_present": False}, False
            if ranged:
                def read_at(offset, length):
                    part = self.storage.read_range(workspace_id, "video", name, offset, length)
                    if not part["ranged"]:
                        raise mp4_boxes.BoxError("storage ignored Range")
                    return part["data"]
                try:
                    walked = mp4_boxes.walk(read_at, info["bytes"])
                except mp4_boxes.BoxError:
                    return None, MSG["format"]
                if walked["moov"] and walked["moov"][1] <= mp4_boxes.MOOV_MAX:
                    offset, size = walked["moov"]
                    parsed = mp4_boxes.parse_moov(read_at(offset, size))
                    moov_read = True
        except AlphaError as error:
            raise AlphaError(MSG["storage"], 503, code="video_storage") from error
        if parsed["location_present"]:
            return None, MSG["location"]
        if moov_read and parsed["duration"] is not None and parsed["duration"] > self.policy.max_seconds:
            return None, too_long(self.policy.max_seconds)
        evidence = {"bytes": info["bytes"], "mime": info["mime"], "etag": info["etag"],
                    "duration": parsed["duration"] if moov_read else None, "durationSource": "container" if moov_read and parsed["duration"] is not None else "client",
                    "width": parsed["width"], "height": parsed["height"], "locationChecked": moov_read}
        return evidence, None

    def _frames(self, workspace_id, frames):
        staged = []
        for frame in frames[: self.policy.frames]:
            try:
                asset = self.service.assets.stage_upload(workspace_id, {"data": frame["data"]})
            except (AlphaError, ValueError):
                continue   # a frame that won't decode is skipped; zero frames is allowed
            staged.append({"objectName": asset["objectName"], "hash": asset["hash"], "width": asset.get("width"), "height": asset.get("height"),
                           "bytes": asset.get("bytes"), "at": float(frame["at"])})
        return staged

    def commit(self, workspace_id, token, upload_id, body):
        from .permissions import require
        self._session_only(token)
        max_bytes = self._ready()
        if not isinstance(upload_id, str) or not ASSET_ID.match(upload_id):
            raise AlphaError(MSG["not_pending"], 404)
        if not isinstance(body, dict) or not set(body) <= {"frames", "locationCleared"} or not isinstance(body.get("frames", []), list) or len(body.get("frames", [])) > 4:
            raise AlphaError("Invalid video commit.", 400)
        frames = []
        for frame in body.get("frames", []):
            if not isinstance(frame, dict) or set(frame) != {"at", "data"} or _number(frame.get("at")) is None or not isinstance(frame.get("data"), str):
                raise AlphaError("Invalid video commit.", 400)
            try:
                base64.b64decode(frame["data"], validate=True)
            except ValueError:
                raise AlphaError("Invalid video commit.", 400) from None
            frames.append(frame)
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "edit")
            upload = self.rows.get(cur, workspace_id, upload_id)
            state = _state(row)
        existing = next((a for a in (state.get("phase2") or {}).get("assets", []) if a.get("id") == upload_id), None)
        if upload and upload["status"] == "committed" and existing and existing.get("objectName") == upload["objectName"]:
            return {"revision": row[0], "video": self._view(existing)}   # idempotent: the same object was already added
        if not upload or upload["status"] != "pending":
            raise AlphaError(MSG["not_pending"], 409, code="video_not_pending")
        evidence, rejection = self._inspect(workspace_id, upload, max_bytes)
        if rejection:
            self._reject(workspace_id, token, upload, rejection)
        staged = self._frames(workspace_id, frames)
        name = upload["objectName"]
        asset = {"id": upload_id, "kind": "video", "mime": upload["mime"], "category": "video", "bucket": upload["bucket"], "objectName": name,
                 "storagePath": f"{workspace_id}/video/{name}", "bytes": evidence["bytes"], "duration": evidence["duration"], "durationSource": evidence["durationSource"],
                 "width": evidence["width"], "height": evidence["height"], "etag": evidence["etag"],
                 "hash": hashlib.sha256(f"video:{name}:{evidence['bytes']}:{evidence['etag']}".encode()).hexdigest(),
                 **({"poster": {k: staged[0][k] for k in ("objectName", "hash", "width", "height", "bytes")}} if staged else {}),
                 "frames": staged, "verified": {"container": True, "locationChecked": evidence["locationChecked"], "locationCleared": bool(body.get("locationCleared"))},
                 "processing": "ready", "uploadedBy": upload["createdBy"], "execution": "hosted-private-storage", "deleted": False}

        def mark_committed(cur, _state, _principal):
            self.rows.set_status(cur, workspace_id, upload_id, "committed")

        def add(revision):
            return self.service.repository.command(workspace_id, token, revision, lambda s, actor: self.service.commands.add_asset(s, actor, asset), after=mark_committed)

        try:
            try:
                saved = add(row[0])
            except AlphaError as error:
                if error.code != "workspace_revision_conflict":
                    raise
                saved = add(self.service.repository.get(workspace_id, token)["revision"])   # it only adds one asset: retry once
        except Exception:
            for frame in staged:
                try:
                    self.storage.delete(workspace_id, "media", frame["objectName"])
                except AlphaError:
                    pass
            raise
        presented = self.service._present(saved) if hasattr(self.service, "_present") else {"revision": saved["revision"]}
        return {**presented, "revision": saved["revision"], "video": self._view(asset)}

    @staticmethod
    def _view(asset):
        return {"assetId": asset["id"], "bytes": asset.get("bytes"), "duration": asset.get("duration"), "durationSource": asset.get("durationSource"),
                "width": asset.get("width"), "height": asset.get("height"), "frames": len(asset.get("frames") or []),
                "verified": {k: (asset.get("verified") or {}).get(k) for k in ("container", "locationChecked")}}

    # --- abort, url -------------------------------------------------------------------------------------------------
    def abort(self, workspace_id, token, upload_id):
        from .permissions import require
        self._session_only(token)
        if not isinstance(upload_id, str) or not ASSET_ID.match(upload_id):
            raise AlphaError(MSG["not_pending"], 404)
        with self.service.repository.transaction(token, workspace_id) as (cur, row, _principal):
            require(_member(row), "edit")
            upload = self.rows.get(cur, workspace_id, upload_id)
            if upload is None:
                raise AlphaError(MSG["not_pending"], 404)
            if upload["status"] == "committed":
                raise AlphaError(MSG["ready"], 409, code="video_ready")
            if upload["status"] != "pending":
                return {"assetId": upload_id, "status": upload["status"]}
            try:
                self.storage.delete(workspace_id, "video", upload["objectName"])   # 404 counts as success
            except AlphaError:
                pass   # kept `aborted`: the sweep retries the delete after expiry + 24 h
            self.rows.set_status(cur, workspace_id, upload_id, "aborted")
        return {"assetId": upload_id, "status": "aborted"}

    def url(self, workspace_id, token, asset_id):
        """A 600 s signed playback URL for a ready video (`read`), audited as `media.url_signed`."""
        from .permissions import require
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "read")
            state = _state(row)
            asset = next((a for a in (state.get("phase2") or {}).get("assets", []) if a.get("id") == asset_id and not a.get("deleted")), None)
            if asset is None:
                raise AlphaError("This private media object is unavailable.", 404)
            if asset_kinds.kind_of(asset) != "video" or not asset.get("objectName"):
                raise AlphaError(MSG["not_video"], 404)
            signed = self.storage.signed_url(workspace_id, "video", asset["objectName"], 600)
            if self.audit:
                self.audit(cur, workspace_id, principal, "media.url_signed", asset_id, {"seconds": 600})
        return {"url": signed, "expiresAt": self.clock() + 600, "mime": asset.get("mime")}

    # --- sweep, purge -----------------------------------------------------------------------------------------------
    def sweep(self, connect, max_rows=50):
        """Two phases for uploads nobody finished (expiry + 24 h): mark `deleting`, delete the object, drop the row.
        A failed delete keeps the row and counts the attempt; the next tick retries."""
        with connect() as db, db.cursor() as cur:
            due = self.rows.due(cur, max_rows)
            for upload in due:
                self.rows.set_status(cur, upload["workspaceId"], upload["id"], "deleting")
        removed, failed = 0, 0
        for upload in due:
            try:
                self.storage.delete(upload["workspaceId"], "video", upload["objectName"])
            except AlphaError as error:
                with connect() as db, db.cursor() as cur:
                    self.rows.failed_delete(cur, upload["id"], error)
                failed += 1
                continue
            with connect() as db, db.cursor() as cur:
                self.rows.remove(cur, upload["id"])
            removed += 1
        return {"removed": removed, "failed": failed}

    def purge_workspace(self, cur, workspace_id):
        """Account deletion: every upload row's object, then whatever remains under the workspace's video prefix."""
        for upload in self.rows.all_for(cur, workspace_id):
            self.storage.delete(workspace_id, "video", upload["objectName"])
        for path in self.storage.list_prefix(f"{workspace_id}/video", bucket=self.policy.bucket):
            self.storage.delete(workspace_id, "video", path.rsplit("/", 1)[-1])
        self.rows.remove_workspace(cur, workspace_id)
