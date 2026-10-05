"""Real disposable PostgreSQL support surveys, no provider or external notices."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from control import test_founder_support_refunds as baseline
from postriff_alpha.domain import AlphaError
from postriff_phase2 import support, support_surveys
from rafii_control import founder_ops, founder_support, founder_metrics_support, founder_tools
from rafii_control.auth import ControlError
from rafii_control.intelligence import Catalog, QueryService


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class SupportSurveyTests(unittest.TestCase):
    setUp = baseline.SupportRefundPostgresTests.setUp
    tearDown = baseline.SupportRefundPostgresTests.tearDown
    request = baseline.SupportRefundPostgresTests.request

    def create(self, workspace=None):
        return support.customer(self.service, workspace or self.primary, self.user, 'POST', body={
            'requestId': str(uuid.uuid4()), 'category': 'technical', 'message': 'Synthetic private support'})['ticket']

    def resolve(self, ticket, reply=True):
        if reply:
            ticket = self.request('reply', ticket['id'], {'requestId': str(uuid.uuid4()), 'revision': ticket['revision'], 'message': 'Synthetic human support reply'})['ticket']
        return self.request('status', ticket['id'], {'requestId': str(uuid.uuid4()), 'revision': ticket['revision'], 'status': 'resolved'})['ticket']

    def survey(self, ticket):
        with self.connect() as db:
            with db.cursor() as cur:
                return support_surveys.read(cur, support.row(cur, ticket['id'], ticket['workspaceId']))

    def metrics(self, ids, *, end=None, group_by=(), filters=()):
        now = datetime.now(timezone.utc)
        service = QueryService(self.store, catalog=Catalog(), clock=lambda: now)
        query = {'metricIds':ids,'interval':{'start':(now-timedelta(days=1)).isoformat(),'end':(end or now).isoformat(),'timeZone':'America/Indiana/Indianapolis'},
                 'groupBy':list(group_by),'filters':list(filters),'comparison':'none','limit':100}
        result = service.metric_query(query, self.principal, str(uuid.uuid4()))
        self.assertEqual(result['executionState'], 'admitted_operational')
        self.assertEqual(result['mode'], 'live')
        self.assertTrue(result['queryReceiptId'])
        return result

    def test_only_new_human_supported_resolution_offers_feedback_once(self):
        ticket = self.create()
        self.assertIsNone(self.survey(ticket))
        ticket = self.resolve(ticket, reply=False)
        self.assertIsNone(self.survey(ticket))
        ticket = self.resolve(ticket)
        offered = self.survey(ticket)
        self.assertEqual(offered['state'], 'eligible')
        self.assertEqual(offered['sourceVersion'], support_surveys.SOURCE_VERSION)
        self.assertIsNone(offered['helpful'])
        closed = self.request('status', ticket['id'], {'requestId': str(uuid.uuid4()), 'revision': ticket['revision'], 'status': 'closed'})['ticket']
        self.assertEqual(self.survey(closed)['id'], offered['id'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_support_survey_offers WHERE workspace_id=%s', (self.primary,)).fetchone()[0], 1)

    def test_feedback_is_immutable_deduplicated_and_original_tenant_only(self):
        ticket = self.resolve(self.create())
        survey = self.survey(ticket)
        body = {'surveyId': survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': True}
        first = support_surveys.respond(self.service, self.primary, self.user, ticket['id'], body)
        self.assertEqual((first['duplicate'], first['survey']['state'], first['survey']['helpful']), (False, 'answered', True))
        self.assertTrue(support_surveys.respond(self.service, self.primary, self.user, ticket['id'], body)['duplicate'])
        metrics = founder_support.list_tickets(self.app, self.principal, {})['metrics']['csat']
        self.assertEqual((metrics['surveyOffers'], metrics['validResponses'], metrics['positiveResponses'], metrics['ratio'], metrics['responseRate']), (1, 1, 1, 1, 1))
        self.assertEqual(metrics['coverage'], 'observed_resolution_offers_only')
        self.assertNotIn('Synthetic private support', str(metrics))
        for conflict in ({**body, 'helpful': False}, {**body, 'requestId': str(uuid.uuid4())}):
            with self.assertRaises(AlphaError):
                support_surveys.respond(self.service, self.primary, self.user, ticket['id'], conflict)
        with self.connect() as db:
            with self.assertRaises(Exception):
                db.execute('UPDATE public.pr_support_survey_responses SET helpful=false WHERE workspace_id=%s', (self.primary,))
        with self.connect() as db:
            db.execute('SET LOCAL ROLE rafii_control_reader')
            aggregate = db.execute('SELECT count(*) FILTER(WHERE helpful),count(*) FROM rafii_control.business_support_survey_responses WHERE "workspaceId"=%s', (self.primary,)).fetchone()
            self.assertEqual(aggregate, (1, 1))
            with self.assertRaises(Exception):
                db.execute('SELECT actor_id,fingerprint FROM public.pr_support_survey_responses')

    def test_reopen_disables_old_offer_preserves_answer_and_new_resolution_is_distinct(self):
        ticket = self.resolve(self.create())
        old_survey = self.survey(ticket)
        body = {'surveyId': old_survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': False}
        reopened = support.customer(self.service, self.primary, self.user, 'POST', ticket['id'], {'requestId': str(uuid.uuid4()), 'message': 'Synthetic reopened issue'})['ticket']
        self.assertEqual(self.survey(reopened)['state'], 'reopened')
        with self.assertRaises(AlphaError):
            support_surveys.respond(self.service, self.primary, self.user, ticket['id'], body)
        next_ticket = self.resolve(reopened)
        next_survey = self.survey(next_ticket)
        self.assertNotEqual(next_survey['id'], old_survey['id'])
        new_body = {**body, 'surveyId': next_survey['id']}
        support_surveys.respond(self.service, self.primary, self.user, ticket['id'], new_body)
        reopened = support.customer(self.service, self.primary, self.user, 'POST', ticket['id'], {'requestId': str(uuid.uuid4()), 'message': 'Synthetic second reopen'})['ticket']
        self.assertEqual(self.survey(reopened)['state'], 'answered')
        self.assertTrue(support_surveys.respond(self.service, self.primary, self.user, ticket['id'], new_body)['duplicate'])

    def test_concurrent_answers_record_only_one_without_rewriting_outcome(self):
        ticket = self.resolve(self.create())
        survey = self.survey(ticket)
        def respond(helpful):
            try:
                support_surveys.respond(self.service, self.primary, self.user, ticket['id'], {'surveyId': survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': helpful})
                return 'recorded'
            except AlphaError:
                return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(respond, (True, False))), ['recorded', 'refused'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_support_survey_responses WHERE workspace_id=%s', (self.primary,)).fetchone()[0], 1)

    def test_no_backfill_internal_excluded_cross_workspace_or_other_creator_denied_and_tenant_deletion_works(self):
        ticket = self.create()
        with self.connect() as db:
            db.execute("UPDATE public.pr_support_tickets SET status='resolved',first_response_at=now(),resolved_at=now() WHERE id=%s", (ticket['id'],))
        self.assertIsNone(self.survey(ticket), 'Pre-collection resolution must not fabricate an invitation')
        internal_workspace = founder_ops.create_ops(self.app, self.principal, {'mode': 'live'})['workspaceId']
        internal = self.create(internal_workspace)
        # Internal resolution is exercised through the original tenant writer,
        # without giving Founder restricted projections access to this ticket.
        with self.connect() as db:
            with db.cursor() as cur:
                before = support.row(cur, internal['id'], internal_workspace)
                cur.execute("UPDATE public.pr_support_tickets SET status='resolved',first_response_at=now(),resolved_at=now(),revision=revision+1 WHERE id=%s", (internal['id'],))
                after = support.row(cur, internal['id'], internal_workspace)
                event = support.event(cur, before, after, self.user, 'founder', 'status', str(uuid.uuid4()), 'synthetic')
                support_surveys.offer(cur, before, after, event)
        internal_survey = self.survey(internal)
        support_surveys.respond(self.service, internal_workspace, self.user, internal['id'], {'surveyId': internal_survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': True})
        with self.connect() as db:
            db.execute('SET LOCAL ROLE rafii_control_reader')
            self.assertEqual(db.execute('SELECT count(*) FROM rafii_control.business_support_survey_offers WHERE "workspaceId"=%s', (internal_workspace,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM rafii_control.business_support_survey_responses WHERE "workspaceId"=%s', (internal_workspace,)).fetchone()[0], 0)
        with self.assertRaises(AlphaError):
            support_surveys.respond(self.service, self.primary, self.user, internal['id'], {'surveyId': internal_survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': False})
        with self.assertRaises(AlphaError):
            support_surveys.respond(self.service, internal_workspace, str(uuid.uuid4()), internal['id'], {'surveyId': internal_survey['id'], 'requestId': str(uuid.uuid4()), 'helpful': False})
        with self.connect() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (internal_workspace,))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_support_survey_responses WHERE workspace_id=%s', (internal_workspace,)).fetchone()[0], 0)

    def test_named_metric_receipts_reconcile_real_projection_and_never_invent_zero_satisfaction(self):
        by_id = {metric:self.metrics([metric])['rows'][0] for metric in ('open_tickets','csat')}
        self.assertEqual((by_id['open_tickets']['value'],by_id['open_tickets']['dataState']), (0,'measured'))
        self.assertEqual((by_id['csat']['value'],by_id['csat']['reason']), (None,'no_observed_resolution_offers'))
        first, second = self.create(), self.create()
        first = self.resolve(first)
        offered = self.survey(first)
        before_response = self.metrics(['csat'])['rows'][0]
        self.assertIsNone(before_response['value'])
        self.assertEqual(before_response['measures']['responseRate'], 0)
        before_answer = datetime.now(timezone.utc)
        support_surveys.respond(self.service, self.primary, self.user, first['id'], {'surveyId':offered['id'],'requestId':str(uuid.uuid4()),'helpful':True})
        current = self.metrics(['csat'])
        by_id = {'csat':current['rows'][0],'open_tickets':self.metrics(['open_tickets'])['rows'][0]}
        self.assertEqual(by_id['open_tickets']['value'], 1)
        self.assertEqual((by_id['csat']['value'],by_id['csat']['sampleCount'],by_id['csat']['dataState']), (1,1,'partial'))
        self.assertEqual(by_id['csat']['coverage']['numerator'],1)
        self.assertEqual(by_id['csat']['coverage']['denominator'],1)
        self.assertIsNone(self.metrics(['csat'], end=before_answer)['rows'][0]['value'], 'A future response cannot enter an earlier observation')
        grouped = self.metrics(['csat'],group_by=['category','window'])['rows'][0]
        self.assertEqual(grouped['dimensions']['category'],'technical')
        self.assertNotIn('Synthetic private',str(current))
        with self.connect() as db:
            receipt = db.execute('SELECT metric_versions,data_state FROM rafii_control.query_receipts WHERE id=%s',(current['queryReceiptId'],)).fetchone()
            self.assertEqual(receipt[0],{'csat':1})
            self.assertEqual(receipt[1],'partial')

    def test_historical_snapshot_and_unknown_sql_dimensions_are_refused(self):
        old = self.metrics(['open_tickets'],end=datetime.now(timezone.utc)-timedelta(hours=1))['rows'][0]
        self.assertEqual((old['value'],old['reason']),(None,'historical_ticket_snapshot_not_collected'))
        with self.assertRaises(ControlError):
            self.metrics(['csat'],group_by=['email'])
        with self.assertRaises(ControlError):
            self.metrics(['open_tickets','csat'])
        injection = self.metrics(['open_tickets'],filters=[{'dimension':'category','operator':'in','values':["technical'); SELECT body FROM public.pr_support_messages --"]}])
        self.assertEqual(injection['rows'][0]['value'],0)

    def test_forced_rls_scoped_projection_and_service_mutation_permissions(self):
        with self.connect() as db:
            for table in ('pr_support_survey_offers','pr_support_survey_responses'):
                self.assertTrue(db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",('public.'+table,)).fetchone()[0])
                for role in ('anon','authenticated','rafii_control_reader'):
                    self.assertFalse(db.execute("SELECT has_table_privilege(%s,%s,'SELECT')",(role,'public.'+table)).fetchone()[0])
                for permission in ('UPDATE','DELETE','TRUNCATE'):
                    self.assertFalse(db.execute('SELECT has_table_privilege(%s,%s,%s)',('service_role','public.'+table,permission)).fetchone()[0])
        first, second = self.resolve(self.create()), self.resolve(self.create())
        first_survey = self.survey(first)
        with self.connect() as db:
            with self.assertRaises(Exception):
                db.execute('INSERT INTO public.pr_support_survey_responses(workspace_id,survey_id,actor_id,request_id,fingerprint,helpful,source_version) VALUES(%s,%s,%s,%s,%s,true,%s)',
                    (self.primary,first_survey['id'],str(uuid.uuid4()),str(uuid.uuid4()),'synthetic',support_surveys.SOURCE_VERSION))


class SupportMetricDemoTests(unittest.TestCase):
    def test_demo_fallback_does_not_alias_privacy_request_counts_to_tickets_or_survey_feedback(self):
        data = {'summary':{'openRequests':777},'asOf':'2026-10-04T00:00:00Z'}
        with patch.object(founder_tools.demo_dataset,'receipt',return_value={'dataState':'synthetic'}):
            for metric in ('open_tickets','csat'):
                row = founder_tools._demo_rows_for(data,metric,[],{})[0]
                self.assertIsNone(row['value'])
                self.assertEqual((row['dataState'],row['reason'],row['fixture']),('unavailable','demo_not_simulated',True))
                self.assertNotIn('777',str(row))
