"""video_uploads with fake storage, rows and repository: policy and caps, begin, commit (HEAD, brand, moov, location,
length, frames, one command with one retry, idempotency, fail closed), abort, playback URL, sweep and purge
(chat-context SPEC §5.7, §7.2–7.4). The SQL runs in tests/phase2/postgres_video.py."""
import base64
import copy
import io
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import video_uploads as vu  # noqa: E402
from test_mp4_boxes import box, ftyp, moov, mvhd, qt_string, trak  # noqa: E402

WS = "5b2e7c1a-0000-4000-8000-000000000001"
ME = "00000000-0000-0000-0000-00000000000a"


def mp4(seconds=42, location=False, moov_last=False):
    tags = box(b"udta", qt_string(b"\xa9xyz", b"+22.27+114.17/")) if location else b""
    head = moov(mvhd(1000, int(seconds * 1000)), trak(1080, 1920), tags)
    media = box(b"mdat", b"\x00" * 256)
    return ftyp() + (media + head if moov_last else head + media)


def jpeg_b64():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (1024, 576), (10, 20, 30)).save(out, "JPEG")
    return base64.b64encode(out.getvalue()).decode()


class FakeRows:
    def __init__(self):
        self.items, self.clock = {}, [1000.0]

    def pending_counts(self, cur, ws, member):
        pending = [r for r in self.items.values() if r["workspaceId"] == ws and r["status"] == "pending"]
        return sum(1 for r in pending if r["createdBy"] == member), len(pending)

    def bytes_since(self, cur, ws, seconds):
        return sum(r["declaredBytes"] for r in self.items.values() if r["workspaceId"] == ws and r["status"] in ("pending", "committed"))

    def pending_bytes(self, cur, ws):
        return sum(r["declaredBytes"] for r in self.items.values() if r["workspaceId"] == ws and r["status"] == "pending")

    def insert(self, cur, row):
        self.items[row["id"]] = {**row, "status": "pending", "tokenExpiresAt": self.clock[0] + vu.TOKEN_SECONDS, "deleteAttempts": 0}
        return self.items[row["id"]]["tokenExpiresAt"]

    def get(self, cur, ws, upload_id, lock=True):
        row = self.items.get(upload_id)
        return dict(row) if row and row["workspaceId"] == ws else None

    def renew(self, cur, ws, upload_id):
        row = self.items[upload_id]
        if row.get('originalExpiry', row['tokenExpiresAt']) + 22 * 3600 <= self.clock[0]:
            raise AlphaError('Expired pending upload.', 409, code='video_resume_expired')
        row.setdefault('originalExpiry', row['tokenExpiresAt'])
        row['tokenExpiresAt'] = self.clock[0] + vu.TOKEN_SECONDS
        return row['tokenExpiresAt']

    def set_status(self, cur, ws, upload_id, status, error=None):
        self.items[upload_id]["status"] = status

    def due(self, cur, limit):
        return [dict(r) for r in self.items.values() if (r["status"] in ("pending", "aborted") and r["tokenExpiresAt"] + vu.SWEEP_MARGIN < self.clock[0]) or r["status"] == "deleting"][:limit]

    def failed_delete(self, cur, upload_id, error):
        self.items[upload_id]["deleteAttempts"] += 1

    def remove(self, cur, upload_id):
        self.items.pop(upload_id, None)

    def all_for(self, cur, ws):
        return [dict(r) for r in self.items.values() if r["workspaceId"] == ws]

    def remove_workspace(self, cur, ws):
        self.items = {k: v for k, v in self.items.items() if v["workspaceId"] != ws}


