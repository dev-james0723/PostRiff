"""Synthetic registry/callback/DB evidence only. No real attended call or dispatch."""
from dataclasses import replace
from datetime import datetime
import base64
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,Mock,patch
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from agent_team.recovery import NativeOwner,RecoveryStore,Registration
from postriff_phase2.agent_team_decision import (
    build_question,validate_question,decision_effect_key,record_verified_human_answer,
    record_verified_bidirectional_media,digest,
)
from postriff_phase2.james_agent_team import TeamStore
from postriff_phase2.james_daily_call import DailyCallService,TEAM_REPORT_ZONE
from postriff_phase2.phone import http
from postriff_phase2.phone.agent_team_media import TeamMediaEvidence,non_silent_frames
from postriff_phase2.phone.providers.twilio import TwilioMediaTransport

USER='11111111-1111-4111-8111-111111111111'
WORKSPACE='22222222-2222-4222-8222-222222222222'
RUN='33333333-3333-4333-8333-333333333333'
CALL='44444444-4444-4444-8444-444444444444'
NOW=datetime(2026,10,5,17,2,tzinfo=ZoneInfo(TEAM_REPORT_ZONE)).timestamp()
REPORT='a'*64
VALUES={'JAMES_DAILY_CALL_USER_ID':USER,'JAMES_DAILY_CALL_WORKSPACE_ID':WORKSPACE,
        'JAMES_DAILY_CALL_TIMEZONE':TEAM_REPORT_ZONE,'JAMES_AGENT_TEAM_CALL_ENABLED':'1'}


def registration():
    return Registration('actual-mission-1','/synthetic/project','/synthetic/worktree',USER,'codex',
                        NativeOwner('synthetic-owner','/synthetic/owner.sock',42,'synthetic-process-start'),
                        'task-1','root-1','phase-1','approved-scope-evidence','b'*64,'approved-scope-v3',
                        ('functional criterion','preserve uncommitted work'),('synthetic-side-effects',))


