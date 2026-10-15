"""P0 offline behavioral regressions. No real DB, users, credentials or HTTP.

SQL concurrency and RLS are separate disposable-PostgreSQL gates. These mocks
exercise actual approval/worker/adapter code and cannot certify those gates.
"""
import copy
import hashlib
import json
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.contracts import digest
from postriff_phase2.discord import authorization as auth
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.social_connectors import DiscordProvider
from postriff_phase2 import campaigns, publisher

NOW = 1_800_000_000.0
WORKSPACE = '10000000-0000-4000-8000-000000000001'
ACTOR = '20000000-0000-4000-8000-000000000001'
GUILD, APP, BOT, USER = '555555', '1234567', '9000009', '4242424'
FIRST, SECOND, THIRD = '7777777', '8888888', '9999999'
GENERATION = '30000000-0000-4000-8000-000000000001'


def fixture():
    commands = HostedPhase2Commands(clock=lambda: NOW)
    state = initial_state(WORKSPACE)
    state['phase2'] = {'channels': [], 'assets': [], 'reviews': [], 'jobs': []}
    channel = {'id': 'discord-connection', 'platform': 'Discord', 'account': 'Synthetic server',
               'providerAccountId': GUILD, 'configured': True, 'identityVerified': True,
               'capabilityVerified': True, 'scopes': ['bot', 'identify'], 'verifiedAt': NOW,
               'expiresAt': NOW + 86400, 'capabilityVersion': 1, 'revoked': False,
               'evidenceSource': 'synthetic', 'discordAuthorizationGeneration': GENERATION}
    state['phase2']['channels'].append(channel)
    variant = {'id': 'synthetic-draft', 'platform': 'Discord', 'text': 'Synthetic approval test @everyone',
               'language': 'en', 'revision': 1, 'voiceRevision': None, 'briefRevision': 1,
               'sourceIds': [], 'needsReview': False, 'blockedByRetraction': False,
               'unknowns': [], 'warnings': [], 'contentTypeId': 'unclassified',
               'contentTypeVersion': 'legacy', 'formatId': None}
    state['variants'].append(variant)
    for target in (FIRST, SECOND):
        auth.register_destination(state, channel, {'applicationId': APP, 'botUserId': BOT,
            'linkedUserId': USER, 'guildId': GUILD, 'channelId': target,
            'guildName': 'Synthetic server', 'channelName': '#synthetic-' + target,
            'kind': 'text'}, GENERATION, ACTOR, NOW)
    return commands.engine, state, channel, variant


def review(engine, state, channel, variant, target=FIRST, at=NOW + 300, actor=ACTOR):
    payload = {'variantId': variant['id'], 'channelId': channel['id'],
               'destinationId': auth.destination_id(WORKSPACE, channel['id'], GUILD, target),
               'localTime': datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M'),
               'timeZone': 'UTC', 'acknowledgedWarnings': []}
    engine.apply_phase2(None, state, 'review', payload, {'user_id': actor})
    return state['phase2']['reviews'][-1]


def approve(engine, state, entry, actor=ACTOR):
    engine.apply_phase2(None, state, 'approve', {'reviewId': entry['id'], 'digest': entry['digest'],
                                               'confirmed': True}, {'user_id': actor})
    return next(j for j in state['phase2']['jobs'] if j['id'] == entry['jobId'])


