"""hosted_storage for chat videos: no-redirect opener, video category, signed upload URL, HEAD, bounded range reads,
bucket info, paginated listing and kind-aware removal (chat-context SPEC §7.3, §7.4). Fakes only; no network."""
import email.message
import io
import json
import sys
import unittest
from pathlib import Path
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService, SupabaseStorage, _NoRedirect  # noqa: E402

PROJECT = "https://abcd1234.supabase.co"
KEY = "sb_secret_" + "x" * 30
WS = "5b2e7c1a-0000-4000-8000-000000000001"
VID = "0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10"
IMG = "9ab1c2d3e4f5061728394a5b6c7d8e9f-" + "a" * 64 + ".jpg"
FRAME = "9ab1c2d3e4f5061728394a5b6c7d8e9f-" + "b" * 64 + ".jpg"


class CountingBody(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.requested = []

    def read(self, size=-1):
        self.requested.append(size)
        return super().read(size)


class FakeHTTPS(BaseHandler):
    """Answers every https request with a scripted (status, headers, body) and records what was asked."""
    handler_order = 100   # ahead of the default HTTPSHandler: these tests never touch the network

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.bodies = []

    def https_open(self, req):
        self.requests.append((req.get_method(), req.full_url, dict(req.header_items())))
        status, headers, body = self.script.pop(0)
        message = email.message.Message()
        for k, v in headers.items():
            message[k] = v
        stream = CountingBody(body)
        self.bodies.append(stream)
        response = addinfourl(stream, message, req.full_url, code=status)
        response.msg = "scripted"
        return response


def storage_with(script):
    handler = FakeHTTPS(script)
    return SupabaseStorage(PROJECT, KEY, opener=build_opener(_NoRedirect(), handler)), handler


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


class ApprovedVideoStreamTests(unittest.TestCase):
    def test_tiktok_one_hour_download_window_does_not_extend_library_urls(self):
        recorder=Recorder((200,{},json.dumps({'signedURL':f'/object/sign/postriff-private/{WS}/media/{IMG}?token=approved'}).encode()))
        store=SupabaseStorage(PROJECT,KEY);store.send=recorder
        with self.assertRaises(AlphaError): store.signed_url(WS,'media',IMG,4200)
        address=store.tiktok_transfer_url(WS,'media',IMG)
        self.assertIn('token=approved',address);self.assertEqual(json.loads(recorder.calls[0][3]),{'expiresIn':4200})
    def test_stream_checks_head_and_get_and_never_reads_more_than_a_chunk(self):
        headers = {"Content-Length": "6", "Content-Type": "video/mp4", "ETag": '"fixed"'}
        storage, handler = storage_with([(200, headers, b""), (200, headers, b"abcdef")])
        pieces = list(storage.iter_verified_video(WS, f"{VID}.mp4", expected_bytes=6,
                                                  expected_mime="video/mp4", expected_etag='"fixed"', chunk_size=2))
        self.assertEqual(pieces, [b"ab", b"cd", b"ef"])
        self.assertEqual([request[0] for request in handler.requests], ["HEAD", "GET"])
        self.assertTrue(all(size <= 2 for size in handler.bodies[1].requested))

    def test_stream_rejects_changed_object_before_returning_bytes(self):
        headers = {"Content-Length": "6", "Content-Type": "video/mp4", "ETag": '"fixed"'}
        changed = {**headers, "ETag": '"changed"'}
        storage, _ = storage_with([(200, headers, b""), (200, changed, b"abcdef")])
        with self.assertRaises(AlphaError):
            list(storage.iter_verified_video(WS, f"{VID}.mp4", expected_bytes=6,
                                             expected_mime="video/mp4", expected_etag='"fixed"', chunk_size=2))


class RedirectTests(unittest.TestCase):
    def test_redirect_is_502_without_follow_up(self):
        storage, handler = storage_with([(302, {"Location": "https://evil.example/steal"}, b""), (200, {}, b"never")])
        with self.assertRaises(AlphaError) as caught:
            storage.get(WS, "media", IMG)
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(len(handler.requests), 1)

    def test_every_method_uses_the_opener(self):
        storage, handler = storage_with([(200, {}, b"img"), (200, {}, b""), (200, {"Content-Length": "5", "Content-Type": "video/mp4", "ETag": "e"}, b"")])
        storage.get(WS, "media", IMG)
        storage.delete(WS, "video", f"{VID}.mp4")
        storage.object_info(WS, "video", f"{VID}.mp4")
        self.assertEqual([r[0] for r in handler.requests], ["GET", "DELETE", "HEAD"])
        self.assertTrue(all(r[1].startswith(PROJECT + "/storage/v1/") for r in handler.requests))
        self.assertIn("/object/postriff-video/", handler.requests[1][1])

    def test_other_host_refused(self):
        storage, handler = storage_with([])
        with self.assertRaises(AlphaError) as caught:
            storage._send("GET", "https://other.supabase.co/storage/v1/x", {}, None)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(handler.requests, [])

    def test_oversize_body_refused(self):
        storage, _ = storage_with([(200, {}, b"x" * (8 * 1024 * 1024 + 2))])
        with self.assertRaises(AlphaError) as caught:
            storage.get(WS, "media", IMG)
        self.assertEqual(caught.exception.status, 502)


class PathTests(unittest.TestCase):
    def test_video_category(self):
        storage = SupabaseStorage(PROJECT, KEY, send=Recorder())
        self.assertEqual(storage._path(WS, "video", f"{VID}.mov"), f"{WS}/video/{VID}.mov")
        for category, name in (("video", f"{VID}.webm"), ("video", IMG), ("media", f"{VID}.mp4"), ("video", f"{VID.upper()}.mp4"), ("other", IMG), ("video", None)):
            with self.subTest(category=category, name=name), self.assertRaises(AlphaError):
                storage._path(WS, category, name)
        self.assertEqual(storage._path(WS, "media", IMG), f"{WS}/media/{IMG}")

    def test_video_never_through_a_function(self):
        storage = SupabaseStorage(PROJECT, KEY, send=Recorder())
        with self.assertRaises(AlphaError):
            storage.get(WS, "video", f"{VID}.mp4")
        with self.assertRaises(AlphaError):
            storage.put_immutable(WS, "video", f"{VID}.mp4", b"x")


class SignedUploadTests(unittest.TestCase):
    def test_signed_upload(self):
        path = f"{WS}/video/{VID}.mp4"
        send = Recorder((200, {}, json.dumps({"url": f"/object/upload/sign/postriff-video/{path}?token=abc"}).encode()))
        storage = SupabaseStorage(PROJECT, KEY, send=send)
        url = storage.signed_upload_url(WS, "video", f"{VID}.mp4")
        self.assertEqual(url, f"{PROJECT}/storage/v1/object/upload/sign/postriff-video/{path}?token=abc")
        method, called, headers, _ = send.calls[0]
        self.assertEqual((method, called), ("POST", f"{PROJECT}/storage/v1/object/upload/sign/postriff-video/{path}"))
        self.assertNotIn("x-upsert", {k.lower() for k in headers})
        prefixed = Recorder((200, {}, json.dumps({"url": f"/storage/v1/object/upload/sign/postriff-video/{path}?token=t"}).encode()))
        self.assertTrue(SupabaseStorage(PROJECT, KEY, send=prefixed).signed_upload_url(WS, "video", f"{VID}.mp4").endswith("?token=t"))

    def test_unsafe_answers_refused(self):
        other = f"{WS}/video/{'1' * 32}.mp4"
        for status, body in ((200, {"url": f"/object/upload/sign/postriff-video/{other}?token=a"}), (200, {"url": "https://evil.example/x?token=a"}),
                             (200, {"url": f"/object/upload/sign/postriff-private/{WS}/video/{VID}.mp4?token=a"}), (200, {}), (400, {}), (200, [])):
            with self.subTest(body=body), self.assertRaises(AlphaError) as caught:
                SupabaseStorage(PROJECT, KEY, send=Recorder((status, {}, json.dumps(body).encode()))).signed_upload_url(WS, "video", f"{VID}.mp4")
            self.assertEqual(caught.exception.status, 502)


class ObjectInfoTests(unittest.TestCase):
    def test_head(self):
        send = Recorder((200, {"content-length": "48211234", "Content-Type": "video/quicktime; charset=x", "ETag": '"abc"'}, b""))
        info = SupabaseStorage(PROJECT, KEY, send=send).object_info(WS, "video", f"{VID}.mov")
        self.assertEqual(info, {"bytes": 48211234, "mime": "video/quicktime", "etag": '"abc"'})
        self.assertEqual(send.calls[0][0], "HEAD")

    def test_missing_and_failure(self):
        with self.assertRaises(AlphaError) as caught:
            SupabaseStorage(PROJECT, KEY, send=Recorder((404, {}, b""))).object_info(WS, "video", f"{VID}.mov")
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(AlphaError) as caught:
            SupabaseStorage(PROJECT, KEY, send=Recorder((500, {}, b""))).object_info(WS, "video", f"{VID}.mov")
        self.assertEqual(caught.exception.status, 502)


class ApprovedVideoReadTests(unittest.TestCase):
    HEADERS = {"Content-Length": "5", "Content-Type": "video/mp4", "ETag": '"e1"'}

    def read(self, storage):
        return storage.get_verified_video(WS, f"{VID}.mp4", expected_bytes=5,
                                          expected_mime="video/mp4", expected_etag='"e1"')

    def test_reads_exact_private_object_for_publishing(self):
        storage, handler = storage_with([(200, self.HEADERS, b""), (200, self.HEADERS, b"video")])
        self.assertEqual(self.read(storage), b"video")
        self.assertEqual([request[0] for request in handler.requests], ["HEAD", "GET"])
        self.assertTrue(handler.requests[1][1].startswith(PROJECT + "/storage/v1/object/postriff-video/"))
        self.assertTrue(handler.bodies[1].closed)

    def test_changed_head_or_get_response_never_returns_bytes(self):
        storage, handler = storage_with([(200, {**self.HEADERS, "ETag": '"changed"'}, b"")])
        with self.assertRaises(AlphaError):
            self.read(storage)
        self.assertEqual(len(handler.requests), 1)
        storage, handler = storage_with([(200, self.HEADERS, b""), (200, {**self.HEADERS, "ETag": '"changed"'}, b"video")])
        with self.assertRaises(AlphaError):
            self.read(storage)
        self.assertTrue(handler.bodies[1].closed)

    def test_bounded_read_and_redirect_fail_closed(self):
        storage, handler = storage_with([(200, self.HEADERS, b""), (200, self.HEADERS, b"videoextra")])
        with self.assertRaises(AlphaError):
            self.read(storage)
        self.assertEqual(handler.bodies[1].requested, [6])
        storage, handler = storage_with([(200, self.HEADERS, b""), (302, {"Location": "https://evil.example/"}, b""), (200, {}, b"never")])
        with self.assertRaises(AlphaError):
            self.read(storage)
        self.assertEqual(len(handler.requests), 2)
        with self.assertRaises(AlphaError):
            storage.get_verified_video(WS, f"{VID}.mp4", expected_bytes=100_000_001,
                                       expected_mime="video/mp4", expected_etag='"e1"')

    def test_failed_body_read_is_a_storage_hold_before_publishing(self):
        storage, handler = storage_with([(200, self.HEADERS, b""), (200, self.HEADERS, b"video")])
        original_open = storage._open

        def fail_get_read(method, url, headers, body, **kwargs):
            response = original_open(method, url, headers, body, **kwargs)
            if method == "GET":
                def fail_read(_size):
                    raise TimeoutError("read timed out")
                response.read = fail_read
            return response

        storage._open = fail_get_read
        with self.assertRaises(AlphaError) as caught:
            self.read(storage)
        self.assertEqual(caught.exception.status, 503)
        self.assertTrue(handler.bodies[1].closed)


class RangeTests(unittest.TestCase):
    def test_206(self):
        storage, handler = storage_with([(206, {}, b"0123456789")])
        out = storage.read_range(WS, "video", f"{VID}.mp4", 100, 4)
        self.assertEqual(out, {"data": b"0123", "ranged": True})
        self.assertEqual(handler.requests[0][2]["Range"], "bytes=100-103")
        self.assertEqual(handler.bodies[0].requested, [4])
        self.assertTrue(handler.bodies[0].closed)

    def test_200_stops_at_length_and_closes(self):
        storage, handler = storage_with([(200, {}, b"A" * 10_000)])
        out = storage.read_range(WS, "video", f"{VID}.mp4", 0, 16)
        self.assertEqual(out, {"data": b"A" * 16, "ranged": False})
        self.assertEqual(handler.bodies[0].requested, [16])
        self.assertTrue(handler.bodies[0].closed)
        storage, handler = storage_with([(200, {}, b"A" * 10_000)])
        self.assertEqual(storage.read_range(WS, "video", f"{VID}.mp4", 64, 16), {"data": b"", "ranged": False})
        self.assertEqual(handler.bodies[0].requested, [])

    def test_errors(self):
        for status, expect in ((404, 404), (500, 502), (302, 502)):
            storage, handler = storage_with([(status, {"Location": "https://evil.example"}, b"")])
            with self.subTest(status=status), self.assertRaises(AlphaError) as caught:
                storage.read_range(WS, "video", f"{VID}.mp4", 0, 16)
            self.assertEqual(caught.exception.status, expect)
            self.assertEqual(len(handler.requests), 1)
        storage, _ = storage_with([(416, {}, b"")])
        self.assertEqual(storage.read_range(WS, "video", f"{VID}.mp4", 10**9, 16), {"data": b"", "ranged": True})
        for start, length in ((-1, 5), (0, 0), (0, 9 * 1024 * 1024), (0.5, 4)):
            with self.assertRaises(AlphaError):
                storage.read_range(WS, "video", f"{VID}.mp4", start, length)


class BucketAndListTests(unittest.TestCase):
    def test_bucket_info(self):
        body = {"id": "postriff-video", "public": False, "file_size_limit": 100000000, "allowed_mime_types": ["video/mp4", "video/quicktime"]}
        info = SupabaseStorage(PROJECT, KEY, send=Recorder((200, {}, json.dumps(body).encode()))).bucket_info()
        self.assertEqual(info, {"id": "postriff-video", "public": False, "fileSizeLimit": 100000000, "allowedMimeTypes": ["video/mp4", "video/quicktime"]})
        self.assertIsNone(SupabaseStorage(PROJECT, KEY, send=Recorder((404, {}, b""))).bucket_info())
        with self.assertRaises(AlphaError) as caught:
            SupabaseStorage(PROJECT, KEY, send=Recorder((500, {}, b""))).bucket_info()
        self.assertEqual(caught.exception.status, 503)

    def test_list_paginates(self):
        page1 = [{"name": f"{n:032x}.mp4"} for n in range(100)]
        page2 = [{"name": "f" * 32 + ".mov"}, {"name": "nested/x"}]
        send = Recorder((200, {}, json.dumps(page1).encode()), (200, {}, json.dumps(page2).encode()))
        names = SupabaseStorage(PROJECT, KEY, send=send).list_prefix(f"{WS}/video/")
        self.assertEqual(len(names), 101)
        self.assertEqual(names[-1], f"{WS}/video/{'f' * 32}.mov")
        self.assertEqual([json.loads(c[3])["offset"] for c in send.calls], [0, 100])
        self.assertTrue(send.calls[0][1].endswith("/object/list/postriff-video"))

    def test_list_prefix_checked(self):
        storage = SupabaseStorage(PROJECT, KEY, send=Recorder())
        for prefix in ("", "../x", f"{WS}/secrets", f"{WS}/video/x"):
            with self.subTest(prefix=prefix), self.assertRaises(AlphaError):
                storage.list_prefix(prefix)


class RemoveTests(unittest.TestCase):
    def test_video_removes_object_poster_and_frames(self):
        send = Recorder((200, {}, b""), (404, {}, b""), (204, {}, b""))
        asset = {"id": VID, "mime": "video/mp4", "objectName": f"{VID}.mp4", "poster": {"objectName": IMG}, "frames": [{"objectName": IMG}, {"objectName": FRAME}]}
        PrivateAssetService(SupabaseStorage(PROJECT, KEY, send=send)).remove(WS, asset)
        urls = [c[1] for c in send.calls]
        self.assertEqual(urls, [f"{PROJECT}/storage/v1/object/postriff-video/{WS}/video/{VID}.mp4",
                                f"{PROJECT}/storage/v1/object/postriff-private/{WS}/media/{IMG}",
                                f"{PROJECT}/storage/v1/object/postriff-private/{WS}/media/{FRAME}"])
        self.assertTrue(all(c[0] == "DELETE" for c in send.calls))

    def test_image_unchanged(self):
        send = Recorder((200, {}, b""))
        PrivateAssetService(SupabaseStorage(PROJECT, KEY, send=send)).remove(WS, {"mime": "image/jpeg", "objectName": IMG})
        self.assertEqual(send.calls[0][1], f"{PROJECT}/storage/v1/object/postriff-private/{WS}/media/{IMG}")

    def test_delete_failure(self):
        with self.assertRaises(AlphaError):
            PrivateAssetService(SupabaseStorage(PROJECT, KEY, send=Recorder((500, {}, b"")))).remove(WS, {"mime": "video/mp4", "objectName": f"{VID}.mp4"})


class ProbeScriptTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("storage_probe", ROOT / "scripts" / "postriff_storage_probe.py")
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)

    def run_main(self, args, env):
        out = io.StringIO()
        stdout, sys.stdout = sys.stdout, out
        try:
            code = self.probe.main(args, env)
        finally:
            sys.stdout = stdout
        return code, json.loads(out.getvalue())

    def test_refuses_without_explicit_flags_and_env(self):
        full = {"POSTRIFF_STORAGE_PROBE": "1", "POSTRIFF_SUPABASE_URL": PROJECT, "POSTRIFF_SUPABASE_SECRET_KEY": KEY}
        for args, env in (([], full), (["--probe"], {**full, "CI": "true"}), (["--probe"], {**full, "GITHUB_ACTIONS": "true"}),
                          (["--probe"], {k: v for k, v in full.items() if k != "POSTRIFF_STORAGE_PROBE"}),
                          (["--create-bucket"], {k: v for k, v in full.items() if k != "POSTRIFF_SUPABASE_SECRET_KEY"}),
                          (["--create-bucket", "--max-bytes", "300000000"], full)):
            with self.subTest(args=args, env=sorted(env)):
                code, out = self.run_main(args, env)
                self.assertEqual((code, out["ok"]), (2, False))
                self.assertNotIn(KEY, json.dumps(out))


if __name__ == "__main__":
    unittest.main()
