"""Keep the X release and inherited Library preview image decoder off a known-vulnerable Pillow pin.

The upstream Pillow 13.0.0 release fixes eight CVEs reported for 12.3.0 in
GitHub run 39620959152. These tests assert deployment/CI pins only; the
runtime's actual image decode compatibility is exercised by dedicated suites.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_PIN = 'Pillow==13.0.0'


class PillowDependencySecurity(unittest.TestCase):
    def test_production_requirements_pin_fixed_pillow_release(self):
        lines = (ROOT / 'requirements.txt').read_text().splitlines()
        pinned = [line.strip() for line in lines if re.fullmatch(r'(?i)\s*pillow\s*==\s*[^\s#]+\s*(?:#.*)?', line)]
        self.assertEqual(pinned, [SAFE_PIN])

    def test_isolated_library_preview_workflow_uses_same_fixed_release(self):
        workflow = (ROOT / '.github/workflows/library-release.yml').read_text()
        self.assertIn('python3.12 -m pip install --target .document-test-python ' + SAFE_PIN, workflow)
        self.assertNotIn('Pillow==12.3.0', workflow)

    def test_hosted_preflight_accepts_patched_release(self):
        from scripts.check_postriff_hosted_preflight import validate_structure
        statuses = {item['name']: item['status'] for item in validate_structure(ROOT)}
        self.assertEqual(statuses['python-runtime'], 'pass')

    def test_hosted_preflight_rejects_vulnerable_legacy_pin(self):
        from unittest.mock import patch
        from scripts.check_postriff_hosted_preflight import validate_structure
        original_read_text = Path.read_text
        requirements = ROOT / 'requirements.txt'

        def legacy_pillow(path, *args, **kwargs):
            content = original_read_text(path, *args, **kwargs)
            return content.replace(SAFE_PIN, 'Pillow==12.3.0') if path == requirements else content

        with patch.object(Path, 'read_text', legacy_pillow):
            statuses = {item['name']: item['status'] for item in validate_structure(ROOT)}
        self.assertEqual(statuses['python-runtime'], 'fail')


if __name__ == '__main__':
    unittest.main()
