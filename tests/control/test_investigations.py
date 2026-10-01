"""Actual captured public metadata plus explicit synthetic fault/clock tests; no provider calls."""
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import uuid
from urllib.error import HTTPError,URLError
from unittest.mock import patch
import psycopg
from rafii_control.auth import ControlError
from rafii_control.deadlines import deadline
from rafii_control.github_source import capture_response,manual_fetch
from rafii_control.investigations import validate_capture
from rafii_control.intelligence import QueryService,canonical
from rafii_control.snapshot_store import import_snapshot
from rafii_control.store import connection_factory,PostgresStore

OBSERVED=json.loads((Path(__file__).parent/'fixtures/github-observed-be140fd.json').read_text())
def request(ref=None):return dict(requestId=str(uuid.uuid4()),conversationId=str(uuid.uuid4()),message='Explain selected receipt' if ref else 'Inspect checks',contextEvidenceIds=[ref] if ref else [],modality='text')
def query(capture=OBSERVED):
    observed=datetime.fromisoformat(capture['observedAt']);return dict(metricIds=['check_failures'],interval={'start':(observed-timedelta(days=1)).isoformat(),'end':(observed+timedelta(days=1)).isoformat(),'timeZone':'UTC'},groupBy=['suite','failure_class'],filters=[],comparison='none',limit=100)

class ProviderBoundaryTests(unittest.TestCase):
    def test_manual_adapter_bounds_429_5xx_timeouts_without_exposing_body(self):
        for error,code in [(HTTPError('safe',429,'PRIVATE_CANARY',{},None),'RATE_LIMITED'),(HTTPError('safe',502,'PRIVATE_CANARY',{},None),'SOURCE_UNAVAILABLE'),(URLError('PRIVATE_CANARY'),'SOURCE_UNAVAILABLE'),(TimeoutError('PRIVATE_CANARY'),'SOURCE_UNAVAILABLE')]:
            def fail(url,timeout):self.assertLessEqual(timeout,5);raise error
            before=time.monotonic()
            with self.subTest(code=code),self.assertRaisesRegex(ControlError,code) as caught:manual_fetch(fail,OBSERVED['exactSha'])
            self.assertNotIn('PRIVATE_CANARY',str(caught.exception));self.assertLess(time.monotonic()-before,.5)

    def test_capture_size_total_coverage_duplicate_timestamps_and_digest(self):
        validate_capture(OBSERVED)
        for change in [dict(providerBodyDigest='0'*64),dict(exactSha='b'*40),dict(observedAt='2099-01-01T00:00:00Z'),dict(coverage={**OBSERVED['coverage'],'totalRuns':3})]:
            with self.subTest(change=change),self.assertRaises(ControlError):validate_capture({**OBSERVED,**change})
        with self.assertRaises(ControlError):validate_capture({**OBSERVED,'provenance':'synthetic'},admit=True)
        body={'workflow_runs':OBSERVED['workflowRuns'],'total_count':3}
        partial=capture_response(body,OBSERVED['exactSha'],OBSERVED['requestedAt'],OBSERVED['observedAt'])
        self.assertFalse(partial['coverage']['complete'])
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,limit):self.limit=limit;return b'x'*limit
        with self.assertRaisesRegex(ControlError,'BUDGET_EXCEEDED'):manual_fetch(lambda *args,**kwargs:Response(),OBSERVED['exactSha'])

    def test_adapter_rejects_late_client_and_no_implicit_fetch_exists(self):
        elapsed=[0]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,limit):elapsed[0]=11;return b'{}'
        token=deadline.set(10)
        try:
            with patch('rafii_control.deadlines.monotonic',side_effect=lambda:elapsed[0]),self.assertRaisesRegex(ControlError,'SOURCE_UNAVAILABLE'):manual_fetch(lambda *args,**kw:Response(),OBSERVED['exactSha'])
        finally:deadline.reset(token)

