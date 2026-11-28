"""First-frame image rights, byte identity and Veo wire contract. No network."""
import base64
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import media_consent
from postriff_phase2 import creative_video_first_frame as frames
from postriff_phase2.creative_video_media_provider import VideoProvider
from postriff_phase2.creative_video_models import RUNWAY_GEN4, STORYBOARD, VERTEX_FAST
from postriff_phase2.creative_video_strategy import route_scene


class FirstFrame(unittest.TestCase):
    def setUp(self):
        self.wid = "c24d4046-d3a3-440d-946a-96fb38e21dda"
        self.key = "a" * 32
        self.raw = b"\xff\xd8\xffsynthetic-rendition\xff\xd9"
        sha = hashlib.sha256(self.raw).hexdigest()
        name = self.key + "-" + sha + ".jpg"
        self.photo = dict(id=self.key, hash=sha, mime="image/jpeg", processing="decoded", width=720, height=1280,
                          bytes=len(self.raw), objectName=name, storagePath=f"{self.wid}/media/{name}")
        self.state = {"phase2":{"assets":[self.photo]}}
        self.options = {"firstFrameAssetId":self.key, "firstFrameConsent":True}
        self.generic = {"id":"openai:fixture","label":"Other provider"}

    def grant(self, cloud=True):
        media_consent.apply_action(self.state, "media_egress",
            {"purpose":"video_first_frame","confirmed":True,"cloud":cloud}, "owner", 10)

    def manifest(self):
        return frames.manifest(self.state, self.wid, self.key)

    def route(self, options):
        return route_scene(options, duration_ms=3500, aspect_ratio="9:16",
                           available_models=[VERTEX_FAST, RUNWAY_GEN4, STORYBOARD])

    def test_processor_is_purpose_specific_and_revocation_invalidates_an_old_quote(self):
        media_consent.apply_action(self.state, "media_egress", {"cloud":True,"confirmed":True},
                                   "owner", 8, processors=[self.generic])
        with self.assertRaises(AlphaError):
            self.manifest()
        self.grant()
        approved = self.manifest()
        self.assertFalse(media_consent.allowed(self.state, media_consent.FIRST_FRAME_PROCESSOR))
        self.grant(False)
        self.assertTrue(media_consent.allowed(self.state, self.generic))
        with self.assertRaises(AlphaError):
            self.manifest()
        self.grant()
        self.assertNotEqual(self.manifest(), approved)
        media_consent.apply_action(self.state, "media_egress", {"cloud":False,"confirmed":True}, "owner", 11)
        with self.assertRaises(AlphaError):
            self.manifest()

    def test_only_a_live_workspace_content_addressed_rendition_can_be_read(self):
        self.grant()
        with self.assertRaises(AlphaError):
            frames.manifest(self.state, "foreign", self.key)
        for field, value in (("deletionPending", True), ("processing","ready"), ("mime","video/mp4"),
                             ("objectName","other.jpg"), ("hash","b"*64), ("sourceId","research-only")):
            with self.subTest(field=field), self.assertRaises(AlphaError):
                frames.manifest({**self.state,"phase2":{"assets":[{**self.photo,field:value}]}}, self.wid, self.key)
        store = Mock()
        service = SimpleNamespace(assets=SimpleNamespace(storage=store))
        approved = self.manifest()
        store.get.return_value = self.raw
        self.assertEqual(frames.read(service, self.wid, approved), self.raw)
        store.get.assert_called_once_with(self.wid, "media", self.photo["objectName"])
        store.get.return_value = b"z" * len(self.raw)
        with self.assertRaises(AlphaError):
            frames.read(service, self.wid, approved)

    def test_routing_and_wire_bytes_are_bound_to_one_paid_veo_take(self):
        for extra in ({"firstFrameConsent": False}, {"firstFrameAssetId":"https://assets.example/reference"},
                      {"mode":"manual","model":RUNWAY_GEN4}, {"level":"draft"}):
            with self.subTest(extra=extra), self.assertRaises(AlphaError):
                self.route({**self.options, **extra})
        self.grant()
        strategy = self.route(self.options)
        text_only = self.route({"mode":"manual","model":VERTEX_FAST})
        self.assertEqual(strategy["model"], VERTEX_FAST)
        self.assertEqual(strategy["estimatedUsdMicro"], text_only["estimatedUsdMicro"])
        strategy["firstFrame"] = self.manifest()
        provider = VideoProvider("fixture-project","fixture-token")
        provider.transport = Mock(return_value=(200,{"name":provider.model_path+"/operations/one"}))
        args = dict(prompt="The box turns slowly.", duration_ms=3500, aspect_ratio="9:16")
        for bad in (None,b"changed"):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                provider.submit(**args,strategy=strategy,first_frame=bad)
        with self.assertRaises(AlphaError):
            provider.submit(**args,strategy=text_only,first_frame=self.raw)
        provider.transport.assert_not_called()
        provider.submit(**args,strategy=strategy,first_frame=self.raw)
        body = provider.transport.call_args.args[1]
        self.assertEqual(body["instances"], [{"prompt":args["prompt"],"image":{
            "bytesBase64Encoded":base64.b64encode(self.raw).decode(),"mimeType":"image/jpeg"}}])
        self.assertEqual(body["parameters"]["sampleCount"], 1)
        provider.submit(**args,strategy=text_only)
        self.assertEqual(provider.transport.call_args.args[1]["instances"], [{"prompt":args["prompt"]}])
