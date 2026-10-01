import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

class PackageTests(unittest.TestCase):
    def test_separate_artifact_has_only_allowlisted_source_and_no_harness_or_credentials(self):
        spec=importlib.util.spec_from_file_location('control_pack',ROOT/'scripts/rafii_control_package.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='control-package-test-') as tmp:
            output=Path(tmp)/'artifact'
            manifest=module.package(output)
            self.assertTrue((output/'api/control.py').exists())
            self.assertTrue((output/'src/rafii_control/hosted.py').exists())
            self.assertTrue((output/'web/src/styles/rafii.css').exists())
            self.assertFalse((output/'api/index.py').exists())
            self.assertFalse((output/'tests').exists())
            self.assertFalse((output/'control-web/tests').exists())
            self.assertFalse((output/'src/postriff_phase2/hosted_app.py').exists())
            self.assertTrue(all(not p.startswith(('.env','.vercel/','.control-venv','.control-browsers')) for p in manifest))
            self.assertEqual((output/'requirements.txt').read_bytes(),(ROOT/'requirements-control.txt').read_bytes())
            config=__import__('json').loads((output/'vercel.json').read_text())
            self.assertNotIn('crons',config)
            self.assertEqual(set(config['services']),{'control_web','control_api'})
            self.assertTrue((output/'src/postriff_phase2/locale_catalogue.json').exists())
            child = subprocess.run([sys.executable, '-c', "import sys; sys.path.insert(0,'src'); import api.control; from postriff_phase2.locales import catalogue; assert catalogue()['entries']; from rafii_control.intelligence import Catalog; assert len(Catalog().metrics)==63"], cwd=output, env={'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True)
            self.assertEqual(child.returncode,0,child.stderr)
