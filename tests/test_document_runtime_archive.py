"""Immutable first-use Office runtime archive regression tests.

No downloaded binaries required: use tiny synthetic runtime fixtures.
The end-to-end real DOCX/XLSX/PPTX/legacy tests remain in test_library_preview.
"""
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from postriff_phase2 import library_preview as preview


class ArchiveRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.source / 'VERSION').write_text(preview._RENDERER_BUILD)
        office = self.source / 'office/program'
        office.mkdir(parents=True)
        (office / 'soffice.bin').write_bytes(b'synthetic executable fixture')
        libraries = self.source / 'lib'
        libraries.mkdir()
        (libraries / 'libseccomp.so.2').write_bytes(b'synthetic sandbox fixture')
        self.archive = self.base / 'artifact.tar.xz'
        self.output = self.base / 'unpacked'

    def package(self, malicious=False):
        with tarfile.open(self.archive, 'w:xz', preset=3) as tar:
            tar.add(self.source, arcname='.')
            if malicious:
                entry = tarfile.TarInfo(name='../../../outside-destination')
                entry.type = tarfile.REGTYPE
                entry.size = 4
                tar.addfile(entry, io.BytesIO(b'bad!'))
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def invoke(self, digest):
        with patch.multiple(preview, _ARCHIVE=self.archive, _ARCHIVE_ID=digest, ROOT=self.output):
            preview._ensure_renderer()

    def test_signed_archive_extracts_once(self):
        digest = self.package()
        self.invoke(digest)
        self.assertEqual((self.output / 'VERSION').read_text(), preview._RENDERER_BUILD)
        self.assertEqual((self.output / 'office/program/soffice.bin').read_bytes(), b'synthetic executable fixture')
        self.invoke(digest)
        self.assertTrue((self.output / 'lib/libseccomp.so.2').exists())

    def test_tampered_archive_fails_closed(self):
        digest = self.package()
        self.archive.write_bytes(self.archive.read_bytes() + b'tamper')
        with self.assertRaisesRegex(RuntimeError, 'integrity mismatch'):
            self.invoke(digest)
        self.assertFalse(self.output.exists())

    def test_invalid_manifest_fails_closed(self):
        self.package()
        with self.assertRaisesRegex(RuntimeError, 'checksum manifest unavailable'):
            self.invoke('not-a-sha256')
        self.assertFalse(self.output.exists())

    def test_archive_traversal_cannot_escape_tmp(self):
        digest = self.package(malicious=True)
        with self.assertRaises(Exception):
            self.invoke(digest)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.base / 'outside-destination').exists())


if __name__ == '__main__':
    unittest.main()
