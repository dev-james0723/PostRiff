"""Raw-file intake units (PRD R-FWR-04; AC11, AC12, AC28): content sniffing and durations without ffmpeg, the bounded
PDF extractor, lower-wins limits, the transcription boundary (no vendor enrolled), the private `source` storage
category, strict source normalisation, retention, routes and agent tool contracts. No network; fixtures are built
in-test. PDF cases need pypdf (requirements.txt) and are skipped when it isn't installed.
"""
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.source_uploads import limits, pdf_text, service as svc_module, sniff, transcribe  # noqa: E402
from source_upload_fixtures import (INJECTION, PARAGRAPH, encrypted_pdf_bytes, m4a_bytes, mp3_bytes, ogg_opus_bytes, pdf_bytes,  # noqa: E402
                                    wav_bytes, webm_bytes)

HAS_PYPDF = pdf_text.available()


def extract(data, **kw):
    return pdf_text.extract(data, **{"max_bytes": 20_000_000, "max_pages": 100, "max_chars": 60_000, "seconds": 15, **kw})


class AC11SniffAndDuration(unittest.TestCase):
    def test_ac11_supported_audio_durations_are_measured_from_the_bytes(self):
        self.assertEqual(sniff.inspect(wav_bytes(3.5), "wav"), {"type": "wav", "seconds": 3.5})
        self.assertAlmostEqual(sniff.inspect(mp3_bytes(12.0), "mp3")["seconds"], 12.0, delta=0.05)
        self.assertAlmostEqual(sniff.inspect(mp3_bytes(2.0, id3=False), "mp3")["seconds"], 2.0, delta=0.05)
        self.assertEqual(sniff.inspect(m4a_bytes(42.5), "m4a")["seconds"], 42.5)
        self.assertEqual(sniff.inspect(ogg_opus_bytes(61.0), "ogg")["seconds"], 61.0)
        self.assertEqual(sniff.inspect(pdf_bytes(["hello world"]), "pdf"), {"type": "pdf", "seconds": None})

    def test_ac12_declared_type_must_match_the_real_content(self):
        for data, declared in ((wav_bytes(1), "mp3"), (pdf_bytes(["x"]), "wav"), (b"<html><script>alert(1)</script>", "pdf"), (mp3_bytes(1), "m4a"), (b"\x00" * 64, "ogg")):
            with self.assertRaises(sniff.SniffError) as caught:
                sniff.inspect(data, declared)
            self.assertEqual(caught.exception.code, "mime_mismatch", declared)

    def test_ac11_video_in_an_audio_container_and_webm_are_refused_truthfully(self):
        with self.assertRaises(sniff.SniffError) as video:
            sniff.inspect(m4a_bytes(5, video=True), "m4a")
        self.assertEqual(video.exception.code, "mime_mismatch")
        with self.assertRaises(sniff.SniffError) as webm:
            sniff.inspect(webm_bytes(), "m4a")
        self.assertEqual(webm.exception.code, "unsupported")
        with self.assertRaises(sniff.SniffError) as codec:
            sniff.inspect(ogg_opus_bytes(3, codec=b"Speex   "), "ogg")
        self.assertEqual(codec.exception.code, "unsupported")

    def test_ac11_unreadable_duration_is_unsupported_not_guessed(self):
        truncated_wav = wav_bytes(1)[:20]   # RIFF/WAVE header with no fmt/data chunks
        with self.assertRaises(sniff.SniffError) as wav:
            sniff.inspect(truncated_wav, "wav")
        self.assertEqual(wav.exception.code, "duration_unreadable")
        no_moov = m4a_bytes(5)[:32]
        with self.assertRaises(sniff.SniffError) as m4a:
            sniff.inspect(no_moov, "m4a")
        self.assertEqual(m4a.exception.code, "duration_unreadable")
        junk_tail = mp3_bytes(1, id3=False)[:300] + b"\x01" * 20_000   # a few frames, then not audio
        with self.assertRaises(sniff.SniffError) as mp3:
            sniff.inspect(junk_tail, "mp3")
        self.assertEqual(mp3.exception.code, "duration_unreadable")

    def test_ac12_declared_mime_aliases_and_refusals(self):
        self.assertEqual(sniff.declared_type("audio", "audio/x-m4a"), "m4a")
        self.assertEqual(sniff.declared_type("audio", "Audio/MPEG"), "mp3")
        self.assertEqual(sniff.declared_type("pdf", "application/pdf"), "pdf")
        for kind, mime, code in (("audio", "audio/webm", "unsupported"), ("audio", "video/mp4", "unsupported"), ("audio", "text/html", "unsupported"),
                                 ("audio", "application/pdf", "mime_mismatch"), ("pdf", "audio/wav", "mime_mismatch"), ("pdf", None, "unsupported")):
            with self.assertRaises(sniff.SniffError) as caught:
                sniff.declared_type(kind, mime)
            self.assertEqual(caught.exception.code, code, mime)


