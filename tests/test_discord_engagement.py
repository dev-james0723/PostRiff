"""Synthetic behavioral controls. SQL locks/RLS are qualified separately in cloud.

No real tokens, provider requests, model calls, or database are reachable here.
"""
import copy
import hashlib
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import authorization as auth
from postriff_phase2.discord.engagement import (DiscordEngagementService, KEY, LIMITS, annotate_capabilities,
                                               managed_messages, message_view, metric, reply_current)
from postriff_phase2.discord.rate_limits import SharedPostgresBudget
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.permissions import Membership, require
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import (ACTOR, APP, BOT, USER, GUILD, FIRST, SECOND, NOW, WORKSPACE,
                                                SyntheticGrants, SyntheticWire, fixture)
from test_discord_worker_lifecycle import MemoryDatabase
from test_discord_rate_limits import MemoryLedger, synthetic_policy

POST, CHILD, HIDDEN, OTHER = '4444444', '5555555', '6666666', '7777771'


def parent_message():
    return {'id': CHILD, 'channel_id': FIRST, 'guild_id': GUILD, 'type': 19,
            'content': '<@' + BOT + '> Please clarify the rehearsal time.',
            'author': {'id': USER, 'username': 'Synthetic reader'}, 'mentions': [{'id': BOT}],
            'message_reference': {'message_id': POST, 'channel_id': FIRST, 'guild_id': GUILD},
            'attachments': []}


class EngagementWire(SyntheticWire):
    def __init__(self):
        super().__init__()
        self.parent = parent_message()
        self.page = [copy.deepcopy(self.parent),
                     {**parent_message(), 'id': HIDDEN, 'content': '', 'mentions': []},
                     {**parent_message(), 'id': OTHER, 'content': 'Unrelated private text',
                      'message_reference': {}, 'mentions': []}]
        self.on_page = None
        self.fail_post = False
        self.application_flags = 0
        self.application_fields = None

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url)
        path = parsed.path.removeprefix('/api/v10')
        if method == 'GET' and path == f'/channels/{FIRST}/messages':
            self.calls.append((method, path, None))
            if self.on_page:
                self.on_page()
            result = {'status': 200, 'body': copy.deepcopy(self.page)}
        elif method == 'GET' and path == f'/channels/{FIRST}/messages/{CHILD}':
            self.calls.append((method, path, None))
            result = {'status': 200, 'body': copy.deepcopy(self.parent)}
        elif method == 'GET' and path == f'/guilds/{GUILD}' and parsed.query:
            result = super().__call__(method, DiscordProvider.API + path, **kwargs)
            result['body'].update(approximate_member_count=12, approximate_presence_count=4)
        elif method == 'GET' and path == f'/channels/{FIRST}/messages/{POST}' and self.message is None:
            self.calls.append((method, path, None))
            result = {'status': 200, 'body': {'id': POST, 'channel_id': FIRST, 'author': {'id': BOT, 'bot': True},
                                            'content': 'Synthetic managed post', 'reactions': [{'count': 3}, {'count': 2}]}}
        else:
            result = super().__call__(method, url, **kwargs)
            if method == 'POST' and path.endswith('/messages'):
                if self.fail_post:
                    raise TimeoutError('Synthetic unknown send outcome')
                if (kwargs.get('body') or {}).get('message_reference'):
                    result['body'].update(type=19, message_reference={**kwargs['body']['message_reference'],
                                               'channel_id': FIRST, 'guild_id': GUILD})
            if method == 'GET' and path == f'/channels/{FIRST}/messages/{POST}' and self.message:
                result['body'] = {**self.message, 'mention_everyone': False, 'mentions': [], 'mention_roles': [], 'attachments': []}
        if path == '/oauth2/applications/@me' and result.get('status') == 200:
            result['body'].pop('flags', None); result['body'].pop('flags_new', None)
            result['body'].update(self.application_fields if self.application_fields is not None else {'flags': self.application_flags})
        result['headers'] = {'X-RateLimit-Bucket': hashlib.sha256(path.encode()).hexdigest()[:16],
                             'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': '99', 'X-RateLimit-Reset-After': '1'}
        return result