class FakeStorage:
    def __init__(self, bucket_limit=100_000_000):
        self.objects, self.deleted, self.calls = {}, [], []
        self.bucket = {"id": "postriff-video", "public": False, "fileSizeLimit": bucket_limit, "allowedMimeTypes": ["video/mp4", "video/quicktime"]}
        self.ranged, self.down, self.fail_delete = True, False, False

    def bucket_info(self, bucket=None):
        self.calls.append("bucket_info")
        return self.bucket

    def signed_upload_url(self, ws, category, name):
        return f"https://abcd.supabase.co/storage/v1/object/upload/sign/postriff-video/{ws}/video/{name}?token=t"

    def signed_resumable_upload(self, ws, name, mime):
        self.calls.append(('signed_resumable', ws, name, mime))
        return {'protocol': 'tus', 'endpoint': 'https://abcd.storage.supabase.co/storage/v1/upload/resumable',
                'headers': {'x-signature': 'one-object-only'}, 'chunkBytes': 6 * 1024 * 1024,
                'metadata': {'bucketName': 'postriff-video', 'objectName': f'{ws}/video/{name}', 'contentType': mime, 'cacheControl': '3600'}}

    def put(self, name, data, mime="video/mp4", etag='"e1"'):
        self.objects[name] = (data, mime, etag)

    def object_info(self, ws, category, name):
        if self.down:
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        if name not in self.objects:
            raise AlphaError("This private media object is unavailable.", 404)
        data, mime, etag = self.objects[name]
        return {"bytes": len(data), "mime": mime, "etag": etag}

    def read_range(self, ws, category, name, start, length):
        self.calls.append(("range", start, length))
        data = self.objects[name][0]
        if not self.ranged:
            return {"data": data[:length] if start == 0 else b"", "ranged": False}
        return {"data": data[start:start + length], "ranged": True}

    def delete(self, ws, category, name):
        if self.fail_delete:
            raise AlphaError("Private storage could not delete this object.", 502)
        self.deleted.append((category, name))
        self.objects.pop(name, None)

    def list_prefix(self, prefix, bucket=None):
        return [f"{prefix}/{name}" for name in self.objects]

    def signed_url(self, ws, category, name, expires_in=300):
        return f"https://abcd.supabase.co/storage/v1/object/sign/postriff-video/{ws}/video/{name}?token=s&e={expires_in}"


class FakeAssets:
    def __init__(self, storage):
        self.storage, self.staged = storage, []

    def stage_upload(self, ws, payload):
        raw = base64.b64decode(payload["data"], validate=True)
        if not raw.startswith(b"\xff\xd8"):
            raise AlphaError("Use a JPEG or PNG image.")
        name = f"{len(self.staged):032x}-" + "b" * 64 + ".jpg"
        self.staged.append(name)
        return {"objectName": name, "hash": f"h{len(self.staged)}", "width": 1024, "height": 576, "bytes": len(raw)}


class FakeCommands:
    @staticmethod
    def add_asset(state, principal, asset):
        if any(item["id"] == asset["id"] for item in state["phase2"]["assets"]):
            raise AlphaError("This asset already exists.", 409)
        state["phase2"]["assets"].append(copy.deepcopy(asset))
        return state


class FakeRepository:
    def __init__(self, role="editor"):
        self.revision, self.state, self.role = 5, {"phase2": {"assets": []}, "workspace": {}}, role
        self.conflicts = 0
        self.after_calls = 0

    def row(self):
        return (self.revision, copy.deepcopy(self.state), self.role, False, False, False, False)

    @contextmanager
    def transaction(self, token, ws):
        if token != "session":
            raise AlphaError("Verified session required.", 401)
        yield None, self.row(), ME

    def get(self, ws, token):
        return {"revision": self.revision, "state": copy.deepcopy(self.state)}

    def command(self, ws, token, revision, fn, after=None):
        if self.conflicts:
            self.conflicts -= 1
            self.revision += 1
            raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
        if revision != self.revision:
            raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
        self.state = fn(copy.deepcopy(self.state), ME)
        self.revision += 1
        if after:
            after(None, self.state, ME)
            self.after_calls += 1
        return {"revision": self.revision, "state": self.state}


class FakeService:
    def __init__(self, role="editor", bucket_limit=100_000_000):
        self.repository = FakeRepository(role)
        self.storage = FakeStorage(bucket_limit)
        self.assets = FakeAssets(self.storage)
        self.commands = FakeCommands()


