"""Real disposable projection/query/evidence/copilot acceptance; zero live provider calls."""
import json
import os
import unittest
import uuid
import psycopg
from control.synthetic_workflow import seed
from rafii_control.auth import ControlError
from rafii_control.intelligence import QueryService, canonical
from rafii_control.projections import Projector
from rafii_control.store import connection_factory, PostgresStore


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'),'disposable control PostgreSQL required')
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['RAFII_CONTROL_TEST_DSN']
        self.events,self.query=seed(self.dsn,'acceptance-'+uuid.uuid4().hex[:8])
        self.store=PostgresStore(connection_factory(self.dsn,'rafii_control_session','local'),connection_factory(self.dsn,'rafii_control_reader','local'),'local')
        self.principal={'operator':{'user_id':'00000000-0000-0000-0000-000000000001','capabilities':['metrics.query','copilot.use']},'session':{'environment':'local'}}
        self.service=QueryService(self.store,synthetic=True)

    def tearDown(self):
        with psycopg.connect(self.dsn,autocommit=True) as owner:
            suites=[event['source'] for event in self.events]
            owner.execute("DELETE FROM rafii_control.metric_rollups WHERE environment='local' AND dimensions->>'suite'=ANY(%s)",(suites,))
            owner.execute("DELETE FROM rafii_control.normalized_events WHERE environment='local' AND source=ANY(%s)",(suites,))
            owner.execute("DELETE FROM rafii_control.engineering_evidence WHERE environment='local' AND id=ANY(%s::uuid[])",([event['payload']['receiptId'] for event in self.events],))

    def test_source_to_projection_query_receipt_and_grounded_copilot(self):
        result=self.service.metric_query(self.query,self.principal,str(uuid.uuid4()))
        self.assertEqual(result['executionState'],'local_synthetic')
        rows={row['dimensions']['suite'].split('-')[-1]:row for row in result['rows']}
        self.assertEqual(rows['zero']['value'],0)
        self.assertEqual(rows['zero']['dataState'],'measured')
        self.assertEqual(rows['one']['value'],1)
        self.assertEqual(rows['partial']['dataState'],'partial')
        self.assertIsNone(rows['partial']['value'])
        self.assertEqual(rows['stale']['dataState'],'stale')
        self.assertTrue(all(row['sourceReceiptIds'] for row in rows.values()))
        self.assertEqual(result['dataState'],'partial')
        receipt=self.store.read('receipt',result['queryReceiptId'])[0]
        self.assertEqual(receipt['result_rows'],result['rows'])
        request=dict(requestId=str(uuid.uuid4()),conversationId=str(uuid.uuid4()),message='Explain these check failures',contextEvidenceIds=[result['queryReceiptId']],modality='text')
        run=self.service.copilot_turn(request,self.principal)
        self.assertEqual(run['queryReceiptIds'],[result['queryReceiptId']])
        self.assertEqual(run['evidenceRows'],result['rows'])
        self.assertIn('Synthetic',run['answerText'])
        self.assertIn('partial',run['answerText'])
        self.assertIn('stale',run['answerText'])
        self.assertEqual(run['usage']['providerCalls'],0)
        self.assertEqual(run['changedEntities'],[])
        evidence=dict(execution='local_synthetic',query=self.query,response=result,receipt=receipt,copilot=run)
        from pathlib import Path
        Path('docs/rafii-control-v2/evidence/read-workflow.json').write_text(json.dumps(evidence,indent=2))

    def test_duplicate_and_conflicting_events_never_change_materialized_count(self):
        projector=Projector(connection_factory(self.dsn,'rafii_control_ingest','local'),'local')
        event=self.events[1]
        self.assertFalse(projector.ingest({**event,'eventId':str(uuid.uuid4())}))
        with self.assertRaisesRegex(ControlError,'IDEMPOTENCY_CONFLICT'):projector.ingest({**event,'payload':{**event['payload'],'exactSha':'b'*40}})
        with self.assertRaisesRegex(ControlError,'VALIDATION_FAILED'):projector.ingest({**event,'eventId':str(uuid.uuid4()),'sourceEventId':str(uuid.uuid4()),'dedupeKey':'changed:'+uuid.uuid4().hex})
        with self.assertRaisesRegex(ControlError,'IDEMPOTENCY_CONFLICT'):projector.ingest({**event,'eventId':str(uuid.uuid4()),'source':'different-suite','dedupeKey':'changed:'+uuid.uuid4().hex})
        result=self.service.metric_query(self.query,self.principal,str(uuid.uuid4()))
        self.assertEqual(next(row['value'] for row in result['rows'] if row['dimensions']['suite']==event['source']),1)

    def test_policy_currency_environment_and_query_boundaries(self):
        unavailable=self.service.metric_query({**self.query,'metricIds':['mrr'],'groupBy':['currency'],'filters':[]},self.principal,str(uuid.uuid4()))
        self.assertEqual(unavailable['dataState'],'unavailable')
        self.assertIsNone(unavailable['rows'][0]['value'])
        with self.assertRaises(ControlError):self.service.metric_query({**self.query,'metricIds':['mrr'],'groupBy':[],'filters':[]},self.principal,str(uuid.uuid4()))
        with self.assertRaisesRegex(ControlError,'SCOPE_DENIED'):QueryService(self.store,synthetic=True).metric_query(self.query,{**self.principal,'session':{'environment':'staging'}},str(uuid.uuid4()))
        normal=QueryService(self.store).metric_query(self.query,self.principal,str(uuid.uuid4()))
        self.assertIsNone(normal['rows'][0]['value'])
        with self.assertRaisesRegex(ControlError,'VALIDATION_FAILED'):self.service.metric_query({**self.query,'comparison':'previous_complete'},self.principal,str(uuid.uuid4()))
        with self.assertRaisesRegex(ControlError,'BUDGET_EXCEEDED'):self.service.metric_query({**self.query,'limit':1},self.principal,str(uuid.uuid4()))
        empty=self.service.metric_query({**self.query,'filters':[{'dimension':'suite','operator':'eq','values':['missing-source']}]},self.principal,str(uuid.uuid4()))
        self.assertIsNone(empty['rows'][0]['value'])
        self.assertEqual(empty['dataState'],'unavailable')

    def test_receipt_expiry_and_hosted_synthetic_context_fail_closed(self):
        result=self.service.metric_query(self.query,self.principal,str(uuid.uuid4()))
        request=dict(requestId=str(uuid.uuid4()),conversationId=str(uuid.uuid4()),message='Explain evidence',contextEvidenceIds=[result['queryReceiptId']],modality='text')
        with self.assertRaisesRegex(ControlError,'SCOPE_DENIED'):QueryService(self.store).copilot_turn(request,self.principal)
        with psycopg.connect(self.dsn,autocommit=True) as owner:
            owner.execute("UPDATE rafii_control.query_receipts SET expires_at=now()-interval '1 second' WHERE id=%s",(result['queryReceiptId'],))
        with self.assertRaisesRegex(ControlError,'STALE_PREVIEW'):self.service.copilot_turn(request,self.principal)

    def test_denial_codes_are_persisted_in_restricted_audit(self):
        import io
        from rafii_control.auth import Boundary, Config
        from rafii_control.http import ControlApplication
        for code,status in [('RATE_LIMITED',429),('SOURCE_UNAVAILABLE',503),('AUTH_REQUIRED',401)]:
            def unavailable(token): raise ControlError(code,status)
            app=ControlApplication(Boundary(Config(True,'local','http://localhost:4449'),self.store,unavailable))
            env=dict(PATH_INFO='/api/control/v2/session/exchange',REQUEST_METHOD='POST',CONTENT_LENGTH='2',CONTENT_TYPE='application/json',HTTP_HOST='localhost:4449',HTTP_ORIGIN='http://localhost:4449',HTTP_AUTHORIZATION='Bearer synthetic-only',HTTP_X_CONTROL_EXCHANGE='1',**{'wsgi.input':io.BytesIO(b'{}')})
            response={}
            body=json.loads(b''.join(app(env,lambda s,h:response.update(status=int(s[:3])))))
            self.assertEqual(response['status'],status)
            audit=next(row for row in self.store.audit_read() if row['request_id']==body['requestId'])
            self.assertEqual(audit['error_code'],code)
            self.assertEqual(audit['result'],'denied')

    def test_concurrent_replay_commits_one_event_and_projection(self):
        from concurrent.futures import ThreadPoolExecutor
        event=self.events[0]
        with psycopg.connect(self.dsn,autocommit=True) as owner:
            owner.execute('DELETE FROM rafii_control.normalized_events WHERE event_id=%s',(event['eventId'],))
            owner.execute("DELETE FROM rafii_control.metric_rollups WHERE environment='local' AND dimensions->>'suite'=%s",(event['source'],))
        projector=Projector(connection_factory(self.dsn,'rafii_control_ingest','local'),'local')
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(projector.ingest,[event,{**event,'eventId':str(uuid.uuid4())}])),[False,True])
        with psycopg.connect(self.dsn,autocommit=True) as owner:
            self.assertEqual(owner.execute('SELECT count(*) FROM rafii_control.normalized_events WHERE source=%s',(event['source'],)).fetchone()[0],1)
            self.assertEqual(owner.execute("SELECT count(*) FROM rafii_control.metric_rollups WHERE environment='local' AND dimensions->>'suite'=%s",(event['source'],)).fetchone()[0],1)

    def test_input_budget_stops_before_returning_or_receipting_truncated_values(self):
        with psycopg.connect(self.dsn,autocommit=True) as owner:
            try:
                owner.execute("""INSERT INTO rafii_control.metric_rollups(environment,metric_id,definition_version,interval_start,interval_end,grain,dimension_digest,dimensions,value,sample_count,source_watermark,source_receipt_ids,data_state,fixture)
                  SELECT 'local','check_failures',1,now()-interval '1 day'+n*interval '1 microsecond',now()-interval '1 day'+(n+1)*interval '1 microsecond','runner check',repeat('a',64),'{"suite":"budget-only","failure_class":"test"}'::jsonb,0,1,now(),ARRAY[gen_random_uuid()],'measured',true FROM generate_series(1,1001) n""")
                before=owner.execute('SELECT count(*) FROM rafii_control.query_receipts').fetchone()[0]
                query={**self.query,'filters':[{'dimension':'suite','operator':'eq','values':['budget-only']}]}
                with self.assertRaisesRegex(ControlError,'BUDGET_EXCEEDED'):self.service.metric_query(query,self.principal,str(uuid.uuid4()))
                self.assertEqual(owner.execute('SELECT count(*) FROM rafii_control.query_receipts').fetchone()[0],before)
            finally:
                owner.execute("DELETE FROM rafii_control.metric_rollups WHERE environment='local' AND dimensions->>'suite'='budget-only'")
