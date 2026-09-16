import base64
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_storage import PrivateAssetService

PREFLIGHT_SPEC = importlib.util.spec_from_file_location("postriff_hosted_preflight", ROOT / "scripts/check_postriff_hosted_preflight.py")
PREFLIGHT = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(PREFLIGHT)
validate_environment = PREFLIGHT.validate_environment
validate_structure = PREFLIGHT.validate_structure


class HostedDeploymentPreparationTests(unittest.TestCase):
    def test_vercel_entrypoint_exports_wsgi_app(self):
        spec = importlib.util.spec_from_file_location("postriff_vercel_entrypoint", ROOT / "api/index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIsInstance(module.app, HostedApplication)

    def test_structure_preflight_passes_and_keeps_external_choices_pending(self):
        results = validate_structure(ROOT)
        by_name = {item["name"]: item["status"] for item in results}
        self.assertNotIn("fail", by_name.values())
        self.assertEqual(by_name["vercel-services-routing"], "pass")
        self.assertEqual(by_name["source-upload-boundary"], "pass")
        self.assertEqual(by_name["production-cron-candidate"], "pass")

    def test_environment_preflight_accepts_transaction_pooler_without_disclosure(self):
        values = {
            "POSTRIFF_DATABASE_URL": "postgresql://user:encoded@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require",
            "POSTRIFF_SUPABASE_URL": "https://project.supabase.co",
            "POSTRIFF_SUPABASE_PUBLISHABLE_KEY": "p" * 32,
            "POSTRIFF_SUPABASE_SECRET_KEY": "s" * 32,
            "CRON_SECRET": "c" * 32,
        }
        results = validate_environment(values)
        self.assertTrue(all(item["status"] == "pass" for item in results))
        rendered = json.dumps(results)
        self.assertNotIn(values["POSTRIFF_DATABASE_URL"], rendered)
        self.assertNotIn(values["POSTRIFF_SUPABASE_SECRET_KEY"], rendered)

    def test_hosted_asset_service_requires_pillow_decoder(self):
        class Storage:
            def put_immutable(self, *_args):
                return "saved"

        malformed = {"data": base64.b64encode(b"\x89PNG\r\n\x1a\ninvalid").decode()}
        with self.assertRaises(Exception) as raised:
            PrivateAssetService(Storage()).stage_upload("00000000-0000-0000-0000-000000000010", malformed)
        self.assertNotIn("ffmpeg", str(raised.exception).lower())

    def test_hosted_asset_service_decodes_and_strips_bytes_before_storage(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pinned hosted Pillow dependency is not installed in this interpreter")

        class Storage:
            def __init__(self):
                self.raw = None

            def put_immutable(self, _workspace_id, _category, _object_name, raw, _content_type="image/jpeg"):
                self.raw = raw
                return "workspace/media/object.jpg"

        source = io.BytesIO()
        Image.new("RGBA", (640, 480), (20, 90, 160, 128)).save(source, "PNG")
        storage = Storage()
        asset = PrivateAssetService(storage).stage_upload(
            "00000000-0000-0000-0000-000000000010",
            {"data": base64.b64encode(source.getvalue()).decode()},
        )
        self.assertEqual((asset["processing"], asset["decoder"]), ("decoded", "pillow"))
        self.assertNotIn("data", asset)
        self.assertTrue(storage.raw.startswith(b"\xff\xd8\xff"))


if __name__ == "__main__":
    unittest.main()
