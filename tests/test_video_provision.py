"""Control-plane safety tests; mocked HTTP never creates a real bucket."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rafii_video_provision', ROOT / 'runtime/provision_video_storage.py')
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


def fake_credential(kind):
    # Symbolic, generated test input; never a provisioned provider credential.
    return '_'.join(('sb', kind, 'a' * 32))


def environment():
    project = 'p' * 20
    return {'VERCEL': '1', 'VERCEL_ENV': 'production', 'RAFII_VIDEO_UPLOADS_ENABLED': 'true',
            'POSTRIFF_PRODUCTION_PROJECT_REF': project, 'POSTRIFF_SUPABASE_URL': f'https://{project}.supabase.co',
            'NEXT_PUBLIC_SUPABASE_URL': f'https://{project}.supabase.co', 'POSTRIFF_SUPABASE_SECRET_KEY': fake_credential('secret')}


def bucket(**changes):
    return json.dumps({'id': 'postriff-video', 'name': 'postriff-video', 'public': False,
                       'file_size_limit': 50_000_000, 'allowed_mime_types': ['video/mp4', 'video/quicktime'], **changes}).encode()


class Recording:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        result = next(self.replies)
        if isinstance(result, BaseException):
            raise result
        return result


class VideoProvision(unittest.TestCase):
    def test_disabled_makes_no_request_and_needs_no_credentials(self):
        for flag in ('', '0', 'false', 'off'):
            send = Recording([])
            self.assertEqual(provision.provision({'RAFII_VIDEO_UPLOADS_ENABLED': flag}, send), {'status': 'disabled', 'changed': False})
            self.assertEqual(send.calls, [])

    def test_pinned_production_verifies_without_mutation(self):
        send = Recording([(200, bucket())])
        self.assertEqual(provision.provision(environment(), send), {'status': 'verified', 'changed': False})
        self.assertEqual([call[0] for call in send.calls], ['GET'])

    def test_missing_or_wrong_target_credentials_make_no_request(self):
        for changes in ({'POSTRIFF_PRODUCTION_PROJECT_REF': ''}, {'POSTRIFF_SUPABASE_SECRET_KEY': ''},
                        {'POSTRIFF_SUPABASE_SECRET_KEY': fake_credential('publishable')},
                        {'VERCEL_ENV': 'development'}, {'VERCEL': ''}, {'POSTRIFF_VIDEO_BUCKET': 'postriff-private'},
                        {'POSTRIFF_SUPABASE_URL': 'https://' + 's' * 20 + '.supabase.co'},
                        {'NEXT_PUBLIC_SUPABASE_URL': 'https://' + 's' * 20 + '.supabase.co'}):
            send = Recording([])
            with self.subTest(changes=tuple(changes)), self.assertRaises(provision.ProvisionError):
                provision.provision({**environment(), **changes}, send)
            self.assertEqual(send.calls, [])

    def test_redirect_query_credentials_and_http_urls_are_rejected(self):
        for url in ('http://' + 'p' * 20 + '.supabase.co', 'https://' + 'p' * 20 + '.supabase.co?wrong=1',
                    urlunsplit(('https', ':'.join(('user', 'fixture')) + '@' + 'p' * 20 + '.supabase.co', '', '', '')), 'https://' + 'p' * 20 + '.supabase.co:443'):
            with self.subTest(url=url), self.assertRaises(provision.ProvisionError):
                provision.provision({**environment(), 'POSTRIFF_SUPABASE_URL': url}, Recording([]))

    def test_existing_unsafe_settings_fail_without_update(self):
        for changes in ({'public': True}, {'public': None}, {'file_size_limit': None}, {'file_size_limit': 0},
                        {'file_size_limit': 100_000_000}, {'file_size_limit': '50000000'},
                        {'allowed_mime_types': []}, {'allowed_mime_types': ['video/mp4', 'video/quicktime', 'text/html']},
                        {'id': 'another-bucket'}):
            send = Recording([(200, bucket(**changes))])
            with self.subTest(changes=changes), self.assertRaises(provision.ProvisionError):
                provision.provision(environment(), send)
            self.assertEqual([call[0] for call in send.calls], ['GET'])

    def test_only_404_allows_create_and_verification_is_mandatory(self):
        send = Recording([(404, b''), (201, b'{}'), (200, bucket())])
        self.assertEqual(provision.provision(environment(), send), {'status': 'created', 'changed': True})
        self.assertEqual([call[0] for call in send.calls], ['GET', 'POST', 'GET'])
        self.assertEqual(json.loads(send.calls[1][3]), json.loads(bucket()))
        self.assertEqual(send.calls[0][1], send.calls[2][1])
        self.assertTrue(send.calls[1][1].endswith('/storage/v1/bucket'))

    def test_other_lookup_failures_never_create(self):
        for status in (301, 302, 400, 401, 403, 409, 500):
            send = Recording([(status, b'private provider detail')])
            with self.subTest(status=status), self.assertRaises(provision.ProvisionError):
                provision.provision(environment(), send)
            self.assertEqual(len(send.calls), 1)

    def test_create_outcome_is_reconciled_without_duplicate_post(self):
        for outcome in ((409, b''), provision.ProvisionError('Private video storage request failed.')):
            send = Recording([(404, b''), outcome, (200, bucket())])
            self.assertEqual(provision.provision(environment(), send), {'status': 'verified_after_create_attempt', 'changed': False})
            self.assertEqual([call[0] for call in send.calls], ['GET', 'POST', 'GET'])

    def test_failed_or_unsafe_post_verification_never_updates_or_retries(self):
        for response in ((404, b''), (403, b''), (200, bucket(public=True)), (200, b'not-json')):
            send = Recording([(404, b''), (201, b'{}'), response])
            with self.subTest(response=response[0]), self.assertRaises(provision.ProvisionError):
                provision.provision(environment(), send)
            self.assertEqual([call[0] for call in send.calls], ['GET', 'POST', 'GET'])

    def test_preview_cannot_use_production_credentials_or_project(self):
        send = Recording([])
        with self.assertRaises(provision.ProvisionError):
            provision.provision({**environment(), 'VERCEL_ENV': 'preview'}, send)
        self.assertEqual(send.calls, [])

    def test_preview_requires_full_existing_staging_isolation_and_fingerprints(self):
        env = {**environment(), 'VERCEL_ENV': 'preview', 'POSTRIFF_ENVIRONMENT': 'staging',
               'POSTRIFF_STAGING_PROJECT_REF': 's' * 20, 'POSTRIFF_SUPABASE_URL': 'https://' + 's' * 20 + '.supabase.co',
               'NEXT_PUBLIC_SUPABASE_URL': 'https://' + 's' * 20 + '.supabase.co',
               'POSTRIFF_DATABASE_URL': urlunsplit(('postgresql', ':'.join(('postgres', 'fixture')) + '@db.' + 's' * 20 + '.supabase.co', '/postgres', 'sslmode=require', '')),
               'POSTRIFF_PUBLIC_BASE_URL': 'https://rafii-staging.example', 'POSTRIFF_STAGING_PUBLIC_BASE_URL': 'https://rafii-staging.example'}
        env['POSTRIFF_STAGING_SECRET_SHA256'] = json.dumps({'POSTRIFF_SUPABASE_SECRET_KEY': hashlib.sha256(env['POSTRIFF_SUPABASE_SECRET_KEY'].encode()).hexdigest()})
        send = Recording([(200, bucket())])
        self.assertEqual(provision.provision(env, send)['status'], 'verified')
        self.assertIn('https://' + 's' * 20 + '.supabase.co/', send.calls[0][1])
        for changes in ({'POSTRIFF_STAGING_SECRET_SHA256': '{}'}, {'RAFII_PHONE_OUTBOUND_ENABLED': 'true'},
                        {'POSTRIFF_SUPABASE_URL': environment()['POSTRIFF_SUPABASE_URL']}):
            send = Recording([])
            with self.subTest(changes=tuple(changes)), self.assertRaises(provision.ProvisionError):
                provision.provision({**env, **changes}, send)
            self.assertEqual(send.calls, [])

    def test_transport_uses_bounded_timeout_and_sanitizes_provider_errors(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = URLError('a-private-secret-and-url')
        with patch.object(provision, 'build_opener', return_value=opener), self.assertRaises(provision.ProvisionError) as caught:
            provision.request('GET', 'https://' + 'p' * 20 + '.supabase.co/storage/v1/bucket/postriff-video', {})
        self.assertNotIn('a-private-secret', str(caught.exception))
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 12)
        self.assertIsNone(provision.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://wrong.example'))

    def test_build_output_never_contains_secret_provider_body_or_project_url(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(provision, 'provision', side_effect=ValueError('secret-value https://private.invalid')):
            self.assertEqual(provision.main(environment()), 1)
        self.assertNotIn('secret-value', out.getvalue())
        self.assertNotIn('https://', out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
