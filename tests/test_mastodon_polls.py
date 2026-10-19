"""Synthetic native-poll custody; no live provider, OAuth or production claims.

Only PollControlTests.test_exact_fields_and_denials is a lightweight injected
control. Store/dispatch classes are cloud-only integration candidates.
"""
import ast
import copy
from datetime import datetime, timezone
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'postriff_phase2'


class Refusal(Exception):
    def __init__(self, message, status=400, **kwargs):
        super().__init__(message)
        self.status = status


def actual_function(filename, name, namespace):
    tree = ast.parse((SOURCE / filename).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'AlphaError': Refusal, **namespace}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), filename, 'exec'), scope)
    return scope[name]


class PollControlTests(unittest.TestCase):
    def test_exact_fields_and_denials(self):
        normalize = actual_function('mastodon_protocol.py', 'status_options', {
            're': re, 'datetime': datetime, 'timezone': timezone,
            'VISIBILITIES': ('public', 'unlisted', 'private', 'direct'), 'ID': re.compile(r'[0-9]{1,40}\Z')})
        bind = actual_function('mastodon_polls.py', 'binding', {'status_options': normalize})
        variant = {'platform': 'Mastodon', 'format': 'mastodon.poll', 'text': 'Which?',
                   'native': {'platform': 'Mastodon', 'formatId': 'mastodon.poll',
                              'fields': {'question': 'Which?', 'options': ['One', 'Two']}}}
        options = {'poll': {'options': ['One', 'Two'], 'expires_in': 600, 'multiple': True, 'hide_totals': True}}
        self.assertEqual(bind(variant, options)['options'], ['One', 'Two'])
        variant['native']['fields']['options'] = [{'index': 1, 'text': 'One'}, {'index': 2, 'text': 'Two'}]
        self.assertEqual(bind(variant, options)['options'], ['One', 'Two'])
        for changed in (None, {}, {'poll': {**options['poll'], 'options': ['Two', 'One']}},
                        {'poll': {**options['poll'], 'expires_in': True}},
                        {'poll': {**options['poll'], 'options': ['One', ' ']}},
                        {'poll': {**options['poll'], 'options': ['One']}},
                        {'poll': {**options['poll'], 'options': ['a', 'b', 'c', 'd', 'e']}},
                        {'poll': {**options['poll'], 'hide_totals': 'false'}},
                        {'poll': {**options['poll'], 'unreviewed': 'discard me'}}):
            with self.subTest(changed=changed), self.assertRaises(Refusal): bind(variant, changed)
        with self.assertRaises(Refusal): bind(variant, options, media=[{'id': 'attachment'}])
        with self.assertRaises(Refusal):
            normalize(options, capabilities={'polls': True, 'pollLimits': {'max_options': 1}})
        changed = copy.deepcopy(variant); changed['native']['fields']['question'] = 'Other?'
        with self.assertRaises(Refusal): bind(changed, options)
        self.assertIsNone(bind({'platform': 'LinkedIn'}, None))


