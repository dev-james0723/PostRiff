"""Bounded pool selection and signed page binding; explicit synthetic data."""
import copy
import os
import unittest
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends import contracts, exposure_events, opportunities, opportunity_pool
import test_trend_service as fixture
import test_trend_integration as integration


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = fixture.make_service()
        self.repo.fetchall = lambda: []
        self.store.rows['opportunity', fixture.OID]['payload']['executable_ready'] = True

    def read(self, surface='weekly', **fields):
        return self.svc.list(fixture.WID, 'session', {'pool': surface, **fields}, kind='opportunity')

    def test_weekly_preserves_unqualified_interpretation_home_abstains(self):
        result = self.read()
        fixture.assert_schema(self, 'opportunities_response', result)
        self.assertEqual([p['id'] for p in result['data']], [fixture.OID])
        self.assertEqual(self.read('home')['data'], [])
        token = self.svc._decode(result['exposure_token'])
        self.assertEqual(token['candidates_digest'], contracts.digest(exposure_events.candidate_ids(result['data'])))
        self.assertEqual(self.repo.queries[0].lstrip()[:6], 'SELECT')
        self.assertFalse(any(q.startswith(('UPDATE', 'INSERT')) for q in self.repo.queries))

    def test_current_revocation_unready_and_concern_are_not_selected(self):
        p = self.store.rows['opportunity', fixture.OID]['payload']
        p['executable_ready'] = False
        self.assertEqual(self.read()['data'], [])
        p['executable_ready'] = True
        p['dimensions']['risk']['assessment'] = 'concern'
        self.assertEqual(self.read()['data'], [])
        p['dimensions']['risk']['assessment'] = 'unknown'
        self.store.rows['receipt', fixture.RID]['validity'] = 'revoked'
        self.assertEqual(self.read()['data'], [])

    def test_home_requires_current_high_calibration_not_just_qualified_flag(self):
        row = self.store.rows['opportunity', fixture.OID]
        row['payload']['qualified'] = True
        row['payload']['dimensions']['confidence']['assessment'] = 'supported'
        p, trend = self.svc._opportunity_read(self.store, self.repo, fixture.WID, fixture.ACTOR, row, self.repo.state, fixture.NOW)
        self.assertFalse(opportunity_pool.eligible(row, p, trend, self.repo.state, fixture.NOW, 'home'))
        trend['inferred'].update(confidence='high', calibration_state='qualified')
        self.assertTrue(opportunity_pool.eligible(row, p, trend, self.repo.state, fixture.NOW, 'home'))

    def test_existing_dismiss_snooze_and_recent_exposure_cooldowns(self):
        self.repo.state.setdefault('raffi', {})['suggestions'] = [{'kind':'trend_opportunity',
            'evidence':[{'id':fixture.OID}], 'status':'dismissed', 'dismissedAt':fixture.NOW-10}]
        self.assertEqual(self.read()['data'], [])
        self.repo.state['raffi']['suggestions'][0].update(status='snoozed', snoozedUntil=fixture.NOW+60)
        self.assertEqual(self.read()['data'], [])
        self.repo.state['raffi']['suggestions'] = []
        self.repo.fetchall = lambda: [(fixture.OID,)]
        self.assertEqual(self.read()['data'], [])
        self.repo.fetchall = lambda: []
        self.store.rows['exposure', fixture.EID] = fixture.fixture_row('exposure', fixture.EID,
            {'opportunity_id':fixture.OID, 'recorded_at':opportunities.iso(fixture.NOW-5)})
        self.assertEqual(self.read()['data'], [])

    def test_bounded_selection_keeps_order_and_signs_only_returned_three(self):
        row = self.store.rows['opportunity', fixture.OID]
        for n in range(10, 35):
            oid = '00000000-0000-4000-8000-' + str(n).zfill(12)
            self.store.rows['opportunity', oid] = copy.deepcopy({**row, 'object_id':oid})
        result = self.read()
        self.assertEqual(len(result['data']), 3)
        self.assertEqual([p['id'] for p in result['data']], sorted([p['id'] for p in result['data']], reverse=True))
        self.assertIsNone(result['next_cursor'])
        self.assertEqual(self.svc._decode(result['exposure_token'])['candidates_digest'],
                         contracts.digest(exposure_events.candidate_ids(result['data'])))
        for call in self.store.calls:
            if call[0] == 'list': self.assertNotIn('pool', call[2])

    def test_invalid_pool_pagination_limit_and_trend_selector_rejected(self):
        for query in ({'pool':'all'}, {'pool':'home','cursor':'x'}, {'pool':'weekly','limit':4}):
            with self.assertRaises(AlphaError): self.svc.list(fixture.WID,'session',query,kind='opportunity')
        with self.assertRaises(AlphaError): self.svc.list(fixture.WID,'session',{'pool':'weekly'})

    def test_incomplete_exposure_history_abstains(self):
        original = self.store.list_projections
        def paged(*args, **kwargs):
            value = original(*args, **kwargs)
            if kwargs.get('kind') == 'exposure': value['next_key'] = ['more']
            return value
        with patch.object(self.store, 'list_projections', side_effect=paged):
            result = self.read()
        self.assertEqual(result['data'], [])
        self.assertIsNone(result['exposure_token'])
        self.assertTrue(any('withheld' in x for x in result['limitations']))


@unittest.skipUnless(os.environ.get('TREND_SERVICE_TEST_DSN'), 'explicit disposable service PostgreSQL required')
class PoolPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        integration.DurableServiceTests.setUpClass.__func__(cls)

    def test_real_current_pool_exposure_suppression_and_dismissal(self):
        import uuid
        query = {'pool':'weekly','limit':'3'}
        self.assertEqual(self.svc.list(self.wid,'fixture-session',query,kind='opportunity')['data'], [])
        with self.connect() as db:
            db.execute("UPDATE pr_trend_projections SET payload=payload||'{\"executable_ready\":true}'::jsonb WHERE scope_key=%s AND object_id=%s AND kind='opportunity'", ('workspace:'+self.wid,self.oid))
            self.assertIsNone(db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0])
        result = self.svc.list(self.wid,'fixture-session',query,kind='opportunity')
        fixture.assert_schema(self,'opportunities_response',result)
        self.assertEqual([p['id'] for p in result['data']], [self.oid])
        op = result['data'][0]
        self.assertEqual(self.svc.list(self.wid,'fixture-session',{'pool':'home'},kind='opportunity')['data'], [])
        body = {'event_id':str(uuid.uuid4()),'exposure_token':result['exposure_token'],
            'opportunity_id':op['id'],'opportunity_revision':op['revision'],'trust_receipt_id':op['trust_receipt_id'],
            'context_digest':op['context_digest'],'eligible_candidates':exposure_events.candidate_ids(result['data'])}
        self.svc.exposure(self.wid,'fixture-session',body)
        self.assertEqual(self.svc.list(self.wid,'fixture-session',query,kind='opportunity')['data'], [])
        # Normal Radar remains available: the pool does not delete the opportunity.
        self.assertEqual(len(self.svc.list(self.wid,'fixture-session',kind='opportunity')['data']),1)
        self.svc.dismiss(self.wid,'fixture-session',self.oid,{'revision':1,'idempotency_key':'pool-dismiss'})
        self.assertEqual(self.svc.list(self.wid,'fixture-session',query,kind='opportunity')['data'], [])


if __name__ == '__main__': unittest.main()
