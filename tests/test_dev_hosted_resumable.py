"""Offline synthetic storage control tests; no servers, database or provider calls."""
import base64
import sys
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from postriff_dev_hosted import DevAssets


class DevResumableTests(unittest.TestCase):
    def setUp(self):
        self.storage = DevAssets()
        self.workspace = str(uuid.uuid4())
        self.object = uuid.uuid4().hex + '.mp4'
        self.grant = self.storage.signed_resumable_upload(self.workspace, self.object, 'video/mp4')

    def request(self, method, session=None, raw=b'', grant=None, **headers):
        grant = grant or self.grant
        return self.storage.resumable_request(method, session,
            {'Tus-Resumable': '1.0.0', **grant['headers'], **headers}, raw)

    def create(self, length=6, grant=None):
        grant = grant or self.grant
        metadata = ','.join(key + ' ' + base64.b64encode(value.encode()).decode()
            for key, value in grant['metadata'].items())
        status, headers, _ = self.request('POST', grant=grant,
            **{'Upload-Length': str(length), 'Upload-Metadata': metadata})
        self.assertEqual(status, 201)
        self.assertTrue(headers['Location'].startswith(self.grant['endpoint'] + '/'))
        return headers['Location'].rsplit('/', 1)[1]

    def patch(self, session, offset, raw, grant=None):
        return self.request('PATCH', session, raw, grant,
            **{'Upload-Offset': str(offset), 'Content-Type': 'application/offset+octet-stream'})

    def test_partial_head_and_exact_immutable_completion(self):
        session = self.create()
        self.assertEqual(self.patch(session, 0, b'abc')[0], 204)
        status, headers, _ = self.request('HEAD', session)
        self.assertEqual((status, headers['Upload-Offset'], headers['Upload-Length']), (200, '3', '6'))
        self.assertNotIn((self.workspace, 'video', self.object), self.storage.objects)
        self.assertEqual(self.patch(session, 3, b'def')[0], 204)
        self.assertEqual(self.request('HEAD', session)[1]['Upload-Offset'], '6')
        self.assertEqual(self.storage.get(self.workspace, 'video', self.object), b'abcdef')
        self.assertEqual(self.storage.object_info(self.workspace, 'video', self.object)['mime'], 'video/mp4')
        self.assertEqual(self.patch(session, 0, b'replace')[0], 409)
        self.assertEqual(self.storage.get(self.workspace, 'video', self.object), b'abcdef')

    def test_signature_metadata_offset_and_length_fail_closed(self):
        session = self.create()
        self.assertEqual(self.request('HEAD', session, **{'x-signature': uuid.uuid4().hex})[0], 403)
        other = self.storage.signed_resumable_upload(str(uuid.uuid4()), self.object, 'video/mp4')
        self.assertEqual(self.request('HEAD', session, grant=other)[0], 403)
        self.assertEqual(self.patch(session, 1, b'abc')[0], 409)
        self.assertEqual(self.patch(session, 0, b'oversize')[0], 413)
        self.assertEqual(self.request('HEAD', session)[1]['Upload-Offset'], '0')
        self.assertEqual(self.request('POST', **{'Upload-Length': '6', 'Upload-Metadata': 'objectName !!!'})[0], 400)
        mismatch = ','.join(key + ' ' + base64.b64encode(value.encode()).decode()
            for key, value in other['metadata'].items())
        self.assertEqual(self.request('POST', **{'Upload-Length': '6', 'Upload-Metadata': mismatch})[0], 403)
        self.assertEqual(self.request('HEAD', session, **{'Tus-Resumable': '0.2.2'})[0], 412)

    def test_renewed_same_object_grant_and_parallel_completion_fence(self):
        session, competing = self.create(), self.create()
        self.assertEqual(self.patch(session, 0, b'abc')[0], 204)
        renewed = self.storage.signed_resumable_upload(self.workspace, self.object, 'video/mp4')
        self.storage.resumable_grants[self.grant['headers']['x-signature']]['expiresAt'] = 0
        self.assertEqual(self.request('HEAD', session)[0], 403)
        self.assertEqual(self.request('HEAD', session, grant=renewed)[1]['Upload-Offset'], '3')
        self.assertEqual(self.patch(session, 3, b'def', renewed)[0], 204)
        self.assertEqual(self.patch(competing, 0, b'UVWXYZ', renewed)[0], 409)
        self.assertEqual(self.storage.get(self.workspace, 'video', self.object), b'abcdef')

    def test_legacy_signed_put_stays_single_use_and_immutable(self):
        signed = self.storage.signed_upload_url(self.workspace, 'video', self.object)
        token = parse_qs(urlsplit(signed).query)['token'][0]
        self.assertTrue(self.storage.receive_upload(token, b'legacy', 'video/mp4'))
        self.assertFalse(self.storage.receive_upload(token, b'replace', 'video/mp4'))
        other = parse_qs(urlsplit(self.storage.signed_upload_url(self.workspace, 'video', self.object)).query)['token'][0]
        self.assertFalse(self.storage.receive_upload(other, b'replace', 'video/mp4'))
        self.assertEqual(self.storage.get(self.workspace, 'video', self.object), b'legacy')

    def test_concurrent_sessions_only_one_can_finalize_the_object(self):
        sessions = [self.create(), self.create()]
        start, results = threading.Barrier(3), []
        def finish(session, raw):
            start.wait(timeout=1)
            results.append(self.patch(session, 0, raw)[0])
        workers = [threading.Thread(target=finish, args=pair)
            for pair in zip(sessions, (b'abcdef', b'UVWXYZ'))]
        for worker in workers:
            worker.start()
        start.wait(timeout=1)
        for worker in workers:
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(results), [204, 409])
        self.assertIn(self.storage.get(self.workspace, 'video', self.object), (b'abcdef', b'UVWXYZ'))


if __name__ == '__main__':
    unittest.main()
