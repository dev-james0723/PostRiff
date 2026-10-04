import asyncio
import base64
import hashlib
import hmac
import io
import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import unittest
from datetime import datetime
from contextlib import contextmanager
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import live
from postriff_phase2.phone import contracts, planner, rules
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from postriff_phase2.phone.providers.twilio import TwilioProvider
from postriff_phase2.phone.session import FAREWELL
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.permissions import Membership


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
        for count in (6, 7, 1000):
            self.assertIsNone(planner.eligibility('explicit',self.prefs,**{**self.args,'daily_calls':count}))
        self.assertEqual(planner.eligibility('scheduled',self.prefs,**{**self.args,'daily_calls':2}),'daily_limit')
        self.assertIsNone(planner.eligibility('explicit',self.prefs,**{**self.args,'reserved_cost':1500000}))

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


class CallDurationLimitTest(unittest.TestCase):
    def test_omitted_limit_preserves_the_product_maximum_for_every_call_kind(self):
        for kind, inbound in [('explicit', False), ('scheduled', False), ('proactive', False), ('explicit', True)]:
            with self.subTest(kind=kind, inbound=inbound):
                self.assertEqual(contracts.call_duration_limit({}, 3600, kind=kind, inbound=inbound), 3600)

    def test_supplied_limit_accepts_exact_integer_boundaries(self):
        for maximum, value in [(3600, 60), (3600, 61), (3600, 3600), (120, 120)]:
            with self.subTest(maximum=maximum, value=value):
                self.assertEqual(contracts.call_duration_limit({'callDurationLimitSeconds': value}, maximum), value)

    def test_supplied_limit_rejects_wrong_types_and_values_outside_the_server_cap(self):
        for value in [True, False, None, '60', 60.0, [], {}, -1, 0, 59, 3601]:
            with self.subTest(value=value):
                with self.assertRaises(AlphaError) as raised:
                    contracts.call_duration_limit({'callDurationLimitSeconds': value}, 3600)
                self.assertEqual(raised.exception.status, 400)
        with self.assertRaises(AlphaError) as raised:
            contracts.call_duration_limit({'callDurationLimitSeconds': 121}, 120)
        self.assertEqual(raised.exception.status, 400)

    def test_supplied_limit_is_only_available_to_explicit_outbound_calls(self):
        for kind, inbound in [('scheduled', False), ('proactive', False), ('explicit', True)]:
            with self.subTest(kind=kind, inbound=inbound):
                with self.assertRaises(AlphaError) as raised:
                    contracts.call_duration_limit({'callDurationLimitSeconds': 60}, 3600, kind=kind, inbound=inbound)
                self.assertEqual(raised.exception.status, 400)


