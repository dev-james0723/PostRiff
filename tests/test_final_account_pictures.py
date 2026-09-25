"""FINAL-10: the real picture fetcher must never raise; an unreachable picture is simply absent.

Before the fix every real call raised TypeError (OpenerDirector.open has no `context` argument), which
turned a successful account connection into an HTTP 500 after the channel was saved.
"""
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2 import account_pictures


def closed_loopback_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class RealPictureFetch(unittest.TestCase):
    def test_unreachable_picture_is_absent_not_an_exception(self):
        status, content_type, body = account_pictures.fetch_image(f'https://127.0.0.1:{closed_loopback_port()}/avatar.jpg')
        self.assertEqual((status, content_type, body), (0, '', b''))

    def test_https_verification_stays_on(self):
        handlers = account_pictures.picture_opener().handlers
        https = [h for h in handlers if h.__class__.__name__ == 'HTTPSHandler']
        self.assertEqual(len(https), 1)
        context = https[0]._context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode.name, 'CERT_REQUIRED')


if __name__ == '__main__':
    unittest.main()
