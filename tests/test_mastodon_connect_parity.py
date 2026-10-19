"""Injected combined-candidate contracts; never live OAuth or production evidence."""
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_connect import ApplicationCache
from postriff_phase2.oauth import OAuthService
from postriff_phase2.social_connectors import MastodonProvider
from test_hosted_wave1_connectors import BASE, PUBLIC, Wire, ok
import test_hosted_wave1_connectors as wave1


class MastodonConnectParity(unittest.TestCase):
    def test_all_callers_share_strict_cache_without_changing_management_scopes(self):
        from postriff_phase2.mastodon_management import ApplicationCache as ManagementCache
        provider = MastodonProvider(BASE, transport=Mock(), resolver=PUBLIC)
        wave1.ServiceFlows().service({'mastodon': provider})
        self.assertIsInstance(provider.application_cache, ApplicationCache)
        self.assertIs(ManagementCache, ApplicationCache)
        self.assertEqual(provider.capability_scopes('identity'), ['read:accounts'])
        self.assertIn('write:reports', provider.capability_scopes('management'))
        provider.transport.assert_not_called()

    def test_malformed_access_token_and_lifetime_never_create_a_grant(self):
        context = json.dumps({'verifier': 'v', 'instance': 'mastodon.social',
            'clientId': 'client', 'clientSecret': 'secret', 'redirect': BASE + '/cb'})
        cases = [{'access_token': value} for value in (None, False, 42, '', 'bad token', '<html>', 'placeholder')]
        cases += [{'access_token': 'valid', 'expires_in': value}
                  for value in (False, True, 0, -1, 1.5, '3600', 315360001)]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(AlphaError) as error:
                provider = MastodonProvider(BASE, transport=Wire([ok(body)]), resolver=PUBLIC)
                provider.exchange('code', context, BASE + '/cb')
            self.assertEqual(error.exception.status, 502)
        for value in (None, 1, 3600, 315360000):
            with self.subTest(expires=value):
                body = {'access_token': 'valid', 'scope': 'read:accounts', 'expires_in': value}
                provider = MastodonProvider(BASE, transport=Wire([ok(body)]), resolver=PUBLIC)
                grant = provider.exchange('code', context, BASE + '/cb')
                self.assertEqual(grant['expiresIn'], value)
                self.assertEqual(json.loads(grant['accessToken'])['at'], 'valid')

    def test_strict_application_cache_replaces_invalid_custody_and_refuses_bad_registration(self):
        def cache(stored, response):
            cursor = Mock(fetchone=Mock(side_effect=[(True,), stored]))
            @contextmanager
            def connection_factory():
                @contextmanager
                def scoped_cursor():
                    yield cursor
                yield SimpleNamespace(cursor=scoped_cursor)
            service = SimpleNamespace(repository=SimpleNamespace(connection_factory=connection_factory),
                vault=SimpleNamespace(decrypt=lambda value, key: value,
                                      encrypt=Mock(return_value=('encrypted', 'key'))), clock=lambda: 100)
            provider = MastodonProvider(BASE, transport=Mock(return_value=ok(response)), resolver=PUBLIC)
            return ApplicationCache(service, provider), service, provider
        good = {'client_id': 'client', 'client_secret': 'secret'}
        invalid = [{'client_id': 'client', 'client_secret': None},
                   {**good, 'client_secret_expires_at': True},
                   {**good, 'client_secret_expires_at': -1},
                   {**good, 'client_secret_expires_at': None},
                   {**good, 'client_secret_expires_at': 700}]
        for body in invalid:
            with self.subTest(body=body):
                app, service, provider = cache((json.dumps(body), 'key'), good)
                self.assertEqual(app('mastodon.social', BASE + '/cb', ['read:accounts']), good)
                provider.transport.assert_called_once()
                app, service, provider = cache(None, body)
                with self.assertRaises(AlphaError):
                    app('mastodon.social', BASE + '/cb', ['read:accounts'])
                service.vault.encrypt.assert_not_called()
        for expiry in ('absent', 0, 701):
            body = good if expiry == 'absent' else {**good, 'client_secret_expires_at': expiry}
            app, service, provider = cache((json.dumps(body), 'key'), {})
            self.assertEqual(app('mastodon.social', BASE + '/cb', ['read:accounts']), body)
            provider.transport.assert_not_called()

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