class SyntheticWire:
    """Deterministic Discord responses; no real transport is reachable."""
    def __init__(self):
        self.calls = []
        self.allowed = {FIRST, SECOND}
        self.user_roles = []
        self.restricted = None
        self.malformed = None
        self.post_status = 200
        self.message = None

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        path = url.removeprefix(DiscordProvider.API)
        self.calls.append((method, path, body))
        status = 200
        required = DiscordProvider.PERMISSIONS | DiscordProvider.MANAGE_GUILD
        if path == '/oauth2/applications/@me': result = {'id': APP}
        elif path == '/users/@me': result = {'id': BOT, 'bot': True}
        elif path == '/guilds/' + GUILD:
            result = {'id': GUILD, 'name': 'Synthetic server', 'owner_id': '1000001',
                      'roles': [{'id': GUILD, 'permissions': str(required)}]}
        elif path in ('/guilds/' + GUILD + '/members/' + BOT, '/guilds/' + GUILD + '/members/' + USER):
            uid = path.rsplit('/', 1)[1]
            result = {'user': {'id': uid}, 'roles': [], 'pending': False, 'communication_disabled_until': None}
            if uid == USER and self.restricted: result.update(self.restricted)
        elif path == '/guilds/' + GUILD + '/channels':
            result = [{'id': cid, 'guild_id': GUILD, 'name': 'synthetic-' + cid, 'type': 0,
                       'permission_overwrites': []} for cid in sorted(self.allowed)]
            if self.malformed: result[0].pop(self.malformed, None)
        elif method == 'POST' and path.startswith('/channels/') and path.endswith('/messages'):
            status = self.post_status
            result = {'id': '4444444', 'channel_id': path.split('/')[2], 'content': (body or {}).get('content'),
                      'author': {'id': BOT, 'bot': True}}
            self.message = result
        elif method == 'GET' and path.endswith('/messages/4444444'):
            result = {**(self.message or {}), 'id': '4444444', 'channel_id': FIRST,
                      'content': 'Synthetic approval test @everyone', 'author': {'id': BOT, 'bot': True},
                      'mention_everyone': False, 'mentions': [], 'mention_roles': [], 'attachments': []}
        else: raise AssertionError('Unexpected synthetic route: ' + method + ' ' + path)
        return {'status': status, 'body': result, 'headers': {}}


class SyntheticGrants:
    def __init__(self):
        self.generation = GENERATION
        self.selected = FIRST
        self.revoked = False

    def discord_grant_for_worker(self, wid, connection, *, cur=None):
        if wid != WORKSPACE or connection != 'discord-connection' or self.revoked:
            raise AlphaError('Synthetic grant unavailable.', 409)
        return {'provider': 'discord', 'scopes': ['bot', 'identify'], 'authorizationGeneration': self.generation,
                'accessToken': json.dumps({'v': 2, 'guild': GUILD, 'user': USER, 'channel': self.selected,
                                          'applicationId': APP, 'botUserId': BOT})}


class SyntheticDatabase:
    def __init__(self, state): self.state, self.revision, self.queries = state, 1, []
    @contextmanager
    def connection(self): yield self
    @contextmanager
    def cursor(self): yield self
    def execute(self, sql, params=()):
        self.queries.append(sql)
        if sql.startswith('SELECT revision,state'): self.result = (self.revision, copy.deepcopy(self.state))
        elif sql.startswith('SELECT state'): self.result = (copy.deepcopy(self.state),)
        elif sql.startswith('SELECT m.role'): self.result = ('owner', True)
        elif sql.startswith('UPDATE public.pr_workspaces'):
            self.state = json.loads(params[0]); self.revision += 1; self.result = None
        else: raise AssertionError('Unexpected fake SQL: ' + sql)
        self.rowcount = 1
    def fetchone(self): return self.result


def transport_and_worker(state):
    wire, grants = SyntheticWire(), SyntheticGrants()
    provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot-token', 'https://example.invalid', transport=wire, production_reviewed=True)
    provider.authorization_v2_enabled = True
    social = HostedSocial(grants, {'discord': provider})
    db = SyntheticDatabase(state)
    worker = PostgresWorker(db.connection, social, clock=lambda: NOW + 301, worker_id='synthetic-worker')
    return wire, grants, social, db, worker


def claimed_job(job):
    job.update(state='submitting', leaseOwner='synthetic-worker', leaseUntil=NOW + 1000, leaseId='synthetic-lease',
               attempts=[{'number': 1, 'startedAt': NOW + 301}])
    return {'workspaceId': WORKSPACE, 'job': copy.deepcopy(job), 'reconciliation': False}


