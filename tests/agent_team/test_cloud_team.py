import io
import json
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock,patch
from types import SimpleNamespace
from agent_team.events import Event
from postriff_alpha.domain import AlphaError
from agent_team.periods import period
from agent_team.reports import EXPECTED_SOURCES,report
from postriff_phase2.james_agent_team import (
    PREFIX,authorize,body,TeamStore,cron,route,source_coverage,content_fingerprint,
)

USER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'
VALUES={'JAMES_AGENT_TEAM_ENABLED':'1','JAMES_AGENT_TEAM_OBSERVER_TOKEN':'o'*40,
        'JAMES_AGENT_TEAM_READER_TOKEN':'r'*40,'JAMES_AGENT_TEAM_VERIFIER_TOKEN':'v'*40}
HALF=period('2026-10-05','half_day')
MISSING_FRESHNESS=object()


def observation(revision='v1',observed='2026-10-05T20:41:00Z',fresh='2026-10-05T20:40:00Z',state='running'):
    return Event('mission','mission-a',revision,'2026-10-05T20:40:00Z',observed,
                 {'state':state,'sourceFreshAt':fresh},mission_id='mission-a').cloud()


def coverage(source='mission',observed='2026-10-05T21:03:00Z',fresh='2026-10-05T20:59:00Z',**changes):
    payload={'kind':'source_coverage','sourceStatus':'ok','scanComplete':True,'gaps':[],**changes}
    if fresh is not MISSING_FRESHNESS:payload['sourceFreshAt']=fresh
    return Event('health',source,'coverage-1',observed,observed,
                 payload).cloud()


class MemoryStore:
    """Synthetic persistence for cron behavior; SQL atomic/version semantics are tested separately."""
    def __init__(self):
        self.versions={};self.inputs={};self.reservations=[];self.effects=[];self.reads=[]

    def get_report(self,key):
        return self.versions.get(key,[None])[-1]

    def observations(self,p,now):
        self.reads.append(p.key)
        return self.inputs.get(p.key,([],False))

    def put_report(self,doc):
        key=doc['period']['key'];old=self.get_report(key)
        if old and content_fingerprint(old)==content_fingerprint(doc):return old,False
        stored={**doc,'fingerprint':content_fingerprint(doc),'version':old['version']+1 if old else 1,
                'initialGeneratedAt':old['initialGeneratedAt'] if old else doc['generatedAt']}
        if old:stored['supplementOf']=old['fingerprint']
        self.versions.setdefault(key,[]).append(stored)
        return stored,True

    def reserve_effect(self,key,report_key,kind):
        if key in self.reservations:return False
        self.reservations.append(key);return True

    def effect(self,*args,**kwargs):self.effects.append((args,kwargs))


def fake_service(now):
    daily=MagicMock();daily.cfg.user_id=USER;daily.call_report.return_value={'id':'synthetic-run','state':'dialing'}
    return SimpleNamespace(clock=lambda:now.timestamp(),connection_factory=MagicMock(),james_daily_call=daily,
                           verify_session=MagicMock(return_value=USER))


