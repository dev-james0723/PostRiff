"""Verify Twitch EventSub webhook deliveries before interpreting JSON.

Pure byte authentication layer; TwitchService persists registered subscription trust,
encrypted events and duplicate receipts transactionally before acknowledgement.
The HTTP boundary selects trust by the registered callback UUID. Never trust tenant IDs inside webhook JSON.
Docs: https://dev.twitch.tv/docs/eventsub/handling-webhook-events/
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib, hmac, json, math, re, time
from typing import Mapping, Sequence

class TwitchWebhookError(Exception):
    pass

@dataclass(frozen=True)
class SubscriptionTrust:
    subscription_id: str
    subscription_type: str
    subscription_version: str
    condition: Mapping[str,str]
    workspace_id: str
    connection_id: str
    credential_generation: str
    secret: str
    allow_pending_binding: bool = False

@dataclass(frozen=True)
class VerifiedMessage:
    message_id: str
    sent_at: datetime
    kind: str
    subscription_id: str
    subscription_type: str
    workspace_id: str
    connection_id: str
    credential_generation: str
    event: dict | None
    revocation_reason: str | None
    challenge: bytes | None

class TwitchWebhookVerifier:
    REQUIRED=("twitch-eventsub-message-id","twitch-eventsub-message-timestamp",
              "twitch-eventsub-message-signature","twitch-eventsub-message-type",
              "twitch-eventsub-subscription-type","twitch-eventsub-subscription-version")
    REVOCATION_STATUSES=frozenset((
        "authorization_revoked", "user_removed", "notification_failures_exceeded",
        "version_removed", "moderator_removed",
    ))
    def __init__(self, *, clock=time.time, max_bytes=262144, past_skew=600, future_skew=60):
        if not callable(clock) or not (0<max_bytes<=1048576):
            raise TwitchWebhookError("invalid_config")
        self.clock,self.max_bytes,self.past_skew,self.future_skew=clock,max_bytes,past_skew,future_skew

    def verify(self, headers, raw_body: bytes, trusted: SubscriptionTrust):
        if not isinstance(trusted,SubscriptionTrust) or (not trusted.subscription_id and not trusted.allow_pending_binding) or not trusted.workspace_id or not trusted.connection_id:
            raise TwitchWebhookError("trusted_subscription_required")
        if (not isinstance(trusted.secret,str) or not 10<=len(trusted.secret)<=100 or
                not trusted.secret.isascii() or any(ord(c)<33 or ord(c)>126 for c in trusted.secret)):
            raise TwitchWebhookError("invalid_webhook_secret")
        if not isinstance(trusted.credential_generation,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', trusted.credential_generation):
            raise TwitchWebhookError("invalid_generation")
        if not isinstance(raw_body,bytes) or len(raw_body)>self.max_bytes:
            raise TwitchWebhookError("body_over_limit")
        if isinstance(headers,Mapping): pairs=list(headers.items())
        elif isinstance(headers,Sequence) and not isinstance(headers,(str,bytes)): pairs=list(headers)
        else: raise TwitchWebhookError("invalid_headers")
        if len(pairs)>80:
            raise TwitchWebhookError("headers_over_limit")
        norm={}
        for item in pairs:
            if not isinstance(item,(tuple,list)) or len(item)!=2:
                raise TwitchWebhookError("invalid_header_pair")
            key,value=item
            if (not isinstance(key,str) or not isinstance(value,str) or len(key)>128 or len(value)>4096 or
                not re.fullmatch(r"[A-Za-z0-9-]+",key) or any(ord(c)<32 or ord(c)==127 for c in value)):
                raise TwitchWebhookError("invalid_header_value")
            lower=key.lower()
            if lower in norm:
                raise TwitchWebhookError("duplicate_header")
            norm[lower]=value
        if any(not norm.get(name) for name in self.REQUIRED):
            raise TwitchWebhookError("missing_header")
        message_id=norm[self.REQUIRED[0]]
        stamp=norm[self.REQUIRED[1]]
        signature=norm[self.REQUIRED[2]]
        kind=norm[self.REQUIRED[3]]
        sub_type=norm[self.REQUIRED[4]]
        sub_version=norm[self.REQUIRED[5]]
        if len(message_id)>256 or any(c.isspace() for c in message_id):
            raise TwitchWebhookError("invalid_message_id")
        if not re.fullmatch(r"sha256=[a-f0-9]{64}",signature):
            raise TwitchWebhookError("invalid_signature")
        expected='sha256='+hmac.new(trusted.secret.encode('ascii'),
            message_id.encode('utf-8')+stamp.encode('utf-8')+raw_body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):
            raise TwitchWebhookError("signature_mismatch")
        if (not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)",stamp)):
            raise TwitchWebhookError("invalid_timestamp")
        try:
            parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            delta=float(self.clock())-parsed.timestamp()
        except (ValueError,OverflowError,TypeError):
            raise TwitchWebhookError("invalid_timestamp") from None
        if not math.isfinite(delta) or delta>self.past_skew or delta < -self.future_skew:
            raise TwitchWebhookError("stale_or_future_message")
        # Authenticate bytes BEFORE parsing untrusted JSON.
        def reject_duplicate(pairs):
            output={}
            for k,v in pairs:
                if k in output: raise TwitchWebhookError('duplicate_json_key')
                output[k]=v
            return output
        try:
            payload=json.loads(raw_body,object_pairs_hook=reject_duplicate,
                parse_constant=lambda _: (_ for _ in ()).throw(TwitchWebhookError('invalid_number')))
        except (UnicodeDecodeError,ValueError,RecursionError):
            raise TwitchWebhookError("invalid_json") from None
        if not isinstance(payload,dict) or not isinstance(payload.get('subscription'),dict):
            raise TwitchWebhookError("missing_subscription")
        sub=payload['subscription']
        # A freshly persisted callback may receive Twitch's signed challenge before
        # Create Subscription returns its provider ID. Only that authenticated
        # challenge may establish the ID; a notification can never bind one.
        provider_id = sub.get('id')
        valid_provider_id = (isinstance(provider_id,str) and
            re.fullmatch(r'[A-Za-z0-9_-]{1,128}',provider_id) is not None)
        initial_binding = (trusted.allow_pending_binding and not trusted.subscription_id and
            kind == 'webhook_callback_verification' and valid_provider_id)
        if (not valid_provider_id or
            (provider_id!=trusted.subscription_id and not initial_binding) or sub.get('type')!=trusted.subscription_type or
            sub.get('version')!=trusted.subscription_version or
            sub.get('condition')!=dict(trusted.condition) or
            sub_type!=trusted.subscription_type or sub_version!=trusted.subscription_version):
            raise TwitchWebhookError("subscription_mismatch")
        if kind not in ('notification','webhook_callback_verification','revocation'):
            raise TwitchWebhookError("unknown_message_type")
        if kind=='notification':
            if sub.get('status')!='enabled' or not isinstance(payload.get('event'),dict):
                raise TwitchWebhookError("invalid_notification")
        elif kind=='webhook_callback_verification':
            if sub.get('status')!='webhook_callback_verification_pending':
                raise TwitchWebhookError("invalid_challenge_status")
        challenge=None
        if kind=='webhook_callback_verification':
            value=payload.get('challenge')
            if not isinstance(value,str) or not 1<=len(value)<=512 or any(ord(c)<32 for c in value):
                raise TwitchWebhookError("invalid_challenge")
            challenge=value.encode('utf-8')
        reason=payload.get('subscription',{}).get('status') if kind=='revocation' else None
        # Message-Type is not covered by Twitch's id + timestamp + raw-body HMAC.
        # A replay with that header changed must not revoke an enabled subscription.
        # Verify against the documented disabled status in the authenticated bytes.
        if kind=='revocation' and (not isinstance(reason,str) or reason not in self.REVOCATION_STATUSES):
            raise TwitchWebhookError("invalid_revocation")
        return VerifiedMessage(message_id,parsed.astimezone(timezone.utc),kind,
            sub['id'],trusted.subscription_type,trusted.workspace_id,
            trusted.connection_id,trusted.credential_generation,
            dict(payload['event']) if kind=='notification' else None,reason,challenge)


# Stable, documented webhook types for the connected broadcaster. Beta types and
# app-global grants are not accepted through this tenant-scoped subscription route.
# Sources: https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/
EVENT_TYPES = {}


def _event(names, scopes=(), *, version='1', moderator=False, chat=False, eligible=False, alternatives=()):
    for name in names.split():
        EVENT_TYPES[name] = {'version': version, 'scopes': list(scopes),
            'scope_options': [list(scopes), *[list(item) for item in alternatives]],
            'moderator': moderator, 'chat': chat, 'eligible': eligible}


_event('stream.online stream.offline')
_event('channel.update', version='2')
_event('channel.follow', ('moderator:read:followers',), version='2', moderator=True)
_event('channel.chat.message channel.chat.message_delete channel.chat.clear channel.chat.clear_user_messages channel.chat.notification channel.chat_settings.update',
       ('user:read:chat','user:bot'), chat=True)
_event('channel.ban channel.unban', ('channel:moderate',))
_event('channel.subscribe channel.subscription.end channel.subscription.gift channel.subscription.message', ('channel:read:subscriptions',), eligible=True)
_event('channel.cheer channel.bits.use', ('bits:read',), eligible=True)
_event('channel.ad_break.begin', ('channel:read:ads',), eligible=True)
_event('channel.poll.begin channel.poll.progress channel.poll.end', ('channel:read:polls',), eligible=True,
       alternatives=(('channel:manage:polls',),))
_event('channel.prediction.begin channel.prediction.progress channel.prediction.lock channel.prediction.end',
       ('channel:read:predictions',), eligible=True, alternatives=(('channel:manage:predictions',),))
_event('channel.channel_points_custom_reward.add channel.channel_points_custom_reward.update channel.channel_points_custom_reward.remove channel.channel_points_custom_reward_redemption.add channel.channel_points_custom_reward_redemption.update',
       ('channel:read:redemptions',), eligible=True, alternatives=(('channel:manage:redemptions',),))
_event('channel.shield_mode.begin channel.shield_mode.end', ('moderator:read:shield_mode',), moderator=True,
       alternatives=(('moderator:manage:shield_mode',),))
_event('automod.message.hold automod.message.update', ('moderator:manage:automod',), version='2', moderator=True)


def event_operation_scopes(capability):
    prefix = 'twitch.eventsub.subscribe.'
    if not isinstance(capability,str) or not capability.startswith(prefix):
        return None
    spec = EVENT_TYPES.get(capability[len(prefix):])
    return list(spec['scopes']) if spec else None
