"""Synthetic scheduled-Pin control contracts; no Pinterest, hosted DB or live publication."""
import copy
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import security_holds
from postriff_phase2.contracts import digest, resolve_time
from postriff_phase2.coworker import flags
from postriff_phase2.hosted_social import HostedSocial
from test_youtube_worker_refresh import NOW, worker_for


def pinterest_worker():
    worker, db, now, _, _ = worker_for(1)
    channel, job = db.state['phase2']['channels'][0], db.state['phase2']['jobs'][0]
    channel.update(platform='Pinterest', providerAccountId='1234567',
                   scopes=['user_accounts:read', 'boards:read', 'pins:read', 'pins:write'])
    job['manifest'].update(platform='Pinterest', providerAccountId='1234567',
                           capability={'scopes': list(channel['scopes']), 'version': 1})
    job['approvalDigest'] = digest(job['manifest'])
    order = []

    def reverify(workspace, connection):
        assert db.depth == 0, 'Pinterest verification must run outside workspace DB locks.'
        assert (workspace, connection) == ('workspace', channel['id'])
        order.append('verify')
        current = db.state['phase2']['channels'][0]
        current.update(expiresAt=now[0] + 30 * 86400, verifiedAt=now[0])
        worker.commands.engine.invalidate(db.state)
        return {'state': 'read_verified', 'ready': True}

    social = HostedSocial.__new__(HostedSocial)
    social.oauth = Mock()
    social.oauth.reverify_for_worker = Mock(side_effect=reverify)
    social.submit = Mock(side_effect=lambda manifest, **kwargs: order.append('submit') or {'state':'provider_accepted'})
    social.reconcile = Mock(side_effect=lambda manifest, job: order.append('reconcile') or {'state':'uncertain'})
    worker.social = social
    return worker, db, now, order, reverify


