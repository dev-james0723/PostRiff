"""Bounded mirror fallback contracts, no actual archive/network/build execution."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('renderer_download', Path(__file__).resolve().parents[1] / 'runtime/build_document_renderer.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class ArchiveDownloadTests(unittest.TestCase):
    def test_unreachable_geo_mirror_falls_back_to_same_version_and_pinned_checksum(self):
        content = b'synthetic locked archive'
        with tempfile.TemporaryDirectory() as work, patch.object(renderer, 'SHA256', hashlib.sha256(content).hexdigest()), \
                patch.object(renderer.urllib.request, 'urlopen', side_effect=[urllib.error.URLError('Network unreachable'), io.BytesIO(content)]) as get:
            destination = Path(work) / 'archive'
            renderer.download_locked_archive(destination)
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(get.call_count, 2)
            self.assertIn('ftp.osuosl.org/pub/tdf/libreoffice/stable/26.2.6/', get.call_args.args[0])
            self.assertEqual(get.call_args.kwargs['timeout'], 30)

    def test_checksum_mismatch_stops_without_retry_or_leaving_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as work, patch.object(renderer.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt')) as get:
            destination = Path(work) / 'archive'
            with self.assertRaises(SystemExit): renderer.download_locked_archive(destination)
            self.assertFalse(destination.exists()); self.assertEqual(get.call_count, 1)

    def test_two_unreachable_mirrors_fail_without_stale_archive(self):
        with tempfile.TemporaryDirectory() as work, patch.object(renderer.urllib.request, 'urlopen', side_effect=urllib.error.URLError('Network unreachable')) as get:
            destination = Path(work) / 'archive'
            destination.write_bytes(b'stale')
            with self.assertRaises(urllib.error.URLError): renderer.download_locked_archive(destination)
            self.assertFalse(destination.exists()); self.assertEqual(get.call_count, 2)