class PhoneRequestDurationRetryTest(unittest.TestCase):
    def setUp(self):
        self.cursor = Mock()
        self.cursor.fetchone.return_value = ('existing-call', 'workspace')
        self.member = Membership('owner')

        @contextmanager
        def transaction(token, workspace):
            self.assertEqual((token, workspace), ('session', 'workspace'))
            yield self.cursor, object(), 'principal'

        hosted = SimpleNamespace(clock=lambda: 1000, oauth=SimpleNamespace(vault=object()),
                                 repository=SimpleNamespace(transaction=transaction),
                                 ideas=SimpleNamespace(_member=lambda row: self.member))
        runtime = SimpleNamespace(cfg=SimpleNamespace(route=Mock(return_value=SimpleNamespace(available=True))))
        self.provider = FakeTelephonyProvider()
        self.phone = PhoneService(hosted, {'RAFII_PHONE_ENABLED': '1'}, provider=self.provider, runtime=runtime)
        self.call = {'id': 'existing-call', 'conversation_id': 'conversation', 'state': 'ambiguous',
                     'kind': 'explicit', 'provider': 'fake', 'direction': 'outbound', 'requested_at': 1000,
                     'duration_seconds': None, 'failure_class': None, 'max_seconds': 60}

    def test_omitted_or_identical_limit_returns_the_original_call_without_dispatch(self):
        for cap in (60, 3600):
            self.call['max_seconds'] = cap
            for extra in ({}, {'callDurationLimitSeconds': cap}):
                with self.subTest(cap=cap, extra=extra), \
                        patch('postriff_phase2.phone.service.store.call', return_value=self.call) as stored, \
                        patch('postriff_phase2.phone.delivery.deliver') as deliver:
                    result = self.phone.request('workspace', 'session', {'idempotencyKey': 'same-request', **extra})
                    self.assertEqual((result['id'], result['maxSeconds'], result['state']), ('existing-call', cap, 'ambiguous'))
                    stored.assert_called_once_with(self.cursor, 'existing-call')
                    deliver.assert_not_called()
                    self.assertEqual(self.call['max_seconds'], cap)
        self.assertEqual(self.provider.create_count, 0)

    def test_a_changed_supplied_limit_conflicts_without_mutating_or_redialing(self):
        for old_cap, requested in [(3600, 60), (60, 120)]:
            self.call['max_seconds'] = old_cap
            with self.subTest(old_cap=old_cap, requested=requested), \
                    patch('postriff_phase2.phone.service.store.call', return_value=self.call), \
                    patch('postriff_phase2.phone.delivery.deliver') as deliver:
                with self.assertRaises(AlphaError) as raised:
                    self.phone.request('workspace', 'session', {'idempotencyKey': 'same-request', 'callDurationLimitSeconds': requested})
                self.assertEqual(raised.exception.status, 409)
                self.assertEqual(self.call['max_seconds'], old_cap)
                deliver.assert_not_called()
        self.assertEqual(self.provider.create_count, 0)

    def test_cross_workspace_denial_precedes_duration_conflict_and_call_lookup(self):
        self.cursor.fetchone.return_value = ('existing-call', 'other-workspace')
        with patch('postriff_phase2.phone.service.store.call') as stored, \
                patch('postriff_phase2.phone.delivery.deliver') as deliver, self.assertRaises(AlphaError) as raised:
            self.phone.request('workspace', 'session', {'idempotencyKey': 'same-request', 'callDurationLimitSeconds': 120})
        self.assertEqual(raised.exception.status, 404)
        stored.assert_not_called()
        deliver.assert_not_called()

    def test_existing_key_does_not_bypass_edit_permission(self):
        self.member = Membership('viewer')
        with patch('postriff_phase2.phone.service.store.call') as stored, \
                patch('postriff_phase2.phone.delivery.deliver') as deliver, self.assertRaises(AlphaError) as raised:
            self.phone.request('workspace', 'session', {'idempotencyKey': 'same-request', 'callDurationLimitSeconds': 60})
        self.assertEqual(raised.exception.status, 403)
        stored.assert_not_called()
        deliver.assert_not_called()