def make(role="editor", policy=None, bucket_limit=100_000_000):
    service = FakeService(role, bucket_limit)
    rows = FakeRows()
    audits = []
    uploads = vu.VideoUploads(service, policy or vu.VideoPolicy(enabled=True), rows=rows, clock=lambda: rows.clock[0],
                              audit=lambda cur, ws, who, kind, subject, meta: audits.append((kind, subject, meta)))
    return service, rows, uploads, audits


def begin(uploads, **body):
    return uploads.begin(WS, "session", {"mime": "video/mp4", "bytes": len(mp4()), "duration": 42.0, "width": 1080, "height": 1920, **body})


class PolicyTests(unittest.TestCase):
    def test_defaults_and_locked_caps(self):
        policy = vu.VideoPolicy.from_environment({})
        self.assertEqual((policy.enabled, policy.max_bytes, policy.max_seconds, policy.frames, policy.daily_bytes, policy.workspace_max_bytes),
                         (False, 100_000_000, 180, 4, 1_000_000_000, 2_000_000_000))
        loose = vu.VideoPolicy.from_environment({"RAFII_VIDEO_UPLOADS_ENABLED": "1", "POSTRIFF_VIDEO_MAX_BYTES": "300000000", "POSTRIFF_VIDEO_MAX_SECONDS": "300", "POSTRIFF_VIDEO_FRAMES": "0"})
        self.assertEqual((loose.enabled, loose.max_bytes, loose.max_seconds, loose.frames), (True, 100_000_000, 180, 1), "Phase 1 caps can't be raised by config")
        free = vu.VideoPolicy.from_environment({"POSTRIFF_VIDEO_MAX_BYTES": "50000000"})
        self.assertEqual(free.max_bytes, 50_000_000)

    def test_catalog_takes_the_smaller_limit(self):
        self.assertEqual(vu.VideoPolicy(enabled=True).catalog(50_000_000)["maxBytes"], 50_000_000)
        self.assertFalse(vu.VideoPolicy(enabled=True).catalog(None)["enabled"])
        _, _, uploads, _ = make(bucket_limit=50_000_000)
        self.assertEqual(uploads.catalog(), {"enabled": True, "mimes": ["video/mp4", "video/quicktime"], "maxBytes": 50_000_000, "maxSeconds": 180, "frames": 4})


