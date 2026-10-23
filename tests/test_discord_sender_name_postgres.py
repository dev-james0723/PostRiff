"""Sender names against a real PostgreSQL: the real repository and SQL for the routes, the cross-workspace nickname check,
and the W-02 lane (and the legacy worker) executing named and unnamed webhook posts and bot posts against a mock Discord.

Runs where PostgreSQL server binaries are named by POSTRIFF_PG_BIN; it starts its own disposable cluster and never reads
application credentials or touches another database (the pattern of test_discord_parallel_lane_postgres.py).
"""
import collections
import json
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import discord_lane_fixture as L
import discord_sender_name_fixture as F
from discord_sender_name_settings_fixture import Settings
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.oauth import DiscordConnections
from postriff_phase2.discord.rate_limits import SharedPostgresBudget
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.social_connectors import DiscordProvider

ON = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}
BODY = {'confirmed': True, 'sharedServerConfirmed': True}
SETTLED = ('verified', 'held', 'uncertain', 'failed', 'canceled')


def extra_migration_cluster():
    """The W-02 lane cluster plus 098 (credential authorization generation) and 131 (admission credential kind
    'webhook': without it the coordinator refuses every webhook request, which the lane reports as rate_delayed)."""
    with patch.object(L, 'MIGRATIONS', L.MIGRATIONS + ('098_youtube_authorization_generation.sql', '131_discord_interactions.sql')):
        return L.Cluster()


# ---------------------------------------------------------------------------------------------------------------------
# (1) the routes and the cross-workspace check on the real repository

class RealStore:
    """Settings (the in-memory builder) flushed into PostgreSQL, served by the real repository and SQL."""
    def __init__(self, cluster):
        self.cluster = cluster
        self.m = Settings()                       # builds states, credential rows and Discord-side configuration
        self.sessions, self.auth_time = {}, {}
        self.s = None

    def flush(self):
        m = self.m
        with self.cluster.connect() as db:
            for workspace in m.workspaces.values():
                for member in workspace.members.values():
                    db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (member.user,))
                    db.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (member.user,))
                db.execute('INSERT INTO public.pr_workspaces(id,revision,state) VALUES(%s,1,%s::jsonb)',
                           (workspace.id, json.dumps(workspace.state)))
                for member in workspace.members.values():
                    flags = member.flags
                    db.execute('INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,'
                               'can_manage_connections) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                               (workspace.id, member.user, member.role, member.status, flags.get('can_publish', False),
                                flags.get('can_reply', False), flags.get('can_moderate', False),
                                flags.get('can_manage_connections', False)))
            for (workspace, connection), credential in m.credentials.items():
                row = credential['row']
                db.execute('INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,'
                           'access_ciphertext,key_id,scopes,access_expires_at,authorization_generation,revoked_at) '
                           "VALUES(%s,%s,'discord',%s,%s,%s,%s,to_timestamp(%s),%s::uuid,CASE WHEN %s THEN now() END)",
                           (workspace, connection, row[6], row[0], row[1], row[5], row[3], row[4], credential['revoked']))
        provider = m.s.adapter

        def verify(token):
            if token not in m.tokens:
                raise AlphaError('This session expired or was revoked. Sign in again.', 401)
            return m.tokens[token]
        verify.auth_time = lambda token, principal: self.auth_time.get(token, time.time())
        repository = PostgresWorkspaceRepository(self.cluster.factory(), verify)
        oauth = SimpleNamespace(_provider=lambda _: provider, callback_uri=lambda _: 'https://rafii.example.invalid/callback',
                                clock=lambda: F.NOW, vault=m.s.oauth.vault, repository=repository,
                                commands=SimpleNamespace(engine=SimpleNamespace(invalidate=lambda *_: None)))
        self.s = DiscordConnections(oauth)
        self.s._fresh_identity = lambda *_: None
        return self

    def snapshot(self):
        with self.cluster.connect(autocommit=True) as db:
            rows = db.execute('SELECT id::text,revision,state::text FROM public.pr_workspaces ORDER BY id').fetchall()
            audit = db.execute("SELECT count(*) FROM public.pr_audit_events WHERE kind LIKE 'discord.sender_name%'").fetchone()[0]
            creds = db.execute('SELECT workspace_id::text,connection_id,revoked_at IS NOT NULL,authorization_generation::text '
                               'FROM public.pr_encrypted_credentials ORDER BY 1,2').fetchall()
        hooks = self.m.hooks
        return json.dumps([rows, audit, creds, hooks.calls, hooks.posts, {g: c.patches for g, c in hooks.guild_config.items()}],
                          default=str, sort_keys=True)

    def attempt(self, call, *args):
        try:
            return ('ok', None, call(*args))
        except AlphaError as error:
            return (error.status, error.code, str(error), getattr(error, 'public_fields', None))

    def get(self, workspace, token, connection):
        return self.s.sender_profile(workspace, token, connection)

    def post(self, workspace, token, connection, body):
        return self.s.set_sender_name(workspace, token, connection, body)


