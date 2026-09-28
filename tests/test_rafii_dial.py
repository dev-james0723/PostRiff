"""Dial contract/security tests. All HTTP, sockets and SMS are synthetic; no provider egress."""
import asyncio
import copy
import hashlib
import hmac
import io
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from postriff_phase2.phone.providers.dial import DialProvider, DialMediaTransport, state
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.config import PhoneConfig
from postriff_phase2.permissions import Membership
from postriff_alpha.domain import AlphaError
from postriff_phase2.phone.asgi import create_lazy_app
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

CALL = '00000000-0000-0000-0000-000000000001'
VALUES = {'DIAL_API_KEY':'sk_live_synthetic', 'DIAL_PHONE_NUMBER':'+12025550100',
          'DIAL_AUDIO_SIGNING_SECRET':'audio-synthetic', 'DIAL_WEBHOOK_SIGNING_SECRET':'webhook-synthetic',
          'DIAL_VERIFICATION_SECRET':'v'*32, 'RAFII_PHONE_PUBLIC_BASE_URL':'https://phone.test'}


def sign(secret, payload, at=1000):
    return 't='+str(at)+',v1='+hmac.new(secret.encode(),str(at).encode()+b'.'+payload,hashlib.sha256).hexdigest()


class DialFixture:
    def __init__(self):
        self.requests=[]
        self.config={'enabled':True,'access':'granted','activeMode':'audio','audio':{
            'wsUrl':'wss://phone.test/api/phone/dial/media','audioInboundFormat':'mulaw_8000','audioOutboundFormat':'mulaw_8000'}}
        self.call={'id':'call_test','direction':'outbound','from':'+12025550100','to':'+12025550123',
                   'instruction':DialProvider.instruction(CALL),'status':'ringing','duration':0}
        self.create_status=201
        self.line={'number':'+12025550100','setupStatus':'ready','callingEnabled':True,'capabilities':['call','sms']}

    def __call__(self, method, path, fields=None, headers=None):
        self.requests.append((method,path,fields,headers))
        if path=='/self-hosted': return 200,copy.deepcopy(self.config)
        if path=='/numbers': return 200,{'numbers':[copy.deepcopy(self.line)]}
        if path=='/account': return 200,{'limits':{'maxCallDurationSeconds':300}}
        if path=='/messages': return 201,{'message':{'id':'message_synthetic'}}
        if path=='/calls' and method=='POST': return self.create_status,{'call':copy.deepcopy(self.call)}
        if path=='/calls': return 200,{'calls':[copy.deepcopy(self.call)]}
        return 200,{'call':copy.deepcopy(self.call)}


