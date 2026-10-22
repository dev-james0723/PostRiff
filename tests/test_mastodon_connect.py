"""Shared lifecycle contracts in the independent management candidate. Never evidence of production or live consent."""
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_connect import ApplicationCache
from postriff_phase2.mastodon_protocol import instance_host
from postriff_phase2.oauth import OAuthService
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.social_connectors import MastodonProvider
from test_hosted_wave1_connectors import BASE, PUBLIC, Wire, ok
import test_hosted_wave1_connectors as wave1


class MastodonConnectContracts(unittest.TestCase):
    def _manual_verification_error(self, code, current):
        cursor = Mock()
        cursor.fetchone.side_effect = [
            ('mastodon', '100@mastodon.social', ['read:accounts'], 'observed-ciphertext', 'key'), current]
        @contextmanager
        def transaction(token, workspace):
            yield cursor, (1, {}, 'owner', False, False, False, False), 'owner'
        repository = SimpleNamespace(transaction=transaction)
        commands = SimpleNamespace(engine=SimpleNamespace(invalidate=Mock()))
        service = OAuthService(repository, commands, SimpleNamespace(fernet=True), {}, BASE)
        service.token_for_worker = Mock(side_effect=AlphaError('Synthetic provider outcome', 503, code=code))
        service.mark_mastodon_revoked = Mock(return_value=current[1])
        return service, cursor, commands

    def test_manual_reverify_transient_error_preserves_grant_and_last_verification(self):
        service, cursor, commands = self._manual_verification_error('mastodon_verification_unavailable', ('observed-ciphertext', False))
        result = service.verify('workspace', 'session', 'connection')
        self.assertEqual(result['state'], 'verification_unavailable')
        self.assertEqual(result['scopes'], ['read:accounts'])
        service.mark_mastodon_revoked.assert_not_called()
        commands.engine.invalidate.assert_not_called()
        self.assertFalse(any(call.args[0].lstrip().upper().startswith('UPDATE') for call in cursor.execute.call_args_list))

    def test_manual_reverify_definitive_revocation_returns_reconnect_state(self):
        service, cursor, commands = self._manual_verification_error('mastodon_authorization_revoked', ('', True))
        result = service.verify('workspace', 'session', 'connection')
        self.assertEqual(result['state'], 'reauthorization_required')
        self.assertFalse(result['identityVerified'])
        self.assertEqual(result['scopes'], [])
        service.mark_mastodon_revoked.assert_called_once_with('workspace', 'connection', expected_ciphertext='observed-ciphertext')

    def test_manual_reverify_error_cannot_overwrite_a_new_consent(self):
        for code in ('mastodon_verification_unavailable', 'mastodon_authorization_revoked'):
            with self.subTest(code=code):
                service, cursor, commands = self._manual_verification_error(code, ('new-consent-ciphertext', False))
                with self.assertRaises(AlphaError) as refused:
                    service.verify('workspace', 'session', 'connection')
                self.assertEqual(refused.exception.status, 409)
                commands.engine.invalidate.assert_not_called()

    def test_management_candidate_preserves_identity_and_requires_all_write_qualifiers(self):
        from itertools import product
        provider = MastodonProvider(BASE, transport=Mock(), resolver=PUBLIC)
        grants = ['read:accounts', 'read:statuses', 'write:statuses', 'write:media']
        for reviewed, tested, permission in product((False, True), repeat=3):
            with self.subTest(reviewed=reviewed, tested=tested, permission=permission):
                provider.production_reviewed = reviewed
                provider.publish_live_tested = tested
                provider.publishing_permission = permission
                matrix = OAuthService._capabilities(provider, 'publish', grants, [], 100)
                self.assertEqual(matrix['identity']['level'], 'Direct')
                ready = reviewed and tested and permission
                self.assertEqual(matrix['publish']['level'] == 'Direct', ready)
                social = HostedSocial(SimpleNamespace(), {'mastodon': provider})
                self.assertIs(social._provider({'platform': 'Mastodon'}), provider if ready else None)
        provider.transport.assert_not_called()

    def test_rejects_url_credentials_paths_ports_and_nonpublic_hosts(self):
        for value in ('https://name:secret@mastodon.social', 'https://mastodon.social/path',
                      'https://mastodon.social?target=local', 'https://mastodon.social:8443',
                      'http://mastodon.social', '127.0.0.1', 'box.local'):
            with self.subTest(value=value), self.assertRaises(AlphaError):
                instance_host(value)
        self.assertEqual(instance_host('@alice@mastodon.online'), 'mastodon.online')

    def test_independent_instances_and_legacy_pkce_compatibility(self):
        for host, version, pkce in (('mastodon.social', '4.3.0', True),
                                    ('mastodon.online', '4.2.9', False)):
            responses = [ok({'version': version})]
            if pkce:
                responses.append(ok({}, 404))
            responses.extend([ok({'client_id': 'client', 'client_secret': 'secret'}),
                              ok({'access_token': 'token', 'scope': 'read:accounts'})])
            wire = Wire(responses)
            provider = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
            begun = provider.begin(BASE + '/cb', 'state', 'verifier', 'challenge', ['read:accounts'], host)
            query = parse_qs(urlsplit(begun['authorizeUrl']).query)
            self.assertEqual('code_challenge' in query, pkce)
            grant = provider.exchange('code', json.dumps({'verifier': 'verifier', **begun['context']}), BASE + '/cb')
            self.assertEqual('code_verifier' in wire.calls[-1]['form'], pkce)
            self.assertEqual(json.loads(grant['accessToken'])['instance'], host)
            self.assertTrue(all(urlsplit(call['url']).hostname == host for call in wire.calls))

    def test_callback_binding_and_issuer_mismatch_fail_before_exchange(self):
        wire = Wire([ok({'version': '4.3.0'}), ok({'issuer': 'https://another.social'})])
        provider = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
        with self.assertRaises(AlphaError):
            provider.begin(BASE + '/cb', 'state', 'verifier', 'challenge', ['read:accounts'], 'mastodon.social')
        self.assertEqual(len(wire.calls), 2)
        wire = Wire([])
        provider.transport = wire
        context = {'verifier': 'v', 'instance': 'mastodon.social', 'clientId': 'c', 'clientSecret': 's', 'redirect': BASE + '/cb'}
        with self.assertRaises(AlphaError):
            provider.exchange('code', json.dumps(context), BASE + '/other')
        self.assertEqual(wire.calls, [])

    def test_application_permissions_cannot_widen_token_grant(self):
        wire = Wire([ok({'id': '100'}), ok({'scopes': ['read', 'write']})])
        provider = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
        token = json.dumps({'v': 1, 'at': 'token', 'instance': 'mastodon.social', 'scope': ['read:accounts']})
        self.assertEqual(provider.inspect_scopes(token, '100@mastodon.social'), ['read:accounts'])

    def test_definitive_401_is_reauthorization_and_outage_is_transient(self):
        token = json.dumps({'v': 1, 'at': 'token', 'instance': 'mastodon.social', 'scope': ['read:accounts']})
        for status, code in ((401, 'mastodon_authorization_revoked'), (503, 'mastodon_verification_unavailable')):
            provider = MastodonProvider(BASE, transport=Wire([ok({}, status)]), resolver=PUBLIC)
            with self.assertRaises(AlphaError) as error:
                provider.identity(token)
            self.assertEqual(error.exception.code, code)

    def test_application_registration_busy_never_contacts_provider(self):
        cursor = Mock(fetchone=Mock(return_value=(False,)))
        @contextmanager
        def connection_factory():
            @contextmanager
            def scoped_cursor():
                yield cursor
            yield SimpleNamespace(cursor=scoped_cursor)
        provider = SimpleNamespace(website=BASE, transport=Mock())
        service = SimpleNamespace(repository=SimpleNamespace(connection_factory=connection_factory))
        with self.assertRaises(AlphaError) as error:
            ApplicationCache(service, provider)('mastodon.social', BASE + '/cb', ['read:accounts'])
        self.assertEqual(error.exception.code, 'mastodon_registration_busy')
        provider.transport.assert_not_called()

    def test_registration_rate_limit_is_named_and_nothing_is_cached(self):
        cursor = Mock(fetchone=Mock(side_effect=[(True,), None]))
        @contextmanager
        def connection_factory():
            @contextmanager
            def scoped_cursor():
                yield cursor
            yield SimpleNamespace(cursor=scoped_cursor)
        provider = MastodonProvider(BASE, transport=Wire([ok({'error': 'Too many requests'}, 429)]), resolver=PUBLIC)
        service = SimpleNamespace(repository=SimpleNamespace(connection_factory=connection_factory), clock=lambda: 100)
        with self.assertRaises(AlphaError) as error:
            ApplicationCache(service, provider)('mastodon.social', BASE + '/cb', ['read:accounts'])
        self.assertEqual((error.exception.status, error.exception.code), (429, 'mastodon_registration_rate_limited'))
        self.assertIn('about 10 minutes', str(error.exception))
        self.assertFalse(any('INSERT' in call.args[0] for call in cursor.execute.call_args_list))

    def test_uncached_registration_rate_limit_uses_retry_after(self):
        wire = Wire([ok({'version': '4.3.0'}), ok({}, 404), {'status': 429, 'body': {}, 'headers': {'Retry-After': '150'}}])
        provider = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
        with self.assertRaises(AlphaError) as error:
            provider.begin(BASE + '/cb', 'state', 'verifier', 'challenge', ['read:accounts'], 'mastodon.social')
        self.assertEqual(error.exception.code, 'mastodon_registration_rate_limited')
        self.assertIn('about 3 minutes', str(error.exception))

    @patch('postriff_phase2.billing.require_plan_capacity', lambda *a, **k: None)
    def test_reconnect_is_workspace_scoped_and_cannot_replace_another_identity(self):
        harness = wave1.ServiceFlows()
        wire = Wire([ok({'version': '4.2.9'}), ok({'client_id': 'c', 'client_secret': 's'}),
                     ok({'access_token': 'token', 'scope': 'read:accounts'}), ok({'id': '200'})])
        service = harness.service({'mastodon': MastodonProvider(BASE, transport=wire, resolver=PUBLIC)})
        service.providers['mastodon'].application_cache = None
        expected = OAuthService._connection_id('mastodon', '100@mastodon.social')
        harness.repo.db.credentials[expected] = {'workspace': 'other', 'provider': 'mastodon',
                                               'account': '100@mastodon.social', 'revoked': False}
        with self.assertRaises(AlphaError):
            service.start('workspace', 'session', 'mastodon', 'identity', inputs={'instance': 'mastodon.social', 'connectionId': expected})
        self.assertEqual(wire.calls, [])
        harness.repo.db.credentials[expected]['workspace'] = 'workspace'
        begun = service.start('workspace', 'session', 'mastodon', 'identity', inputs={'instance': 'mastodon.social', 'connectionId': expected})
        state = parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
        with self.assertRaises(AlphaError) as error:
            service.complete('workspace', 'session', 'mastodon', state, 'code')
        self.assertEqual(error.exception.code, 'mastodon_account_changed')
        self.assertEqual(set(harness.repo.db.credentials), {expected})
        with self.assertRaises(AlphaError):
            service.complete('workspace', 'session', 'mastodon', state, 'code')
        self.assertEqual(len(wire.calls), 4)  # committed one-use state prevents a repeated exchange
