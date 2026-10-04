"""Twilio Programmable Voice + bidirectional Media Streams. No SDK types escape this adapter.

Protocol verified 2026-09-26 against official Calls, Media Streams and request-validation documentation.
The audio bridge speaks GPT-Live, not the incompatible Realtime API event protocol.
"""
import base64
import hashlib
import hmac
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener
from xml.sax.saxutils import escape

from ...agent_runtime_v2.creative import _NoRedirect
from ..contracts import CallReceipt, ProviderEvent, phone_number

STATUS = {'queued':'ringing','initiated':'ringing','ringing':'ringing','in-progress':'answered','completed':'completed',
          'busy':'busy','no-answer':'no_answer','failed':'failed','canceled':'declined'}


class TwilioMediaTransport:
    def __init__(self, socket, stream_id):
        self.socket, self.stream_id = socket, stream_id

    async def receive_audio(self):
        while True:
            event = await self.socket.receive_json()
            if event.get('event') == 'stop':
                return None
            if event.get('event') == 'media':
                payload = (event.get('media') or {}).get('payload')
                if isinstance(payload,str) and len(payload)<=65536:
                    return payload

    async def send_audio(self, audio):
        await self.socket.send_json({'event':'media','streamSid':self.stream_id,'media':{'payload':audio}})

    async def interrupt(self):
        await self.socket.send_json({'event':'clear','streamSid':self.stream_id})