class CustomCallRuleTest(unittest.TestCase):
    RULE_ID = 'b85919c0-2f06-4db9-9486-301ae01bf204'

    def draft(self, when='Call me if a scheduled post fails twice in one day', discuss='Tell me which post failed and why'):
        return {'id': self.RULE_ID, 'when': when, 'discuss': discuss, 'enabled': False}

    def test_review_then_activation_and_edit_revocation(self):
        first = contracts.preferences({'customRules': [self.draft()]})['customRules'][0]
        self.assertFalse(first['enabled'])
        self.assertEqual((first['eventType'], first['countAtLeast'], first['sameEntity']), ('publish.failed', 2, True))
        active = contracts.preferences({'customRules': [{**first, 'enabled': True}]}, {'customRules': [first]})['customRules'][0]
        self.assertTrue(active['enabled'])
        edited = contracts.preferences({'customRules': [{**active, 'discuss': 'Explain the failure', 'enabled': True}]},
                                       {'customRules': [active]})['customRules'][0]
        self.assertFalse(edited['enabled'])
        self.assertNotEqual(edited['version'], active['version'])

    def test_unsupported_or_ambiguous_conditions_fail_closed(self):
        for when in ('Call me if a post fails and costs over $100', 'Call me when a trend looks promising',
                     'Call me when a payment fails', 'Do not call me when a post fails'):
            with self.subTest(when=when), self.assertRaises(AlphaError):
                contracts.preferences({'customRules': [self.draft(when=when)]})
        with self.assertRaises(AlphaError):
            contracts.preferences({'customRules': [self.draft()] * 6})

    def test_supported_situations_compile_to_exact_events(self):
        examples = {
            'Call me if a post fails': 'publish.failed',
            'Call me if publication outcome is uncertain': 'publish.uncertain',
            'Call me if approval is due within 24 hours': 'campaign.approval_required',
            'Call me if a campaign is blocked': 'campaign.blocked',
            'Call me if a channel needs reconnection': 'channel.reconnect_required',
        }
        for when, event in examples.items():
            with self.subTest(when=when):
                self.assertEqual(contracts.preferences({'customRules': [self.draft(when=when)]})['customRules'][0]['eventType'], event)

    def test_custom_rule_respects_shared_hard_gates(self):
        initial = contracts.preferences({'customRules': [self.draft()]})['customRules'][0]
        active = contracts.preferences({'customRules': [{**initial, 'enabled': True}]}, {'customRules': [initial]})['customRules'][0]
        prefs = {**contracts.DEFAULTS, 'enabled': True, 'proactiveCalls': True, 'customRules': [active]}
        now = datetime(2026, 9, 28, 12, tzinfo=ZoneInfo('UTC')).timestamp()
        args = {'now': now, 'verified': True, 'membership': True, 'configured': True, 'live_configured': True,
                'flags': {f: True for f in contracts.FLAGS}, 'event_type': 'publish.failed',
                'custom_rule_ref': (active['id'], active['version']), 'estimate': 100, 'daily_budget': 1000}
        self.assertIsNone(planner.eligibility('proactive', prefs, **args))
        self.assertEqual(planner.eligibility('proactive', prefs, **{**args, 'daily_calls': 2}), 'daily_limit')
        self.assertEqual(planner.eligibility('proactive', prefs, **{**args, 'verified': False}), 'phone_unverified')
        self.assertEqual(planner.eligibility('proactive', prefs, **{**args, 'reserved_cost': 950}), 'phone_budget')
        self.assertEqual(planner.eligibility('proactive', prefs, **{**args, 'custom_rule_ref': (active['id'], '0'*16)}), 'event_not_allowed')

    def test_count_and_cooldown_use_workspace_and_same_entity(self):
        initial = contracts.preferences({'customRules': [self.draft()]})['customRules'][0]
        active = contracts.preferences({'customRules': [{**initial, 'enabled': True}]}, {'customRules': [initial]})['customRules'][0]
        class Cursor:
            def __init__(self, count, prior=False): self.count, self.prior, self.calls = count, prior, []
            def execute(self, query, params): self.calls.append((query, params))
            def fetchone(self):
                return (1,) if self.prior else None if len(self.calls) == 1 else (self.count,)
        for count, prior, expected in ((1, False, None), (2, False, active), (3, True, None)):
            cur = Cursor(count, prior)
            self.assertEqual(rules.matching(cur, {'customRules': [active]}, 'user', 'workspace', 'publish.failed', 'post-1', 100000), expected)
            if not prior:
                self.assertEqual(cur.calls[1][1][-2:], (True, 'post-1'))
        self.assertIsNone(rules.matching(Cursor(3), {'customRules': [active]}, 'user', 'workspace', 'publish.failed', None, 100000))


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

    def test_twilio_machine_detection_can_be_disabled_for_bounded_james_trial(self):
        requests = []
        def transport(method, url, fields=None):
            requests.append((method, fields))
            return 201, {'sid':'CA'+'c'*32, 'status':'queued'}
        p = self.twilio(transport)
        self.assertEqual(
            p.create_outbound_call(number='+14155550111', call_id='one', max_seconds=180, detect_machine=False).state,
            'ringing',
        )
        self.assertNotIn(('MachineDetection','Enable'), requests[0][1])
        requests.clear()
        self.assertEqual(
            p.create_outbound_call(number='+14155550111', call_id='two', max_seconds=180).state,
            'ringing',
        )
        self.assertIn(('MachineDetection','Enable'), requests[0][1])

    def test_twilio_ambiguous_create_never_retries(self):
        for status in (0,408,500,201):
            calls=[]
            def transport(method,url,fields=None):calls.append(method);return status,{}
            p=self.twilio(transport)
            self.assertEqual(p.create_outbound_call(number='+14155550111',call_id='one',max_seconds=600).state,'ambiguous')
            p.reconcile(number='+14155550111',call_id='one',call_ref=None,requested_at=0)
            self.assertEqual(calls,['POST','GET'])

    def test_twilio_preserves_a_shorter_per_call_limit_in_its_only_create_request(self):
        requests = []
        def transport(method, url, fields=None):
            requests.append((method, fields))
            return 201, {'sid': 'CA' + 'c' * 32, 'status': 'queued'}
        receipt = self.twilio(transport).create_outbound_call(number='+14155550111', call_id='short-call', max_seconds=60)
        self.assertEqual(receipt.state, 'ringing')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], 'POST')
        self.assertIn(('TimeLimit', '60'), requests[0][1])

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
