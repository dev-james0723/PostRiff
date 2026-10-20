"""X media acceptance: real adapter, synthetic wire/storage. Never live provider proof."""
import copy
import hashlib
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from postriff_phase2.social_connectors import XProvider
from postriff_phase2.x_direct_cost import PRICES, XCostAdmissionError, bind_x_cost_context
from postriff_phase2 import x_direct_media as media

RAW = b'\xff\xd8synthetic-jpeg-bytes\xff\xd9'
QUOTES = {key: 17 for key in media.MEDIA_PRICE_KEYS}  # TEST QUOTES, not X prices.
BOOK = {**PRICES, **QUOTES}
WS, CONN, ACTOR = 'workspace-a', 'a' * 32, '123'
NOW = 1_800_000_000.0

def image():
    h = hashlib.sha256(RAW).hexdigest()
    return {'id': 'b' * 32, 'objectName': 'b' * 32 + '-' + h + '.jpg',
            'hash': h, 'mime': 'image/jpeg', 'bytes': len(RAW), 'processing': 'decoded', 'deleted': False}

def video(size=media.CHUNK_BYTES + 11):
    name = 'c' * 32 + '.mp4'
    return {'id': 'c' * 32, 'objectName': name, 'mime': 'video/mp4', 'bytes': size,
            'etag': 'immutable-test-etag', 'hash': hashlib.sha256(f'video:{name}:{size}:immutable-test-etag'.encode()).hexdigest(),
            'duration': 10, 'durationSource': 'container', 'processing': 'ready',
            'verified': {'container': True}, 'deleted': False}

class Storage:
    def __init__(self): self.changed = False; self.reads = []
    def get(self, workspace, category, name):
        self.reads.append((workspace, category, name))
        return RAW + (b'changed' if self.changed else b'')
    def iter_verified_video(self, workspace, name, *, expected_bytes, expected_mime, expected_etag, chunk_size):
        if self.changed: raise AlphaError('Changed source', 409)
        self.reads.append((workspace, 'video', name))
        remaining = expected_bytes
        while remaining:
            n = min(remaining, chunk_size); remaining -= n
            yield b'v' * n

class Wire:
    def __init__(self, answers): self.answers, self.calls = list(answers), []
    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.answers: raise AssertionError('Unplanned synthetic request')
        value = self.answers.pop(0)
        if isinstance(value, Exception): raise value
        return copy.deepcopy(value)

def ok(**data): return {'status': 200, 'body': {'data': data}}
def accepted(processing=None):
    fields = {'id': '1880028106020515840', 'media_key': '3_1880028106020515840', 'expires_after_secs': 3600}
    if processing is not None: fields['processing_info'] = processing
    return ok(**fields)