@unittest.skipUnless(HAS_PYPDF, "pypdf (requirements.txt) is not installed")
class AC11PdfText(unittest.TestCase):
    def test_ac11_text_pdf_is_extracted_with_per_page_counts(self):
        out = extract(pdf_bytes([PARAGRAPH, "Second page line one.\nSecond page line two."]))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["pageCount"], 2)
        self.assertIn("Riverside Youth Orchestra", out["text"])
        self.assertEqual(len(out["text"]), out["totalChars"])
        self.assertEqual([p["page"] for p in out["pages"]], [1, 2])

    def test_ac12_embedded_instructions_come_back_as_plain_text(self):
        out = extract(pdf_bytes([INJECTION]))
        self.assertEqual(out["status"], "ok")
        self.assertIn("Ignore previous instructions", out["text"])

    def test_ac11_scanned_encrypted_and_broken_pdfs_are_unsupported(self):
        self.assertEqual(extract(pdf_bytes(["", ""], image_only=True))["status"], "no_text_layer")
        self.assertEqual(extract(encrypted_pdf_bytes())["status"], "encrypted")
        self.assertEqual(extract(b"%PDF-1.4 not really")["status"], "unreadable")
        self.assertEqual(extract(b"")["status"], "unreadable")

    def test_ac11_over_limits_report_measured_values_and_never_truncate(self):
        over = extract(pdf_bytes([PARAGRAPH] * 4), max_chars=500)
        self.assertEqual(over["status"], "over_limit")
        self.assertNotIn("text", over)
        self.assertGreater(over["totalChars"], 500)
        self.assertEqual(len(over["pages"]), 4)
        pages = extract(pdf_bytes(["page text one"] * 4), max_pages=3)
        self.assertEqual((pages["status"], pages["pageCount"]), ("too_many_pages", 4))
        chosen = extract(pdf_bytes(["first page words for the season", "second page words for the season", "third page words for the season"]), max_pages=3, pages=(2, 3))
        self.assertEqual((chosen["status"], chosen["selection"]), ("ok", [2, 3]))
        self.assertNotIn("first page", chosen["text"])

    def test_elapsed_cap_kills_the_parser(self):
        with mock.patch.object(pdf_text.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 1)):
            self.assertEqual(extract(pdf_bytes(["x"]))["status"], "timeout")

    def test_the_parser_process_gets_no_secrets(self):
        with mock.patch.dict("os.environ", {"POSTRIFF_SUPABASE_SECRET_KEY": "sb_secret_never", "OPENAI_API_KEY": "sk-never"}):
            env = pdf_text._child_environment()
        self.assertEqual(set(env), {"PATH", "PYTHONPATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "LANG"})
        self.assertNotIn("never", json.dumps(env))


class LimitsLowerWins(unittest.TestCase):
    def test_environment_can_only_lower_the_launch_ceilings(self):
        policy = limits.Policy.from_environment({"RAFII_SOURCE_UPLOADS_ENABLED": "1", "RAFII_SOURCE_UPLOADS_AUDIO_MAX_BYTES": "999999999999",
                                                 "RAFII_SOURCE_UPLOADS_AUDIO_MAX_SECONDS": "300", "RAFII_SOURCE_UPLOADS_TEXT_MAX_CHARS": "90000"})
        self.assertTrue(policy.enabled)
        self.assertEqual((policy.audio_max_bytes, policy.audio_max_seconds, policy.text_max_chars), (30_000_000, 300, 60_000))
        self.assertFalse(limits.Policy.from_environment({}).enabled)

    def test_bucket_and_route_limits_lower_what_is_shown_and_enforced(self):
        route = transcribe.SyntheticTranscriber(max_seconds=120, max_bytes=5_000_000)
        effective = limits.Policy().effective(bucket_limit=10_000_000, route=route)
        self.assertEqual(effective["audio"], {"maxBytes": 5_000_000, "maxSeconds": 120})
        self.assertEqual(effective["pdf"], {"maxBytes": 10_000_000, "maxPages": 100, "maxCharacters": 60_000})


class TranscriptionBoundary(unittest.TestCase):
    def test_no_vendor_is_enrolled_so_audio_is_not_enabled(self):
        self.assertEqual(transcribe.ROUTES, {})
        self.assertEqual(transcribe.route_from_environment({}), (None, "transcription_route_not_enabled"))
        self.assertEqual(transcribe.route_from_environment({"RAFII_TRANSCRIPTION_ROUTE": "synthetic"}), (None, "transcription_route_not_enabled"))
        self.assertEqual(transcribe.route_from_environment({"RAFII_TRANSCRIPTION_ROUTE": "openai:whisper-1"}), (None, "transcription_route_not_enabled"))

    def test_synthetic_transcriber_is_labelled_and_bounded(self):
        route = transcribe.SyntheticTranscriber()
        self.assertTrue(route.synthetic)
        self.assertEqual(route.max_cost_usd_micro(61), 12_000)
        out = route.transcribe(b"x", "audio/wav", 61, timeout=5)
        self.assertTrue(out["text"].startswith("[Synthetic transcript"))
        with self.assertRaises(transcribe.TranscriptionFailed):
            transcribe.SyntheticTranscriber(fail="refused").transcribe(b"x", "audio/wav", 1, timeout=1)


class StorageSourceCategory(unittest.TestCase):
    def setUp(self):
        from postriff_phase2.hosted_storage import SupabaseStorage
        self.calls = []

        def send(method, url, headers, body):
            self.calls.append((method, url))
            return 200, {}, json.dumps({"url": "/object/upload/sign/rafii-source-uploads/5b2e7c1a-0000-4000-8000-000000000001/source/" + "a" * 32 + ".pdf?token=t"}).encode()

        self.storage = SupabaseStorage("https://abcd1234.supabase.co", "sb_secret_" + "x" * 30, send=send)

    def test_source_objects_have_their_own_private_bucket_and_names(self):
        ws = "5b2e7c1a-0000-4000-8000-000000000001"
        url = self.storage.signed_upload_url(ws, "source", "a" * 32 + ".pdf")
        self.assertIn("/object/upload/sign/rafii-source-uploads/", url)
        self.assertIn("/object/upload/sign/rafii-source-uploads/", self.calls[0][1])
        for bad in ("a" * 32 + ".exe", "a" * 32 + ".webm", "../x.pdf", "a" * 31 + ".pdf"):
            with self.assertRaises(AlphaError):
                self.storage.signed_upload_url(ws, "source", bad)

    def test_raw_sources_are_never_written_or_served_by_the_generic_paths(self):
        ws = "5b2e7c1a-0000-4000-8000-000000000001"
        with self.assertRaises(AlphaError):
            self.storage.put_immutable(ws, "source", "a" * 32 + ".pdf", b"%PDF-1.4")
        with self.assertRaises(AlphaError):
            self.storage.get(ws, "source", "a" * 32 + ".pdf")
        self.assertEqual(self.calls, [])


class StrictNormalisationAndRetention(unittest.TestCase):
    def test_strict_mode_refuses_over_limit_text_with_its_measured_length(self):
        from postriff_phase2.coworker import source_intake
        long = "A complete sentence about the orchestra season. " * 1300
        with self.assertRaises(AlphaError) as caught:
            source_intake.normalize("pdf", {"text": long}, strict=True)
        self.assertEqual((caught.exception.status, caught.exception.code), (413, "source_too_long"))
        self.assertIn(f"{len(long.strip()):,}", str(caught.exception))
        # Other callers keep the historical behaviour.
        self.assertEqual(len(source_intake.normalize("pdf", {"text": long})["text"]), source_intake.MAX_TEXT)

    def test_raw_upload_retention_class_is_published(self):
        from postriff_phase2 import privacy
        entry = privacy.notice()["retention"]["raw_source_uploads"]
        self.assertIn("30 days after a source is created", entry["retention"])
        self.assertIn("retracted", entry["retention"])


class TextHelpers(unittest.TestCase):
    def test_caption_cues_read_as_paragraphs_split_on_pauses(self):
        segments = [{"start": 0.0, "end": 1.5, "text": "We open registration"}, {"start": 1.6, "end": 3.0, "text": "on Monday."},
                    {"start": 6.0, "end": 8.0, "text": "Rehearsals start in June."}]
        self.assertEqual(svc_module.join_cues(segments), "We open registration on Monday.\n\nRehearsals start in June.")

    def test_clean_text_and_ids(self):
        self.assertEqual(svc_module.clean_text("a\x00b\r\nc \t\n\n\n\n\nd\x07"), "ab\nc\n\n\nd")
        self.assertEqual(svc_module._id("0F3C0E3A9D5B4C1E8F7A6B5C4D3E2F10"), "0f3c0e3a-9d5b-4c1e-8f7a-6b5c4d3e2f10")
        for bad in ("../etc", "x" * 32, None):
            with self.assertRaises(AlphaError):
                svc_module._id(bad)
        with self.assertRaises(AlphaError):
            svc_module._key("short")
        self.assertEqual(svc_module.mmss(612.4), "10:12")


class FakeApp:
    def __init__(self):
        self.responses = []

    def _json(self, start_response, status, body):
        self.responses.append((status, body))
        return [b""]

    @staticmethod
    def _body(environ):
        return json.loads(environ.get("body", "{}"))

    @staticmethod
    def _query_str(environ, key):
        return None

    @staticmethod
    def _query_int(environ, key, default=0):
        return default


class Routes(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        # test_growth_v2_routes checks that a failed lazy import leaves no module behind; don't leave ours either.
        sys.modules.pop("postriff_phase2.source_uploads.http", None)

    def setUp(self):
        from postriff_phase2.source_uploads import http
        self.http = http
        self.service = mock.MagicMock()
        self.service.policy = limits.Policy(enabled=True)
        self.hosted = mock.MagicMock(source_uploads=self.service)
        self.app = FakeApp()

    def call(self, method, *rest, body=None):
        environ = {"CONTENT_LENGTH": "2" if body is not None else "0", "body": json.dumps(body or {})}
        self.http.handle(self.app, environ, None, self.hosted, "session", method, ["api", "workspaces", "w1", "source-uploads", *rest])
        return self.app.responses[-1]

    def test_routes_map_to_one_service_operation_each(self):
        uid = "0f3c0e3a-9d5b-4c1e-8f7a-6b5c4d3e2f10"
        self.assertEqual(self.call("GET", "limits")[0], 200)
        self.service.limits_view.assert_called_once_with("w1", "session")
        self.assertEqual(self.call("POST", body={"kind": "pdf"})[0], 201)
        self.service.begin.assert_called_once()
        self.assertEqual(self.call("POST", "transcripts", body={})[0], 201)
        self.call("GET", uid)
        self.service.status.assert_called_with("w1", "session", uid)
        self.call("DELETE", uid)
        self.service.delete.assert_called_with("w1", "session", uid)
        for action, method in (("commit", "commit"), ("process", "process"), ("cancel", "cancel"), ("transcribe", "transcribe"), ("pages", "select_pages"),
                               ("text", "save_text"), ("review", "review")):
            self.call("POST", uid, action, body={})
            getattr(self.service, method).assert_called()
        self.assertEqual(self.call("POST", uid, "source", body={})[0], 201)
        self.call("GET", uid, "text")
        self.service.text.assert_called_with("w1", "session", uid)
        self.call("GET", uid, "quote")
        self.service.quote.assert_called_with("w1", "session", uid)

    def test_unknown_routes_are_404(self):
        for method, rest in (("PUT", ["x"]), ("POST", ["x", "publish"]), ("GET", ["x", "y", "z"])):
            with self.assertRaises(AlphaError) as caught:
                self.call(method, *rest, body={})
            self.assertEqual(caught.exception.status, 404)

    def test_dispatcher_reaches_this_slice(self):
        from postriff_phase2 import growth_v2_routes
        self.assertEqual(growth_v2_routes.RESOURCES["source-uploads"], "postriff_phase2.source_uploads.http")
        self.assertIn("postriff_phase2.source_uploads.jobs", growth_v2_routes.CRON)
        self.assertIsNotNone(growth_v2_routes._module("postriff_phase2.source_uploads.jobs"))


class AC28AgentTools(unittest.TestCase):
    def test_tools_have_typed_effects_and_voice_parity(self):
        from postriff_phase2.agent_runtime_v2 import contracts, tool_adapter
        from postriff_phase2.source_uploads import agent_tools
        agent_tools.register()
        agent_tools.register()   # idempotent
        status, create = tool_adapter.REGISTRY["source_upload_status"].spec, tool_adapter.REGISTRY["source_from_upload"].spec
        self.assertEqual((status.effect, status.permission, status.voice), (contracts.READ, "read", True))
        self.assertEqual((create.effect, create.permission, create.voice, create.approval), (contracts.CREATE_DRAFT, "edit", True, False))
        schema = tool_adapter.REGISTRY["source_from_upload"].schema
        self.assertEqual(set(schema["properties"]), {"uploadId", "title"})   # no quote acceptance, no review confirmation
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
