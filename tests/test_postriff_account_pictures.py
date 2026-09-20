"""Connected accounts' profile pictures for previews: provider fields, the download rules, re-encoding, storage
guards and the picture route. No network: every fetch is a fake."""
import hashlib
import io
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from postriff_alpha.domain import AlphaError
from postriff_phase2 import account_pictures
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.privacy import notice
from postriff_phase2.providers import InstagramProvider, LinkedInProvider, ThreadsProvider
from test_postriff_channels import FakeOAuth
from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke
from test_postriff_providers import Recorder


def image_bytes(fmt="PNG", size=(320, 240), mode="RGB", color=(200, 30, 60, 255)):
    image = Image.new(mode, size, color[: len(mode)] if mode != "P" else 1)
    output = io.BytesIO()
    if fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "SecretCam"  # Make: must not survive re-encoding
        image.save(output, format=fmt, exif=exif)
    else:
        image.save(output, format=fmt)
    return output.getvalue()


class Fetch:
    def __init__(self, status=200, content_type="image/png", raw=None):
        self.status, self.content_type, self.raw, self.urls = status, content_type, raw if raw is not None else image_bytes(), []

    def __call__(self, url):
        self.urls.append(url)
        return self.status, self.content_type, self.raw


class ProviderFields(unittest.TestCase):
    def test_each_provider_returns_the_picture_it_already_may_read(self):
        linkedin = LinkedInProvider("id", "secret", transport=Recorder([{"status": 200, "headers": {}, "body": {"sub": "abc", "name": "Member", "picture": "https://media.licdn.com/dms/image/p.jpg"}}]))
        self.assertEqual(linkedin.identity("AT")["pictureUrl"], "https://media.licdn.com/dms/image/p.jpg")
        for cls, field in ((ThreadsProvider, "threads_profile_picture_url"), (InstagramProvider, "profile_picture_url")):
            with self.subTest(provider=cls.id):
                transport = Recorder([{"status": 200, "headers": {}, "body": {"id": "1789", "username": "creator", field: "https://scontent.cdninstagram.com/v/p.jpg"}}])
                identity = cls("id", "secret", transport=transport).identity("LONG")
                self.assertEqual((identity["handle"], identity["pictureUrl"]), ("@creator", "https://scontent.cdninstagram.com/v/p.jpg"))
                self.assertIn(field, parse_qs(urlparse(transport.calls[0]["url"]).query)["fields"][0].split(","))

    def test_a_profile_without_a_picture_reports_none(self):
        linkedin = LinkedInProvider("id", "secret", transport=Recorder([{"status": 200, "headers": {}, "body": {"sub": "abc", "name": "Member"}}]))
        self.assertIsNone(linkedin.identity("AT")["pictureUrl"])


class Download(unittest.TestCase):
    def test_only_the_providers_image_hosts_over_https(self):
        for url in ("https://media.licdn.com/dms/image/a.jpg", "https://scontent-lax3-1.cdninstagram.com/v/t51/a.jpg", "https://scontent.xx.fbcdn.net/v/a.jpg", "https://media.licdn.com:443/a.jpg"):
            with self.subTest(url=url):
                self.assertTrue(account_pictures.allowed_url(url))
        for url in (
            None,
            "",
            "http://media.licdn.com/a.jpg",
            "https://example.com/a.jpg",
            "https://evilcdninstagram.com/a.jpg",
            "https://cdninstagram.com.evil.example/a.jpg",
            "https://user:pass@media.licdn.com/a.jpg",
            "https://media.licdn.com:8443/a.jpg",
            "https://media.licdn.com:bad/a.jpg",
            "file:///etc/passwd",
            "https://media.licdn.com/" + "a" * 4100,
        ):
            with self.subTest(url=url):
                self.assertFalse(account_pictures.allowed_url(url))

    def test_disallowed_or_missing_url_is_absent_and_never_fetched(self):
        fetch = Fetch()
        self.assertEqual(account_pictures.picture_from_identity({"pictureUrl": "https://example.com/a.png"}, fetch), ("absent", None))
        self.assertEqual(account_pictures.picture_from_identity({}, fetch), ("absent", None))
        self.assertEqual(account_pictures.picture_from_identity(None, fetch), ("absent", None))
        self.assertEqual(fetch.urls, [])

    def test_failed_or_unusable_downloads_are_unavailable(self):
        url = {"pictureUrl": "https://media.licdn.com/a.png"}
        cases = {
            "not found": Fetch(status=404, raw=b""),
            "unreachable": Fetch(status=0, raw=b""),
            "html": Fetch(content_type="text/html", raw=b"<html></html>"),
            "oversize": Fetch(raw=b"\x89PNG" + b"0" * (account_pictures.MAX_DOWNLOAD + 1)),
            "corrupt": Fetch(raw=image_bytes()[:40]),
            "tiny": Fetch(raw=image_bytes(size=(8, 8))),
            "gif": Fetch(content_type="image/gif", raw=image_bytes(fmt="GIF")),
        }
        for name, fetch in cases.items():
            with self.subTest(case=name):
                self.assertEqual(account_pictures.picture_from_identity(url, fetch), ("unavailable", None))

    def test_pictures_are_re_encoded_small_square_and_without_metadata(self):
        for fmt, mode in (("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB")):
            with self.subTest(fmt=fmt):
                raw = image_bytes(fmt=fmt, size=(640, 360), mode=mode, color=(10, 120, 200, 0) if mode == "RGBA" else (10, 120, 200))
                status, (jpeg, digest) = account_pictures.picture_from_identity({"pictureUrl": "https://scontent.cdninstagram.com/p"}, Fetch(content_type=f"image/{fmt.lower()}", raw=raw))
                self.assertEqual(status, "ok")
                self.assertEqual(digest, hashlib.sha256(jpeg).hexdigest())
                with Image.open(io.BytesIO(jpeg)) as out:
                    self.assertEqual((out.format, out.size, out.mode), ("JPEG", (account_pictures.SIDE, account_pictures.SIDE), "RGB"))
                    self.assertNotIn("SecretCam", str(dict(out.getexif())))
                    if mode == "RGBA":  # transparent pixels flatten onto white, never black
                        self.assertGreater(min(out.getpixel((100, 100))), 240)
                self.assertLess(len(jpeg), 262144)  # fits the table's check


