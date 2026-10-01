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
CAPABILITIES = frozenset({'control.read', 'metrics.query', 'customers.read', 'workspaces.read', 'engineering.read', 'audit.read', 'copilot.use', 'workspaces.test.rename',
                          # Founder Admin v2 (CONTRACTS §3). The last two are also the audit action names the agent/contact slices record.
                          'incidents.ack', 'followups.write', 'control.settings', 'founder.agent.turn', 'founder.call.request',
                          # Founder Admin P1/P2 (CONTRACTS §8, migration 056). Every write among them needs a fresh second factor
                          # (step_up) and a preview → confirm pair with a content-free audit row; the agent never holds them.
                          'usage.reconcile', 'credits.adjust', 'accounts.block', 'refunds.prepare', 'founder.export'})
# Per-minute request budgets by purpose. Purposes not listed share the dashboard read budget (READ_BUDGET). A page load makes
# five to ten Control reads (session, page records, incidents, follow-ups, receipts), so 300/min lets a founder move quickly
# between sections and still bounds a runaway client. A domain page asks for
# 8–15 receipted metrics at once, so metrics.query allows 240/min (4/s): enough to move between sections, still a hard ceiling.
READ_BUDGET = 300
BUDGETS = {'copilot.use': 5, 'metrics.query': 240, 'founder.agent.turn': 20, 'founder.call.request': 5, 'founder.action': 10, 'founder.voice': 5, 'founder.export': 10}
MOUNTS = ('separate', 'embedded')


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
    """Deployment shape of Control.

    ``mount='separate'`` is the original dedicated Vercel project (one exact origin, no consumer credentials in
    the process). ``mount='embedded'`` serves the same `/api/control/v2` prefix from inside the consumer API, so
    the browser origin is the consumer app's own origin(s) and consumer credentials legitimately share the
    process; Control tolerates their presence there but never reads them.
    """
    enabled: bool = False
    environment: str = 'local'
    origin: str = 'http://localhost:4449'
    mount: str = 'separate'
    origins: tuple = ()

    @property
    def allowed_origins(self):
        """Every browser origin Control answers; ``origin`` stays the first one for callers that need a single value."""
        return self.origins or (self.origin,)

    @classmethod
    def from_environment(cls, values):
        enabled = boolean(values.get('RAFII_CONTROL_ENABLED'))
        environment = values.get('RAFII_CONTROL_ENVIRONMENT', 'local')
        mount = values.get('RAFII_CONTROL_MOUNT', 'separate')
        if mount not in MOUNTS: raise ValueError('Invalid control mount')
        if mount == 'embedded': return cls._embedded(values, enabled, environment)
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
                cls._staging_identity(values)
                if values.get('POSTRIFF_DATABASE_URL') or values.get('SUPABASE_SERVICE_ROLE_KEY'): raise ValueError('Consumer/privileged credentials forbidden')
        return cls(enabled, environment, origin, 'separate', (origin,))

    @staticmethod
    def _staging_identity(values):
        stage, prod = values.get('RAFII_CONTROL_STAGING_PROJECT_REF'), values.get('RAFII_CONTROL_PRODUCTION_PROJECT_REF')
        if not stage or not prod or stage == prod: raise ValueError('Verified distinct staging identity required')
        if values.get('RAFII_CONTROL_SUPABASE_URL') != f'https://{stage}.supabase.co': raise ValueError('Preview identity mismatch')

    @classmethod
    def _embedded(cls, values, enabled, environment):
        """Embedded mount. Origins come only from RAFII_CONTROL_ORIGINS (comma list) plus, on a Vercel preview, the
        deployment's own https://VERCEL_URL and https://VERCEL_BRANCH_URL. Production never infers an origin.
        The consumer-credential checks of the separate mount do not apply: those variables are never read here."""
        if environment not in ('local', 'staging', 'production'): raise ValueError('Invalid control environment')
        vercel = values.get('VERCEL_ENV')
        listed = [item.strip() for item in values.get('RAFII_CONTROL_ORIGINS', '').split(',') if item.strip()]
        if vercel == 'preview':
            listed.extend(f'https://{values[key]}' for key in ('VERCEL_URL', 'VERCEL_BRANCH_URL') if values.get(key))
        if not listed: raise ValueError('Explicit control origins required')
        for origin in listed:
            parsed = urlsplit(origin)
            if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username: raise ValueError('Exact origin required')
            if parsed.scheme != 'https' and not (environment == 'local' and parsed.scheme == 'http' and parsed.hostname == 'localhost'):
                raise ValueError('HTTPS control origin required')
        if vercel:
            if values.get('RAFII_CONTROL_HARNESS'): raise ValueError('Harness forbidden on Vercel')
            if environment == 'local' and enabled: raise ValueError('Local control cannot run on Vercel')
            if vercel == 'preview' and environment == 'production': raise ValueError('Preview cannot use production authority')
            if vercel == 'preview' and enabled and environment != 'staging': raise ValueError('Preview control must run as staging')
            if vercel == 'preview' and (enabled or values.get('RAFII_CONTROL_SUPABASE_URL')): cls._staging_identity(values)
        origins = tuple(dict.fromkeys(listed))
        return cls(enabled, environment, origins[0], 'embedded', origins)


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
        if origin is not None and origin not in self.config.allowed_origins: raise ControlError('SCOPE_DENIED')

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

    def authorize(self, token, capability, *, origin=None, csrf=None, unsafe=False, step_up=False, ending_session=False, ending_preview=False, request_id=None, purpose=None):
        """``purpose`` only selects the per-minute budget bucket (see BUDGETS); the audit action is always the capability."""
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
            if unsafe and (origin not in self.config.allowed_origins or not isinstance(csrf, str) or not hmac.compare_digest(csrf_token(token), csrf)):
                raise ControlError('SCOPE_DENIED')
            if step_up and not 0 <= now - row['mfa_at'] <= 300: raise ControlError('STEP_UP_REQUIRED')
            if ending_session and (capability != 'control.read' or not unsafe): raise ControlError('SCOPE_DENIED')
            if ending_preview and (capability != 'control.read' or not unsafe): raise ControlError('SCOPE_DENIED')
            # Read throttling must not prevent an authorized founder from revoking their session.
            purpose = 'session.logout' if ending_session else 'preview.stop' if ending_preview else 'copilot.read' if capability == 'copilot.use' and not unsafe else purpose or capability
            self.store.budget(purpose, user, BUDGETS.get(purpose, READ_BUDGET))
            self._audit(capability, 'allowed', user, session_id, request_id)
            self.store.touch(row['token_hash'], now)
            return {'operator': operator, 'session': row, 'csrfToken': csrf_token(token)}
        except ControlError as error:
            self._audit(capability if capability in CAPABILITIES else 'prohibited', 'denied', user, session_id, request_id, error.code)
            raise

    def logout(self, token):
        self.store.revoke(digest(token), self.clock())
