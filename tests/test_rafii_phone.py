import asyncio
import base64
import hashlib
import hmac
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import live
from postriff_phase2.phone import contracts, planner
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from postriff_phase2.phone.providers.twilio import TwilioProvider
from postriff_phase2.phone.session import FAREWELL


class PhonePolicyTest(unittest.TestCase):
    def setUp(self):
        self.prefs={**contracts.DEFAULTS,'enabled':True,'proactiveCalls':True,'scheduledCalls':True,'timeZone':'America/Indiana/Indianapolis','eventAllowlist':['publish.failed']}
        self.now=datetime(2026,9,26,12,tzinfo=ZoneInfo(self.prefs['timeZone'])).timestamp()
        self.args={'now':self.now,'verified':True,'membership':True,'configured':True,'live_configured':True,
                   'flags':{f:True for f in contracts.FLAGS},'event_type':'publish.failed','estimate':600000,'daily_budget':2000000}

    def test_proactive_defaults_off(self):
        prefs={**contracts.DEFAULTS,'enabled':True}
        self.assertEqual(planner.eligibility('proactive',prefs,**self.args),'proactive_off')

    def test_each_hard_gate(self):
        for key,reason in [('verified','phone_unverified'),('membership','membership'),('configured','provider_unavailable'),('live_configured','live_unavailable')]:
            with self.subTest(key=key):
                self.assertEqual(planner.eligibility('explicit',self.prefs,**{**self.args,key:False}),reason)

    def test_egress_flags_independent(self):
        for flag in ('RAFII_PHONE_ENABLED','RAFII_PHONE_OUTBOUND_ENABLED'):
            args={**self.args,'flags':{**self.args['flags'],flag:False}}
            self.assertIsNotNone(planner.eligibility('explicit',self.prefs,**args))

    def test_overnight_quiet_hours_boundaries(self):
        for hour,minute,blocked in [(21,59,False),(22,0,True),(23,59,True),(7,59,True),(8,0,False)]:
            now=datetime(2026,9,26,hour,minute,tzinfo=ZoneInfo(self.prefs['timeZone'])).timestamp()
            args={**self.args,'now':now}
            self.assertEqual(planner.eligibility('proactive',self.prefs,**args)=='quiet_hours',blocked)
            self.assertIsNone(planner.eligibility('explicit',self.prefs,**args))

    def test_dst_and_daily_boundary(self):
        tz=ZoneInfo('America/New_York')
        for fold in (0,1):
            now=datetime(2026,11,1,1,30,tzinfo=tz,fold=fold).timestamp()
            self.assertEqual(planner.eligibility('scheduled',{**self.prefs,'timeZone':tz.key},**{**self.args,'now':now}),'quiet_hours')
            self.assertEqual(datetime.fromtimestamp(planner.day_start(now,tz.key),tz).hour,0)

    def test_daily_and_cost_limits(self):
        self.assertEqual(planner.eligibility('proactive',self.prefs,**{**self.args,'daily_calls':2}),'daily_limit')
        self.assertEqual(planner.eligibility('explicit',self.prefs,**{**self.args,'daily_calls':6}),'explicit_daily_limit')
        self.assertEqual(planner.eligibility('explicit',self.prefs,**{**self.args,'reserved_cost':1500000}),'phone_budget')

    def test_no_routine_billing_security_calls(self):
        for event in ('publish.succeeded','campaign.drafts_ready','billing.payment_failed','security.new_device'):
            self.assertEqual(planner.eligibility('proactive',self.prefs,**{**self.args,'event_type':event}),'event_not_allowed')

    def test_no_duplicate_or_concurrent_calls(self):
        self.assertIsNone(planner.eligibility('explicit',self.prefs,**{**self.args,'recent_equivalent':True}))
        self.assertEqual(planner.eligibility('proactive',self.prefs,**{**self.args,'recent_equivalent':True}),'recent_equivalent')
        self.assertEqual(planner.eligibility('scheduled',self.prefs,**{**self.args,'recent_equivalent':True}),'recent_equivalent')
        self.assertEqual(planner.eligibility('explicit',self.prefs,**{**self.args,'active':True}),'call_active')

    def test_preferences_validation(self):
        for patch in ({'enabled':'yes'},{'timeZone':'Invalid/Zone'},{'maxCallsPerDay':99},{'maxMilliCreditsPerCall':True},{'maxMilliCreditsPerCall':-1},{'maxMilliCreditsPerCall':100_000_001},{'eventAllowlist':['security.new_device']},{'phoneNumber':'+123456789'}):
            with self.assertRaises(AlphaError):contracts.preferences(patch)
        self.assertEqual(contracts.preferences({}),contracts.DEFAULTS)

    def test_e164_and_hangup(self):
        for value in ('4155550123','+123','+1 415 555 0123','javascript:1'):
            with self.assertRaises(AlphaError):contracts.phone_number(value)
        self.assertEqual(contracts.phone_number('+14155550123'),'+14155550123')
        for text in ('goodbye','Hang up.','Please hang up now.','Can you end this call?','Okay, bye.','收線','幫我收線','再見','请挂断电话'):
            self.assertTrue(FAREWELL.fullmatch(text))
        for text in ('write a goodbye post','do not hang up','explain how to hang up'):
            self.assertFalse(FAREWELL.fullmatch(text))


