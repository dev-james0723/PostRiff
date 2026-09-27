"""Offline policy/transport contracts. Real provider egress is never used."""
import re
import unittest
from datetime import datetime,timezone

from postriff_phase2.notifications import catalog,detector,email_render,planner,sms

NOW = datetime(2026,9,26,12,tzinfo=timezone.utc).timestamp()
ID = '00000000-0000-0000-0000-000000000001'
CONTEXT = {'enabled':True,'escalation_enabled':True,'verified':True,'consented':True,'security_sms':False}


class SMSPolicyTest(unittest.TestCase):
    def test_approval_timing_comes_from_current_scheduled_state(self):
        state={'phase2':{'reviews':[{'id':'r','status':'needs_review','manifest':{'timing':{'timestamp':NOW+3600}}}]}}
        event=detector.from_state('w',state,NOW)[0]
        self.assertTrue(event['time_sensitive'])
        self.assertEqual(event['expires_at'],NOW+3600)
        self.assertIn(':timely:',event['dedupe_key'])
        state['phase2']['reviews'][0]['manifest']['timing']['timestamp']=NOW+86401
        self.assertNotIn('time_sensitive',detector.from_state('w',state,NOW)[0])
        self.assertTrue(detector.from_state('w',state,NOW+2)[0]['time_sensitive'])
        state['phase2']['reviews'][0]['manifest']={'time_sensitive':True,'timing':{'timestamp':NOW-1}}
        self.assertNotIn('time_sensitive',detector.from_state('w',state,NOW)[0])
    def plan(self, event_type='publish.failed', prefs=None, context=None, push=True, recent=None, **event):
        out = planner.plan({'event_type':event_type,'workspace_id':'w',**event}, {'userId':ID,'time_zone':'UTC'},
                           {('*','*'):prefs if prefs is not None else {'sms_mode':'important_only'}},NOW,
                           push_available=push,recent=recent,sms_context=CONTEXT if context is None else context)
        return {d['channel']:d for d in out}

    def test_defaults_off_and_phone_verification_or_call_mode_never_grants_sms(self):
        self.assertEqual(self.plan(prefs={})['sms']['reason'],'sms_off')
        for extra in ({'verified':True},{'verified':True,'phone_enabled':True}):
            self.assertEqual(self.plan(context={**CONTEXT,**extra,'consented':False})['sms']['reason'],'sms_consent_required')

    def test_explicit_sms_consent_and_important_mode_enable_ten_minute_push_fallback(self):
        d = self.plan()['sms']
        self.assertEqual((d['status'],d['next_attempt_at']),('pending',NOW+600))

    def test_timely_approval_waits_thirty_minutes_ordinary_approval_does_not_text(self):
        self.assertEqual(self.plan('campaign.approval_required')['sms']['reason'],'not_time_sensitive')
        self.assertEqual(self.plan('campaign.approval_required',time_sensitive=True)['sms']['next_attempt_at'],NOW+1800)

    def test_push_unavailable_or_off_allows_explicit_important_text_now(self):
        self.assertEqual(self.plan(push=False)['sms']['next_attempt_at'],NOW)
        self.assertEqual(self.plan(prefs={'sms_mode':'important_only','push_mode':'off'})['sms']['next_attempt_at'],NOW)
        self.assertEqual(self.plan(push=False,prefs={})['sms']['status'],'suppressed')

    def test_smart_toggle_and_server_escalation_flag_cancel_push_fallback(self):
        self.assertEqual(self.plan(prefs={'sms_mode':'important_only','smart_escalation':False})['sms']['reason'],'smart_escalation_off')
        self.assertEqual(self.plan(context={**CONTEXT,'escalation_enabled':False})['sms']['reason'],'smart_escalation_off')

    def test_acknowledgement_resolution_expiry_and_provider_stop_suppress(self):
        cases = [({'context':{**CONTEXT,'acknowledged':True}},'acknowledged'),({'resolved':True},'resolved'),
                 ({'expires_at':NOW-1},'expired'),({'expires_at':NOW+500},'expired'),
                 ({'context':{**CONTEXT,'provider_blocked':True}},'provider_stop')]
        for kwargs,reason in cases:
            with self.subTest(reason=reason): self.assertEqual(self.plan(**kwargs)['sms']['reason'],reason)

    def test_security_requires_extra_consent_and_does_not_bypass_mute_or_quiet(self):
        self.assertEqual(self.plan('security.account_change')['sms']['reason'],'security_sms_off')
        c = {**CONTEXT,'security_sms':True}
        self.assertEqual(self.plan('security.account_change',context=c,prefs={'sms_mode':'important_only','muted_until':NOW+3600})['sms']['reason'],'muted')
        d = self.plan('security.account_change',context=c,prefs={'sms_mode':'important_only','quiet_start':0,'quiet_end':13*60,'time_zone':'UTC'})['sms']
        self.assertEqual(d['next_attempt_at'],NOW+3600)

    def test_quiet_hours_wait_until_after_push_then_escalation(self):
        p = {'sms_mode':'important_only','quiet_start':0,'quiet_end':13*60,'time_zone':'UTC'}
        self.assertEqual(self.plan(prefs=p)['sms']['next_attempt_at'],NOW+3600+600)
        self.assertEqual(self.plan(push=False,prefs=p)['sms']['next_attempt_at'],NOW+3600)

    def test_hourly_daily_limits_and_mute_are_independent_of_email_transactionality(self):
        for recent,reason in (({'sms':2},'sms_hourly_limit'),({'sms_day':4},'sms_daily_limit')):
            self.assertEqual(self.plan('billing.payment_failed',recent=recent)['sms']['reason'],reason)
        self.assertEqual(self.plan(prefs={'sms_mode':'important_only','muted_until':NOW+1})['sms']['reason'],'muted')

    def test_routine_events_are_off_and_phone_remains_a_different_channel(self):
        for kind,item in catalog.EVENTS.items():
            self.assertIn(item['sms'],('off','escalate','immediate'))
            if item['sms']=='off': self.assertNotIn('sms',self.plan(kind))
        self.assertNotEqual('sms','phone')
        self.assertEqual(catalog.MAX_ATTEMPTS['phone'],1)

    def test_sms_and_phone_can_coexist_with_separate_consents(self):
        phone_context={'prefs':{'enabled':True,'proactiveCalls':True,'quietStart':None,'quietEnd':None,'timeZone':'UTC','maxCallsPerDay':2,'eventAllowlist':['publish.failed']},
                       'verified':True,'membership':True,'configured':True,'live_configured':True,'flags':{k:True for k in ('RAFII_PHONE_ENABLED','RAFII_PHONE_OUTBOUND_ENABLED','RAFII_PHONE_PROACTIVE_ENABLED')},
                       'estimate':1,'daily_budget':10}
        rows=planner.plan({'event_type':'publish.failed','workspace_id':'w'}, {'userId':'u'}, {('*','*'):{'sms_mode':'important_only'}}, NOW,
                          phone_context=phone_context,sms_context=CONTEXT,push_available=True)
        self.assertEqual({r['channel'] for r in rows},{'in_app','email','push','sms','phone'})
        self.assertEqual(next(r for r in rows if r['channel']=='phone')['next_attempt_at'],NOW)
        self.assertEqual(next(r for r in rows if r['channel']=='sms')['next_attempt_at'],NOW+600)


