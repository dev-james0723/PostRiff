"""Synthetic registry/native receipts only; no provider call or native execution."""
from dataclasses import asdict, replace
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from agent_team.recovery import NativeOwner, RecoveryStore, Registration
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_team_decision import digest
from postriff_phase2.agent_team_registry import CloudMissionRegistry, validate_projection
from postriff_phase2.agent_team_native import NativeDecisionBridge
from postriff_phase2.james_agent_team import PREFIX, route

USER='11111111-1111-4111-8111-111111111111'
WORKSPACE='22222222-2222-4222-8222-222222222222'
NOW=1791313320.0
VALUES={'JAMES_AGENT_TEAM_ENABLED':'1','JAMES_AGENT_TEAM_VERIFIER_TOKEN':'v'*40,
        'JAMES_AGENT_TEAM_OBSERVER_TOKEN':'o'*40,'JAMES_AGENT_TEAM_READER_TOKEN':'r'*40}


def registered():
    registration=Registration('real-contract-synthetic-mission','/synthetic/project','/synthetic/worktree',USER,'codex',
        NativeOwner('synthetic-owner','/synthetic/owner.sock',42,'synthetic-process-start'),
        'task-1','root-1','phase-1','approved-scope-evidence','b'*64,'approved-v3',
        ('驗證原有任务','preserve concurrent edits'),('synthetic-side-effect-ledger',))
    store=RecoveryStore(':memory:');store.register(registration);execution=store.current_execution(registration);store.close()
    return registration,execution


def projection(registration=None,execution=None,**attestation_changes):
    if registration is None:registration,execution=registered()
    attestation={'schemaVersion':1,'source':'kynlo_orc_owner','evidenceRef':'synthetic-owner-observation',
        'nativeGuardRef':'synthetic-guard-attestation','nativeGuardVerified':True,'observedAt':NOW,
        'registrationSha256':registration.fingerprint,'executionSha256':execution.fingerprint,
        'authorizationSha256':registration.authorization_sha256,'owner':asdict(execution.owner),**attestation_changes}
    return {'schemaVersion':1,'actorId':USER,'workspaceId':WORKSPACE,'registration':asdict(registration),
            'registrationSha256':registration.fingerprint,'execution':asdict(execution),
            'executionSha256':execution.fingerprint,'nativeAttestation':attestation}


def json_document(value):return json.loads(json.dumps(value))


def row_for(document):
    value=json_document(document)
    return (value['actorId'],value['workspaceId'],value['registrationSha256'],value['executionSha256'],
            value['execution']['ordinal'],value['registration'],value['execution'],value['nativeAttestation'],digest(value['nativeAttestation']))


class RegistryDB:
    def __init__(self):self.row=None;self.result=None;self.queries=[];self.commits=0
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def commit(self):self.commits+=1
    def execute(self,sql,parameters):
        self.queries.append((sql,parameters))
        if 'pg_advisory_xact_lock' in sql:self.result=None
        elif sql.startswith('SELECT DISTINCT mission_id'):self.result=[(self.row[5]['mission_id'],)] if self.row else []
        elif sql.startswith('SELECT actor_id'):self.result=self.row
        elif sql.startswith('INSERT INTO public.pr_agent_team_mission_registry'):
            candidate=(parameters[1],parameters[2],parameters[3],parameters[4],parameters[5],
                       json.loads(parameters[6]),json.loads(parameters[7]),json.loads(parameters[8]),parameters[9])
            duplicate=self.row==candidate;self.row=candidate;self.result=None if duplicate else (parameters[9],)
        else:raise AssertionError('Unrecognized registry query')
    def fetchone(self):return self.result
    def fetchall(self):return self.result


class MissionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registration,self.execution=registered()
        self.document=json_document(projection(self.registration,self.execution))
        self.db=RegistryDB();self.registry=CloudMissionRegistry(lambda:self.db,USER,WORKSPACE,lambda:NOW)

    def test_hashes_recomputed_with_recovery_canonical_algorithm_including_unicode(self):
        registration,execution,_=validate_projection(self.document,actor_id=USER,workspace_id=WORKSPACE,now=NOW)
        self.assertEqual(registration.fingerprint,self.registration.fingerprint)
        self.assertEqual(execution.fingerprint,self.execution.fingerprint)
        for name in ('registrationSha256','executionSha256'):
            with self.assertRaises(AlphaError):validate_projection({**self.document,name:'f'*64},actor_id=USER,workspace_id=WORKSPACE,now=NOW)

    def test_unknown_fields_owner_false_guard_and_stale_attestations_rejected(self):
        bad=[{**self.document,'command':'resume anything'},
             {**self.document,'registration':{**self.document['registration'],'command':'anything'}}]
        for changes in ({'nativeGuardVerified':False},{'nativeGuardVerified':1},{'source':'ordinary_observer'},
                        {'observedAt':NOW-31},{'observedAt':NOW+1},{'owner':{**asdict(self.execution.owner),'pid':43}},
                        {'authorizationSha256':'f'*64},{'unexpected':'field'}):
            bad.append({**self.document,'nativeAttestation':{**self.document['nativeAttestation'],**changes}})
        for document in bad:
            with self.subTest(fields=set(document)),self.assertRaises(AlphaError):self.registry.put(document)
        self.assertEqual(self.db.queries,[])

    def test_native_principal_cannot_cross_bind(self):
        for changes in ({'actorId':WORKSPACE},{'workspaceId':USER}):
            with self.assertRaises(AlphaError):self.registry.put({**self.document,**changes})
        self.assertEqual(self.db.queries,[])

    def test_projection_persists_replays_and_detects_changed_registration(self):
        first=self.registry.put(self.document);second=self.registry.put(self.document)
        self.assertFalse(first['replayed']);self.assertTrue(second['replayed'])
        self.assertEqual(first['nativeExecutionState'],'not_dispatched')
        changed=replace(self.registration,scope_version='unapproved-new-scope')
        store=RecoveryStore(':memory:');store.register(changed);execution=store.current_execution(changed);store.close()
        with self.assertRaises(AlphaError) as raised:self.registry.put(json_document(projection(changed,execution)))
        self.assertEqual(raised.exception.code,'decision_registration_changed')
        self.assertEqual(self.db.row[2],self.registration.fingerprint)

    def test_origin_and_execution_lineage_cannot_be_replaced(self):
        for execution in (replace(self.execution,continuity_revision=1),replace(self.execution,created_at=NOW)):
            with self.assertRaises(AlphaError):self.registry.put(json_document(projection(self.registration,execution)))
        self.registry.put(self.document)
        execution=replace(self.execution,ordinal=1,predecessor_sha256='f'*64,checkpoint_sha256='c'*64,attempt_id=1)
        with self.assertRaises(AlphaError):self.registry.put(json_document(projection(self.registration,execution)))

    def test_question_resolves_report_evidence_mission_and_fresh_exact_persisted_authority(self):
        self.registry.put(self.document)
        report={'fingerprint':'a'*64,'version':2,'period':{'key':'agent-team:v1:2026-10-06:half_day'},
                'evidence':[{'missionId':self.registration.mission_id,'id':'c'*64}]}
        question=self.registry.for_report(report).document(now=NOW)
        self.assertEqual(question['missionId'],self.registration.mission_id)
        self.assertEqual(question['registrationSha256'],self.registration.fingerprint)
        self.assertEqual(question['executionBindingSha256'],self.execution.fingerprint)
        with self.assertRaises(AlphaError):self.registry.for_report({**report,'evidence':[]})
        with self.assertRaises(AlphaError):self.registry.for_report(report,'unregistered-mission')
        self.registry.clock=lambda:NOW+31
        with self.assertRaises(AlphaError):self.registry.for_report(report)

    def test_machine_observer_and_reader_cannot_upload_registry_or_fetch_native_work(self):
        service=SimpleNamespace(james_daily_call=SimpleNamespace(cfg=SimpleNamespace(user_id=USER,workspace_id=WORKSPACE)),
            connection_factory=MagicMock(),clock=lambda:NOW)
        app=SimpleNamespace(_runtime=lambda:service,_json=lambda _s,_c,value,**_kw:value)
        raw=json.dumps(self.document).encode()
        for token in ('o'*40,'r'*40):
            for path,method in (('/mission-registry','POST'),('/native-work','GET'),('/native-receipts','POST'),('/decisions/33333333-3333-4333-8333-333333333333','GET')):
                environ={'HTTP_AUTHORIZATION':'Bearer '+token,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
                with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError) as raised:route(app,environ,MagicMock(),method,PREFIX+path)
                self.assertEqual(raised.exception.status,401)
        service.connection_factory.assert_not_called()


class NativeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.registration,self.execution=registered()
        self.document=projection(self.registration,self.execution)
        self.cur=MagicMock();self.db=MagicMock();self.db.__enter__.return_value=self.db
        self.db.cursor.return_value.__enter__.return_value=self.cur
        service=SimpleNamespace(james_daily_call=SimpleNamespace(cfg=SimpleNamespace(user_id=USER,workspace_id=WORKSPACE)),
                               connection_factory=lambda:self.db,clock=lambda:NOW)
        self.bridge=NativeDecisionBridge(service)
        self.decision={'decisionKey':'team-decision:'+'a'*64,'missionId':self.registration.mission_id,
            'registrationSha256':self.registration.fingerprint,'executionBindingSha256':self.execution.fingerprint,'choice':'continue'}
        self.bridge._decision=MagicMock(return_value=(self.decision,{},'recorded'))

    def receipt(self,**changes):
        value={'decisionKey':self.decision['decisionKey'],'registrationSha256':self.registration.fingerprint,
            'executionBindingSha256':self.execution.fingerprint,'checkpointSha256':'c'*64,'attemptId':1,'generation':1,
            'nativeGuardRef':'synthetic-guard-attestation','resumeRequestId':'resume-request-1','turnRequestId':'turn-request-1',
            'turnId':'turn-1','executionState':'turn_started','reason':'native_turn_started',
            'source':'kynlo_orc_native_transport','nativeGuardVerified':True,'observedAt':NOW,**changes}
        value['receiptSha256']=digest(value);return value

    def test_receipt_never_accepts_machine_claim_without_exact_native_guard_fence_and_binding(self):
        for changes in ({'nativeGuardVerified':False},{'nativeGuardVerified':1},{'source':'observer'},
                        {'observedAt':NOW-31},{'attemptId':0},{'generation':True},
                        {'checkpointSha256':None},{'turnId':None},{'receiptSha256':'f'*64}):
            value=self.receipt(**changes)
            if 'receiptSha256' in changes:value['receiptSha256']=changes['receiptSha256']
            with self.assertRaises(AlphaError):self.bridge.receipt(value)
        self.db.commit.assert_not_called()

    def test_fresh_exact_native_receipt_is_immutable_and_consumes_decision(self):
        self.cur.fetchone.side_effect=[None,row_for(self.document)]
        result=self.bridge.receipt(self.receipt())
        self.assertEqual(result['executionState'],'turn_started');self.assertFalse(result['replayed'])
        self.assertTrue(any('SET execution_state=\'consumed\'' in call.args[0] for call in self.cur.execute.call_args_list))
        self.db.commit.assert_called_once()

    def test_unknown_effect_consumes_without_manufacturing_rpc_or_turn_identity(self):
        self.cur.fetchone.side_effect=[None,row_for(self.document)]
        result=self.bridge.receipt(self.receipt(executionState='unknown',reason='native_effect_unknown',resumeRequestId=None,turnRequestId=None,turnId=None))
        self.assertEqual(result['executionState'],'unknown')
        self.assertTrue(any('SET execution_state=\'consumed\'' in call.args[0] for call in self.cur.execute.call_args_list))

    def test_changed_guard_registration_and_noncontinue_choice_never_persist_native_receipt(self):
        for changes in ({'nativeGuardRef':'other-guard'},{'registrationSha256':'f'*64}):
            self.cur.fetchone.side_effect=[None,row_for(self.document)]
            with self.assertRaises(AlphaError):self.bridge.receipt(self.receipt(**changes))
        self.decision['choice']='wait';self.cur.fetchone.side_effect=[]
        with self.assertRaises(AlphaError):self.bridge.receipt(self.receipt())
        self.assertFalse(any(call.args[0].startswith('INSERT INTO public.pr_agent_team_native_receipts') for call in self.cur.execute.call_args_list))

    def test_native_queue_is_read_only_and_never_claims_execution(self):
        self.bridge._decision.return_value=None
        self.assertEqual(self.bridge.work(),{'state':'idle','nativeExecutionState':'not_dispatched'})
        self.bridge._decision.return_value=(self.decision,{},'recorded')
        result=self.bridge.work()
        self.assertEqual(result['state'],'ready');self.assertEqual(result['nativeExecutionState'],'not_dispatched')
        self.db.commit.assert_not_called()


if __name__=='__main__':unittest.main()