class BeginTests(unittest.TestCase):
    def test_resumable_ticket_keeps_original_intent_and_service_key_out_of_browser(self):
        service, rows, uploads, _ = make()
        ticket = begin(uploads, transport='tus')['upload']
        self.assertEqual(ticket['method'], 'TUS')
        self.assertEqual(ticket['resumable']['headers'], {'x-signature': 'one-object-only'})
        self.assertEqual(ticket['resumable']['metadata']['objectName'], f"{WS}/video/{ticket['assetId']}.mp4")
        self.assertNotIn('one-object-only', str(rows.items))
        self.assertEqual(service.repository.revision, 5)

    def test_ticket_and_no_state_change(self):
        service, rows, uploads, _ = make()
        ticket = begin(uploads)["upload"]
        self.assertRegex(ticket["assetId"], r"^[0-9a-f]{32}$")
        self.assertEqual((ticket["method"], ticket["headers"], ticket["maxBytes"]), ("PUT", {"Content-Type": "video/mp4"}, 100_000_000))
        self.assertIn(f"/{WS}/video/{ticket['assetId']}.mp4?token=", ticket["uploadUrl"])
        self.assertEqual(rows.items[ticket["assetId"]]["status"], "pending")
        self.assertNotIn("token=", str(rows.items[ticket["assetId"]]), "the signed URL's token is never stored")
        self.assertNotIn(ticket["uploadUrl"], str(rows.items[ticket["assetId"]]))
        self.assertEqual(service.repository.revision, 5, "begin writes no workspace state")

    def test_off_or_bucket_not_ready(self):
        for policy, bucket in ((vu.VideoPolicy(enabled=False), None), (vu.VideoPolicy(enabled=True), {"public": True}), (vu.VideoPolicy(enabled=True), {"fileSizeLimit": 200_000_000}),
                               (vu.VideoPolicy(enabled=True), {"allowedMimeTypes": ["video/mp4"]})):
            service, _, uploads, _ = make(policy=policy)
            if bucket:
                service.storage.bucket.update(bucket)
            with self.subTest(policy=policy.enabled, bucket=bucket), self.assertRaises(AlphaError) as refused:
                begin(uploads)
            self.assertEqual((refused.exception.status, str(refused.exception)), (503, "Video uploads aren't available yet."))

    def test_declared_size_and_length(self):
        _, _, uploads, _ = make(bucket_limit=50_000_000)
        with self.assertRaises(AlphaError) as big:
            begin(uploads, bytes=50_000_001)
        self.assertEqual(str(big.exception), "This video is over 50 MB.")
        with self.assertRaises(AlphaError) as long:
            begin(uploads, duration=181.0)
        self.assertEqual(str(long.exception), "This video is longer than 3 minutes.")
        for body in ({"mime": "video/webm"}, {"bytes": 0}, {"bytes": "10"}, {"extra": 1}):
            with self.subTest(body=body), self.assertRaises(AlphaError):
                begin(uploads, **body)
        self.assertIn("upload", begin(uploads, duration=None))

    def test_role_sample_deletion_and_api_tokens(self):
        _, _, viewer, _ = make(role="viewer")
        with self.assertRaises(AlphaError) as refused:
            begin(viewer)
        self.assertEqual(refused.exception.status, 403)
        service, _, uploads, _ = make()
        service.repository.state["workspace"]["sample"] = True
        with self.assertRaises(AlphaError):
            begin(uploads)
        service.repository.state["workspace"]["sample"] = False
        service.repository.state["accountDeletion"] = {"requestedAt": 1}
        with self.assertRaises(AlphaError) as deleting:
            begin(uploads)
        self.assertEqual(deleting.exception.code, "account_deletion_pending")
        with self.assertRaises(AlphaError) as token:
            uploads.begin(WS, "prt_token", {"mime": "video/mp4", "bytes": 10})
        self.assertEqual((token.exception.status, str(token.exception)), (403, "Sign in to upload videos."))

    def test_pending_caps(self):
        _, rows, uploads, _ = make()
        for _ in range(3):
            begin(uploads)
        with self.assertRaises(AlphaError) as capped:
            begin(uploads)
        self.assertEqual((capped.exception.status, str(capped.exception)), (429, "Finish or remove your other video uploads first."))
        for n in range(3):
            rows.insert(None, {"id": f"other{n}", "workspaceId": WS, "createdBy": "someone-else", "bucket": "b", "objectName": "x", "mime": "video/mp4", "declaredBytes": 1})
        self.assertEqual(rows.pending_counts(None, WS, ME), (3, 6))

    def test_daily_and_workspace_bytes(self):
        _, _, uploads, _ = make(policy=vu.VideoPolicy(enabled=True, daily_bytes=1000))
        with self.assertRaises(AlphaError) as daily:
            begin(uploads, bytes=1001)
        self.assertEqual(daily.exception.code, "video_daily_bytes")
        service, _, stored, _ = make(policy=vu.VideoPolicy(enabled=True, workspace_max_bytes=1000))
        service.repository.state["phase2"]["assets"].append({"id": "v", "mime": "video/mp4", "bytes": 900, "deleted": False})
        with self.assertRaises(AlphaError) as full:
            begin(stored, bytes=200)
        self.assertEqual(full.exception.code, "video_workspace_bytes")


