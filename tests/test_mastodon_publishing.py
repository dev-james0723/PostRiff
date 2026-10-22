"""Durable Mastodon boundaries using synthetic transport; never live acceptance."""
import copy
import hashlib
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone

from postriff_phase2.mastodon_publishing import advance, backoff, can_resume, checked_progress, native_reconcile
from postriff_phase2.outcomes import normalize_result


def response(data=None, status=200, headers=None):
    return {'status': status, 'body': data or {}, 'headers': headers or {}}


class DurablePublishingTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791690000
        self.calls, self.saved = [], []
        self.replies = []
        self.raw = b'synthetic audio bytes'
        self.asset = {'id': 'a' * 32, 'hash': hashlib.sha256(self.raw).hexdigest(), 'bytes': len(self.raw),
                      'mime': 'audio/mpeg', 'alt': 'Audio example', 'normalizedLibrary': True, 'objectName': 'a' * 32 + '.mp3'}
        self.manifest = {'platform': 'Mastodon', 'workspaceId': 'w', 'channelId': 'c', 'providerAccountId': '10@mastodon.social',
                         'idempotencyKey': 'single-approved-job', 'payload': {'text': 'An approved post'}, 'publishOptions': {}, 'media': [self.asset]}
        def api(session, method, path, **kw):
            self.calls.append((method, path, kw))
            if not self.replies: raise AssertionError('Unexpected provider API call')
            item = self.replies.pop(0)
            if isinstance(item, Exception): raise item
            return item
        provider = SimpleNamespace(publish_required={'write:statuses', 'write:media'},
            session=lambda _: {'instance': 'mastodon.social'}, api=api,
            transport=lambda _method, url, **_kw: response(status=404) if '/.well-known/' in url else response({'version': '4.3.7'}))
        self.storage_calls = []
        def storage_get(*args): self.storage_calls.append(args); return self.raw
        self.social = SimpleNamespace(_provider=lambda _: provider,
            oauth=SimpleNamespace(token_for_worker=lambda *_: {'accessToken': 'synthetic', 'providerAccountId': '10@mastodon.social', 'scopes': ['write:statuses', 'write:media']}),
            assets=SimpleNamespace(storage=SimpleNamespace(get=storage_get, get_bounded=lambda w, c, n, limit: storage_get(w, c, n))))

    def checkpoint(self, progress, **kw): self.saved.append((copy.deepcopy(progress), kw))
    def run_step(self, progress=None): return advance(self.social, self.manifest, {'progress': progress}, self.checkpoint, lambda: self.now)

    def test_every_external_checkpoint_carries_the_exact_grant_outside_progress(self):
        grant = {'accessToken': 'synthetic', 'providerAccountId': '10@mastodon.social',
            'scopes': ['write:statuses', 'write:media'], '_mastodonCredentialBinding': 'a' * 64}
        self.social.oauth.token_for_worker = lambda *_: grant
        self.replies = [response({'id': '21', 'url': 'https://mastodon.social/media/21'}), response({'id': '31'})]
        result = self.run_step()
        self.assertEqual(result['state'], 'provider_accepted')
        external = [(progress, kw) for progress, kw in self.saved if kw.get('before_external')]
        self.assertEqual([p['stage'] for p, _ in external], ['media_wait', 'media_upload_attempted', 'publish_attempted'])
        for progress, kw in external:
            self.assertIs(kw['authorization'], grant)
            self.assertNotIn('accessToken', progress)
            self.assertNotIn('_mastodonCredentialBinding', progress)

    def test_mastodon_preview_writer_is_local_bilingual_and_bounds_all_openings(self):
        from postriff_alpha.generation import FixtureAdapter
        for language in ('en', 'zh-Hant'):
            result = FixtureAdapter().generate({'platform': 'Mastodon', 'language': language,
                'facts': [], 'idea': 'SYNTHETIC very long topic ' * 120})
            self.assertLessEqual(len(result['text']), 500)
            self.assertEqual(len(result['openings']), 3)
            self.assertTrue(any('No language model' in warning for warning in result['warnings']))
            for opening in result['openings']:
                self.assertLessEqual(len(result['text'].replace(result['openings'][0], opening, 1)), 500)
            self.assertEqual(result['sourceIds'], [])

    def test_unavailable_verification_obeys_saved_cooldown_without_provider_writes(self):
        from postriff_alpha.domain import AlphaError
        error = AlphaError('Synthetic server cooldown', 503)
        error.mastodon_retry_headers = {'retry-after': '300'}
        checks = []
        def unavailable(*_args): checks.append('verification'); raise error
        self.social.oauth.token_for_worker = unavailable
        result = self.run_step()
        self.assertEqual(result['state'], 'processing'); self.assertEqual(self.calls, [])
        self.assertGreaterEqual(result['progress']['retryAt'], self.now + 300)
        self.assertEqual(self.run_step(result['progress'])['state'], 'processing')
        self.assertEqual(len(checks), 1); self.assertEqual(self.storage_calls, [])
        self.now += 310
        saved = copy.deepcopy(result['progress']); saved['attachments'][0].update(state='ready', id='21')
        saved.update(stage='provider_accepted', reference='31')
        result = self.run_step(saved)
        self.assertEqual(result['state'], 'processing'); self.assertEqual(result['reference'], '31')
        self.assertEqual(result['progress']['attachments'][0]['id'], '21'); self.assertEqual(self.calls, [])
        saved['retryCount'] = 20
        self.assertEqual(self.run_step(saved)['state'], 'held')

    def test_verification_failure_never_retries_an_unknown_external_intent(self):
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.mastodon_publishing import grant_retry
        progress = {'version': 3, 'stage': 'publish_attempted', 'retryCount': 0,
            'attachments': [{'hash': self.asset['hash'], 'state': 'ready', 'id': '21'}]}
        result = grant_retry(self.manifest, {'progress': progress}, self.now, AlphaError('Unavailable', 503))
        self.assertEqual(result['state'], 'uncertain'); self.assertNotIn('retryAt', result['progress'])
        progress['stage'] = 'media_wait'
        result = grant_retry(self.manifest, {'progress': progress}, self.now, AlphaError('Revoked', 409))
        self.assertEqual(result['state'], 'held'); self.assertNotIn('retryAt', result['progress'])

    def test_known_media_id_survives_restart_without_upload_repetition(self):
        self.replies = [response({'id': '21'}, 202)]
        result = self.run_step()
        self.assertEqual(result['state'], 'processing')
        self.assertEqual(self.saved[1][0]['stage'], 'media_upload_attempted')
        self.assertTrue(self.saved[1][1]['before_external'])
        self.assertEqual(result['progress']['attachments'][0]['id'], '21')
        self.now = result['progress']['retryAt'] + 1
        self.replies = [response({'id': '21', 'url': 'https://cdn.mastodon.social/media/21'}), response({'id': '31'})]
        resumed = self.run_step(copy.deepcopy(result['progress']))
        self.assertEqual(resumed['state'], 'provider_accepted')
        self.assertEqual([p for m, p, _ in self.calls if m == 'POST'], ['/api/v2/media', '/api/v1/statuses'])
        self.assertEqual(self.calls[-1][2]['body']['media_ids'], ['21'])
        self.assertEqual(self.storage_calls, [('w', 'file', self.asset['objectName'])])
        self.assertEqual(self.run_step(resumed['progress'])['reference'], '31')
        self.assertEqual(len(self.calls), 3)

    def test_interrupted_upload_intent_never_resends_after_restart(self):
        self.replies = [TimeoutError('synthetic network interruption')]
        with self.assertRaises(TimeoutError): self.run_step()
        progress = self.saved[-1][0]
        self.assertEqual(progress['stage'], 'media_upload_attempted')
        count = len(self.calls)
        self.assertEqual(self.run_step(progress)['state'], 'uncertain')
        self.assertEqual(len(self.calls), count)
        self.assertFalse(can_resume({'state': 'submitting', 'manifest': self.manifest, 'progress': progress}))

    def test_interrupted_status_intent_never_republishes(self):
        self.manifest['media'] = []
        self.replies = [TimeoutError('synthetic network interruption')]
        with self.assertRaises(TimeoutError): self.run_step()
        progress = self.saved[-1][0]
        self.assertEqual(progress['stage'], 'publish_attempted')
        self.assertEqual(self.run_step(progress)['state'], 'uncertain')
        self.assertEqual(len(self.calls), 1)

    def test_definitive_rate_rejection_waits_and_reuses_accepted_media(self):
        self.replies = [response({'id': '21', 'url': 'https://cdn.mastodon.social/media/21'}), response(status=429, headers={'Retry-After': '120'})]
        first = self.run_step()
        self.assertGreaterEqual(first['progress']['retryAt'], self.now + 120)
        self.assertTrue(can_resume({'state': 'processing', 'manifest': self.manifest, 'progress': first['progress']}))
        self.assertEqual(self.run_step(first['progress'])['state'], 'processing')
        self.assertEqual(len(self.calls), 2)
        self.now = first['progress']['retryAt'] + 1; self.replies = [response({'id': '31'})]
        self.assertEqual(self.run_step(first['progress'])['reference'], '31')
        self.assertEqual([p for m, p, _ in self.calls if m == 'POST'].count('/api/v2/media'), 1)

    def test_old_media_endpoint_only_follows_definitive_404(self):
        self.replies = [response(status=404), response({'id': '21', 'url': 'https://cdn.mastodon.social/media/21'}), response({'id': '31'})]
        self.assertEqual(self.run_step()['reference'], '31')
        self.assertEqual([p for _, p, _ in self.calls], ['/api/v2/media', '/api/v1/media', '/api/v1/statuses'])

    def test_changed_bytes_and_wrong_media_progress_stop_before_external_write(self):
        self.raw = b'changed'
        self.assertEqual(self.run_step()['state'], 'held')
        self.assertEqual(self.calls, [])
        progress = {'version': 3, 'stage': 'media_wait', 'attachments': [{'hash': 'b' * 64, 'state': 'ready', 'id': '21'}]}
        with self.assertRaises(Exception): checked_progress(progress, self.manifest)

    def test_queue_verification_accepts_only_the_exact_mastodon_instance_url(self):
        job = {'manifest': self.manifest}
        receipt = {'state': 'verified', 'reference': '31', 'verification': 'provider_lookup', 'confirmed': 'Exact read-back', 'url': 'https://mastodon.social/@alice/31'}
        self.assertEqual(normalize_result(receipt, job, True)['state'], 'verified')
        for url in ('https://mastodon.online/@alice/31', 'https://mastodon.social@127.0.0.1/@alice/31', 'https://mastodon.social/@alice/31?secret=x'):
            self.assertEqual(normalize_result({**receipt, 'url': url}, job, True)['state'], 'uncertain')

    def test_rate_reset_timestamp_and_exponential_backoff_are_bounded(self):
        self.assertGreater(backoff(response(headers={'X-RateLimit-Reset': '2026-10-11T06:00:00Z'}), 1791690000, 0, 'job'), 1791690000)
        self.assertLessEqual(backoff(response(), self.now, 20, 'job'), self.now + 1805)
        self.replies = [response(status=429, headers={'Retry-After': '7200'})]; self.manifest['media'] = []
        self.assertEqual(self.run_step()['state'], 'held')

    def native_progress(self):
        at = datetime.fromtimestamp(self.now + 600, timezone.utc).isoformat()
        self.manifest['publishOptions'] = {'scheduled_at': at}
        return {'version': 3, 'stage': 'native_scheduled', 'scheduledAt': at, 'reference': '41',
                'attachments': [{'hash': self.asset['hash'], 'state': 'ready', 'id': '21'}], 'retryCount': 0}

    def test_native_schedule_pending_is_not_published(self):
        p = self.native_progress()
        self.replies = [response({'id': '41', 'scheduled_at': p['scheduledAt'],
            'params': {'text': self.manifest['payload']['text'], 'visibility': 'public', 'media_ids': ['21']}})]
        result = native_reconcile(self.social._provider(None), '', self.manifest, {'progress': p}, self.now)
        self.assertEqual(result['state'], 'processing')
        self.assertEqual(normalize_result(result, {'manifest': self.manifest}, True)['state'], 'processing')
        self.assertFalse(can_resume({'state': 'processing', 'manifest': self.manifest, 'progress': p}))

    def test_native_schedule_absence_requires_a_unique_exact_media_readback(self):
        p = self.native_progress()
        published = {'id': '51', 'account': {'id': '10'}, 'created_at': p['scheduledAt'], 'content': '<p>An approved post</p>',
            'visibility': 'public', 'sensitive': False, 'spoiler_text': '', 'media_attachments': [{'id': '21'}], 'url': 'https://mastodon.social/@alice/51'}
        self.now += 610
        for rows, expected in [([], 'uncertain'), ([{**published, 'media_attachments': [{'id': '22'}]}], 'uncertain'),
                               ([published, {**published, 'id': '52'}], 'uncertain'), ([published], 'verified')]:
            with self.subTest(expected=expected):
                self.replies = [response(status=404), response(rows)]
                result = native_reconcile(self.social._provider(None), '', self.manifest, {'progress': p}, self.now)
                self.assertEqual(result['state'], expected)
                if expected == 'verified':
                    self.assertEqual(normalize_result(result, {'manifest': self.manifest}, True)['state'], 'verified')
                    self.assertEqual(result['reference'], '51')
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_single_and_native_readback_reject_every_changed_approved_setting(self):
        from datetime import datetime, timedelta
        from postriff_phase2.hosted_social import HostedSocial
        p = self.native_progress()
        self.manifest['publishOptions'].update(visibility='unlisted', sensitive=True, language='en',
            spoiler_text='CW', in_reply_to_id='9', poll={'options': ['A', 'B'], 'multiple': False, 'expires_in': 600},
            quoted_status_id='8')
        published = {'id': '51', 'account': {'id': '10'}, 'created_at': p['scheduledAt'],
            'content': '<p>An approved post</p>', 'visibility': 'unlisted', 'sensitive': True, 'language': 'en',
            'spoiler_text': 'CW', 'in_reply_to_id': '9', 'media_attachments': [{'id': '21'}],
            'poll': {'options': [{'title': 'A'}, {'title': 'B'}], 'multiple': False,
                     'expires_at': (datetime.fromisoformat(p['scheduledAt'].replace('Z', '+00:00')) + timedelta(seconds=600)).isoformat()},
            'quote': {'state': 'accepted', 'quoted_status_id': '8'}}
        self.now += 610
        provider = self.social._provider(None)
        hosted = HostedSocial(self.social.oauth, {})
        for change in ({}, {'language': 'fr'}, {'sensitive': False}, {'in_reply_to_id': None},
                       {'quote': {'state': 'accepted', 'quoted_status_id': '7'}},
                       {'poll': {**published['poll'], 'expires_at': p['scheduledAt']}},
                       {'poll': {**published['poll'], 'expires_at': None}},
                       {'poll': {'multiple': True, 'options': [{'title': 'A'}, {'title': 'B'}]}},
                       {'poll': {'multiple': False, 'options': [{'title': 'A'}, {'title': 'C'}]}}):
            with self.subTest(change=change):
                expected = 'verified' if not change else 'uncertain'
                self.replies = [response(status=404), response([{**published, **change}])]
                self.assertEqual(native_reconcile(provider, '', self.manifest, {'progress': p}, self.now)['state'], expected)
                single = copy.deepcopy(self.manifest); single['publishOptions'].pop('scheduled_at')
                self.replies = [response({**published, **change})]
                job = {'progress': {**p, 'stage': 'provider_accepted', 'reference': '51'}}
                self.assertEqual(hosted._reconcile_wave1(single, provider, '', '51', job)['state'], expected)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_native_lookup_cooldown_keeps_the_known_schedule_without_writes(self):
        p = self.native_progress(); self.replies = [response({}, 429, {'retry-after': '120'})]
        result = native_reconcile(self.social._provider(None), '', self.manifest, {'progress': p}, self.now)
        self.assertEqual(result['state'], 'processing'); self.assertEqual(result['reference'], '41')
        self.assertGreaterEqual(result['progress']['retryAt'], self.now + 120)
        self.assertEqual([method for method, _path, _kwargs in self.calls], ['GET'])

    def test_text_only_native_absence_never_claims_publication(self):
        p = self.native_progress(); p['attachments'] = []; self.manifest['media'] = []
        self.replies = [response(status=404)]
        self.assertEqual(native_reconcile(self.social._provider(None), '', self.manifest, {'progress': p}, self.now)['state'], 'uncertain')

    def test_text_only_native_needs_one_exact_rafii_post_at_the_due_time(self):
        from datetime import datetime, timedelta
        p = self.native_progress(); p['attachments'] = []; self.manifest['media'] = []
        provider = self.social._provider(None); provider.website = 'https://rafii.io'
        due = datetime.fromisoformat(p['scheduledAt'].replace('Z', '+00:00'))
        published = {'id': '51', 'account': {'id': '10'}, 'created_at': (due + timedelta(seconds=14)).isoformat(),
                     'content': '<p>An approved post</p>', 'visibility': 'public', 'sensitive': False, 'spoiler_text': '',
                     'media_attachments': [], 'application': {'name': 'Rafii', 'website': 'https://rafii.io/'},
                     'url': 'https://mastodon.social/@alice/51'}
        self.now += 900
        for rows, expected in [([], 'uncertain'), ([published], 'verified'),
                               ([{**published, 'application': {'name': 'Other', 'website': 'https://other.example'}}], 'uncertain'),
                               ([{**published, 'application': None}], 'uncertain'),
                               ([{**published, 'created_at': (due + timedelta(seconds=301)).isoformat()}], 'uncertain'),
                               ([{**published, 'content': '<p>Another post</p>'}], 'uncertain'),
                               ([published, {**published, 'id': '52'}], 'uncertain')]:
            with self.subTest(rows=len(rows), expected=expected):
                self.replies = [response(status=404), response(rows)]
                result = native_reconcile(provider, '', self.manifest, {'progress': p}, self.now)
                self.assertEqual(result['state'], expected)
                if expected == 'verified':
                    self.assertEqual(result['reference'], '51')
        provider.website = ''
        self.replies = [response(status=404)]
        self.assertEqual(native_reconcile(provider, '', self.manifest, {'progress': p}, self.now)['state'], 'uncertain')
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))
