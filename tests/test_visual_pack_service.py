"""Visual Pack service units without a database: storage object rules (PNG only for rendered pack slides, no upsert),
the deterministic assisted-export zip, routing and the flag gate, and the honest Queue capability answer."""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted_storage import SupabaseStorage  # noqa: E402
from postriff_phase2.visual_pack import http, render, service, slides  # noqa: E402

WID = "00000000-0000-0000-0000-000000000010"
PNG_NAME = "a" * 32 + "-" + "b" * 64 + ".png"
JPG_NAME = "a" * 32 + "-" + "b" * 64 + ".jpg"


class Storage(unittest.TestCase):
    def storage(self, status=200):
        self.calls = []

        def send(method, url, headers, body):
            self.calls.append((method, url, headers))
            if method == "POST" and "/object/list/" in url:
                return 200, {}, json.dumps([{"name": PNG_NAME}]).encode()
            return status, {}, b"{}"
        return SupabaseStorage("https://project.supabase.co", "s" * 32, send=send)

    def test_png_is_allowed_only_for_rendered_pack_slides_without_upsert(self):
        storage = self.storage()
        self.assertEqual(storage.put_immutable(WID, "visual-pack", PNG_NAME, b"png", content_type="image/png"), f"{WID}/visual-pack/{PNG_NAME}")
        self.assertEqual(self.calls[0][2]["x-upsert"], "false")
        self.assertTrue(self.calls[0][1].endswith(f"/storage/v1/object/postriff-private/{WID}/visual-pack/{PNG_NAME}"))
        for category, name, mime in (("visual-pack", JPG_NAME, "image/png"), ("visual-pack", PNG_NAME, "image/jpeg"), ("media", PNG_NAME, "image/png"),
                                     ("media", JPG_NAME, "image/png"), ("artwork", PNG_NAME, "image/png"), ("video", PNG_NAME, "image/png"),
                                     ("visual-pack", "../" + PNG_NAME, "image/png"), ("visual-pack", "c" * 31 + "-" + "b" * 64 + ".png", "image/png")):
            with self.subTest(category=category, name=name, mime=mime), self.assertRaises(AlphaError):
                storage.put_immutable(WID, category, name, b"x", content_type=mime)
        self.assertEqual(storage.put_immutable(WID, "media", JPG_NAME, b"jpeg"), f"{WID}/media/{JPG_NAME}")   # uploads unchanged

    def test_existing_object_is_never_overwritten(self):
        with self.assertRaisesRegex(AlphaError, "already exists") as caught:
            self.storage(409).put_immutable(WID, "visual-pack", PNG_NAME, b"png", content_type="image/png")
        self.assertEqual(caught.exception.status, 409)

    def test_read_delete_and_list_the_pack_prefix(self):
        storage = self.storage()
        storage.get(WID, "visual-pack", PNG_NAME)
        storage.delete(WID, "visual-pack", PNG_NAME)
        self.assertEqual(storage.list_prefix(f"{WID}/visual-pack"), [f"{WID}/visual-pack/{PNG_NAME}"])
        with self.assertRaises(AlphaError):
            storage.list_prefix(f"{WID}/other")


def manifest():
    files = render.render([{"key": f"s{i}", "text": f"Slide {i}", "altText": slides.default_alt(i, f"Slide {i}"), "imageAssetId": None} for i in range(1, 7)],
                          {}, {}, {})["files"]
    return {"schema": "rafii.visual-pack-manifest.v1", "caption": "Caption text", "slides": [
        {"position": f["position"], "file": f"slide-{f['position']:02d}.png", "sha256": f["sha256"], "altText": f"Slide {f['position']} of 6. Text: Slide {f['position']}",
         "objectName": "x" * 32 + "-" + f["sha256"] + ".png", "storagePath": f"{WID}/visual-pack/x"} for f in files]}, {f["position"]: f["png"] for f in files}


class Export(unittest.TestCase):
    def test_zip_is_deterministic_complete_and_free_of_storage_locations(self):
        record, files = manifest()
        first, second = service.build_zip(record, files), service.build_zip(record, dict(files))
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first)) as bundle:
            self.assertEqual(bundle.namelist(), [f"slide-{i:02d}.png" for i in range(1, 7)] + ["caption.txt", "alt-text.txt", "manifest.json", "HANDOFF.txt"])
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in bundle.infolist()))
            self.assertEqual(bundle.read("slide-03.png"), files[3])
            self.assertEqual(bundle.getinfo("slide-01.png").compress_type, zipfile.ZIP_STORED)
            exported = json.loads(bundle.read("manifest.json"))
            self.assertNotIn("storagePath", json.dumps(exported))
            self.assertNotIn("objectName", json.dumps(exported))
            self.assertEqual((exported["handoff"], exported["publication"]), ("assisted_export", "not_published_by_rafii"))
            self.assertIn("has not published", bundle.read("HANDOFF.txt").decode())
            self.assertIn("沒有發佈", bundle.read("HANDOFF.txt").decode())
            self.assertEqual(bundle.read("caption.txt").decode(), "Caption text\n")


