"""Synthetic official-API analytics/capability boundaries; no provider traffic or activation."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights
from postriff_phase2.growth.metric_schedule import MetricScheduler
from postriff_phase2.oauth import OAuthService
from postriff_phase2.pinterest_analytics import SCOPES, fetch, describe, enabled
from postriff_phase2.wave3_connectors import PinterestProvider
from test_hosted_wave1_connectors import Wire, ok

NOW = 1792238400
IDENTITY = ok({'id':'1234567','username':'synthetic','account_type':'BUSINESS'})
REPORT = ok({'all':{'summary_metrics':{'IMPRESSION':25,'SAVE':0,'PIN_CLICK':4,'OUTBOUND_CLICK':2}}})


def fixture(replies=(), scopes=SCOPES):
    p= PinterestProvider('1615884','SYNTHETIC',transport=Wire(replies),production_reviewed=True,analytics_enabled=True)
    token=json.dumps({'v':1,'at':'SYNTHETIC_TOKEN','environment':'production','clientId':'1615884','accountId':'1234567','scope':sorted(scopes)})
    return p,token


class PrivateAnalyticsPolicy:
    """Synthetic exact private scope; the real policy is independently configured server-side."""
    workspace_id='w'
    now=NOW
    expires_at=NOW+600
    analytics=True
    account='1234567'
    actor_id='00000000-0000-0000-0000-000000000502'
    board_ids=('7654321',)
    pilot_id='00000000-0000-0000-0000-000000000503'

    def binding(self):
        capabilities=['identity','boards_read']+(['analytics'] if self.analytics is True else [])
        return {'workspace':self.workspace_id,'actor':self.actor_id,'username':'synthetic',
                'expiresAt':self.expires_at,'account':self.account,'boards':list(self.board_ids),
                'capabilities':sorted(capabilities),'pilot':self.pilot_id,'maxCreateAttempts':2}

    def supports(self,capability):return self.analytics if capability=='analytics' else False

    def require(self,workspace_id,actor_id=None,*,now=None):
        if workspace_id!=self.workspace_id or self.now>=self.expires_at:
            raise AlphaError('Synthetic private authority denied.',403)

    def require_scopes(self,scopes):
        permitted={'user_accounts:read','boards:read'}|({'pins:read'} if self.analytics is True else set())
        if (not isinstance(scopes,list) or not scopes or any(not isinstance(scope,str) for scope in scopes)
                or not set(scopes)<=permitted):
            raise AlphaError('Synthetic private scope denied.',403)

    def require_account(self,account):
        if account!=self.account:raise AlphaError('Synthetic private account mismatch.',409)

    def require_identity(self,identity):
        self.require_account(identity.get('providerAccountId'))
        if identity.get('handle')!='@synthetic':
            raise AlphaError('Synthetic private account mismatch.',409)


def private_fixture(replies=()):
    p,t=fixture(replies);p.production_reviewed=False;p.private_trial=True;p.trial_policy=PrivateAnalyticsPolicy()
    p.private_trial_pin_gate=Mock(side_effect=lambda pin_id:pin_id=='1')  # Provider guard ownership is tested separately.
    envelope=json.loads(t);envelope['privateTrialBinding']=p.trial_policy.binding()
    return p,json.dumps(envelope)


class PinterestAnalytics(unittest.TestCase):
    def test_official_summary_uses_bound_adapter_quota_and_native_metrics(self):
        p,t=fixture([IDENTITY,REPORT]);quota=[];p.quota_required=True;p.rate_gate=lambda *a:quota.append(a)
        r=fetch(p,t,'7654321',start_at=NOW-3600,end_at=NOW)
        self.assertEqual(r['found'],{'impressions':25,'saves':0,'pin_clicks':4,'outbound_clicks':2})
        self.assertEqual(r['outcome'],'success')
        self.assertEqual(len(quota),2)
        self.assertIn('/v5/pins/7654321/analytics?',r['endpoint'])
        self.assertNotIn('access_token',r['endpoint']);self.assertNotIn('SYNTHETIC_TOKEN',json.dumps(r))
        self.assertEqual(p.transport.calls[-1]['headers']['Authorization'],'Bearer SYNTHETIC_TOKEN')
        self.assertEqual(r['periodStart']%86400,0)

    def test_flags_review_pause_and_readonly_deny_before_network(self):
        for field,value in [('analytics_enabled',False),('analytics_enabled','false'),('production_reviewed',False),('production_reviewed','false'),('execution_enabled',False),('trial_readonly',True)]:
            with self.subTest(field=field,value=value):
                p,t=fixture();setattr(p,field,value)
                with self.assertRaises(AlphaError):fetch(p,t,'1',start_at=NOW,end_at=NOW)
                self.assertEqual(p.transport.calls,[])

    def test_missing_scopes_and_unknown_account_deny_before_network(self):
        for change in ('scope','accountId'):
            p,t=fixture();d=json.loads(t);d[change]=[] if change=='scope' else None
            with self.assertRaises(AlphaError):fetch(p,json.dumps(d),'1',start_at=NOW,end_at=NOW)
            self.assertEqual(p.transport.calls,[])

    def test_account_drift_stops_before_analytics(self):
        p,t=fixture([ok({'id':'999','username':'other'})])
        with self.assertRaises(AlphaError):fetch(p,t,'1',start_at=NOW,end_at=NOW)
        self.assertEqual(len(p.transport.calls),1)

    def test_invalid_pin_and_reporting_windows_never_call_provider(self):
        for pin,start,end in [('../1',NOW,NOW),('1',True,NOW),('1',float('nan'),NOW),('1',1e300,1e300),('1',NOW,NOW-1),('1',NOW-91*86400,NOW)]:
            p,t=fixture()
            with self.assertRaises(AlphaError):fetch(p,t,pin,start_at=start,end_at=end)
            self.assertEqual(p.transport.calls,[])

    def test_missing_or_bad_values_stay_unavailable_and_error_payload_is_not_retained(self):
        for body,status in [({'all':{'summary_metrics':{'IMPRESSION':True,'SAVE':-1,'PIN_CLICK':float('inf')}}},200),({'split':{'summary_metrics':{'IMPRESSION':999}}},200),({'message':'SYNTHETIC_SECRET'},403)]:
            p,t=fixture([IDENTITY,ok(body,status)]);r=fetch(p,t,'1',start_at=NOW,end_at=NOW)
            self.assertEqual(r['found'],{});self.assertEqual(r['outcome'],'read_failed')
            self.assertNotIn('SYNTHETIC_SECRET',json.dumps(r))

    def test_existing_observation_storage_keeps_zero_and_unavailable_separate(self):
        rows=[];cur=SimpleNamespace(execute=lambda sql,args:rows.append(args))
        insights.record_observations(cur,'w','c','pinterest','1','job',{'saves':0},'safe',NOW)
        self.assertEqual(len(rows),4)
        by_name={r[5]:r for r in rows}
        self.assertEqual(by_name['saves'][7:9],[0,'available'])
        self.assertEqual(by_name['impressions'][7:9],[None,'unavailable'])
        self.assertTrue(all(r[6]=='pinterest-pin-utc-window-v1' for r in rows))

    def test_scheduling_is_rafii_queue_and_analytics_uses_minimal_separate_scopes(self):
        p,t=fixture();full=sorted(SCOPES|{'pins:write'})
        m=OAuthService._capabilities(p,'publish',full,[],NOW,t)
        self.assertEqual(m['publish']['level'],'Direct');self.assertEqual(m['schedule']['level'],'Direct')
        self.assertIn('scheduled time',m['schedule']['evidence']);self.assertFalse(p.native_schedule)
        self.assertNotIn('pins:write',p.capability_scopes('analytics'))
        for name in ('comments_read','reply'):self.assertEqual(m[name]['level'],'Unsupported')
        p.analytics_enabled=False;self.assertEqual(p.capability_scopes('analytics'),[])
        self.assertEqual(describe(m,full,analytics_enabled=False)['analytics']['level'],'Unsupported')
        readonly=OAuthService._capabilities(p,'boards_read',['user_accounts:read','boards:read'],[],NOW,t)
        self.assertNotEqual(readonly['analytics']['level'],'Direct');self.assertIn('read-only',readonly['schedule']['evidence'])

    def test_scheduler_uses_existing_custody_not_generic_raw_transport(self):
        p,t=fixture([IDENTITY,REPORT]);oauth=SimpleNamespace(providers={'pinterest':p},token_for_worker=Mock(return_value={'provider':'pinterest','accessToken':t,'scopes':sorted(SCOPES)}),_provider_for_access=Mock(return_value=p))
        scheduler=MetricScheduler(None,oauth,transport=Mock(side_effect=AssertionError('raw transport bypass')),workspace_allowlist={'w'},clock=lambda:NOW)
        scheduler._eligible=lambda row:'read';scheduler._pinterest_schema_ready=lambda:True
        r=scheduler.read({'workspaceId':'w','connectionId':'c','provider':'pinterest','postId':'1','anchorAt':NOW-3600},{})
        self.assertEqual(r['state'],'done');self.assertEqual(r['found']['impressions'],25)
        self.assertEqual(r['analyticsOutcome'],'success')
        self.assertEqual(oauth.token_for_worker.call_args.args,('w','c'));scheduler.transport.assert_not_called()
        scheduler._pinterest_schema_ready=lambda:False
        before=len(p.transport.calls);self.assertFalse(scheduler.provider_allowed('pinterest'));self.assertEqual(len(p.transport.calls),before)


    def test_confirmed_empty_summary_and_native_zero_are_different_successes(self):
        for body,outcome,found in [({'all':{'summary_metrics':{}}},'no_data',{}),
                                   ({'all':{'daily_metrics':[]}},'no_data',{}),
                                   ({'ALL':{'summary_metrics':{'SAVE':0}}},'success',{'saves':0}),
                                   ({'all':{'summary_metrics':{'IMPRESSION':1}}},'success',{'impressions':1})]:
            with self.subTest(body=body):
                p,t=fixture([IDENTITY,ok(body)])
                result=fetch(p,t,'1',start_at=NOW,end_at=NOW)
                self.assertEqual((result['outcome'],result['found']),(outcome,found))
                self.assertNotIn('failure',result)

    def test_malformed_success_cannot_be_reported_as_no_data(self):
        malformed=[None,[],{}, {'all':None}, {'all':{'summary_metrics':[]}},
                   {'all':{'summary_metrics':{'IMPRESSION':None}}},
                   {'all':{'summary_metrics':{'IMPRESSION':10**1000}}},
                   {'all':{'summary_metrics':{'SAVE':1,'PIN_CLICK':False}}},
                   {'all':{'summary_metrics':{}},'ALL':{'summary_metrics':{}}},
                   {'message':'SYNTHETIC_SECRET'}]
        for body in malformed:
            with self.subTest(body=body):
                p,t=fixture([IDENTITY,{'status':200,'body':body}])
                result=fetch(p,t,'1',start_at=NOW,end_at=NOW)
                self.assertEqual((result['outcome'],result['failure'],result['found']),('read_failed','invalid_response',{}))
                self.assertNotIn('SYNTHETIC_SECRET',json.dumps(result))

    def test_optional_summary_without_totals_is_not_fabricated_from_daily_values(self):
        for report in ({}, {'daily_metrics':[{'metrics':{'SAVE':0}}]}, {'lifetime_metrics':{'SAVE':2}}):
            with self.subTest(report=report):
                p,t=fixture([IDENTITY,ok({'all':report})])
                result=fetch(p,t,'1',start_at=NOW,end_at=NOW)
                self.assertEqual((result['outcome'],result['failure'],result['found']),('read_failed','summary_unavailable',{}))

    def test_scheduler_keeps_no_data_distinct_and_retries_malformed_success(self):
        for body,status,state,analytics,failure in [({'all':{'summary_metrics':{}}},200,'done','no_data',None),
                                                   ({'all':{'summary_metrics':{'SAVE':0}}},200,'done','success',None),
                                                   ({'message':'SYNTHETIC_SECRET'},200,'transient','read_failed','invalid_response'),
                                                   ({'all':{'daily_metrics':[{'metrics':{'SAVE':0}}]}},200,'transient','read_failed','summary_unavailable'),
                                                   ({'message':'SYNTHETIC_SECRET'},403,'unavailable','read_failed','http_403'),
                                                   ({'message':'SYNTHETIC_SECRET'},429,'transient','read_failed','http_429')]:
            with self.subTest(status=status,body=body):
                p,t=fixture([IDENTITY,ok(body,status)])
                oauth=SimpleNamespace(providers={'pinterest':p},token_for_worker=Mock(return_value={'provider':'pinterest','accessToken':t,'scopes':sorted(SCOPES)}),_provider_for_access=Mock(return_value=p))
                scheduler=MetricScheduler(None,oauth,transport=Mock(side_effect=AssertionError('raw transport bypass')),workspace_allowlist={'w'},clock=lambda:NOW)
                scheduler._eligible=lambda row:'read';scheduler._pinterest_schema_ready=lambda:True
                row={'id':'read','attempts':1,'maxAttempts':2,'workspaceId':'w','connectionId':'c','provider':'pinterest','postId':'1','anchorAt':NOW-3600}
                outcome=scheduler.read(row,{})
                self.assertEqual((outcome['state'],outcome['analyticsOutcome'],outcome.get('failure')),(state,analytics,failure))
                self.assertNotIn('SYNTHETIC_SECRET',json.dumps(outcome))
                scheduler.claim=lambda limit:[row];scheduler.read=lambda *args:outcome;scheduler.complete=lambda *args:True
                tick=scheduler.tick()
                self.assertEqual(tick['pinterestAnalytics'],{name:int(name==analytics) for name in ('success','no_data','read_failed')})
                self.assertEqual(tick['providerErrors'],int(state!='done'))
                self.assertEqual(tick['done'],int(state=='done'))

    def test_durable_empty_marker_and_failure_never_write_fabricated_observations(self):
        row={'id':'read','attempts':1,'maxAttempts':2,'workspaceId':'w','connectionId':'c','provider':'pinterest','postId':'1','jobId':'job','offset':'t0','anchorAt':NOW-3600}
        for analytics,state,marker in [('no_data','done','no_data'),('success','done',None),('read_failed','transient',None)]:
            with self.subTest(analytics=analytics):
                db=MagicMock();db.__enter__.return_value=db
                cur=MagicMock();cur.__enter__.return_value=cur;cur.rowcount=1;db.cursor.return_value=cur
                scheduler=MetricScheduler(lambda:db,None,transport=None,workspace_allowlist={'w'},clock=lambda:NOW)
                scheduler._eligibility=lambda *args,**kw:'read'
                outcome={'state':state,'analyticsOutcome':analytics,'http':200,'found':{} if analytics!='success' else {'saves':0},'endpoint':'safe','failure':'invalid_response' if state=='transient' else None}
                with patch('postriff_phase2.growth.metric_schedule.insights.record_observations') as record:
                    self.assertTrue(scheduler.complete(row,outcome))
                sql,args=cur.execute.call_args.args
                if state=='done':
                    self.assertIn("status='done'",sql);self.assertEqual(args[0],marker)
                    self.assertEqual(record.call_args.args[6],outcome['found'])
                else:
                    self.assertIn("status='pending'",sql);self.assertEqual(args[2],'invalid_response')
                    record.assert_not_called()

    def test_direct_ingest_records_no_failed_response_as_an_observation(self):
        p,t=fixture();oauth=SimpleNamespace(providers={'pinterest':p},token_for_worker=Mock(return_value={'accessToken':t}),_provider_for_access=Mock(return_value=p))
        for outcome,expected in [('read_failed',0),('no_data',1),('success',1)]:
            with self.subTest(outcome=outcome), patch.object(insights,'fetch_post_insights',return_value={'status':200,'outcome':outcome,'found':{},'endpoint':'safe'}), patch.object(insights,'record_observations',return_value=[]) as record:
                result=insights.ingest_post_insights(None,None,oauth,'w','c','pinterest','1','job',NOW)
                self.assertEqual(result['outcome'],outcome);self.assertEqual(record.call_count,expected)

    def test_latest_read_receipts_include_first_failure_and_bind_workspace(self):
        class Cursor:
            def __init__(self):self.calls=[]
            def execute(self,sql,args=None):self.calls.append((sql,args))
            def fetchall(self):return [('pinterest','c','1','job','pending','invalid_response',200,NOW,'t0'),('pinterest','c','2','job2','done','no_data',200,NOW,'24h')]
        cur=Cursor();rows,availability=insights.latest_read_outcomes(cur,'workspace-a','24h')
        query,args=cur.calls[1]
        self.assertEqual(args,('workspace-a','24h'));self.assertIn('WHERE workspace_id=%s',query);self.assertIn('read_offset=%s',query)
        self.assertEqual(availability,'available');self.assertEqual([row['outcome'] for row in rows],['read_failed','no_data'])
        self.assertEqual(rows[0]['jobId'],'job');self.assertEqual(rows[0]['connectionId'],'c');self.assertNotIn('failure_class',json.dumps(rows))

    def test_missing_queue_schema_rolls_back_savepoint_without_hiding_observations(self):
        class Cursor:
            def __init__(self):self.calls=[]
            def execute(self,sql,args=None):
                self.calls.append(sql)
                if 'FROM public.pr_metric_reads' in sql:raise RuntimeError('SYNTHETIC_SECRET table missing')
        cur=Cursor();rows,availability=insights.latest_read_outcomes(cur,'workspace-a')
        self.assertEqual((rows,availability),([],'unavailable'))
        self.assertTrue(any(sql.startswith('ROLLBACK TO SAVEPOINT') for sql in cur.calls))
        self.assertTrue(cur.calls[-1].startswith('RELEASE SAVEPOINT'))

    def test_summary_keeps_older_zero_and_attaches_only_exact_read_binding(self):
        observations=[('pinterest','1','job','saves','pinterest-pin-utc-window-v1',0,'count','available',NOW-60,NOW-60,'c','t0',NOW-86400)]
        failure={'provider':'pinterest','connectionId':'c','providerPostId':'1','jobId':'job','outcome':'read_failed','observedAt':NOW,'readOffset':'1h'}
        other={**failure,'connectionId':'other','jobId':'other-job'}
        first_failure={**failure,'providerPostId':'2','jobId':'job2'}
        with patch.object(insights,'latest_observations',return_value=observations),patch.object(insights,'latest_read_outcomes',return_value=([failure,other,first_failure],'available')):
            result=insights.summary(None,'workspace-a',[],NOW)
        self.assertEqual(len(result['posts']),1);post=result['posts'][0]
        self.assertEqual(post['metrics']['saves']['value'],0);self.assertEqual(post['latestRead'],failure)
        self.assertEqual(post['freshness']['observedAt'],NOW-60)
        self.assertEqual(len(result['readOutcomes']),3)

    def test_private_trial_reads_native_metrics_without_claiming_public_review(self):
        p,t=private_fixture([IDENTITY,REPORT]);quota=[];p.quota_required=True;p.rate_gate=lambda *args:quota.append(args)
        result=fetch(p,t,'1',start_at=NOW,end_at=NOW)
        self.assertFalse(p.production_reviewed);self.assertTrue(enabled(p));self.assertEqual(result['outcome'],'success')
        self.assertEqual(result['found']['saves'],0);self.assertEqual(len(quota),2)
        oauth=SimpleNamespace(providers={'pinterest':p})
        scheduler=MetricScheduler(None,oauth,transport=None,workspace_allowlist={'w','other'})
        scheduler._pinterest_schema_ready=lambda:True
        self.assertTrue(scheduler.provider_allowed('pinterest','w'));self.assertFalse(scheduler.provider_allowed('pinterest','other'))

    def test_private_trial_analytics_is_default_off_expiring_paused_and_readonly_denied(self):
        cases=('default_off','private_missing','private_malformed','missing_policy','missing_pin_gate','missing_capability','malformed_capability','expired','paused','readonly')
        for case in cases:
            with self.subTest(case=case):
                p,t=private_fixture()
                if case=='default_off':p.analytics_enabled=False
                elif case=='private_missing':p.private_trial=False
                elif case=='private_malformed':p.private_trial='true'
                elif case=='missing_policy':p.trial_policy=None
                elif case=='missing_pin_gate':p.private_trial_pin_gate=None
                elif case=='missing_capability':p.trial_policy.analytics=False
                elif case=='malformed_capability':p.trial_policy.analytics='true'
                elif case=='expired':p.trial_policy.now=NOW+600
                elif case=='paused':p.execution_enabled=False
                else:p.trial_readonly=True
                self.assertFalse(enabled(p))
                with self.assertRaises(AlphaError):fetch(p,t,'1',start_at=NOW,end_at=NOW)
                self.assertEqual(p.transport.calls,[])

    def test_private_trial_wrong_workspace_denies_before_custody_even_on_metric_allowlist(self):
        p,t=private_fixture()
        oauth=SimpleNamespace(providers={'pinterest':p},token_for_worker=Mock(side_effect=AssertionError('foreign custody')))
        scheduler=MetricScheduler(None,oauth,transport=None,workspace_allowlist={'w','other'})
        scheduler._pinterest_schema_ready=lambda:True
        outcome=scheduler.read({'workspaceId':'other','connectionId':'c','provider':'pinterest','postId':'1','anchorAt':NOW},{})
        self.assertEqual(outcome['state'],'cancelled');oauth.token_for_worker.assert_not_called();self.assertEqual(p.transport.calls,[])

    def test_private_trial_wrong_bound_account_or_identity_cannot_read_pin_metrics(self):
        for account,username in [('999','synthetic'),('1234567','other')]:
            with self.subTest(account=account,username=username):
                p,t=private_fixture([ok({'id':account,'username':username})]);envelope=json.loads(t);envelope['accountId']=account
                with self.assertRaises(AlphaError):fetch(p,json.dumps(envelope),'1',start_at=NOW,end_at=NOW)
                self.assertLessEqual(len(p.transport.calls),1)
                self.assertFalse(any('/pins/' in call['url'] for call in p.transport.calls))

    def test_private_trial_unrecorded_pin_never_reaches_provider_pin_api(self):
        p,t=private_fixture([IDENTITY])
        with self.assertRaises(AlphaError):fetch(p,t,'2',start_at=NOW,end_at=NOW)
        self.assertLessEqual(len(p.transport.calls),1)
        self.assertFalse(any('/pins/' in call['url'] for call in p.transport.calls))

    def test_private_trial_expiry_during_identity_read_stops_next_provider_request(self):
        p,t=private_fixture([IDENTITY]);wire=p.transport
        def identity_then_expire(*args,**kwargs):
            result=wire(*args,**kwargs);p.trial_policy.now=NOW+600;return result
        p.transport=identity_then_expire
        with self.assertRaises(AlphaError):fetch(p,t,'1',start_at=NOW,end_at=NOW)
        self.assertEqual(len(wire.calls),1)

if __name__=='__main__':unittest.main()