class TwilioProvider:
    name, real = 'twilio', True

    def __init__(self, values, *, transport=None):
        self.account = values.get('TWILIO_ACCOUNT_SID', '')
        self.auth = values.get('TWILIO_AUTH_TOKEN', '')
        self.originating_number = values.get('TWILIO_PHONE_NUMBER', '')
        self.verify_service = values.get('TWILIO_VERIFY_SERVICE_SID', '')
        self.base_url = str(values.get('RAFII_PHONE_PUBLIC_BASE_URL') or '').rstrip('/')
        self.transport = transport or self._http
        self.configured = bool(re.fullmatch(r'AC[0-9a-fA-F]{32}', self.account) and self.auth and self.originating_number and
                               re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', self.base_url))

    def _http(self, method, url, fields=None):
        if not (url.startswith('https://api.twilio.com/2010-04-01/Accounts/' + self.account + '/') or
                url.startswith('https://verify.twilio.com/v2/Services/' + self.verify_service + '/')):
            raise ValueError('Twilio endpoint refused')
        auth = base64.b64encode((self.account + ':' + self.auth).encode()).decode()
        request = Request(url, data=urlencode(fields).encode() if fields is not None else None, method=method,
                          headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=15) as response:
                return response.status, json.loads(response.read(200_000))
        except HTTPError as error:
            # Retain only the bounded numeric error code, never message/more_info/PII.
            try:
                code = json.loads(error.read(16384)).get('code')
            except (ValueError, TypeError, AttributeError, OSError):
                code = None
            return error.code, {'code': code} if type(code) is int and 10000 <= code <= 99999 else {}
        except (URLError, TimeoutError, OSError):
            return 0, {}

    def _calls(self, suffix=''):
        return 'https://api.twilio.com/2010-04-01/Accounts/' + self.account + '/Calls' + suffix + '.json'

    def create_outbound_call(self, *, number, call_id, max_seconds, detect_machine=True):
        phone_number(number)
        fields = [('To', number), ('From', phone_number(self.originating_number)), ('Url', self.base_url + '/api/phone/answer/' + call_id),
                  ('Method','POST'), ('StatusCallback',self.base_url + '/api/phone/webhooks/' + call_id), ('StatusCallbackMethod','POST'),
                  ('Timeout','25'), ('TimeLimit',str(min(600,max_seconds))), ('Record','false')]
        if detect_machine:
            fields.append(('MachineDetection','Enable'))
        fields += [('StatusCallbackEvent', event) for event in ('initiated','ringing','answered','completed')]
        status, result = self.transport('POST', self._calls(), fields)
        if status == 201 and re.fullmatch(r'CA[0-9a-fA-F]{32}', str(result.get('sid',''))):
            return CallReceipt(STATUS.get(result.get('status'), 'ringing'), result['sid'])
        if 400 <= status < 500 and status != 408:
            code = result.get('code')
            failure = {
                20003: 'provider_auth', 20006: 'provider_account', 20403: 'provider_account',
                21210: 'provider_caller', 21212: 'provider_caller', 21213: 'provider_caller',
                21215: 'provider_country', 21216: 'provider_destination', 21219: 'provider_trial_recipient',
                21264: 'provider_caller', 20429: 'provider_rate_limit',
            }.get(code) if type(code) is int else None
            return CallReceipt('failed', failure=failure or ('provider_rate_limit' if status == 429 else 'provider_auth' if status == 401 else 'provider_rejected'))
        return CallReceipt('ambiguous')

    def end_call(self, call_ref):
        if not re.fullmatch(r'CA[0-9a-fA-F]{32}', call_ref):
            return False
        status, result = self.transport('POST', self._calls('/' + call_ref), {'Status':'completed'})
        return status == 200 and result.get('status') in ('completed','canceled')

    def reconcile(self, *, number, call_id, call_ref, requested_at):
        if not call_ref:
            # Twilio Calls has no safe client idempotency primitive. A To/From/time search is ambiguous if it
            # has zero or multiple candidates. Never infer "not sent" or authorize redial from that search.
            query = urlencode({'To':number,'From':self.originating_number,'PageSize':50})
            status, result = self.transport('GET', self._calls() + '?' + query)
            matches = []
            for c in result.get('calls', []) if status == 200 else []:
                from email.utils import parsedate_to_datetime
                try:
                    at = parsedate_to_datetime(c['date_created']).timestamp()
                except (KeyError, ValueError, TypeError):
                    continue
                if requested_at - 5 <= at <= requested_at + 60:
                    matches.append(c)
            if len(matches) != 1:
                return CallReceipt('ambiguous')
            # A single candidate is still not proof it belongs to this request. Signed callbacks bind it.
            return CallReceipt('ambiguous')
        status, result = self.transport('GET', self._calls('/' + call_ref))
        if status != 200:
            return CallReceipt('ambiguous')
        duration = result.get('duration')
        duration = int(duration) if str(duration).isdigit() and 0 <= int(duration) <= 86400 else None
        return CallReceipt(STATUS.get(result.get('status'),'ambiguous'),call_ref,duration)

    def verify_webhook(self, url, parameters, signature):
        # Twilio signs the exact public URL, then sorted form names and each unique value sorted lexically.
        if not self.auth or not url.startswith(self.base_url + '/'):
            return False
        data = url
        for name in sorted(parameters):
            values = parameters[name] if isinstance(parameters[name], list) else [parameters[name]]
            for value in sorted(set(values)):
                data += name + str(value)
        expected = base64.b64encode(hmac.new(self.auth.encode(), data.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(expected, signature or '')

    def normalize_event(self, parameters):
        scalar = lambda key, default='': (parameters.get(key) or [default])[0] if isinstance(parameters.get(key), list) else parameters.get(key, default)
        ref, status = scalar('CallSid'), scalar('CallStatus')
        if scalar('AccountSid') != self.account or not re.fullmatch(r'CA[0-9a-fA-F]{32}', ref) or status not in STATUS:
            raise ValueError('Invalid provider identity or lifecycle')
        duration = scalar('CallDuration', None)
        return ProviderEvent(ref + ':' + str(scalar('SequenceNumber',status)) + ':' + status, ref, STATUS.get(status,'failed'), int(duration) if duration is not None else None)

    def verify_media(self, path, signature):
        # Media Streams use a WSS handshake. Accept only the exact configured host/path and Twilio's documented slash variant.
        https_url = self.base_url + path
        for url in (https_url, https_url+'/', https_url.replace('https://','wss://',1), https_url.replace('https://','wss://',1)+'/'):
            expected = base64.b64encode(hmac.new(self.auth.encode(),url.encode(),hashlib.sha1).digest()).decode()
            if self.auth and hmac.compare_digest(expected,signature or ''):
                return True
        return False

    def answer_xml(self, call_id, *, voicemail=False):
        if voicemail:
            return '<Response><Hangup/></Response>'
        url = escape(self.base_url.replace('https://','wss://',1) + '/api/phone/media/' + call_id, {'"':'&quot;'})
        return '<Response><Connect><Stream url="' + url + '"/></Connect><Hangup/></Response>'

    def start_verification(self, number):
        if not re.fullmatch(r'VA[0-9a-fA-F]{32}', self.verify_service):
            raise ValueError('Verification not configured')
        status, value = self.transport('POST', 'https://verify.twilio.com/v2/Services/' + self.verify_service + '/Verifications', {'To':number,'Channel':'sms'})
        if status not in (200,201) or not value.get('sid'):
            raise ValueError('Verification not confirmed')
        return value['sid']

    def check_verification(self, number, code):
        status, value = self.transport('POST', 'https://verify.twilio.com/v2/Services/' + self.verify_service + '/VerificationCheck', {'To':number,'Code':code})
        return status == 200 and value.get('status') == 'approved'
