"""Regression oracles for the approved read-only investigation milestone."""
from datetime import datetime, timezone, timedelta
import json
import unittest
import uuid
from rafii_control.intelligence import QueryService
from control import test_intelligence as intelligence_helpers
from control import test_boundary as boundary_helpers
from rafii_control.http import ControlApplication

class TrustRegressionTests(unittest.TestCase):
    def setUp(self):
        self.store=intelligence_helpers.ReadStore()
        base=intelligence_helpers.IntelligenceTests(); base.setUp()
        self.principal,self.query=base.principal,base.query
        self.service=QueryService(self.store)

    def test_aged_source_cannot_remain_current_measured(self):
        self.store.read=lambda kind,identifier=None: [dict(source_id='github',state='measured',watermark='2000-01-01T00:00:00+00:00',checked_at='2000-01-01T00:00:00+00:00',reason_code='qualified')] if kind=='sources' else []
        source=next(s for s in self.service.source_health() if s['source_id']=='github')
        self.assertNotEqual(source['state'],'measured')
        self.assertEqual(source['last_good']['state'],'measured')

    def test_receipt_retains_reproducible_query_and_calculation(self):
        result=self.service.metric_query(self.query,self.principal,str(uuid.uuid4()))
        saved=self.store.receipts[-1]
        self.assertEqual(saved['normalizedQuery'],self.query)
        self.assertEqual(saved['calculatedAt'],result['asOf'])
        self.assertIn('complete',saved['coverage'])
        self.assertIn('sourceVersions',saved)

    def test_unknown_question_does_not_select_activation(self):
        request=dict(requestId=str(uuid.uuid4()),conversationId=str(uuid.uuid4()),message='Why did AI spend spike yesterday?',contextEvidenceIds=[],modality='text')
        run=self.service.copilot_turn(request,self.principal)
        self.assertEqual(run['queryReceiptIds'],[])
        self.assertEqual(run['state'],'blocked')
        self.assertIn('unsupported',run['answerText'].lower())
        self.assertEqual(self.store.receipts,[])

    def test_generic_read_failure_has_terminal_outcome(self):
        h=boundary_helpers.HttpTests();h.setUp();token,session=h.exchange()
        class Broken:
            def dispatch(self,*args):raise RuntimeError('PRIVATE_BODY_SECRET_CANARY')
        response,body=h.request(ControlApplication(h.boundary,Broken()),'/api/control/v2/metrics/query','POST',{},cookie='__Host-rafii-control='+token,headers={'HTTP_X_CSRF_TOKEN':session['csrfToken']})
        self.assertEqual(response['status'],503)
        self.assertEqual(h.store.events[-1]['result'],'failed')
        self.assertEqual(h.store.events[-1]['request_id'],body['requestId'])
        self.assertNotIn('PRIVATE_BODY_SECRET_CANARY',json.dumps(body)+json.dumps(h.store.events))

    def test_quality_rejects_future_missing_malformed_conflicts_and_unqualified(self):
        from rafii_control.investigations import effective_quality
        now=datetime.now(timezone.utc)
        row=dict(source_id='github',state='measured',checked_at=now.isoformat(),watermark=now.isoformat(),qualified=True,coverage_complete=True,provenance='admitted_operational',source_version='github-workflow/1')
        self.assertEqual(effective_quality(row,now)['state'],'measured')
        for change in [dict(checked_at=None),dict(watermark='broken'),dict(checked_at=(now+timedelta(seconds=1)).isoformat()),dict(state='conflicting'),dict(qualified=False),dict(coverage_complete=False),dict(provenance='synthetic')]:
            self.assertNotEqual(effective_quality({**row,**change},now)['state'],'measured')

    def test_exact_manifest_and_sha_distinguish_all_check_states(self):
        from rafii_control.investigations import evaluate_checks
        manifest=dict(version=1,repository='dev-james0723/PostRiff',sha='a'*40,required=['Control','Release'])
        base=[dict(name=n,head_sha='a'*40,status='completed',conclusion='success',id=i+1) for i,n in enumerate(manifest['required'])]
        self.assertEqual(evaluate_checks(base,manifest,True)['qualification'],'required_checks_succeeded')
        self.assertEqual(evaluate_checks(base,manifest,False)['qualification'],'incomplete_coverage')
        for conclusion,status in [('failure','failure'),('skipped','skipped'),('timed_out','infrastructure_failure'),(None,'incomplete')]:
            rows=[{**base[0],'conclusion':conclusion},base[1]]
            self.assertEqual(evaluate_checks(rows,manifest,True)['checks'][0]['outcome'],status)
        self.assertEqual(evaluate_checks(base[1:],manifest,True)['checks'][0]['outcome'],'missing')
        self.assertEqual(evaluate_checks([{**base[0],'head_sha':'b'*40},base[1]],manifest,True)['checks'][0]['outcome'],'missing')
        self.assertFalse(evaluate_checks(base,manifest,True)['releaseAccepted'])

    def test_supported_intent_preserves_window_and_declines_unqualified_comparison(self):
        from rafii_control.investigations import plan_intent
        now=datetime(2026,9,30,12,tzinfo=timezone.utc)
        plan=plan_intent('Show check failures yesterday',now)
        self.assertEqual(plan['metricIds'],['check_failures'])
        self.assertEqual(plan['interval']['start'],'2026-09-29T00:00:00+00:00')
        self.assertEqual(plan['interval']['end'],'2026-09-30T00:00:00+00:00')
        self.assertEqual(plan_intent('Compare check failures with last week',now)['comparison'],'previous_complete')
        self.assertIsNone(plan_intent('Why did AI spend spike yesterday?',now))

    def test_upstream_revocation_and_identity_outage_fail_closed_locally(self):
        from rafii_control.auth import ControlError
        h=boundary_helpers.HttpTests();h.setUp();token,_=h.exchange()
        h.store.identity_active=lambda *args:False
        with self.assertRaises(ControlError):h.boundary.authorize(token,'control.read')
        def unavailable(*args):raise RuntimeError('PRIVATE_IDENTITY_BODY')
        h.store.identity_active=unavailable
        response,body=h.request(ControlApplication(h.boundary),cookie='__Host-rafii-control='+token)
        self.assertEqual(response['status'],503)
        self.assertNotIn('PRIVATE_IDENTITY_BODY',json.dumps(body))

    def test_age_never_admits_unqualified_or_conflicting_evidence(self):
        from rafii_control.investigations import effective_quality
        now=datetime.now(timezone.utc);old=(now-timedelta(minutes=20)).isoformat()
        base=dict(state='measured',checked_at=old,watermark=old,qualified=True,coverage_complete=True,provenance='admitted_operational',source_version='github-workflow/1')
        self.assertEqual(effective_quality(base,now)['state'],'stale')
        for change in [dict(provenance='provider_observed_test'),dict(qualified=False),dict(coverage_complete=False),dict(conflicts=True)]:
            self.assertNotIn(effective_quality({**base,**change},now)['state'],('stale','measured'))

    def test_receipt_get_and_explanation_recheck_engineering_capability(self):
        from rafii_control.auth import ControlError
        ref=str(uuid.uuid4())
        receipt=dict(id=ref,operator_id=self.principal['operator']['user_id'],source_versions={'adapter':'github-workflow/1'},normalized_query={'metricIds':['check_failures']},expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),execution_state='admitted_operational',data_state='measured',result_rows=[])
        self.store.read=lambda kind,identifier=None:[receipt] if kind=='receipt' else []
        self.principal['operator']['capabilities'].remove('engineering.read')
        with self.assertRaises(ControlError):self.service.dispatch('/metrics/receipts/'+ref,{},self.principal,str(uuid.uuid4()))
        with self.assertRaises(ControlError):self.service.copilot_turn(dict(requestId=str(uuid.uuid4()),conversationId=str(uuid.uuid4()),message='Explain selected receipt',contextEvidenceIds=[ref],modality='text'),self.principal)

    def test_connection_initialization_rechecks_remaining_budget(self):
        from unittest.mock import patch
        from rafii_control.store import connection_factory
        from rafii_control.deadlines import deadline
        from rafii_control.auth import ControlError
        elapsed=[0];calls=[]
        class Connection:
            def execute(self,sql):calls.append(str(sql));elapsed[0]+=6;return self
            def fetchone(self):return (False,False)
            def commit(self):calls.append('commit')
            def close(self):calls.append('close')
        token=deadline.set(10)
        try:
            with patch('rafii_control.deadlines.monotonic',side_effect=lambda:elapsed[0]),patch('rafii_control.store.psycopg.connect',return_value=Connection()) as connect:
                with self.assertRaises(ControlError):connection_factory('synthetic-dsn','rafii_control_reader','local')()
                self.assertIn('statement_timeout',connect.call_args.kwargs.get('options',''))
            self.assertNotIn('commit',calls)
        finally:deadline.reset(token)

    def test_terminal_audit_outage_fails_closed_with_safe_correlation_log(self):
        h=boundary_helpers.HttpTests();h.setUp();token,_=h.exchange()
        original=h.store.audit
        def fail_terminal(**event):
            if event['result'] in ('succeeded','failed'):raise RuntimeError('PRIVATE_AUDIT_BODY')
            return original(**event)
        h.store.audit=fail_terminal
        with self.assertLogs('rafii_control.audit',level='ERROR') as log:
            response,body=h.request(ControlApplication(h.boundary),cookie='__Host-rafii-control='+token)
        self.assertEqual(response['status'],503);self.assertIn(body['requestId'],' '.join(log.output));self.assertNotIn('PRIVATE_AUDIT_BODY',' '.join(log.output))

    def test_source_health_dispatch_is_available_for_founder_workbench(self):
        result=self.service.dispatch('/sources/health',{},self.principal,str(uuid.uuid4()))
        self.assertTrue(result['sources']);self.assertEqual(result['_dataState'],'partial')

    def test_legacy_receipts_recheck_capability_from_definition_lineage(self):
        from rafii_control.auth import ControlError
        ref=str(uuid.uuid4())
        receipt=dict(id=ref,operator_id=self.principal['operator']['user_id'],normalized_query={},source_versions={},metric_versions={'check_failures':1},expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),execution_state='local_synthetic',data_state='measured',result_rows=[])
        self.store.read=lambda kind,identifier=None:[receipt] if kind=='receipt' else []
        self.service.synthetic=True;self.principal['operator']['capabilities'].remove('engineering.read')
        with self.assertRaises(ControlError):self.service.authorized_receipt(ref,self.principal)
