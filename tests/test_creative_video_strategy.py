"""No provider calls. The storyboard test encodes and decodes actual original media."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import creative_video_strategy as engine
from postriff_phase2.creative_video_assets import validate_generated_clip
from postriff_phase2 import creative_video_health as health
from postriff_phase2.creative_video_health import WorkerHealth
from postriff_phase2 import creative_video_media_provider as vertex
from postriff_phase2.creative_video_models import PriceLine, metered_total
from postriff_phase2.creative_video_media_provider import ProviderError, VideoProvider
from postriff_phase2 import creative_video_runway as runway
from postriff_phase2.creative_video_runway import asset_request_path


GEN4 = "gen4.5"
VERTEX = VideoProvider.model
GATEWAY = "veo3.1_fast"
BOARD = "storyboard-v1"
ALL = {GEN4, VERTEX, GATEWAY, BOARD}
CONFIG = {"RAFII_CREATIVE_VIDEO_PROVIDERS": "runway", "RAFII_CREATIVE_VIDEO_RUNWAY_KEY": "fixture",
          "RAFII_CREATIVE_VIDEO_RUNWAY_MODELS": "gen4.5,veo3.1_fast"}
HANDLE = "60f57220-70ac-4a7c-bb95-cb229ca651c8"


def route(settings=None, duration=3500, available=ALL, balance=None, ratio="9:16"):
    return engine.route_scene(settings or {}, duration_ms=duration, aspect_ratio=ratio,
                              available_models=available, available_millicredits=balance)


class RoutingTests(unittest.TestCase):
    def test_presets_change_real_strategy_and_native_resolution_cost(self):
        draft, balanced, cinematic = (route({"level": level}) for level in ("draft", "balanced", "cinematic"))
        self.assertEqual((draft["model"], draft["mediaKind"], draft["estimatedMilliCredits"]), (BOARD, "composed", 0))
        self.assertEqual((balanced["model"], balanced["audio"], balanced["estimatedMilliCredits"]),
                         (VERTEX, "generated", 120_000))
        self.assertEqual((cinematic["resolution"], cinematic["estimatedMilliCredits"]), ("1080p", 288_000))
        self.assertTrue(cinematic["outputProfile"]["strictQuality"])

    def test_fail_closed_for_unimplemented_inputs_and_incompatible_manual_controls(self):
        for settings in ({"requirements": ["reference-video"]}, {"variations": 2},
                         {"mode": "manual", "model": GEN4, "audio": "generated"},
                         {"mode": "manual", "model": GEN4, "resolution": "1080p"},
                         {"mode": "manual", "model": "invented"}, {"debug": "pass-through"},
                         {"requirements": ["character-identity"]}, {"referenceAdherence": []}):
            with self.subTest(settings=settings), self.assertRaises(AlphaError):
                route(settings)

    def test_budget_mode_and_balance_never_downgrade_or_switch_output_type(self):
        self.assertEqual(route({"mode": "budget", "maxMilliCredits": 80_000}, duration=1750)["model"], GEN4)
        quiet = route({"mode":"budget","maxMilliCredits":100_000}, duration=4000, available={VERTEX})
        self.assertEqual((quiet["audio"],quiet["estimatedMilliCredits"]),("silent",96_000))
        with self.assertRaises(AlphaError):
            route({"mode":"budget","maxMilliCredits":100_000,"requirements":["native-audio"]},duration=4000,available={VERTEX})
        for settings, balance in (({"mode": "budget", "maxMilliCredits": 0}, None), ({}, 0),
                                  ({"mode": "budget"}, None), ({"level": "balanced"}, 500)):
            with self.subTest(settings=settings), self.assertRaises(AlphaError):
                route(settings, balance=balance)
        with self.assertRaises(AlphaError):
            route({"mode": "manual", "model": VERTEX}, available={GEN4})
        preview = engine.route_scene({"mode":"budget", "maxMilliCredits":0}, duration_ms=1800, aspect_ratio="9:16",
                                     available_models=ALL, available_millicredits=0, preview_over_budget=True)
        self.assertTrue(preview["budgetExceeded"])
        self.assertEqual((preview["model"], preview["estimatedMilliCredits"]), (GEN4, 72_000))

    def test_scene_specific_hybrid_audio_constraints_and_offline_default(self):
        first = route({"level": "professional", "mode": "hybrid", "audio": "silent",
                       "motionQuality": "high", "resolution": "720p", "speed": "fast"}, duration=1750)
        second = route({"mode": "hybrid", "audio": "generated", "requirements": ["native-audio"]})
        self.assertEqual((first["model"], second["model"]), (GEN4, VERTEX))
        self.assertNotEqual(first["provider"], second["provider"])
        self.assertEqual((first["billedSeconds"], second["billedSeconds"]), (2, 4))
        with self.assertRaises(AlphaError):
            route({}, available={BOARD})
        self.assertEqual(route({"level": "draft"}, available={BOARD}, ratio="1:1")["provider"], "rafii-local")

    def test_versioned_immutable_price_snapshot_and_no_client_rate(self):
        quote = route({"mode": "manual", "model": GATEWAY, "audio": "silent"}, duration=4100)
        self.assertEqual((quote["billedSeconds"], quote["estimatedUsdMicro"]), (6, 600_000))
        self.assertEqual(quote["outputProfile"]["hasAudio"], False)
        self.assertTrue(quote["pricingVersion"])
        self.assertEqual(quote["priceItems"], [{"component":"native_video", "unit":"output_second",
                                                "quantity":6, "rateUsdMicro":100000, "perUnits":1}])
        # Synthetic rate card for metering units; these components are not asserted as available provider features.
        lines = [PriceLine("caption", "input_token", 1, 200_000, 1_000_000),
                 PriceLine("voice", "output_millisecond", 4, 200, 1000),
                 PriceLine("upscale", "output_frame", 5, 3), PriceLine("variation", "candidate", 2, 100_000)]
        self.assertEqual(metered_total(lines), 200016)
        with self.assertRaises(ValueError):
            metered_total([PriceLine("unsafe","input_token",-1,10)])
        with self.assertRaises(AlphaError):
            route({"estimatedUsdMicro": 1})

    def test_direction_changes_and_utf16_limit_checked_before_submission(self):
        ordinary = route({"mode": "manual", "model": GEN4})
        directed = route({"mode": "manual", "model": GEN4, "creativeFreedom": "low", "brandConsistency": "high"})
        self.assertNotEqual(engine.apply_direction("A green bag.", ordinary), engine.apply_direction("A green bag.", directed))
        with self.assertRaises(AlphaError):
            engine.apply_direction("🍎" * 501, ordinary)

    def test_configuration_is_not_health_measurement_and_removal_allows_poll_only(self):
        catalog = engine.model_catalog({})
        self.assertFalse(any(item["available"] for item in catalog if item["mediaKind"] == "generated"))
        self.assertTrue(next(item for item in catalog if item["id"] == BOARD)["available"])
        enabled = {item["id"] for item in engine.model_catalog(CONFIG) if item["available"]}
        self.assertEqual(enabled, {BOARD, GEN4, GATEWAY})
        self.assertNotIn("fixture", str(engine.model_catalog(CONFIG)))
        paused = {**CONFIG, "RAFII_CREATIVE_VIDEO_PROVIDERS": ""}
        with self.assertRaises(AlphaError):
            engine.adapter_for(GEN4, paused)
        reader = engine.adapter_for(GEN4, paused, for_recovery=True)
        with self.assertRaises(AlphaError):
            reader.submit(prompt="A bag.", duration_ms=4000, aspect_ratio="9:16", strategy=route({"mode":"manual","model":GEN4}))
        self.assertFalse(next(x for x in engine.model_catalog({**CONFIG, "VERCEL_ENV": "preview"})
                              if x["id"] == GEN4)["available"])

    def test_missing_output_tools_close_new_admission_and_preserve_same_operation_recovery(self):
        config = {**CONFIG, "RAFII_CREATIVE_VIDEO_PROVIDERS": "runway,vertex-veo",
                  "RAFII_CREATIVE_VIDEO_AUTH": "attached-service-account", "RAFII_CREATIVE_VIDEO_PROJECT": "fixture-123"}
        real_which = health.shutil.which
        for missing in ("ffprobe", "ffmpeg"):
            with self.subTest(missing=missing), patch.object(health.shutil, "which",
                    side_effect=lambda name: None if name == missing else real_which(name)):
                self.assertFalse(any(row["available"] for row in engine.model_catalog(config)))
                for model in (GEN4, GATEWAY, VERTEX):
                    with self.assertRaisesRegex(ProviderError, "decode and verify"):
                        engine.adapter_for(model, config)
                    self.assertFalse(engine.adapter_for(model, config, for_recovery=True).may_submit)
                reader = engine.adapter_for(GEN4, config, for_recovery=True)
                with patch.object(reader, "transport", return_value=(200, {"id": HANDLE, "status": "RUNNING"})) as send:
                    self.assertEqual(reader.poll(HANDLE)["state"], "pending")
                    self.assertEqual(send.call_count, 1)

    def test_decoder_capability_is_exercised_and_cached_even_when_binaries_exist(self):
        health._decode_probe.cache_clear()
        self.addCleanup(health._decode_probe.cache_clear)
        with patch.object(health.media, "_cmd", wraps=health.media._cmd) as command:
            self.assertTrue(health.output_decoder_ready())
            self.assertEqual([call.args[0] for call in command.call_args_list], ["ffprobe", "ffmpeg"])
            self.assertTrue(health.output_decoder_ready())
            self.assertEqual(command.call_count, 2)
        health._decode_probe.cache_clear()
        with patch.object(health.media, "_cmd", side_effect=AlphaError("Incompatible tool", 422)):
            self.assertFalse(health.output_decoder_ready())
            with self.assertRaisesRegex(ProviderError, "decode and verify"):
                engine.adapter_for(GEN4, CONFIG)

    def test_observed_performance_is_scoped_comparable_and_not_in_pinned_billing(self):
        cursor = MagicMock()
        rows = [(model, "720p", "silent", "9:16", "4", "completed", None, answer, timing, False)
                for model, answer, timing in ((GEN4, "true", 25), (VERTEX, "false", 70)) for _ in range(5)]
        rows += [(GEN4, "720p", "silent", "9:16", "4", "failed", "authorization_changed", None, None, False)]
        rows += [(VERTEX, "720p", "silent", "9:16", "4", "completed", None, "true", 95, True)] * 5
        cursor.fetchall.return_value = rows
        observations = engine.workspace_observations(cursor, "fictional-workspace")
        self.assertEqual(cursor.execute.call_args.args[1], ("fictional-workspace",))
        self.assertIn("workspace_id=%s", cursor.execute.call_args.args[0])
        models = [{"id": model, "available":True} for model in (GEN4, VERTEX)]
        settings = {"level":"professional", "audio":"silent", "speed":"fast"}
        no_evidence = route(settings, duration=3500, available=models)
        self.assertEqual(no_evidence["model"], VERTEX)
        catalog = engine.apply_observations(models, observations)
        chosen = route(settings, duration=3500, available=catalog)
        self.assertEqual(chosen["model"], GEN4)
        self.assertEqual(engine.observed_latency(catalog, chosen), 25)
        conditioned = route({**settings, "firstFrameConsent":True, "firstFrameAssetId":"a"*32}, duration=3500, available=catalog)
        self.assertEqual(engine.observed_latency(catalog, conditioned), 95)
        self.assertNotIn("workspaceObservations", chosen)
        self.assertIsNone(engine.observed_latency(models, chosen))
        cursor.fetchall.return_value = rows[:4]
        self.assertEqual(engine.workspace_observations(cursor, "fictional-workspace").get(GEN4), {})

    def test_strict_technical_rejects_blank_or_silent_contract_with_no_semantic_score(self):
        sample = {"scenes":[{"measurements":{"meanLuma":.45,"audioRms":0.0}}]}
        engine.validate_quality_observations(sample, {"hasAudio":True})
        with self.assertRaises(AlphaError):
            engine.validate_quality_observations(sample, {"hasAudio":True, "strictQuality":True})
        engine.validate_quality_observations(sample, {"hasAudio":False, "strictQuality":True})
        sample["scenes"][0]["measurements"]["meanLuma"] = .995
        with self.assertRaises(AlphaError):
            engine.validate_quality_observations(sample, {"hasAudio":False,"strictQuality":True})


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = engine.adapter_for(GEN4, CONFIG)
        self.strategy = route({"mode": "manual", "model": GEN4})

    def test_direct_and_gateway_send_only_the_supported_fields(self):
        for model in (GEN4, GATEWAY):
            provider = engine.adapter_for(model, CONFIG)
            with patch.object(provider, "transport", return_value=(200, {"id": HANDLE})) as transport:
                strategy = route({"mode":"manual", "model":model})
                self.assertEqual(provider.submit(prompt="Camera follows the bag.", duration_ms=3500, aspect_ratio="9:16",
                                                 strategy=strategy), HANDLE)
                method, path, body, _ = transport.call_args.args
                self.assertEqual((method, path, body["ratio"]), ("POST", "/v1/text_to_video", "720:1280"))
                self.assertEqual(set(body), {"model","ratio","duration","promptText"} | ({"audio"} if model == GATEWAY else set()))

    def test_timeout_never_retries_and_wrong_operation_never_makes_a_request(self):
        with patch.object(self.adapter, "transport", side_effect=TimeoutError) as send:
            with self.assertRaises(ProviderError) as err:
                self.adapter.submit(prompt="A take.", duration_ms=3500, aspect_ratio="9:16", strategy=self.strategy)
            self.assertTrue(err.exception.uncertain)
            with self.assertRaises(AlphaError):
                self.adapter.poll("unknown")
            self.assertEqual(send.call_count, 1)

    def test_https_transport_uses_fixed_origin_direct_token_and_bounded_credential_free_download(self):
        def response(status, mime, payload):
            http_response = MagicMock()
            http_response.status = status
            headers = {"Content-Type":mime, "Content-Length":str(len(payload))}
            http_response.getheader.side_effect = lambda name, default=None: headers.get(name, default)
            http_response.read1.side_effect = io.BytesIO(payload).read1
            return http_response

        with patch.object(runway.http.client, "HTTPSConnection") as connection:
            transport = connection.return_value
            transport.getresponse.return_value = response(200, "application/json", json.dumps({"id":HANDLE}).encode())
            self.adapter.submit(prompt="An original shot.", duration_ms=3500, aspect_ratio="9:16", strategy=self.strategy)
            self.assertEqual(connection.call_args.args, (runway.API_HOST,))
            self.assertEqual(transport.request.call_args.kwargs["headers"]["X-Runway-Version"], "2024-11-06")
            self.assertIn("Authorization", transport.request.call_args.kwargs["headers"])
            payload = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
            transport.getresponse.return_value = response(200,"video/mp4",payload)
            self.assertEqual(runway._download("/result.mp4"),payload)
            self.assertEqual(connection.call_args.args,(runway.ASSET_HOST,))
            self.assertNotIn("Authorization", transport.request.call_args.kwargs["headers"])
            transport.getresponse.return_value = response(302,"text/plain",b"")
            calls_before = connection.call_count
            with self.assertRaises(OSError):
                runway._download("/result.mp4")
            self.assertEqual(connection.call_count,calls_before+1)
            transport.getresponse.return_value = response(200,"text/html",b"wrong format")
            with self.assertRaises(ProviderError) as error:
                runway._download("/result.mp4")
            self.assertEqual(error.exception.code,"creative_video_provider_output_invalid")

    def test_cancel_ack_and_terminal_cost_do_not_infer_zero(self):
        with patch.object(self.adapter, "transport", return_value=(204, {})):
            result = self.adapter.cancel(HANDLE)
            self.assertEqual(result["state"], "pending")
            self.assertIsNone(result["costUsdMicro"])
        for credits, expected in ((0,0),(12,120_000),(None,None),(-1,None),(True,None)):
            with patch.object(self.adapter, "transport", return_value=(200,{"id":HANDLE, "status":"CANCELLED","cost":{"credits":credits}})):
                result = self.adapter.poll(HANDLE, verified_unit_usd_micro=10_000)
                self.assertEqual(result["state"], "cancelled")
                self.assertEqual(result["costUsdMicro"], expected)
        with patch.object(self.adapter, "transport", return_value=(200, {"id":HANDLE,"status":"CANCELED","cost":{"credits":48}})):
            result = self.adapter.poll(HANDLE)
            self.assertEqual((result["state"], result["providerCredits"], result["costUsdMicro"]), ("cancelled",48,None))
        catalog = engine.model_catalog({**CONFIG, "RAFII_CREATIVE_VIDEO_RUNWAY_VERIFIED_UNIT_USD_MICRO": "9600"})
        quote = route({"mode":"manual", "model":GEN4}, available=catalog)
        self.assertEqual(quote["verifiedProviderUnitUsdMicro"], 9600)

    def test_retrieval_only_from_documented_distribution_and_never_logs_signed_urls(self):
        for url in ("https://localhost/asset", "https://other.cloudfront.net/asset",
                    "https://dnznrvs05pmza.cloudfront.net:443/a", "https://user@dnznrvs05pmza.cloudfront.net/a"):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                asset_request_path(url)
        signed = "https://dnznrvs05pmza.cloudfront.net/output.mp4?sig=x"
        self.assertEqual(asset_request_path(signed), "/output.mp4?sig=x")
        for outputs in ([], ["https://unapproved.invalid/file"]):
            with patch.object(self.adapter,"transport",return_value=(200,{"id":HANDLE,"status":"SUCCEEDED","output":outputs,
                              "cost":{"credits":48}})), patch.object(self.adapter,"download") as download:
                outcome = self.adapter.poll(HANDLE, verified_unit_usd_micro=10_000)
                self.assertEqual((outcome["state"],outcome["reason"],outcome["providerCredits"],outcome["costUsdMicro"]),
                                 ("failed","provider_output_unusable",48,480000))
                download.assert_not_called()
        with patch.object(self.adapter,"transport",return_value=(200,{"id":HANDLE,"status":"SUCCEEDED","output":[signed]})), \
             patch.object(self.adapter,"download", side_effect=OSError("sig=x")):
            with self.assertRaises(ProviderError) as err:
                self.adapter.poll(HANDLE)
            self.assertNotIn("sig=x", str(err.exception))
            self.assertTrue(err.exception.uncertain)

    def test_storyboard_is_actual_decodable_original_motion_without_provider_credentials(self):
        strategy = route({"level":"draft"}, duration=1000, available={BOARD}, ratio="1:1")
        provider = engine.adapter_for(BOARD,{})
        prompt = "Show the teal case opening on a sunlit desk."
        handle = provider.submit(prompt=prompt, duration_ms=1000, aspect_ratio="1:1", strategy=strategy)
        result = provider.poll(handle, prompt=prompt, strategy=strategy)
        checked = validate_generated_clip(result["video"], strategy["outputProfile"])
        self.assertEqual((checked["width"], checked["height"], checked["fps"], checked["hasAudio"]), (720,720,24,False))
        self.assertEqual((result["costUsdMicro"], result["state"]), (0,"completed"))
        with self.assertRaises(AlphaError):
            provider.poll(handle, prompt="Different authorized shot", strategy=strategy)

    def test_vertex_workload_token_is_lazy_scoped_bounded_and_never_displayed(self):
        config = {"RAFII_CREATIVE_VIDEO_PROVIDER":"vertex-veo","RAFII_CREATIVE_VIDEO_PROJECT":"fixture-project",
                  "RAFII_CREATIVE_VIDEO_AUTH":"attached-service-account"}
        with patch.object(vertex.http.client,"HTTPConnection") as connection:
            adapter = engine.adapter_for(VERTEX, config)
            self.assertTrue(next(v for v in engine.model_catalog(config) if v["id"] == VERTEX)["available"])
            connection.assert_not_called()
            resp = connection.return_value.getresponse.return_value
            resp.status = 200
            resp.getheader.side_effect = {"Metadata-Flavor":"Google","Content-Type":"application/json","Content-Length":None}.get
            raw = json.dumps({"access_token":"fictional-workload-secret","token_type":"Bearer","expires_in":900}).encode()
            resp.read1.side_effect = io.BytesIO(raw).read1
            with patch.object(adapter, "transport", return_value=(200, {"name": adapter.model_path + "/operations/test"})) as send:
                adapter.submit(prompt="An original shot", duration_ms=4000, aspect_ratio="9:16")
                self.assertEqual(send.call_args.args[2], "fictional-workload-secret")
            self.assertEqual(connection.call_args.args, ("metadata.google.internal",))
            self.assertEqual(connection.return_value.request.call_args.args, ("GET", "/computeMetadata/v1/instance/service-accounts/default/token"))
            resp.status = 302
            with patch.object(adapter, "transport") as send, self.assertRaises(ProviderError) as denied:
                adapter.submit(prompt="An original shot", duration_ms=4000, aspect_ratio="9:16")
            self.assertFalse(denied.exception.uncertain)
            self.assertNotIn("fictional", str(denied.exception))
            send.assert_not_called()
        with self.assertRaises(ProviderError):
            engine.adapter_for(VERTEX, {**config, "RAFII_CREATIVE_VIDEO_ACCESS_TOKEN": "other-source"})

    def test_passive_hold_tracks_real_status_and_keeps_recovery_and_other_routes_available(self):
        now = [10.0]
        health = WorkerHealth(lambda: now[0])
        with patch.object(engine,"worker_health",health), patch("postriff_phase2.creative_video_runway.worker_health",health):
            provider = engine.adapter_for(GEN4,CONFIG)
            with patch.object(provider,"transport",return_value=(429,{})), self.assertRaises(ProviderError):
                provider.submit(prompt="A scene.",duration_ms=3500,aspect_ratio="9:16",strategy=self.strategy)
            rows = {m["id"]:m for m in engine.model_catalog(CONFIG)}
            self.assertFalse(rows[GEN4]["available"])
            self.assertEqual(rows[GEN4]["health"],"temporary_hold")
            self.assertTrue(rows[BOARD]["available"])
            recovery = engine.adapter_for(GEN4,CONFIG,for_recovery=True)
            with patch.object(recovery,"transport",return_value=(200,{"id":HANDLE,"status":"RUNNING"})):
                self.assertEqual(recovery.poll(HANDLE)["state"],"pending")
            self.assertFalse(next(m["available"] for m in engine.model_catalog(CONFIG) if m["id"] == GEN4))
            now[0] += 31
            self.assertTrue(next(m["available"] for m in engine.model_catalog(CONFIG) if m["id"] == GEN4))
