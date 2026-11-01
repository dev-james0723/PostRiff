"""Twitch confidential user OAuth for the existing Rafii credential vault.

Provider contracts verified against Twitch's authentication and Get Users docs:
https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
https://dev.twitch.tv/docs/authentication/validate-tokens/
https://dev.twitch.tv/docs/authentication/refresh-tokens/
https://dev.twitch.tv/docs/api/reference/#get-users

This is regular OAuth authorization code flow. Twitch does not document PKCE for
this confidential flow. No id_token is consumed, no email scope is requested, and
identity is resolved through authenticated Helix plus /validate. Rafii consumes
the workspace/member-bound state before exchange. Envelopes below are server-only
plaintext inside CredentialVault encryption; they must never enter a UI or log.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from .provider_base import OAuthProvider


CALLBACK = "https://rafii.io/api/oauth/twitch/callback"
_TOKEN = re.compile(r"[\x21-\x7e]{1,4096}\Z")
_USER_ID = re.compile(r"[1-9][0-9]{0,29}\Z")
_SCOPE = re.compile(r"[a-z][a-z0-9:_-]{0,127}\Z")
_GENERATION = re.compile(r"[a-f0-9]{32}\Z")


def _secret(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise AlphaError('Twitch returned an invalid credential. Reconnect.', 409, code='twitch_revoked_oauth')
    return value


def _scopes(value):
    if (not isinstance(value, (list, tuple)) or len(value) > 256
            or any(not isinstance(item, str) or not _SCOPE.fullmatch(item) for item in value)):
        raise AlphaError('Twitch permissions could not be verified.', 503, code='twitch_validation_unavailable')
    return sorted(set(value))


def _expiry(value):
    if type(value) is not int or not 0 < value <= 2**31:
        raise AlphaError('Twitch token lifetime could not be verified.', 503, code='twitch_validation_unavailable')
    return value


class TwitchProvider(OAuthProvider):
    id, platform, capability_version = 'twitch', 'Twitch', 1
    AUTH = 'https://id.twitch.tv/oauth2/authorize'
    TOKEN = 'https://id.twitch.tv/oauth2/token'
    VALIDATE = 'https://id.twitch.tv/oauth2/validate'
    REVOKE = 'https://id.twitch.tv/oauth2/revoke'
    USERS = 'https://api.twitch.tv/helix/users'
    callback_origin = 'https://rafii.io'
    assisted_fallback = False
    feature_flag_required = True
    refresh_margin = 120
    SCOPES = {'identity': []}
    account_requirement = 'Your own Twitch user account. Native functions depend on the account role, granted scopes and Twitch eligibility.'
    normalized = {'identity': 'supported', 'refresh_token': 'supported', 'revoke': 'supported',
                  'owned_content_read': 'supported', 'webhooks': 'supported'}

    def __init__(self, client_id, client_secret, transport=None, production_reviewed=False,
                 *, public_connect_enabled=False, commercial_approved=False, clock=time.time):
        super().__init__(_secret(client_id), _secret(client_secret), transport, production_reviewed)
        self.public_connect_enabled = bool(public_connect_enabled)
        self.commercial_approved = bool(commercial_approved)
        self.execution_enabled = self.public_connect_enabled and self.commercial_approved
        self.clock = clock

    @classmethod
    def mount(cls, values, transport=None):
        client, secret, valid, diagnostic = cls.credential_pair(values)
        configured_callback = values.get('POSTRIFF_OAUTH_TWITCH_REDIRECT_URI', CALLBACK)
        configured_origin = values.get('POSTRIFF_OAUTH_TWITCH_CALLBACK_ORIGIN', cls.callback_origin)
        if configured_callback != CALLBACK or configured_origin != cls.callback_origin:
            diagnostic.update(configurationState='invalid_configuration', callbackOriginPinned=False,
                              callbackConfigurationError=True)
            return None, diagnostic
        enabled = str(values.get('RAFII_TWITCH_PUBLIC_CONNECT', '')).lower() == 'true'
        approved = str(values.get('RAFII_TWITCH_COMMERCIAL_APPROVED', '')).lower() == 'true'
        diagnostic.update(callbackOriginPinned=True, commercialApproved=approved, featureFlagEnabled=enabled)
        return (cls(client, secret, transport, public_connect_enabled=enabled,
                    commercial_approved=approved) if valid else None), diagnostic

    def assert_enabled(self):
        if not self.execution_enabled or not self.public_connect_enabled or not self.commercial_approved:
            raise AlphaError('Twitch is awaiting operator release and commercial authorization.', 409, code='twitch_release_blocked')

    @staticmethod
    def supports_capability(capability):
        if not isinstance(capability, str):
            return False
        if capability == 'identity':
            return True
        if capability.startswith('twitch.eventsub.subscribe.'):
            from .twitch_eventsub import event_operation_scopes
            return event_operation_scopes(capability) is not None
        from .twitch_native import OPERATIONS
        return capability in OPERATIONS

    def capability_scopes(self, capability):
        if capability == 'identity':
            return []  # /validate and GET users accept a user token without privileged scopes.
        if isinstance(capability, str) and capability.startswith('twitch.eventsub.subscribe.'):
            from .twitch_eventsub import event_operation_scopes
            return list(event_operation_scopes(capability) or [])
        from .twitch_native import OPERATIONS, operation_scopes
        if not isinstance(capability, str) or capability not in OPERATIONS:
            return []
        options = operation_scopes(capability)
        return list(options[0]) if options else []

    @staticmethod
    def available_scopes():
        from .twitch_native import union_supported_scopes
        from .twitch_eventsub import EVENT_TYPES
        return union_supported_scopes() | frozenset(scope for event in EVENT_TYPES.values() for scope in event['scopes'])

    def explain(self, capability):
        if capability == 'identity':
            return 'Confirm your Twitch account without requesting email, chat or channel management permissions. Each native action has its own permission and approval.'
        return 'Enable the selected Twitch capability for this account. Previously granted permissions remain listed. Rafii still requires approval of the exact native action before executing it.'

    @staticmethod
    def assert_callback(redirect):
        if redirect != CALLBACK:
            raise AlphaError('The Twitch callback must be the exact registered Rafii HTTPS URL.', 503, code='twitch_callback_mismatch')

    def authorize_url(self, redirect, state, challenge, scopes):
        self.assert_enabled()
        self.assert_callback(redirect)
        if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', state):
            raise AlphaError('Invalid Twitch authorization state.', 400)
        scopes = _scopes(scopes)
        if set(scopes) - self.available_scopes():
            raise AlphaError('This Twitch permission is not implemented.', 409)
        return self.AUTH + '?' + urlencode({'client_id': self.client_id, 'response_type': 'code',
            'redirect_uri': redirect, 'state': state, 'scope': ' '.join(scopes), 'force_verify': 'true'})

    def _send(self, method, url, *, headers=None, form=None, cleanup=False):
        if not cleanup:
            self.assert_enabled()
        allowed = {('POST', self.TOKEN), ('GET', self.VALIDATE), ('GET', self.USERS), ('POST', self.REVOKE)}
        if (method, url) not in allowed:
            raise AlphaError('Unexpected Twitch OAuth endpoint.', 500)
        try:
            response = self.transport(method, url, headers=headers, form=form)
        except Exception:
            raise AlphaError('Twitch is temporarily unreachable.', 503, code='twitch_validation_unavailable') from None
        if not isinstance(response, dict) or type(response.get('status')) is not int:
            raise AlphaError('Twitch response could not be verified.', 503, code='twitch_validation_unavailable')
        if response['status'] == 429 or 500 <= response['status'] <= 599:
            raise AlphaError('Twitch is temporarily unavailable. Try again later.', 503, code='twitch_validation_unavailable')
        if 300 <= response['status'] <= 399:
            raise AlphaError('Twitch provider redirects are not permitted.', 502, code='twitch_validation_unavailable')
        return response

    def _bound(self, value, kind='at'):
        if not isinstance(value, str) or len(value) > 12288:
            raise AlphaError('Reconnect this Twitch account.', 409, code='twitch_oauth_binding_changed')
        try:
            result = json.loads(value)
        except ValueError:
            result = None
        if (not isinstance(result, dict) or type(result.get('v')) is not int or result.get('v') != 1 or result.get('provider') != 'twitch'
                or result.get('clientId') != self.client_id or not isinstance(result.get('sub'), str)
                or not _USER_ID.fullmatch(result['sub']) or not isinstance(result.get('generation'), str)
                or not _GENERATION.fullmatch(result['generation']) or kind not in ('at', 'rt')
                or set(result) != {'v', 'provider', 'clientId', 'sub', 'generation', kind}):
            raise AlphaError('The Twitch credential binding changed. Reconnect.', 409, code='twitch_oauth_binding_changed')
        _secret(result[kind])
        return result

    def raw_access_token(self, value):
        return self._bound(value, 'at')['at']

    def credential_generation(self, value):
        return self._bound(value, 'at')['generation']

    def credential_subject(self, value):
        return self._bound(value, 'at')['sub']

    def _seal(self, token, kind, subject, generation):
        return json.dumps({'v': 1, 'provider': 'twitch', 'clientId': self.client_id,
                           'sub': subject, 'generation': generation, kind: _secret(token)},
                          sort_keys=True, separators=(',', ':'))

    def validate_raw(self, access, expected_user_id=None):
        response = self._send('GET', self.VALIDATE, headers={'Authorization': 'OAuth ' + _secret(access)})
        if response['status'] == 401:
            raise AlphaError('Twitch access requires renewal.', 409, code='twitch_access_invalid')
        body = response.get('body')
        if response['status'] != 200 or not isinstance(body, dict):
            raise AlphaError('Twitch token could not be validated.', 503, code='twitch_validation_unavailable')
        if (body.get('client_id') != self.client_id or not isinstance(body.get('user_id'), str)
                or not _USER_ID.fullmatch(body['user_id'])
                or (expected_user_id is not None and body['user_id'] != expected_user_id)):
            raise AlphaError('Twitch client or account binding did not match. Reconnect.', 409, code='twitch_revoked_oauth')
        login = body.get('login')
        if not isinstance(login, str) or not re.fullmatch(r'[a-z0-9_]{1,64}', login):
            raise AlphaError('Twitch account could not be validated.', 503, code='twitch_validation_unavailable')
        return {'providerAccountId': body['user_id'], 'login': login, 'scopes': _scopes(body.get('scopes')),
                'expiresIn': _expiry(body.get('expires_in')), 'validatedAt': self.clock()}

    def validate_credentials(self, access_token, expected_account_id):
        bound = self._bound(access_token)
        if bound['sub'] != expected_account_id:
            raise AlphaError('Twitch account binding changed. Reconnect.', 409, code='twitch_revoked_oauth')
        return self.validate_raw(bound['at'], expected_account_id)

    def inspect_scopes(self, access_token, expected_account_id=None):
        bound = self._bound(access_token)
        return self.validate_credentials(access_token, expected_account_id or bound['sub'])['scopes']

    def _finish(self, response, *, previous=None):
        if response['status'] in (400, 401):
            raise AlphaError('Twitch authorization expired or was revoked. Reconnect.', 409, code='twitch_revoked_oauth')
        body = response.get('body')
        if response['status'] != 200 or not isinstance(body, dict) or str(body.get('token_type', '')).lower() != 'bearer':
            raise AlphaError('Twitch authorization could not be verified.', 503, code='twitch_validation_unavailable')
        access, refresh = _secret(body.get('access_token')), _secret(body.get('refresh_token'))
        issued_at = self.clock()
        lifetime = _expiry(body.get('expires_in'))
        receipt = self.validate_raw(access, previous['sub'] if previous else None)
        generation = previous['generation'] if previous else secrets.token_hex(16)
        remaining = int(min(issued_at + lifetime, receipt['validatedAt'] + receipt['expiresIn']) - self.clock())
        if remaining <= 0:
            raise AlphaError('Twitch authorization expired during verification.', 503, code='twitch_validation_unavailable')
        return {'accessToken': self._seal(access, 'at', receipt['providerAccountId'], generation),
                'refreshToken': self._seal(refresh, 'rt', receipt['providerAccountId'], generation),
                'expiresIn': remaining, 'scopes': receipt['scopes'],
                'providerAccountId': receipt['providerAccountId'], 'authorizationGeneration': generation,
                'validatedAt': receipt['validatedAt']}

    def exchange(self, code, verifier, redirect):
        self.assert_callback(redirect)
        response = self._send('POST', self.TOKEN, form={'grant_type': 'authorization_code',
            'client_id': self.client_id, 'client_secret': self.client_secret,
            'code': _secret(code), 'redirect_uri': redirect})
        return self._finish(response)

    def refresh(self, refresh_token):
        previous = self._bound(refresh_token, 'rt')
        response = self._send('POST', self.TOKEN, form={'grant_type': 'refresh_token',
            'client_id': self.client_id, 'client_secret': self.client_secret, 'refresh_token': previous['rt']})
        return self._finish(response, previous=previous)

    def identity(self, access_token):
        bound = self._bound(access_token)
        receipt = self.validate_credentials(access_token, bound['sub'])
        response = self._send('GET', self.USERS,
            headers={'Authorization': 'Bearer ' + bound['at'], 'Client-Id': self.client_id})
        body = response.get('body')
        users = body.get('data') if isinstance(body, dict) else None
        if response['status'] != 200 or not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict):
            raise AlphaError('Twitch account identity could not be verified.', 503, code='twitch_validation_unavailable')
        user = users[0]
        if user.get('id') != receipt['providerAccountId']:
            raise AlphaError('Twitch account identity did not match its token.', 409, code='twitch_revoked_oauth')
        return {'providerAccountId': user['id'], 'handle': '@' + receipt['login'],
                'accountType': user.get('broadcaster_type') if user.get('broadcaster_type') in ('affiliate', 'partner') else 'user'}

    def revoke(self, access_token):
        # Exact access-token revocation only. Local disconnect also removes refresh custody,
        # scheduled authority and EventSub routing; do not claim an app-wide user revoke.
        response = self._send('POST', self.REVOKE,
            form={'client_id': self.client_id, 'token': self.raw_access_token(access_token)}, cleanup=True)
        return response['status'] == 200
