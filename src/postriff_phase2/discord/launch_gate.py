"""Discord launch gate and server cap. Fail closed; no Discord I/O, no schema, no scheduler.

Rafii runs ONE Discord bot for every customer, and a Discord app that is not verified may be in at most 100 servers.
This module decides who may START a Discord connection and how many servers the bot may join, so a build can go live
dark, be proven on tester workspaces, and then open without a second build.

Gate, POSTRIFF_DISCORD_CONNECT_WORKSPACES (read at request time, never cached):
- unset: nobody on hosted production (VERCEL_ENV or POSTRIFF_ENVIRONMENT is "production"), everybody elsewhere so
  development and CI behave as before;
- set but empty: nobody;
- "*": everybody. It must be written out;
- otherwise a comma or whitespace separated list of workspace UUIDs;
- anything malformed (a bad id, "*" mixed with ids) closes the gate and is reported as misconfigured.

A workspace that already has a live Discord footprint (an unrevoked server card or a linked identity) is never locked
out, so closing the gate stops NEW connections only. Existing connections, queued posts and the kill switch
(POSTRIFF_OAUTH_DISCORD_DISABLED) are unaffected.

Cap, POSTRIFF_DISCORD_GUILD_CAP: unset is 90 on hosted production and unlimited elsewhere; "0" blocks every new server;
garbage becomes 0. The bot joins a server on Discord's consent screen, BEFORE Rafii's callback runs, so the cap is
enforced when a new installation is STARTED (reservation under an advisory lock), never at the callback.
"""
import re

from postriff_alpha.domain import AlphaError

ENV_WORKSPACES = 'POSTRIFF_DISCORD_CONNECT_WORKSPACES'
ENV_CAP = 'POSTRIFF_DISCORD_GUILD_CAP'
DEFAULT_PRODUCTION_CAP = 90

CLOSED_MESSAGE = 'Discord is not open to new connections for this workspace yet. Connections you already have keep working.'
CAPACITY_MESSAGE = 'Discord has no room for another server right now. Nothing was connected or posted. Try again later.'

_WORKSPACE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_DIGITS = re.compile(r'^[0-9]{1,9}$')

_LOCK = "SELECT pg_advisory_xact_lock(hashtext('rafii.discord.server-cap'))"
# Servers the bot is already in (one per distinct server, however many workspaces share it) plus installations that
# were started or are mid-exchange: the bot may already be in those servers although no credential is stored yet.
_COUNT = """SELECT
  (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials
     WHERE provider='discord' AND revoked_at IS NULL AND 'bot' = ANY(scopes))
  +
  (SELECT count(*) FROM public.pr_oauth_transactions
     WHERE provider='discord' AND 'bot' = ANY(scopes)
       AND ((consumed_at IS NULL AND expires_at > now())
            OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes')))"""


class Gate:
    __slots__ = ('mode', 'workspaces', 'misconfigured')

    def __init__(self, mode, workspaces=frozenset(), misconfigured=False):
        self.mode, self.workspaces, self.misconfigured = mode, frozenset(workspaces), misconfigured

    def allows(self, workspace_id):
        if self.mode == 'open':
            return True
        return self.mode == 'list' and isinstance(workspace_id, str) and workspace_id.strip().lower() in self.workspaces


def _values(values):
    if values is None:
        import os
        return os.environ
    return values


def hosted_production(values=None):
    values = _values(values)
    return values.get('VERCEL_ENV') == 'production' or values.get('POSTRIFF_ENVIRONMENT') == 'production'


def configuration(values=None):
    values = _values(values)
    raw = values.get(ENV_WORKSPACES)
    if raw is None:
        return Gate('closed' if hosted_production(values) else 'open')
    raw = str(raw).strip()
    if not raw:
        return Gate('closed')
    if raw == '*':
        return Gate('open')
    ids = [part.lower() for part in re.split(r'[\s,]+', raw) if part]
    if not ids or any(not _WORKSPACE.match(part) for part in ids):
        return Gate('closed', misconfigured=True)
    return Gate('list', ids)


def guild_cap(values=None):
    """(cap or None for unlimited, misconfigured)."""
    values = _values(values)
    raw = values.get(ENV_CAP)
    if raw is None:
        return (DEFAULT_PRODUCTION_CAP if hosted_production(values) else None), False
    raw = str(raw).strip()
    if not _DIGITS.match(raw):
        return 0, True
    return int(raw), False


def has_footprint(state):
    """True when this workspace already has a live Discord server card or linked identity."""
    phase2 = state.get('phase2') if isinstance(state, dict) else None
    if not isinstance(phase2, dict):
        return False
    channels, links = phase2.get('channels'), phase2.get('discordIdentityLinks')
    if isinstance(channels, list) and any(isinstance(c, dict) and c.get('platform') == 'Discord' and not c.get('revoked') for c in channels):
        return True
    return isinstance(links, list) and any(isinstance(link, dict) and link.get('status') == 'linked' for link in links)


def access(workspace_id, state, values=None):
    gate = configuration(values)
    if gate.allows(workspace_id):
        return {'status': 'open', 'reason': 'open_to_all' if gate.mode == 'open' else 'allowlisted'}
    if has_footprint(state):
        return {'status': 'open', 'reason': 'existing_connection'}
    return {'status': 'closed', 'reason': 'misconfigured' if gate.misconfigured else 'invite_only'}


def require_connect_access(connections, workspace, token, values=None):
    """Refuse a NEW Discord connection for a workspace outside the gate. Runs before any provider request."""
    if configuration(values).allows(workspace):
        return
    with connections.local(workspace, token) as (_cur, state, _actor):
        verdict = access(workspace, state, values)
    if verdict['status'] != 'open':
        raise AlphaError(CLOSED_MESSAGE, 403, code='discord_access_closed')


def reserve_capacity(cur, values=None):
    """Inside the transaction that records a new installation start: serialise, count, refuse at the cap."""
    cap, _misconfigured = guild_cap(values)
    if cap is None:
        return None
    cur.execute(_LOCK)
    cur.execute(_COUNT)
    used = int(cur.fetchone()[0])
    if used >= cap:
        raise AlphaError(CAPACITY_MESSAGE, 409, code='discord_capacity_reached')
    return {'used': used, 'cap': cap}


def annotate_catalog(entries, workspace_id, state, values=None):
    """Tell the UI whether THIS workspace may start a Discord connection. Other providers are untouched."""
    for entry in entries:
        if entry.get('id') != 'discord':
            continue
        verdict = access(workspace_id, state, values)
        entry['discordAccess'] = {**verdict, 'capped': guild_cap(values)[0] is not None}
        if verdict['status'] != 'open':
            entry['connectReady'] = False
    return entries
