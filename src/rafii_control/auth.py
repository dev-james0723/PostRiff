"""Server-bound founder identity, opaque sessions and deny-by-default capabilities."""
import hashlib
import hmac
import math
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from postriff_phase2.provider_candidates import SupabaseSessionCandidate
from postriff_phase2.hosted_identity import _verified_payload
from postriff_alpha.domain import AlphaError

COOKIE = '__Host-rafii-control'
CAPABILITIES = frozenset({'control.read', 'metrics.query', 'customers.read', 'workspaces.read', 'engineering.read', 'audit.read', 'copilot.use', 'workspaces.test.rename'})


class ControlError(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def boolean(value):
    if value in (None, '', '0', 'false'): return False
    if value in ('1', 'true'): return True
    raise ValueError('Invalid control flag')


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    environment: str = 'local'
    origin: str = 'http://localhost:4449'

    @classmethod
    def from_environment(cls, values):
        enabled = boolean(values.get('RAFII_CONTROL_ENABLED'))
        environment = values.get('RAFII_CONTROL_ENVIRONMENT', 'local')
        origin = values.get('RAFII_CONTROL_ORIGIN', 'http://localhost:4449')
        parsed = urlsplit(origin)
        if environment not in ('local', 'staging', 'production'): raise ValueError('Invalid control environment')
        if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username: raise ValueError('Exact origin required')
        if parsed.scheme != 'https' and not (environment == 'local' and parsed.scheme == 'http' and parsed.hostname == 'localhost'):
            raise ValueError('HTTPS control origin required')
        if environment == 'production' and not parsed.hostname.startswith('ops.'): raise ValueError('Verified ops origin required')
        if values.get('VERCEL_ENV'):
            if environment == 'local' and enabled: raise ValueError('Local control cannot run on Vercel')
            if values.get('RAFII_CONTROL_HARNESS'): raise ValueError('Harness forbidden on Vercel')
            if values['VERCEL_ENV'] == 'preview' and environment == 'production': raise ValueError('Preview cannot use production authority')
            if values['VERCEL_ENV'] == 'preview' and (enabled or values.get('RAFII_CONTROL_SUPABASE_URL')):
                stage, prod = values.get('RAFII_CONTROL_STAGING_PROJECT_REF'), values.get('RAFII_CONTROL_PRODUCTION_PROJECT_REF')
                if not stage or not prod or stage == prod: raise ValueError('Verified distinct staging identity required')
                if values.get('RAFII_CONTROL_SUPABASE_URL') != f'https://{stage}.supabase.co': raise ValueError('Preview identity mismatch')
                if values.get('POSTRIFF_DATABASE_URL') or values.get('SUPABASE_SERVICE_ROLE_KEY'): raise ValueError('Consumer/privileged credentials forbidden')
        return cls(enabled, environment, origin)


@dataclass(frozen=True)
class VerifiedIdentity:
    user_id: str
    assurance: str
    upstream_session: str
    mfa_at: float


def fresh_mfa(payload):
    methods = payload.get('amr') or []
    if not isinstance(methods, list): return 0
    # Supabase stamps 'totp' for TOTP MFA. Passkey/password/iat do not establish AAL2.
    return max((float(item['timestamp']) for item in methods if isinstance(item, dict)
                and item.get('method') in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
                and type(item.get('timestamp')) in (int, float) and math.isfinite(item['timestamp'])), default=0)


def supabase_identity(project_url, get_user):
    if not isinstance(project_url,str) or not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co/?',project_url): raise ValueError('Exact Supabase origin required')
    candidate = SupabaseSessionCandidate(project_url, get_user)
    def verify(token):
        if not isinstance(token, str) or not 32 <= len(token) <= 8192: raise ControlError('AUTH_REQUIRED', 401)
        try: user = candidate.verify(token)  # HTTPS getUser checks signature/identity before claims are decoded.
        except AlphaError as error: raise ControlError('AUTH_REQUIRED', 401) from error
        try: payload = _verified_payload(token, user)
        except AlphaError as error: raise ControlError('AUTH_REQUIRED', 401) from error
        session = payload.get('session_id')
        if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,160}', session): raise ControlError('AUTH_REQUIRED', 401)
        return VerifiedIdentity(user, payload.get('aal', 'aal1'), session, fresh_mfa(payload))
    return verify


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return hmac.new(token.encode(), b'rafii-control-v2-csrf', hashlib.sha256).hexdigest()