class NativePollCustodyTests(unittest.TestCase):
    """Actual Store draft->review->approval plus injected provider; cloud only."""
    def setUp(self):
        from test_postriff_phase2 import Phase2Acceptance
        from postriff_phase2.creation_capabilities import native_draft, projection
        from postriff_phase2.coworker import flags
        self.h = Phase2Acceptance(methodName='runTest'); self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.h.draft(); self.h.channel()
        self.state = copy.deepcopy(self.h.j.state)
        self.variant = self.state['variants'][0]
        self.variant.update(platform='Mastodon', format='mastodon.poll', text='Which is your choice?',
                            nativeFields={'question': 'Which is your choice?', 'options': [{'index': 1, 'text': 'One'}, {'index': 2, 'text': 'Two'}]})
        flags.attach({'RAFII_CREATION_ALL_PLATFORMS_ENABLED': 'true'})
        try: self.variant['native'] = native_draft(self.variant, proj=projection())
        finally: flags.attach(None)
        self.channel = self.state['phase2']['channels'][-1]
        self.channel.update(platform='Mastodon', account='Synthetic poll account',
                            providerAccountId='10@mastodon.social', scopes=['read:accounts', 'write:statuses', 'write:media'])
        self.options = {'visibility': 'unlisted', 'poll': {'options': ['One', 'Two'], 'expires_in': 600,
                                                        'multiple': True, 'hide_totals': True}}
        self.request = {'variantId': self.variant['id'], 'channelId': self.channel['id'],
                        'localTime': datetime.fromtimestamp(self.h.now + 600, timezone.utc).replace(tzinfo=None).isoformat(),
                        'timeZone': 'UTC', 'acknowledgedWarnings': self.variant['warnings'], 'publishOptions': self.options}
        self.device = {'user_id': 'ordinary-poll-reviewer'}

    def review(self):
        self.h.store.apply_phase2(None, self.state, 'review', self.request, self.device)
        return self.state['phase2']['reviews'][-1]

    def approve(self, review, **changes):
        self.h.store.apply_phase2(None, self.state, 'approve', {
            'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True, **changes}, self.device)

    def test_exact_native_fields_are_frozen_and_duplicate_approval_has_one_job(self):
        from postriff_phase2.contracts import digest
        review = self.review()
        self.assertEqual(review['digest'], digest(review['manifest']))
        self.assertEqual(review['manifest']['mastodonNativePoll']['options'], ['One', 'Two'])
        self.assertEqual(review['manifest']['publishOptions']['poll'], self.options['poll'])
        self.assertEqual(review['manifest']['actor'], self.device['user_id'])
        self.approve(review); self.approve(review)
        self.assertEqual(len(self.state['phase2']['jobs']), 1)
        self.assertEqual(self.state['phase2']['jobs'][0]['approvalDigest'], review['digest'])

    def test_no_approval_cannot_create_job(self):
        from postriff_alpha.domain import AlphaError
        review = self.review()
        self.assertEqual(self.state['phase2']['jobs'], [])
        for changes in ({'confirmed': False}, {'digest': '0' * 64}):
            with self.assertRaises(AlphaError): self.approve(review, **changes)
        self.assertEqual(self.state['phase2']['jobs'], [])

    def test_preview_tamper_duration_and_draft_choices_invalidate_review(self):
        from postriff_alpha.domain import AlphaError
        review = self.review()
        review['manifest']['publishOptions']['poll']['expires_in'] += 1
        with self.assertRaises(AlphaError): self.approve(review)
        review['manifest']['publishOptions']['poll']['expires_in'] -= 1
        self.variant['native']['fields']['options'].reverse()
        with self.assertRaises(AlphaError): self.approve(review)
        self.assertEqual(self.state['phase2']['jobs'], [])

    def test_changed_question_missing_choices_and_changed_review_choices_are_refused(self):
        from postriff_alpha.domain import AlphaError
        for mutate in ('question', 'choices', 'review'):
            variant, options = copy.deepcopy(self.variant), copy.deepcopy(self.options)
            if mutate == 'question': self.variant['native']['fields']['question'] = 'Changed?'
            elif mutate == 'choices': self.variant['native']['fields']['options'] = None
            else: self.options['poll']['options'].reverse()
            with self.subTest(mutate=mutate), self.assertRaises(AlphaError): self.review()
            self.variant.clear(); self.variant.update(variant)
            self.options.clear(); self.options.update(options)

    def test_approved_payload_reaches_provider_with_exact_key_and_grant_checkpoint(self):
        import hashlib
        from test_mastodon_publishing import DurablePublishingTests, response
        from postriff_phase2.mastodon_publishing import advance
        review = self.review(); self.approve(review)
        job = self.state['phase2']['jobs'][0]
        provider_fixture = DurablePublishingTests(methodName='runTest'); provider_fixture.setUp()
        provider_fixture.replies = [response({'id': '31'})]
        result = advance(provider_fixture.social, job['manifest'], job, provider_fixture.checkpoint, lambda: self.h.now)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(len(provider_fixture.calls), 1)
        method, path, kwargs = provider_fixture.calls[0]
        self.assertEqual((method, path), ('POST', '/api/v1/statuses'))
        self.assertEqual(kwargs['body']['poll'], self.options['poll'])
        self.assertEqual(kwargs['body']['status'], self.variant['text'])
        self.assertEqual(kwargs['body'].get('media_ids', []), [])
        self.assertEqual(kwargs['headers']['Idempotency-Key'], hashlib.sha256(job['manifest']['idempotencyKey'].encode()).hexdigest())
        external = [kw for _, kw in provider_fixture.saved if kw.get('before_external')]
        self.assertTrue(external)
        self.assertTrue(all(kw['authorization']['providerAccountId'] == job['manifest']['providerAccountId'] for kw in external))

    def test_server_limits_are_rechecked_before_any_write(self):
        from postriff_alpha.domain import AlphaError
        from test_mastodon_publishing import DurablePublishingTests, response
        from postriff_phase2.mastodon_publishing import advance
        review = self.review(); self.approve(review)
        fixture = DurablePublishingTests(methodName='runTest'); fixture.setUp()
        provider = fixture.social._provider({})
        provider.transport = lambda *args, **kwargs: response({'version': '4.3.7', 'configuration': {'polls': {
            'max_options': 4, 'max_characters_per_option': 50, 'min_expiration': 1000, 'max_expiration': 2000}}}) if '/.well-known/' not in args[1] else response(status=404)
        job = self.state['phase2']['jobs'][0]
        with self.assertRaises(AlphaError):
            advance(fixture.social, job['manifest'], job, fixture.checkpoint, lambda: self.h.now)
        self.assertEqual(fixture.calls, [])
        self.assertFalse(any(kw.get('before_external') for _, kw in fixture.saved))

    def test_reconnected_account_cannot_receive_approved_poll(self):
        from test_mastodon_publishing import DurablePublishingTests
        from postriff_phase2.mastodon_publishing import advance
        review = self.review(); self.approve(review)
        fixture = DurablePublishingTests(methodName='runTest'); fixture.setUp()
        fixture.social.oauth.token_for_worker = lambda *_: {'accessToken': 'synthetic',
            'providerAccountId': 'another@mastodon.social', 'scopes': ['write:statuses', 'write:media']}
        job = self.state['phase2']['jobs'][0]
        result = advance(fixture.social, job['manifest'], job, fixture.checkpoint, lambda: self.h.now)
        self.assertEqual(result['state'], 'held')
        self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.saved, [])

    def test_poll_never_bypasses_independent_write_release_gate(self):
        from test_mastodon_write_release import method
        select = method('hosted_social.py', 'HostedSocial', '_provider',
                        {'HOSTED_PUBLISHERS': {'Mastodon': 'mastodon'}})
        review = self.review()
        provider = SimpleNamespace(id='mastodon', execution_enabled=True,
            production_reviewed=True, publish_live_tested=True, publishing_permission=True,
            account_scoped_direct=False, publisher=None)
        social = SimpleNamespace(providers={'mastodon': provider})
        for flag in ('production_reviewed', 'publish_live_tested', 'publishing_permission'):
            setattr(provider, flag, False)
            self.assertIsNone(select(social, review['manifest']))
            setattr(provider, flag, True)
        self.assertIs(select(social, review['manifest']), provider)
