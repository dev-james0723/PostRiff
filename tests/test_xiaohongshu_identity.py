import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from james_au_social.studio import StudioError
from james_au_social.studio_connections import XiaohongshuBrowserIdentity
from james_au_social.xiaohongshu_mcp import XiaohongshuMcpSupervisor


class XiaohongshuBrowserIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = XiaohongshuBrowserIdentity(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_then_creator_centre_connects_without_publish_authority(self):
        observed = self.store.observe_profile(
            'https://www.rednote.com/user/profile/6aa748a9000000000301c840',
            '小红薯6AA7E810', '94556602041')
        self.assertEqual(observed['state'], 'browser_profile_observed')
        self.assertFalse(observed['publishReady'])
        connected = self.store.confirm_creator_centre('94556602041')
        self.assertEqual(connected['state'], 'identity_connected')
        self.assertEqual(connected['identitySignals'][-1], 'owner_confirmed_creator_centre_rednote_id')
        self.assertFalse(connected['publishing'])

    def test_rejects_non_profile_urls_and_mismatched_creator_identity(self):
        with self.assertRaises(StudioError):
            self.store.observe_profile('https://creator.rednote.com/login', 'name', '94556602041')
        self.store.observe_profile('https://www.rednote.com/user/profile/6aa748a9000000000301c840', 'name', '94556602041')
        with self.assertRaises(StudioError):
            self.store.confirm_creator_centre('94556602042')


class XiaohongshuMcpSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.supervisor = XiaohongshuMcpSupervisor(Path(self.temp.name))
        self.supervisor._ensure_private_directories()
        self.supervisor.server_binary.write_bytes(b'server fixture')
        self.supervisor.login_binary.write_bytes(b'login fixture')
        self.supervisor.server_binary.chmod(0o700)
        self.supervisor.login_binary.chmod(0o700)
        self.supervisor.SERVER_SHA256 = hashlib.sha256(b'server fixture').hexdigest()
        self.supervisor.LOGIN_SHA256 = hashlib.sha256(b'login fixture').hexdigest()

    def tearDown(self):
        self.supervisor.shutdown()
        self.temp.cleanup()

    def test_status_exposes_capabilities_without_secret_material(self):
        with patch.object(self.supervisor, '_keychain_token', return_value='a' * 64):
            status = self.supervisor.status()
        self.assertTrue(status['driverInstalled'])
        self.assertTrue(status['serviceAuthenticated'])
        self.assertTrue(status['sessionOpaque'])
        self.assertTrue(status['mutationsLocked'])
        self.assertEqual(status['routeDriver'], 'local_mcp_browser_rednote')
        self.assertEqual(self.supervisor.cookies_path.name, 'cookies-rednote.json')
        self.assertIn('publish_image_note', status['allowedOperations'])
        self.assertNotIn('token', status)
        self.assertNotIn('cookiesPath', status)

    def test_identity_verification_persists_only_bounded_public_signals(self):
        with (patch.object(self.supervisor, '_session_stored', return_value=True),
              patch.object(self.supervisor, '_running', return_value=True),
              patch.object(self.supervisor, '_request', side_effect=[
                  {'success': True, 'data': {'is_logged_in': True}},
                  {'success': True, 'data': {'data': {'userBasicInfo': {
                      'redId': '94556602041', 'nickname': '小红薯6AA7E810'},
                      'feeds': [{'xsecToken': 'synthetic-secret'}]}}},
              ])):
            record = self.supervisor.verify_identity(
                expected_rednote_id='94556602041', expected_nickname='小红薯6AA7E810')
        self.assertEqual(record['state'], 'authenticated_route_test_required')
        saved = self.supervisor.route_record.read_text(encoding='utf-8')
        self.assertNotIn('synthetic-secret', saved)
        self.assertNotIn('xsec', saved.lower())
        self.assertEqual(self.supervisor.route_record.stat().st_mode & 0o777, 0o600)

    def test_container_request_keeps_bearer_token_out_of_process_arguments(self):
        response = json.dumps({'success': True, 'data': {'is_logged_in': False}})
        completed = subprocess.CompletedProcess([], 0, stdout=response, stderr='')
        with (patch.object(self.supervisor, '_container_running', return_value=True),
              patch.object(self.supervisor, '_keychain_token', return_value='a' * 64),
              patch('james_au_social.xiaohongshu_mcp.subprocess.run', return_value=completed) as run):
            value = self.supervisor._container_request('/api/v1/login/status')
        argv = ' '.join(run.call_args.args[0])
        self.assertNotIn('a' * 64, argv)
        self.assertIn('Authorization: Bearer ' + ('a' * 64), run.call_args.kwargs['input'])
        self.assertFalse(value['data']['is_logged_in'])

    def test_container_qr_handoff_returns_only_bounded_image_data(self):
        qr = 'data:image/png;base64,iVBORw0KGgo='
        with (patch.object(self.supervisor, '_container_installed', return_value=True),
              patch.object(self.supervisor, '_container_running', return_value=True),
              patch.object(self.supervisor, '_container_app_running', return_value=True),
              patch.object(self.supervisor, '_request', return_value={
                  'success': True,
                  'data': {'timeout': '4m0s', 'is_logged_in': False, 'img': qr},
              })):
            result = self.supervisor.begin_private_login()
        self.assertEqual(result['state'], 'private_handoff')
        self.assertEqual(result['qrImage'], qr)
        self.assertEqual(result['expiresInSeconds'], 240)
        self.assertFalse(result['publishing'])

    def test_container_fallback_clears_native_blocker_from_active_status(self):
        self.supervisor.blocker_record.write_text('{}', encoding='utf-8')
        with (patch.object(self.supervisor, '_container_installed', return_value=True),
              patch.object(self.supervisor, '_container_running', return_value=True),
              patch.object(self.supervisor, '_container_app_running', return_value=True),
              patch.object(self.supervisor, '_container_session_stored', return_value=False),
              patch.object(self.supervisor, '_keychain_token', return_value='a' * 64)):
            status = self.supervisor.status()
        self.assertTrue(status['driverInstalled'])
        self.assertTrue(status['driverRunning'])
        self.assertEqual(status['executionMode'], 'isolated_container')
        self.assertEqual(status['serviceBoundary'], 'docker_socket_and_bearer')
        self.assertFalse(status['driverBlocked'])
        self.assertEqual(status['nativeBlockerCode'], 'browser_runtime_integrity_failure')
