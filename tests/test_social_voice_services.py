"""Hosted orchestration contracts with in-memory persistence and synthetic transport.

Exercises real permission, source, receipt and model adapters without a database or
provider account. Live OAuth and PostgreSQL tests are separate deployment gates.
"""
import copy
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2 import social_history, voice_ai, voice_sources
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.permissions import Membership, require
from postriff_phase2.providers import InstagramProvider
from test_postriff_voice_analysis import add_sample
from test_postriff_providers import Recorder


class Repository:
    def __init__(self):
        self.state = initial_phase2_state('workspace', 'owner', 'Owner', 'studio', 100)
        self.revision, self.role = 1, 'owner'
        self.credential = None
        self.cur = SimpleNamespace(execute=Mock(), fetchone=lambda: self.credential)

    @contextmanager
    def transaction(self, token, workspace):
        if token != 'session' or workspace != 'workspace':
            raise AlphaError('Workspace unavailable.', 403)
        yield self.cur, (self.revision, self.state, self.role, False, False, False, False), 'owner'

    def command(self, workspace, token, revision, command, requirement='edit', after=None, **kwargs):
        with self.transaction(token, workspace):
            require(Membership(self.role), requirement)
            if revision != self.revision:
                raise AlphaError('Workspace changed.', 409)
            state = command(copy.deepcopy(self.state), 'owner')
            if after:
                after(self.cur, state, 'owner')
            self.state, self.revision = state, self.revision + 1
            return {'state': state, 'revision': self.revision}

    @contextmanager
    def connection_factory(self):
        @contextmanager
        def cursor():
            yield self.cur
        yield SimpleNamespace(cursor=cursor)


class HostedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        self.sid = add_sample(self.repo.state, 'Hello friends. My own writing.', 'one')
        self.route = 'cloud:test-provider:test-model'
        voice_sources.apply_action(self.repo.state, 'voice_sample_grant', {'sourceId': self.sid, 'grants': [{'purpose': 'analysis', 'route': self.route}], 'confirmed': True}, 'owner', 100)
        self.output = {'dimensions': [{'id': 'openings', 'observation': 'Uses a friendly greeting.', 'support': [self.sid], 'counterEvidence': [], 'quotes': [{'sourceId': self.sid, 'text': 'Hello friends.'}]}]}
        self.runtime = SimpleNamespace(provider='test-provider', analyze_voice=Mock(return_value={'output': self.output, 'usage': {'costUsd': 0.0002}}), quote_voice_analysis=Mock(return_value=1000))
        self.ledger = SimpleNamespace(reserve=Mock(return_value={'reservationId': 'reservation', 'duplicate': False}), settle=Mock())
        self.service = SimpleNamespace(repository=self.repo, clock=lambda: 200, ledger=self.ledger,
                                       ideas=SimpleNamespace(_select_runtime=lambda model: self.runtime), _present=lambda saved: saved)
        self.handler = voice_ai.HostedVoiceAnalysis(self.service)
        self.payload = {'confirmed': True, 'sourceIds': [self.sid], 'model': 'test-model', 'route': self.route, 'requestId': 'unique-request-12345'}
        self.throttle = patch('postriff_phase2.hosted.throttle')
        self.throttle.start()
        self.addCleanup(self.throttle.stop)

    def test_success_proposes_without_activating_and_settles_one_usage(self):
        active = self.repo.state['speaker']['activeRevision']
        saved = self.handler.run('workspace', 'session', 1, self.payload)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(saved['state']['speaker']['activeRevision'], active)
        self.assertEqual(saved['state']['speaker']['provisional']['analysisMethod'], 'ai')
        self.runtime.analyze_voice.assert_called_once()
        self.assertEqual(self.ledger.settle.call_args.args[3:5], ('completed', 200))

    def test_non_owner_no_confirmation_and_foreign_workspace_never_call_model(self):
        for role, workspace, confirmed in [('viewer', 'workspace', True), ('owner', 'foreign', True), ('owner', 'workspace', False)]:
            self.repo.role = role
            with self.subTest(role=role, workspace=workspace, confirmed=confirmed), self.assertRaises(AlphaError):
                self.handler.run(workspace, 'session', 1, {**self.payload, 'confirmed': confirmed})
        self.runtime.analyze_voice.assert_not_called()
        self.ledger.reserve.assert_not_called()

    def test_budget_refusal_and_duplicate_reservation_never_call_model(self):
        self.ledger.reserve.side_effect = AlphaError('Budget approval required.', 402)
        with self.assertRaises(AlphaError):
            self.handler.run('workspace', 'session', 1, self.payload)
        self.ledger.reserve.side_effect = None
        self.ledger.reserve.return_value['duplicate'] = True
        with self.assertRaises(AlphaError):
            self.handler.run('workspace', 'session', 1, self.payload)
        self.runtime.analyze_voice.assert_not_called()

    def test_revocation_during_call_prevents_persistence_but_settles_usage(self):
        def execute(*args):
            voice_sources.apply_action(self.repo.state, 'voice_sample_revoke', {'sourceId': self.sid, 'confirmed': True}, 'owner', 201)
            return {'output': self.output, 'usage': {'costUsd': 0.0002}}
        self.runtime.analyze_voice.side_effect = execute
        with self.assertRaises(AlphaError):
            self.handler.run('workspace', 'session', 1, self.payload)
        self.assertIsNone(self.repo.state['speaker']['provisional'])
        self.assertEqual(self.ledger.settle.call_args.args[3:5], ('failed', 200))

    def test_unknown_transport_keeps_reservation_instead_of_reporting_zero_cost(self):
        self.runtime.analyze_voice.side_effect = AlphaError('Provider outcome unknown.', 502)
        with self.assertRaises(AlphaError):
            self.handler.run('workspace', 'session', 1, self.payload)
        self.assertEqual(self.ledger.settle.call_args.args[3:5], ('unknown', None))

    def test_manual_guidance_is_distinguished_from_model_observations(self):
        self.handler.run('workspace', 'session', 1, self.payload)
        HostedPhase2Commands(clock=lambda: 202)(self.repo.state, 'owner', 'profile_decide', {'decision': 'approve', 'note': 'Prefer short, concrete openings.'})
        profile = self.repo.state['speaker']['revisions'][-1]['profile']
        self.assertEqual(profile['observations'], ['Prefer short, concrete openings.'])
        self.assertEqual(profile['observationsBasis'], 'owner_edited')


class HistoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        self.vault = CredentialVault(CredentialVault.generate_key())
        encrypted, key = self.vault.encrypt('synthetic-token')
        self.repo.credential = ('instagram', '1789', encrypted, key)
        self.transport = Recorder([])
        self.adapter = InstagramProvider('id', 'secret', transport=self.transport)
        self.adapter.identity = Mock(return_value={'providerAccountId': '1789'})
        self.oauth = OAuthService(self.repo, HostedPhase2Commands(clock=lambda: 200), self.vault, {'instagram': self.adapter}, 'https://app.example', clock=lambda: 200)
        self.oauth.token_for_worker = Mock(return_value={'accessToken': 'synthetic-token', 'scopes': ['instagram_business_basic']})
        self.throttle = patch('postriff_phase2.hosted.throttle')
        self.throttle.start()
        self.addCleanup(self.throttle.stop)

    def test_verified_page_import_is_retained_only_and_deduplicates(self):
        response = {'status': 200, 'body': {'data': [{'id': '22', 'caption': 'Original caption.'}]}}
        self.adapter.transport = Recorder([response, response, response])
        page = self.oauth.history.preview('workspace', 'session', 'connection', {'confirmed': True})
        self.assertFalse(any(source.get('kind') == 'voice_sample' for source in self.repo.state['sources']))
        payload = {'confirmedAuthorship': True, 'receipt': page['receipt'], 'postIds': ['22'], 'expectedRevision': 1}
        saved = self.oauth.history.retain('workspace', 'session', 'connection', payload)
        sample = saved['state']['sources'][-1]
        self.assertEqual(sample['voiceOrigin'], 'official_api')
        self.assertFalse(sample['selected'])
        self.assertEqual(sample['useGrants'], [])
        self.assertEqual(sample['connectionId'], 'connection')
        self.oauth.history.retain('workspace', 'session', 'connection', {**payload, 'expectedRevision': 2})
        self.assertEqual(len([source for source in self.repo.state['sources'] if source.get('kind') == 'voice_sample']), 1)

    def test_foreign_workspace_cannot_trigger_token_decryption_or_provider_read(self):
        with self.assertRaises(AlphaError):
            self.oauth.history.preview('foreign', 'session', 'connection', {'confirmed': True})
        self.oauth.token_for_worker.assert_not_called()
        self.adapter.identity.assert_not_called()

    def test_identity_drift_does_not_return_other_accounts_posts(self):
        self.adapter.identity.return_value = {'providerAccountId': '9999'}
        with self.assertRaises(AlphaError):
            self.oauth.history.preview('workspace', 'session', 'connection', {'confirmed': True})
        self.assertEqual(self.transport.calls, [])

    def test_revoke_removes_stored_ai_evidence_quotes_too(self):
        sid = add_sample(self.repo.state, 'Original private phrase.', 'one')
        self.repo.state['speaker']['provisional'] = {'status': 'proposed', 'evidenceSourceIds': [sid], 'dimensions': [{'id': 'openings', 'quotes': [{'sourceId': sid, 'text': 'Original private phrase.'}]}]}
        voice_sources.apply_action(self.repo.state, 'voice_sample_revoke', {'sourceId': sid, 'confirmed': True}, 'owner', 201)
        self.assertNotIn('Original private phrase.', json.dumps(self.repo.state['speaker']))

    def test_connection_revocation_only_purges_its_official_samples(self):
        self.assertTrue(callable(getattr(social_history, 'revoke_connection_samples', None)))
        first = add_sample(self.repo.state, 'First private text.', 'one')
        second = add_sample(self.repo.state, 'Manual text.', 'two')
        self.repo.state['sources'][-2].update(voiceOrigin='official_api', connectionId='connection')
        count = social_history.revoke_connection_samples(self.repo.state, 'connection', 'owner', 200)
        self.assertEqual(count, 1)
        sources = {source['id']: source for source in self.repo.state['sources']}
        self.assertEqual(sources[first]['text'], '')
        self.assertEqual(sources[second]['text'], 'Manual text.')


if __name__ == '__main__':
    unittest.main()
