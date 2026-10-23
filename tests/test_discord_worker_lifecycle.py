"""Small offline P3/P4 controls. Fake SQL does not certify PostgreSQL concurrency.

The separate guarded SQL fixture exercises real locks, leases and fairness.
No real credentials, customer data, network or database are used here.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import worker as policy
from postriff_phase2.discord.lane import _SOONEST as DUE_PROBE
from postriff_phase2 import security_holds
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker, due_workspaces_sql
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import (
    ACTOR, APP, FIRST, GENERATION, NOW, WORKSPACE, SyntheticGrants,
    SyntheticWire, approve, fixture, review,
)


class UndefinedTable(Exception):
    sqlstate = '42P01'


class MemoryDatabase:
    """A single-tenant SQL boundary double, not a lock/RLS implementation."""
    def __init__(self, state):
        self.state, self.now, self.revision = copy.deepcopy(state), NOW + 301, 1
        self.queries, self.cursor_ready, self.member = [], True, ('owner', True)
        self.projection_ready = False
        self.security_hold = False

    @contextmanager
    def connection(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        self.rows, self.rowcount = [], 1
        if sql == security_holds._PROBE:
            self.rows = [(True,)]
        elif sql.startswith('SELECT hold_active FROM public.pr_security_account_controls WHERE user_id='):
            self.rows = [(self.security_hold,)]
        elif sql == DUE_PROBE:  # the W-02 lane's projection probe: the clock and the soonest due Discord work
            if not self.projection_ready:
                raise UndefinedTable('relation "public.pr_discord_worker_projection" does not exist')
            live = [j for j in self.state['phase2']['jobs'] if j.get('manifest', {}).get('platform') == 'Discord'
                    and j['state'] not in ('verified', 'failed', 'canceled', 'held')]
            self.rows = [(self.now, min((max(j.get('leaseUntil', 0), j.get('nextAt', 0)) for j in live), default=None))]
        elif sql.startswith('SELECT extract(epoch from clock_timestamp()'):
            self.rows = [(self.now,)]
        elif sql.startswith('SELECT pg_try_advisory'):
            self.rows = [(True,)]
        elif sql == "SELECT to_regclass('public.pr_discord_worker_projection')":
            self.rows = [('pr_discord_worker_projection' if self.projection_ready else None,)]
        elif sql.startswith('SELECT to_regclass'):
            self.rows = [('pr_worker_tenants' if self.cursor_ready else None,)]
        elif sql.startswith('SELECT revision,state') or sql.startswith('SELECT state'):
            if params[0] == WORKSPACE:
                self.rows = [(self.revision, copy.deepcopy(self.state))] if sql.startswith('SELECT revision') else [(copy.deepcopy(self.state),)]
        elif sql.startswith('SELECT id::text,revision,state'):
            if params[0] == WORKSPACE:
                self.rows = [(WORKSPACE, self.revision, copy.deepcopy(self.state))]
        elif sql.startswith('SELECT w.id::text,w.revision,w.state'):
            excluded = params[2] if len(params) == 3 else []
            jobs = self.state['phase2']['jobs']
            due = any(j['state'] not in ('verified', 'failed', 'canceled', 'held')
                      and j.get('leaseUntil', 0) <= params[0] and j.get('nextAt', 0) <= params[1] for j in jobs)
            if WORKSPACE not in excluded and due and not policy.in_flight(jobs, self.now):
                self.rows = [(WORKSPACE, self.revision, copy.deepcopy(self.state))]
        elif sql.startswith('SELECT m.role'):
            self.rows = [self.member] if self.member else []
        elif sql.startswith('UPDATE public.pr_workspaces'):
            if params[1] != WORKSPACE or len(params) == 3 and params[2] != self.revision:
                self.rowcount = 0
            else:
                self.state = json.loads(params[0]); self.revision += 1
        elif sql.startswith('INSERT INTO public.pr_worker_tenants'):
            pass
        elif sql.startswith('WITH sample AS MATERIALIZED'):
            jobs = self.state['phase2']['jobs']
            live = [j for j in jobs if j['state'] not in ('verified', 'failed', 'canceled', 'held')]
            eligible = [j for j in live if j.get('leaseUntil', 0) <= self.now]
            self.rows = [(len(live), max([max(0, self.now-j.get('nextAt', self.now)) for j in eligible] or [0]),
                          sum(j['state'] == 'held' for j in jobs), sum(j['state'] == 'uncertain' for j in jobs),
                          sum(bool(j.get(policy.KEY, {}).get('deadLetter')) for j in jobs))]
        else:
            raise AssertionError('Unexpected fake SQL: ' + sql)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class WorkerLifecycle(unittest.TestCase):
    def setUp(self):
        # Model the installed core-hold table; never mock the production hold
        # check or leak its process-wide availability cache between tests.
        self.hold_cache=patch.dict(security_holds._INSTALLED,{'readable':True,'checked':float('-inf')})
        self.hold_cache.start();self.addCleanup(self.hold_cache.stop)
        engine, state, channel, variant = fixture()
        self.original = copy.deepcopy(approve(engine, state, review(engine, state, channel, variant)))
        self.db, self.wire, self.grants = MemoryDatabase(state), SyntheticWire(), SyntheticGrants()
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                   transport=self.wire, production_reviewed=True)
        provider.authorization_v2_enabled = True
        self.social = HostedSocial(self.grants, {'discord': provider})
        self.worker = PostgresWorker(self.db.connection, self.social, clock=lambda: NOW + 301,
                                     worker_id='owner-one', discord_workers=True)
        self.billing = patch('postriff_phase2.billing.require_publishing', return_value=None)
        self.billing.start(); self.addCleanup(self.billing.stop)
        self.network = patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)

    def job(self):
        return self.db.state['phase2']['jobs'][0]

    def claim(self):
        value = self.worker.claim(discord_only=True)
        self.assertIsNotNone(value)
        return value

    def test_active_core_account_hold_blocks_discord_claim_with_feature_flag_off(self):
        self.db.security_hold=True
        with patch.object(security_holds,'enabled',return_value=False):
            self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(self.job()['state'],'held')
        self.assertFalse(self.job().get('attempts'))
        self.assertFalse(any(call[0]=='POST' for call in self.wire.calls))

    def test_core_hold_placed_after_claim_blocks_discord_handoff_with_flag_off(self):
        claimed=self.claim()
        claimed['discordPrepared']=self.social.prepare_discord_dispatch(claimed['job']['manifest'])
        self.db.security_hold=True
        with patch.object(security_holds,'enabled',return_value=False):
            self.assertFalse(self.worker.authorize_dispatch(claimed))
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(any(call[0]=='POST' for call in self.wire.calls))

    def seal(self, claimed):
        claimed['discordPrepared'] = self.social.prepare_discord_dispatch(claimed['job']['manifest'])
        return self.worker.authorize_dispatch(claimed)

    def assert_frozen(self):
        self.assertEqual(self.job()['manifest'], self.original['manifest'])
        self.assertEqual(self.job()['discordAuthorization'], self.original['discordAuthorization'])
        self.assertEqual(self.job()['approvalDigest'], self.original['approvalDigest'])

    def test_parallel_selection_is_default_off_and_locks_one_row(self):
        self.assertFalse(policy.enabled({}))
        off = PostgresWorker(self.db.connection, discord_workers=False)
        self.assertIsNone(off.claim(discord_only=True))
        self.assertEqual(self.db.queries, [])
        query = due_workspaces_sql(discord_only=True)
        self.assertIn('LIMIT 1 FOR UPDATE OF w SKIP LOCKED', query)
        self.assertIn('discordWorkerCursor,lastClaimedAt', query)
        self.assertNotIn('dispatch.last_claimed_at NULLS FIRST', query)
        self.assertIn('NOT EXISTS', query)
        self.assertIn('LIMIT 100', due_workspaces_sql())

    def test_claim_does_not_take_global_lock_and_second_job_cannot_claim(self):
        claimed = self.claim()
        self.assertFalse(any('pg_try_advisory' in q for q, _ in self.db.queries))
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(self.job()['leaseId'], claimed['job']['leaseId'])
        self.assert_frozen()

    def test_projection_is_only_selection_hint_and_keeps_workspace_lock(self):
        self.db.projection_ready = True
        claimed = self.claim()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['job']['discordAuthorization'], self.original['discordAuthorization'])
        self.assertTrue(any('JOIN public.pr_discord_worker_projection' in sql for sql,_ in self.db.queries))
        projected=due_workspaces_sql(discord_only=True,discord_projected=True)
        self.assertIn('LIMIT 1 FOR UPDATE OF w SKIP LOCKED',projected)
        self.assertNotIn('jsonb_array_elements',projected)
        self.assertNotIn('discordWorkerCursor',projected)
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assert_frozen()

    def test_database_time_not_host_clock_controls_lease(self):
        self.worker.clock = lambda: NOW - 3600
        claimed = self.claim()
        self.assertEqual(claimed['job']['leaseUntil'], self.db.now + 45)
        self.worker.clock = lambda: NOW + 3600
        self.db.now += 10
        self.assertTrue(self.worker.renew_discord_lease(claimed))
        self.assertEqual(self.job()['leaseUntil'], self.db.now + 45)
        self.assert_frozen()

    def test_renewal_never_extends_approval_or_crosses_its_expiry(self):
        claimed = self.claim()
        expiry = self.job()['manifest']['expiresAt']
        self.db.now += 5
        self.assertTrue(self.worker.renew_discord_lease(claimed))
        self.assertEqual(self.job()['manifest']['expiresAt'], expiry)
        self.db.now = self.job()['leaseUntil']
        self.assertFalse(self.worker.renew_discord_lease(claimed))
        self.assertFalse(self.seal(claimed))
        self.assert_frozen()

    def test_foreign_workspace_wrong_owner_and_stale_lease_cannot_renew(self):
        claimed = self.claim()
        for mutate in ('workspace', 'owner', 'lease', 'digest'):
            with self.subTest(mutate=mutate):
                attempted = copy.deepcopy(claimed)
                if mutate == 'workspace': attempted['workspaceId'] = 'foreign-workspace'
                if mutate == 'lease': attempted['job']['leaseId'] = 'old-lease'
                if mutate == 'digest': attempted['job']['approvalDigest'] = 'f'*64
                worker = PostgresWorker(self.db.connection, self.social, clock=lambda: self.db.now,
                    worker_id='foreign-worker' if mutate == 'owner' else self.worker.worker_id, discord_workers=True)
                self.assertFalse(worker.renew_discord_lease(attempted))
        self.assert_frozen()

    def test_revocation_content_permission_and_cancellation_block_renewal(self):
        for change in ('grant', 'content', 'destination', 'membership', 'cancel'):
            with self.subTest(change=change):
                original_state = copy.deepcopy(self.db.state)
                claimed = self.claim()
                claimed['discordPrepared'] = self.social.prepare_discord_dispatch(claimed['job']['manifest'])
                if change == 'grant': self.grants.revoked = True
                elif change == 'content': self.db.state['variants'][-1]['text'] = 'Changed after approval'
                elif change == 'destination': self.db.state['phase2']['channels'][0]['discordDestinations'][0]['status'] = 'revoked'
                elif change == 'membership': self.db.member = ('viewer', False)
                else: self.job()['cancelRequested'] = True
                self.assertFalse(self.worker.renew_discord_lease(claimed))
                self.assertFalse(self.worker.authorize_dispatch(claimed))
                self.assertFalse(any(method == 'POST' for method, _, _ in self.wire.calls))
                self.db.state = original_state; self.grants.revoked = False; self.db.member = ('owner', True)

    def test_expiry_during_credential_lock_check_cannot_seal(self):
        claimed = self.claim()
        claimed['discordPrepared'] = self.social.prepare_discord_dispatch(claimed['job']['manifest'])
        original = self.grants.discord_grant_for_worker
        def delayed(*args, **kwargs):
            grant = original(*args, **kwargs)
            self.db.now = self.job()['leaseUntil'] + 1
            return grant
        with patch.object(self.grants, 'discord_grant_for_worker', side_effect=delayed):
            self.assertFalse(self.worker.authorize_dispatch(claimed))
        self.assertFalse(self.job().get('discordDispatchIntents'))

    def test_approval_expiring_during_claim_checks_does_not_spend_attempt(self):
        original_approved = self.worker._approved
        def expired_after_check(*args, **kwargs):
            allowed = original_approved(*args, **kwargs)
            self.db.now = self.original['manifest']['expiresAt'] + 1
            return allowed
        with patch.object(self.worker, '_approved', side_effect=expired_after_check):
            self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(self.job()['state'], 'held')
        self.assertEqual(self.job()['attempts'], [])
        self.assertFalse(self.job().get('leaseOwner'))
        self.assert_frozen()

    def test_expired_unsent_claim_recovers_same_approval_with_backoff(self):
        first = self.claim()
        self.db.now = first['job']['leaseUntil'] + 1
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(self.job()['state'], 'scheduled')
        self.assertGreater(self.job()['nextAt'], self.db.now)
        self.assertEqual(self.job()[policy.KEY]['recoveries'], 1)
        self.db.now = self.job()['nextAt'] + 1
        second = self.claim()
        self.assertNotEqual(first['job']['leaseId'], second['job']['leaseId'])
        self.assertFalse(self.worker.authorize_dispatch(first))
        self.assertTrue(self.seal(second))
        self.assert_frozen()

    def test_expired_sealed_claim_only_reconciles_and_never_reposts(self):
        claimed = self.claim()
        self.assertTrue(self.seal(claimed))
        self.db.now = self.job()['leaseUntil'] + 1
        recovered = self.claim()
        self.assertTrue(recovered['reconciliation'])
        self.assertFalse(policy.pending_unsent(self.job()))
        result = self.social.reconcile(recovered['job']['manifest'], recovered['job'])
        self.assertTrue(self.worker.complete(recovered, result))
        self.assertEqual(len(self.job()['discordDispatchIntents']), 1)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire.calls))

    def test_rejected_receipt_or_mismatched_marker_is_never_unsent(self):
        claimed = self.claim()
        for change in ('intent', 'receipt', 'marker'):
            candidate = copy.deepcopy(self.job())
            if change == 'intent': candidate['discordDispatchIntents'] = [{'id': 'known-rejection'}]
            elif change == 'receipt': candidate['discordReceipts'] = [{'deliveryEvidence': 'rejected'}]
            else: candidate[policy.KEY]['leaseId'] = 'mismatched'
            self.assertFalse(policy.pending_unsent(candidate))
            self.assertEqual(policy.recovery(candidate, claimed['job']['leaseUntil'] + 1), 'reconcile')

    def test_transient_preflight_is_bounded_and_dead_letter_keeps_authority(self):
        with patch.object(self.social, 'prepare_discord_dispatch', side_effect=TimeoutError('synthetic')):
            for attempt in range(3):
                self.assertTrue(self.worker.step(discord_only=True))
                self.assertEqual(self.job()['state'], 'failed' if attempt == 2 else 'scheduled')
                self.db.now = self.job()['nextAt'] + 1
        self.assertEqual(self.job()[policy.KEY]['deadLetter']['attempts'], 3)
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire.calls))
        self.assert_frozen()

    def test_expired_linked_identity_can_refresh_before_strict_lease_renewal(self):
        fresh = False
        grant, prepare = self.grants.discord_grant_for_worker, self.social.prepare_discord_dispatch
        def expired_until_refresh(*args, **kwargs):
            if kwargs.get('cur') is not None and not fresh:
                raise AlphaError('The linked identity expired.', 409)
            return grant(*args, **kwargs)
        def refresh_then_prepare(manifest):
            nonlocal fresh
            fresh = True
            return prepare(manifest)
        with patch.object(self.grants, 'discord_grant_for_worker', side_effect=expired_until_refresh), \
                patch.object(self.social, 'prepare_discord_dispatch', side_effect=refresh_then_prepare) as preflight:
            self.assertTrue(self.worker.step(discord_only=True))
        self.assertTrue(fresh)
        self.assertEqual(preflight.call_count, 1)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.wire.calls), 1)
        self.assertNotEqual(self.job()['state'], 'held')
        self.assert_frozen()

    def test_revocation_during_identity_preflight_blocks_before_rate_reservation(self):
        prepare = self.social.prepare_discord_dispatch
        def revoked_after_read(manifest):
            prepared = prepare(manifest)
            self.grants.revoked = True
            return prepared
        with patch.object(self.social, 'prepare_discord_dispatch', side_effect=revoked_after_read), \
                patch.object(self.social, 'reserve_discord_send') as reserve:
            self.assertTrue(self.worker.step(discord_only=True))
        reserve.assert_not_called()
        self.assertEqual(self.job()['state'], 'held')
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire.calls))
        self.assert_frozen()

    def test_permanent_preflight_failure_holds_instead_of_retry(self):
        with patch.object(self.social, 'prepare_discord_dispatch', side_effect=AlphaError('forbidden', 403)):
            self.assertTrue(self.worker.step(discord_only=True))
        self.assertEqual(self.job()['state'], 'held')
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertFalse(self.job().get('discordDispatchIntents'))
        selected = self.original['manifest']['destinationId']
        destination = next(d for d in self.db.state['phase2']['channels'][0]['discordDestinations'] if d['id'] == selected)
        self.assertEqual(destination['status'], 'verification_required')

    def test_commit_delay_losing_sealed_lease_stops_before_post(self):
        authorize = self.worker.authorize_dispatch
        def slow_commit(claimed):
            allowed = authorize(claimed)
            if allowed:
                self.db.now = self.job()['leaseUntil'] + 1
            return allowed
        with patch.object(self.worker, 'authorize_dispatch', side_effect=slow_commit):
            self.assertTrue(self.worker.step(discord_only=True))
        self.assertEqual(len(self.job()['discordDispatchIntents']), 1)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire.calls))
        self.assert_frozen()

    def test_shutdown_releases_only_owned_unsent_and_makes_no_new_claim(self):
        claimed = self.claim()
        self.worker.request_shutdown()
        before = len(self.db.queries)
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(len(self.db.queries), before)
        self.assertFalse(self.worker.renew_discord_lease(claimed))
        self.assertTrue(self.worker.release_discord_unsent(claimed))
        self.assertEqual(self.job()['state'], 'scheduled')
        self.assertEqual(policy.attempt_count(self.job()), 0)
        self.assert_frozen()

    def test_shutdown_preserves_sealed_intent_and_late_receipt_cannot_steal(self):
        claimed = self.claim(); self.assertTrue(self.seal(claimed))
        self.worker.request_shutdown()
        self.assertFalse(self.worker.release_discord_unsent(claimed))
        old_until = self.job()['leaseUntil']
        self.db.now = old_until + 1
        next_worker = PostgresWorker(self.db.connection, self.social, worker_id='new-owner', discord_workers=True)
        recovered = next_worker.claim(discord_only=True)
        self.assertIsNotNone(recovered)
        newer_lease = self.job()['leaseId']
        receipt = {'state': 'provider_accepted', 'reference': FIRST + '/4444444',
                   'confirmed': 'Synthetic late response', 'discordDeliveryEvidence': 'accepted'}
        self.assertFalse(self.worker.complete(claimed, receipt))
        self.assertEqual(self.job()['leaseOwner'], 'new-owner')
        self.assertEqual(self.job()['leaseId'], newer_lease)
        self.assertTrue(self.job()['discordReceipts'][-1]['late'])
        self.assert_frozen()

    def test_legacy_minimal_completion_cannot_complete_a_discord_job(self):
        claimed=self.claim();self.assertTrue(self.seal(claimed))
        before=copy.deepcopy(self.db.state)
        minimal={**claimed,'job':{'id':claimed['job']['id'],'leaseId':claimed['job']['leaseId']}}
        result={'state':'verified','reference':FIRST+'/4444444','confirmed':'Untrusted minimal completion',
                'verification':'provider_lookup','discordDeliveryEvidence':'accepted'}
        self.assertFalse(self.worker.complete(minimal,result))
        self.assertEqual(self.db.state,before)
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assert_frozen()

    def test_removed_cursor_blocks_parallel_lane_without_schema_fallback(self):
        self.db.cursor_ready = False
        self.assertIsNone(self.worker.claim(discord_only=True))
        self.assertEqual(self.worker.capacity_intervention['code'], 'discord_worker_cursor_schema')
        self.assertFalse(self.job().get('leaseOwner'))

    def test_default_disabled_transport_holds_managed_discord_without_aborting_worker(self):
        disabled = PostgresWorker(self.db.connection, worker_id='disabled-owner', discord_workers=True)
        self.assertTrue(disabled.step(discord_only=True))
        self.assertEqual(self.job()['state'], 'held')
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(self.job().get('leaseOwner'))
        self.assert_frozen()

    def test_aggregate_report_is_sampled_and_contains_no_content_or_grants(self):
        self.claim()
        report = self.worker.discord_report()
        self.assertEqual(report['queue']['status'], 'observed_sample')
        self.assertEqual(report['queue']['depth'], 1)
        self.assertTrue(report['queue']['sampled'])
        self.assertNotIn('Synthetic approval test', json.dumps(report))
        self.assertNotIn('accessToken', json.dumps(report))
        self.assertNotIn(WORKSPACE, json.dumps(report))


    def enable_rate(self):
        from test_discord_rate_limits import MemoryLedger,synthetic_policy
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget,route_identity,RequestIdentity
        from urllib.parse import urlsplit
        import hashlib
        self.ledger=MemoryLedger(now=self.db.now,workspace=self.db)
        provider=self.social.providers['discord']
        self.social.prepare_discord_dispatch(self.job()['manifest'])
        paths={urlsplit(url).path.removeprefix('/api/v10') for method,url,_ in self.wire.calls if method=='GET'}
        coordinator=SharedPostgresBudget(self.ledger.connection,APP,policy=synthetic_policy(self.db.now))
        identity=RequestIdentity.make(APP,'bot',provider.bot_token)
        learned=set()
        for path in sorted(paths):
            template,major=route_identity('GET',path)
            if (template,major) in learned:continue
            learned.add((template,major))
            bucket='fixture-'+hashlib.sha256(template.encode()).hexdigest()[:16]
            permit=coordinator.reserve('GET',path,identity=identity)
            coordinator.consume(permit,'GET',path)
            coordinator.observe(permit,{'status':200,'headers':{'X-RateLimit-Bucket':bucket,'X-RateLimit-Limit':'100',
                'X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}})
        for row in self.ledger.states.values():
            if row['kind']=='route':row['reset']=self.db.now-1
        original_wire=provider.transport
        def rated_wire(method,url,**kwargs):
            response=original_wire(method,url,**kwargs)
            template,_major=route_identity(method,urlsplit(url).path.removeprefix('/api/v10'))
            return {**response,'headers':{'X-RateLimit-Bucket':'fixture-'+hashlib.sha256(template.encode()).hexdigest()[:16],
                'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}}
        provider.transport=rated_wire;provider.rate_v1_enabled=True
        provider.rate_limiter=coordinator
        self.wire.calls.clear()
        self.worker.connection_factory=self.ledger.connection
        return provider

    def prepare_rate(self,claimed):
        claimed['discordPrepared']=self.social.prepare_discord_dispatch(claimed['job']['manifest'])
        claimed['discordPrepared']['ratePermit']=self.social.reserve_discord_send(
            claimed['job']['manifest'],job=claimed['job'],workspace_id=claimed['workspaceId'],worker_id=self.worker.worker_id)

    def test_rate_wait_preserves_long_deadline_and_holds_expired_approval(self):
        claimed=self.claim()
        self.assertTrue(self.worker.release_discord_unsent(claimed,reason='rate_delayed',retry_after_seconds=172800.25))
        self.assertGreaterEqual(self.job()['nextAt'],self.db.now+172800.25)
        self.assertEqual(self.job()['state'],'held')
        self.assertEqual(policy.attempt_count(self.job()),0)
        self.assertEqual(self.job()[policy.KEY]['unsentFailures'],0)
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assert_frozen()

    def test_rate_read_rejection_is_bounded_without_spending_publish_attempts(self):
        self.social.discord_read_attempt_limit=lambda:2
        for index in range(2):
            claimed=self.claim()
            self.assertTrue(self.worker.release_discord_unsent(claimed,reason='rate_delayed',retry_after_seconds=1.25,rate_cause='provider_429'))
            if index==0:
                self.db.now=self.job()['nextAt']+.01
        self.assertEqual(self.job()['state'],'held')
        self.assertEqual(policy.attempt_count(self.job()),0)
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assert_frozen()

    def test_permit_is_sealed_with_intent_and_consumed_before_one_post(self):
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        permit=claimed['discordPrepared']['ratePermit']
        self.assertTrue(self.worker.authorize_dispatch(claimed))
        self.assertEqual(self.ledger.admissions[permit.id]['state'],'sealed')
        self.assertEqual(self.job()['discordDispatchIntents'][0]['rateAdmissionId'],permit.id)
        result=self.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
        self.assertEqual(result['state'],'provider_accepted')
        self.assertEqual(self.ledger.admissions[permit.id]['state'],'observed')
        self.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
        self.assertEqual(sum(method=='POST' for method,_,_ in self.wire.calls),1)
        self.assert_frozen()

    def test_cross_tenant_and_wrong_lease_permits_cannot_seal(self):
        from dataclasses import replace
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        permit=claimed['discordPrepared']['ratePermit']
        claimed['discordPrepared']['ratePermit']=replace(permit,binding_hash='f'*64)
        self.assertFalse(self.worker.authorize_dispatch(claimed))
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assert_frozen()

    def test_revocation_after_seal_blocks_consume_and_keeps_intent(self):
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        self.assertTrue(self.worker.authorize_dispatch(claimed));self.grants.revoked=True
        result=self.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
        self.assertEqual(result['state'],'uncertain')
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assertEqual(len(self.job()['discordDispatchIntents']),1)
        self.assert_frozen()

    def test_postseal_destination_membership_and_lease_loss_keep_intent(self):
        from postriff_phase2.permissions import Membership
        self.assertTrue(Membership.from_row('owner',can_publish=False).allows('approve'))
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        self.assertTrue(self.worker.authorize_dispatch(claimed))
        original_state=copy.deepcopy(self.db.state)
        for change in ('destination','membership','lease'):
            with self.subTest(change=change):
                self.db.state=copy.deepcopy(original_state)
                self.db.member=('owner',True)
                if change=='destination':self.db.state['phase2']['channels'][0]['discordDestinations'][0]['status']='revoked'
                elif change=='membership':self.db.member=None  # SQL active-member filter returns no row
                else:self.job()['leaseUntil']=self.db.now-1
                result=self.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
                self.assertEqual(result['state'],'uncertain')
                self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
                self.assertEqual(len(self.job()['discordDispatchIntents']),1)
                self.assert_frozen()

    def test_expiry_after_seal_blocks_consume_and_never_reposts(self):
        from postriff_phase2.discord.rate_limits import UnconsumedPublishPermit
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        self.assertTrue(self.worker.authorize_dispatch(claimed))
        self.db.now=claimed['discordPrepared']['ratePermit'].expires_at+.01
        with self.assertRaises(UnconsumedPublishPermit) as caught:
            self.social.submit_discord_authorized(claimed['job']['manifest'],claimed['discordDispatch'])
        self.assertEqual(caught.exception.permit_id,claimed['discordPrepared']['ratePermit'].id)
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assertEqual(len(self.job()['discordDispatchIntents']),1)
        self.assert_frozen()

    def test_expired_permit_before_intent_waits_with_the_same_frozen_approval(self):
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        self.db.now=claimed['discordPrepared']['ratePermit'].expires_at+.01
        self.assertFalse(self.worker.authorize_dispatch(claimed))
        self.assertEqual(self.job()['state'],'scheduled')
        self.assertEqual(self.job()['discordWorker']['stage'],'released')
        self.assertEqual(self.job()['discordWorker']['ratePermitRetries'],1)
        self.assertFalse(self.job().get('discordDispatchIntents'))
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assert_frozen()

    def test_consumed_permit_is_never_a_preintent_expiry_retry(self):
        self.enable_rate();claimed=self.claim();self.prepare_rate(claimed)
        self.ledger.admissions[claimed['discordPrepared']['ratePermit'].id]['state']='sent'
        self.assertFalse(self.worker.authorize_dispatch(claimed))
        self.assertEqual(self.job()['state'],'held')
        self.assertEqual(self.job()['discordWorker'].get('ratePermitRetries',0),0)
        self.assertFalse(any(method=='POST' for method,_,_ in self.wire.calls))
        self.assert_frozen()

if __name__ == '__main__':
    unittest.main()