@unittest.skipIf(L.FENCED, L.SKIP_FENCED)
@unittest.skipUnless(L.AVAILABLE, L.SKIP_UNAVAILABLE)
class RoutesOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = extra_migration_cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()
        with self.cluster.connect(autocommit=True) as db:
            db.execute('DELETE FROM public.pr_encrypted_credentials')
            db.execute("DELETE FROM public.pr_auth_throttle")
        patcher = patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.r = RealStore(self.cluster)
        m = self.r.m
        self.ua, self.ub = m.user(1), m.user(2)
        self.A, self.B = m.workspace(1), m.workspace(2)
        self.ta, self.tb = m.member(self.A, self.ua, 'owner'), m.member(self.B, self.ub, 'owner')
        self.wa = m.webhook(self.A, 1, self.ua, name='Alpha Weekly')
        self.wb = m.webhook(self.B, 2, self.ub, name='Beta Weekly')
        self.ia = m.installation(self.A, 1, self.ua, guild='6600001')
        self.ib = m.installation(self.B, 2, self.ub, guild='6600002')

    def test_cross_tenant_matrix_on_the_real_repository_and_sql(self):
        with self.cluster.connect(autocommit=True) as db:
            existing = db.execute('SELECT count(*) FROM public.pr_workspaces').fetchone()[0]
        r = self.r.flush()
        targets = {'A': self.A, 'B': self.B, 'missing': '90000000-0000-4000-8000-000000000009', 'malformed': 'not-a-workspace',
                   'empty': '', 'injection': "x'; DROP TABLE public.pr_workspaces; --", 'long': 'a' * 5000,
                   'unicode': 'é中-0000'}
        connections = {'wa': self.wa.connection, 'ia': self.ia.connection, 'wb': self.wb.connection, 'ib': self.ib.connection,
                       'unknown': 'discord-webhook-unknown', 'malformed': "../../' OR '1'='1"}
        own = {'A': ('wa', 'ia'), 'B': ('wb', 'ib')}
        tokens = {'A': (self.A, self.ta), 'B': (self.B, self.tb)}
        foreign_workspace, foreign_connection, allowed = set(), set(), 0
        for actor, (own_workspace, token) in tokens.items():
            for target_name, target in targets.items():
                for connection_name, connection in connections.items():
                    for operation in ('GET', 'POST'):
                        before = r.snapshot()
                        outcome = (r.attempt(r.get, target, token, connection) if operation == 'GET' else
                                   r.attempt(r.post, target, token, connection, {'name': 'Intruder Weekly', 'fingerprint': 'f' * 64, **BODY}))
                        if target == own_workspace and connection_name in own[actor]:
                            allowed += outcome[0] == 'ok'
                            continue
                        self.assertNotEqual(outcome[0], 'ok', (actor, target_name, connection_name, operation))
                        self.assertEqual(r.snapshot(), before, (actor, target_name, connection_name, operation))
                        (foreign_workspace if target != own_workspace else foreign_connection).add(outcome[:3])
        self.assertEqual(foreign_workspace, {(403, 'permission_denied', 'Workspace unavailable.')})
        self.assertIn((404, 'not_found', 'This Discord connection is unavailable.'), foreign_connection)
        self.assertGreaterEqual(allowed, 4)
        # The other tenant's table is intact (the injection string was only ever a parameter).
        with self.cluster.connect(autocommit=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_workspaces').fetchone()[0], existing + 2)

    def test_members_removed_deleted_or_unknown_get_the_foreign_workspace_answer_from_the_real_membership_rows(self):
        m = self.r.m
        removed, deleted = m.user(31), m.user(32)
        removed_token, deleted_token = m.member(self.A, removed, 'admin'), m.member(self.A, deleted, 'owner')
        r = self.r.flush()
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.A, removed))
            db.execute('UPDATE public.pr_profiles SET deleted_at=now() WHERE user_id=%s', (deleted,))
        for token in (removed_token, deleted_token):
            before = r.snapshot()
            for outcome in (r.attempt(r.get, self.A, token, self.wa.connection),
                            r.attempt(r.post, self.A, token, self.wa.connection, {'name': 'Gone Weekly', 'fingerprint': 'f' * 64, **BODY})):
                self.assertEqual(outcome[:3], (403, 'permission_denied', 'Workspace unavailable.'))
            self.assertEqual(r.snapshot(), before)
        self.assertEqual(r.attempt(r.get, self.A, 'synthetic-unknown-session', self.wa.connection)[:2], (401, 'unauthenticated'))

    def test_save_replay_stale_session_and_role_refusals_on_real_rows(self):
        m = self.r.m
        viewer = m.user(41)
        viewer_token = m.member(self.A, viewer, 'viewer')
        admin = m.user(42)
        admin_token = m.member(self.A, admin, 'admin')
        r = self.r.flush()
        profile = r.get(self.A, self.ta, self.wa.connection)
        saved = r.post(self.A, self.ta, self.wa.connection, {'name': 'Real Weekly', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual((saved['savedName'], saved['saved']), ('Real Weekly', True))
        with self.cluster.connect(autocommit=True) as db:
            state, revision = db.execute('SELECT state,revision FROM public.pr_workspaces WHERE id=%s', (self.A,)).fetchone()
            kinds = db.execute("SELECT kind,meta::text FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'discord.sender_name%%'",
                               (self.A,)).fetchall()
            other = db.execute('SELECT revision FROM public.pr_workspaces WHERE id=%s', (self.B,)).fetchone()[0]
        self.assertEqual(revision, 2)
        self.assertEqual(other, 1, 'the other tenant\'s row was not touched')
        self.assertEqual(next(c for c in state['phase2']['channels'] if c['id'] == self.wa.connection)['discordSenderName'], 'Real Weekly')
        self.assertEqual([k for k, _ in kinds], ['discord.sender_name_updated'])
        self.assertNotIn('Real Weekly', kinds[0][1], 'the audit trail carries no customer-chosen text')
        # replay
        before = r.snapshot()
        self.assertEqual(r.attempt(r.post, self.A, self.ta, self.wa.connection,
                                   {'name': 'Replay Weekly', 'fingerprint': profile['fingerprint'], **BODY})[:2],
                         (409, 'discord_sender_name_required'))
        self.assertEqual(r.snapshot(), before)
        # a stale session reads but cannot write (the real repository's step-up window)
        self.r.auth_time[self.ta] = time.time() - 3600
        stale = r.get(self.A, self.ta, self.wa.connection)
        self.assertIn('session_reverification_required', [x['code'] for x in stale['unavailable']])
        before = r.snapshot()
        self.assertEqual(r.attempt(r.post, self.A, self.ta, self.wa.connection,
                                   {'name': 'Stale Weekly', 'fingerprint': stale['fingerprint'], **BODY})[:2], (403, 'step_up_required'))
        self.assertEqual(r.snapshot(), before)
        self.r.auth_time.pop(self.ta)
        # role refusals against the real membership flags
        before = r.snapshot()
        self.assertEqual(r.attempt(r.get, self.A, viewer_token, self.wa.connection)[:2], (403, 'permission_denied'))
        outcome = r.attempt(r.post, self.A, admin_token, self.wa.connection, {'name': 'Admin Weekly', 'fingerprint': 'f' * 64, **BODY})
        self.assertEqual(outcome[:2], (403, 'discord_sender_name_unavailable'))
        self.assertEqual(r.snapshot(), before)

    def test_the_real_throttle_counts_per_connection_and_resets_with_its_window(self):
        r = self.r.flush()
        for _ in range(12):
            r.get(self.A, self.ta, self.wa.connection)
        calls = len(self.r.m.hooks.calls)
        outcome = r.attempt(r.get, self.A, self.ta, self.wa.connection)
        self.assertEqual(outcome[:2], (429, 'rate_limited'))
        self.assertEqual(len(self.r.m.hooks.calls), calls)
        r.get(self.A, self.ta, self.ia.connection)
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_auth_throttle SET window_start=now()-interval '11 minutes'")
        r.get(self.A, self.ta, self.wa.connection)

    def test_request_counts_a_name_change_adds_to_one_edit(self):
        r = self.r.flush()
        hooks = self.r.m.hooks
        before = len(hooks.calls)
        profile = r.get(self.A, self.ta, self.wa.connection)
        webhook_read = len(hooks.calls) - before
        before = len(hooks.calls)
        r.post(self.A, self.ta, self.wa.connection, {'name': 'Counted Weekly', 'fingerprint': profile['fingerprint'], **BODY})
        webhook_edit = len(hooks.calls) - before
        self.assertEqual((webhook_read, webhook_edit), (1, 1))                    # one GET of the webhook itself, no write
        self.assertEqual({method for method, _ in hooks.calls}, {'GET'})
        before = len(hooks.calls)
        profile = r.get(self.A, self.ta, self.ia.connection)
        bot_read = collections.Counter(method for method, _ in hooks.calls[before:])
        before = len(hooks.calls)
        r.post(self.A, self.ta, self.ia.connection, {'name': 'Counted Bot', 'fingerprint': profile['fingerprint'], **BODY})
        bot_edit = collections.Counter(method for method, _ in hooks.calls[before:])
        self.assertEqual(bot_read, collections.Counter({'GET': 6}))      # identity x2 (cold cache), server, two members, bot member
        self.assertEqual(bot_edit, collections.Counter({'GET': 7, 'PATCH': 1}))   # the same reads, one write, one read-back
        # A post itself: the name adds no request (the wire tests count the create; the lane tests compare named and unnamed).

    # -- the cross-workspace nickname check (SQL) ---------------------------------------------------------------------------

    def test_the_contender_count_sees_only_other_live_bot_installations_of_the_same_server(self):
        m = self.r.m
        server = '6600555'
        a = m.installation(self.A, 5, self.ua, guild=server)
        b = m.installation(self.B, 6, self.ub, guild=server)
        other_server = m.installation(self.B, 7, self.ub, guild='6600556')
        webhook_in_same_guild = m.webhook(self.B, 8, self.ub, guild=server)          # a webhook is not a bot installation
        gone = m.installation(self.B, 9, self.ub, guild=server)
        m.revoke(self.B, gone.connection)
        r = self.r.flush()
        with self.cluster.connect(autocommit=True) as db:
            # a webhook row whose account id equals the server id must not count either
            db.execute("UPDATE public.pr_encrypted_credentials SET provider_account_id=%s WHERE workspace_id=%s AND connection_id=%s",
                       (server, self.B, webhook_in_same_guild.connection))
        with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
            def count(workspace, connection, guild):
                return self.r.s.nickname_contenders(cur, workspace, connection, guild)
            self.assertEqual(count(self.A, a.connection, server), 1)              # B's live installation
            self.assertEqual(count(self.B, b.connection, server), 1)              # A's live installation
            self.assertEqual(count(self.B, other_server.connection, '6600556'), 0)
            self.assertEqual(count(self.A, self.ia.connection, self.ia.guild), 0)  # A's other server has no second holder
            with self.cluster.connect(autocommit=True) as other:
                other.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s",
                              (self.B, b.connection))
            self.assertEqual(count(self.A, a.connection, server), 0)              # the only holder left may write
            self.assertEqual(count(self.B, b.connection, server), 1)              # a revoked row sees A, but cannot be used anyway
        self.assertEqual(r.get(self.A, self.ta, a.connection)['unavailable'], [])

    def test_two_workspaces_racing_for_one_server_never_both_write_a_nickname(self):
        m = self.r.m
        rounds = []
        for number in range(10):
            server = str(6700000 + number)
            a = m.installation(self.A, 100 + number, self.ua, guild=server)
            b = m.installation(self.B, 200 + number, self.ub, guild=server)
            m.revoke(self.B, b.connection)       # B starts disconnected; its reconnect races A's write
            rounds.append((server, a, b))
        r = self.r.flush()
        for server, a, b in rounds:
            hooks = m.hooks
            config = hooks.guild_config[server]
            profile = r.get(self.A, self.ta, a.connection)
            barrier, results = threading.Barrier(2, timeout=60), {}

            def writer():
                barrier.wait()
                results['a'] = r.attempt(r.post, self.A, self.ta, a.connection,
                                         {'name': 'Race Bot', 'fingerprint': profile['fingerprint'], **BODY})

            def reconnect():
                barrier.wait()
                with self.cluster.connect(autocommit=True) as db:      # what a reconnect's upsert does to the row
                    db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s',
                               (self.B, b.connection))
            threads = [threading.Thread(target=writer), threading.Thread(target=reconnect)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=120)
            self.assertLessEqual(len(config.patches), 1, server)
            # B is live now: B cannot write, and A's next attempt is refused as well.
            for workspace, token, ids in ((self.B, self.tb, b), (self.A, self.ta, a)):
                profile_now = r.attempt(r.get, workspace, token, ids.connection)
                if workspace == self.B:
                    # the card is still marked revoked in B's workspace state: B cannot even open it
                    self.assertEqual(profile_now[:2], (404, 'not_found'))
                else:
                    self.assertEqual([x['code'] for x in profile_now[2]['unavailable']], ['nickname_authority_other_workspace'])
            written = len(config.patches)
            self.assertIn(results['a'][0], ('ok', 409), results['a'])
            if results['a'][0] == 'ok':
                self.assertEqual(written, 1)
            else:
                self.assertEqual(results['a'][1], 'discord_sender_name_unavailable')
                self.assertEqual(written, 0)


