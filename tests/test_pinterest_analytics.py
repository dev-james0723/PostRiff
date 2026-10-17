"""Synthetic official-API analytics/capability boundaries; no provider traffic or activation."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights
from postriff_phase2.growth.metric_schedule import MetricScheduler
from postriff_phase2.oauth import OAuthService
from postriff_phase2.pinterest_analytics import SCOPES, fetch, describe
from postriff_phase2.wave3_connectors import PinterestProvider
from test_hosted_wave1_connectors import Wire, ok

NOW = 1792238400
IDENTITY = ok({'id':'1234567','username':'synthetic','account_type':'BUSINESS'})
REPORT = ok({'all':{'summary_metrics':{'IMPRESSION':25,'SAVE':0,'PIN_CLICK':4,'OUTBOUND_CLICK':2}}})


def fixture(replies=(), scopes=SCOPES):
    p= PinterestProvider('1615884','SYNTHETIC',transport=Wire(replies),production_reviewed=True,analytics_enabled=True)
    token=json.dumps({'v':1,'at':'SYNTHETIC_TOKEN','environment':'production','clientId':'1615884','accountId':'1234567','scope':sorted(scopes)})
    return p,token


class PinterestAnalytics(unittest.TestCase):
    def test_official_summary_uses_bound_adapter_quota_and_native_metrics(self):
        p,t=fixture([IDENTITY,REPORT]);quota=[];p.quota_required=True;p.rate_gate=lambda *a:quota.append(a)
        r=fetch(p,t,'7654321',start_at=NOW-3600,end_at=NOW)
        self.assertEqual(r['found'],{'impressions':25,'saves':0,'pin_clicks':4,'outbound_clicks':2})
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
            self.assertEqual(r['found'],{});self.assertNotIn('SYNTHETIC_SECRET',json.dumps(r))

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
        self.assertEqual(oauth.token_for_worker.call_args.args,('w','c'));scheduler.transport.assert_not_called()
        scheduler._pinterest_schema_ready=lambda:False
        before=len(p.transport.calls);self.assertFalse(scheduler.provider_allowed('pinterest'));self.assertEqual(len(p.transport.calls),before)


if __name__=='__main__':unittest.main()
