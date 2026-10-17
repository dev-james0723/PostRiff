"""Server-configured, time-limited Pinterest Trial authority. No user input enables it."""
from dataclasses import dataclass
import re
import time
import uuid
from postriff_alpha.domain import AlphaError

READ_SCOPES = frozenset({'user_accounts:read', 'boards:read'})


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
        if (not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) for s in scopes)
                or not set(scopes) <= READ_SCOPES):
            raise AlphaError('Reconnect Pinterest with profile and board read permissions only for this Trial.',
                             403, code='pinterest_trial_readonly')

    def require_identity(self, identity):
        if identity.get('handle', '').removeprefix('@').casefold() != self.username:
            raise AlphaError('A different Pinterest account was selected. Reconnect the approved Trial account.',
                             409, code='pinterest_trial_account_mismatch')