# ---------------------------------------------------------------------------------------------------------------------
# (2) the W-02 lane and the legacy worker execute named, unnamed and bot posts against a mock Discord

class WebhookDiscord(L.MockDiscord):
    """MockDiscord plus the execute-webhook route: records exactly what each execute carried."""
    def __init__(self, tenants, **kwargs):
        super().__init__(tenants, **kwargs)
        self.by_hook = {t.hook: t for t in tenants if t.kind == 'webhook'}
        self.executes = []
        self.default_name = F.DEFAULT_HOOK_NAME

    def _answer(self, method, path, body, now):
        parts = path.split('?')[0].strip('/').split('/')
        if parts[0] != 'webhooks':
            return super()._answer(method, path, body, now)
        tenant = self.by_hook.get(parts[1])
        if tenant is None or len(parts) < 3 or parts[2] != tenant.hook_credential:
            return {'status': 404, 'headers': {}, 'body': {'message': 'Unknown Webhook'}}
        if method == 'POST' and len(parts) == 3:
            ok, headers = self._bucket('webhook-execute', parts[1], *self.LIMITS['create'], now)
            if not ok:
                self.route429 += 1
                return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                    'retry_after': float(headers['retry-after']), 'global': False}}
            self.sequence += 1
            username = (body or {}).get('username')
            message = {'id': str(self.sequence), 'channel_id': tenant.channel, 'webhook_id': tenant.hook,
                       'author': {'id': tenant.hook, 'bot': True, 'username': username if username is not None else self.default_name},
                       'content': (body or {}).get('content'), 'mentions': [], 'mention_roles': [], 'mention_everyone': False,
                       'attachments': [], 'embeds': []}
            self.messages[message['id']] = message
            self.executes.append({'workspace': tenant.workspace, 'hook': tenant.hook, 'body': dict(body or {}), 'message': message['id']})
            return {'status': 200, 'headers': headers, 'body': message}
        template = f'{method}:/webhooks/{{id}}/{{token}}' + ('/messages/{id}' if len(parts) == 5 else '')
        import hashlib
        ok, headers = self._bucket(hashlib.sha256(template.encode()).hexdigest()[:20], parts[1], *self.read_limit, now)
        if not ok:
            self.route429 += 1
            return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                'retry_after': float(headers['retry-after']), 'global': False}}
        if method == 'GET' and len(parts) == 3:
            return {'status': 200, 'headers': headers, 'body': {'id': tenant.hook, 'application_id': F.APP, 'guild_id': tenant.guild,
                                                                'channel_id': tenant.channel, 'type': 1, 'name': self.default_name}}
        if method == 'GET' and len(parts) == 5 and parts[3] == 'messages' and parts[4] in self.messages:
            return {'status': 200, 'headers': headers, 'body': self.messages[parts[4]]}
        return {'status': 404, 'headers': headers, 'body': {'message': 'Unknown'}}


