"""Coordinator wiring between workstreams: processor registry identity and the job writer order."""
import unittest

from library_intelligence_fakes import FakeCursor, ctx, version
from postriff_phase2.library_intelligence import capabilities, jobs


def proc(name, capability="extract", ver="v1", location="local", category="extract"):
    return {"name": name, "capability": capability, "version": ver, "location": location, "category": category,
            "applies": lambda v: True, "run": lambda job: {"state": "ready"}}


class Registry(unittest.TestCase):
    def setUp(self):
        self.saved = {k: list(v) for k, v in capabilities.PROCESSORS.items()}

    def tearDown(self):
        capabilities.PROCESSORS.clear()
        capabilities.PROCESSORS.update(self.saved)

    def test_local_and_cloud_processors_for_one_capability_coexist(self):
        capabilities.PROCESSORS.pop("extract", None)
        capabilities.register(proc("t.structure"))
        capabilities.register(proc("t.ocr", location="cloud", category="ocr"))
        capabilities.register(proc("t.structure"))  # re-import is idempotent by name
        names = [p["name"] for p in capabilities.PROCESSORS["extract"]]
        self.assertEqual(names, ["t.ocr", "t.structure"])


class WriterOrder(unittest.TestCase):
    def test_media_written_before_segments_with_new_bounds(self):
        calls = []
        originals = jobs._writer

        def fake_writer(module, function):
            def write(cur, ws, v, items, **kw):
                calls.append((function, (v.get("media") or {}).get("durationMs"), kw))
                return len(items) if isinstance(items, list) else True
            return write
        jobs._writer = fake_writer
        try:
            context = ctx(FakeCursor())
            outcome = {"state": "ready", "segments": [{"text": "hi"}], "annotations": [], "embeddings": [], "media": {"durationMs": 9000},
                       "extractor": "library.transcribe", "extractorVersion": "asr-1:whisper-1", "replaceFields": None, "provider": None}
            written = jobs._write(context, version(kind="audio"), proc("t.transcribe", capability="transcribe"), outcome)
        finally:
            jobs._writer = originals
        self.assertEqual([c[0] for c in calls], ["write_media", "write_segments"])
        self.assertEqual(calls[1][1], 9000, "segments see the duration written in the same finalize")
        self.assertEqual(calls[1][2]["extractor_version"], "asr-1:whisper-1")
        self.assertTrue(written["media"])


class Effects(unittest.TestCase):
    def test_new_scheduled_job_records_usage_and_never_raises(self):
        import os
        from unittest import mock
        from postriff_phase2.library_intelligence import effects, usage
        calls = []
        media = "a" * 32
        before = {"phase2": {"jobs": []}, "variants": []}
        after = {"phase2": {"jobs": [{"id": "job1", "manifest": {"platform": "Threads", "media": [{"id": media}, {"id": "../x"}]}}]}, "variants": []}
        with mock.patch.object(usage, "record_usage", lambda cur, ws, a, v, kind, **kw: calls.append((a, kind, kw["dedup_key"], kw["channel"])) or {"recorded": True}), \
                mock.patch.dict(os.environ, {"RAFII_LIBRARY_SUGGESTIONS_ENABLED": ""}):
            effects.capture(FakeCursor(), "ws", before, after, "actor")
        self.assertEqual(calls, [(media, "post_scheduled", f"schedule:job1:{media}", "Threads")], "only valid Library ids; deduplicated per job")

        def boom(*_a, **_k):
            raise RuntimeError("db down")
        cur = FakeCursor()
        with mock.patch.object(usage, "record_usage", boom):
            effects.capture(cur, "ws", before, after, "actor")  # must not raise into the command
        self.assertTrue(cur.sql(r"ROLLBACK TO SAVEPOINT library_intelligence_effects"))

    def test_published_wrapper_calls_inner_first(self):
        from unittest import mock
        from postriff_phase2.library_intelligence import effects, usage
        order = []
        with mock.patch.object(usage, "record_usage", lambda *a, **k: order.append("usage") or {"recorded": True}):
            effects.on_published(lambda cur, ws, job: order.append("inner"))(FakeCursor(), "ws", {"id": "j", "manifest": {"media": [{"id": "b" * 32}]}})
        self.assertEqual(order, ["inner", "usage"])


class OfficeXmlGuard(unittest.TestCase):
    def test_utf16_part_cannot_hide_a_doctype(self):
        import io
        import zipfile
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.library_intelligence import structure
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<?xml version=\"1.0\"?><Types/>")
            z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "b">]><w/>'.encode("utf-16"))
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as archive:
            with self.assertRaises(AlphaError):
                structure._xml(archive, "word/document.xml")


if __name__ == "__main__":
    unittest.main()