class CommitTests(unittest.TestCase):
    def uploaded(self, data=None, mime="video/mp4", **policy):
        service, rows, uploads, audits = make(policy=vu.VideoPolicy(enabled=True, **policy))
        data = data if data is not None else mp4()
        ticket = uploads.begin(WS, "session", {"mime": mime, "bytes": len(data), "duration": 42.0})["upload"]
        service.storage.put(rows.items[ticket["assetId"]]["objectName"], data, mime=mime)
        return service, rows, uploads, ticket["assetId"], audits

    def test_happy_path_adds_one_verified_asset(self):
        service, rows, uploads, upload_id, _ = self.uploaded()
        frames = [{"at": 4.2, "data": jpeg_b64()}, {"at": 14.7, "data": jpeg_b64()}]
        result = uploads.commit(WS, "session", upload_id, {"frames": frames, "locationCleared": True})
        asset = service.repository.state["phase2"]["assets"][0]
        self.assertEqual(result["video"], {"assetId": upload_id, "bytes": len(mp4()), "duration": 42.0, "durationSource": "container", "width": 1080, "height": 1920,
                                           "frames": 2, "verified": {"container": True, "locationChecked": True}})
        self.assertEqual((asset["kind"], asset["category"], asset["processing"], asset["mime"]), ("video", "video", "ready", "video/mp4"))
        self.assertEqual(asset["poster"]["objectName"], asset["frames"][0]["objectName"])
        self.assertEqual([f["at"] for f in asset["frames"]], [4.2, 14.7])
        self.assertEqual(rows.items[upload_id]["status"], "committed")
        self.assertEqual(service.repository.after_calls, 1, "the row is committed in the same command")
        self.assertEqual(len(asset["hash"]), 64)

    def test_moov_after_mdat_and_mov(self):
        service, _, uploads, upload_id, _ = self.uploaded(mp4(moov_last=True), mime="video/quicktime")
        self.assertEqual(uploads.commit(WS, "session", upload_id, {"frames": []})["video"]["durationSource"], "container")

    def test_idempotent_second_commit(self):
        service, _, uploads, upload_id, _ = self.uploaded()
        first = uploads.commit(WS, "session", upload_id, {"frames": []})
        again = uploads.commit(WS, "session", upload_id, {"frames": []})
        self.assertEqual(again["video"], first["video"])
        self.assertEqual(len(service.repository.state["phase2"]["assets"]), 1)

    def test_rejections_delete_the_object(self):
        cases = [("location", mp4(location=True), "This video still has location data. Export it without location and try again."),
                 ("too long", mp4(seconds=200), "This video is longer than 3 minutes."),
                 ("bad brand", b"\x00\x00\x00\x0cftypheic" + b"\x00" * 100, "Use an MP4 or MOV video.")]
        for name, data, message in cases:
            service, rows, uploads, upload_id, _ = self.uploaded(data)
            with self.subTest(name), self.assertRaises(AlphaError) as refused:
                uploads.commit(WS, "session", upload_id, {"frames": []})
            self.assertEqual((refused.exception.status, str(refused.exception)), (400, message))
            self.assertIn(("video", rows.items[upload_id]["objectName"]), service.storage.deleted)
            self.assertEqual(rows.items[upload_id]["status"], "aborted")
            self.assertEqual(service.repository.state["phase2"]["assets"], [])

    def test_size_mismatch_or_missing_etag(self):
        service, rows, uploads, upload_id, _ = self.uploaded()
        name = rows.items[upload_id]["objectName"]
        service.storage.put(name, mp4() + b"extra")
        with self.assertRaises(AlphaError):
            uploads.commit(WS, "session", upload_id, {"frames": []})
        service, rows, uploads, upload_id, _ = self.uploaded()
        service.storage.put(rows.items[upload_id]["objectName"], mp4(), etag=None)
        with self.assertRaises(AlphaError):
            uploads.commit(WS, "session", upload_id, {"frames": []})

    def test_storage_down_fails_closed_and_stays_pending(self):
        service, rows, uploads, upload_id, _ = self.uploaded()
        service.storage.down = True
        with self.assertRaises(AlphaError) as refused:
            uploads.commit(WS, "session", upload_id, {"frames": []})
        self.assertEqual((refused.exception.status, str(refused.exception)), (503, "Couldn't check this video yet. Try again."))
        self.assertEqual(rows.items[upload_id]["status"], "pending")
        self.assertEqual(service.storage.deleted, [])

    def test_range_ignored_means_length_not_checked(self):
        service, _, uploads, upload_id, _ = self.uploaded()
        service.storage.ranged = False
        video = uploads.commit(WS, "session", upload_id, {"frames": []})["video"]
        self.assertEqual((video["duration"], video["durationSource"], video["verified"]["locationChecked"]), (None, "client", False))

    def test_bad_frames_are_skipped(self):
        service, _, uploads, upload_id, _ = self.uploaded()
        result = uploads.commit(WS, "session", upload_id, {"frames": [{"at": 1, "data": base64.b64encode(b"not a jpeg").decode()}, {"at": 2, "data": jpeg_b64()}]})
        self.assertEqual(result["video"]["frames"], 1)
        with self.assertRaises(AlphaError):
            uploads.commit(WS, "session", upload_id, {"frames": [{"at": 1, "data": "%%%"}]})

    def test_one_retry_on_a_revision_conflict(self):
        service, _, uploads, upload_id, _ = self.uploaded()
        service.repository.conflicts = 1
        self.assertEqual(uploads.commit(WS, "session", upload_id, {"frames": []})["video"]["assetId"], upload_id)
        service, _, uploads, upload_id, _ = self.uploaded()
        service.repository.conflicts = 2
        with self.assertRaises(AlphaError) as twice:
            uploads.commit(WS, "session", upload_id, {"frames": [{"at": 1, "data": jpeg_b64()}]})
        self.assertEqual(twice.exception.code, "workspace_revision_conflict")
        self.assertTrue(any(category == "media" for category, _ in service.storage.deleted), "staged frames are cleaned up")

    def test_not_pending(self):
        _, rows, uploads, upload_id, _ = self.uploaded()
        rows.items[upload_id]["status"] = "aborted"
        with self.assertRaises(AlphaError) as refused:
            uploads.commit(WS, "session", upload_id, {"frames": []})
        self.assertEqual((refused.exception.status, str(refused.exception)), (409, "This upload isn't waiting to be finished."))
        with self.assertRaises(AlphaError):
            uploads.commit(WS, "session", "f" * 32, {"frames": []})


