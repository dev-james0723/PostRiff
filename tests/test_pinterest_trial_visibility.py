"""Private Trial publisher and durable receipt contracts; all accounts, tokens and I/O are synthetic."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.outcomes import normalize_result
from test_youtube_worker_refresh import NOW, WorkerDatabase

SCOPES = ['user_accounts:read', 'boards:read', 'pins:read', 'pins:write']
PIN = '987654321'
BOARD = '1234567'


def manifest():
    return {'workspaceId':'synthetic-workspace', 'channelId':'synthetic-connection', 'platform':'Pinterest',
            'actor':'synthetic-owner', 'providerAccountId':'7654321', 'idempotencyKey':'k' * 64,
            'payload':{'text':'Synthetic review description', 'language':'en'},
            'media':[{'id':'synthetic-asset', 'mime':'image/png', 'bytes':1024, 'alt':'Synthetic image'}],
            'publishOptions':{'boardId':BOARD, 'title':'Synthetic title', 'link':'https://example.com/trial'},
            'timing':{'timestamp':NOW + 120}, 'expiresAt':NOW + 3600}


def fixture(*, private=True, reviewed=False, sandbox=False):
    policy = SimpleNamespace(require_manifest=Mock())
    provider = SimpleNamespace(private_trial=private, production_reviewed=reviewed, execution_enabled=True,
        sandbox=sandbox, trial_policy=policy, publish_required=frozenset(SCOPES),
        identity=Mock(return_value={'providerAccountId':'7654321'}),
        destinations=Mock(return_value=[{'id':BOARD, 'eligible':True}]),
        api=Mock(return_value={'status':201, 'body':{'id':PIN}}))
    contexts = []

    @contextmanager
    def dispatch(m, token, fence, **kwargs):
        assert token == 'SYNTHETIC-ACCESS'
        proof = {}
        contexts.append({'manifest':copy.deepcopy(m), 'fence':fence, 'kwargs':copy.deepcopy(kwargs), 'proof':proof})
        yield proof

    oauth = SimpleNamespace(token_for_worker=Mock(return_value={'accessToken':'SYNTHETIC-ACCESS', 'scopes':SCOPES}),
                            pinterest_dispatch=dispatch)
    social = HostedSocial(oauth, {'pinterest':provider},
        assets=SimpleNamespace(storage=SimpleNamespace(signed_url=Mock(return_value='https://example.com/synthetic.png'))))
    return social, provider, contexts


def readback(m):
    return {'status':200, 'body':{'id':PIN, 'board_id':BOARD, 'title':m['publishOptions']['title'],
        'description':m['payload']['text'], 'link':m['publishOptions']['link'], 'media':{'media_type':'image'}}}


class ReceiptDatabase(WorkerDatabase):
    def execute(self, sql, params=()):
        if sql.startswith('SELECT revision,state FROM public.pr_workspaces'):
            self.result = (1, copy.deepcopy(self.state))
        else:
            return super().execute(sql, params)


class PinterestTrialVisibility(unittest.TestCase):
    def test_unreviewed_private_trial_needs_exact_policy_before_custody_or_provider_reads(self):
        social, provider, _ = fixture()
        m = manifest()
        self.assertIs(social._provider(m), provider)
        provider.trial_policy.require_manifest.assert_called_once_with(m)
        self.assertFalse(provider.production_reviewed)
        provider.trial_policy.require_manifest.side_effect = AlphaError('Synthetic policy refused.', 403)
        changed = m | {'actor':'different-synthetic-actor'}
        self.assertEqual(social.submit(changed)['state'], 'held')
        provider.trial_policy.require_manifest.assert_called_with(changed)
        social.oauth.token_for_worker.assert_not_called()
        provider.identity.assert_not_called()
        provider.api.assert_not_called()

    def test_missing_policy_paused_provider_and_public_unreviewed_provider_cannot_publish(self):
        for change in ('missing', 'paused', 'public', 'malformed-private'):
            with self.subTest(change=change):
                social, provider, _ = fixture()
                if change == 'missing':
                    provider.trial_policy = None
                elif change == 'paused':
                    provider.execution_enabled = False
                else:
                    provider.private_trial = False if change == 'public' else 'true'
                self.assertEqual(social.submit(manifest())['state'], 'held')
                social.oauth.token_for_worker.assert_not_called()
                provider.api.assert_not_called()

    def test_private_official_api_submission_passes_exact_body_to_fence_and_labels_creator_only(self):
        social, provider, contexts = fixture()
        m, fence = manifest(), {'leaseId':'synthetic-lease', 'leaseOwner':'synthetic-worker'}
        original = copy.deepcopy(m)
        result = social.submit(m, dispatch_context=fence)
        self.assertEqual((result['state'], result['reference'], result['visibility']),
                         ('provider_accepted', PIN, 'creator_only_trial'))
        self.assertIn('creator-only Trial', result['confirmed'])
        self.assertFalse(provider.sandbox)
        self.assertFalse(provider.production_reviewed)
        body = provider.api.call_args.kwargs['body']
        self.assertEqual((body['board_id'], body['title'], body['description'], body['link'], body['alt_text']),
                         (BOARD, 'Synthetic title', 'Synthetic review description', 'https://example.com/trial', 'Synthetic image'))
        self.assertEqual(contexts[0]['kwargs'], {'trial_pin':body})
        self.assertEqual(contexts[0]['fence'], fence)
        self.assertEqual(contexts[0]['proof']['pinId'], PIN)
        self.assertEqual(m, original)
        provider.api.assert_called_once()
        self.assertEqual(provider.api.call_args.args[:3], ('SYNTHETIC-ACCESS', 'POST', '/v5/pins'))

    def test_public_context_remains_compatible_without_new_trial_keyword(self):
        social, provider, contexts = fixture(private=False, reviewed=True)
        @contextmanager
        def legacy_dispatch(m, token, fence):
            contexts.append({'legacy':True})
            yield {}
        social.oauth.pinterest_dispatch = legacy_dispatch
        result = social.submit(manifest())
        self.assertEqual(result['visibility'], 'unverified')
        self.assertEqual(contexts, [{'legacy':True}])
        provider.trial_policy.require_manifest.assert_not_called()

    def test_readback_trial_sandbox_and_public_visibility_are_distinct(self):
        for private, reviewed, sandbox, expected in ((True, False, False, 'creator_only_trial'),
                (False, True, True, 'creator_only_sandbox'), (False, True, False, 'unverified')):
            with self.subTest(expected=expected):
                social, provider, _ = fixture(private=private, reviewed=reviewed, sandbox=sandbox)
                m = manifest()
                provider.api.return_value = readback(m)
                result = social.reconcile(m, {'providerReference':PIN})
                self.assertEqual((result['state'], result['visibility']), ('verified', expected))
                self.assertEqual(provider.api.call_args.args[:3], ('SYNTHETIC-ACCESS', 'GET', '/v5/pins/' + PIN))
                if private:
                    self.assertIn('Creator-only Trial', result['confirmed'])
                    self.assertEqual(result['url'], 'https://www.pinterest.com/pin/' + PIN + '/')
                if not private and not sandbox:
                    self.assertIn('Public visibility has not been verified', result['confirmed'])
                normalized = normalize_result(result, {'manifest':m, 'providerReference':PIN}, reconciliation=True)
                self.assertEqual(normalized['visibility'], expected)

    def test_unknown_or_arbitrary_visibility_never_promotes_publication_or_echoes_input(self):
        base = {'state':'verified', 'confirmed':'Synthetic exact lookup.', 'reference':PIN, 'verification':'provider_lookup'}
        for bad in ('public', 'PUBLIC', 'SYNTHETIC-PRIVATE-SECRET', {'secret':'SYNTHETIC-PRIVATE-SECRET'}, True):
            with self.subTest(bad=bad):
                result = normalize_result(base | {'visibility':bad}, {'manifest':manifest()})
                self.assertEqual(result['state'], 'uncertain')
                self.assertNotIn('SYNTHETIC-PRIVATE-SECRET', json.dumps(result))
        other = normalize_result(base | {'visibility':'public'}, {'manifest':{'platform':'LinkedIn'}})
        self.assertEqual(other['state'], 'verified')
        self.assertNotIn('visibility', other)

    def test_changing_runtime_tier_does_not_erase_recorded_creator_only_pin_visibility(self):
        job = {'manifest':manifest(), 'providerReference':PIN, 'providerVisibility':'creator_only_trial'}
        result = normalize_result({'state':'verified', 'confirmed':'Synthetic read-back after runtime change.',
            'reference':PIN, 'verification':'provider_lookup', 'visibility':'unverified'}, job, reconciliation=True)
        self.assertEqual(result['visibility'], 'creator_only_trial')

    @patch('postriff_phase2.hosted_worker.record_published')
    @patch('postriff_phase2.product_events.publish_outcome')
    def test_worker_persists_normalized_trial_visibility_and_keeps_it_during_later_uncertainty(self, _event, _learning):
        db = ReceiptDatabase(1)
        job = db.state['phase2']['jobs'][0]
        job.update(state='submitting', leaseOwner='synthetic-worker', leaseId='synthetic-lease', leaseUntil=NOW + 45)
        job['manifest']['platform'] = 'Pinterest'
        worker = PostgresWorker.__new__(PostgresWorker)
        worker.connection_factory, worker.clock, worker.worker_id = db.connection_factory, lambda:NOW, 'synthetic-worker'
        worker.on_verified = None
        claimed = {'workspaceId':'workspace', 'job':copy.deepcopy(job), 'reconciliation':True}
        result = {'state':'verified', 'confirmed':'Synthetic creator-only Trial lookup.', 'reference':PIN,
                  'verification':'provider_lookup', 'visibility':'creator_only_trial',
                  'url':'https://www.pinterest.com/pin/' + PIN + '/'}
        self.assertTrue(worker.complete(claimed, result))
        saved = db.state['phase2']['jobs'][0]
        self.assertEqual((saved['state'], saved['providerVisibility'], saved['providerReference']),
                         ('verified', 'creator_only_trial', PIN))
        saved.update(state='uncertain', leaseOwner='synthetic-worker', leaseId='synthetic-lease', leaseUntil=NOW + 45)
        claimed['job'] = copy.deepcopy(saved)
        self.assertTrue(worker.complete(claimed, {'state':'uncertain', 'confirmed':'Synthetic lookup unavailable.'}))
        saved = db.state['phase2']['jobs'][0]
        self.assertEqual((saved['state'], saved['providerVisibility']), ('uncertain', 'creator_only_trial'))


if __name__ == '__main__':
    unittest.main()