class ExportFormats(unittest.TestCase):
    """A recorded export's sha256 can never change (the database keeps it append-only), so a download rebuilds it with
    the exact format it was recorded with: each format pins its handoff text, manifest shape and compression."""

    # Changing a recorded handoff version breaks every earlier export: add a version instead (and a new format).
    PINNED_HANDOFF = {1: "126c4c73967a0c4a"}

    def test_handoff_versions_are_never_edited_in_place(self):
        import hashlib
        for version, prefix in self.PINNED_HANDOFF.items():
            self.assertTrue(hashlib.sha256(service.HANDOFF_TEXTS[version].encode()).hexdigest().startswith(prefix),
                            f"handoff v{version} changed; add a new version and export format instead")
        for fmt, spec in service.EXPORT_FORMATS.items():
            self.assertIn(spec["handoff"], service.HANDOFF_TEXTS, fmt)
        self.assertIn(service.EXPORT_FORMAT, service.EXPORT_FORMATS)

    def test_each_format_lays_the_zip_out_as_pinned(self):
        record, files = manifest()
        legacy, current = service.build_zip(record, files, 1), service.build_zip(record, files, 2)
        self.assertEqual(service.build_zip(record, files), current)                       # new exports use format 2
        with zipfile.ZipFile(io.BytesIO(legacy)) as old, zipfile.ZipFile(io.BytesIO(current)) as new:
            self.assertEqual(old.namelist(), new.namelist())
            self.assertEqual(old.getinfo("HANDOFF.txt").compress_type, zipfile.ZIP_DEFLATED)   # format 1 depended on zlib
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in new.infolist()))   # format 2 never does
            self.assertNotIn("exportFormat", json.loads(old.read("manifest.json")))
            self.assertEqual(json.loads(new.read("manifest.json"))["exportFormat"], 2)
            self.assertEqual(old.read("HANDOFF.txt"), new.read("HANDOFF.txt"))

    def test_the_recorded_digest_names_the_format(self):
        for fmt in service.EXPORT_FORMATS:
            rev = {"approvalDigest": "a" * 64, "exportSha256": "b" * 64, "exportBytes": 1234,
                   "exportDigest": service.export_digest("a" * 64, "b" * 64, 1234, fmt)}
            self.assertEqual(service.recorded_format(rev), fmt)
        self.assertIsNone(service.recorded_format({"approvalDigest": "a" * 64, "exportSha256": "b" * 64, "exportBytes": 1234, "exportDigest": "c" * 64}))

    def test_a_later_wording_change_never_breaks_an_earlier_export(self):
        record, files = manifest()
        hosted = type("Hosted", (), {"assets": type("Assets", (), {"storage": type("S", (), {
            "get": staticmethod(lambda workspace_id, category, name: files[next(s["position"] for s in record["slides"] if s["objectName"] == name)])})()})()})()
        svc = service.VisualPackService(hosted)
        archive = service.build_zip(record, files)
        import hashlib
        sha = hashlib.sha256(archive).hexdigest()
        rev = {"manifest": record, "approvalDigest": "a" * 64, "exportSha256": sha, "exportBytes": len(archive),
               "exportDigest": service.export_digest("a" * 64, sha, len(archive), service.EXPORT_FORMAT)}
        self.assertEqual(svc._rebuild(WID, rev), archive)
        # A later deploy rewords the handoff note as a new version and a new format: the recorded export still rebuilds.
        from unittest import mock
        with mock.patch.dict(service.HANDOFF_TEXTS, {2: "Reworded handoff note.\n"}), \
                mock.patch.dict(service.EXPORT_FORMATS, {3: {"handoff": 2, "deflate": False, "manifestFormat": True}}), \
                mock.patch.object(service, "EXPORT_FORMAT", 3):
            self.assertNotEqual(service.build_zip(record, files), archive)
            self.assertEqual(svc._rebuild(WID, rev), archive)
        # Bytes that really differ from the record (or an unknown digest) are refused with the way on: a new version.
        for broken in ({**rev, "exportSha256": "0" * 64}, {**rev, "exportDigest": "0" * 64}):
            with self.assertRaises(AlphaError) as caught:
                svc._rebuild(WID, broken)
            self.assertEqual((caught.exception.status, caught.exception.code), (502, "integrity_failed"))
            self.assertIn("make a new version", str(caught.exception))