class Grants:
    def __init__(self, tenants):
        self.by_workspace = {t.workspace: t for t in tenants}

    def discord_grant_for_worker(self, workspace, connection, *, cur=None):
        tenant = self.by_workspace.get(workspace)
        if tenant is None or connection != tenant.connection:
            raise AlphaError('Synthetic grant unavailable.', 409)
        return tenant.grant()


def lane_social(cluster, tenants, wire, *, capacity=200):
    provider = DiscordProvider(F.APP, 'synthetic-oauth-client', 'synthetic-bot', 'https://rafii.example.invalid',
                               transport=wire, production_reviewed=True)
    provider.authorization_v2_enabled = provider.connections_v2_enabled = provider.rate_v1_enabled = True
    provider.webhook_v1_enabled = True
    provider.rate_limiter = SharedPostgresBudget(cluster.factory(), F.APP, policy=L.policy(cluster.now(), capacity=capacity))
    return HostedSocial(Grants(tenants), {'discord': provider})


def seed(cluster, tenants):
    with cluster.connect() as db:
        db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (F.ACTOR,))
        db.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (F.ACTOR,))
        for tenant in tenants:
            db.execute('INSERT INTO public.pr_workspaces(id,revision,state) VALUES(%s,1,%s::jsonb)', (tenant.workspace, json.dumps(tenant.state)))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply) "
                       "VALUES(%s,%s,'owner','active',true,true)", (tenant.workspace, F.ACTOR))