class PhoneTransportTest(unittest.TestCase):
    def test_fake_lifecycle_outcomes(self):
        for state in ('ringing','busy','declined','no_answer','failed','ambiguous','voicemail'):
            provider=FakeTelephonyProvider(state)
            receipt=provider.create_outbound_call(number='+14155550123',call_id='one',max_seconds=600)
            self.assertEqual(receipt.state,state)
            if state=='ambiguous':
                self.assertIsNone(receipt.call_ref)
                self.assertEqual(provider.reconcile(number='',call_id='one',call_ref=None,requested_at=0).call_ref,'fake_one')
            self.assertNotIn('+14155550123',str(provider.__dict__))
            self.assertEqual(provider.create_count,1)

    def test_monotonic_webhooks(self):
        self.assertEqual(contracts.transition('live','ringing'),'live')
        self.assertEqual(contracts.transition('completed','answered'),'completed')
        self.assertEqual(contracts.transition('ambiguous','answered'),'answered')

    def test_signed_fake_webhook(self):
        p=FakeTelephonyProvider();event={'callRef':'fake_one','state':'answered','eventId':'one'}
        sig=p.sign('https://example.test/hook',event)
        self.assertTrue(p.verify_webhook('https://example.test/hook',event,sig))
        self.assertFalse(p.verify_webhook('https://example.test/hook',{**event,'state':'completed'},sig))

    def twilio(self,transport=None):
        return TwilioProvider({'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'12345','TWILIO_PHONE_NUMBER':'+14155550123','RAFII_PHONE_PUBLIC_BASE_URL':'https://example.test'},transport=transport)

    def test_twilio_signature_and_tamper(self):
        p=self.twilio();url='https://example.test/hook';params={'CallSid':['CA'+'b'*32],'CallStatus':['ringing'],'SequenceNumber':['1']}
        signed=url+'CallSid'+'CA'+'b'*32+'CallStatusringingSequenceNumber1'
        sig=base64.b64encode(hmac.new(b'12345',signed.encode(),hashlib.sha1).digest()).decode()
        self.assertTrue(p.verify_webhook(url,params,sig))
        self.assertFalse(p.verify_webhook(url+'/',params,sig))
        self.assertFalse(p.verify_webhook(url,params,'invalid'))

    def test_twilio_create_cap_no_recording_and_callbacks(self):
        requests=[]
        def transport(method,url,fields=None):
            requests.append((method,url,fields));return 201,{'sid':'CA'+'c'*32,'status':'queued'}
        receipt=self.twilio(transport).create_outbound_call(number='+14155550111',call_id='one',max_seconds=3600)
        self.assertEqual(receipt.state,'ringing')
        fields=requests[0][2]
        self.assertIn(('TimeLimit','600'),fields);self.assertIn(('Record','false'),fields)
        self.assertEqual([v for k,v in fields if k=='StatusCallbackEvent'],['initiated','ringing','answered','completed'])

    def test_twilio_ambiguous_create_never_retries(self):
        for status in (0,408,500,201):
            calls=[]
            def transport(method,url,fields=None):calls.append(method);return status,{}
            p=self.twilio(transport)
            self.assertEqual(p.create_outbound_call(number='+14155550111',call_id='one',max_seconds=600).state,'ambiguous')
            p.reconcile(number='+14155550111',call_id='one',call_ref=None,requested_at=0)
            self.assertEqual(calls,['POST','GET'])

    def test_twilio_rejection_has_safe_reason_and_no_payload(self):
        for status, code, reason in [(401,20003,'provider_auth'), (400,21219,'provider_trial_recipient'),
                                    (400,21215,'provider_country'), (403,21216,'provider_destination'),
                                    (400,21212,'provider_caller'), (429,20429,'provider_rate_limit'),
                                    (400,99999,'provider_rejected')]:
            calls=[]
            def transport(method,url,fields=None):
                calls.append(method)
                return status,{'code':code,'message':'Private recipient +14155550111 and credentials'}
            receipt=self.twilio(transport).create_outbound_call(number='+14155550111',call_id='one',max_seconds=600)
            self.assertEqual(receipt.state,'failed')
            self.assertEqual(receipt.failure,reason)
            self.assertIsNone(receipt.call_ref)
            self.assertEqual(calls,['POST'])
            self.assertNotIn('+14155550111',str(receipt))

    def test_twilio_http_error_retains_only_numeric_code(self):
        for body, expected in [(json.dumps({'code':21219,'message':'Private +14155550111','more_info':'https://private.test'}).encode(), {'code':21219}),
                               (b'invalid body +14155550111', {}), (b'{"code":"21219"}', {})]:
            error=HTTPError('https://api.twilio.com',400,'bad request',{},io.BytesIO(body))
            with patch('postriff_phase2.phone.providers.twilio.build_opener') as opener:
                opener.return_value.open.side_effect=error
                p=self.twilio()
                self.assertEqual(p._http('POST',p._calls(),[]),(400,expected))

    def test_twilio_status_and_voicemail_xml(self):
        p=self.twilio()
        for status,state in [('busy','busy'),('no-answer','no_answer'),('failed','failed'),('canceled','declined'),('completed','completed')]:
            event=p.normalize_event({'AccountSid':p.account,'CallSid':'CA'+'c'*32,'CallStatus':status,'CallDuration':'42','SequenceNumber':'1'})
            self.assertEqual(event.state,state);self.assertEqual(event.duration_seconds,42)
        self.assertIn('wss://example.test/api/phone/media/one',p.answer_xml('one'))
        self.assertEqual(p.answer_xml('one',voicemail=True),'<Response><Hangup/></Response>')

    def test_shared_live_policy_and_verified_result(self):
        browser=live.session_config('gpt-live-1','en','marin',history='recap',browser=True)
        phone=live.session_config('gpt-live-1','en','marin',history='recap')
        self.assertEqual({k:v for k,v in browser.items() if k!='client'},phone)
        self.assertFalse(phone['store']);self.assertEqual(phone['delegation'],{'type':'client'})
        payload=live.delegation_payload('conversation','edit it','phone:test')
        self.assertEqual(payload['modality'],'voice');self.assertEqual(payload['uiCapabilities'],[])
        self.assertEqual(live.speakable_result({'body':{'agent':{'speakableSummary':'Saved the revised draft.'}}}),'Saved the revised draft.')
        self.assertEqual(live.speakable_result({'result':{'speakableSummary':'Verified runtime result.'}}),'Verified runtime result.')


if __name__=='__main__':unittest.main()