class CloudTeamTests(unittest.TestCase):
    def test_separate_roles_and_no_unconfigured_acceptance(self):
        values={'JAMES_AGENT_TEAM_OBSERVER_TOKEN':'o'*40,'JAMES_AGENT_TEAM_VERIFIER_TOKEN':'v'*40}
        authorize({'HTTP_AUTHORIZATION':'Bearer '+'o'*40},values,'observer')
        with self.assertRaises(AlphaError):authorize({'HTTP_AUTHORIZATION':'Bearer '+'o'*40},values,'verifier')
        with self.assertRaises(AlphaError):authorize({'HTTP_AUTHORIZATION':'Bearer '},{},'reader')

    def test_invalid_body_and_oversize_rejected(self):
        for raw in (b'[]',b'invalid',b'null'):
            with self.assertRaises(AlphaError):body({'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)})
        with self.assertRaises(AlphaError):body({'CONTENT_LENGTH':str(300000),'wsgi.input':io.BytesIO(b'')})

    def test_observer_cannot_submit_completed_acceptance(self):
        row=Event('acceptance','test','v1','2026-01-01T13:00:00Z','2026-01-01T13:01:00Z',
            {'kind':'completed','scopeVersion':'v1','requirements':[{'id':'acceptance','status':'passed','scopeVersion':'v1','evidenceRefs':['a'*64]}]}).cloud()
        factory=MagicMock()
        with self.assertRaises(AlphaError) as e:TeamStore(factory).ingest([row])
        self.assertEqual(e.exception.status,403)
        factory.assert_not_called()

    def test_off_is_no_database_or_call(self):
        service=SimpleNamespace(clock=lambda:1791243600,connection_factory=MagicMock(),james_daily_call=MagicMock())
        self.assertEqual(cron(service,{}),{'state':'disabled'})
        service.connection_factory.assert_not_called();service.james_daily_call.call_report.assert_not_called()

    def run_cron(self,store,now,call=False):
        service=fake_service(now)
        with patch('postriff_phase2.james_agent_team.TeamStore',return_value=store):
            result=cron(service,{'JAMES_AGENT_TEAM_ENABLED':'1','JAMES_AGENT_TEAM_CALL_ENABLED':'1' if call else '0'})
        return result,service

    def test_night_report_never_reserves_phone(self):
        store=MemoryStore();now=datetime.fromisoformat('2026-10-06T05:01:00+00:00')
        result,service=self.run_cron(store,now,call=True)
        self.assertEqual(result['callState'],'disabled');self.assertEqual(result['audioState'],'unavailable')
        self.assertEqual(len(store.versions),1);self.assertEqual(store.reservations,[])
        service.james_daily_call.call_report.assert_not_called()

    def test_generation_timestamp_does_not_append_unchanged_report(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation()],False)
        first,_=self.run_cron(store,HALF.cutoff+timedelta(minutes=1))
        second,service=self.run_cron(store,HALF.cutoff+timedelta(minutes=2))
        self.assertEqual((first['state'],second['state']),('generated','already_generated'))
        self.assertEqual(first['fingerprint'],second['fingerprint'])
        self.assertEqual(len(store.versions[HALF.key]),1)
        service.james_daily_call.call_report.assert_not_called()

    def test_late_event_appends_version_without_second_phone_effect(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation()],False)
        first,original_service=self.run_cron(store,HALF.cutoff+timedelta(minutes=1),call=True)
        original_service.james_daily_call.call_report.assert_called_once()
        self.assertEqual(original_service.james_daily_call.call_report.call_args.kwargs['version'],1)
        store.inputs[HALF.key]=([observation(),observation('v2','2026-10-05T21:03:00Z',state='waiting_human')],False)
        second,service=self.run_cron(store,HALF.cutoff+timedelta(minutes=4),call=True)
        self.assertEqual((second['state'],second['version'],second['callState']),('supplemented',2,'supplement_no_call'))
        latest=store.get_report(HALF.key)
        self.assertEqual(latest['supplementOf'],first['fingerprint'])
        self.assertEqual(latest['asOf'],HALF.cutoff.isoformat())
        self.assertEqual(latest['lateObservationCount'],1)
        self.assertEqual(len(store.reservations),1)
        service.james_daily_call.call_report.assert_not_called()

    def test_missed_original_cutoff_is_not_retried_when_supplement_arrives(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation()],False)
        first,service=self.run_cron(store,HALF.cutoff+timedelta(minutes=20),call=True)
        self.assertEqual(first['callState'],'missed_window')
        store.inputs[HALF.key]=([observation('v2','2026-10-05T21:20:00Z')],False)
        later,service=self.run_cron(store,HALF.cutoff+timedelta(minutes=21),call=True)
        self.assertEqual(later['callState'],'supplement_no_call')
        self.assertEqual(store.reservations,[])
        service.james_daily_call.call_report.assert_not_called()

    def test_period_rollover_revisits_only_existing_recent_reports(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation()],False)
        self.run_cron(store,HALF.cutoff+timedelta(minutes=1))
        store.inputs[HALF.key]=([observation('v2','2026-10-06T04:55:00Z')],False)
        store.reads=[]
        result,service=self.run_cron(store,datetime.fromisoformat('2026-10-06T05:01:00+00:00'),call=True)
        self.assertEqual(result['reportKey'],period('2026-10-05','whole_day').key)
        self.assertEqual(result['supplements'][0]['reportKey'],HALF.key)
        self.assertEqual(result['supplements'][0]['callState'],'supplement_no_call')
        self.assertLessEqual(len(store.reads),3)
        self.assertEqual(len(store.versions),2)
        self.assertEqual(store.reservations,[])
        service.james_daily_call.call_report.assert_not_called()

    def test_post_cutoff_source_edit_cannot_rewrite_original_report(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation()],False)
        first,_=self.run_cron(store,HALF.cutoff+timedelta(minutes=1))
        store.inputs[HALF.key]=([observation(),observation('v2','2026-10-05T21:04:00Z','2026-10-05T21:01:00Z','waiting_human')],False)
        later,_=self.run_cron(store,HALF.cutoff+timedelta(minutes=5))
        self.assertEqual(later['state'],'already_generated')
        self.assertEqual(later['fingerprint'],first['fingerprint'])
        self.assertEqual(len(store.versions[HALF.key]),1)

    def test_required_coverage_accepts_late_pre_cutoff_watermark_and_keeps_other_gaps(self):
        sources=source_coverage([coverage()],HALF,HALF.cutoff+timedelta(minutes=4))
        self.assertEqual(set(sources),set(EXPECTED_SOURCES))
        self.assertTrue(sources['mission']['complete'])
        self.assertFalse(sources['luci']['complete'])
        self.assertEqual(sources['luci']['gaps'],['source_not_verified'])
        doc=report(HALF,[observation(),coverage()],HALF.cutoff+timedelta(minutes=4),sources)
        self.assertEqual(doc['counts']['running'],1)
        self.assertIn('luci:source_not_verified',doc['gaps'])

    def test_stale_future_or_partial_health_cannot_claim_complete_coverage(self):
        for row in (coverage(fresh='2026-10-05T20:55:00Z'),coverage(fresh='2026-10-05T21:01:00Z'),
                    coverage(sourceStatus='partial'),coverage(gaps=['query_limit'])):
            sources=source_coverage([row],HALF,HALF.cutoff+timedelta(minutes=4))
            self.assertFalse(sources['mission']['complete'])
            self.assertTrue(sources['mission']['gaps'])
        sources=source_coverage([coverage(observed='2026-10-05T21:05:00Z')],HALF,HALF.cutoff+timedelta(minutes=4))
        self.assertFalse(sources['mission']['complete'])

    def test_missing_source_freshness_is_unknown_even_when_scan_time_is_recent(self):
        row=coverage(observed='2026-10-05T20:59:30Z',fresh=MISSING_FRESHNESS,gaps=['source_freshness_unknown'])
        self.assertNotIn('sourceFreshAt',row['payload'])
        result=source_coverage([row],HALF,HALF.cutoff+timedelta(minutes=1))['mission']
        self.assertEqual((result['status'],result['freshAt'],result['complete']),('unknown',None,False))
        self.assertIn('source_freshness_unknown',result['gaps'])

    def test_post_cutoff_unknown_scan_cannot_replace_positive_cutoff_freshness(self):
        unknown=coverage(observed='2026-10-05T21:04:00Z',fresh=MISSING_FRESHNESS,gaps=['source_freshness_unknown'])
        self.assertNotIn('sourceFreshAt',unknown['payload'])
        sources=source_coverage([unknown,coverage()],HALF,HALF.cutoff+timedelta(minutes=5))
        self.assertTrue(sources['mission']['complete'])
        self.assertEqual(sources['mission']['freshAt'],'2026-10-05T20:59:00+00:00')

    def test_query_truncation_invalidates_all_required_source_coverage(self):
        store=MemoryStore();store.inputs[HALF.key]=([observation(),coverage()],True)
        result,_=self.run_cron(store,HALF.cutoff+timedelta(minutes=4))
        doc=store.get_report(result['reportKey'])
        self.assertIsNone(doc['counts']['running'])
        self.assertTrue(all(not c['complete'] for c in doc['coverage']))
        self.assertTrue(all('observation_query_limit' in c['gaps'] for c in doc['coverage']))


