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

A workspace that already has a live Discord footprint (an unrevoked server card, or a linked identity, including one
that must be reconnected) is never locked out, so closing the gate stops connections from workspaces with no Discord
history. Such a workspace may still start any kind of connection, including a new server (which then takes a cap slot).
Existing connections, queued posts and the kill switch (POSTRIFF_OAUTH_DISCORD_DISABLED) are unaffected.

Cap, POSTRIFF_DISCORD_GUILD_CAP: unset is 90 on hosted production and unlimited elsewhere; "0" blocks every new server;
garbage becomes 0. The bot joins a server on Discord's consent screen, BEFORE Rafii's callback runs, so the cap is
enforced when a new installation is STARTED (reservation under an advisory lock), never at the callback. A disconnect
does not remove the shared bot from a server, so servers whose grant was revoked still count toward the cap. A server
that already has a bot credential row holds its slot and is never counted twice.

Every live installation start holds its own slot, because each one is a server the bot may join (the authorize link
stays usable at Discord whatever Rafii does to the row). To keep one account from holding the cap by starting over and
over, a person (workspace and member) may have at most MAX_PENDING_PER_PERSON starts in flight; a fourth is refused until
one finishes or expires (ten minutes). A server that already has a bot credential row is admitted at any fill, even
with the cap at 0 or misconfigured: it takes no new slot. The original (non-v2) connect flow cannot name the server
before the person picks it on Discord's screen, so it always asks for a slot.

What the count cannot see (compare with the Developer Portal's own number, monitoring.sql Q9 and Q12): a person who
picks a different server on Discord's screen than the one reserved, or closes the tab after consenting, or whose
callback fails, has still put the bot in a server that Rafii holds no row for; so do deleted workspaces and anyone who
adds the public bot by hand.
"""
import re

from postriff_alpha.domain import AlphaError

ENV_WORKSPACES = 'POSTRIFF_DISCORD_CONNECT_WORKSPACES'
ENV_CAP = 'POSTRIFF_DISCORD_GUILD_CAP'
DEFAULT_PRODUCTION_CAP = 90
MAX_PENDING_PER_PERSON = 3

CLOSED_MESSAGE = 'Discord is not open to new connections for this workspace yet. Connections you already have keep working.'
CAPACITY_MESSAGE = 'Discord has no room for another server right now. Nothing was connected or posted. Try again later.'
PENDING_MESSAGE = 'You already have Discord installations waiting to be finished. Finish them or try again in a few minutes. Nothing was connected or posted.'

_WORKSPACE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_DIGITS = re.compile(r'^[0-9]{1,9}$')

_LOCK = "SELECT pg_advisory_xact_lock(hashtext('rafii.discord.server-cap'))"
# Servers the bot is in (one per distinct server, however many workspaces share it) plus installations that were
# started or are mid-exchange: the bot may already be in those servers although no credential is stored yet. A
# disconnect only revokes Rafii's stored grant; the shared bot stays in the server, and the row keeps the server id and
# scopes, so revoked rows still count. (Deleted workspaces take their rows with them; compare with the Developer
# Portal's own server count, see monitoring.sql Q9.) Each in-flight start is counted exactly, one slot per row: the
# server it will join is inside the encrypted request and cannot be compared, so collapsing rows per person would let
# one account open the bot to many servers for the price of one. A double click or a reconnect start therefore holds
# a slot for the minutes it is in flight; that over-count is deliberate, and MAX_PENDING_PER_PERSON bounds it.
_IN_FLIGHT = """provider='discord' AND 'bot' = ANY(scopes)
       AND ((consumed_at IS NULL AND expires_at > now())
            OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))"""
_COUNT = """SELECT
  (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials
     WHERE provider='discord' AND 'bot' = ANY(scopes))
  +
  (SELECT count(*) FROM public.pr_oauth_transactions
     WHERE """ + _IN_FLIGHT + """)"""
# What one person already has in flight (reconnect starts included).
_PENDING = """SELECT count(*) FROM public.pr_oauth_transactions
  WHERE """ + _IN_FLIGHT + """ AND workspace_id = %s AND member_id = %s"""
# A server that already has a bot credential row (revoked or not) holds its slot: starting it again, from this or
# another workspace, must not need a second one.
_KNOWN = """SELECT 1 FROM public.pr_encrypted_credentials
  WHERE provider='discord' AND 'bot' = ANY(scopes) AND provider_account_id = %s LIMIT 1"""


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
    """Case and space tolerant on purpose: a misspelt production must close the gate, not open it."""
    values = _values(values)
    return any(str(values.get(name) or '').strip().lower() == 'production' for name in ('VERCEL_ENV', 'POSTRIFF_ENVIRONMENT'))


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
    """True when this workspace already has a live Discord server card or a linked identity. An identity whose refresh
    failed ('reconnect_required') still counts: its person must be able to reconnect, and its dependants are revoked or,
    after an unconfirmed refresh, suspended until the same Discord user links again."""
    phase2 = state.get('phase2') if isinstance(state, dict) else None
    if not isinstance(phase2, dict):
        return False
    channels, links = phase2.get('channels'), phase2.get('discordIdentityLinks')
    if isinstance(channels, list) and any(isinstance(c, dict) and c.get('platform') == 'Discord' and not c.get('revoked') for c in channels):
        return True
    return isinstance(links, list) and any(isinstance(link, dict) and link.get('status') in ('linked', 'reconnect_required') for link in links)


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


def reserve_capacity(cur, values=None, guild_id=None, person=None, new_server=True):
    """Inside the transaction that records a new installation start: serialise, count, refuse at the cap.

    `guild_id` (the server being installed, when known) lets a server that already holds a slot through at any fill.
    `person` is (workspace id, member id): at most MAX_PENDING_PER_PERSON starts of theirs may be in flight, whatever the
    cap. `new_server=False` is a reconnect of a server Rafii already holds: it takes no slot but still counts as a start."""
    cap, _misconfigured = guild_cap(values)
    if cap is None:
        return None
    cur.execute(_LOCK)
    if person:
        cur.execute(_PENDING, tuple(person))
        if int(cur.fetchone()[0]) >= MAX_PENDING_PER_PERSON:
            raise AlphaError(PENDING_MESSAGE, 409, code='discord_capacity_reached')
    if not new_server:
        return {'reconnect': True, 'cap': cap}
    if guild_id:
        cur.execute(_KNOWN, (str(guild_id),))
        if cur.fetchone():
            return {'known': True, 'cap': cap}
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
