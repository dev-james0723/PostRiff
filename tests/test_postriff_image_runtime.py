import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.image_runtime import DEFAULT_ENDPOINT, GatewayImageRuntime, ImageGenerationError, from_environment
from postriff_phase2.ideas import IdeasService


PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image"


class Recording:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


class GatewayImageRuntimeTests(unittest.TestCase):
    def test_generates_bounded_base64_image_and_reports_progress(self):
        transport = Recording({"status": 200, "body": {"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": 0.03}}})
        events = []
        result = GatewayImageRuntime("secret", transport=transport).generate("A red piano on cream paper", emit=events.append)

        self.assertEqual(result["images"], [PNG])
        self.assertEqual(result["usage"]["costUsd"], 0.03)
        self.assertEqual([event["percent"] for event in events], [25, 75])
        call = transport.calls[0]
        self.assertEqual((call["method"], call["url"]), ("POST", DEFAULT_ENDPOINT))
        self.assertEqual(call["body"]["response_format"], "b64_json")
        self.assertEqual(call["body"]["n"], 1)

    def test_url_only_or_malformed_results_fail_without_remote_fetch(self):
        runtime = GatewayImageRuntime("secret", transport=Recording({"status": 200, "body": {"data": [{"url": "https://example.invalid/image.png"}]}}))
        with self.assertRaises(ImageGenerationError) as raised:
            runtime.generate("A safe prompt")
        self.assertTrue(raised.exception.uncertain)

    def test_environment_and_catalog_keep_media_separate_from_writer(self):
        image = from_environment({"AI_GATEWAY_API_KEY": "secret", "POSTRIFF_IMAGE_MODEL": "openai/gpt-image-2.5-flare", "POSTRIFF_IMAGE_ESTIMATE_USD_MICRO": "90000"})
        service = IdeasService(None, None, runtimes=[FixtureAgentRuntime()], image_runtime=image, assets=object(), researcher=False)
        catalog = service.model_catalog()

        self.assertTrue(catalog["imageGeneration"]["available"])
        self.assertTrue(catalog["imageGeneration"]["independentOfWritingModel"])
        self.assertEqual(catalog["models"][0]["id"], "deterministic-preview")
        self.assertEqual(image.estimate_usd_micro, 90000)

    def test_invalid_generation_shape_and_count_fail_closed(self):
        runtime = GatewayImageRuntime("secret", transport=Recording({"status": 200, "body": {}}))
        with self.assertRaises(AlphaError):
            runtime.generate("A safe prompt", count=2)
        with self.assertRaises(ImageGenerationError):
            runtime.generate("A safe prompt")


if __name__ == "__main__":
    unittest.main()