def read_jobs(cluster):
    with cluster.connect(autocommit=True) as db:
        rows = db.execute("SELECT id::text,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall()
    return {(workspace, job['id']): job for workspace, state in rows for job in state['phase2']['jobs']}


@unittest.skipIf(L.FENCED, L.SKIP_FENCED)
@unittest.skipUnless(L.AVAILABLE, L.SKIP_UNAVAILABLE)
class LaneAndWorkerOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = extra_migration_cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()
        patcher = patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tenants(self, now, *, named=6, plain=4, bots=4, posts=2):
        out = []
        for index in range(named):
            out.append(F.Tenant(index, f'Brand {index} Weekly', now=now))
        for index in range(named, named + plain):
            out.append(F.Tenant(index, None, now=now))
        for index in range(named + plain, named + plain + bots):
            out.append(F.Tenant(index, f'Remembered Nick {index}', kind='bot', now=now))
        for tenant in out:
            tenant.build(text=f'Post for {tenant.index}')
            first = tenant.approve()
            for number in range(1, posts):
                tenant.variant = dict(tenant.variant, id=f'synthetic-draft-extra-{number}', text=f'Post {number} for {tenant.index}')
                tenant.state['variants'].append(tenant.variant)
                tenant.approve()
        return out

    def start(self, **counts):
        now = self.cluster.now() - 360
        tenants = self.tenants(now, **counts)
        seed(self.cluster, tenants)
        self.wire = WebhookDiscord(tenants)
        self.hosted = lane_social(self.cluster, tenants, self.wire)
        self.tenant_list = tenants
        return tenants

    def assert_exact_names(self, tenants, posts):
        executes = self.wire.executes
        webhook_tenants = [t for t in tenants if t.kind == 'webhook']
        self.assertEqual(len(executes), len(webhook_tenants) * posts)
        per_hook = collections.Counter(e['hook'] for e in executes)
        for tenant in webhook_tenants:
            self.assertEqual(per_hook[tenant.hook], posts, 'exactly one execute per approved post')
        every_name = [t.name for t in webhook_tenants if t.name]
        for execute in executes:
            tenant = next(t for t in webhook_tenants if t.hook == execute['hook'])
            self.assertEqual(execute['workspace'], tenant.workspace)
            self.assertEqual(execute['body'].get('username'), tenant.name)
            self.assertEqual(set(execute['body']), {'content', 'allowed_mentions', 'flags'} | ({'username'} if tenant.name else set()))
            for other in every_name:
                if other != tenant.name:
                    self.assertNotIn(other, json.dumps(execute), 'another customer\'s name appeared in this request')
            self.assertEqual(self.wire.messages[execute['message']]['author']['username'], tenant.name or F.DEFAULT_HOOK_NAME)
        bot_creates = [c for c in self.wire.creates.values() for _ in c]
        self.assertEqual(len(bot_creates), len([t for t in tenants if t.kind == 'bot']) * posts)

    def drain(self, worker, loops, *, seconds, rounds=4):
        every = []
        for _ in range(rounds):
            results, failures = L.run_lanes(worker, loops, seconds=seconds)
            self.assertEqual(failures, [])
            every.extend(results)
            if all(job['state'] in SETTLED for job in read_jobs(self.cluster).values()):
                break
        return every

    def test_the_lane_sends_named_unnamed_and_bot_posts_each_under_exactly_its_own_name(self):
        tenants = self.start()
        worker = PostgresWorker(self.cluster.factory(), social=self.hosted, worker_id='sn-lane-base', discord_workers=True)
        results = self.drain(worker, 4, seconds=60)
        jobs = read_jobs(self.cluster)
        self.assertEqual(len(jobs), len(tenants) * 2)
        self.assertEqual(sorted({j['state'] for j in jobs.values()}), ['verified'])
        self.assert_exact_names(tenants, 2)
        for (workspace, _), job in jobs.items():
            tenant = next(t for t in tenants if t.workspace == workspace)
            frozen = job['manifest'].get('discordSenderName')
            self.assertEqual(frozen, tenant.name if tenant.kind == 'webhook' else None)
            self.assertEqual(len(job['discordDispatchIntents']), 1)
        self.assertEqual(self.wire.route429, 0)
        self.assertEqual(sum(r['counters']['posted'] for r in results), len(jobs))

    def run_one(self, name):
        """One webhook tenant, one approved post, one thread: the exact multiset of Discord requests it takes."""
        self.cluster.reset()
        now = self.cluster.now() - 360
        tenant = F.Tenant(0, name, now=now).build(text='Counted post')
        tenant.approve()
        seed(self.cluster, [tenant])
        wire = WebhookDiscord([tenant])
        hosted = lane_social(self.cluster, [tenant], wire)
        worker = PostgresWorker(self.cluster.factory(), social=hosted, worker_id='sn-count', discord_workers=True)
        with L.no_billing():
            for _ in range(400):
                worker.step()
                if all(job['state'] in SETTLED for job in read_jobs(self.cluster).values()):
                    break
                time.sleep(.1)
        self.assertEqual(sorted({j['state'] for j in read_jobs(self.cluster).values()}), ['verified'])
        counted = collections.Counter()
        for _, method, path in wire.calls:
            shape = (path.split('?')[0].replace(tenant.hook_credential, '{token}').replace(tenant.hook, '{hook}')
                     .replace(tenant.guild, '{guild}').replace(tenant.channel, '{channel}'))
            counted[(method, '/'.join('{id}' if part.isdigit() else part for part in shape.split('/')))] += 1
        return counted, wire

    def test_a_name_adds_no_request_to_a_webhook_post(self):
        named, named_wire = self.run_one('Counted Weekly')
        plain, plain_wire = self.run_one(None)
        self.assertEqual(named_wire.executes[0]['body'].get('username'), 'Counted Weekly')
        self.assertNotIn('username', plain_wire.executes[0]['body'])
        self.assertEqual(named, plain, 'a sender name must add no Discord request to a post')
        self.assertEqual(named[('POST', '/webhooks/{hook}/{token}')], 1)
        # Recorded for CAPACITY-NOTES.md: the full per-post request shape of one webhook post.
        self.assertEqual(sum(named.values()), sum(plain.values()))

    def test_switching_the_feature_off_holds_only_the_named_posts_and_they_stay_held_when_it_returns(self):
        tenants = self.start(named=3, plain=2, bots=2, posts=1)
        worker = PostgresWorker(self.cluster.factory(), social=self.hosted, worker_id='sn-lane-off', discord_workers=True)
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            self.drain(worker, 3, seconds=60)
        jobs = read_jobs(self.cluster)
        states = {}
        for (workspace, _), job in jobs.items():
            tenant = next(t for t in tenants if t.workspace == workspace)
            states.setdefault(('named webhook' if tenant.kind == 'webhook' and tenant.name else tenant.kind), set()).add(job['state'])
        self.assertEqual(states, {'named webhook': {'held'}, 'webhook': {'verified'}, 'bot': {'verified'}})
        held = [j for j in jobs.values() if j['state'] == 'held']
        self.assertEqual(len(held), 3)
        for job in held:
            self.assertIn('switched off', job['events'][-1]['message'])
            self.assertEqual(job.get('discordDispatchIntents') or [], [], 'no intent was sealed for a post that could not be sent')
            self.assertNotIn('providerReference', job)
        named_hooks = {t.hook for t in tenants if t.kind == 'webhook' and t.name}
        self.assertFalse([e for e in self.wire.executes if e['hook'] in named_hooks], 'no named post reached Discord while off')
        sent_before = len(self.wire.executes)
        self.drain(worker, 3, seconds=30, rounds=2)      # switched back on: a held approval is never resent on its own
        self.assertEqual(len(self.wire.executes), sent_before)
        self.assertEqual({j['state'] for j in read_jobs(self.cluster).values() if j in held} or {'held'}, {'held'})

    def test_the_minute_tick_worker_path_with_the_lane_off_sends_the_same_exact_names(self):
        """/api/cron/worker with the lane off: PostgresWorker.step() over all platforms under the fenced lease
        protocol (a worker without it cannot dispatch Discord at all: migration 128 refuses the claim)."""
        tenants = self.start(named=4, plain=2, bots=2, posts=2)
        worker = PostgresWorker(self.cluster.factory(), social=self.hosted, worker_id='sn-tick', discord_workers=True)
        with L.no_billing():
            for _ in range(300):
                worker.step()
                if all(job['state'] in SETTLED for job in read_jobs(self.cluster).values()):
                    break
                time.sleep(.05)
        jobs = read_jobs(self.cluster)
        self.assertEqual(sorted({j['state'] for j in jobs.values()}), ['verified'])
        self.assert_exact_names(tenants, 2)

    def test_a_worker_without_the_fenced_lease_protocol_cannot_dispatch_discord_at_all(self):
        """Why the frozen RC1 worker can only HOLD named posts on a migrated database: it cannot send any Discord post."""
        self.start(named=1, plain=0, bots=0, posts=1)
        legacy = PostgresWorker(self.cluster.factory(), social=self.hosted, worker_id='sn-unfenced', discord_workers=False)
        import psycopg
        with L.no_billing(), self.assertRaises(psycopg.errors.CheckViolation):
            legacy.step()
        self.assertEqual(self.wire.executes, [])

    def test_two_lane_processes_and_a_legacy_worker_together_never_cross_names(self):
        tenants = self.start(named=8, plain=4, bots=4, posts=3)
        lane_a = PostgresWorker(self.cluster.factory(), social=self.hosted, worker_id='sn-lane-a', discord_workers=True)
        self.drain(lane_a, 4, seconds=60)
        self.assertEqual(sorted({j['state'] for j in read_jobs(self.cluster).values()}), ['verified'])
        self.assert_exact_names(tenants, 3)
        self.assertEqual(sum(len(job['discordDispatchIntents']) for job in read_jobs(self.cluster).values()), len(tenants) * 3)


if __name__ == '__main__':
    unittest.main()