class DialTests(unittest.TestCase):
    def setUp(self):
        self.http=DialFixture()
        self.provider=DialProvider(VALUES,transport=self.http,clock=lambda:1000)

    def test_create_is_same_agent_only_idempotent_and_free_account_capped(self):
        receipt=self.provider.create_outbound_call(number='+12025550123',call_id=CALL,max_seconds=600)
        self.assertEqual((receipt.state,receipt.call_ref),('ringing','call_test'))
        request=self.http.requests[-1]
        self.assertEqual(request[3],{'Idempotency-Key':'rafii-phone:'+CALL})
        self.assertEqual(request[2]['maxCallDurationSeconds'],300)
        self.assertEqual(request[2]['fromNumber'],VALUES['DIAL_PHONE_NUMBER'])
        self.assertNotIn('record',request[2])

    def test_managed_llm_wrong_url_or_formats_never_dial(self):
        for key,value in [('access','pending'),('enabled',False),('activeMode','llm'),('audio',{'wsUrl':'wss://other.test'})]:
            with self.subTest(key=key):
                fixture=DialFixture();fixture.config[key]=value
                provider=DialProvider(VALUES,transport=fixture)
                self.assertEqual(provider.create_outbound_call(number='+12025550123',call_id=CALL,max_seconds=60).state,'failed')
                self.assertFalse(any(r[0]=='POST' for r in fixture.requests))

    def test_readiness_reports_safe_stage_without_provider_body_or_call(self):
        fixture=DialFixture()
        fixture.config['audio']['wsUrl']='wss://other.test/private'
        provider=DialProvider(VALUES,transport=fixture)
        self.assertEqual(provider.readiness(),{'ready':False,'reason':'provider_account','stage':'self_hosted_url'})
        self.assertFalse(any(r[0]=='POST' for r in fixture.requests))

        def denied(method,path,*_args):
            return 403,{'error':'private destination and credential'}
        provider.transport=denied
        self.assertEqual(provider.readiness(),{'ready':False,'reason':'provider_account','stage':'self_hosted_http','httpStatus':403})

    def test_provider_readiness_requires_workspace_owner(self):
        class Repository:
            @contextmanager
            def transaction(self,_token,_workspace):
                yield None, {}, 'user'
        fixture=DialFixture()
        provider=DialProvider(VALUES,transport=fixture)
        member=Membership('viewer')
        service=object.__new__(PhoneService)
        service.config=PhoneConfig({'RAFII_PHONE_ENABLED':'1'})
        service.provider=provider
        service.hosted=SimpleNamespace(repository=Repository(),ideas=SimpleNamespace(_member=lambda _row:member))
        with self.assertRaises(AlphaError):
            service.provider_readiness('workspace','session')
        self.assertEqual(fixture.requests,[])
        member=Membership('owner')
        self.assertTrue(service.provider_readiness('workspace','session')['ready'])
        self.assertEqual([r[:2] for r in fixture.requests],[('GET','/self-hosted'),('GET','/numbers'),('GET','/account')])

    def test_10dlc_readiness_reports_sms_block_without_disabling_verified_voice(self):
        cases=[(None,'not_applicable',True),({'status':'approved'},'approved',True)]
        cases += [({'status':status},status,False) for status in
                  ('not_registered','in_review','with_carrier','rejected')]
        cases += [({},'unknown',False),({'status':[]},'unknown',False)]
        for registration,expected_status,sms_ready in cases:
            with self.subTest(registration=registration):
                self.http.line['tenDlc']=registration
                readiness=self.provider.readiness()
                self.assertEqual((readiness['ready'],readiness['smsReady'],readiness['smsRegistration']),
                                 (True,sms_ready,expected_status))
                receipt=self.provider.create_outbound_call(number='+12025550123',call_id=CALL,max_seconds=60)
                self.assertEqual(receipt.state,'ringing')

    def test_unknown_response_has_no_automatic_retry(self):
        self.http.create_status=0
        self.assertEqual(self.provider.create_outbound_call(number='+12025550123',call_id=CALL,max_seconds=60).state,'ambiguous')
        self.assertEqual(sum(r[:2]==('POST','/calls') for r in self.http.requests),1)

    def test_non_2xx_guarantees_no_call_and_safe_failure(self):
        for status in (400,401,402,403,404,429,500,503):
            self.http.create_status=status
            self.assertEqual(self.provider.create_outbound_call(number='+12025550123',call_id=CALL,max_seconds=60).state,'failed')

    def test_reconcile_exact_attempt_without_redial_and_reject_foreign_call(self):
        for ref in (None,'call_test'):
            result=self.provider.reconcile(number='+12025550123',call_id=CALL,call_ref=ref,requested_at=1000)
            self.assertEqual(result.call_ref,'call_test')
        self.assertFalse(any(r[0]=='POST' for r in self.http.requests))
        self.http.call['instruction']='Unrelated call'
        self.assertEqual(self.provider.reconcile(number='+12025550123',call_id=CALL,call_ref=None,requested_at=1000).state,'ambiguous')
        self.http.call['instruction']=DialProvider.instruction(CALL)
        self.http.call['to']='+12025550124'
        self.assertEqual(self.provider.reconcile(number='+12025550123',call_id=CALL,call_ref='call_test',requested_at=1000).state,'ambiguous')

    def test_ending_is_confirmed_by_authoritative_read_only(self):
        self.assertFalse(self.provider.end_call('call_test'))
        self.http.call['status']='completed'
        self.assertTrue(self.provider.end_call('call_test'))
        self.assertFalse(any(r[0]=='POST' for r in self.http.requests))

    def test_http_discards_error_body_and_refuses_untrusted_endpoints(self):
        error=HTTPError('https://api.getdial.ai',402,'private',{},io.BytesIO(b'{"error":"private +12025550123"}'))
        with patch('postriff_phase2.phone.providers.dial.build_opener') as opener:
            opener.return_value.open.side_effect=error
            self.assertEqual(self.provider._http('POST','/calls',{}),(402,{}))
        with self.assertRaises(ValueError):self.provider._http('GET','//evil.test')

    def test_signed_raw_body_tamper_timestamp_duplicates_and_socket_identity(self):
        raw=b'{"id":"evt_test","type":"webhook.ping"}'
        header=sign(VALUES['DIAL_WEBHOOK_SIGNING_SECRET'],raw)
        url='https://phone.test/api/phone/dial/events'
        self.assertTrue(self.provider.verify_webhook(url,{'_raw':raw},header))
        for bad in (header+',t=1000',header.replace('t=1000','t=700'),'invalid'):
            self.assertFalse(self.provider.verify_webhook(url,{'_raw':raw},bad))
        self.assertFalse(self.provider.verify_webhook(url,{'_raw':raw+b' '},header))
        media=sign(VALUES['DIAL_AUDIO_SIGNING_SECRET'],b'call_test')
        self.assertTrue(self.provider.verify_media('call_test',media))
        self.assertFalse(self.provider.verify_media('call_other',media))

    def test_otp_is_hashed_number_bound_expiring_and_uses_sms(self):
        with patch('postriff_phase2.phone.providers.dial.secrets.randbelow',return_value=123456):
            ref=self.provider.start_verification('+12025550123')
        self.assertNotIn('123456',ref)
        self.assertNotIn('channel',self.http.requests[-1][2])  # Standard SMS line's documented default.
        self.assertTrue(self.provider.check_verification('+12025550123','123456',reference=ref))
        self.assertFalse(self.provider.check_verification('+12025550124','123456',reference=ref))
        self.assertFalse(self.provider.check_verification('+12025550123','000000',reference=ref))
        self.assertFalse(self.provider.check_verification('+12025550123','123456'))
        self.provider.clock=lambda:1600
        self.assertFalse(self.provider.check_verification('+12025550123','123456',reference=ref))

    def test_imessage_line_cannot_silently_replace_sms_verification(self):
        def transport(method,path,fields=None,headers=None):
            self.assertEqual((method,path),('GET','/numbers'))
            return 200,{'numbers':[{'number':VALUES['DIAL_PHONE_NUMBER'],'setupStatus':'ready','capabilities':['sms','call','imessage']}]}
        self.provider.transport=transport
        with self.assertRaises(ValueError):self.provider.start_verification('+12025550123')

    def test_lifecycle_object_and_terminal_event_contract(self):
        self.assertEqual(state({'status':{'state':'In-Progress'}}),'answered')
        self.assertEqual(state({'status':{'state':'Terminated'},'terminationType':'no-answer'}),'no_answer')
        event={'id':'evt_1','type':'call.ended','relatedObject':{'id':'call_test'},'data':{
            'callId':'call_test','direction':'outbound','from':'+12025550100','status':'completed','durationSeconds':42}}
        self.assertEqual(self.provider.normalize_event(event).duration_seconds,42)
        event['data']['direction']='inbound'
        with self.assertRaises(ValueError):self.provider.normalize_event(event)

    def test_dial_lazy_kill_switch_initializes_nothing(self):
        def fail():raise AssertionError('Runtime should remain unloaded')
        with TestClient(create_lazy_app(values={},application_factory=fail)) as client:
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect('/api/phone/dial/media/call_test'):pass
            self.assertEqual(error.exception.code,1008)


