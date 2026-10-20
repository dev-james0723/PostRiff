import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ReceiptPackaging(unittest.TestCase):
 def test_vercel_upload_explicitly_includes_ignored_source_receipt(self):
  lines=(ROOT/'.vercelignore').read_text().splitlines()
  self.assertIn('!src/postriff_phase2/release-source.json',lines)
  self.assertTrue((ROOT/'src/postriff_phase2/release-source.json').is_file())