class Repository(MemoryDatabase):
    def __init__(self, state):
        super().__init__(state)
        self.now = NOW
        self.members = {'owner': (ACTOR, Membership('owner')), 'other': ('other-actor', Membership('owner')),
                        'reader': ('reader-actor', Membership('viewer')),
                        'replyer': (ACTOR, Membership('editor', {'can_reply': True}))}
        self.audit = []
        self.learning_events = []

    @contextmanager
    def transaction(self, token, workspace):
        if token not in self.members or workspace != WORKSPACE:
            raise AlphaError('Workspace unavailable.', 403)
        actor, member = self.members[token]
        row = (self.revision, copy.deepcopy(self.state), member.role, *[member.flags[k] for k in
               ('can_publish', 'can_reply', 'can_moderate', 'can_manage_connections')])
        yield self, row, actor

    def get(self, workspace, token):
        with self.transaction(token, workspace):
            return {'state': copy.deepcopy(self.state), 'revision': self.revision}

    def command(self, workspace, token, revision, action, requirement='edit', after=None, audit_event=None):
        with self.transaction(token, workspace) as (cur, _, actor):
            require(self.members[token][1], requirement)
            if revision != self.revision:
                raise AlphaError('Workspace changed.', 409)
            before = copy.deepcopy(self.state)
            try:
                state = action(copy.deepcopy(self.state), actor)
                if after: after(cur, state, actor)
                self.state = state; self.revision += 1
                if audit_event: self.audit.append(audit_event(state))
            except BaseException:
                self.state = before
                raise
            return {'state': copy.deepcopy(state), 'revision': self.revision}

    def execute(self, sql, params=()):
        if sql.startswith('INSERT INTO public.pr_audit_events'):
            self.audit.append(params); self.rows = []; self.rowcount = 1
        elif sql.startswith(('SAVEPOINT learning_', 'RELEASE SAVEPOINT learning_', 'ROLLBACK TO SAVEPOINT learning_')):
            self.queries.append((sql, params)); self.rows = []; self.rowcount = 0
        elif sql.startswith('INSERT INTO public.pr_learning_events'):
            self.learning_events.append(params); self.rows = []; self.rowcount = 1
        elif 'public.pr_discord_request_admissions' in sql:
            self.ledger.execute(sql, params)
            self.rows = self.ledger.fetchall(); self.rowcount = self.ledger.rowcount
        else:
            super().execute(sql, params)


class EngagementFixture:
    def __init__(self):
        _, state, channel, _ = fixture()
        target = next(d for d in channel['discordDestinations'] if d['channelId'] == FIRST)
        state['phase2']['jobs'].append({'id': 'managed-post', 'state': 'verified', 'providerReference': FIRST + '/' + POST,
            'manifest': {'platform': 'Discord', 'workspaceId': WORKSPACE, 'channelId': channel['id'], 'discord': {'target': target}}})
        self.repo, self.wire, self.grants = Repository(state), EngagementWire(), SyntheticGrants()
        self.provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://example.invalid',
                                        transport=self.wire, production_reviewed=True)
        self.provider.authorization_v2_enabled = self.provider.connections_v2_enabled = True
        self.provider.rate_v1_enabled = self.provider.engagement_v1_enabled = True
        self.ledger = MemoryLedger(now=NOW, workspace=self.repo)
        self.repo.ledger = self.ledger
        self.provider.rate_limiter = SharedPostgresBudget(self.ledger.connection, APP, policy=synthetic_policy(NOW))
        self.oauth = SimpleNamespace(providers={'discord': self.provider}, discord_grant_for_worker=self.grants.discord_grant_for_worker)
        self.commands = HostedPhase2Commands(clock=lambda: self.repo.now)
        self.service = DiscordEngagementService(self.repo, self.oauth, self.commands, lambda: self.repo.now)
        self.connection, self.destination = channel['id'], target['id']
        self.social = HostedSocial(self.oauth, self.oauth.providers)

    def grant(self, token='owner', **overrides):
        status = self.service.status(WORKSPACE, token, self.connection)
        d = next(x for x in status['destinations'] if x['target']['id'] == self.destination)
        return self.service.consent(WORKSPACE, token, self.connection, {'destinationId': self.destination,
            'targetDigest': d['targetDigest'], 'permissions': {'analytics': True, 'inbox': True, 'reply': True, **overrides}, 'confirmed': True})

    def preview(self, token='owner', **overrides):
        return self.service.preview(WORKSPACE, token, self.connection,
            {'destinationId': self.destination, 'parentMessageId': CHILD, 'text': 'The rehearsal starts at 4 pm.', **overrides})

    def approve(self, review, token='owner'):
        return self.service.approve(WORKSPACE, token, self.connection,
                                    {'reviewId': review['reviewId'], 'digest': review['digest'], 'confirmed': True})

    def worker(self):
        return PostgresWorker(self.repo.connection, self.social, clock=lambda: self.repo.now,
                              worker_id='engagement-worker', discord_workers=True)

    def due(self, job):
        queued = next(j for j in self.repo.state['phase2']['jobs'] if j['id'] == job['jobId'])
        self.repo.now = queued['nextAt'] + 1
        self.ledger.now = self.repo.now
        return queued


