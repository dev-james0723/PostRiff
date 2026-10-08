"""Disposable SQL + synthetic Facebook transport. No live provider/public-access evidence."""
import copy
import json
import time
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import postgres_repository as fixture
from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.wave3_connectors import FacebookPagesProvider
from test_hosted_wave1_connectors import Wire, ok


class FacebookConnectionSQL(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.before = copy.deepcopy(fixture.service.repository.get(fixture.wid, 'fixture-one')['state'])
        self.adapter = FacebookPagesProvider('synthetic-app', 'synthetic-secret')
        self.blob = json.dumps({'v': 1, 'user': '777', 'ut': 'SYNTHETIC', 'scope': ['pages_show_list'], 'page': None})
        self.adapter.exchange = Mock(return_value={'accessToken': self.blob, 'scopes': ['pages_show_list'], 'expiresIn': 3600})
        self.adapter.identity = Mock(return_value={'providerAccountId': '777', 'handle': 'Synthetic Person', 'accountType': 'person'})
        self.oauth = OAuthService(fixture.service.repository, fixture.service.commands, CredentialVault(CredentialVault.generate_key()),
                                  {'facebook': self.adapter}, 'https://example.invalid', clock=lambda: self.now)
        self.oauth._keep_picture = Mock()
        begun = self.oauth.start(fixture.wid, 'fixture-one', 'facebook', 'identity')
        state = parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
        self.connection_id = self.oauth.complete(fixture.wid, 'fixture-one', 'facebook', state, 'synthetic-code')['connectionId']
        self.page = {'id': '10001', 'name': 'Synthetic Page', 'tasks': ['ANALYZE']}

    def tearDown(self):
        with fixture.connection() as db:
            db.execute('DELETE FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (fixture.wid, self.connection_id))
            db.execute('DELETE FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s', (fixture.wid, self.connection_id))
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(self.before), fixture.wid))
            db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s", (fixture.wid, fixture.one))

    def responses(self, pages):
        return [ok({'data': {'app_id': 'synthetic-app', 'user_id': '777', 'is_valid': True, 'expires_at': self.now + 3600}}),
                ok({'data': [{'permission': 'pages_show_list', 'status': 'granted'}]}), ok({'data': pages})]

    def channel(self):
        state = fixture.service.repository.get(fixture.wid, 'fixture-one')['state']
        return next(c for c in state['phase2']['channels'] if c['id'] == self.connection_id)

    def test_connection_manager_can_choose_basic_page_without_publish_authority(self):
        self.adapter.transport = Wire(self.responses([self.page]) + self.responses([self.page]))
        with fixture.connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='admin',can_publish=false WHERE workspace_id=%s AND user_id=%s", (fixture.wid, fixture.one))
        self.assertEqual(self.oauth.destinations(fixture.wid, 'fixture-one', self.connection_id)['destinations'][0]['id'], '10001')
        self.oauth.choose_destination(fixture.wid, 'fixture-one', self.connection_id, '10001')
        channel = self.channel()
        self.assertEqual((channel['accountType'], channel['destinationId'], channel['providerAccountId']), ('page', '10001', '777'))
        self.assertFalse(channel['capabilityVerified'])
        self.assertEqual(channel['scopes'], ['pages_show_list'])
        with fixture.connection() as db:
            saved = db.execute('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (fixture.wid, self.connection_id)).fetchone()
        self.assertNotIn('SYNTHETIC', saved[0])
        self.assertNotIn('token', json.loads(self.oauth.vault.decrypt(saved[0], saved[1]))['page'])

    def test_other_workspace_cannot_read_or_attach_the_connection(self):
        self.adapter.transport = Wire([])
        for operation in (lambda: self.oauth.destinations(fixture.foreign, 'fixture-one', self.connection_id),
                          lambda: self.oauth.choose_destination(fixture.foreign, 'fixture-two', self.connection_id, '10001')):
            with self.assertRaises(AlphaError):
                operation()
        self.assertEqual(self.adapter.transport.calls, [])
        self.assertNotIn('destinationId', self.channel())

    def test_destination_choice_cannot_overwrite_a_concurrent_reconnect(self):
        self.adapter.transport = Wire(self.responses([])[:2])
        rotated = self.blob.replace('SYNTHETIC', 'ROTATED')
        ciphertext, key_id = self.oauth.vault.encrypt(rotated)
        def reconnect_then_choose(*args):
            with fixture.connection() as db:
                db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s WHERE workspace_id=%s AND connection_id=%s',
                           (ciphertext, key_id, fixture.wid, self.connection_id))
            return json.dumps({**json.loads(self.blob), 'page': self.page})
        self.adapter.with_destination = Mock(side_effect=reconnect_then_choose)
        with self.assertRaises(AlphaError):
            self.oauth.choose_destination(fixture.wid, 'fixture-one', self.connection_id, '10001')
        self.assertNotIn('destinationId', self.channel())
        with fixture.connection() as db:
            self.assertEqual(db.execute('SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                                        (fixture.wid, self.connection_id)).fetchone()[0], ciphertext)


outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FacebookConnectionSQL))
if not outcome.wasSuccessful():
    raise SystemExit(1)
