"""Real disposable PostgreSQL isolation and action journal. All Mastodon responses synthetic."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import MastodonProvider
from postriff_phase2.mastodon_management import MastodonManagement
from test_hosted_wave1_connectors import PUBLIC, ok

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')


def connection(): return psycopg.connect(DSN, client_encoding='utf8')


class JournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (ROOT / 'migrations/postriff/113_mastodon_management.sql').read_text()
        with connection() as db:
            db.execute(cls.sql)
            db.execute(cls.sql)

    def setUp(self):
        self.actor = str(uuid.uuid4())
        self.other = str(uuid.uuid4())
        self.now = time.time()
        self.posts = []
        self.calls = []
        def transport(method, url, **kw):
            self.calls.append((method, url, kw))
            if '/api/v2/instance' in url: return ok({'version': '4.2.9'})
            if '/verify_credentials' in url:
                if '/apps/' in url: return ok({'scopes': ['read:accounts', 'write:favourites']})
                return ok({'id': '100', 'username': 'fixture'})
            if method == 'POST' and '/api/v1/apps' in url:
                return ok({'client_id': 'fixture-client', 'client_secret': 'fixture-secret'})
            if method == 'POST':
                self.posts.append(url)
                return ok({'id': '123'})
            return ok({}, 404)
        self.provider = MastodonProvider('https://rafii.io', transport=transport, production_reviewed=True, resolver=PUBLIC)
        self.vault = CredentialVault(CredentialVault.generate_key())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s),(%s)', (self.actor, self.other))
        self.service = HostedWorkspaceService(connection, lambda token: str(uuid.UUID(token)),
            clock=lambda: self.now, vault=self.vault, providers={'mastodon': self.provider}, public_base_url='https://rafii.io')
        self.workspace = self.service.bootstrap(self.actor, 'studio')['workspaceId']
        self.foreign = self.service.bootstrap(self.other, 'studio')['workspaceId']
        self.manager = MastodonManagement(self.service)
        self.account = '100@mastodon.social'
        self.connection_id = uuid.uuid4().hex
        encrypted, key = self.vault.encrypt(json.dumps({'v': 1, 'at': 'fixture-token', 'instance': 'mastodon.social',
            'clientId': 'fixture-client', 'clientSecret': 'fixture-secret', 'scope': ['read:accounts', 'write:favourites']}))
        with connection() as db:
            db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'mastodon',%s,%s,%s,%s)",
                       (self.workspace, self.connection_id, self.account, encrypted, key, ['read:accounts', 'write:favourites']))

    def preview(self):
        return self.manager.preview(self.workspace, self.actor, self.connection_id, {'action': 'favourite', 'targetId': '123'})

    def execute(self, preview, **changes):
        return self.manager.execute(self.workspace, self.actor, self.connection_id, preview['actionId'],
                                    {'confirmed': True, 'digest': preview['digest'], **changes})

    def test_cross_tenant_denial_sends_no_provider_request(self):
        before = len(self.calls)
        for workspace, actor in ((self.workspace, self.other), (self.foreign, self.other)):
            with self.assertRaises(AlphaError):
                self.manager.read(workspace, actor, self.connection_id, 'profile')
        self.assertEqual(len(self.calls), before)

    def test_approval_digest_and_expiry(self):
        preview = self.preview()
        self.assertEqual(self.posts, [])
        with self.assertRaises(AlphaError): self.execute(preview, digest='0' * 64)
        with self.assertRaises(AlphaError): self.execute(preview, confirmed=False)
        self.now += 601
        with self.assertRaises(AlphaError): self.execute(preview)
        self.assertEqual(self.posts, [])

    def test_repeated_confirmation_never_sends_twice(self):
        preview = self.preview()
        self.assertEqual(self.execute(preview)['state'], 'accepted')
        self.assertTrue(self.execute(preview)['replayed'])
        self.assertEqual(len(self.posts), 1)

    def test_simultaneous_confirmation_has_one_effect(self):
        preview = self.preview()
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.execute(preview), range(8)))
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(sum(not r.get('replayed', False) for r in results), 1)

    def test_revoked_connection_stops_before_dispatch(self):
        preview = self.preview()
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
        with self.assertRaises(AlphaError): self.execute(preview)
        self.assertEqual(self.posts, [])

    def test_application_cache_is_encrypted_and_shared_by_binding(self):
        cache = self.provider.application_cache
        first = cache('mastodon.social', 'https://rafii.io/api/oauth/mastodon/callback', ['read:accounts'])
        second = cache('mastodon.social', 'https://rafii.io/api/oauth/mastodon/callback', ['read:accounts'])
        self.assertEqual(first, second)
        self.assertEqual(len([c for c in self.calls if c[0] == 'POST' and c[1].endswith('/api/v1/apps')]), 1)
        with connection() as db:
            row = db.execute('SELECT credentials_ciphertext FROM public.pr_mastodon_applications').fetchone()
            self.assertNotIn('fixture-secret', row[0])

    def test_browser_roles_cannot_read_credentials_or_action_bodies(self):
        self.preview()
        for role in ('anon', 'authenticated'):
            for table in ('pr_mastodon_applications', 'pr_mastodon_actions'):
                with connection() as db:
                    db.execute('SET LOCAL ROLE ' + role)
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege): db.execute('SELECT * FROM public.' + table)


if __name__ == '__main__': unittest.main()