class PinterestScheduleReverification(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        flags.attach({})
        installed = dict(security_holds._INSTALLED)
        self.addCleanup(security_holds._INSTALLED.update, installed)
        security_holds._INSTALLED.update(readable=False, checked=float('-inf'))

    @patch('postriff_phase2.billing.require_publishing')
    def test_stale_hour_or_expired_access_reverify_before_first_write_attempt(self, _billing):
        for expired in (False, True):
            with self.subTest(expired=expired):
                worker, db, now, order, _ = pinterest_worker()
                channel = db.state['phase2']['channels'][0]
                channel.update(verifiedAt=NOW - 3601, expiresAt=NOW - 1 if expired else NOW + 86400)
                approval = copy.deepcopy(db.state['phase2']['jobs'][0]['manifest'])
                worker.commands.engine.invalidate(db.state)
                self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'approved')
                self.assertTrue(worker.step())
                job = db.state['phase2']['jobs'][0]
                self.assertEqual(order, ['verify', 'submit'])
                self.assertEqual(job['manifest'], approval)
                self.assertEqual(len(job['attempts']), 1)
                self.assertEqual(job['state'], 'submitting')
                self.assertTrue(worker.social.submit.call_args.kwargs['dispatch_context']['leaseId'])

    @patch('postriff_phase2.billing.require_publishing')
    def test_transient_read_releases_lease_without_consuming_write_retry_then_recovers(self, _billing):
        worker, db, now, order, reverify = pinterest_worker()
        worker.social.oauth.reverify_for_worker.side_effect = AlphaError('Synthetic provider unavailable.', 503)
        self.assertTrue(worker.step())
        job = db.state['phase2']['jobs'][0]
        self.assertEqual((job['state'], job['attempts'], job['leaseUntil']), ('approved', [], 0))
        self.assertEqual(job['nextAt'], NOW + 60)
        worker.social.submit.assert_not_called()
        self.assertFalse(worker.step())
        now[0] += 61
        worker.social.oauth.reverify_for_worker.side_effect = reverify
        self.assertTrue(worker.step())
        self.assertEqual(order, ['verify', 'submit'])
        self.assertEqual(len(db.state['phase2']['jobs'][0]['attempts']), 1)

    @patch('postriff_phase2.billing.require_publishing')
    def test_transient_verification_never_extends_manifest_expiry(self, _billing):
        worker, db, now, _, _ = pinterest_worker()
        worker.social.oauth.reverify_for_worker.return_value = {'state':'verification_unavailable'}
        worker.social.oauth.reverify_for_worker.side_effect = None
        self.assertTrue(worker.step())
        now[0] = NOW + 3601
        self.assertFalse(worker.step())
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(worker.social.oauth.reverify_for_worker.call_count, 1)
        worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_scope_or_account_drift_never_releases_approval(self, _billing):
        for outcome in ('scope_changed', 'scope_missing', 'reauthorization_required'):
            with self.subTest(outcome=outcome):
                worker, db, _, _, _ = pinterest_worker()
                worker.social.oauth.reverify_for_worker.side_effect = None
                worker.social.oauth.reverify_for_worker.return_value = {'state':outcome, 'ready':False}
                self.assertTrue(worker.step())
                job = db.state['phase2']['jobs'][0]
                self.assertEqual((job['state'], job['attempts']), ('held', []))
                worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_revoked_credential_stops_without_write_attempt(self, _billing):
        worker, db, _, _, _ = pinterest_worker()
        worker.social.oauth.reverify_for_worker.side_effect = AlphaError('Synthetic revoked credential.', 404)
        self.assertTrue(worker.step())
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
        worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_disconnect_reconnect_cancel_and_lease_takeover_during_read_never_post(self, _billing):
        for change in ('disconnect_reconnect', 'cancel', 'lease', 'membership', 'account', 'approval'):
            with self.subTest(change=change):
                worker, db, _, _, reverify = pinterest_worker()

                def changed(workspace, connection):
                    result = reverify(workspace, connection)
                    job, channel = db.state['phase2']['jobs'][0], db.state['phase2']['channels'][0]
                    if change == 'disconnect_reconnect':
                        # Consent can return the same account after disconnect; this old lease stays canceled.
                        job.update(state='canceled', cancelRequested=True, leaseOwner=None, leaseId=None, leaseUntil=0)
                        channel.update(revoked=False, identityVerified=True, capabilityVerified=True)
                    elif change == 'cancel':
                        job['cancelRequested'] = True
                    elif change == 'lease':
                        job['leaseId'] = 'new-worker-lease'
                    elif change == 'membership':
                        db.member_role = 'viewer'
                    elif change == 'account':
                        channel['providerAccountId'] = '7654321'
                    else:
                        job['approvalDigest'] = 'changed-review'
                    return result

                worker.social.oauth.reverify_for_worker.side_effect = changed
                self.assertTrue(worker.step())
                worker.social.submit.assert_not_called()
                worker.social.reconcile.assert_not_called()
                self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])
                if change == 'lease':
                    self.assertEqual(db.state['phase2']['jobs'][0]['leaseId'], 'new-worker-lease')

    @patch('postriff_phase2.billing.require_publishing')
    def test_existing_pin_outcome_reconciles_without_new_forward_verification_or_write(self, _billing):
        worker, db, _, order, _ = pinterest_worker()
        db.state['phase2']['jobs'][0].update(state='provider_accepted', providerReference='987654321')
        self.assertTrue(worker.step())
        self.assertEqual(order, ['reconcile'])
        worker.social.oauth.reverify_for_worker.assert_not_called()
        worker.social.submit.assert_not_called()
        self.assertEqual(db.state['phase2']['jobs'][0]['attempts'], [])

    def test_age_exception_is_hosted_pin_only_and_cannot_restore_downgraded_authority(self):
        worker, db, _, _, _ = pinterest_worker()
        engine, channel = worker.commands.engine, db.state['phase2']['channels'][0]
        self.assertTrue(engine.pinterest_reverification_due(channel))
        self.assertFalse(engine.channel_reverification_due(channel))  # Composer's YouTube path stays separate.
        for mutation in ({'revoked':True}, {'identityVerified':False}, {'capabilityVerified':False},
                         {'configured':False}, {'scopes':[]}, {'platform':'Instagram'}):
            self.assertFalse(engine.pinterest_reverification_due(channel | mutation))
        engine.hosted_entitlements = False
        self.assertFalse(engine.pinterest_reverification_due(channel))

    def test_selected_zone_dst_gap_and_fold_are_frozen_as_different_utc_instants(self):
        for local, fold in (('2026-03-08T02:30', None), ('2026-11-01T01:30', None)):
            with self.assertRaises(AlphaError):
                resolve_time(local, 'America/New_York', fold, 1_700_000_000)
        first = resolve_time('2026-11-01T01:30', 'America/New_York', 0, 1_700_000_000)
        second = resolve_time('2026-11-01T01:30', 'America/New_York', 1, 1_700_000_000)
        self.assertEqual(second['timestamp'] - first['timestamp'], 3600)
        self.assertEqual((first['timeZone'], second['timeZone']), ('America/New_York', 'America/New_York'))


if __name__ == '__main__':
    unittest.main()
