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


if __name__ == '__main__':
    unittest.main()
