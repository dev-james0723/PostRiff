"""Verifier-only decision work and immutable native transport receipts.

Cloud persistence cannot launch a native turn. The owning host must still pass
recovery.py/native_transport.py fences and produce a genuine native guard receipt.
"""
import json
import math
import re

from .agent_team_decision import HASH, decision_effect_key, digest, invalid, validate_question
from .agent_team_registry import CloudMissionRegistry, TABLE, COLUMNS

RECEIPT_FIELDS={'decisionKey','registrationSha256','executionBindingSha256','checkpointSha256','attemptId','generation',
                'nativeGuardRef','resumeRequestId','turnRequestId','turnId','executionState','reason','receiptSha256',
                'source','nativeGuardVerified','observedAt'}
STATES={'blocked','unknown','resumed','turn_started','wait','needs_human'}
DECISION_FIELDS=('decisionKey','effectKey','missionId','scopeVersion','callRunId','questionVersion','choice',
                 'authenticatedUserId','workspaceId','questionSha256','authorizationSha256','registrationSha256',
                 'executionBindingSha256','completionRequirementRefs','attendedCallId')


class NativeDecisionBridge:
    def __init__(self,service):
        self.service=service;cfg=service.james_daily_call.cfg
        self.actor_id=cfg.user_id;self.workspace_id=cfg.workspace_id
        self.registry=CloudMissionRegistry(service.connection_factory,self.actor_id,self.workspace_id,service.clock)

    def _decision(self,cur,decision_key=None):
        conditions=' AND d.decision_key=%s' if decision_key is not None else " AND d.execution_state='recorded'"
        parameters=(self.actor_id,self.workspace_id)+((decision_key,) if decision_key is not None else ())
        cur.execute("SELECT d.decision_key,d.effect_key,d.mission_id,d.scope_version,d.call_run_id::text,d.question_version,d.choice,d.authenticated_user_id::text,d.workspace_id::text,d.question_sha256,d.authorization_sha256,d.registration_sha256,d.execution_binding_sha256,d.completion_requirement_refs,d.attended_call_id::text,r.context,h.evidence_sha256,m.evidence_sha256,m.playback_ack_sha256,extract(epoch from d.received_at),d.execution_state FROM public.pr_agent_team_decisions d JOIN public.pr_james_daily_call_runs r ON r.id=d.call_run_id JOIN public.pr_phone_calls c ON c.id=d.attended_call_id JOIN public.pr_agent_team_call_evidence h ON h.call_id=c.id AND h.provider=c.provider AND h.evidence_kind='human' AND h.source='signed_provider_human_detection' JOIN public.pr_agent_team_call_evidence m ON m.call_id=c.id AND m.provider=c.provider AND m.evidence_kind='media' AND m.source='authenticated_bidirectional_media' WHERE d.authenticated_user_id=%s AND d.workspace_id=%s AND r.user_id=d.authenticated_user_id AND r.workspace_id=d.workspace_id AND r.origin='agent_team_report' AND c.user_id=d.authenticated_user_id AND c.workspace_id=d.workspace_id AND c.provider='twilio' AND c.state='completed' AND c.direction='outbound' AND c.destination_ref='james_env' AND c.reason_key='james_daily:'||d.call_run_id::text AND m.input_frames>0 AND m.output_frames>0 AND m.playback_ack_sha256 ~ '^[0-9a-f]{64}$'"+conditions+' ORDER BY d.received_at LIMIT 1',parameters)
        row=cur.fetchone()
        if not row:return None
        decision=dict(zip(DECISION_FIELDS,row[:15]));context=row[15] or {}
        report=context.get('agentTeamReport') or {}
        question=validate_question(context.get('agentTeamDecisionQuestion'),actor_id=self.actor_id,workspace_id=self.workspace_id,
            mission_id=decision['missionId'],report_id=report.get('reportId'),report_version=report.get('version'),now=float(row[19]))
        if (report.get('missionId')!=question['missionId'] or question['reportKey']!='agent-team:v1:'+str(report.get('workday'))+':half_day'
                or decision['decisionKey']!=decision['effectKey'] or decision['effectKey']!=decision_effect_key(decision['callRunId'],question)):
            raise invalid('native_decision_binding_mismatch')
        for name in ('scopeVersion','questionVersion','questionSha256','authorizationSha256','registrationSha256','completionRequirementRefs'):
            if decision[name]!=question[name]:raise invalid('native_decision_binding_mismatch')
        if decision['executionBindingSha256']!=question['executionBindingSha256']:raise invalid('native_decision_binding_mismatch')
        if any(not isinstance(value,str) or not HASH.fullmatch(value) for value in row[16:19]):raise invalid('native_decision_attendance_unverified')
        decision.update(humanEvidenceId=row[16],mediaEvidenceId=row[17],playbackAckSha256=row[18],recordedAt=float(row[19]))
        return decision,question,row[20]

    def work(self):
        with self.service.connection_factory() as db,db.cursor() as cur:record=self._decision(cur)
        if record is None:return {'state':'idle','nativeExecutionState':'not_dispatched'}
        decision,question,_=record
        return {'state':'ready','decision':decision,'question':question,'nativeExecutionState':'not_dispatched',
                'requiredGuard':'fresh_owning_native_transport_attestation'}

    def receipt(self,document):
        if not isinstance(document,dict) or set(document)!=RECEIPT_FIELDS:raise invalid('native_receipt_invalid')
        if document['source']!='kynlo_orc_native_transport' or document['nativeGuardVerified'] is not True:raise invalid('native_guard_unverified')
        state=document['executionState']
        if state not in STATES:raise invalid('native_receipt_invalid')
        now=self.service.clock();observed=document['observedAt']
        if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=now-observed<=30:raise invalid('native_receipt_stale')
        for name in ('registrationSha256','executionBindingSha256','receiptSha256'):
            if not isinstance(document[name],str) or not HASH.fullmatch(document[name]):raise invalid('native_receipt_invalid')
        for name in ('decisionKey','nativeGuardRef','reason'):
            if not isinstance(document[name],str) or not 1<=len(document[name])<=2048 or '\0' in document[name]:raise invalid('native_receipt_invalid')
        request_id=document['resumeRequestId']
        if request_id is None:
            if state!='unknown':raise invalid('native_receipt_invalid')
        elif not isinstance(request_id,str) or not 1<=len(request_id)<=200 or '\0' in request_id:raise invalid('native_receipt_invalid')
        if not re.fullmatch(r'team-decision:[0-9a-f]{64}',document['decisionKey']):raise invalid('native_receipt_invalid')
        started=state in ('resumed','turn_started','unknown')
        if started:
            if not isinstance(document['checkpointSha256'],str) or not HASH.fullmatch(document['checkpointSha256']):raise invalid('native_checkpoint_required')
            if any(type(document[name]) is not int or document[name]<1 for name in ('attemptId','generation')):raise invalid('native_fence_required')
        elif any(document[name] is not None for name in ('checkpointSha256','attemptId','generation','turnRequestId','turnId')):raise invalid('native_receipt_invalid')
        if state=='turn_started':
            for name in ('turnRequestId','turnId'):
                if not isinstance(document[name],str) or not 1<=len(document[name])<=200 or '\0' in document[name]:raise invalid('native_turn_receipt_required')
        elif state=='resumed':
            if document['turnId'] is not None:raise invalid('native_receipt_invalid')
            if document['turnRequestId'] is not None and (not isinstance(document['turnRequestId'],str) or not 1<=len(document['turnRequestId'])<=200 or '\0' in document['turnRequestId']):raise invalid('native_receipt_invalid')
        elif state=='unknown':
            for name in ('turnRequestId','turnId'):
                if document[name] is not None and (not isinstance(document[name],str) or not 1<=len(document[name])<=200 or '\0' in document[name]):raise invalid('native_receipt_invalid')
        expected_hash=digest({key:value for key,value in document.items() if key!='receiptSha256'})
        if document['receiptSha256']!=expected_hash:raise invalid('native_receipt_digest_mismatch')
        with self.service.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(document['decisionKey'],))
            record=self._decision(cur,document['decisionKey'])
            if record is None:raise invalid('native_decision_unavailable')
            decision,question,execution_state=record
            if (decision['registrationSha256'],decision['executionBindingSha256'])!=(document['registrationSha256'],document['executionBindingSha256']):raise invalid('native_decision_binding_mismatch')
            if (started and decision['choice']!='continue') or (state in ('wait','needs_human') and state!=decision['choice']):raise invalid('native_decision_choice_mismatch')
            cur.execute('SELECT document FROM public.pr_agent_team_native_receipts WHERE decision_key=%s AND (receipt_sha256=%s OR resume_request_id=%s)',
                        (document['decisionKey'],expected_hash,document['resumeRequestId']))
            old=cur.fetchone()
            if old:
                if old[0]!=document:raise invalid('native_receipt_conflict')
                return {'state':'recorded','replayed':True,'decisionKey':document['decisionKey'],'receiptSha256':expected_hash,'executionState':state}
            if execution_state!='recorded':raise invalid('native_decision_already_consumed')
            cur.execute('SELECT '+COLUMNS+' FROM '+TABLE+' WHERE mission_id=%s AND actor_id=%s AND workspace_id=%s ORDER BY ordinal DESC,observed_at DESC LIMIT 1',
                        (decision['missionId'],self.actor_id,self.workspace_id))
            projection=cur.fetchone()
            if not projection:raise invalid('native_registry_unavailable')
            registration,execution=self.registry._decode(projection)
            if (registration.fingerprint,execution.fingerprint)!=(document['registrationSha256'],document['executionBindingSha256']) or projection[7]['nativeGuardRef']!=document['nativeGuardRef']:raise invalid('native_guard_binding_mismatch')
            cur.execute('INSERT INTO public.pr_agent_team_native_receipts(decision_key,resume_request_id,receipt_sha256,execution_state,document,observed_at) VALUES(%s,%s,%s,%s,%s::jsonb,to_timestamp(%s))',
                        (document['decisionKey'],document['resumeRequestId'],expected_hash,state,json.dumps(document),observed))
            if state!='blocked':
                cur.execute("UPDATE public.pr_agent_team_decisions SET execution_state='consumed' WHERE decision_key=%s AND execution_state='recorded'",(document['decisionKey'],))
            db.commit()
        return {'state':'recorded','replayed':False,'decisionKey':document['decisionKey'],'receiptSha256':expected_hash,'executionState':state}