class App:
    def __init__(self, body=None, query=None):
        self.body, self.query, self.sent = body or {}, query or {}, None

    def _json(self, start_response, status, value):
        self.sent = (status, value)
        return [b""]

    def _body(self, _environ):
        return self.body

    def _query_str(self, _environ, key):
        return self.query.get(key)

    def _query_int(self, _environ, key, default=0):
        return int(self.query.get(key, default))


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args[2:]))
            if name == "slide":
                return b"\x89PNG", "f" * 64
            if name == "download":
                return b"PK", "rafii-carousel-x-r1.zip"
            return {"ok": name}
        return call


class Routes(unittest.TestCase):
    def setUp(self):
        self.addCleanup(flags.attach, None)

    def route(self, method, rest, body=None, query=None):
        app, recorder, headers = App(body, query), Recorder(), {}

        class Hosted:
            visual_packs = recorder
        result = http.handle(app, {}, lambda status, h: headers.update(dict(h), status=status), Hosted(), "token", method, ["api", "workspaces", WID, "visual-packs", *rest])
        return app.sent, recorder.calls, headers, result

    def test_flag_off_answers_feature_disabled(self):
        flags.attach({})
        self.assertFalse(service.enabled())
        with self.assertRaises(AlphaError) as caught:
            self.route("GET", [])
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))

    def test_routes_map_to_one_service_call_each(self):
        flags.attach({"RAFII_VISUAL_PACK_ENABLED": "1"})
        pid = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(self.route("GET", [], query={"limit": "10"})[1], [("list", (None, 10))])
        self.assertEqual(self.route("POST", [], body={"variantId": "v"})[0][0], 201)
        self.assertEqual(self.route("GET", [pid])[1], [("get", (pid,))])
        self.assertEqual(self.route("POST", [pid, "revisions"], body={"x": 1})[1], [("edit", (pid, {"x": 1}))])
        for action, method in (("render", "render"), ("accept", "accept"), ("export", "export"), ("confirm-used", "confirm_used"), ("queue", "queue")):
            self.assertEqual(self.route("POST", [pid, action], body={"expectedRevision": 1})[1], [(method, (pid, {"expectedRevision": 1}))])
        sent, calls, headers, raw = self.route("GET", [pid, "revisions", "3", "slides", "2"])
        self.assertEqual((calls, headers["Content-Type"], headers["ETag"], raw), ([("slide", (pid, 3, 2))], "image/png", '"' + "f" * 64 + '"', [b"\x89PNG"]))
        sent, calls, headers, raw = self.route("GET", [pid, "revisions", "3", "export"])
        self.assertEqual((calls, headers["Content-Type"], headers["Cache-Control"]), ([("download", (pid, 3))], "application/zip", "no-store"))
        self.assertIn('filename="rafii-carousel-x-r1.zip"', headers["Content-Disposition"])
        for method, rest in (("DELETE", [pid]), ("GET", [pid, "revisions", "x", "slides", "1"]), ("PUT", [])):
            with self.assertRaises(AlphaError):
                self.route(method, rest)


class Capability(unittest.TestCase):
    def test_queue_handoff_is_never_offered_without_verified_carousel_publishing(self):
        for platform in ("Instagram", "Threads", "LinkedIn", "X", None):
            answer = service.queue_capability({"platform": platform})
            self.assertFalse(answer["supported"])
            self.assertIn("six-image carousel", answer["reason"])

    def test_blocking_findings_map_to_actionable_codes(self):
        texts = ["Hook", "", "Point ✅", "Point", "Point", "Close"]
        measured = render.layout([{"key": f"s{i + 1}", "text": t, "altText": "alt", "imageAssetId": None} for i, t in enumerate(texts)], {}, {})
        error = service._blocking_error(measured)
        self.assertEqual((error.status, error.code), (409, "unsupported_input"))
        long = render.layout([{"key": f"s{i + 1}", "text": t, "altText": "alt", "imageAssetId": None} for i, t in enumerate(["Hook " * 300] + ["x"] * 5)], {}, {})
        self.assertEqual(service._blocking_error(long).code, "needs_shorter_copy")


if __name__ == "__main__":
    unittest.main()