class MediaWorkflow(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(); self.reservations = []
    def setup_wire(self, answers):
        self.wire = Wire(answers); self.provider = XProvider('fixture', 'not-a-secret', transport=self.wire)
        token = self.provider._grant({'access_token': 'synthetic', 'scope': 'media.write tweet.write tweet.read users.read', 'expires_in': 3600})
        self.grant = {'accessToken': token['accessToken'], 'workspaceId': WS, 'connectionId': CONN,
                      'providerAccountId': ACTOR, 'authorizationGeneration': self.provider.authorization_generation(token['accessToken']),
                      'scopes': ['media.write', 'tweet.write', 'tweet.read', 'users.read']}
    @contextmanager
    def admitted(self, prices=BOOK):
        def reserve(req): self.reservations.append(req); return req.request_id
        with bind_x_cost_context(workspace_id=WS, connection_id=CONN, operation='media.upload', reserve=reserve, price_book=prices): yield
    def plan(self, asset=None, alt=''):
        return media.plan_media(WS, CONN, ACTOR, asset or image(), alt, BOOK)
    def step(self, plan, progress=None, now=NOW):
        with self.admitted():
            return media.advance_media(plan, self.provider, self.grant, progress or {}, self.storage, now=now)

    def test_image_upload_receipt_binds_bytes_account_and_expiration(self):
        self.setup_wire([accepted()]); plan = self.plan(); result = self.step(plan)
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['receipt']['resourceId'], '1880028106020515840')
        state = result['progress']['media']
        self.assertEqual((state['stage'], state['expiresAt']), ('ready', NOW + 3600))
        self.assertEqual(state['authorizationGeneration'], self.grant['authorizationGeneration'])
        self.assertIn(RAW, self.wire.calls[0][2]['data'])
        self.assertIn(b'tweet_image', self.wire.calls[0][2]['data'])
        self.assertNotIn(b'additional_owners', self.wire.calls[0][2]['data'])
        self.assertEqual(len(self.reservations), 1)
        self.assertEqual(self.reservations[0].price_key, 'media_upload')

    def test_upload_and_metadata_need_separate_receipts(self):
        self.setup_wire([accepted(), ok(id='1880028106020515840', associated_metadata={'alt_text': {'text': 'Score'}})])
        plan = self.plan(alt='Score'); first = self.step(plan)
        self.assertEqual(first['state'], 'queued')
        last = self.step(plan, first['progress'])
        self.assertEqual(last['state'], 'verified'); self.assertTrue(last['progress']['media']['altVerified'])
        self.assertEqual(self.wire.calls[1][2]['body'], {'id': '1880028106020515840', 'metadata': {'alt_text': {'text': 'Score'}}})

    def test_video_initialize_chunks_finalize_and_processing(self):
        self.setup_wire([accepted(), ok(expires_at=int(NOW + 3600)), ok(expires_at=int(NOW + 3600)),
                         accepted({'state': 'pending', 'check_after_secs': 1}), accepted({'state': 'succeeded'})])
        plan = self.plan(video()); progress = {}; states = []
        for tick in range(5):
            result = self.step(plan, progress, NOW + tick * 2); progress = result['progress']; states.append(result['state'])
        self.assertEqual(states, ['queued'] * 4 + ['verified'])
        self.assertTrue(self.wire.calls[0][1].endswith('/initialize'))
        self.assertEqual(self.wire.calls[0][2]['body']['total_bytes'], media.CHUNK_BYTES + 11)
        self.assertTrue(self.wire.calls[1][1].endswith('/append'))
        self.assertIn(b'\r\n0\r\n', self.wire.calls[1][2]['data'])
        self.assertIn(b'\r\n1\r\n', self.wire.calls[2][2]['data'])
        self.assertTrue(self.wire.calls[3][1].endswith('/finalize'))
        self.assertIn('command=STATUS', self.wire.calls[4][1])
        self.assertEqual(len(self.reservations), 5)

    def test_changed_image_never_reaches_x(self):
        self.setup_wire([]); self.storage.changed = True
        with self.assertRaises(AlphaError): self.step(self.plan())
        self.assertEqual(self.wire.calls, [])

    def test_foreign_actor_or_reconnect_cannot_resume_upload(self):
        self.setup_wire([accepted()]); plan = self.plan(alt='Score'); result = self.step(plan)
        for key, value in [('providerAccountId', '999'), ('connectionId', 'f' * 32), ('authorizationGeneration', 'new-consent')]:
            with self.subTest(key=key):
                grant = {**self.grant, key: value}
                with self.admitted(), self.assertRaises(AlphaError):
                    media.advance_media(plan, self.provider, grant, result['progress'], self.storage, now=NOW)
        self.assertEqual(len(self.wire.calls), 1)

    def test_expired_media_stops_without_metadata_call(self):
        self.setup_wire([accepted()]); plan = self.plan(alt='Score'); result = self.step(plan)
        with self.assertRaises(AlphaError): self.step(plan, result['progress'], NOW + 3601)
        self.assertEqual(len(self.wire.calls), 1)

    def test_timeout_is_uncertain_not_verified_or_retried(self):
        self.setup_wire([TimeoutError('synthetic lost response')]); result = self.step(self.plan())
        self.assertEqual(result['state'], 'uncertain'); self.assertEqual(len(self.wire.calls), 1)
        self.assertNotIn('receipt', result)

    def test_missing_price_evidence_blocks_before_network(self):
        self.setup_wire([])
        with self.assertRaises(XCostAdmissionError): media.plan_media(WS, CONN, ACTOR, image(), '', PRICES)
        with self.admitted(PRICES), self.assertRaises(XCostAdmissionError):
            media.advance_media(self.plan(), self.provider, self.grant, {}, self.storage, now=NOW)
        self.assertEqual(self.wire.calls, [])

    def test_wrong_id_partial_and_malformed_media_responses_never_succeed(self):
        for response in [ok(id='bad'), {'status': 200, 'body': {'data': accepted()['body']['data'], 'errors': [{}]}},
                         accepted({'state': 'not-real'}), ok(id='1880028106020515840', media_key='3_999', expires_after_secs=3600)]:
            with self.subTest(response=response):
                self.setup_wire([response]); result = self.step(self.plan())
                self.assertNotEqual(result['state'], 'verified')

    def test_invalid_asset_and_paths_rejected_before_io(self):
        for changes in [{'deleted': True}, {'objectName': '../../secret'}, {'bytes': True}, {'mime': 'text/html'},
                        {'processing': 'pending'}, {'hash': 'x'}, {'bytes': 5_000_001}]:
            with self.subTest(changes=changes), self.assertRaises(AlphaError): self.plan({**image(), **changes})

    def test_pending_status_is_bounded_and_does_not_refresh_expiration(self):
        self.setup_wire([accepted({'state': 'pending', 'check_after_secs': 1})] + [accepted({'state': 'pending', 'check_after_secs': 1})] * media.MAX_POLLS)
        plan = self.plan(); result = self.step(plan)
        for i in range(media.MAX_POLLS): result = self.step(plan, result['progress'], NOW + 2 + i * 2)
        self.assertEqual(result['state'], 'held')
        self.assertEqual(result['progress']['media']['expiresAt'], NOW + 3600)
        self.assertEqual(len(self.wire.calls), media.MAX_POLLS + 1)

if __name__ == '__main__': unittest.main()