class DecisionDB:
    def __init__(self,context,attendance=None,spoken=None):
        self.context=context;self.actor=USER;self.workspace=WORKSPACE;self.origin='agent_team_report'
        self.attendance=[(CALL,'twilio','completed',True,True,True,True,True,'c'*64,'d'*64)] if attendance is None else attendance
        self.records={};self.result=None;self.queries=[];self.commits=0
        self.spoken=spoken

    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def commit(self):self.commits+=1

    def execute(self,sql,parameters):
        self.queries.append((sql,parameters))
        if 'SELECT context' in sql:self.result=(self.context,self.actor,self.workspace,self.origin,CALL,None)
        elif 'FROM public.pr_phone_calls c' in sql:self.result=self.attendance
        elif sql.startswith('SELECT choice,call_id::text,candidate_sha256'):self.result=self.spoken
        elif 'pg_advisory_xact_lock' in sql:self.result=None
        elif sql.startswith('INSERT INTO public.pr_agent_team_decisions'):
            key=parameters[0]
            if key in self.records:self.result=None
            else:self.records[key]=tuple(parameters[1:]);self.result=(key,)
        elif sql.startswith('SELECT mission_id'):self.result=next(iter(self.records.values()),None)
        else:raise AssertionError('Unknown decision query')

    def fetchone(self):return self.result
    def fetchall(self):return self.result


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.registry=RecoveryStore(':memory:');self.reg=registration();self.registry.register(self.reg)
        self.question=self.build();self.doc=self.question.document(now=NOW)
        self.context={'agentTeamReport':{'missionId':self.reg.mission_id,'reportId':REPORT,'version':12,'kind':'half_day','workday':'2026-10-05'},
                      'agentTeamDecisionQuestion':self.doc}

    def tearDown(self):self.registry.close()

    def build(self,**changes):
        values={'actor_id':USER,'workspace_id':WORKSPACE,'report_id':REPORT,'report_version':12,
                'report_key':'agent-team:v1:2026-10-05:half_day','prompt':'Continue the already approved mission?',
                'now':NOW,'expires_at':NOW+900,**changes}
        return build_question(self.registry,self.reg,**values)

    def request(self,**changes):
        return {'decisionKey':'arbitrary-client-key','missionId':self.reg.mission_id,'scopeVersion':self.reg.scope_version,
                'callRunId':RUN,'questionVersion':self.doc['questionVersion'],'choice':'continue',**changes}

    def test_question_requires_existing_exact_registration_and_current_execution(self):
        unregistered=RecoveryStore(':memory:')
        try:
            with self.assertRaises(AlphaError):
                build_question(unregistered,self.reg,actor_id=USER,workspace_id=WORKSPACE,report_id=REPORT,
                    report_version=12,report_key='agent-team:v1:2026-10-05:half_day',prompt='Continue?',now=NOW,expires_at=NOW+900)
        finally:unregistered.close()
        self.registry.db.execute('UPDATE recovery_execution_bindings SET digest=?',('f'*64,))
        with self.assertRaises(AlphaError):self.question.document(now=NOW)

    def test_scope_question_and_completion_requirements_are_independent_from_report_version(self):
        self.assertEqual(self.doc['scopeVersion'],'approved-scope-v3')
        newer=self.build(report_id='e'*64,report_version=13).document(now=NOW)
        self.assertEqual(newer['questionVersion'],self.doc['questionVersion'])
        self.assertNotEqual(newer['questionSha256'],self.doc['questionSha256'])
        self.assertEqual(self.doc['completionRequirementRefs'],[hashlib.sha256(x.encode()).hexdigest() for x in self.reg.acceptance_criteria])
        self.assertEqual(self.doc['executionBindingSha256'],self.registry.current_execution(self.reg).fingerprint)

    def test_mutated_missing_or_expired_authority_is_rejected(self):
        for changed in ({**self.doc,'completionRequirementRefs':[]},{**self.doc,'scopeVersion':'report-12'},
                        {**self.doc,'workspaceId':RUN},{**self.doc,'command':'execute arbitrary task'}):
            with self.assertRaises(AlphaError):validate_question(changed,now=NOW)
        with self.assertRaises(AlphaError):validate_question(self.doc,now=NOW+901)
        with self.assertRaises(AlphaError):validate_question(self.doc,now=NOW-1)

    def test_client_cannot_supply_authority_or_choose_actor(self):
        factory=Mock()
        for extra in ({'authorizationSha256':'f'*64},{'actorId':USER},{'workspaceId':WORKSPACE}):
            with self.assertRaises(AlphaError):TeamStore(factory).decision(self.request(**extra),USER,WORKSPACE,NOW)
        factory.assert_not_called()

    def test_completed_run_without_trusted_question_or_attendance_stays_blocked(self):
        for context,attendance in (({'agentTeamReport':self.context['agentTeamReport']},None),(self.context,[])):
            db=DecisionDB(context,attendance)
            result=TeamStore(lambda:db).decision(self.request(),USER,WORKSPACE,NOW)
            self.assertEqual((result['state'],result['executionState']),('blocked','not_dispatched'))
            self.assertEqual(db.records,{});self.assertEqual(db.commits,0)

    def test_real_provider_completed_human_and_bidirectional_evidence_are_all_required(self):
        positive=(CALL,'twilio','completed',True,True,True,True,True,'c'*64,'d'*64)
        for index,value in ((1,'fake'),(2,'answered'),(3,False),(4,False),(5,False),(6,False),(7,False),(8,None),(9,None)):
            attendance=list(positive);attendance[index]=value
            db=DecisionDB(self.context,[tuple(attendance)])
            result=TeamStore(lambda:db).decision(self.request(),USER,WORKSPACE,NOW)
            self.assertEqual(result['reason'],'attended_call_unverified');self.assertEqual(db.records,{})

    def test_exact_question_choice_records_once_and_arbitrary_client_keys_cannot_bypass(self):
        db=DecisionDB(self.context);store=TeamStore(lambda:db)
        first=store.decision(self.request(),USER,WORKSPACE,NOW)
        second=store.decision(self.request(decisionKey='another-client-key'),USER,WORKSPACE,NOW)
        stable=decision_effect_key(RUN,self.doc)
        self.assertEqual(first['decisionKey'],stable);self.assertEqual(second['effectKey'],stable)
        self.assertFalse(first['replayed']);self.assertTrue(second['replayed'])
        self.assertEqual(len(db.records),1)
        self.assertEqual(first['executionState'],'not_dispatched')
        with self.assertRaises(AlphaError) as raised:
            store.decision(self.request(decisionKey='third-key',choice='wait'),USER,WORKSPACE,NOW)
        self.assertEqual(raised.exception.code,'decision_choice_conflict');self.assertEqual(len(db.records),1)
        sql=next(sql for sql,_ in db.queries if sql.startswith('INSERT'))
        self.assertIn('ON CONFLICT(call_run_id,mission_id,scope_version,question_version)',sql)

    def test_authenticated_session_confirms_same_spoken_choice_and_same_attended_call(self):
        candidate=('continue',CALL,'e'*64)
        db=DecisionDB(self.context,spoken=candidate)
        result=TeamStore(lambda:db).decision(self.request(),USER,WORKSPACE,NOW)
        self.assertEqual(result['decisionSource'],'authenticated_session_confirmed_phone_choice')
        self.assertEqual(result['spokenChoiceSha256'],'e'*64)
        self.assertEqual(result['executionState'],'not_dispatched')
        self.assertEqual(next(iter(db.records.values()))[-1],'e'*64)
        for candidate in (('wait',CALL,'e'*64),('continue',RUN,'e'*64)):
            db=DecisionDB(self.context,spoken=candidate)
            if candidate[0]=='wait':
                with self.assertRaises(AlphaError) as raised:TeamStore(lambda:db).decision(self.request(),USER,WORKSPACE,NOW)
                self.assertEqual(raised.exception.code,'spoken_choice_confirmation_mismatch')
            else:
                result=TeamStore(lambda:db).decision(self.request(),USER,WORKSPACE,NOW)
                self.assertEqual(result['reason'],'attended_call_unverified')
            self.assertEqual(db.records,{})

    def test_mission_scope_question_actor_and_workspace_cannot_cross_bind(self):
        for changes in ({'scopeVersion':'12'},{'questionVersion':'e'*64},{'missionId':'different-mission'}):
            db=DecisionDB(self.context)
            with self.assertRaises(AlphaError):TeamStore(lambda:db).decision(self.request(**changes),USER,WORKSPACE,NOW)
            self.assertEqual(db.records,{})
        for actor,workspace in ((RUN,WORKSPACE),(USER,RUN)):
            db=DecisionDB(self.context)
            with self.assertRaises(AlphaError):TeamStore(lambda:db).decision(self.request(),actor,workspace,NOW)
            self.assertEqual(db.records,{})

    def test_call_report_accepts_internal_question_capability_and_rejects_raw_dict(self):
        service=DailyCallService(SimpleNamespace(clock=lambda:NOW),VALUES)
        service._require_base=Mock();service._start_context=Mock(side_effect=lambda _slot,_origin,context:{'id':RUN,'context':context,'replayed':False})
        briefing={'kind':'half_day','verified':True,'timeZone':TEAM_REPORT_ZONE,'cutoffLocalTime':'17:00',
                  'generatedAt':NOW,'summary':'Acceptance pending.','evidenceRefs':['e'*64]}
        with self.assertRaises(AlphaError) as raised:
            service.call_report(REPORT,self.reg.mission_id,'2026-10-05',12,briefing,decision_question=self.doc)
        self.assertEqual(raised.exception.code,'decision_question_untrusted');service._start_context.assert_not_called()
        service.call_report(REPORT,self.reg.mission_id,'2026-10-05',12,briefing,decision_question=self.question)
        self.assertEqual(service._start_context.call_args.args[2]['agentTeamDecisionQuestion'],self.doc)
        with self.assertRaises(AlphaError):
            service.call_report(REPORT,'different-mission','2026-10-05',12,briefing,decision_question=self.question)

    def synthetic_call(self,**changes):
        return {'id':CALL,'user_id':USER,'workspace_id':WORKSPACE,'provider':'twilio','provider_call_ref':'CA'+'1'*32,
                'direction':'outbound','destination_ref':'james_env','reason_key':'james_daily:'+RUN,'state':'ringing',**changes}

    def evidence_cursor(self,kind='human'):
        cur=MagicMock();call=self.synthetic_call()
        evidence=digest(['provider-human:v1',CALL,'twilio',call['provider_call_ref'],'human','amd_not_bypassed']) if kind=='human' else 'f'*64
        old=('twilio','signed_provider_human_detection',evidence,None,None,None) if kind=='human' else ('twilio','authenticated_bidirectional_media',evidence,1,1,'e'*64)
        cur.fetchone.side_effect=[(self.context,USER,WORKSPACE,'agent_team_report'),old]
        return cur

    def test_private_callback_receipt_never_accepts_fake_unknown_or_amd_bypass(self):
        provider=SimpleNamespace(name='twilio',real=True)
        for answered,bypass,real in (('unknown',False,True),('machine',False,True),('human',True,True),('human',False,False)):
            cur=MagicMock();provider.real=real
            self.assertFalse(record_verified_human_answer(cur,self.synthetic_call(),provider=provider,
                call_ref='CA'+'1'*32,answered_by=answered,amd_bypassed=bypass,observed_at=NOW))
            cur.execute.assert_not_called()
        provider.real=True;cur=self.evidence_cursor()
        self.assertTrue(record_verified_human_answer(cur,self.synthetic_call(),provider=provider,
            call_ref='CA'+'1'*32,answered_by='human',amd_bypassed=False,observed_at=NOW))
        self.assertTrue(any(query.args[0].startswith('INSERT INTO public.pr_agent_team_call_evidence') for query in cur.execute.call_args_list))

    def test_bidirectional_port_requires_actual_positive_both_directions_and_exact_call_ref(self):
        cur=MagicMock()
        self.assertFalse(record_verified_bidirectional_media(cur,self.synthetic_call(),call_ref='wrong',
            input_frames=1,output_frames=1,observed_at=NOW,evidence_sha256='f'*64,playback_ack_sha256='e'*64))
        cur.execute.assert_not_called()
        cur=MagicMock();cur.fetchone.return_value=(self.context,USER,WORKSPACE,'agent_team_report')
        with self.assertRaises(AlphaError):record_verified_bidirectional_media(cur,self.synthetic_call(),call_ref='CA'+'1'*32,
            input_frames=1,output_frames=0,observed_at=NOW,evidence_sha256='f'*64)
        self.assertFalse(any(x.args[0].startswith('INSERT') for x in cur.execute.call_args_list))
        cur=self.evidence_cursor('media')
        self.assertTrue(record_verified_bidirectional_media(cur,self.synthetic_call(),call_ref='CA'+'1'*32,
            input_frames=1,output_frames=1,observed_at=NOW,evidence_sha256='f'*64,playback_ack_sha256='e'*64))

    def test_twilio_hook_is_after_signature_identity_checks_and_bypass_has_no_evidence(self):
        for signature_ok,bypass in ((False,False),(True,True),(True,False)):
            cur=self.evidence_cursor();db=MagicMock();db.cursor.return_value.__enter__.return_value=cur
            factory=MagicMock();factory.return_value.__enter__.return_value=db
            provider=SimpleNamespace(name='twilio',real=True,account='AC'+'2'*32,
                verify_webhook=Mock(return_value=signature_ok),answer_xml=Mock(return_value='<Response/>'))
            service=SimpleNamespace(provider=provider,hosted=SimpleNamespace(connection_factory=factory),clock=lambda:NOW,
                config=SimpleNamespace(values={'JAMES_DAILY_CALL_ACCEPTANCE_BYPASS_AMD':'1' if bypass else '0'},enabled=lambda _flag:True))
            parameters={'CallSid':['CA'+'1'*32],'AccountSid':['AC'+'2'*32],'AnsweredBy':['human']}
            with patch('postriff_phase2.phone.http.store.call',return_value=self.synthetic_call()),patch('postriff_phase2.phone.http.store.set_state'):
                if not signature_ok:
                    with self.assertRaises(AlphaError):http.answer(service,CALL,'synthetic-url',parameters,'synthetic-signature')
                    factory.assert_not_called()
                else:
                    http.answer(service,CALL,'synthetic-url',parameters,'synthetic-signature')
                    inserts=[x for x in cur.execute.call_args_list if x.args[0].startswith('INSERT INTO public.pr_agent_team_call_evidence')]
                    self.assertEqual(bool(inserts),not bypass)


