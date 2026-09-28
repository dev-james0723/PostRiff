"""Dial REST + Self-Hosted audio. Only Rafii's server drives the conversation.

Contract: docs.getdial.ai OpenAPI and Self-Hosted audio protocol, checked 2026-09-27.
No SDK, automatic redial, managed-agent fallback, or recording.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from ...agent_runtime_v2.creative import _NoRedirect
from ..contracts import CallReceipt, ProviderEvent, TERMINAL, phone_number

API = 'https://api.getdial.ai/api/v1'
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,100}')
STATUS = {'initiated': 'ringing', 'queued': 'ringing', 'ringing': 'ringing',
          'in-progress': 'answered', 'completed': 'completed', 'busy': 'busy',
          'no-answer': 'no_answer', 'failed': 'failed', 'canceled': 'cancelled'}


def state(value):
    status = value.get('status')
    if isinstance(status, dict):
        status = value.get('terminationType') if status.get('state') == 'Terminated' else status.get('state')
    return STATUS.get(str(status).lower(), 'ambiguous')


def signature_valid(secret, header, payload, now):
    """Verify exact bytes; duplicate fields, stale timestamps and malformed headers fail closed."""
    match = re.fullmatch(r't=([0-9]{1,12}),v1=([0-9a-f]{64})', header or '')
    if not secret or not match or abs(now - int(match[1])) >= 300:
        return False
    expected = hmac.new(secret.encode(), match[1].encode() + b'.' + payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, match[2])


class DialProvider:
    name, real = 'dial', True

    def __init__(self, values, *, transport=None, clock=time.time):
        self.api_key = values.get('DIAL_API_KEY', '')
        self.originating_number = values.get('DIAL_PHONE_NUMBER', '')
        self.media_secret = values.get('DIAL_AUDIO_SIGNING_SECRET', '')
        self.webhook_secret = values.get('DIAL_WEBHOOK_SIGNING_SECRET', '')
        self.verification_secret = values.get('DIAL_VERIFICATION_SECRET', '')
        self.base_url = str(values.get('RAFII_PHONE_PUBLIC_BASE_URL') or '').rstrip('/')
        self.media_url = self.base_url.replace('https://', 'wss://', 1) + '/api/phone/dial/media'
        self.transport, self.clock = transport or self._http, clock
        self.configured = bool(self.api_key.startswith('sk_live_') and
            re.fullmatch(r'\+[1-9][0-9]{7,14}', self.originating_number) and
            self.media_secret and self.webhook_secret and len(self.verification_secret) >= 32 and
            re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', self.base_url))

    def _http(self, method, path, fields=None, headers=None):
        # Paths are server-owned. Never follow provider/body URLs or forward credentials on a redirect.
        if not re.fullmatch(r'/(?:account|numbers|self-hosted|messages|calls(?:/[A-Za-z0-9_-]{1,100})?)', path):
            raise ValueError('Dial endpoint refused')
        request = Request(API + path, method=method,
            data=json.dumps(fields).encode() if fields is not None else None,
            headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json',
                     'Accept': 'application/json', 'User-Agent': 'Rafii/1.0', **(headers or {})})
        try:
            with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=15) as response:
                raw = response.read(200_001)
                if len(raw) > 200_000:
                    return 0, {}
                result = json.loads(raw)
                return response.status, result if isinstance(result, dict) else {}
        except HTTPError as error:
            # Preserve only this exact infrastructure error, never arbitrary provider text/PII.
            # Non-2xx call creation guarantees no live call per Dial's contract. No retry.
            status, diagnostic = error.code, {}
            try:
                if status == 403 and error.read(257).strip() == b'error code: 1010':
                    diagnostic = {'code': 'cloudflare_1010'}
            except (OSError, ValueError):
                pass
            finally:
                error.close()
            return status, diagnostic
        except (URLError, TimeoutError, OSError, ValueError):
            return 0, {}

    @staticmethod
    def _http_failure(status, result, stage, fallback):
        if status == 403 and result.get('code') == 'cloudflare_1010':
            return {'ready': False, 'reason': 'provider_transport', 'stage': 'provider_transport', 'httpStatus': status}
        reason = 'provider_auth' if status == 401 else 'provider_unavailable' if status == 0 or status >= 500 else fallback
        return {'ready': False, 'reason': reason, 'stage': stage, 'httpStatus': status}

    @staticmethod
    def instruction(call_id):
        if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', call_id):
            raise ValueError('Invalid Rafii call identity')
        return 'Rafii phone session: ' + call_id + '. Conversation and instructions are supplied by Rafii’s server.'

    def local_call_id(self, instruction):
        match = re.match(r'^Rafii phone session: ([0-9a-f-]{36})\.', instruction or '')
        if not match or instruction != self.instruction(match[1]):
            raise ValueError('Unbound Dial call')
        return match[1]

    def readiness(self):
        """Read-only checks immediately before egress; account configuration is never assumed from env."""
        if not self.configured:
            return {'ready': False, 'reason': 'provider_auth', 'stage': 'local_configuration'}
        status, hosted = self.transport('GET', '/self-hosted')
        if status != 200:
            return self._http_failure(status, hosted, 'self_hosted_http', 'provider_account')
        audio = hosted.get('audio') or {}
        for matches, stage in (
            (hosted.get('access') == 'granted', 'self_hosted_access'),
            (hosted.get('enabled') is True, 'self_hosted_disabled'),
            (hosted.get('activeMode') == 'audio', 'self_hosted_mode'),
            (audio.get('wsUrl') == self.media_url, 'self_hosted_url'),
            (audio.get('audioInboundFormat') == audio.get('audioOutboundFormat') == 'mulaw_8000', 'self_hosted_format'),
        ):
            if not matches:
                return {'ready': False, 'reason': 'provider_account', 'stage': stage}
        status, result = self.transport('GET', '/numbers')
        if status != 200:
            return self._http_failure(status, result, 'numbers_http', 'provider_caller')
        lines = [n for n in result.get('numbers', []) if isinstance(n, dict) and n.get('number') == self.originating_number]
        if not (len(lines) == 1 and 'call' in lines[0].get('capabilities', []) and
                lines[0].get('setupStatus') == 'ready' and lines[0].get('callingEnabled') is True):
            return {'ready': False, 'reason': 'provider_caller', 'stage': 'outgoing_line'}
        status, account = self.transport('GET', '/account')
        if status != 200:
            return self._http_failure(status, account, 'account_http', 'provider_account')
        limit = (account.get('limits') or {}).get('maxCallDurationSeconds', 3600)
        if type(limit) is not int or not 60 <= limit <= 3600:
            return {'ready': False, 'reason': 'provider_account', 'stage': 'account_limit'}
        capabilities = lines[0].get('capabilities', [])
        registration = lines[0].get('tenDlc')
        registration_status = 'not_applicable'
        if registration is not None:
            registration_status = registration.get('status') if isinstance(registration, dict) else 'unknown'
            if registration_status not in ('not_registered', 'in_review', 'with_carrier', 'approved', 'rejected'):
                registration_status = 'unknown'
        # Voice remains available to previously verified users. US carrier SMS needs
        # approved registration when Dial says 10DLC applies to the originating line.
        sms_ready = ('sms' in capabilities and 'imessage' not in capabilities and
                     registration_status in ('not_applicable', 'approved'))
        return {'ready': True, 'maxSeconds': limit, 'smsReady': sms_ready,
                'smsRegistration': registration_status}

    def _receipt(self, value, *, number=None, call_id=None, call_ref=None, direction='outbound'):
        ref = value.get('id')
        if not isinstance(ref, str) or not IDENTIFIER.fullmatch(ref) or (call_ref and ref != call_ref):
            return CallReceipt('ambiguous')
        if value.get('direction') != direction or value.get('to' if direction == 'inbound' else 'from') != self.originating_number:
            return CallReceipt('ambiguous')
        if number is not None and value.get('to') != number:
            return CallReceipt('ambiguous')
        if call_id is not None and value.get('instruction') != self.instruction(call_id):
            return CallReceipt('ambiguous')
        duration = value.get('duration')
        duration = duration if type(duration) is int and 0 <= duration <= 86400 else None
        return CallReceipt(state(value), ref, duration)

    def create_outbound_call(self, *, number, call_id, max_seconds):
        phone_number(number)
        ready = self.readiness()
        if not ready['ready']:
            return CallReceipt('failed', failure=ready['reason'])
        status, result = self.transport('POST', '/calls', {
            'fromNumber': self.originating_number, 'to': number, 'outboundInstruction': self.instruction(call_id),
            'maxCallDurationSeconds': min(max_seconds, ready['maxSeconds'])}, {'Idempotency-Key': 'rafii-phone:' + call_id})
        if status in (200, 201):
            return self._receipt(result.get('call') or {}, number=number, call_id=call_id)
        if status == 403 and result.get('code') == 'cloudflare_1010':
            return CallReceipt('failed', failure='provider_transport')
        if status >= 300:
            reason = {401: 'provider_auth', 403: 'provider_account', 404: 'provider_caller',
                      429: 'provider_rate_limit'}.get(status, 'provider_rejected')
            return CallReceipt('failed', failure=reason)
        return CallReceipt('ambiguous')

    def reconcile(self, *, number, call_id, call_ref, requested_at):
        if call_ref:
            if not IDENTIFIER.fullmatch(call_ref):
                return CallReceipt('ambiguous')
            status, result = self.transport('GET', '/calls/' + call_ref)
            return self._receipt(result.get('call') or {}, number=number, call_id=call_id, call_ref=call_ref) if status == 200 else CallReceipt('ambiguous')
        # Exact server-generated instruction identifies this attempt. Empty/truncated history stays ambiguous.
        status, result = self.transport('GET', '/calls')
        matches = [c for c in result.get('calls', []) if isinstance(c, dict) and c.get('instruction') == self.instruction(call_id)] if status == 200 else []
        return self._receipt(matches[0], number=number, call_id=call_id) if len(matches) == 1 else CallReceipt('ambiguous')

    def end_call(self, call_ref):
        # Dial exposes hang-up on the audio socket, not a documented REST cancel endpoint.
        # HTTP/cron sets ledger state=ending; the media watchdog sends end_call. Confirm via authoritative GET.
        if not IDENTIFIER.fullmatch(call_ref):
            return False
        status, result = self.transport('GET', '/calls/' + call_ref)
        value = result.get('call') or {}
        direction = value.get('direction')
        return status == 200 and direction in ('inbound','outbound') and self._receipt(value, call_ref=call_ref, direction=direction).state in TERMINAL

    def reconcile_inbound(self, call_ref):
        if not isinstance(call_ref, str) or not IDENTIFIER.fullmatch(call_ref):
            return CallReceipt('ambiguous')
        status, result = self.transport('GET', '/calls/' + call_ref)
        return self._receipt(result.get('call') or {}, call_ref=call_ref, direction='inbound') if status == 200 else CallReceipt('ambiguous')

    def verify_media(self, call_ref, signature):
        return bool(IDENTIFIER.fullmatch(call_ref) and signature_valid(self.media_secret, signature, call_ref.encode(), self.clock()))

    def verify_webhook(self, url, parameters, signature):
        raw = parameters.get('_raw')
        return url == self.base_url + '/api/phone/dial/events' and isinstance(raw, bytes) and signature_valid(self.webhook_secret, signature, raw, self.clock())

    def normalize_event(self, parameters):
        data = parameters.get('data') or {}
        ref, kind = data.get('callId'), parameters.get('type')
        event_id = parameters.get('id')
        direction = data.get('direction')
        if not (isinstance(ref, str) and IDENTIFIER.fullmatch(ref) and isinstance(event_id, str) and
                1 <= len(event_id) <= 200 and kind in ('call.ended', 'call.status_changed') and
                direction in ('inbound','outbound') and data.get('to' if direction == 'inbound' else 'from') == self.originating_number and
                (parameters.get('relatedObject') or {}).get('id') == ref):
            raise ValueError('Invalid Dial call event')
        next_state = state(data)
        if next_state == 'ambiguous' or (kind == 'call.ended' and next_state not in TERMINAL):
            raise ValueError('Invalid Dial lifecycle')
        duration = data.get('durationSeconds')
        if duration is not None and (type(duration) is not int or not 0 <= duration <= 86400):
            raise ValueError('Invalid Dial duration')
        return ProviderEvent(event_id, ref, next_state, duration, direction)

    def start_verification(self, number):
        phone_number(number)
        if len(self.verification_secret) < 32:
            raise ValueError('Dial verification unavailable')
        # The official send schema has no `channel: sms`: standard lines default to SMS,
        # while iMessage lines default to iMessage. Require a standard owned SMS line for OTP.
        status, result = self.transport('GET', '/numbers')
        lines = [n for n in result.get('numbers', []) if isinstance(n,dict) and n.get('number') == self.originating_number]
        if not (status == 200 and len(lines) == 1 and lines[0].get('setupStatus') == 'ready' and
                'sms' in lines[0].get('capabilities', []) and 'imessage' not in lines[0].get('capabilities', [])):
            raise ValueError('Dial SMS verification line unavailable')
        code = f'{secrets.randbelow(1_000_000):06d}'
        expires, nonce = str(int(self.clock()) + 600), secrets.token_hex(16)
        digest = self._verification_digest(number, code, expires, nonce)
        status, result = self.transport('POST', '/messages', {'fromNumber': self.originating_number, 'to': number,
            'body': 'Your Rafii verification code is ' + code + '. It expires in 10 minutes. Do not share it.'})
        if status != 201 or not (result.get('message') or {}).get('id'):
            raise ValueError('Dial verification not confirmed')
        return 'dial.' + expires + '.' + nonce + '.' + digest

    def _verification_digest(self, number, code, expires, nonce):
        return hmac.new(self.verification_secret.encode(), ('rafii-otp|' + number + '|' + expires + '|' + nonce + '|' + code).encode(), hashlib.sha256).hexdigest()

    def check_verification(self, number, code, *, reference=None):
        match = re.fullmatch(r'dial\.([0-9]{1,12})\.([0-9a-f]{32})\.([0-9a-f]{64})', reference or '')
        if len(self.verification_secret) < 32 or not match or not re.fullmatch(r'[0-9]{6}', code) or not self.clock() < int(match[1]) <= self.clock() + 600:
            return False
        return hmac.compare_digest(match[3], self._verification_digest(number, code, match[1], match[2]))


class DialMediaTransport:
    """Pump keepalive immediately, independently of Live startup and delegated work. Bounded audio queue."""
    def __init__(self, socket, *, require_acceptance=True, collect_code=False):
        self.socket, self.ended = socket, False
        self.audio = asyncio.Queue(maxsize=256)
        self.stopped = asyncio.Event()
        self.error = None
        self.accepted = not require_acceptance
        self.acceptance = asyncio.Event()
        self.collect_code = collect_code
        self.digits = asyncio.Queue(maxsize=32)
        self.code_audio = asyncio.Queue(maxsize=256)
        self.collect_speech = False
        self.speech_attempts = 0
        self.input_mode = None
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while True:
                raw = await self.socket.receive_text()
                if len(raw) > 65536:
                    raise ValueError('Dial frame too large')
                event = json.loads(raw)
                if event.get('type') == 'ping_pong':
                    await self.socket.send_json({'type': 'ping_pong', 'timestamp': event['timestamp']})
                elif event.get('type') == 'call_ended':
                    self.ended = True
                    break
                elif event.get('type') == 'dtmf' and self.collect_code and not self.accepted:
                    digit = event.get('digit')
                    if isinstance(digit, str) and digit in '0123456789*#' and len(digit) == 1 and self.input_mode != 'spoken':
                        self.input_mode = 'keypad'
                        self.collect_speech = False
                        self.digits.put_nowait(digit)
                elif event.get('type') == 'dtmf' and not self.acceptance.is_set():
                    self.accepted = event.get('digit') == '1'
                    self.acceptance.set()
                elif event.get('type') == 'media':
                    if not self.accepted:
                        if self.collect_speech:
                            payload = event.get('payload')
                            if not isinstance(payload, str) or not payload or len(payload) > 48000:
                                raise ValueError('Invalid code audio')
                            audio = base64.b64decode(payload, validate=True)
                            from ..code_speech import PCM
                            if audio and sum(PCM[c] ** 2 for c in audio) > len(audio) * 400 ** 2:
                                self.input_mode = 'spoken'
                            self.code_audio.put_nowait(audio)
                        continue  # Pre-auth audio is only for isolated code transcription; never Live.
                    payload = event.get('payload')
                    if not isinstance(payload, str) or not payload or len(payload) > 48000:
                        raise ValueError('Invalid Dial media')
                    base64.b64decode(payload, validate=True)
                    self.audio.put_nowait(payload)
        except Exception as error:
            self.error = error
        finally:
            self.stopped.set()
            self.acceptance.set()
            if self.digits.full():
                self.digits.get_nowait()
            self.digits.put_nowait(None)
            if self.audio.full():
                self.audio.get_nowait()
            self.audio.put_nowait(None)

    async def accept_call(self, *, timeout=20):
        """Generic prerecorded μ-law prompt; voicemail cannot authorize private agent access."""
        from ..prompt_assets import read
        prompt = read('dial-acceptance')
        if not 8000 <= len(prompt) <= 120000:
            raise ValueError('Dial acceptance prompt unavailable')
        if not self.accepted:
            for offset in range(0, len(prompt), 1600):
                await self.send_audio(base64.b64encode(prompt[offset:offset + 1600]).decode())
        try:
            await asyncio.wait_for(self.acceptance.wait(), timeout)
        except TimeoutError:
            return False
        if not self.accepted or self.stopped.is_set():
            return False
        await self.interrupt()  # Flush any unplayed greeting before starting Rafii's normal voice.
        return True

    async def play_prompt(self, name):
        if name not in ('dial-inbound', 'dial-inbound-retry', 'dial-repeat'):
            raise ValueError('Unknown phone prompt')
        from ..prompt_assets import read
        prompt = read(name)
        if not 8000 <= len(prompt) <= 200000:
            raise ValueError('Phone prompt unavailable')
        await self.interrupt()
        for offset in range(0, len(prompt), 1600):
            await self.send_audio(base64.b64encode(prompt[offset:offset + 1600]).decode())

    def prepare_code_input(self):
        """Arm only after signed admission, before prompt playback, so early speech is not lost."""
        self.input_mode = None
        self.collect_speech = self.collect_code and not self.accepted and self.speech_attempts < 3

    async def _read_keypad(self):
        code = ''
        while not self.stopped.is_set():
            digit = await self.digits.get()
            if digit is None:
                return None
            self.keypad_selected.set()
            self.collect_speech = False
            if digit == '*':
                return code
            elif digit == '#':
                code = ''
            else:
                code = (code + digit)[:13]
        return None

    async def _read_spoken(self, recognize):
        from ..code_speech import Utterance, parse_code
        utterance = Utterance()
        try:
            while not self.stopped.is_set():
                audio = await self.code_audio.get()
                candidate = utterance.feed(audio)
                if candidate:
                    if self.speech_attempts >= 3:
                        await asyncio.Future()  # Keypad remains available, with no additional model cost.
                    self.speech_attempts += 1
                    self.collect_speech = False
                    try:
                        result = await recognize(candidate)
                        return parse_code(result) or ''  # Empty is a failed auth attempt, never a credential.
                    except Exception:
                        return ''
        finally:
            utterance.clear()

    async def read_code(self, *, timeout, recognize=None):
        self.keypad_selected = asyncio.Event()
        self.collect_speech = self.collect_code and recognize is not None and self.speech_attempts < 3 and self.input_mode != 'keypad'
        tasks = [asyncio.create_task(self._read_keypad())]
        if self.collect_speech:
            tasks.append(asyncio.create_task(self._read_spoken(recognize)))
        keypad_selected = asyncio.create_task(self.keypad_selected.wait())
        try:
            async with asyncio.timeout(timeout):
                done, _ = await asyncio.wait([*tasks, keypad_selected], return_when=asyncio.FIRST_COMPLETED)
                # Once the person chooses the keypad, cancel STT and wait for star; never race two auth attempts.
                if self.keypad_selected.is_set():
                    for task in tasks[1:]:
                        task.cancel()
                    return await tasks[0]
                return next((task.result() for task in tasks if task in done), None)
        except TimeoutError:
            return None
        finally:
            self.collect_speech = False
            self.input_mode = None
            keypad_selected.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, keypad_selected, return_exceptions=True)
            while not self.code_audio.empty():
                self.code_audio.get_nowait()

    async def authorize_inbound(self):
        if self.stopped.is_set():
            return False
        await self.interrupt()
        self.accepted = True
        self.acceptance.set()
        while not self.digits.empty():
            self.digits.get_nowait()
        return True

    async def receive_audio(self):
        value = await self.audio.get()
        if value is None and self.error:
            raise ValueError('Dial media disconnected') from None
        return value

    async def send_audio(self, audio):
        await self.socket.send_json({'type': 'media', 'payload': audio})

    async def interrupt(self):
        await self.socket.send_json({'type': 'clear'})

    async def end_call(self):
        if not self.ended:
            await self.socket.send_json({'type': 'end_call'})
            try:
                await asyncio.wait_for(self.stopped.wait(), 3)
            except TimeoutError:
                pass

    async def close(self):
        self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)
        self.collect_speech = False
        for queue in (self.code_audio, self.digits, self.audio):
            while not queue.empty():
                queue.get_nowait()