class Socket:
    def __init__(self):self.frames=asyncio.Queue();self.sent=[]
    async def receive_text(self):return await self.frames.get()
    async def send_json(self,event):self.sent.append(event)


class DialMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_keepalive_runs_before_model_or_audio_consumer(self):
        socket=Socket();transport=DialMediaTransport(socket,require_acceptance=False)
        await socket.frames.put(json.dumps({'type':'ping_pong','timestamp':42}))
        await socket.frames.put(json.dumps({'type':'media','payload':'ZmFrZQ==','seq':1}))
        await asyncio.sleep(.01)
        self.assertEqual(socket.sent,[{'type':'ping_pong','timestamp':42}])
        self.assertEqual(await transport.receive_audio(),'ZmFrZQ==')
        await transport.interrupt();await transport.send_audio('ZmFrZQ==')
        await socket.frames.put(json.dumps({'type':'call_ended','reason':'caller_hangup'}))
        self.assertIsNone(await transport.receive_audio())
        await transport.close()

    async def test_end_frame_and_no_rest_claim_before_call_ended(self):
        socket=Socket();transport=DialMediaTransport(socket)
        task=asyncio.create_task(transport.end_call())
        await asyncio.sleep(.01)
        self.assertEqual(socket.sent,[{'type':'end_call'}])
        self.assertFalse(transport.ended)
        await socket.frames.put(json.dumps({'type':'call_ended','reason':'customer_hangup'}))
        await task
        self.assertTrue(transport.ended)
        await transport.close()

    async def test_invalid_media_fences_the_stream(self):
        socket=Socket();transport=DialMediaTransport(socket,require_acceptance=False)
        await socket.frames.put(json.dumps({'type':'media','payload':'invalid!!!'}))
        with self.assertRaises(ValueError):await transport.receive_audio()
        await transport.close()

    async def test_no_audio_or_private_session_before_keypad_acceptance(self):
        socket=Socket();transport=DialMediaTransport(socket)
        await socket.frames.put(json.dumps({'type':'media','payload':'ZmFrZQ=='}))
        await socket.frames.put(json.dumps({'type':'dtmf','digit':'1'}))
        self.assertTrue(await transport.accept_call(timeout=.1))
        self.assertTrue(transport.audio.empty())
        self.assertEqual(socket.sent[-1],{'type':'clear'})
        await transport.close()

    async def test_decline_and_voicemail_timeout_never_accept(self):
        for digit in ('2',None):
            socket=Socket();transport=DialMediaTransport(socket)
            if digit:await socket.frames.put(json.dumps({'type':'dtmf','digit':digit}))
            self.assertFalse(await transport.accept_call(timeout=.01))
            self.assertFalse(transport.accepted)
            await transport.close()


if __name__=='__main__':unittest.main()