class EvidenceDB:
    def __init__(self,context):
        self.context=context;self.records={};self.result=None;self.queries=[];self.commits=0;self.commit_error=False
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def commit(self):
        self.commits+=1
        if self.commit_error:raise RuntimeError('synthetic unknown commit outcome')
    def execute(self,sql,parameters):
        self.queries.append((sql,parameters))
        if sql.startswith('SELECT context'):self.result=(self.context,USER,WORKSPACE,'agent_team_report')
        elif sql.startswith('SELECT EXISTS'):self.result=('media' in self.records,)
        elif sql.startswith('INSERT INTO public.pr_agent_team_call_evidence'):
            _,kind,provider,source,sha,_,incoming,outgoing,ack=parameters
            self.records.setdefault(kind,(provider,source,sha,incoming,outgoing,ack));self.result=None
        elif sql.startswith('SELECT provider,source'):self.result=self.records.get(parameters[1])
        else:raise AssertionError('Unknown packet evidence query')
    def fetchone(self):return self.result


class SyntheticSocket:
    def __init__(self):self.events=[];self.sent=[];self.fail_send=False
    async def send_json(self,event):
        if self.fail_send:raise RuntimeError('synthetic failed packet send')
        self.sent.append(event)
    async def receive_json(self):return self.events.pop(0)


class MediaEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        registry=RecoveryStore(':memory:');reg=registration();registry.register(reg)
        try:
            question=build_question(registry,reg,actor_id=USER,workspace_id=WORKSPACE,report_id=REPORT,
                report_version=12,report_key='agent-team:v1:2026-10-05:half_day',prompt='Continue approved mission?',now=NOW,expires_at=NOW+900)
            document=question.document(now=NOW)
        finally:registry.close()
        context={'agentTeamReport':{'missionId':reg.mission_id,'reportId':REPORT,'version':12,'workday':'2026-10-05','kind':'half_day'},
                 'agentTeamDecisionQuestion':document}
        self.db=EvidenceDB(context)
        self.service=SimpleNamespace(provider=SimpleNamespace(name='twilio',real=True),clock=lambda:NOW,
            hosted=SimpleNamespace(connection_factory=lambda:self.db,james_daily_call=SimpleNamespace(cfg=SimpleNamespace(user_id=USER,workspace_id=WORKSPACE))))
        self.call={'id':CALL,'user_id':USER,'workspace_id':WORKSPACE,'provider':'twilio','provider_call_ref':'CA'+'1'*32,
                   'direction':'outbound','destination_ref':'james_env','reason_key':'james_daily:'+RUN}
        self.stream='MZ'+'2'*32
        self.proof=TeamMediaEvidence.create(self.service,self.call,self.stream)
        self.socket=SyntheticSocket();self.transport=TwilioMediaTransport(self.socket,self.stream,evidence=self.proof)
        self.loud=base64.b64encode(b'\x00'*160).decode()

    def frame(self,event,**values):return {'event':event,'streamSid':self.stream,**values}

    def test_non_silence_parser_is_bounded_and_does_not_count_silence_or_invalid_bytes(self):
        self.assertEqual(non_silent_frames(self.loud),1)
        for payload in ('invalid',base64.b64encode(b'\xff'*160).decode(),base64.b64encode(b'\x00'*159).decode(),'x'*65537):
            self.assertEqual(non_silent_frames(payload),0)

    async def test_non_silent_packets_need_uncleared_provider_ack_before_one_immutable_receipt(self):
        await self.transport.send_audio(self.loud)
        mark=self.socket.sent[-1]['mark']['name']
        self.socket.events=[self.frame('media',media={'track':'inbound','payload':self.loud})]
        self.assertEqual(await self.transport.receive_audio(),self.loud)
        self.assertEqual(self.db.records,{})
        self.socket.events=[self.frame('mark',mark={'name':mark}),self.frame('stop')]
        self.assertIsNone(await self.transport.receive_audio())
        self.assertEqual(self.proof.state,'persisted');self.assertEqual(self.db.commits,1)
        proof=self.db.records['media']
        self.assertEqual(proof[3:5],(1,1));self.assertRegex(proof[5],r'^[0-9a-f]{64}$')
        serialized=repr(self.db.records)
        self.assertNotIn(self.loud,serialized)
        await self.proof.inbound(self.loud);await self.proof.mark_ack(mark)
        self.assertEqual(self.db.commits,1)

    async def test_clear_returned_mark_is_not_playback_evidence(self):
        await self.proof.inbound(self.loud)
        await self.transport.send_audio(self.loud);old_mark=self.socket.sent[-1]['mark']['name']
        await self.transport.interrupt()
        self.socket.events=[self.frame('mark',mark={'name':old_mark}),self.frame('stop')]
        await self.transport.receive_audio()
        self.assertEqual(self.db.records,{})
        await self.transport.send_audio(self.loud);new_mark=self.socket.sent[-1]['mark']['name']
        self.assertNotEqual(old_mark,new_mark)
        self.socket.events=[self.frame('mark',mark={'name':new_mark}),self.frame('stop')]
        await self.transport.receive_audio()
        self.assertEqual(self.proof.state,'persisted')

    async def test_failed_send_silence_wrong_mark_and_cross_stream_never_produce_receipt(self):
        await self.proof.inbound(self.loud)
        self.socket.fail_send=True
        with self.assertRaises(RuntimeError):await self.transport.send_audio(self.loud)
        self.assertIsNone(self.proof.pending_mark);self.assertEqual(self.db.records,{})
        self.socket.fail_send=False
        await self.transport.send_audio(base64.b64encode(b'\xff'*160).decode())
        self.assertIsNone(self.proof.pending_mark)
        await self.transport.send_audio(self.loud)
        await self.proof.mark_ack('incorrect-mark')
        self.assertEqual(self.db.records,{})
        self.socket.events=[{'event':'media','streamSid':'MZ'+'9'*32,'media':{'track':'inbound','payload':self.loud}}]
        with self.assertRaises(ValueError):await self.transport.receive_audio()
        self.assertEqual(self.db.records,{})

    async def test_unknown_insert_or_commit_is_not_retried(self):
        await self.proof.inbound(self.loud)
        await self.transport.send_audio(self.loud);mark=self.socket.sent[-1]['mark']['name']
        self.db.commit_error=True
        await self.proof.mark_ack(mark)
        self.assertEqual(self.proof.state,'unknown')
        count=len([sql for sql,_ in self.db.queries if sql.startswith('INSERT')])
        await self.proof.inbound(self.loud);await self.proof.mark_ack(mark)
        await self.transport.send_audio(self.loud)
        self.assertEqual(len([sql for sql,_ in self.db.queries if sql.startswith('INSERT')]),count)

    def test_only_exact_configured_real_provider_question_stream_gets_a_collector(self):
        self.assertIsNotNone(self.proof)
        self.service.provider.real=False
        self.assertIsNone(TeamMediaEvidence.create(self.service,self.call,self.stream))
        self.service.provider.real=True
        self.assertIsNone(TeamMediaEvidence.create(self.service,{**self.call,'user_id':RUN},self.stream))
        self.assertIsNone(TeamMediaEvidence.create(self.service,self.call,'unverified-stream'))
        self.db.context.pop('agentTeamDecisionQuestion')
        self.assertIsNone(TeamMediaEvidence.create(self.service,self.call,self.stream))


if __name__=='__main__':unittest.main()