class Cursor:
    def __init__(self, fail_on=None, rows=None):
        self.sql, self.fail_on, self.rows = [], fail_on, rows or []

    def execute(self, statement, params=None):
        self.sql.append(statement)
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("relation does not exist")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Storage(unittest.TestCase):
    def test_a_storage_fault_rolls_back_to_its_savepoint_and_reads_as_nothing(self):
        cur = Cursor(fail_on="pr_channel_pictures")
        self.assertIsNone(account_pictures.guarded(cur, account_pictures.digests, "w"))
        self.assertTrue(cur.sql[0].startswith("SAVEPOINT picture_") and cur.sql[-1].startswith("ROLLBACK TO SAVEPOINT picture_"))
        ok = Cursor(rows=[("c" * 32, "d" * 64)])
        self.assertEqual(account_pictures.guarded(ok, account_pictures.digests, "w"), {"c" * 32: "d" * 64})
        self.assertTrue(ok.sql[-1].startswith("RELEASE SAVEPOINT picture_"))

    def test_store_replaces_removes_or_keeps(self):
        cur = Cursor()
        account_pictures.store(cur, "w", "c" * 32, ("ok", (b"jpeg", "d" * 64)))
        account_pictures.store(cur, "w", "c" * 32, ("absent", None))
        account_pictures.store(cur, "w", "c" * 32, ("unavailable", None))
        self.assertEqual([s.split()[0] for s in cur.sql], ["INSERT", "DELETE"])  # a failed fetch keeps the old picture


class PictureOAuth(FakeOAuth):
    def picture(self, w, t, c):
        if c != "conn1":
            raise AlphaError("This account has no picture.", 404)
        return b"\xff\xd8jpeg", "e" * 64


class Route(unittest.TestCase):
    def test_picture_route_serves_private_cacheable_jpeg(self):
        service = FakeService()
        service.oauth = PictureOAuth()
        app = HostedApplication(service, FakeWorker(), {"projectUrl": "x", "publishableKey": "public", "flow": "pkce"}, "c" * 24)
        auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}
        status, headers, body = invoke(app, "GET", "/api/workspaces/w/channels/conn1/picture", headers=auth)
        self.assertEqual((status, body, headers["Content-Type"], headers["Cache-Control"], headers["ETag"]), (200, b"\xff\xd8jpeg", "image/jpeg", "private, max-age=86400", '"' + "e" * 64 + '"'))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, _, missing = invoke(app, "GET", "/api/workspaces/w/channels/other/picture", headers=auth)
        self.assertEqual(status, 404)


class Notice(unittest.TestCase):
    def test_privacy_notice_names_the_stored_picture(self):
        self.assertEqual(notice()["retention"]["account_pictures"]["retention"], "until disconnect")


if __name__ == "__main__":
    unittest.main()
