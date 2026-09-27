"""Deterministic SMS policy and transport seam. Identity is decrypted only at the egress boundary.

No provider body, raw address or free-form event payload is returned or logged. A lost response is uncertain:
Twilio Messaging has no client idempotency primitive that would make an automatic resend safe.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import ssl
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from . import catalog, email_render, planner
from ..phone.contracts import phone_number
from ..phone.providers.twilio import _NoRedirect

CONSENT_VERSION = 'rafii-sms/1'
SMS_HOURLY_LIMIT, SMS_DAILY_LIMIT = 2, 4
COPY = {
    'en': {'publish.failed': 'Publishing needs attention.', 'publish.uncertain': 'Publishing needs a check.',
           'channel.reconnect_required': 'Reconnect a channel.', 'campaign.approval_required': 'A timely approval needs you.',
           'billing.payment_failed': 'Review a payment issue.', 'security.account_change': 'Review an account change.'},
    'zh-Hant-HK': {'publish.failed': '發佈需要你處理。', 'publish.uncertain': '請檢查發佈狀態。', 'channel.reconnect_required': '請重新連接渠道。',
                   'campaign.approval_required': '請及時審批。', 'billing.payment_failed': '請檢查付款問題。', 'security.account_change': '請檢查帳戶變更。'},
    'zh-Hant': {'publish.failed': '發佈需要你處理。', 'publish.uncertain': '請檢查發佈狀態。', 'channel.reconnect_required': '請重新連接頻道。',
                'campaign.approval_required': '請及時審批。', 'billing.payment_failed': '請檢查付款問題。', 'security.account_change': '請檢查帳戶變更。'},
    'zh-Hans': {'publish.failed': '发布需要你处理。', 'publish.uncertain': '请检查发布状态。', 'channel.reconnect_required': '请重新连接渠道。',
                'campaign.approval_required': '请及时审批。', 'billing.payment_failed': '请检查付款问题。', 'security.account_change': '请检查账户变更。'},
}


def origin(value):
    parsed = urlsplit(str(value or ''))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('SMS requires an HTTPS origin')
    return str(value).rstrip('/')


def acknowledgement_path(path, delivery_id):
    # The reference is not a capability. Only an authenticated owner of this delivery can acknowledge it.
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', str(delivery_id)):
        raise ValueError('Invalid notification reference')
    path = email_render.safe_app_path(path)
    # Never let a payload override the acknowledgement reference.
    if 'notification=' in path:
        path = '/app'
    return path + ('&' if '?' in path else '?') + urlencode({'notification': delivery_id})


def segment_count(text):
    gsm = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
    extended = '^{}\\[~]|€'
    if all(c in gsm or c in extended for c in text):
        units = sum(2 if c in extended else 1 for c in text)
        return 1 if units <= 160 else (units + 152) // 153
    units = len(text.encode('utf-16-be')) // 2
    return 1 if units <= 70 else (units + 66) // 67


def render(event_type, locale, base_url, delivery_id, *, max_segments=2):
    loc = email_render.resolve_locale(locale)
    reason = COPY[loc].get(event_type)
    if not reason:
        raise ValueError('No approved SMS copy')
    stop = 'Reply STOP to opt out.' if loc == 'en' else ('回复STOP退订。' if loc == 'zh-Hans' else '回覆STOP退訂。')
    # A fixed minimal route avoids including any private payload in a text or its URL.
    text = f'Rafii: {reason} {origin(base_url)}{acknowledgement_path("/app", delivery_id)} {stop}'
    segments = segment_count(text)
    if segments > max_segments:
        raise ValueError('SMS exceeds segment ceiling')
    return {'text': text, 'segments': segments, 'version': CONSENT_VERSION}


def eligibility(event, prefs, context, now, recent=None):
    recent = recent or {}
    policy = event.get('sms_policy', catalog.spec(event['event_type'])['sms'])
    if policy == 'off': return 'sms_policy_off'
    if not context.get('enabled'): return 'sms_disabled'
    if event.get('resolved') or event.get('resolved_at'): return 'resolved'
    if context.get('acknowledged'): return 'acknowledged'
    if event.get('expires_at') is not None and event['expires_at'] <= now: return 'expired'
    if prefs.get('sms_mode', 'off') != 'important_only': return 'sms_off'
    if not context.get('verified'): return 'phone_unverified'
    if not context.get('consented'): return 'sms_consent_required'
    if context.get('provider_blocked'): return 'provider_stop'
    if event['event_type'] == 'security.account_change' and not context.get('security_sms'): return 'security_sms_off'
    if event['event_type'] == 'campaign.approval_required' and not event.get('time_sensitive'): return 'not_time_sensitive'
    if isinstance(prefs.get('muted_until'), (int, float)) and prefs['muted_until'] > now: return 'muted'
    if recent.get('sms', 0) >= SMS_HOURLY_LIMIT: return 'sms_hourly_limit'
    if recent.get('sms_day', 0) >= SMS_DAILY_LIMIT: return 'sms_daily_limit'
    return None


def plan(event, prefs, context, now, *, push_delivery=None, recent=None):
    reason = eligibility(event, prefs, context, now, recent)
    due = now
    escalating = False
    if not reason and event.get('sms_policy', catalog.spec(event['event_type'])['sms']) == 'escalate':
        if push_delivery and push_delivery['status'] == 'pending':
            if not prefs.get('smart_escalation', True) or not context.get('escalation_enabled'):
                reason = 'smart_escalation_off'
            else:
                escalating = True
                delay = 600 if catalog.spec(event['event_type'])['severity'] in ('critical', 'security') else 1800
                due = max(now, push_delivery['next_attempt_at']) + delay
        # Important Texts is explicit permission for immediate fallback when push cannot reach the person.
    if not reason and planner.in_quiet_hours(due, prefs):
        due = planner.quiet_end_after(due, prefs)
    if not reason and event.get('expires_at') is not None and due >= event['expires_at']:
        reason = 'expired'
    return {'channel': 'sms', 'mode': 'immediate', 'status': 'suppressed' if reason else 'pending',
            'next_attempt_at': due, 'escalation':escalating,
            'reason': reason or ('sms_escalation' if escalating else 'quiet_hours' if due > now else None)}


class FakeSMSTransport:
    name, real, configured = 'fake_sms', False, True

    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.sent = []  # no raw number or text even in fake receipts

    def send(self, *, number, text, delivery_id, idempotency_key):
        phone_number(number)
        self.sent.append({'deliveryId': delivery_id, 'idempotencyKey': idempotency_key, 'segments': segment_count(text)})
        return self.outcomes.pop(0) if self.outcomes else {'state': 'sent', 'provider': self.name, 'providerRef': 'SM' + hashlib.sha256(delivery_id.encode()).hexdigest()[:32]}


class TwilioSMSTransport:
    name, real = 'twilio_sms', True

    def __init__(self, values, transport=None):
        self.account = values.get('TWILIO_ACCOUNT_SID', '')
        self.auth = values.get('TWILIO_AUTH_TOKEN', '')
        self.sender = values.get('TWILIO_SMS_FROM_NUMBER', '')
        self.messaging_service = values.get('TWILIO_SMS_MESSAGING_SERVICE_SID', '')
        try: self.base_url = origin(values.get('POSTRIFF_PUBLIC_BASE_URL'))
        except ValueError: self.base_url = ''
        self.configured = bool(re.fullmatch(r'AC[0-9a-fA-F]{32}', self.account) and self.auth and self.base_url and
                               (re.fullmatch(r'MG[0-9a-fA-F]{32}', self.messaging_service) or re.fullmatch(r'\+[1-9][0-9]{7,14}', self.sender)))
        self.transport = transport or self._http

    def _http(self, fields):
        url = f'https://api.twilio.com/2010-04-01/Accounts/{self.account}/Messages.json'
        auth = base64.b64encode((self.account + ':' + self.auth).encode()).decode()
        req = Request(url, data=urlencode(fields).encode(), headers={'Authorization': 'Basic ' + auth,
                      'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        try:
            with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(req, timeout=15) as res:
                return res.status, json.loads(res.read(65536))
        except HTTPError as error:
            # Retain only the standardized opt-out error, never a provider message or phone number.
            try: code = json.loads(error.read(65536)).get('code')
            except (ValueError, OSError, AttributeError): code = None
            return error.code, {'code':21610} if str(code)=='21610' else {}
        except (URLError, TimeoutError, OSError, ValueError): return 0, {}

    def send(self, *, number, text, delivery_id, idempotency_key):
        if not self.configured: return {'state': 'config', 'detail': 'sms_unconfigured'}
        phone_number(number)
        fields = {'To': number, 'Body': text, 'StatusCallback': self.base_url + '/api/notifications/sms/webhook/' + delivery_id}
        fields['MessagingServiceSid' if self.messaging_service else 'From'] = self.messaging_service or self.sender
        try: status, result = self.transport(fields)
        except Exception: return {'state': 'uncertain', 'detail': 'sms_acceptance_unknown'}
        if not isinstance(result,dict): return {'state':'uncertain','detail':'sms_acceptance_unknown'}
        if status == 201 and re.fullmatch(r'SM[0-9a-fA-F]{32}', str(result.get('sid', ''))):
            return {'state': 'sent', 'provider': self.name, 'providerRef': result['sid'],
                    **receipt_metrics(result.get('num_segments'),result.get('price'),result.get('price_unit'))}
        if status == 429: return {'state': 'transient', 'detail': 'sms_provider_rate_limit'}
        if 400 <= status < 500 and status != 408:
            return {'state': 'permanent', 'detail': 'sms_provider_rejected','providerStop':str(result.get('code'))=='21610'}
        return {'state': 'uncertain', 'detail': 'sms_acceptance_unknown'}

    def verify_webhook(self, url, parameters, signature):
        if not self.configured or not url.startswith(self.base_url + '/api/notifications/sms/'): return False
        data = url
        for key in sorted(parameters):
            values = parameters[key] if isinstance(parameters[key], list) else [parameters[key]]
            for value in sorted(set(values)): data += key + str(value)
        expected = base64.b64encode(hmac.new(self.auth.encode(), data.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(expected, signature or '')


def receipt_metrics(segments=None, price=None, currency=None):
    """Bounded numeric accounting from provider receipts, without retaining their private body."""
    result = {}
    if re.fullmatch(r'[1-9]|10', str(segments or '')): result['segments'] = int(segments)
    if str(currency or '').upper() == 'USD' and price is not None:
        try:
            amount = abs(Decimal(str(price)))
            if amount.is_finite() and amount <= 100:
                result['costUsdMicro'] = int((amount * 1000000).to_integral_value(rounding=ROUND_CEILING))
        except (InvalidOperation, ValueError): pass
    return result
