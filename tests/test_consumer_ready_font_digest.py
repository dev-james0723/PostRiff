"""The offline secrets scanner recognizes only locally verified asset digests.

These checks never weaken ordinary high-entropy credential detection.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import consumer_ready_secrets as scan  # noqa: E402


class FontDigestSecretScanTest(unittest.TestCase):
    def test_real_vendored_merriweather_and_license_are_verified(self):
        lines = (ROOT / scan._FONT_MANIFEST).read_text().splitlines()
        sha_lines = [i for i, line in enumerate(lines, 1) if '"sha256":' in line]
        self.assertEqual(len(sha_lines), 2)
        for line in sha_lines:
            with self.subTest(line=line):
                self.assertTrue(scan.verified_font_checksum({
                    'path': scan._FONT_MANIFEST, 'type': 'Hex High Entropy String', 'line': line
                }))

    def test_fail_closed_on_changed_bytes_wrong_origins_and_wrong_findings(self):
        with tempfile.TemporaryDirectory(prefix='font-digest-safety-') as tmp:
            root = Path(tmp)
            folder = root / 'web/src/components/themes/fonts'
            folder.mkdir(parents=True)
            first = b'synthetic font bytes'
            second = b'synthetic license bytes'
            entries = []
            for name, blob in [('Merriweather.ttf', first), ('OFL.txt', second)]:
                (folder / name).write_bytes(blob)
                entries.append({'name': name, 'source': scan._FONT_SOURCES[name],
                                'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()})
            manifest = folder / 'SOURCE.json'
            def write():
                manifest.write_text(json.dumps({'reason': 'fixture', 'files': entries}, indent=2) + '\n')
                return next(i for i, s in enumerate(manifest.read_text().splitlines(), 1)
                            if '"sha256":' in s)
            n = write()
            row = {'path': scan._FONT_MANIFEST, 'type': 'Hex High Entropy String', 'line': n}
            with patch.object(scan, 'ROOT', root):
                self.assertTrue(scan.verified_font_checksum(row))
                self.assertFalse(scan.verified_font_checksum({**row, 'path': 'web/credentials.json'}))
                self.assertFalse(scan.verified_font_checksum({**row, 'type': 'Secret Keyword'}))
                self.assertFalse(scan.verified_font_checksum({**row, 'line': n - 1}))
                (folder / 'Merriweather.ttf').write_bytes(b'synthetic f0nt bytes')
                self.assertFalse(scan.verified_font_checksum(row))
                (folder / 'Merriweather.ttf').write_bytes(first)
                entries[0]['source'] = 'https://attacker.invalid/fake.ttf'
                write()
                self.assertFalse(scan.verified_font_checksum(row))
                entries[0]['source'] = scan._FONT_SOURCES['Merriweather.ttf']
                entries[0]['sha256'] = 'a' * 64
                write()
                self.assertFalse(scan.verified_font_checksum(row))


if __name__ == '__main__':
    unittest.main()