@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'),'disposable PostgreSQL required')
class InvestigationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['RAFII_CONTROL_TEST_DSN'];self.capture={**copy.deepcopy(OBSERVED),'captureId':str(uuid.uuid4()),'requestId':str(uuid.uuid4())}
        self.principal={'operator':{'user_id':'00000000-0000-0000-0000-000000000001','capabilities':['engineering.read','metrics.query','copilot.use']},'session':{'environment':'local'}}
        self.store=PostgresStore(connection_factory(self.dsn,'rafii_control_session','local'),connection_factory(self.dsn,'rafii_control_reader','local'),'local')
        self.factory=connection_factory(self.dsn,'rafii_control_ingest','local')
        self.clock=lambda:datetime.fromisoformat(self.capture['observedAt'])+timedelta(seconds=1)
        self.service=QueryService(self.store,clock=self.clock)
        self.ids=[]
    def tearDown(self):
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.github_check_snapshots WHERE id=ANY(%s::uuid[])',([self.capture['captureId'],*self.ids],))
    def test_actual_metadata_admission_replay_exact_sha_receipt_and_explanation(self):
        identifier,inserted=import_snapshot(self.factory,self.capture,admit=True);self.assertTrue(inserted)
        self.assertEqual(import_snapshot(self.factory,self.capture,admit=True),(identifier,False))
        with self.assertRaisesRegex(ControlError,'IDEMPOTENCY_CONFLICT'):import_snapshot(self.factory,{**self.capture,'requestId':str(uuid.uuid4())},admit=True)
        result=self.service.metric_query(query(self.capture),self.principal,str(uuid.uuid4()),identifier)
        self.assertEqual([r['value'] for r in result['rows']],[0,0]);self.assertEqual(result['dataState'],'measured');self.assertEqual(result['executionState'],'admitted_operational')
        receipt=self.service.authorized_receipt(result['queryReceiptId'],self.principal)
        self.assertEqual(receipt['normalized_query'],result['normalizedQuery']);self.assertEqual(receipt['result_rows'],result['rows'])
        self.assertEqual(receipt['query_digest'],hashlib.sha256(canonical(query(self.capture)).encode()).hexdigest())
        self.assertEqual(receipt['source_versions']['exactSha'],OBSERVED['exactSha']);self.assertFalse(receipt['coverage']['releaseAccepted'])
        run=self.service.copilot_turn(request(result['queryReceiptId']),self.principal);self.assertEqual(run['evidenceRows'],result['rows']);self.assertEqual(run['usage']['providerCalls'],0)
    def test_unadmitted_capture_never_becomes_numeric_with_age(self):
        identifier,_=import_snapshot(self.factory,self.capture)
        for minutes in [1,20]:
            self.service.clock=lambda:datetime.fromisoformat(self.capture['observedAt'])+timedelta(minutes=minutes)
            result=self.service.metric_query(query(self.capture),self.principal,str(uuid.uuid4()),identifier)
            self.assertTrue(all(row['value'] is None for row in result['rows']))
            self.assertEqual(result['executionState'],'provider_observed_test')
    def test_revoked_engineering_denies_receipt_cached_run_and_new_query(self):
        identifier,_=import_snapshot(self.factory,self.capture,admit=True)
        result=self.service.metric_query(query(self.capture),self.principal,str(uuid.uuid4()),identifier);turn=request(result['queryReceiptId']);run=self.service.copilot_turn(turn,self.principal)
        self.principal['operator']['capabilities'].remove('engineering.read')
        for call in [lambda:self.service.authorized_receipt(result['queryReceiptId'],self.principal),lambda:self.service.copilot_turn(turn,self.principal),lambda:self.service.dispatch('/copilot/runs/'+run['runId'],{},self.principal,str(uuid.uuid4())),lambda:self.service.metric_query(query(self.capture),self.principal,str(uuid.uuid4()),identifier)]:
            with self.assertRaisesRegex(ControlError,'SCOPE_DENIED'):call()
    def test_immutable_snapshot_rls_no_browser_writes_and_no_fixture_admission(self):
        synthetic={**self.capture,'provenance':'synthetic'}
        with self.assertRaises(ControlError):import_snapshot(self.factory,synthetic,admit=True)
        identifier,_=import_snapshot(self.factory,synthetic)
        for role in ['anon','authenticated','service_role','rafii_control_reader','rafii_control_session']:
            with psycopg.connect(self.dsn,autocommit=True) as con:
                con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):con.execute('DELETE FROM rafii_control.github_check_snapshots WHERE id=%s',(identifier,))
        reader=PostgresStore(connection_factory(self.dsn,'rafii_control_session','local'),connection_factory(self.dsn,'rafii_control_reader','local'),'staging')
        self.assertIsNone(reader.check_snapshot(identifier))
    def test_filters_windows_and_unsupported_comparison_do_not_become_zero(self):
        identifier,_=import_snapshot(self.factory,self.capture,admit=True);q=query(self.capture)
        absent=self.service.metric_query({**q,'filters':[{'dimension':'suite','operator':'eq','values':['no such workflow']}]},self.principal,str(uuid.uuid4()),identifier)
        self.assertIsNone(absent['rows'][0]['value'])
        for change in [dict(comparison='previous_complete'),dict(groupBy=[])]:
            with self.assertRaises(ControlError):self.service.metric_query({**q,**change},self.principal,str(uuid.uuid4()),identifier)
    def test_terminated_worker_running_record_recovers_and_late_completion_cannot_overwrite(self):
        turn=request()
        import subprocess,sys
        program="from rafii_control.store import PostgresStore,connection_factory;import os,json;d=os.environ['RAFII_CONTROL_TEST_DSN'];s=PostgresStore(connection_factory(d,'rafii_control_session','local'),connection_factory(d,'rafii_control_reader','local'),'local');p=json.loads(os.environ['CONTROL_TEST_PRINCIPAL']);r=json.loads(os.environ['CONTROL_TEST_REQUEST']);identifier,_=s.reserve_run(r,p,'a'*64);print(identifier,flush=True);os._exit(23)"
        child=subprocess.run([sys.executable,'-c',program],env={**os.environ,'CONTROL_TEST_PRINCIPAL':json.dumps(self.principal),'CONTROL_TEST_REQUEST':json.dumps(turn)},capture_output=True,text=True,timeout=5)
        self.assertEqual(child.returncode,23);run_id=str(uuid.UUID(child.stdout.strip()))
        with psycopg.connect(self.dsn,autocommit=True) as con:con.execute("UPDATE rafii_control.founder_runs SET created_at=now()-interval '3 minutes' WHERE id=%s",(run_id,))
        recovered=self.store.run(run_id,self.principal['operator']['user_id']);self.assertEqual(recovered['state'],'blocked');self.assertIn('unknown',recovered['answerText'])
        self.assertIs(self.store.save_run(dict(runId=run_id,state='completed',queryReceiptIds=[]),self.principal,turn['conversationId']),False)
        self.assertEqual(self.store.run(run_id,self.principal['operator']['user_id'])['state'],'blocked')
        with psycopg.connect(self.dsn) as con:
            audit=con.execute("SELECT result,error_code FROM rafii_control.admin_audit_log WHERE request_id=%s",(turn['requestId'],)).fetchall()
        self.assertEqual(audit,[('failed','SOURCE_UNAVAILABLE')])
    def test_real_statement_deadline_cancels_pg_sleep(self):
        token=deadline.set(time.monotonic()+.2);before=time.monotonic()
        try:
            with self.assertRaises((psycopg.errors.QueryCanceled,ControlError)):
                with self.store.transaction(read=True) as con:con.execute('SELECT pg_sleep(2)')
        finally:deadline.reset(token)
        self.assertLess(time.monotonic()-before,.8)
    def test_keyboard_interrupt_persists_safe_terminal_run(self):
        turn=request()
        with patch.object(self.service,'_copilot_read',side_effect=KeyboardInterrupt('PRIVATE_CANARY')),self.assertRaises(KeyboardInterrupt):self.service.copilot_turn(turn,self.principal)
        with psycopg.connect(self.dsn) as con:row=con.execute('SELECT result FROM rafii_control.founder_runs WHERE request_id=%s',(turn['requestId'],)).fetchone()[0]
        self.assertEqual(row['state'],'blocked');self.assertNotIn('PRIVATE_CANARY',json.dumps(row))

    def test_real_database_cancellation_rolls_back_and_remains_readable(self):
        from threading import Timer
        with self.store.transaction(read=True) as con:
            timer=Timer(.15,con.cancel);timer.start();before=time.monotonic()
            try:
                with self.assertRaises(psycopg.errors.QueryCanceled):con.execute('SELECT pg_sleep(5)')
            finally:timer.cancel()
        self.assertLess(time.monotonic()-before,.8)
        self.assertTrue(self.store.read('users'))

    def test_pg_read_failure_returns_safe_503_and_persists_terminal_audit(self):
        import io
        from rafii_control.auth import Boundary,Config,VerifiedIdentity,COOKIE
        from rafii_control.http import ControlApplication
        boundary=Boundary(Config(True,'local','http://localhost:4449'),self.store,lambda token:VerifiedIdentity(self.principal['operator']['user_id'],'aal2','synthetic-fault-session-001',time.time()))
        token,_=boundary.exchange('synthetic-only','http://localhost:4449')
        def unavailable():raise psycopg.OperationalError('PRIVATE_DATABASE_BODY_CANARY')
        broken=PostgresStore(self.store.session_factory,unavailable,'local')
        app=ControlApplication(boundary,QueryService(broken))
        env=dict(PATH_INFO='/api/control/v2/overview',REQUEST_METHOD='GET',HTTP_HOST='localhost:4449',HTTP_COOKIE=COOKIE+'='+token,**{'wsgi.input':io.BytesIO(b'')})
        response={};body=json.loads(b''.join(app(env,lambda s,h:response.update(status=int(s[:3])))))
        self.assertEqual(response['status'],503);self.assertNotIn('PRIVATE_DATABASE_BODY_CANARY',json.dumps(body))
        event=next(r for r in self.store.audit_read() if r['request_id']==body['requestId'])
        self.assertEqual((event['result'],event['error_code']),('failed','SOURCE_UNAVAILABLE'))

    def test_upstream_revocation_projection_denies_existing_local_founder_cookie(self):
        from rafii_control.auth import Boundary,Config,VerifiedIdentity
        upstream='synthetic-revocation-'+uuid.uuid4().hex
        boundary=Boundary(Config(True,'local','http://localhost:4449'),self.store,lambda token:VerifiedIdentity(self.principal['operator']['user_id'],'aal2',upstream,time.time()))
        token,_=boundary.exchange('synthetic-only','http://localhost:4449');boundary.authorize(token,'control.read')
        with psycopg.connect(self.dsn,autocommit=True) as con:con.execute('INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s)',(self.principal['operator']['user_id'],upstream))
        try:
            with self.assertRaisesRegex(ControlError,'AUTH_REQUIRED'):boundary.authorize(token,'control.read')
        finally:
            with psycopg.connect(self.dsn,autocommit=True) as con:con.execute('DELETE FROM public.pr_session_revocations WHERE session_id=%s',(upstream,))
