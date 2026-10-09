"""Synthetic worker control regression: no Google, production DB, or real PASS."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_worker import PostgresWorker, configured_worker_limits
from postriff_phase2.store import Phase2Store


NOW = 1_800_000_000


class WorkerDatabase:
    def __init__(self, channels=2, capacity_ready=True):
        self.depth, self.result, self.rowcount = 0, None, 1
        self.capacity_ready, self.tenant_dispatches = capacity_ready, 0
        self.member_role = 'owner'
        self.youtube_generation = 'synthetic-consent-generation'
        self.state = {'phase2': {'channels': [], 'reviews': [], 'jobs': []}}
        for index in range(channels):
            channel = {'id': f'connection-{index}', 'platform': 'YouTube', 'configured': True,
                       'identityVerified': True, 'capabilityVerified': True, 'revoked': False,
                       'expiresAt': NOW - 1, 'verifiedAt': NOW - 3601, 'scopes': ['youtube.upload'],
                       'providerAccountId': f'UC-synthetic-{index}', 'capabilityVersion': 1}
            manifest = {'workspaceId': 'workspace', 'channelId': channel['id'], 'platform': 'YouTube', 'actor': 'owner',
                        'providerAccountId': channel['providerAccountId'], 'expiresAt': NOW + 3600,
                        'idempotencyKey': f'synthetic-{index}',
                        'capability': {'scopes': list(channel['scopes']), 'version': 1}}
            self.state['phase2']['channels'].append(channel)
            self.state['phase2']['jobs'].append({'id': f'job-{index}', 'manifest': manifest,
                'approvedBy': 'owner', 'approvedAt': NOW, 'approvalDigest': digest(manifest), 'state': 'approved',
                'attempts': [], 'events': []})

    @contextmanager
    def connection_factory(self):
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT pg_try_advisory_xact_lock'):
            self.result = (True,)
        elif sql.startswith('SELECT to_regclass'):
            self.result = ('pr_worker_tenants' if self.capacity_ready else None,)
        elif sql.startswith('SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces'):
            assert ('LEFT JOIN public.pr_worker_tenants' in sql) == self.capacity_ready
            self.result = [('workspace', 1, copy.deepcopy(self.state))]
        elif sql.startswith('INSERT INTO public.pr_worker_tenants'):
            assert self.capacity_ready
            self.tenant_dispatches += 1
        elif sql.startswith('SELECT m.role,m.can_publish'):
            self.result = (self.member_role, True)
        elif sql.startswith('SELECT authorization_generation::text FROM public.pr_encrypted_credentials'):
            assert params[0] == 'workspace'
            channel = next((item for item in self.state['phase2']['channels'] if item['id'] == params[1]), None)
            self.result = (self.youtube_generation,) if channel and not channel.get('revoked') else None
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.result = (copy.deepcopy(self.state),)
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state = json.loads(params[0])
            self.rowcount = 1
        else:
            raise AssertionError(f'Unexpected synthetic SQL: {sql}')

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


def worker_for(channels=2):
    db, now, order = WorkerDatabase(channels), [NOW], []
    engine = Phase2Store.__new__(Phase2Store)
    engine.clock, engine.hosted_entitlements = lambda: now[0], True

    # Full manifest/source/media-current contracts remain in the existing suite.
    # Here current() retains the real worker's identity/scope/version dependency.
    def current(state, manifest):
        channel = next(c for c in state['phase2']['channels'] if c['id'] == manifest['channelId'])
        return (manifest['providerAccountId'] == channel['providerAccountId']
                and manifest['capability']['scopes'] == channel['scopes']
                and manifest['capability']['version'] == channel['capabilityVersion'])

    engine.current = current
    worker = PostgresWorker.__new__(PostgresWorker)
    worker.connection_factory, worker.clock, worker.worker_id = db.connection_factory, engine.clock, 'synthetic-worker'
    worker.commands, worker.complete = SimpleNamespace(engine=engine), Mock()

    def reverify(workspace, connection):
        assert db.depth == 0, 'Provider grant/identity verification must happen outside DB locks.'
        assert workspace == 'workspace'
        order.append(('verify', connection))
        channel = next(c for c in db.state['phase2']['channels'] if c['id'] == connection)
        channel.update(expiresAt=now[0] + 3600, verifiedAt=now[0])
        engine.invalidate(db.state)
        return {'state': 'read_verified', 'ready': True}

    oauth = SimpleNamespace(reverify_for_worker=Mock(side_effect=reverify))
    worker.social = SimpleNamespace(youtube=SimpleNamespace(oauth=oauth),
        submit=Mock(side_effect=lambda manifest: order.append(('submit', manifest['channelId']))),
        reconcile=Mock(side_effect=lambda manifest, job: order.append(('reconcile', manifest['channelId']))))
    return worker, db, now, order, reverify


class YouTubeWorkerRefreshTests(unittest.TestCase):
    def test_server_worker_budget_tuning_preserves_defaults_and_hard_bounds(self):
        self.assertEqual(configured_worker_limits({}), (10, 20))
        self.assertEqual(configured_worker_limits({'POSTRIFF_WORKER_MAX_JOBS': '25', 'POSTRIFF_WORKER_MAX_SECONDS': '45'}), (25, 45))
        for values in ({'POSTRIFF_WORKER_MAX_JOBS': '26'}, {'POSTRIFF_WORKER_MAX_JOBS': '0'},
                       {'POSTRIFF_WORKER_MAX_SECONDS': '46'}, {'POSTRIFF_WORKER_MAX_SECONDS': 'nan'},
                       {'POSTRIFF_WORKER_MAX_JOBS': 'bad'}):
            with self.subTest(values=values), self.assertRaises(AlphaError) as caught:
                configured_worker_limits(values)
            self.assertEqual(caught.exception.code, 'worker_budget_configuration')

    @patch('postriff_phase2.billing.require_publishing')
    def test_missing_capacity_migration_defers_youtube_but_claims_other_platform(self, _billing):
        worker, db, now, _, _ = worker_for(2)
        db.capacity_ready = False
        youtube, other = db.state['phase2']['jobs']
        # Provider readback is enough to cover the unaffected platform without
        # replacing the real billing/approval coverage in its existing suite.
        other['manifest']['platform'], other['state'] = 'LinkedIn', 'processing'
        self.assertTrue(worker.step())
        self.assertEqual((youtube := db.state['phase2']['jobs'][0])['state'], 'approved')
        self.assertEqual((youtube['attempts'], youtube['nextAt']), ([], NOW + 60))
        self.assertEqual(youtube['capacityIntervention']['code'], 'youtube_capacity_schema')
        self.assertNotIn('leaseId', youtube)
        self.assertEqual(db.tenant_dispatches, 0)
        worker.social.youtube.oauth.reverify_for_worker.assert_not_called()
        worker.social.submit.assert_not_called()
        self.assertEqual(worker.social.reconcile.call_args.args[0]['platform'], 'LinkedIn')
        # Applying the schema resumes the original operation, not a replacement.
        db.capacity_ready, now[0] = True, NOW + 61
        self.assertTrue(worker.step())
        self.assertNotIn('capacityIntervention', db.state['phase2']['jobs'][0])
        self.assertEqual(len(db.state['phase2']['jobs'][0]['attempts']), 1)
        worker.social.submit.assert_called_once()

    @patch('postriff_phase2.billing.require_publishing')
    def test_missing_migration_is_visible_without_claiming_any_youtube_attempt(self, _billing):
        worker, db, _, _, _ = worker_for(1)
        db.capacity_ready = False
        self.assertFalse(worker.step())
        self.assertEqual(worker.capacity_intervention['youtubeDispatch'], 'paused')
        self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
        worker.social.youtube.oauth.reverify_for_worker.assert_not_called()
        worker.social.submit.assert_not_called()
        worker.social.reconcile.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    @patch('postriff_phase2.hosted_worker.assert_job_authority')
    def test_autopilot_pause_before_claim_and_during_refresh_stops_forward_work(self, authority, _billing):
        for during_refresh in (False, True):
            with self.subTest(during_refresh=during_refresh):
                worker, db, _, _, reverify = worker_for(1)
                paused = AlphaError('Synthetic paused Autopilot.', 409, code='youtube_agent_authority_required')
                authority.side_effect = None if during_refresh else paused
                if during_refresh:
                    def changed(workspace, connection):
                        result = reverify(workspace, connection)
                        authority.side_effect = paused
                        return result
                    worker.social.youtube.oauth.reverify_for_worker.side_effect = changed
                worker.step()
                self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
                self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()

    @patch('postriff_phase2.hosted_worker.assert_job_authority', side_effect=AlphaError('Synthetic paused Autopilot.', 409))
    def test_accepted_native_schedule_readback_survives_paused_autopilot(self, authority):
        for stage, state in (('native_scheduled', 'processing'), ('native_schedule_reconciling', 'uncertain')):
            with self.subTest(stage=stage):
                worker, db, _, order, _ = worker_for(1)
                db.state['phase2']['jobs'][0].update(state=state, progress={'stage': stage},
                                                     youtubeAgent={'policyId': 'synthetic-paused-policy'})
                self.assertTrue(worker.step())
                self.assertEqual(order, [('reconcile', 'connection-0')])
                worker.social.submit.assert_not_called()
                worker.social.youtube.oauth.reverify_for_worker.assert_not_called()
        authority.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    @patch('postriff_phase2.hosted_worker.assert_job_authority')
    def test_queued_autopilot_owner_demotion_blocks_claim_and_forward_write(self, _authority, _billing):
        # An approver/editor may retain manual publishing authority after losing
        # ownership. That never preserves a former owner's standing authority.
        for role in ('approver', 'editor'):
            for during_refresh in (False, True):
                with self.subTest(role=role, during_refresh=during_refresh):
                    worker, db, _, _, reverify = worker_for(1)
                    db.state['phase2']['jobs'][0]['youtubeAgent'] = {'policyId': 'synthetic-owner-policy'}
                    if during_refresh:
                        def demoted(workspace, connection):
                            result = reverify(workspace, connection)
                            db.member_role = role
                            return result
                        worker.social.youtube.oauth.reverify_for_worker.side_effect = demoted
                    else:
                        db.member_role = role
                    worker.step()
                    self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
                    self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                    worker.social.submit.assert_not_called()
                    worker.social.reconcile.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_two_stale_connections_refresh_independently_before_forward_bytes(self, _billing):
        worker, db, _, order, _ = worker_for()
        worker.commands.engine.invalidate(db.state)
        self.assertEqual([j['state'] for j in db.state['phase2']['jobs']], ['approved', 'approved'])
        self.assertEqual(worker.commands.engine.channel_state(db.state['phase2']['channels'][1]), 'Reconnect')
        self.assertTrue(worker.step())
        self.assertEqual(db.state['phase2']['jobs'][1]['state'], 'approved')
        self.assertEqual(worker.commands.engine.channel_state(db.state['phase2']['channels'][1]), 'Reconnect')
        self.assertTrue(worker.step())
        self.assertEqual(order, [('verify', 'connection-0'), ('submit', 'connection-0'),
                                 ('verify', 'connection-1'), ('submit', 'connection-1')])
        self.assertEqual([len(j['attempts']) for j in db.state['phase2']['jobs']], [1, 1])

    @patch('postriff_phase2.billing.require_publishing')
    def test_unavailable_or_missing_refresh_retries_without_attempt_or_write(self, _billing):
        for reason in ('temporary provider failure', 'missing refresh credential'):
            with self.subTest(reason=reason):
                worker, db, now, _, reverify = worker_for(1)
                worker.social.youtube.oauth.reverify_for_worker.side_effect = lambda *_: {'state': 'verification_unavailable', 'ready': False}
                self.assertTrue(worker.step())
                job = db.state['phase2']['jobs'][0]
                self.assertEqual((job['state'], job['attempts'], job['leaseUntil']), ('approved', [], 0))
                self.assertEqual(job['nextAt'], NOW + 60)
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()
                worker.social.youtube.oauth.reverify_for_worker.side_effect = reverify
                now[0] += 61
                self.assertTrue(worker.step())
                self.assertEqual(len(db.state['phase2']['jobs'][0]['attempts']), 1)
                worker.social.submit.assert_called_once()

    @patch('postriff_phase2.billing.require_publishing')
    def test_revoked_grant_identity_scope_digest_and_approval_changes_block(self, _billing):
        for failure in ('revoked', 'identity', 'scopes', 'digest', 'approval_expired', 'account_block'):
            with self.subTest(failure=failure):
                worker, db, now, _, reverify = worker_for(1)

                def changed(workspace, connection):
                    if failure == 'revoked':
                        raise AlphaError('Synthetic revoked credential', 404)
                    result = reverify(workspace, connection)
                    channel, job = db.state['phase2']['channels'][0], db.state['phase2']['jobs'][0]
                    if failure == 'identity':
                        channel.update(providerAccountId='UC-another-channel', identityVerified=False, revoked=True)
                    elif failure == 'scopes':
                        channel.update(scopes=[], capabilityVerified=False)
                    elif failure == 'account_block':
                        db.state['accountBlock'] = {'reason': 'Synthetic founder block after claim'}
                    elif failure == 'digest':
                        job['approvalDigest'] = 'changed-after-claim'
                    else:
                        now[0] = job['manifest']['expiresAt'] + 1
                        # Keep the worker fence live so this fails on approval expiry.
                        job['leaseUntil'] = now[0] + 45
                        channel.update(expiresAt=now[0] + 3600, verifiedAt=now[0])
                    return result  # Even successful refresh cannot override current authority.

                worker.social.youtube.oauth.reverify_for_worker.side_effect = changed
                self.assertTrue(worker.step())
                self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
                self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_reconciliation_and_existing_native_schedule_cancellation_are_reverified(self, _billing):
        for stage, canceled in (('uploading', False), ('uploading', True), ('native_scheduled', True)):
            with self.subTest(stage=stage, canceled=canceled):
                worker, db, _, order, _ = worker_for(1)
                db.state['phase2']['jobs'][0].update(state='processing', progress={'stage': stage}, cancelRequested=canceled)
                self.assertTrue(worker.step())
                self.assertEqual(order, [('verify', 'connection-0'), ('reconcile', 'connection-0')])
                self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                self.assertEqual(worker.social.reconcile.call_args.args[1].get('cancelRequested'), canceled)
                worker.social.submit.assert_not_called()

        worker, db, _, _, _ = worker_for(1)
        db.state['phase2']['jobs'][0].update(state='processing', progress={'stage': 'native_scheduled'}, cancelRequested=True)
        worker.social.youtube.oauth.reverify_for_worker.side_effect = AlphaError('Synthetic revoked credential', 404)
        self.assertTrue(worker.step())
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')  # Cancellation is not falsely confirmed.
        worker.social.reconcile.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_new_cancellation_or_changed_fence_during_refresh_stops_forward_work(self, _billing):
        for change in ('cancel', 'lease'):
            with self.subTest(change=change):
                worker, db, now, _, reverify = worker_for(1)
                db.state['phase2']['jobs'][0].update(state='processing', progress={'stage': 'uploading'})

                def changed(workspace, connection):
                    result = reverify(workspace, connection)
                    job = db.state['phase2']['jobs'][0]
                    job.update({'cancelRequested': True} if change == 'cancel' else {'leaseId': 'another-fence'})
                    return result

                worker.social.youtube.oauth.reverify_for_worker.side_effect = changed
                self.assertTrue(worker.step())
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()
                self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                job = db.state['phase2']['jobs'][0]
                if change == 'cancel':
                    self.assertEqual((job['state'], job['cancelRequested'], job['leaseUntil']), ('processing', True, 0))
                    self.assertEqual(job['nextAt'], NOW + 1)
                    now[0] += 2
                    self.assertTrue(worker.step())
                    worker.social.reconcile.assert_called_once()
                    self.assertTrue(worker.social.reconcile.call_args.args[1]['cancelRequested'])
                    worker.social.submit.assert_not_called()
                else:
                    self.assertEqual(job['leaseId'], 'another-fence')

    @patch('postriff_phase2.billing.require_publishing')
    def test_disconnect_hold_or_terminal_state_survives_reconnect_during_refresh(self, _billing):
        for stopped in ('held', 'canceled', 'failed', 'verified'):
            with self.subTest(stopped=stopped):
                worker, db, _, _, reverify = worker_for(1)

                def disconnected_then_reconnected(workspace, connection):
                    # The fresh identity/scopes can match exactly after reconnect.
                    # The original operation's explicit hold still ends its lease.
                    result = reverify(workspace, connection)
                    db.state['phase2']['jobs'][0]['state'] = stopped
                    return result

                worker.social.youtube.oauth.reverify_for_worker.side_effect = disconnected_then_reconnected
                self.assertTrue(worker.step())
                job = db.state['phase2']['jobs'][0]
                self.assertEqual((job['state'], job['attempts'], job['leaseUntil']), (stopped, [], 0))
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()

    def test_age_deferral_never_applies_to_revoked_unverified_or_local_channels(self):
        worker, db, _, _, _ = worker_for(1)
        engine, channel = worker.commands.engine, db.state['phase2']['channels'][0]
        self.assertTrue(engine.channel_reverification_due(channel))
        for mutation in ({'revoked': True}, {'identityVerified': False}, {'capabilityVerified': False},
                         {'configured': False}, {'scopes': []}, {'platform': 'Instagram'}):
            with self.subTest(mutation=mutation):
                self.assertFalse(engine.channel_reverification_due(channel | mutation))
        engine.hosted_entitlements = False
        self.assertFalse(engine.channel_reverification_due(channel))


if __name__ == '__main__':
    unittest.main()