class EngagementControls(unittest.TestCase):
    def setUp(self):
        self.fixture = EngagementFixture()
        from postriff_phase2 import security_holds
        for p in (patch('socket.socket.connect', side_effect=AssertionError('No network')),
                  patch('postriff_phase2.billing.require_publishing', return_value=None),
                  patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')})):
            p.start(); self.addCleanup(p.stop)

    def test_no_read_before_exact_consent_no_transport(self):
        f = self.fixture
        with self.assertRaises(AlphaError): f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertEqual(f.wire.calls, [])

    def test_consent_is_personal_tenant_and_destination_bound(self):
        f = self.fixture; f.grant()
        for workspace, token, destination in ((WORKSPACE, 'other', f.destination), ('foreign', 'owner', f.destination),
                                                (WORKSPACE, 'owner', 'other-destination')):
            with self.subTest(token=token, workspace=workspace), self.assertRaises(AlphaError):
                f.service.read(workspace, token, f.connection, {'kind': 'inbox', 'destinationId': destination})
        self.assertEqual(f.wire.calls, [])

    def test_viewer_cannot_grant_reply_but_can_approve_own_read(self):
        f = self.fixture
        with self.assertRaises(AlphaError): f.grant('reader')
        f.grant('reader', reply=False)
        status = f.service.status(WORKSPACE, 'reader', f.connection)
        self.assertFalse(status['canReply'])
        self.assertTrue(status['destinations'][0]['permissions']['inbox'])

    def test_human_only_rejects_tool_context(self):
        from postriff_phase2.agent_runtime_v2.authz import IN_TOOL
        mark = IN_TOOL.set(True)
        try:
            with self.assertRaises(AlphaError): self.fixture.grant()
        finally: IN_TOOL.reset(mark)

    def test_inbox_partial_and_unrelated_content_never_leaks_or_persists(self):
        f = self.fixture; f.grant()
        data = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertEqual([m['id'] for m in data['messages']], [CHILD, HIDDEN])
        self.assertTrue(data['messages'][0]['replyable']); self.assertIsNone(data['messages'][1]['content'])
        self.assertEqual(data['coverage'], 'latest_page_only')
        self.assertNotIn('Unrelated private text', json.dumps(data))
        self.assertNotIn('Please clarify', json.dumps(f.repo.state))
        self.assertTrue(f.ledger.admissions, 'Actual shared admission algorithm must run for GETs')

    def test_analytics_native_and_derived_are_separate_lower_bound(self):
        f = self.fixture; f.grant(inbox=False, reply=False)
        data = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'analytics', 'destinationId': f.destination})
        self.assertEqual(data['server']['approximateMembers']['value'], 12)
        post = data['managedMessages'][0]
        self.assertEqual(post['reactions']['value'], 5)
        self.assertEqual(post['repliesObserved']['value'], 2)
        self.assertTrue(post['repliesObserved']['lowerBound'])
        self.assertNotIn('messages', data); self.assertIn('reach', data['unavailableMetrics'])
        self.assertIsNone(metric(None, source='x', definition='x')['value'])

    def test_read_cooldown_prevents_another_provider_request(self):
        f = self.fixture; f.grant()
        args = {'kind': 'inbox', 'destinationId': f.destination}
        f.service.read(WORKSPACE, 'owner', f.connection, args)
        calls = len(f.wire.calls)
        with self.assertRaises(AlphaError) as caught: f.service.read(WORKSPACE, 'owner', f.connection, args)
        self.assertEqual(caught.exception.status, 429); self.assertEqual(len(f.wire.calls), calls)

    def test_revocation_during_read_suppresses_result_and_subsequent_get(self):
        f = self.fixture; f.grant()
        f.wire.on_page = lambda: f.grant(analytics=False, inbox=False, reply=False)
        with self.assertRaises(AlphaError):
            f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'analytics', 'destinationId': f.destination})
        self.assertFalse(any('with_counts' in call[1] for call in f.wire.calls))

    def test_revoke_still_works_while_rollout_paused(self):
        f = self.fixture; f.grant(); f.provider.engagement_v1_enabled = False
        f.grant(analytics=False, inbox=False, reply=False)
        self.assertFalse(f.service.status(WORKSPACE, 'owner', f.connection)['destinations'][0]['permissions']['inbox'])

    def test_identity_or_generation_change_blocks_read_before_transport(self):
        f = self.fixture; f.grant(); f.grants.generation = 'rotated'
        with self.assertRaises(AlphaError):
            f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertEqual(f.wire.calls, [])

    def test_restricted_parent_cannot_prepare_reply(self):
        f = self.fixture; f.grant(); f.wire.parent['content'] = ''; f.wire.parent['mentions'] = []
        with self.assertRaises(AlphaError): f.preview()
        self.assertFalse(f.repo.state['phase2'][KEY]['reviews'])

    def test_exact_parent_text_destination_time_preview_creates_no_job_or_post(self):
        f = self.fixture; f.grant(); review = f.preview(text='  Exact text @everyone  ')
        m = review['manifest']; wire = auth.wire_content(m)
        self.assertEqual(m['payload']['text'], '  Exact text @everyone  ')
        self.assertEqual(wire['message_reference'], {'type': 0, 'message_id': CHILD, 'fail_if_not_exists': True})
        self.assertEqual(wire['allowed_mentions'], {'parse': [], 'replied_user': False})
        self.assertEqual(m['discord']['target']['channelId'], FIRST)
        self.assertFalse(any(j.get('manifest', {}).get('operation') == 'discord.reply' for j in f.repo.state['phase2']['jobs']))
        self.assertFalse(any(c[0] == 'POST' for c in f.wire.calls))

    def test_changed_parent_or_foreign_actor_cannot_approve(self):
        f = self.fixture; f.grant(); f.grant('other'); review = f.preview()
        with self.assertRaises(AlphaError): f.approve(review, 'other')
        f.wire.parent['content'] += ' Changed.'
        with self.assertRaises(AlphaError): f.approve(review)

    def test_approval_is_idempotent_and_old_consent_never_revives(self):
        f = self.fixture; f.grant(); review = f.preview(); first = f.approve(review)
        self.assertEqual(f.approve(review)['jobId'], first['jobId'])
        self.assertEqual(sum(j.get('manifest', {}).get('operation') == 'discord.reply' for j in f.repo.state['phase2']['jobs']), 1)
        manifest = review['manifest']; f.grant()
        self.assertFalse(reply_current(f.repo.state, manifest, f.repo.now))
        with self.assertRaises(AlphaError): f.approve(review)

    def test_reply_permission_is_rechecked_at_claim(self):
        f = self.fixture; f.grant('replyer'); job = f.approve(f.preview('replyer'), 'replyer'); f.due(job)
        f.repo.member = ('editor', False)
        self.assertIsNone(f.worker().claim(discord_only=True))
        self.assertFalse(any(c[0] == 'POST' for c in f.wire.calls))

    def test_can_reply_without_can_publish_uses_fenced_worker_once(self):
        f = self.fixture; f.grant('replyer'); job = f.approve(f.preview('replyer'), 'replyer'); f.due(job)
        f.repo.member = ('editor', True)  # SQL now reads can_reply for this operation.
        worker = f.worker()
        self.assertTrue(worker.step(discord_only=True))
        queued = next(j for j in f.repo.state['phase2']['jobs'] if j['id'] == job['jobId'])
        self.assertEqual(queued['state'], 'provider_accepted')
        self.assertEqual(len(queued['discordDispatchIntents']), 1)
        self.assertEqual(sum(c[0] == 'POST' for c in f.wire.calls), 1)
        # Follow the existing reconciliation due time; never force a claim.
        f.repo.now = queued['nextAt'] + .1; f.ledger.now = f.repo.now
        self.assertTrue(worker.step(discord_only=True))
        self.assertEqual(next(j for j in f.repo.state['phase2']['jobs'] if j['id'] == job['jobId'])['state'], 'verified')
        self.assertEqual(sum(c[0] == 'POST' for c in f.wire.calls), 1)
        self.assertEqual(len(f.repo.learning_events), 1)

    def test_revoke_after_claim_fences_read_and_post(self):
        f = self.fixture; f.grant(); job = f.approve(f.preview()); f.due(job)
        worker = f.worker(); claimed = worker.claim(discord_only=True); self.assertIsNotNone(claimed)
        f.grant(analytics=False, inbox=False, reply=False)
        calls = len(f.wire.calls)
        with self.assertRaises(AlphaError): worker._discord_reply_read_guard(claimed)()
        self.assertFalse(worker.authorize_dispatch(claimed)); self.assertEqual(len(f.wire.calls), calls)

    def test_unknown_outcome_retains_intent_and_blocks_new_copy(self):
        f = self.fixture; f.grant(); job = f.approve(f.preview()); f.due(job); f.wire.fail_post = True
        self.assertTrue(f.worker().step(discord_only=True))
        queued = next(j for j in f.repo.state['phase2']['jobs'] if j['id'] == job['jobId'])
        self.assertEqual(queued['state'], 'uncertain'); self.assertEqual(len(queued['discordDispatchIntents']), 1)
        with self.assertRaises(AlphaError): f.preview()
        self.assertEqual(sum(c[0] == 'POST' for c in f.wire.calls), 1)

    def test_capability_labels_are_scoped_and_rollout_gated(self):
        f = self.fixture
        views = [{'id': f.connection, 'platform': 'Discord', 'capabilities': {}, 'connectionState': 'connected'}]
        annotate_capabilities(views, f.repo.state, ACTOR, NOW, f.provider)
        self.assertEqual(views[0]['capabilities']['analytics']['availability'], 'consent_required')
        f.grant(); annotate_capabilities(views, f.repo.state, ACTOR, NOW, f.provider)
        self.assertEqual(views[0]['capabilities']['analytics']['level'], 'Direct')
        self.assertIn('No impressions or reach', views[0]['capabilities']['analytics']['evidence'])
        f.provider.engagement_v1_enabled = False; views[0]['capabilities'] = {}
        annotate_capabilities(views, f.repo.state, ACTOR, NOW, f.provider)
        self.assertEqual(views[0]['capabilities'], {})

    def test_exact_engagement_queries_share_existing_route_identity(self):
        from postriff_phase2.discord.rate_limits import route_identity, RateCoordinatorUnavailable
        self.assertEqual(route_identity('GET', f'/channels/{FIRST}/messages?limit=50'), route_identity('GET', f'/channels/{FIRST}/messages'))
        self.assertEqual(route_identity('GET', f'/guilds/{GUILD}?with_counts=true'), route_identity('GET', f'/guilds/{GUILD}'))
        for path in (f'/channels/{FIRST}/messages?limit=100', f'/channels/{FIRST}/messages?limit=50&before=12345',
                     f'/guilds/{GUILD}?with_counts=true&other=1', f'/guilds/{GUILD}?with_counts=false'):
            with self.subTest(path=path), self.assertRaises(RateCoordinatorUnavailable): route_identity('GET', path)

    def test_denied_final_read_guard_retires_admission_without_refund_or_http(self):
        f = self.fixture
        calls = [0]
        def guard():
            calls[0] += 1
            if calls[0] > 1: raise AlphaError('Synthetic consent withdrawn', 409)
            return True
        with self.assertRaises(AlphaError): f.provider._bot('GET', '/users/@me', read_authorize=guard)
        self.assertEqual(f.wire.calls, [])
        self.assertEqual([a['state'] for a in f.ledger.admissions.values()], ['blocked'])
        spent = [row for row in f.ledger.states.values() if row['kind'] == 'policy']
        self.assertTrue(spent and spent[0]['left'] < spent[0]['cap'])

    def _extended_policy(self):
        return {'schema': 'rafii.discord.message-content-evidence.v1', 'applicationId': APP, 'botUserId': BOT,
                'permission': 'MESSAGE_CONTENT', 'reviewStatus': 'approved', 'reviewReference': 'synthetic-review-record',
                'approvedBy': 'synthetic-operator', 'issuedAt': NOW - 1, 'expiresAt': NOW + 3600}

    def test_extended_content_requires_server_record_and_live_provider_flag(self):
        f = self.fixture
        status = f.service.status(WORKSPACE, 'owner', f.connection)
        target = next(d for d in status['destinations'] if d['target']['id'] == f.destination)
        body = {'destinationId': f.destination, 'targetDigest': target['targetDigest'], 'confirmed': True,
                'permissions': {'analytics': True, 'inbox': True, 'reply': True}, 'contentAccess': 'approved_content'}
        with self.assertRaises(AlphaError): f.service.consent(WORKSPACE, 'owner', f.connection, body)
        f.provider.message_content_evidence_raw = self._extended_policy()
        f.service.consent(WORKSPACE, 'owner', f.connection, body)
        with self.assertRaises(AlphaError):
            f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertFalse(any(path == f'/channels/{FIRST}/messages' for _, path, *_ in f.wire.calls))

    def test_extended_content_is_explicit_consent_and_filters_only_exact_channel(self):
        f = self.fixture
        f.provider.message_content_evidence_raw = self._extended_policy()
        f.wire.application_flags = 1 << 18
        f.grant()  # Live flags alone never widen limited consent.
        narrow = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertNotIn('Unrelated private text', json.dumps(narrow))
        status = f.service.status(WORKSPACE, 'owner', f.connection)
        target = next(d for d in status['destinations'] if d['target']['id'] == f.destination)
        f.service.consent(WORKSPACE, 'owner', f.connection, {'destinationId': f.destination, 'targetDigest': target['targetDigest'],
            'confirmed': True, 'permissions': {'analytics': True, 'inbox': True, 'reply': True}, 'contentAccess': 'approved_content'})
        f.repo.now += 16; f.ledger.now = f.repo.now
        broad = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
        self.assertEqual(broad['contentAccess'], 'approved_content')
        self.assertIn('Unrelated private text', json.dumps(broad))
        self.assertNotIn('Unrelated private text', json.dumps(f.repo.state))
        f.wire.parent['mentions'] = []
        review = f.preview()
        self.assertEqual(review['manifest']['engagementReply']['contentAccess'], 'approved_content')
        f.provider.message_content_evidence_raw = None
        with self.assertRaises(AlphaError): f.approve(review)

    def _grant_extended_fixture(self):
        f = EngagementFixture()
        f.provider.message_content_evidence_raw = self._extended_policy()
        status = f.service.status(WORKSPACE, 'owner', f.connection)
        target = next(d for d in status['destinations'] if d['target']['id'] == f.destination)
        f.service.consent(WORKSPACE, 'owner', f.connection, {'destinationId': f.destination, 'targetDigest': target['targetDigest'],
            'confirmed': True, 'permissions': {'analytics': True, 'inbox': True, 'reply': True}, 'contentAccess': 'approved_content'})
        return f

    def test_extended_flags_conflicts_fail_closed_in_both_directions(self):
        for fields in ({'flags': 0, 'flags_new': str(1 << 18)}, {'flags': 1 << 18, 'flags_new': '0'},
                       {'flags': 1 << 18, 'flags_new': str(1 << 19)}):
            with self.subTest(fields=fields):
                f = self._grant_extended_fixture(); f.wire.application_fields = fields
                with self.assertRaises(AlphaError) as denied:
                    f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
                self.assertEqual(denied.exception.code, 'discord_message_content_approval_required')
                self.assertFalse(any(path == f'/channels/{FIRST}/messages' for _, path, *_ in f.wire.calls))

    def test_extended_flags_missing_or_invalid_fail_closed(self):
        for fields in ({}, {'flags': True}, {'flags_new': '-1'}, {'flags_new': str(1 << 64)},
                       {'flags': 1 << 18, 'flags_new': None}, {'flags': '262144', 'flags_new': '262144'}):
            with self.subTest(fields=fields):
                f = self._grant_extended_fixture(); f.wire.application_fields = fields
                with self.assertRaises(AlphaError):
                    f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
                self.assertFalse(any(path == f'/channels/{FIRST}/messages' for _, path, *_ in f.wire.calls))

    def test_extended_flags_documented_representations_agree(self):
        for fields in ({'flags': 1 << 18}, {'flags_new': str(1 << 19)}, {'flags': 1 << 18, 'flags_new': str(1 << 18)}):
            with self.subTest(fields=fields):
                f = self._grant_extended_fixture(); f.wire.application_fields = fields
                result = f.service.read(WORKSPACE, 'owner', f.connection, {'kind': 'inbox', 'destinationId': f.destination})
                self.assertEqual(result['contentAccess'], 'approved_content')
                self.assertIn('Unrelated private text', json.dumps(result))

    def test_expired_or_wrong_app_extended_record_is_not_eligible(self):
        f = self.fixture
        for overrides in ({'expiresAt': NOW - 1}, {'applicationId': '9999999'}, {'botUserId': '1111111'}):
            f.provider.message_content_evidence_raw = {**self._extended_policy(), **overrides}
            status = f.service.status(WORKSPACE, 'owner', f.connection)
            self.assertFalse(status['destinations'][0]['broaderContentEligible'])



if __name__ == '__main__': unittest.main()