class AbortUrlSweepTests(unittest.TestCase):
    def test_abort_pending_only(self):
        service, rows, uploads, _ = make()
        upload_id = begin(uploads)["upload"]["assetId"]
        self.assertEqual(uploads.abort(WS, "session", upload_id), {"assetId": upload_id, "status": "aborted"})
        self.assertEqual(rows.items[upload_id]["status"], "aborted", "the row stays until expiry + 24 h")
        rows.items[upload_id]["status"] = "committed"
        with self.assertRaises(AlphaError) as ready:
            uploads.abort(WS, "session", upload_id)
        self.assertEqual((ready.exception.status, str(ready.exception)), (409, "Remove ready videos from the Library."))

    def test_url_for_videos_only_and_audited(self):
        service, _, uploads, audits = make(role="viewer")
        service.repository.state["phase2"]["assets"] += [{"id": "v" * 32, "mime": "video/mp4", "objectName": "v" * 32 + ".mp4", "deleted": False},
                                                          {"id": "i" * 32, "mime": "image/jpeg", "objectName": "x.jpg", "deleted": False}]
        signed = uploads.url(WS, "session", "v" * 32)
        self.assertTrue(signed["url"].endswith("e=600"))
        self.assertEqual(signed["mime"], "video/mp4")
        self.assertEqual(audits, [("media.url_signed", "v" * 32, {"seconds": 600})])
        with self.assertRaises(AlphaError) as image:
            uploads.url(WS, "session", "i" * 32)
        self.assertEqual((image.exception.status, str(image.exception)), (404, "This isn't a video."))

    def test_sweep_waits_for_expiry_plus_a_day_and_retries(self):
        service, rows, uploads, _ = make()

        @contextmanager
        def connect():
            class DB:
                def cursor(self):
                    return self

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            yield DB()
        upload_id = begin(uploads)["upload"]["assetId"]
        self.assertEqual(uploads.sweep(connect), {"removed": 0, "failed": 0})
        rows.clock[0] += vu.TOKEN_SECONDS + vu.SWEEP_MARGIN + 1
        service.storage.fail_delete = True
        self.assertEqual(uploads.sweep(connect), {"removed": 0, "failed": 1})
        self.assertEqual((rows.items[upload_id]["status"], rows.items[upload_id]["deleteAttempts"]), ("deleting", 1))
        service.storage.fail_delete = False
        self.assertEqual(uploads.sweep(connect), {"removed": 1, "failed": 0})
        self.assertNotIn(upload_id, rows.items)

    def test_purge_workspace(self):
        service, rows, uploads, _ = make()
        upload_id = begin(uploads)["upload"]["assetId"]
        service.storage.put("stray" + "0" * 27 + ".mp4", b"x")
        uploads.purge_workspace(None, WS)
        self.assertIn(("video", rows.items.get(upload_id, {}).get("objectName") or f"{upload_id}.mp4"), service.storage.deleted)
        self.assertIn(("video", "stray" + "0" * 27 + ".mp4"), service.storage.deleted)
        self.assertEqual(rows.all_for(None, WS), [])




