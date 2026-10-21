"""Fail-first contract for strictly isolated Rafii Discord A7a-0 signed PING."""
from __future__ import annotations
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
APP = "1553164599086555297"
ORIGIN = "https://synthetic-a7a0.example.invalid"

class SignedPingTests(unittest.TestCase):
    def setUp(self):
        from a7a0_ping_core import Settings
        self.secret = Ed25519PrivateKey.generate()  # synthetic, never written
        self.public = self.secret.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.settings = Settings(application_id=APP, public_key_hex=self.public, expected_origin=ORIGIN)
        self.now = 1800000000

    def signed(self, packet, *, when=None):
        raw = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        stamp = str(self.now if when is None else when)
        return raw, stamp, self.secret.sign(stamp.encode("ascii") + raw).hex()

    def test_valid_ping_returns_only_pong(self):
        from a7a0_ping_core import verify_ping
        raw, timestamp, sig = self.signed({"application_id": APP, "type": 1})
        self.assertEqual(verify_ping(raw, timestamp, sig, self.settings, now=self.now), {"type": 1})

    def test_invalid_signature_wrong_public_key_and_modified_raw_body(self):
        from a7a0_ping_core import Reject, Settings, verify_ping
        raw, timestamp, sig = self.signed({"application_id": APP, "type": 1})
        for bad_raw, bad_sig, settings in [
            (raw, "00" * 64, self.settings),
            (raw + b" ", sig, self.settings),
            (raw, sig, Settings(application_id=APP, public_key_hex=Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(), expected_origin=ORIGIN)),
        ]:
            with self.subTest(case=(len(bad_raw), bad_sig[:4])), self.assertRaises(Reject) as cm:
                verify_ping(bad_raw, timestamp, bad_sig, settings, now=self.now)
            self.assertEqual(cm.exception.status, 401)

    def test_time_boundaries(self):
        from a7a0_ping_core import verify_ping, Reject
        for delta in (-301, 301, -10000):
            raw, timestamp, sig = self.signed({"application_id": APP, "type": 1}, when=self.now + delta)
            with self.subTest(delta=delta), self.assertRaises(Reject) as cm:
                verify_ping(raw, timestamp, sig, self.settings, now=self.now)
            self.assertEqual(cm.exception.status, 401)
        for delta in (-300, 300):
            raw, timestamp, sig = self.signed({"application_id": APP, "type": 1}, when=self.now + delta)
            self.assertEqual(verify_ping(raw, timestamp, sig, self.settings, now=self.now), {"type": 1})

    def test_wrong_app_boolean_type_and_non_ping_never_execute(self):
        from a7a0_ping_core import verify_ping, Reject
        for packet, status in [
            ({"application_id": "000000000000000000", "type": 1}, 401),
            ({"application_id": APP, "type": True}, 401),
            ({"application_id": APP, "type": 2}, 503),
            ({"application_id": APP, "type": 4}, 503),
        ]:
            raw, timestamp, sig = self.signed(packet)
            with self.subTest(packet=packet), self.assertRaises(Reject) as cm:
                verify_ping(raw, timestamp, sig, self.settings, now=self.now)
            self.assertEqual(cm.exception.status, status)

    def test_oversized_duplicate_keys_invalid_json_and_nonobject(self):
        from a7a0_ping_core import verify_ping, Reject
        raws = [
            b"{" + b" " * 65536 + b"}",
            ('{"application_id":"' + APP + '","type":1,"type":2}').encode(),
            b'{"application_id": "' + APP.encode() + b'", "type": NaN}',
            b'[]', b'{}', b'{', b'\xff', b'',
        ]
        for raw in raws:
            timestamp = str(self.now)
            signature = self.secret.sign(timestamp.encode() + raw).hex()
            with self.subTest(length=len(raw)), self.assertRaises(Reject):
                verify_ping(raw, timestamp, signature, self.settings, now=self.now)

    def test_signed_non_utf8_and_bom_are_rejected(self):
        from a7a0_ping_core import verify_ping, Reject
        for raw in [
            json.dumps({'application_id': APP, 'type':1}).encode('utf-16'),
            b'\xef\xbb\xbf' + json.dumps({'application_id':APP,'type':1}).encode('utf-8'),
        ]:
            ts = str(self.now)
            sig = self.secret.sign(ts.encode('ascii') + raw).hex()
            with self.subTest(length=len(raw)), self.assertRaises(Reject):
                verify_ping(raw, ts, sig, self.settings, now=self.now)

    def test_origin_binding_never_uses_request_host(self):
        from a7a0_ping_core import Settings, Reject, settings_from_env
        fields = {'RAFII_A7A0_APPLICATION_ID': APP, 'RAFII_A7A0_PUBLIC_KEY_HEX': self.public,
                  'RAFII_A7A0_EXPECTED_ORIGIN': ORIGIN,
                  'VERCEL_URL': 'synthetic-a7a0.example.invalid'}
        self.assertEqual(settings_from_env(fields), self.settings)
        bad = {**fields, 'VERCEL_URL': 'evil.example.invalid'}
        with self.assertRaises(Reject):
            settings_from_env(bad)
        with self.assertRaises(Reject):
            settings_from_env({k: v for k, v in fields.items() if k != 'RAFII_A7A0_EXPECTED_ORIGIN'})
        for poisoned in ['http://synthetic-a7a0.example.invalid', 'https://a@synthetic-a7a0.example.invalid',
                         'https://synthetic-a7a0.example.invalid:443/path', 'https://synthetic-a7a0.example.invalid/', 'https://x..example.invalid', 'https://-bad.example.invalid']:
            with self.subTest(poisoned=poisoned), self.assertRaises(Reject):
                Settings(APP, self.public, poisoned)

    def test_no_db_socket_or_outbound_provider_execution(self):
        from a7a0_ping_core import verify_ping
        import a7a0_ping_core
        raw, timestamp, sig = self.signed({"application_id": APP, "type": 1})
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK IO')) as a, \
             patch.object(socket, 'create_connection', side_effect=AssertionError('NETWORK IO')) as b:
            self.assertEqual(verify_ping(raw, timestamp, sig, self.settings, now=self.now), {"type": 1})
            a.assert_not_called()
            b.assert_not_called()
        self.assertFalse(any(x.startswith(('postriff_alpha','postriff_phase2','psycopg')) for x in sys.modules))
        self.assertNotIn('sqlite3', sys.modules)
        self.assertFalse(any(word in a7a0_ping_core.__dict__ for word in ('request', 'httpx', 'requests', 'psycopg')))

    def test_http_handler_is_exact_route_and_status_fail_closed(self):
        from api.discord.interactions import handler
        from a7a0_ping_core import settings_from_env
        keyvars = {'RAFII_A7A0_APPLICATION_ID': APP, 'RAFII_A7A0_PUBLIC_KEY_HEX': self.public,
                   'RAFII_A7A0_EXPECTED_ORIGIN': ORIGIN, 'VERCEL_URL':'synthetic-a7a0.example.invalid'}
        raw, timestamp, sig = self.signed({"application_id": APP, "type": 1})
        class Header(dict):
            duplicate_keys = frozenset()
            def get_all(self, key):
                if key not in self:
                    return []
                return [self[key],self[key]] if key in self.duplicate_keys else [self[key]]
        def run(method='POST', path='/api/discord/interactions', body=raw, hdr=None, env=None, duplicate=None):
            h = object.__new__(handler)
            h.path = path
            h.command = method
            h.headers = Header({'Content-Type':'application/json','Content-Length':str(len(body)),
                'X-Signature-Timestamp':timestamp, 'X-Signature-Ed25519':sig, **(hdr or {})})
            h.headers.duplicate_keys = set(duplicate or ())
            h.rfile = io.BytesIO(body)
            h.wfile = io.BytesIO()
            h._status=[]
            h.send_response = lambda x: h._status.append(x)
            h.send_header = lambda k,v: None
            h.end_headers = lambda: None
            with patch.dict(os.environ, keyvars if env is None else env, clear=True), \
                 patch('a7a0_ping_core.time.time', return_value=self.now):
                getattr(h, 'do_'+method)()
            return h._status, h.wfile.getvalue()
        self.assertEqual(run(), ([200], b'{"type":1}'))
        self.assertEqual(run(method='GET')[0], [405])
        self.assertEqual(run(method='HEAD')[0], [405])
        self.assertEqual(run(method='TRACE')[0], [405])
        self.assertEqual(run(method='CONNECT')[0], [405])
        self.assertEqual(run(path='/any/other/path')[0], [404])
        self.assertEqual(run(path='/api/discord/interactions?foo=1')[0], [404])
        self.assertEqual(run(hdr={'Content-Type':'text/plain'})[0], [415])
        self.assertEqual(run(hdr={'Content-Length':'65537'})[0], [413])
        self.assertEqual(run(hdr={'Content-Length':'garbage'})[0], [400])
        self.assertEqual(run(hdr={'Transfer-Encoding':'chunked'})[0], [400])
        self.assertEqual(run(hdr={'X-Signature-Ed25519':'00'*64})[0], [401])
        self.assertEqual(run(duplicate=['Content-Length'])[0],[400])
        self.assertEqual(run(duplicate=['X-Signature-Timestamp'])[0],[401])
        self.assertEqual(run(duplicate=['X-Signature-Ed25519'])[0],[401])
        self.assertEqual(run(env={})[0], [503])
        self.assertEqual(run(body=raw[:-1])[0], [401])
        bad_signed=json.dumps({'application_id':APP,'type':2}).encode()
        bad_ts=str(self.now)
        bad_sig=self.secret.sign(bad_ts.encode()+bad_signed).hex()
        self.assertEqual(run(body=bad_signed,hdr={'X-Signature-Timestamp':bad_ts,'X-Signature-Ed25519':bad_sig})[0],[503])

    def test_manifest_no_cron_external_services_and_pinned_runtime(self):
        data=json.loads((BASE / 'vercel.json').read_text())
        self.assertNotIn('crons',data)
        self.assertNotIn('rewrites',data)
        self.assertNotIn('services',data)
        self.assertEqual(data['framework'],None)
        self.assertEqual((BASE / '.python-version').read_text().strip(),'3.12')
        self.assertEqual((BASE / 'requirements.txt').read_text().strip(),'cryptography==50.0.1')
        self.assertEqual(list((BASE / 'api').rglob('*.py')),[BASE/'api/discord/interactions.py'])
        self.assertFalse((BASE/'api/index.py').exists())
        self.assertNotIn('POSTRIFF_',json.dumps(data))

if __name__ == '__main__':
    unittest.main()
