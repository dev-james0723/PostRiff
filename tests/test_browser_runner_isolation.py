"""Local acceptance must never inherit credentials or silently use another API's build."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrowserIsolationTests(unittest.TestCase):
    def test_prepared_frontend_keeps_binding_guard_without_private_runtime_state(self):
        helper = load('consumer_ready_web')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'isolated/web'
            with patch.object(helper,'DEST',destination), patch.object(sys,'argv',['helper','--prepare']):
                self.assertEqual(helper.main(),0)
            self.assertTrue((destination.parent/'scripts/check_social_release_binding.py').is_file())
            self.assertEqual(sorted(p.name for p in (destination.parent/'src/postriff_phase2').iterdir()),
                             ['__init__.py','social_release.py'])
            child=helper.subprocess.run([sys.executable,str(destination.parent/'scripts/check_social_release_binding.py')],
                                       capture_output=True,text=True,env={'PATH':os.environ.get('PATH',''),'CI':'true'})
            self.assertEqual(child.returncode,0,child.stderr)
            self.assertFalse(json.loads(child.stdout)['productionBindingVerified'])
            self.assertFalse((destination.parent/'.vercel').exists())
            self.assertFalse(any(p.name.startswith('.env') for p in destination.iterdir()))

    def test_real_build_child_gets_only_local_binding_and_no_credentials(self):
        helper = load('consumer_ready_web')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            report = destination / 'child.json'
            child = "import json,os,sys;open(sys.argv[1],'w').write(json.dumps(dict(api=os.environ['POSTRIFF_API_ORIGIN'],web=os.environ['NEXT_PUBLIC_APP_URL'],credential='SUPABASE_SERVICE_ROLE_KEY' in os.environ)))"
            for ports, api, web in (([],4438,4439),(['--api-port','4838','--web-port','4839'],4838,4839)):
                with patch.object(helper,'DEST',destination), patch.object(sys,'argv',['helper',*ports,sys.executable,'-c',child,str(report)]), patch.dict(os.environ,{'SUPABASE_SERVICE_ROLE_KEY':'fictional-test-sentinel'}):
                    self.assertEqual(helper.main(),0)
                self.assertEqual(json.loads(report.read_text()),dict(api=f'http://127.0.0.1:{api}',web=f'http://127.0.0.1:{web}',credential=False))

    def test_mismatched_compiled_rewrite_refuses_before_any_process_starts(self):
        runner = load('consumer_ready_browser')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / '.codex/consumer-ready/web/.next/routes-manifest.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(rewrites={'afterFiles':[dict(source=route,destination='http://127.0.0.1:4438'+route) for route in ('/api/:path*','/dev/:path*')]})))
            with patch.object(runner,'ROOT',root), patch.object(sys,'argv',['runner','--founder','--api-port','4838','--web-port','4839','--pg-port','55489']), patch.object(runner.subprocess,'Popen') as spawn:
                self.assertEqual(runner.main(),3)
                spawn.assert_not_called()

    def test_invalid_port_cannot_become_an_external_build_origin(self):
        helper = load('consumer_ready_web')
        for args in (['--api-port','https://example.invalid'],['--api-port','0'],['--api-port','4839','--web-port','4839']):
            with self.subTest(args=args), patch.object(sys,'argv',['helper',*args]), patch.object(helper.subprocess,'call') as run:
                with self.assertRaises(SystemExit):helper.main()
                run.assert_not_called()

    def test_history_fixture_cannot_share_another_suite_or_database_port(self):
        runner = load('consumer_ready_browser')
        for args in (['--history-import','--founder'], ['--history-import','--performance'], ['--history-import','--pg-port','55489']):
            with self.subTest(args=args), patch.object(sys,'argv',['runner',*args]), patch.object(runner.subprocess,'Popen') as spawn:
                with self.assertRaises(SystemExit):runner.main()
                spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