class ResumableGrantTests(unittest.TestCase):
    def test_resume_regrants_same_object_after_expired_signature(self):
        service, rows, uploads, audits = make()
        ticket = begin(uploads, transport='tus')['upload']; identifier = ticket['assetId']
        rows.clock[0] += vu.TOKEN_SECONDS + 10
        result = uploads.resume(WS, 'session', identifier, {'mime': 'video/mp4', 'bytes': len(mp4())})
        self.assertFalse(result['objectComplete'])
        self.assertEqual(result['upload']['assetId'], identifier)
        self.assertEqual(result['upload']['resumable']['metadata']['objectName'], f'{WS}/video/{identifier}.mp4')
        self.assertGreater(result['upload']['expiresAt'], ticket['expiresAt'])
        self.assertEqual(len(rows.items), 1)
        self.assertEqual(audits[-1][0], 'media.video_upload_resumed')

    def test_accepted_final_chunk_is_reconciled_without_another_signed_upload(self):
        service, rows, uploads, _ = make()
        ticket = begin(uploads, transport='tus')['upload']; identifier = ticket['assetId']
        service.storage.put(identifier + '.mp4', mp4())
        before = len([x for x in service.storage.calls if isinstance(x, tuple) and x[0] == 'signed_resumable'])
        result = uploads.resume(WS, 'session', identifier, {'mime': 'video/mp4', 'bytes': len(mp4())})
        self.assertEqual(result, {'assetId': identifier, 'objectComplete': True})
        self.assertEqual(len([x for x in service.storage.calls if isinstance(x, tuple) and x[0] == 'signed_resumable']), before)

    def test_foreign_creator_tenant_changed_file_or_committed_intent_cannot_regrant(self):
        for condition in ('creator', 'tenant', 'bytes', 'mime', 'committed', 'expired'):
            with self.subTest(condition=condition):
                service, rows, uploads, _ = make()
                identifier = begin(uploads, transport='tus')['upload']['assetId']
                target = rows.items[identifier]; payload = {'mime': 'video/mp4', 'bytes': len(mp4())}; workspace = WS
                if condition == 'creator': target['createdBy'] = 'foreign-user'
                if condition == 'tenant': workspace = '5b2e7c1a-0000-4000-8000-000000000099'
                if condition == 'bytes': payload['bytes'] += 1
                if condition == 'mime': payload['mime'] = 'video/quicktime'
                if condition == 'committed': target['status'] = 'committed'
                if condition == 'expired': rows.clock[0] += 25 * 3600
                with self.assertRaises(AlphaError): uploads.resume(workspace, 'session', identifier, payload)
                self.assertEqual(len(rows.items), 1)

    def test_storage_uncertainty_never_restarts_or_replaces_the_object(self):
        service, rows, uploads, _ = make()
        identifier = begin(uploads, transport='tus')['upload']['assetId']
        service.storage.down = True
        with self.assertRaises(AlphaError): uploads.resume(WS, 'session', identifier, {'mime': 'video/mp4', 'bytes': len(mp4())})
        self.assertEqual(rows.items[identifier]['status'], 'pending')
        self.assertEqual(len(service.storage.deleted), 0)


if __name__ == "__main__":
    unittest.main()
