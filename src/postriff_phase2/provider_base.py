"""Shared base for hosted channel adapters. `providers.py` re-exports these names and owns `http_transport`."""
from postriff_alpha.domain import AlphaError

GRAPH_VERSION = "v24.0"  # current Graph API version read in the 2026-09-15 audit; re-verify at review time


def default_transport():
    from .providers import http_transport  # resolved at call time: tests patch providers.build_opener
    return http_transport


def _credential_shape(value):
    # Shape is not provider authentication. Never include the supplied value in an error.
    return (isinstance(value, str) and 0 < len(value) <= 8192
            and not any(character.isspace() for character in value)
            and not value.startswith('<')
            and value.lower() not in {'change-me', 'changeme', 'replace-me', 'placeholder', 'todo'})


class OAuthProvider:
    id = ""
    platform = ""
    capability_version = 1
    native_schedule = False
    assisted_fallback = True
    SCOPES = {}
    EXPLAIN = {}
    # Channels card and readiness copy; each adapter states its own (oauth.py never branches on a platform name).
    account_requirement = ""
    read_scope = None
    publish_scope = None
    publish_required = frozenset()
    # "oauth": redirect to the provider. "bot_code": the person posts a one-time code where Rafii's bot can see it.
    connect_kind = "oauth"
    # {"name", "label", "placeholder"} when connecting needs one value first (a Bluesky handle, a Mastodon server).
    start_input = None
    # True when the callback carries an `iss` that the exchange must check.
    requires_issuer = False
    # Grants that never expire (bot-held access, Mastodon tokens): no expiry date is invented for them.
    non_expiring = False
    # True when posting needs a destination: chosen once per connection (a Discord channel, a Facebook Page) or for
    # each post (a Pinterest board); `destination_label` names it on screen.
    has_destinations = False
    destination_scope, destination_label = "connection", "Channel"
    # True when revoking acts on something other workspaces may share (Rafii's bot in a server or channel).
    shared_remote = False
    # Renew this many seconds before expiry, so a publish never starts on a token about to lapse (0 = at expiry).
    refresh_margin = 0

    def __init__(self, client_id, client_secret, transport=None, production_reviewed=False):
        if not client_id or not client_secret:
            raise AlphaError(f"{self.platform} client credentials are required.", 503)
        self.client_id, self.client_secret = client_id, client_secret
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True

    @classmethod
    def env_prefix(cls):
        return f"POSTRIFF_OAUTH_{cls.id.upper()}_"

    @classmethod
    def credential_pair(cls, values):
        """(client id, secret, valid, presence-only diagnostic) for POSTRIFF_OAUTH_<ID>_CLIENT_ID/_CLIENT_SECRET."""
        prefix = cls.env_prefix()
        client_id, secret = values.get(prefix + "CLIENT_ID"), values.get(prefix + "CLIENT_SECRET")
        presence = {'clientId': client_id is not None, 'clientSecret': secret is not None}
        missing = [prefix + suffix for suffix, present in (('CLIENT_ID', presence['clientId']), ('CLIENT_SECRET', presence['clientSecret'])) if not present]
        valid = _credential_shape(client_id) and _credential_shape(secret)
        state = 'not_configured' if len(missing) == 2 else 'partial_configuration' if missing else 'configured' if valid else 'invalid_configuration'
        return client_id, secret, valid, {'configurationState': state, 'credentialPresence': presence, 'missingVariables': missing}

    @classmethod
    def mount(cls, values, transport=None):
        """(adapter or None, presence-only diagnostic). Only a valid-shaped complete credential pair mounts."""
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        return (cls(client_id, secret, transport=transport) if valid else None), diagnostic

    def capability_scopes(self, capability):
        return list(self.SCOPES.get(capability, []))

    def explain(self, capability):
        return self.EXPLAIN.get(capability, "Rafii will act on this account only when you approve an exact action.")

    def revoke(self, token):
        return False

    @staticmethod
    def _ok(response, *keys):
        body = response.get("body", {})
        if response.get("status") != 200 or not isinstance(body, dict) or any(not body.get(k) for k in keys):
            raise AlphaError("The provider did not complete this authorization step.", 502)
        return body
