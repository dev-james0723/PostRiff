"""Server-configured, time-limited Pinterest Trial authority. No user input enables it."""
from dataclasses import dataclass
import re
import math
import time
import uuid
from postriff_alpha.domain import AlphaError

READ_SCOPES = frozenset({'user_accounts:read', 'boards:read'})


def _internal_scopes(scopes):
    """Validate scopes from OAuth grants, PostgreSQL arrays and internal callers.

    PostgreSQL/client adapters may return an ordered list or tuple; internal
    analytics callers may supply a set/frozenset. Never interpret a string,
    mapping or malformed scalar as a grant (including comma-joined text).
    """
    if type(scopes) not in (list, tuple, set, frozenset) or not scopes:
        return None
    if any(type(scope) is not str or not scope for scope in scopes):
        return None
    return frozenset(scopes)


@dataclass(frozen=True)
class PinterestTrialPolicy:
    workspace_id: str
    actor_id: str
    username: str
    expires_at: int

    @classmethod
    def from_environment(cls, values):
        prefix = 'POSTRIFF_PINTEREST_TRIAL_'
        workspace = values.get(prefix + 'WORKSPACE_ID', '')
        actor = values.get(prefix + 'ACTOR_ID', '')
        username = values.get(prefix + 'USERNAME', '')
        expires = values.get(prefix + 'EXPIRES_AT', '')
        try:
            # Exactly one canonical UUID per field; no wildcard, CSV or tenant list.
            if any(not isinstance(v, str) or str(uuid.UUID(v)) != v for v in (workspace, actor)):
                raise ValueError('UUID')
            if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,30}', username):
                raise ValueError('username')
            if not isinstance(expires, str) or not re.fullmatch(r'[0-9]{10}', expires):
                raise ValueError('expiry')
            expiry = int(expires)
            if not time.time() < expiry <= time.time() + 86400:
                raise ValueError('pilot must expire within 24 hours')
        except (ValueError, AttributeError, TypeError) as error:
            raise AlphaError('Pinterest Trial needs an exact workspace, operator, account and expiry within 24 hours.',
                             503, code='pinterest_trial_configuration') from error
        return cls(workspace, actor, username.casefold(), expiry)

    def require(self, workspace_id, actor_id=None, *, now=None):
        now = time.time() if now is None else now
        if (workspace_id != self.workspace_id or actor_id is not None and actor_id != self.actor_id
                or now >= self.expires_at):
            raise AlphaError('This Pinterest Trial is unavailable for this workspace or operator, or has expired.',
                             403, code='pinterest_trial_denied')

    @staticmethod
    def require_scopes(scopes):
        granted = _internal_scopes(scopes)
        if granted is None or not granted <= READ_SCOPES:
            raise AlphaError('Reconnect Pinterest with profile and board read permissions only for this Trial.',
                             403, code='pinterest_trial_readonly')

    def require_identity(self, identity):
        if identity.get('handle', '').removeprefix('@').casefold() != self.username:
            raise AlphaError('A different Pinterest account was selected. Reconnect the approved Trial account.',
                             409, code='pinterest_trial_account_mismatch')


@dataclass(frozen=True)
class PinterestExecutionTrialPolicy(PinterestTrialPolicy):
    """Private account-bound capability trial; never an assertion of Standard Access."""
    provider_account_id: str
    board_ids: tuple
    capabilities: frozenset
    pilot_id: str

    @classmethod
    def from_environment(cls, values):
        base = PinterestTrialPolicy.from_environment(values)
        prefix = 'POSTRIFF_PINTEREST_TRIAL_'
        account = values.get(prefix + 'ACCOUNT_ID', '')
        board_value = values.get(prefix + 'BOARD_IDS', '')
        cap_value = values.get(prefix + 'CAPABILITIES', '')
        pilot = values.get(prefix + 'ID', '')
        allowed = {'identity', 'boards_read', 'publish', 'schedule', 'analytics'}
        try:
            if not isinstance(board_value, str) or not isinstance(cap_value, str):
                raise ValueError('list configuration')
            boards, caps = board_value.split(','), cap_value.split(',')
            if not re.fullmatch(r'[0-9]{5,30}', account):
                raise ValueError('account')
            if not 1 <= len(boards) <= 4 or len(set(boards)) != len(boards) or any(not re.fullmatch(r'[0-9]{5,30}', b) for b in boards):
                raise ValueError('boards')
            if len(set(caps)) != len(caps) or not {'identity', 'boards_read'} <= set(caps) <= allowed:
                raise ValueError('capabilities')
            # Rafii's immediate and future Pins share the durable queue. This
            # bounded execution mode therefore admits both actions together.
            if ('schedule' in caps) != ('publish' in caps):
                raise ValueError('publish and schedule must be scoped together')
            if str(uuid.UUID(pilot)) != pilot:
                raise ValueError('pilot')
        except (ValueError, TypeError, AttributeError):
            raise AlphaError('Private Pinterest Trial needs a stable account, exact boards, capability list and pilot ID.', 503,
                             code='pinterest_trial_configuration') from None
        return cls(base.workspace_id, base.actor_id, base.username, base.expires_at, account,
                   tuple(sorted(boards)), frozenset(caps), pilot)

    def binding(self):
        return {'workspace': self.workspace_id, 'actor': self.actor_id, 'username': self.username,
                'expiresAt': self.expires_at, 'account': self.provider_account_id,
                'boards': list(self.board_ids), 'capabilities': sorted(self.capabilities), 'pilot': self.pilot_id,
                'maxCreateAttempts': 2}

    def supports(self, capability):
        return capability in self.capabilities

    def require_scopes(self, scopes):
        permitted = set(READ_SCOPES)
        if self.supports('analytics') or self.supports('publish'):
            permitted.add('pins:read')
        if self.supports('publish'):
            permitted.add('pins:write')
        granted = _internal_scopes(scopes)
        if granted is None or not granted <= permitted:
            raise AlphaError('The requested Pinterest scope is outside this private Trial.', 403, code='pinterest_trial_denied')

    def require_account(self, account_id):
        if account_id != self.provider_account_id:
            raise AlphaError('This Pinterest account is outside the approved private Trial.', 403, code='pinterest_trial_account_mismatch')

    def require_identity(self, identity):
        super().require_identity(identity)
        self.require_account(identity.get('providerAccountId'))

    def require_board(self, board_id):
        if board_id not in self.board_ids:
            raise AlphaError('Choose an explicitly approved private Trial board.', 403, code='pinterest_trial_denied')

    def require_manifest(self, manifest, *, now=None):
        self.require(manifest.get('workspaceId'), manifest.get('actor'), now=now)
        if manifest.get('actor') != self.actor_id:
            raise AlphaError('Only the approved operator can authorize this private Trial Pin.', 403, code='pinterest_trial_denied')
        self.require_account(manifest.get('providerAccountId'))
        self.require_board((manifest.get('publishOptions') or {}).get('boardId'))
        if manifest.get('platform') != 'Pinterest' or not self.supports('publish') or not self.supports('schedule') or not manifest.get('idempotencyKey'):
            raise AlphaError('This Pinterest operation is outside the private Trial.', 403, code='pinterest_trial_denied')
        at = (manifest.get('timing') or {}).get('timestamp')
        if type(at) not in (int, float) or not math.isfinite(at) or not 0 < at < self.expires_at:
            raise AlphaError('Schedule this approved Pin inside the private Trial window.', 403, code='pinterest_trial_denied')