class CloudAuthTests(unittest.TestCase):
    def app(self,principal=USER):
        service=fake_service(HALF.cutoff);service.verify_session.return_value=principal
        app=SimpleNamespace(_runtime=MagicMock(return_value=service),
                            _token=MagicMock(side_effect=lambda e:e['HTTP_AUTHORIZATION'][7:]),
                            _json=MagicMock(side_effect=lambda _start,_status,data,**kwargs:data))
        return app,service

    def decision_env(self,token='authenticated-james-session'):
        raw=json.dumps({'decisionKey':'decision-1','missionId':'james-agent-team','scopeVersion':'1',
                        'callRunId':'33333333-3333-4333-8333-333333333333','questionVersion':'1','choice':'continue'}).encode()
        return {'HTTP_AUTHORIZATION':'Bearer '+token,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_decision_uses_actual_verified_session_principal(self,store_type):
        app,service=self.app();store_type.return_value.decision.return_value={'state':'recorded'}
        with patch.dict('os.environ',VALUES):
            result=route(app,self.decision_env(),MagicMock(),'POST',PREFIX+'/decisions')
        self.assertEqual(result['state'],'recorded')
        service.verify_session.assert_called_once_with('authenticated-james-session')
        self.assertEqual(store_type.return_value.decision.call_args.args[1],USER)

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_verifier_observer_and_reader_tokens_cannot_impersonate_james(self,store_type):
        for token in ('v'*40,'o'*40,'r'*40):
            app,service=self.app()
            with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError) as raised:
                route(app,self.decision_env(token),MagicMock(),'POST',PREFIX+'/decisions')
            self.assertEqual(raised.exception.status,401)
            service.verify_session.assert_not_called()
        store_type.return_value.decision.assert_not_called()

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_other_authenticated_user_cannot_decide_james_mission(self,store_type):
        app,_=self.app(OTHER)
        with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError) as raised:
            route(app,self.decision_env(),MagicMock(),'POST',PREFIX+'/decisions')
        self.assertEqual(raised.exception.code,'agent_team_principal_mismatch')
        store_type.return_value.decision.assert_not_called()

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_expired_session_cannot_record_a_decision(self,store_type):
        app,service=self.app();service.verify_session.side_effect=AlphaError('Session expired.',401)
        with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError) as raised:
            route(app,self.decision_env(),MagicMock(),'POST',PREFIX+'/decisions')
        self.assertEqual(raised.exception.status,401)
        store_type.return_value.decision.assert_not_called()

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_report_read_accepts_exact_james_session_or_reader_token(self,store_type):
        store_type.return_value.get_report.return_value={'fingerprint':'synthetic-report'}
        for token in ('authenticated-james-session','r'*40):
            app,service=self.app()
            with patch.dict('os.environ',VALUES):
                result=route(app,{'HTTP_AUTHORIZATION':'Bearer '+token},MagicMock(),'GET',PREFIX+'/reports/2026-10-05/half_day/json')
            self.assertEqual(result,{'fingerprint':'synthetic-report'})
            if token.startswith('authenticated'):service.verify_session.assert_called_once()
            else:service.verify_session.assert_not_called()

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_report_version_is_exact_and_matches_identity_headers(self,store_type):
        app,_=self.app();store_type.return_value.get_report.return_value={'version':2,'fingerprint':'a'*64}
        with patch.dict('os.environ',VALUES):
            route(app,{'HTTP_AUTHORIZATION':'Bearer '+'r'*40,'QUERY_STRING':'version=2'},MagicMock(),'GET',PREFIX+'/reports/2026-10-05/half_day/json')
        store_type.return_value.get_report.assert_called_once_with(period('2026-10-05','half_day').key,2)
        self.assertIn(('X-Agent-Team-Report-Version','2'),app._json.call_args.kwargs['extra_headers'])
        for query in ('version=0','version=2&version=3','version=x','readerToken=secret'):
            with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError):
                route(app,{'HTTP_AUTHORIZATION':'Bearer '+'r'*40,'QUERY_STRING':query},MagicMock(),'GET',PREFIX+'/reports/2026-10-05/half_day/json')

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_machine_event_roles_remain_separate_from_human_and_reader(self,store_type):
        raw=b'{"events":[]}'
        for token in ('authenticated-james-session','r'*40,'v'*40):
            app,_=self.app()
            env={'HTTP_AUTHORIZATION':'Bearer '+token,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
            with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError):
                route(app,env,MagicMock(),'POST',PREFIX+'/events')
        store_type.return_value.ingest.assert_not_called()

    @patch('postriff_phase2.james_agent_team.TeamStore')
    def test_verifier_or_other_user_cannot_read_private_reports(self,store_type):
        for token,principal in (('v'*40,USER),('o'*40,USER),('other-session',OTHER)):
            app,_=self.app(principal)
            with patch.dict('os.environ',VALUES),self.assertRaises(AlphaError):
                route(app,{'HTTP_AUTHORIZATION':'Bearer '+token},MagicMock(),'GET',PREFIX+'/reports/2026-10-05/half_day/json')
        store_type.return_value.get_report.assert_not_called()


