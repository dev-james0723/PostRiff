"""Focused local-preview safety checks. No database, server or provider is started."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('rafii_admin_preview', ROOT / 'scripts/rafii_admin_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewLauncherTests(unittest.TestCase):
    def test_provider_database_and_identity_environment_is_removed(self):
        values = {'PATH': '/synthetic/path', 'HOME': '/synthetic/home', 'OPENAI_API_KEY': 'never-forward', 'POSTRIFF_DATABASE_URL': 'never-forward', 'PGHOST': 'remote.invalid', 'PGSERVICE': 'production', 'AWS_ACCESS_KEY_ID': 'never-forward', 'SUPABASE_SERVICE_ROLE_KEY': 'never-forward', 'NEXT_PUBLIC_CONTROL_SUPABASE_URL': 'https://remote.invalid', 'RAFII_CONTROL_SESSION_DSN': 'never-forward', 'NODE_OPTIONS': '--require injected.js', 'PYTHONPATH': '/unsafe', 'LD_PRELOAD': '/unsafe', 'NEXT_TELEMETRY_DISABLED': '0'}
        env = preview.safe_environment(values)
        self.assertEqual(env['PATH'], values['PATH'])
        self.assertEqual(env['HOME'], values['HOME'])
        self.assertEqual(env['POSTRIFF_RESEARCH'], '0')
        self.assertEqual(env['NEXT_TELEMETRY_DISABLED'], '1')
        for key in values.keys() - preview.SAFE_ENVIRONMENT:
            if key != 'NEXT_TELEMETRY_DISABLED':
                self.assertNotIn(key, env)

    def test_deployment_environment_is_rejected_before_sanitizing(self):
        for key in ('VERCEL', 'VERCEL_ENV'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                preview.safe_environment({key: 'preview'})

    def test_runtime_uses_distinct_loopback_services_and_server_only_identity(self):
        api, web = preview.runtime_environment(preview.safe_environment({}), web_port=4649, api_port=4650, pg_port=5651)
        self.assertEqual(api['RAFII_CONTROL_TEST_DSN'], 'host=127.0.0.1 port=5651 dbname=postgres')
        self.assertEqual(web['RAFII_CONTROL_ORIGIN'], 'http://localhost:4649')
        self.assertEqual(web['RAFII_CONTROL_LOCAL_API'], 'http://127.0.0.1:4650')
        self.assertEqual(web['RAFII_CONTROL_LOCAL_PREVIEW'], '1')
        self.assertNotIn('RAFII_CONTROL_TEST_DSN', web)
        self.assertNotIn('RAFII_CONTROL_LOCAL_PREVIEW_TOKEN', api)
        for ports in ((1, 1, 2), (0, 1, 2), (1, 2, 65536)):
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                preview.runtime_environment({}, web_port=ports[0], api_port=ports[1], pg_port=ports[2])

    def test_occupied_or_excluded_port_is_not_reused(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            self.assertNotEqual(preview.free_port(port), port)
            self.assertNotEqual(preview.free_port(port, excluded=frozenset({port})), port)
        with self.assertRaises(ValueError):
            preview.free_port(-1)

    def test_automatic_next_environment_files_are_refused(self):
        with tempfile.TemporaryDirectory(prefix='rafii-preview-gate-test-') as directory:
            root = Path(directory)
            required = [root / 'python', root / 'node', *[root / 'pg' / name for name in ('initdb', 'pg_ctl', 'psql')], root / 'control-web/node_modules/next/dist/bin/next', root / 'control-web/.next/BUILD_ID', root / 'tests/control/serve.py', *[root / file for file in preview.MIGRATIONS]]
            for file in required:
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            with patch.object(preview, 'ROOT', root):
                preview.prerequisites(root / 'python', root / 'pg', root / 'node')
                (root / 'control-web/.env.production').touch()
                with self.assertRaisesRegex(ValueError, 'environment files'):
                    preview.prerequisites(root / 'python', root / 'pg', root / 'node')

    @unittest.skipUnless(preview.NODE.is_file(), 'Node 24 unavailable')
    def test_demo_access_gate_denies_remote_host_missing_flag_and_deployment(self):
        module = (ROOT / 'control-web/app/demo-access/access-gate.mjs').as_uri()
        script = '''import {localDemoAccessAllowed as gate} from MODULE;
const env={RAFII_CONTROL_ENABLED:'1',RAFII_CONTROL_ENVIRONMENT:'local',RAFII_CONTROL_LOCAL_PREVIEW:'1',RAFII_CONTROL_ORIGIN:'http://localhost:4649',RAFII_CONTROL_LOCAL_PREVIEW_TOKEN:'local-only-simulation'};
const checks=[gate('localhost:4649',env),gate('localhost:4649',{...env,RAFII_CONTROL_LOCAL_PREVIEW:'0'}),gate('localhost:4649',{...env,VERCEL:'1'}),gate('localhost:4649',{...env,VERCEL_ENV:'preview'}),gate('localhost:4649',{...env,RAFII_CONTROL_ENVIRONMENT:'staging'}),gate('localhost:4649',{...env,RAFII_CONTROL_LOCAL_PREVIEW_TOKEN:''}),gate('localhost:4649',{...env,RAFII_CONTROL_ENABLED:'0'}),gate('evil.localhost:4649',env),gate('ops.example.test',{...env,RAFII_CONTROL_ORIGIN:'https://ops.example.test'}),gate('127.0.0.1:4649',env),gate('localhost:4649',{...env,RAFII_CONTROL_ORIGIN:'http://localhost:4649/path'}),gate('localhost:4649',{...env,RAFII_CONTROL_ORIGIN:'http://user@localhost:4649'}),gate('localhost:4649',{...env,RAFII_CONTROL_ORIGIN:'http://localhost:4649?x=1'})];console.log(JSON.stringify(checks));'''.replace('MODULE', json.dumps(module))
        result = subprocess.run([str(preview.NODE), '--input-type=module', '-e', script], check=True, text=True, capture_output=True, env=preview.safe_environment(dict(os.environ)))
        self.assertEqual(json.loads(result.stdout), [True] + [False] * 12)

    def test_synthetic_identity_is_not_literal_in_browser_or_server_page(self):
        for file in (ROOT / 'control-web/app/demo-access').iterdir():
            self.assertNotIn('synthetic-founder-aal2', file.read_text(), str(file))

    def test_cleanup_targets_only_owned_children(self):
        from unittest.mock import Mock
        running = Mock()
        running.poll.return_value = None
        stopped = Mock()
        stopped.poll.return_value = 0
        preview.stop_children([running, stopped])
        running.terminate.assert_called_once_with()
        stopped.terminate.assert_not_called()
        running.kill.assert_not_called()
        running.wait.assert_called_once_with(timeout=10)
        stopped.wait.assert_called_once_with(timeout=10)


if __name__ == '__main__':
    unittest.main()