class SMSTransportTest(unittest.TestCase):
    def provider(self,status=201,body=None):
        return sms.TwilioSMSTransport({'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'local-synthetic',
                                     'TWILIO_SMS_MESSAGING_SERVICE_SID':'MG'+'b'*32,'POSTRIFF_PUBLIC_BASE_URL':'https://sms.test'},
                                    transport=lambda _: (status,body or {'sid':'SM'+'c'*32}))

    def test_fake_transport_keeps_only_safe_receipt_fields(self):
        p=sms.FakeSMSTransport()
        result=p.send(number='+12025550123',text='Rafii: Check the app.',delivery_id=ID,idempotency_key='ntf-test')
        self.assertEqual(result['state'],'sent')
        self.assertNotIn('12025550123',str(p.sent)+str(result))

    def test_provider_acceptance_known_rejection_and_unknown_acceptance(self):
        for code,state in ((201,'sent'),(400,'permanent'),(429,'transient'),(408,'uncertain'),(500,'uncertain'),(0,'uncertain')):
            with self.subTest(code=code):
                result=self.provider(code).send(number='+12025550123',text='Rafii.',delivery_id=ID,idempotency_key='ntf-test')
                self.assertEqual(result['state'],state)
                self.assertNotIn('12025550123',str(result))
        self.assertEqual(self.provider(201,{'error':'private','sid':'bad'}).send(number='+12025550123',text='Rafii.',delivery_id=ID,idempotency_key='ntf-test')['state'],'uncertain')

    def test_copy_is_localized_static_private_payload_free_and_bounded(self):
        for loc in email_render.catalogue()['locales']:
            for event in sms.COPY['en']:
                out=sms.render(event,loc,'https://app.rafii.example',ID)
                self.assertLessEqual(out['segments'],2)
                self.assertIn('STOP',out['text'])
                self.assertIn('https://app.rafii.example/app?notification=',out['text'])
                self.assertNotIn('@',out['text'])
        self.assertEqual(sms.render('publish.failed','yue','https://sms.test',ID),sms.render('publish.failed','zh-Hant-HK','https://sms.test',ID))

    def test_sms_origin_and_deep_links_cannot_escape_app(self):
        for value in ('http://app.test','https://user@app.test','https://app.test/path','https://app.test?foo=bar'):
            with self.assertRaises(ValueError): sms.render('publish.failed','en',value,ID)
        for path in ('https://evil.test','/app/../private','javascript:alert(1)','//evil.test'):
            d=sms.acknowledgement_path(path,ID)
            self.assertTrue(d.startswith('/app?notification='))
            self.assertNotIn('evil',d)

    def test_provider_metrics_are_bounded_and_never_retain_private_fields(self):
        self.assertEqual(sms.receipt_metrics('2','-0.015','usd'),{'segments':2,'costUsdMicro':15000})
        self.assertEqual(sms.receipt_metrics('0','NaN','USD'),{})
        self.assertEqual(sms.receipt_metrics('100','200','USD'),{})
        self.assertEqual(sms.receipt_metrics('1','1','HKD'),{'segments':1})

    def test_every_email_template_locale_has_both_brand_elements_and_text_twin(self):
        for template in email_render.TEMPLATES:
            for locale in email_render.catalogue()['locales']:
                with self.subTest(template=template,locale=locale):
                    r=email_render.render(template,locale=locale,base_url='https://app.rafii.example')
                    degraded=re.sub(r'<img\b[^>]*>','',r['html'])
                    self.assertIn('data-rafii-wordmark="approved"',r['html'])
                    self.assertIn('data-rafii-character="approved"',r['html'])
                    self.assertIn('>Rafii</td>',degraded)
                    self.assertIn('<h1',degraded)
                    self.assertEqual(degraded.count('class="rf-cta-a"'),1)
                    self.assertIn(r['url'],r['text'])
                    self.assertLess(len(r['html'].encode()),102000)


if __name__=='__main__': unittest.main()