class DiscordP0(unittest.TestCase):
    def test_aged_server_bot_installation_keeps_frozen_approval_and_fresh_permission_check(self):
        engine, state, channel, variant = fixture()
        channel.update(discordConnectionKind='installation', qualification='server_verified',
                       evidenceSource='live_provider', verifiedAt=NOW-7200)
        job = approve(engine, state, review(engine, state, channel, variant))
        original = copy.deepcopy(job)
        engine.invalidate(state)
        self.assertEqual(job['state'], original['state'])
        self.assertEqual(job['discordAuthorization'], original['discordAuthorization'])
        self.assertTrue(auth.job_authorized(state, channel, job))
        wire, grants, social, db, worker = transport_and_worker(state)
        social.prepare_discord_dispatch(job['manifest'])
        self.assertTrue(any(call[1] == '/guilds/'+GUILD+'/channels' for call in wire.calls))
        wire.allowed.clear()
        with self.assertRaises(AlphaError): social.prepare_discord_dispatch(job['manifest'])
        self.assertEqual(sum(call[0] == 'POST' for call in wire.calls), 0)
        self.assertEqual(job, original)

    def test_aged_installation_exception_preserves_other_readiness_boundaries(self):
        engine, state, channel, variant = fixture()
        channel.update(discordConnectionKind='installation', qualification='server_verified',
                       evidenceSource='live_provider', verifiedAt=NOW-7200)
        self.assertEqual(engine.channel_state(channel), 'Ready for posting')
        for changed in ({'revoked':True}, {'expiresAt':NOW}, {'configured':False},
                        {'identityVerified':False}, {'capabilityVerified':False},
                        {'discordConnectionKind':'identity'}, {'platform':'LinkedIn'},
                        {'qualification':'implemented_with_fixtures'}, {'evidenceSource':'synthetic'},
                        {'discordAuthorizationGeneration':None}):
            with self.subTest(changed=changed):
                self.assertNotEqual(engine.channel_state({**channel,**changed}), 'Ready for posting')

    def test_timezone_metadata_cached_once_with_exact_package_or_system_label(self):
        import importlib.metadata
        from postriff_phase2.contracts import tzdb_version
        for failure in (False, True):
            tzdb_version.cache_clear()
            try:
                with patch('importlib.metadata.version', side_effect=importlib.metadata.PackageNotFoundError('tzdata') if failure else None,
                           return_value='2026.2') as lookup:
                    first=tzdb_version()
                    self.assertTrue(first.startswith('system:') if failure else first=='tzdata 2026.2')
                    self.assertEqual(tzdb_version(),first)
                    lookup.assert_called_once_with('tzdata')
            finally:
                tzdb_version.cache_clear()

    def test_original_destination_mutation_exploit_is_blocked(self):
        engine, state, channel, variant = fixture()
        entry = review(engine, state, channel, variant)
        job = approve(engine, state, entry)
        claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state)
        manifest_before = copy.deepcopy(job['manifest'])
        with patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden')):
            claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest'])
            # The reproduced exploit changed the encrypted session's default.
            grants.selected = SECOND
            channel['defaultDestinationId'] = auth.destination_id(WORKSPACE, channel['id'], GUILD, SECOND)
            with patch('postriff_phase2.billing.require_publishing', return_value=None):
                self.assertTrue(worker.authorize_dispatch(claimed))
            receipt = social.submit_discord_authorized(claimed['job']['manifest'], claimed['discordDispatch'])
        posts = [c for c in wire.calls if c[0] == 'POST']
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], '/channels/' + FIRST + '/messages')
        self.assertEqual(posts[0][2]['allowed_mentions'], {'parse': []})
        self.assertTrue(posts[0][2]['enforce_nonce'])
        self.assertEqual(receipt['reference'], FIRST + '/4444444')
        self.assertEqual(claimed['job']['manifest'], manifest_before)
        self.assertTrue(auth.job_authorized(db.state, db.state['phase2']['channels'][0], db.state['phase2']['jobs'][0]))
        self.assertNotIn('accessToken', json.dumps(db.state))

    def test_unapproved_channel_cannot_be_reviewed(self):
        engine, state, channel, variant = fixture()
        with self.assertRaises(AlphaError): review(engine, state, channel, variant, target=THIRD)

    def test_content_edit_invalidates_approval(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        variant.update(text='Edited after approval', revision=2)
        self.assertFalse(engine.current(state, job['manifest']))

    def test_removed_destination_invalidates_approval(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        auth.revoke_destination(state, channel, job['manifest']['destinationId'], ACTOR, NOW + 1)
        self.assertFalse(auth.job_authorized(state, channel, job))

    def test_tenant_cannot_borrow_another_destination(self):
        engine, state, channel, variant = fixture(); state['workspace']['id'] = '10000000-0000-4000-8000-000000000002'
        with self.assertRaises(AlphaError): review(engine, state, channel, variant)

    def test_legacy_approval_and_direct_adapter_submit_are_held(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state)
        legacy = copy.deepcopy(job['manifest']); legacy.pop('discord')
        self.assertFalse(engine.current(state, legacy))
        self.assertEqual(social.submit(job['manifest'])['state'], 'held')
        self.assertEqual(social._submit_discord(job['manifest'], social.providers['discord'], grants.discord_grant_for_worker(WORKSPACE, channel['id'])['accessToken'])['state'], 'held')
        self.assertEqual(wire.calls, [])

    def test_reconnect_between_preflight_and_handoff_is_blocked(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state)
        claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest']); grants.generation = 'replacement-generation'
        with patch('postriff_phase2.billing.require_publishing', return_value=None): self.assertFalse(worker.authorize_dispatch(claimed))
        self.assertFalse(any(c[0] == 'POST' for c in wire.calls))

    def test_revocation_between_preflight_and_handoff_is_blocked(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state)
        claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest']); grants.revoked = True
        with patch('postriff_phase2.billing.require_publishing', return_value=None): self.assertFalse(worker.authorize_dispatch(claimed))
        self.assertFalse(any(c[0] == 'POST' for c in wire.calls))

    def test_two_destinations_have_independent_jobs(self):
        engine, state, channel, variant = fixture()
        first = approve(engine, state, review(engine, state, channel, variant, FIRST))
        second = approve(engine, state, review(engine, state, channel, variant, SECOND))
        self.assertNotEqual(first['id'], second['id']); self.assertNotEqual(first['manifest']['idempotencyKey'], second['manifest']['idempotencyKey'])
        self.assertEqual(len(state['phase2']['jobs']), 2)

    def test_two_approvers_cannot_allocate_the_same_publication_id(self):
        engine, state, channel, variant = fixture(); other = '20000000-0000-4000-8000-000000000002'
        first = approve(engine, state, review(engine, state, channel, variant))
        second = approve(engine, state, review(engine, state, channel, variant, actor=other), actor=other)
        self.assertNotEqual(first['id'], second['id'])

    def test_automation_preserves_original_human_destination_and_time(self):
        engine, state, channel, variant = fixture()
        target = auth.destination(state, channel, auth.destination_id(WORKSPACE, channel['id'], GUILD, FIRST))
        task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
        item = {'key': 'synthetic-item', 'platform': 'Discord', 'channelId': channel['id'],
                'variantId': variant['id'], 'state': 'ready_for_review', 'publishAt': NOW + 300}
        run = {'id': 'synthetic-run', 'taskId': task['id'], 'items': [item]}
        root = campaigns._root(state); root['recurringTasks'].append(task); root['occurrences'].append(run)
        campaigns._decide(state, root, {'occurrenceId': run['id'], 'itemKey': item['key'],
             'decision': 'approve', 'confirmed': True, 'variantRevision': 1, 'excludedUnknowns': [],
             'acknowledgedWarnings': [], 'destinationId': target['id'],
             'destinationGeneration': target['resourceGeneration'], 'publishAt': NOW + 300}, ACTOR, NOW)
        frozen = copy.deepcopy(item['decision'])
        channel['defaultDestinationId'] = auth.destination_id(WORKSPACE, channel['id'], GUILD, SECOND)
        queued = publisher.commit(engine, state, ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, NOW + 60)
        job = next(j for j in state['phase2']['jobs'] if j['id'] == queued['jobId'])
        self.assertEqual(job['manifest']['discord'], frozen['discord'])
        self.assertEqual(job['manifest']['timing'], frozen['timing'])
        self.assertEqual(job['discordHumanApproval']['at'], NOW)
        self.assertTrue(auth.job_authorized(state, channel, job))
        item['publishAt'] += 60
        self.assertFalse(auth.job_authorized(state, channel, job))

    def test_stale_prepared_review_cannot_bypass_uncertain_delivery(self):
        engine, state, channel, variant = fixture()
        first_review = review(engine, state, channel, variant)
        second_review = review(engine, state, channel, variant, at=NOW + 600)
        first = approve(engine, state, first_review); first['state'] = 'uncertain'
        first['discordDispatchIntents'] = [{'id': 'possibly-transmitted'}]
        with self.assertRaises(AlphaError): approve(engine, state, second_review)

    def test_second_preapproved_job_cannot_bypass_uncertain_delivery_at_handoff(self):
        engine, state, channel, variant = fixture()
        first = approve(engine, state, review(engine, state, channel, variant))
        second = approve(engine, state, review(engine, state, channel, variant, at=NOW + 600))
        claimed = claimed_job(second); wire, grants, social, db, worker = transport_and_worker(state)
        claimed['discordPrepared'] = social.prepare_discord_dispatch(second['manifest'])
        first['state'] = 'uncertain'; first['discordDispatchIntents'] = [{'id': 'possibly-transmitted'}]
        with patch('postriff_phase2.billing.require_publishing', return_value=None): self.assertFalse(worker.authorize_dispatch(claimed))
        self.assertFalse(any(c[0] == 'POST' for c in wire.calls))

    def test_ambiguous_delivery_blocks_another_approval_and_never_reposts(self):
        for outcome in ('timeout', 'server_error'):
            with self.subTest(outcome=outcome):
                engine, state, channel, variant = fixture()
                job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
                wire, grants, social, db, worker = transport_and_worker(state)
                claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest'])
                with patch('postriff_phase2.billing.require_publishing', return_value=None):
                    self.assertTrue(worker.authorize_dispatch(claimed))
                if outcome == 'server_error':
                    wire.post_status = 500
                else:
                    def timeout(method, url, **kwargs):
                        if method == 'POST':
                            wire.calls.append((method, url.removeprefix(DiscordProvider.API), kwargs.get('body')))
                            raise TimeoutError('Synthetic connection lost after transmission')
                        return wire(method, url, **kwargs)
                    social.providers['discord'].transport = timeout
                receipt = social.submit_discord_authorized(claimed['job']['manifest'], claimed['discordDispatch'])
                self.assertEqual(receipt['state'], 'uncertain')
                self.assertTrue(worker.complete(claimed, receipt))
                self.assertEqual(db.state['phase2']['jobs'][0]['discordReceipts'][-1]['deliveryEvidence'], 'uncertain')
                with self.assertRaises(AlphaError):
                    review(engine, db.state, db.state['phase2']['channels'][0], db.state['variants'][0], at=NOW + 600)
                with patch('postriff_phase2.billing.require_publishing', return_value=None):
                    self.assertFalse(worker.authorize_dispatch(claimed))
                self.assertEqual(sum(call[0] == 'POST' for call in wire.calls), 1)

    def test_missing_permission_overwrites_are_not_treated_as_empty(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state); wire.malformed = 'permission_overwrites'
        with self.assertRaises(AlphaError): social.prepare_discord_dispatch(job['manifest'])

    def test_timeout_and_pending_members_cannot_authorize(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state)
        for restriction in ({'pending': True}, {'communication_disabled_until': '2099-01-01T00:00:00Z'}):
            wire.restricted = restriction
            with self.assertRaises(AlphaError): social.prepare_discord_dispatch(job['manifest'])

    def test_permission_loss_blocks_dispatch(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state); wire.allowed = {SECOND}
        with self.assertRaises(AlphaError): social.prepare_discord_dispatch(job['manifest'])

    def test_expired_lease_cannot_dispatch(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state); claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest'])
        job['leaseUntil'] = NOW
        with patch('postriff_phase2.billing.require_publishing', return_value=None): self.assertFalse(worker.authorize_dispatch(claimed))

    def test_late_receipt_is_retained_without_overwriting_new_lease(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state); claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest'])
        with patch('postriff_phase2.billing.require_publishing', return_value=None): self.assertTrue(worker.authorize_dispatch(claimed))
        db.state['phase2']['jobs'][0].update(leaseOwner='new-worker', leaseId='new-lease', state='uncertain')
        self.assertFalse(worker.complete(claimed, {'state': 'provider_accepted', 'reference': FIRST + '/4444444', 'confirmed': 'Synthetic late response', 'discordDeliveryEvidence': 'accepted'}))
        current = db.state['phase2']['jobs'][0]
        self.assertEqual(current['leaseOwner'], 'new-worker'); self.assertEqual(current['leaseId'], 'new-lease')
        self.assertEqual(current['state'], 'uncertain'); self.assertEqual(current['discordReceipts'][0]['reference'], FIRST + '/4444444')
        self.assertNotIn('providerReference', current)

    def test_duplicate_intent_cannot_authorize_a_second_post(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant)); claimed = claimed_job(job)
        wire, grants, social, db, worker = transport_and_worker(state); claimed['discordPrepared'] = social.prepare_discord_dispatch(job['manifest'])
        with patch('postriff_phase2.billing.require_publishing', return_value=None):
            self.assertTrue(worker.authorize_dispatch(claimed)); self.assertFalse(worker.authorize_dispatch(claimed))
        self.assertEqual(len(db.state['phase2']['jobs'][0]['discordDispatchIntents']), 1)

    def test_reconciliation_uses_frozen_channel_after_default_change(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state); grants.selected = SECOND
        result = social.reconcile(job['manifest'], {'providerReference': FIRST + '/4444444'})
        self.assertEqual(result['state'], 'verified'); self.assertEqual(wire.calls[-1][1], '/channels/' + FIRST + '/messages/4444444')

    def test_reference_for_another_channel_is_never_looked_up(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state)
        self.assertEqual(social.reconcile(job['manifest'], {'providerReference': SECOND + '/4444444'})['state'], 'uncertain')
        self.assertEqual(wire.calls, [])

    def test_known_receipt_rate_wait_resumes_only_frozen_lookup(self):
        from postriff_phase2.discord.rate_limits import RateDelayed, ReadAdmissionDelayed
        from postriff_phase2.outcomes import normalize_result
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        wire, grants, social, db, worker = transport_and_worker(state)
        job['providerReference'] = FIRST + '/4444444'
        before = copy.deepcopy(job)
        with patch.object(social.providers['discord'], '_bot', side_effect=ReadAdmissionDelayed(RateDelayed(172800.25))):
            result = normalize_result(social.reconcile(job['manifest'], job), job, True)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertTrue(result['discordReadDeferred'])
        self.assertTrue(result['discordReadAdmissionDenied'])
        self.assertEqual(result['retryAfterSeconds'], 172801)
        self.assertEqual(result['reference'], before['providerReference'])
        self.assertEqual(job, before)
        self.assertFalse(wire.calls)
        self.assertEqual(social.reconcile(job['manifest'], job)['state'], 'verified')
        self.assertTrue(all(method == 'GET' for method, _, _ in wire.calls))
        self.assertEqual(wire.calls[-1][1], '/channels/' + FIRST + '/messages/4444444')

    def test_read_wait_cannot_authorize_a_create_or_substitute_receipt(self):
        from postriff_phase2.outcomes import normalize_result
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        job['providerReference'] = FIRST + '/4444444'
        result = {'state': 'provider_accepted', 'confirmed': 'Synthetic read wait',
                  'reference': job['providerReference'], 'discordDeliveryEvidence': 'accepted',
                  'discordReadDeferred': True, 'retryAfterSeconds': 2}
        self.assertEqual(normalize_result(result, job, False)['state'], 'uncertain')
        result['reference'] = SECOND + '/4444444'
        self.assertEqual(normalize_result(result, job, True)['state'], 'uncertain')

    def test_provider_429_spends_read_check_but_unsent_get_does_not(self):
        from postriff_phase2.discord.rate_limits import RateDelayed, ReadAdmissionDelayed
        for error, denied in ((ReadAdmissionDelayed(RateDelayed(2)), True), (RateDelayed(2, cause='provider_429'), False)):
            engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
            job.update(providerReference=FIRST + '/4444444', checks=5)
            claimed = claimed_job(job); claimed['reconciliation'] = True
            wire, grants, social, db, worker = transport_and_worker(state)
            with patch.object(social.providers['discord'], '_bot', side_effect=error):
                result = social.reconcile(job['manifest'], job)
            self.assertEqual(result['discordReadAdmissionDenied'], denied)
            self.assertTrue(worker.complete(claimed, result))
            current = db.state['phase2']['jobs'][0]
            self.assertEqual(current['checks'], 4 if denied else 5)
            self.assertEqual(current['nextAt'], NOW + 303 if denied else NOW + 301 + 86400)
            self.assertEqual(current['providerReference'], FIRST + '/4444444')
            self.assertEqual(current['discordAuthorization'], job['discordAuthorization'])
            self.assertFalse(wire.calls)

    def test_legacy_standing_automation_authority_is_rejected(self):
        engine, state, channel, variant = fixture(); job = approve(engine, state, review(engine, state, channel, variant))
        job['automation'] = {'approvedVia': 'owner_preauthorization'}
        self.assertFalse(auth.job_authorized(state, channel, job))
        self.assertTrue(publisher.auto_blockers(state, {}, {}, {'platform': 'Discord'}, variant))

    def test_media_hash_checked_against_actual_bytes_before_handoff(self):
        engine, state, channel, variant = fixture(); entry = review(engine, state, channel, variant)
        media = {'id': 'image', 'mime': 'image/png', 'bytes': 3, 'hash': hashlib.sha256(b'old').hexdigest(), 'alt': 'Synthetic image'}
        entry['manifest']['media'] = [media]
        auth.freeze_manifest(state, channel, entry['manifest'], entry['manifest']['destinationId'])
        wire, grants, social, db, worker = transport_and_worker(state)
        social.assets = SimpleNamespace(storage=SimpleNamespace(get=lambda *_: b'new'))
        with self.assertRaises(AlphaError): social.prepare_discord_dispatch(entry['manifest'])
        self.assertFalse(any(c[0] == 'POST' for c in wire.calls))

    def test_discord_versioned_envelope_accepts_v2_and_holds_legacy_authority(self):
        token = SyntheticGrants().discord_grant_for_worker(WORKSPACE, 'discord-connection')['accessToken']
        self.assertEqual(DiscordProvider.session(token)['v'], 2)
        with self.assertRaises(AlphaError): DiscordProvider.session(json.dumps({'v': 3, 'guild': GUILD}))


if __name__ == '__main__': unittest.main()