class Boundary:
    def __init__(self, config, store, verify_identity, clock=time.time):
        self.config, self.store, self.verify_identity, self.clock = config, store, verify_identity, clock

    def gate(self, origin=None):
        if not self.config.enabled: raise ControlError('SOURCE_UNAVAILABLE', 404)
        if origin is not None and origin != self.config.origin: raise ControlError('SCOPE_DENIED')

    def _audit(self, action, result, user=None, session=None, request_id=None, error_code=None):
        self.store.audit(action=action, result=result, actor=user, session=session, environment=self.config.environment, request_id=request_id or str(uuid.uuid4()), error_code=error_code)

    def _operator(self, user):
        operator = self.store.operator(user, self.config.environment)
        if not operator or operator['status'] != 'active' or operator['role'] != 'founder': raise ControlError('FOUNDER_REQUIRED')
        return operator

    def exchange(self, upstream_token, origin, request_id=None):
        user = None
        try:
            self.gate(origin)
            self.store.budget('exchange', 'global', 10)
            identity = self.verify_identity(upstream_token)
            user = str(uuid.UUID(identity.user_id))
            operator = self._operator(user)
            now = self.clock()
            if identity.assurance != 'aal2' or not 0 <= now - identity.mfa_at <= 300: raise ControlError('STEP_UP_REQUIRED')
            if not self.store.identity_active(user, identity.upstream_session): raise ControlError('AUTH_REQUIRED', 401)
            token = secrets.token_urlsafe(48)
            row = dict(id=str(uuid.uuid4()), user_id=user, environment=self.config.environment, token_hash=digest(token),
                       auth_epoch=operator['auth_epoch'], assurance='aal2', upstream_session=identity.upstream_session,
                       mfa_at=identity.mfa_at, created_at=now, last_seen_at=now, expires_at=now + 28800, revoked_at=None)
            self.store.create_session(row)
            self._audit('session.exchange', 'allowed', user, row['id'], request_id)
            return token, {'csrfToken': csrf_token(token), 'assurance': 'aal2', 'expiresAt': row['expires_at'],
                           'capabilities': sorted(set(operator['capabilities']) & CAPABILITIES)}
        except ControlError as error:
            self._audit('session.exchange', 'denied', user, request_id=request_id, error_code=error.code)
            raise

    def authorize(self, token, capability, *, origin=None, csrf=None, unsafe=False, step_up=False, request_id=None):
        user, session_id = None, None
        try:
            self.gate(origin if unsafe else None)
            if not isinstance(token, str) or not 32 <= len(token) <= 128: raise ControlError('AUTH_REQUIRED', 401)
            row = self.store.session(digest(token))
            now = self.clock()
            if not row or row['revoked_at'] is not None or row['expires_at'] <= now or now - row['last_seen_at'] >= 1800:
                raise ControlError('AUTH_REQUIRED', 401)
            user, session_id = row['user_id'], row['id']
            operator = self._operator(user)
            if row['environment'] != self.config.environment or row['auth_epoch'] != operator['auth_epoch']:
                raise ControlError('AUTH_REQUIRED', 401)
            if row['assurance'] != 'aal2': raise ControlError('STEP_UP_REQUIRED')
            if not self.store.identity_active(user, row['upstream_session']): raise ControlError('AUTH_REQUIRED', 401)
            if capability not in CAPABILITIES or capability not in operator['capabilities']: raise ControlError('SCOPE_DENIED')
            if unsafe and (origin != self.config.origin or not isinstance(csrf, str) or not hmac.compare_digest(csrf_token(token), csrf)):
                raise ControlError('SCOPE_DENIED')
            if step_up and not 0 <= now - row['mfa_at'] <= 300: raise ControlError('STEP_UP_REQUIRED')
            purpose = 'copilot.read' if capability == 'copilot.use' and not unsafe else capability
            self.store.budget(purpose, user, 5 if purpose == 'copilot.use' else 30 if capability == 'metrics.query' else 120)
            self._audit(capability, 'allowed', user, session_id, request_id)
            self.store.touch(row['token_hash'], now)
            return {'operator': operator, 'session': row, 'csrfToken': csrf_token(token)}
        except ControlError as error:
            self._audit(capability if capability in CAPABILITIES else 'prohibited', 'denied', user, session_id, request_id, error.code)
            raise

    def logout(self, token):
        self.store.revoke(digest(token), self.clock())
