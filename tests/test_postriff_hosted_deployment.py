import base64
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_storage import PrivateAssetService
from postriff_phase2.phone.asgi import create_lazy_app
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
        self.assertEqual(by_name["phone-media-duration"], "pass")

    def test_media_entrypoint_import_and_disabled_upgrade_need_no_credentials(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            'postriff_phase2.hosted_app.runtime_from_environment',
            side_effect=AssertionError('Disabled media must not initialize the runtime'),
        ) as runtime:
            spec = importlib.util.spec_from_file_location('postriff_vercel_phone', ROOT / 'api/phone.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertIsInstance(module.app, Starlette)
            with TestClient(module.app) as client:
                self.assertEqual(client.get('/api/workspaces/private').status_code, 404)
                with self.assertRaises(WebSocketDisconnect) as error:
                    with client.websocket_connect('/api/phone/media/private'):
                        self.fail('Phone kill switch accepted an upgrade')
                self.assertEqual(error.exception.code, 1008)
            runtime.assert_not_called()

    def test_media_lazy_host_reuses_runtime_and_rechecks_kill_switch(self):
        requests = []
        values = {'RAFII_PHONE_ENABLED': '1'}

        async def media(socket):
            await socket.accept()
            await socket.send_json({'callId': socket.path_params['call_id']})
            await socket.close()

        def initialize():
            requests.append('initialized')
            return Starlette(routes=[WebSocketRoute('/api/phone/media/{call_id}', media)])

        with TestClient(create_lazy_app(values=values, application_factory=initialize)) as client:
            self.assertEqual(requests, [])
            for call_id in ('one', 'two'):
                with client.websocket_connect('/api/phone/media/' + call_id) as socket:
                    self.assertEqual(socket.receive_json(), {'callId': call_id})
            self.assertEqual(requests, ['initialized'])
            values['RAFII_PHONE_ENABLED'] = '0'
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect('/api/phone/media/three'):
                    self.fail('Cached media ignored the kill switch')
            self.assertEqual(error.exception.code, 1008)
            self.assertEqual(client.get('/api/cron/worker').status_code, 404)

    def test_media_unavailable_runtime_refuses_upgrade_without_error_disclosure(self):
        def initialize():
            raise ValueError('private provider configuration')

        app = create_lazy_app(values={'RAFII_PHONE_ENABLED': '1'}, application_factory=initialize)
        with TestClient(app) as client, self.assertRaises(WebSocketDisconnect) as error:
            with client.websocket_connect('/api/phone/media/private'):
                self.fail('Unconfigured media accepted an upgrade')
        self.assertEqual(error.exception.code, 1008)
        self.assertNotIn('private provider', str(error.exception))

    def test_deployment_preflight_rejects_shadowed_media_short_timeout_and_private_bundle(self):
        original = json.loads((ROOT / 'vercel.json').read_text())
        for change, failed_check in (
            ('route', 'vercel-services-routing'),
            ('duration', 'phone-media-duration'),
            ('bundle', 'function-bundle-boundary'),
        ):
            value = json.loads(json.dumps(original))
            if change == 'route':
                value['rewrites'][0], value['rewrites'][1] = value['rewrites'][1], value['rewrites'][0]
            elif change == 'duration':
                value['services']['rafii_phone_media']['functions']['api/phone.py']['maxDuration'] = 300
            else:
                value['services']['rafii_phone_media']['functions']['api/phone.py']['excludeFiles'] = 'web/**'
            with self.subTest(change=change), patch.object(PREFLIGHT.json, 'loads', return_value=value):
                checks = {item['name']: item['status'] for item in validate_structure(ROOT)}
                self.assertEqual(checks[failed_check], 'fail')

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

    def test_environment_preflight_accepts_session_pooler_and_still_requires_tls(self):
        values = {
            'POSTRIFF_DATABASE_URL': 'postgresql://user:encoded@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require',
            'POSTRIFF_SUPABASE_URL': 'https://project.supabase.co',
            'POSTRIFF_SUPABASE_PUBLISHABLE_KEY': 'p' * 32,
            'POSTRIFF_SUPABASE_SECRET_KEY': 's' * 32,
            'CRON_SECRET': 'c' * 32,
        }
        self.assertTrue(all(item['status'] == 'pass' for item in validate_environment(values)))
        for dsn in (
            values['POSTRIFF_DATABASE_URL'].replace('?sslmode=require', ''),
            values['POSTRIFF_DATABASE_URL'].replace(':5432/', ':5433/'),
            values['POSTRIFF_DATABASE_URL'].replace('.pooler.supabase.com', '.example.com'),
        ):
            with self.subTest(dsn=dsn):
                checks = {item['name']: item['status'] for item in validate_environment({**values, 'POSTRIFF_DATABASE_URL': dsn})}
                self.assertEqual(checks['database-connection'], 'fail')

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
