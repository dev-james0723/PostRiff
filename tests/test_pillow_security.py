"""Regression for GHSA-65qm-jvmh-6pqg without decoding a large image."""
import io
import unittest
from unittest.mock import patch

from PIL import Image


class PillowSecurityTests(unittest.TestCase):
    def test_rejected_gif_frame_does_not_poison_image_dimensions(self):
        # A tiny first frame followed by an oversized descriptor. Only inspect
        # metadata after the refusal: loading the rejected frame is unsafe on
        # vulnerable Pillow and is deliberately never attempted here.
        raw = bytes.fromhex(
            '47494638396101000100800000000000ffffff'
            '2c0000000001000100000202440100'
            '2c00000000409c409c00'
            '2c00000000010001000002024401003b')
        with patch.object(Image, 'MAX_IMAGE_PIXELS', 4096), Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, (1, 1))
            with self.assertRaises(Image.DecompressionBombError):
                image.seek(1)
            self.assertEqual(image.size, (1, 1), 'Rejected dimensions must not survive a decompression-bomb error')
