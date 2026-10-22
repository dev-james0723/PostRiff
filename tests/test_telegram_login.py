"""Offline cryptographic and consent contracts. These are not Telegram E2E."""
import base64
import json
import unittest
from contextlib import contextmanager
from unittest import mock
from types import SimpleNamespace
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from postriff_alpha.domain import AlphaError
from postriff_phase2.telegram.login import ISSUER, TelegramLogin, verify_id_token
from postriff_phase2.telegram.controls import DEFAULT, present, TelegramControls
from postriff_phase2.telegram.managed import ManagedBots


def encode(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


class TelegramLoginSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = cls.key.public_key().public_numbers()
        cls.jwks = {'keys': [{'kid': 'test', 'kty': 'RSA', 'alg': 'RS256', 'use': 'sig',
                             'n': encode(public.n.to_bytes(256, 'big')), 'e': encode(public.e.to_bytes(3, 'big'))}]}

    def token(self, patch=None, header=None):
        claims = {'iss': ISSUER, 'aud': '123456', 'sub': '100001', 'id': 778899,
                  'iat': 1000, 'exp': 2000, 'name': 'Test owner', 'preferred_username': 'owner',
                  **(patch or {})}
        raw = encode(json.dumps(header or {'alg': 'RS256', 'kid': 'test'}).encode()) + '.' + encode(json.dumps(claims).encode())
        signature = self.key.sign(raw.encode(), padding.PKCS1v15(), hashes.SHA256())
        return raw + '.' + encode(signature)

    def test_verified_identity_does_not_retain_tokens_phone_or_private_chats(self):
        result = verify_id_token(self.token({'phone_number': '+1000000', 'access_token': 'do-not-retain'}), self.jwks, '123456', 1500)
        self.assertEqual(result['telegramUserId'], '778899')
        self.assertEqual(set(result), {'subject', 'telegramUserId', 'name', 'username'})

    def test_wrong_issuer_audience_expiration_and_numeric_types_fail_closed(self):
        for patch in ({'iss': 'https://evil.example'}, {'aud': 'other-bot'}, {'aud': ['123456', 'evil']},
                      {'exp': 1500}, {'exp': True}, {'iat': 1531}, {'iat': 2500}, {'id': True},
                      {'sub': ''}, {'id': -1}, {'nbf': True}, {'nbf': 1600}, {'exp': float('nan')}):
            with self.subTest(patch=patch), self.assertRaises(AlphaError):
                verify_id_token(self.token(patch), self.jwks, '123456', 1500)

    def test_algorithm_substitution_unsigned_and_remote_keys_are_rejected(self):
        for alg in ('none', 'HS256', 'ES256'):
            with self.subTest(alg=alg), self.assertRaises(AlphaError):
                verify_id_token(self.token(header={'alg': alg, 'kid': 'test', 'jku': 'https://evil.example'}), self.jwks, '123456', 1500)

    def test_invalid_signature_and_unknown_key_rejected(self):
        token = self.token()
        with self.assertRaises(AlphaError):
            verify_id_token(token[:-5] + 'abcde', self.jwks, '123456', 1500)
        with self.assertRaises(AlphaError):
            verify_id_token(self.token(header={'alg': 'RS256', 'kid': 'missing'}), self.jwks, '123456', 1500)

    def test_login_configuration_pins_an_https_origin(self):
        for base in ('http://rafii.io', 'https://rafii.io/evil', 'https://user@rafii.io', 'https://rafii.io?x=1'):
            telegram = SimpleNamespace(repository=None, vault=None, oauth=SimpleNamespace(public_base_url=base))
            login = TelegramLogin(telegram, {'POSTRIFF_TELEGRAM_LOGIN_CLIENT_ID': '123456', 'POSTRIFF_TELEGRAM_LOGIN_CLIENT_SECRET': 'test'})
            self.assertFalse(login.configured())

    def test_production_login_returns_to_rafii_without_repointing_bot_webhook(self):
        webhook_origin = 'https://postriff-phase2-private.vercel.app'
        telegram = SimpleNamespace(repository=None, vault=None, oauth=SimpleNamespace(public_base_url=webhook_origin))
        login = TelegramLogin(telegram, {'VERCEL_ENV': 'production', 'POSTRIFF_TELEGRAM_LOGIN_CLIENT_ID': '123456',
                                       'POSTRIFF_TELEGRAM_LOGIN_CLIENT_SECRET': 'test'})
        self.assertTrue(login.configured())
        self.assertEqual(login.base, 'https://rafii.io')
        self.assertEqual(telegram.oauth.public_base_url, webhook_origin)

    def test_canary_callback_requires_actual_production_binding_and_active_grant(self):
        from postriff_phase2.social_release import PRODUCTION_PROJECT, PRODUCTION_REF, PRODUCTION_URL
        provider = SimpleNamespace(candidate_scope={'expiresAt': 1600, 'workspaceId': 'owner-workspace', 'actorId': 'owner'})
        telegram = SimpleNamespace(repository=None, vault=None, oauth=SimpleNamespace(public_base_url='https://rafii.io', providers={'telegram': provider}))
        values = {'VERCEL_ENV': 'production', 'VERCEL_PROJECT_ID': PRODUCTION_PROJECT,
                  'POSTRIFF_SUPABASE_URL': PRODUCTION_URL, 'NEXT_PUBLIC_SUPABASE_URL': PRODUCTION_URL,
                  'POSTRIFF_DATABASE_URL': 'host=db.' + PRODUCTION_REF + '.supabase.co user=postgres sslmode=require',
                  'VERCEL_URL': 'postriff-phase2-private-owner-acceptance.vercel.app',
                  'POSTRIFF_TELEGRAM_LOGIN_CLIENT_ID': '123456', 'POSTRIFF_TELEGRAM_LOGIN_CLIENT_SECRET': 'test',
                  'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'true', 'POSTRIFF_TELEGRAM_LOGIN_USE_DEPLOYMENT_ORIGIN': 'true'}
        login = TelegramLogin(telegram, values, clock=lambda: 1500)
        self.assertTrue(login.configured())
        self.assertEqual(login.base, 'https://' + values['VERCEL_URL'])
        self.assertEqual(telegram.oauth.public_base_url, 'https://rafii.io')
        # Expiry must be checked again on a reused Fluid Compute instance.
        login.clock = lambda: 1600
        self.assertFalse(login.configured())
        @contextmanager
        def transaction(_token, _workspace):
            yield mock.Mock(), None, 'owner'
        telegram.repository = SimpleNamespace(transaction=transaction)
        with mock.patch('postriff_phase2.hosted._membership', return_value=SimpleNamespace(allows=lambda _action: True)):
            for workspace, actor in (('foreign-workspace', 'owner'), ('owner-workspace', 'foreign-member')):
                @contextmanager
                def wrong_scope_transaction(_token, _workspace):
                    yield mock.Mock(), None, actor
                telegram.repository.transaction = wrong_scope_transaction
                rejected = TelegramLogin(telegram, values, clock=lambda: 1500)
                with self.subTest(workspace=workspace, actor=actor), self.assertRaises(AlphaError) as error:
                    rejected.start(workspace, 'owner-session')
                self.assertEqual(error.exception.status, 403)
        for patch in ({'VERCEL_ENV': 'preview'}, {'VERCEL_PROJECT_ID': 'unverified'},
                      {'POSTRIFF_DATABASE_URL': ''}, {'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'false'},
                      {'VERCEL_URL': 'rafii-consumer-staging-qa.vercel.app'}, {'VERCEL_URL': 'attacker.example'},
                      {'VERCEL_URL': 'postriff-phase2-private-qa.vercel.app/path'}):
            with self.subTest(patch=patch):
                self.assertFalse(TelegramLogin(telegram, {**values, **patch}, clock=lambda: 1500).configured())
        for scope in (None, {}, {'expiresAt': 1500}, {'expiresAt': True}, {'expiresAt': float('nan')}, {'expiresAt': 88001}):
            provider.candidate_scope = scope
            with self.subTest(scope=scope):
                self.assertFalse(TelegramLogin(telegram, values, clock=lambda: 1500).configured())

    def test_automation_default_is_paused_and_requires_approval(self):
        self.assertEqual(present(None), DEFAULT)
        self.assertTrue(DEFAULT['paused'])
        self.assertEqual(DEFAULT['approvalPolicy'], 'always')

    def test_unimplemented_automatic_actions_cannot_receive_consent(self):
        controls = TelegramControls(SimpleNamespace(repository=None))
        for action in ('reply', 'moderate'):
            with self.subTest(action=action), self.assertRaises(AlphaError):
                controls.set('workspace', 'actor', {'paused': True, 'allowedActions': [action]})

    def test_managed_access_ignores_provider_extraneous_identity_fields(self):
        self.assertEqual(ManagedBots.normalize_access({'is_access_restricted': True,
            'added_users': [{'id': 778899, 'first_name': 'Not retained', 'phone_number': 'Not retained'}]}),
            {'restricted': True, 'addedUserIds': [778899]})
        self.assertEqual(ManagedBots.normalize_access({'is_access_restricted': False,
            'added_users': [{'id': 778899}]}), {'restricted': False, 'addedUserIds': []})
        for value in ({'is_access_restricted': 1}, {'is_access_restricted': True, 'added_users': [{'id': True}]}):
            with self.subTest(value=value), self.assertRaises(AlphaError):
                ManagedBots.normalize_access(value)


if __name__ == '__main__':
    unittest.main()