class CloudPersistenceTests(unittest.TestCase):
    def store(self,prior=None):
        cur,db=MagicMock(),MagicMock();db.__enter__.return_value=db
        db.cursor.return_value.__enter__.return_value=cur;cur.fetchone.return_value=(prior,) if prior else None
        return TeamStore(lambda:db),cur

    def test_append_serializes_versions_and_unchanged_report_is_not_inserted(self):
        first=report(HALF,[observation()],HALF.cutoff+timedelta(minutes=1),source_coverage([],HALF))
        store,cur=self.store();stored,created=store.put_report(first)
        self.assertTrue(created);self.assertEqual(stored['version'],1)
        self.assertIn('pg_advisory_xact_lock',cur.execute.call_args_list[0].args[0])
        newer=report(HALF,[observation()],HALF.cutoff+timedelta(minutes=2),source_coverage([],HALF))
        store,cur=self.store(stored);same,created=store.put_report(newer)
        self.assertFalse(created);self.assertEqual(same,stored)
        self.assertFalse(any(c.args[0].startswith('INSERT') for c in cur.execute.call_args_list))
        changed=report(HALF,[observation('v2','2026-10-05T21:03:00Z')],HALF.cutoff+timedelta(minutes=4),source_coverage([],HALF))
        store,cur=self.store(stored);supplement,created=store.put_report(changed)
        self.assertTrue(created);self.assertEqual(supplement['version'],2)
        self.assertEqual(supplement['initialGeneratedAt'],stored['generatedAt'])
        self.assertEqual(supplement['supplementOf'],stored['fingerprint'])

    def test_observation_query_keeps_late_health_but_bounds_cutoff_and_generated_time(self):
        store,cur=self.store();cur.fetchall.return_value=[]
        now=HALF.cutoff+timedelta(minutes=5)
        store.observations(HALF,now)
        sql,args=cur.execute.call_args.args
        self.assertIn("happened_at<%s OR source='health'",sql)
        self.assertIn('observed_at<=%s',sql)
        self.assertIn('LIMIT 10001',sql)
        self.assertEqual(args,(HALF.start,HALF.cutoff,now))

    def test_invalid_source_freshness_cannot_poison_future_report_generation(self):
        for fresh in ('invalid-timestamp','2026-01-01T14:00:00Z'):
            row=Event('mission','mission-a','v1','2026-01-01T12:00:00Z','2026-01-01T13:00:00Z',{'state':'running'}).cloud()
            row['payload']['sourceFreshAt']=fresh
            factory=MagicMock()
            with self.assertRaises(AlphaError):TeamStore(factory).ingest([row])
            factory.assert_not_called()

    def test_legacy_report_version_cannot_supply_question_authority(self):
        store,cur=self.store()
        workspace='22222222-2222-4222-8222-222222222222'
        cur.fetchone.return_value=({'agentTeamReport':{'missionId':'james-agent-team','version':2,'reportId':'a'*64,'workday':'2026-10-05'}},USER,workspace,'agent_team_report',None,None)
        d={'decisionKey':'d1','missionId':'james-agent-team','scopeVersion':'2',
           'callRunId':'33333333-3333-4333-8333-333333333333','questionVersion':'1','choice':'continue'}
        result=store.decision(d,USER,workspace,HALF.cutoff.timestamp())
        self.assertEqual((result['state'],result['executionState']),('blocked','not_dispatched'))
        self.assertFalse(any(c.args[0].startswith('INSERT') for c in cur.execute.call_args_list))

    def test_matching_legacy_report_version_cannot_bypass_question_and_attendance_evidence(self):
        store,cur=self.store()
        workspace='22222222-2222-4222-8222-222222222222'
        d={'decisionKey':'d1','missionId':'james-agent-team','scopeVersion':'2',
           'callRunId':'33333333-3333-4333-8333-333333333333','questionVersion':'2','choice':'continue'}
        cur.fetchone.return_value=({'agentTeamReport':{'missionId':'james-agent-team','version':2,'reportId':'a'*64,'workday':'2026-10-05'}},USER,workspace,'agent_team_report',None,None)
        result=store.decision(d,USER,workspace,HALF.cutoff.timestamp())
        self.assertEqual((result['state'],result['executionState']),('blocked','not_dispatched'))
        self.assertFalse(any(c.args[0].startswith('INSERT') for c in cur.execute.call_args_list))
