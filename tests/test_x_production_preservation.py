"""Release reconciliation must not remove live unrelated integrations or cost controls."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class XProductionPreservation(unittest.TestCase):
    def test_inherited_live_files_are_preserved_exactly(self):
        manifest = json.loads((ROOT / 'docs/operations/X-PRODUCTION-PRESERVATION.json').read_text())
        self.assertIsNone(manifest['historicalDeploymentGitSha'])
        for name, expected in manifest['exactInheritedFiles'].items():
            with self.subTest(path=name):
                path = ROOT / name
                self.assertTrue(path.is_file() and not path.is_symlink(), name)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, name)

    def test_automatic_vercel_deploy_remains_disabled(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        self.assertIs(config['git']['deploymentEnabled'], False)

if __name__ == '__main__':
    unittest.main()
