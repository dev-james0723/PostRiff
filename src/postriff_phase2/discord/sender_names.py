"""Connection-owned webhook names and explicitly shared, per-guild bot nicknames.

No personal-user writes or global bot identity changes. Provider IO is outside workspace transactions; custody is
checked again at the transport boundary.

Server-side switches, read at request time and never cached (exact string "true", like the other Discord flags):

* POSTRIFF_DISCORD_SENDER_NAMES_ENABLED, the master switch for the whole feature. Unset: off on hosted production
  (VERCEL_ENV or POSTRIFF_ENVIRONMENT is "production"), on everywhere else so development and CI exercise it. Any value
  other than "true" is off. Off means: nothing is read from Discord or changed by the routes; a new review freezes no
  custom name (the webhook's own name is used, as in RC1); an already approved post that carries a frozen custom name is
  HELD at dispatch with nothing sent (never sent under a different name); posts without a custom name and every receipt
  reconciliation are unaffected.
* POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED, the bot-nickname capability (one value per Discord server, shared by every post
  of the one Rafii bot). Unset or any value other than "true": off everywhere. It additionally needs the master switch.
  Off means the nickname routes answer without any Discord request, no review freezes a nickname and no nickname write
  can pass the transport guard.

A bot nickname belongs to the shared bot member of ONE Discord server. Rafii writes it from at most one workspace: when
any other workspace has a live bot installation of the same server, neither may change it (nickname_contenders).
"""
import copy
import hashlib
import math
import os
import re
import unicodedata
import uuid

from postriff_alpha.domain import AlphaError
from .authorization import digest, snowflake

ENV_SENDER_NAMES = 'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED'
ENV_BOT_NICKNAME = 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED'
LIMITS = {'webhook': 80, 'bot': 32}
MANAGE_NICKNAMES, CHANGE_NICKNAME = 1 << 27, 1 << 26
PENDING_SECONDS = 120
CLAIM_GRACE_SECONDS = 900
CONTRACT_VERSION = 2
# Evaluation order of the reasons an edit is unavailable (docs/sender-name/UI-API-CONTRACT.md).
REASON_ORDER = ('sender_names_disabled', 'bot_nickname_disabled', 'provider_unavailable', 'not_authorizing_member',
                'session_reverification_required', 'person_missing_manage_nicknames', 'person_role_below_bot',
                'bot_missing_change_nickname', 'nickname_authority_other_workspace', 'edit_pending')
PERSON_BOUND = frozenset({'not_authorizing_member', 'person_missing_manage_nicknames', 'person_role_below_bot'})
_WORKSPACE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
_CONNECTION = re.compile(r'^[A-Za-z0-9_.:-]{8,80}$')
ALLOWED_BODY = frozenset({'name', 'fingerprint', 'confirmed', 'sharedServerConfirmed', 'reset'})


def _values(values):
    return os.environ if values is None else values


def names_enabled(values=None):
    """The master switch. Unset is off on hosted production and on elsewhere; only the exact string "true" turns it on."""
    values = _values(values)
    raw = values.get(ENV_SENDER_NAMES)
    if raw is None:
        from .launch_gate import hosted_production
        return not hosted_production(values)
    return raw == 'true'


def nickname_enabled(values=None):
    """Bot nicknames: off unless the exact string "true", on every environment."""
    return _values(values).get(ENV_BOT_NICKNAME) == 'true'


def provider_ready(provider, *, webhook=False):
    """The gate the sibling routes (engagement) have: the shared request coordinator must be able to admit the request."""
    limiter = getattr(provider, 'rate_limiter', None)
    return bool(provider is not None
                and getattr(provider, 'authorization_v2_enabled', False) and getattr(provider, 'connections_v2_enabled', False)
                and getattr(provider, 'rate_v1_enabled', False) and getattr(provider, 'production_reviewed', False)
                and getattr(provider, 'execution_enabled', True) and limiter is not None
                and getattr(limiter, 'policy', None) is not None
                and not getattr(provider, 'rate_coordinator_degraded', False)
                and (not webhook or getattr(provider, 'webhook_v1_enabled', False)))


def names_available(provider, kind, values=None):
    """What the provider view tells the UI: may this kind of sender name be edited at all, right now."""
    return bool(names_enabled(values) and (kind != 'bot' or nickname_enabled(values))
                and provider_ready(provider, webhook=kind == 'webhook'))


def fail(message='Discord sender settings changed. Reload and review the name again.', status=409, *,
         code='discord_sender_name_required', **fields):
    error = AlphaError(message, status, code=code)
    if fields:
        error.public_fields = fields
    raise error


def unavailable(reasons):
    """One stable refusal for every reason an edit cannot proceed. Person-bound reasons are 403, a provider that is not
    ready is 503, every other state-bound reason is 409."""
    reasons = sorted(reasons, key=lambda r: REASON_ORDER.index(r['code']))
    first = reasons[0]['code']
    status = 403 if first in PERSON_BOUND else 503 if first == 'provider_unavailable' else 409
    fail('This Discord sender name cannot be changed right now.', status, code='discord_sender_name_unavailable',
         reasons=reasons)


def assert_sendable(manifest, values=None):
    """Dispatch gate: a frozen custom webhook name is only ever sent while the feature is on. Otherwise HOLD. The post
    is never stripped of its name or sent under another one, because its approval covers exactly that wire content."""
    if manifest.get('senderKind') == 'webhook' and 'discordSenderName' in manifest and not names_enabled(values):
        fail('Discord custom sender names are switched off; nothing was posted.', 409,
             code='discord_sender_names_disabled')


def frozen_bot_nickname(channel, values=None):
    """(nickname or None,) a review freezes NOW for a bot installation, or None when nothing is frozen: the capability is
    off, or this connection has not yet observed the server nickname. The value is what Discord last reported for the
    bot member (reverify, or this connection's own verified write), so it is what the person saw."""
    if channel.get('discordConnectionKind') != 'installation' or not (names_enabled(values) and nickname_enabled(values)):
        return None
    seen = channel.get('discordBotNickname')
    if not isinstance(seen, dict) or 'value' not in seen or not (seen['value'] is None or isinstance(seen['value'], str)):
        return None
    return (seen['value'],)


def assert_nickname_unchanged(manifest, evidence):
    """Dispatch gate for a bot post approved under a frozen nickname: Discord must still report that nickname."""
    if 'botNickname' not in evidence or evidence['botNickname'] != manifest.get('discordBotNickname'):
        fail('The Rafii bot\U00002019s server nickname is no longer the one this post was approved under. Nothing was posted.',
             409, code='discord_bot_nickname_changed')


# --------------------------------------------------------------------------------------------------------------------
# Name rules. One rule set for both kinds; the server is authoritative and reports a stable `reason`.

# Letters of other scripts that render like Latin ones: a compact subset of the Unicode confusables data, applied only
# to the reserved-word comparison. Full-width and compatibility forms are folded by NFKD.
_HOMOGLYPHS = str.maketrans({
    '\U00000430': 'a', '\U00000435': 'e', '\U0000043e': 'o', '\U00000440': 'p', '\U00000441': 'c', '\U00000445': 'x', '\U00000443': 'y',
    '\U00000456': 'i', '\U00000458': 'j', '\U00000455': 's', '\U00000501': 'd', '\U000004cf': 'l', '\U00000261': 'g', '\U0000043a': 'k',
    '\U00000442': 't', '\U0000043d': 'h', '\U0000043c': 'm', '\U00000432': 'b', '\U00000433': 'r', '\U00000131': 'i', '\U00000142': 'l',
    '\U000000f8': 'o', '\U00000111': 'd', '\U000003bf': 'o', '\U000003bd': 'v', '\U000003b9': 'i', '\U000003c1': 'p', '\U000003ba': 'k',
    '\U000003c4': 't', '\U000003b1': 'a', '\U000003b5': 'e',
})
# Characters that render as nothing (or as blank space) although they are letters or symbols.
_BLANKS = frozenset('\U0000115f\U00001160\U00003164\U0000ffa0\U00002800\U000017b4\U000017b5\U0000034f\U0000180e')
ZWNJ, ZWJ = '\U0000200c', '\U0000200d'
_VARIATION = frozenset('\U0000fe0e\U0000fe0f')
_RESERVED_PARTS = ('discord', 'clyde', 'rafii', 'postriff')   # Discord's own webhook rule, plus the product's names
_RESERVED_WHOLE = ('everyone', 'here')                         # Discord's reserved whole names
_FORBIDDEN = ('@', '#', ':', '```', '<', '>')                  # Discord's username substrings, plus mention/emoji syntax
_LEET = ({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't'}, {'0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's', '7': 't'})


def _skeletons(name):
    folded = unicodedata.normalize('NFKD', name)
    folded = ''.join(c for c in folded if not unicodedata.category(c).startswith('M')).casefold().translate(_HOMOGLYPHS)
    plain = re.sub(r'[^a-z0-9]', '', folded)
    return {plain.translate(str.maketrans(table)) for table in _LEET}


def _joiner_allowed(name, index):
    """The two zero-width joiners real text needs, and nothing else invisible: a ZWJ only inside an emoji sequence (a
    symbol, optionally with its variation selector or skin tone, on both sides) and a ZWNJ only between letters of a
    script that needs it (Persian, Indic and so on), never between Latin letters, where it could only hide a word."""
    before_index = index - 1
    while before_index >= 0 and name[before_index] in _VARIATION:
        before_index -= 1
    before = name[before_index] if before_index >= 0 else ''
    after = name[index + 1] if index + 1 < len(name) else ''
    if not before or not after:
        return False
    if name[index] == ZWJ:
        return unicodedata.category(before) in ('So', 'Sk') and unicodedata.category(after) in ('So', 'Sk')
    return (name[index] == ZWNJ and ord(before) > 0x24f and ord(after) > 0x24f
            and unicodedata.category(before)[0] in 'LM' and unicodedata.category(after)[0] in 'LM')


def name_problem(name, kind):
    """The first rule `name` breaks as a stable reason code, or None."""
    limit = LIMITS[kind]
    if not isinstance(name, str):
        return 'not_text'
    if not name.strip():
        return 'empty'
    if name != name.strip():
        return 'surrounding_space'
    if unicodedata.normalize('NFC', name) != name:
        return 'not_normalized'
    # Code points, and UTF-16 units (an astral character is two), counted without encoding: a lone surrogate, which a
    # JSON body can carry, cannot be encoded and must reach the category scan below as an ordinary invalid character.
    if len(name) > limit or len(name) + sum(1 for ch in name if ord(ch) > 0xFFFF) > limit:
        return 'too_long'
    categories = [unicodedata.category(c) for c in name]
    for index, (category, ch) in enumerate(zip(categories, name)):
        if (category.startswith('C') or ch in '\U00002028\U00002029') and not (ch in (ZWJ, ZWNJ) and _joiner_allowed(name, index)):
            return 'control_or_format'
    if '  ' in name or any(c.startswith('Z') and ch != ' ' for c, ch in zip(categories, name)):
        return 'spacing'
    if any(ch in _BLANKS for ch in name) or not any(c[0] in 'LNSP' for c in categories):
        return 'invisible'
    if any(part in name for part in _FORBIDDEN):
        return 'forbidden_character'
    if '://' in name or re.search(r'(?i)(^|[^a-z0-9])www\.', name):
        return 'url_like'
    skeletons = _skeletons(name)
    if any(part in skeleton for skeleton in skeletons for part in _RESERVED_PARTS) or skeletons & set(_RESERVED_WHOLE):
        return 'reserved_word'
    return None


def validate_name(name, kind):
    problem = name_problem(name, kind)
    if problem:
        fail(f'Choose a name of 1\U00002013{LIMITS[kind]} characters without surrounding spaces, control characters, '
             'reserved words or mention syntax.', 400, code='discord_sender_name_invalid',
             reason=problem, maxLength=LIMITS[kind])
    return name


def names_equivalent(left, right):
    """The read-back comparison of a created message's author name with the frozen one: equal after Unicode NFC and
    whitespace canonicalisation (which Discord is documented to apply to names), and not otherwise."""
    def canon(value):
        return unicodedata.normalize('NFC', ' '.join(value.split())) if isinstance(value, str) else None
    return canon(left) is not None and canon(left) == canon(right)


def frozen_webhook_name(channel, values=None):
    """The custom name a review freezes NOW for a webhook connection, or None (unset, or the feature is off)."""
    if channel.get('discordConnectionKind') != 'webhook' or 'discordSenderName' not in channel or not names_enabled(values):
        return None
    return validate_name(channel['discordSenderName'], 'webhook')


def fingerprint_of(stamp, name):
    """64 hex: the first half binds the Rafii-side state (cheap to recheck before any Discord read), the second the name
    the person saw (for a bot nickname, what Discord reported)."""
    return digest(['rafii-state', stamp])[:32] + digest(['shown-name', name])[:32]


def _rules(kind):
    return {'minLength': 1, 'maxLength': LIMITS[kind], 'lengthUnit': 'codepoints', 'surroundingSpace': False,
            'forbiddenCharacters': list(_FORBIDDEN), 'reservedWords': True, 'singleSpacesOnly': True}


def _above(guild, person_roles, bot_roles, user):
    """Discord's role hierarchy: the owner, or a highest role strictly above the bot's highest role."""
    if str(guild.get('owner_id')) == str(user):
        return True
    position = {str(r.get('id')): r.get('position') for r in guild.get('roles', []) if isinstance(r, dict)}

    def top(roles):
        values = [position.get(str(role)) for role in roles]
        return None if any(type(v) is not int for v in values) else max([0] + values)
    person, bot = top(person_roles), top(bot_roles)
    return person is not None and bot is not None and person > bot


class SenderNames:
    denied = None

    def __init__(self, connections, workspace, token, connection):
        if token is None:
            fail('Sign in to manage Discord sender names.', 401, code='unauthenticated')
        if not isinstance(workspace, str) or not _WORKSPACE.match(workspace):
            # Same body as a foreign or non-existent workspace (hosted.PostgresWorkspaceRepository.transaction).
            fail('Workspace unavailable.', 403, code='permission_denied')
        self.s, self.workspace, self.token, self.connection = connections, workspace, token, connection

    # ----------------------------------------------------------------------------------------------------------------
    # Throttles (pr_auth_throttle, no schema change): bound the provider reads a settings page can cause.
    def _limit(self, cur, kind, scope, limit):
        from ..hosted import throttle
        try:
            throttle(cur, f'discord-sender-name:{kind}:{scope}', limit, 600)
        except AlphaError:
            fail('Too many sender-name requests. Wait a few minutes and try again.', 429, code='rate_limited',
                 retryAfterSeconds=60)

    # ----------------------------------------------------------------------------------------------------------------
    def authorizing(self, state, channel, envelope, actor):
        """A webhook name is a Rafii setting: any member who may manage connections edits it (the workspace role gate
        has already run). A bot nickname changes a shared Discord object, so only the member whose Discord identity
        installed the bot may."""
        if envelope.get('kind') == 'webhook':
            return True
        record = next((x for x in state.get('phase2', {}).get('discordIdentityLinks', [])
                       if x.get('id') == envelope.get('identityConnectionId')
                       and x.get('workspaceId') == state['workspace']['id']), None)
        return bool(record) and record.get('authorizedBy') == actor

    def custody(self, cur, state, actor, *, fresh=True, require_authorizer=True, live=True):
        """(channel, envelope, stamp). Every integrity failure is a reconnect; only the authorizer may write a nickname.
        `live=False` skips the webhook validator that needs the webhook route to be enabled: used only for the first look,
        when the answer is going to be "unavailable" without any provider request."""
        if (not actor or state.get('workspace', {}).get('id') != self.workspace
                or state.get('accountDeletion') or state.get('accountBlock')):
            fail('This workspace cannot change Discord sender settings.', 403, code='permission_denied')
        channel = (next((c for c in state.get('phase2', {}).get('channels', [])
                         if c.get('id') == self.connection and c.get('platform') == 'Discord'), None)
                   if isinstance(self.connection, str) and _CONNECTION.match(self.connection) else None)
        if not channel or channel.get('revoked'):
            fail('This Discord connection is unavailable.', 404, code='not_found')
        row, envelope = self.s.read_credential(cur, self.workspace, self.connection)
        kind = envelope.get('kind')
        required = {'identify', 'webhook.incoming' if kind == 'webhook' else 'bot'}
        if (kind not in ('webhook', 'installation') or channel.get('discordConnectionKind') != kind
                or envelope.get('applicationId') != self.s.adapter.client_id
                or not row[4] or row[4] != channel.get('discordAuthorizationGeneration')
                or not required.issubset(row[5] or []) or set(row[5]) != set(channel.get('scopes') or [])
                or any(not snowflake(envelope.get(k)) for k in ('guild', 'user'))):
            fail('Reconnect this Discord connection before changing its sender name.', 409,
                 code='discord_connection_required')
        authorizing = self.authorizing(state, channel, envelope, actor)
        if require_authorizer and not authorizing:
            unavailable([{'code': 'not_authorizing_member'}])
        identity = None
        if kind == 'webhook':
            if (envelope.get('workspaceId') != self.workspace or envelope.get('connectionId') != self.connection
                    or channel.get('discordLinkedUserId') != envelope['user']
                    or envelope.get('webhookId') != row[6] or row[6] != channel.get('providerAccountId')
                    or envelope.get('channel') != channel.get('discordWebhookChannelId')):
                fail('Reconnect this Discord connection before changing its sender name.', 409,
                     code='discord_connection_required')
            if live:
                self.s.validate_webhook(cur, self.workspace, envelope)
        else:
            identity = next((x for x in state.get('phase2', {}).get('discordIdentityLinks', [])
                             if x.get('id') == envelope.get('identityConnectionId')
                             and x.get('workspaceId') == state['workspace']['id']), None)
            if (not identity or envelope['guild'] != row[6] or row[6] != channel.get('providerAccountId')
                    or channel.get('discordIdentityConnectionId') != identity['id']
                    or identity.get('authorizationGeneration') != envelope.get('identityGeneration')
                    or identity.get('userId') != envelope['user'] or identity.get('status') != 'linked'
                    or not snowflake(envelope.get('botUserId'))):
                fail('The Discord installation\U00002019s authorizing identity changed.', 409, code='discord_connection_required')
            if fresh and authorizing:
                self.s.validate_installation(cur, self.workspace, envelope)
        fields = ('id', 'platform', 'providerAccountId', 'discordConnectionKind', 'scopes', 'revoked',
                  'discordIdentityConnectionId', 'discordAuthorizationGeneration', 'discordAuthorizedBy',
                  'discordLinkedUserId', 'discordWebhookChannelId', 'defaultDestinationId', 'discordDestinations',
                  'discordSenderName', 'discordSenderRevision', 'discordSenderEdit', 'discordBotNickname',
                  'enabledPermissionGroups')
        # The webhook's own token is custody, not a fingerprint input: a client-visible hash must not depend on it.
        public_envelope = {k: v for k, v in envelope.items() if k != 'secret'}
        stamp = digest({'workspace': self.workspace, 'actor': actor,
                        'channel': {k: channel.get(k) for k in fields},
                        'credential': [row[0], row[4], public_envelope],
                        'identity': {k: identity.get(k) for k in ('id', 'authorizedBy', 'userId', 'status', 'authorizationGeneration')} if identity else None})
        custody_view = copy.deepcopy(envelope)
        custody_view['_authorizing'] = authorizing
        return channel, custody_view, stamp

    def _stale_session(self, actor):
        try:
            self.s.oauth.repository.assert_fresh(self.token, actor)
        except AlphaError:
            return True
        return False

    @staticmethod
    def _finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def _pending_seconds(self, claim):
        expires = claim.get('expiresAt') if isinstance(claim, dict) else None
        if not self._finite(expires):
            return PENDING_SECONDS
        return max(0, math.ceil(expires - self.s.oauth.clock()))

    @staticmethod
    def policy_reasons(kind, authorizing, names_on, nickname_on, ready=True):
        """Reasons known without asking Discord: the switches, whether the shared request coordinator can admit a request,
        and who the authorizing member is."""
        reasons = []
        if not names_on:
            reasons.append({'code': 'sender_names_disabled'})
        elif kind == 'bot' and not nickname_on:
            reasons.append({'code': 'bot_nickname_disabled'})
        elif not ready:
            reasons.append({'code': 'provider_unavailable'})
        if not authorizing:
            reasons.append({'code': 'not_authorizing_member'})
        return reasons

    def _provider_reads(self, perform):
        from .rate_limits import RateDelayed
        try:
            return perform()
        except RateDelayed as delayed:
            fail('Discord is waiting for shared request capacity. Try again shortly; nothing was changed.', 429,
                 code='discord_rate_delayed', retryAfterSeconds=max(1, math.ceil(delayed.retry_after_seconds)))

    def observe(self, *, reconcile=False, writing=False, precheck=None):
        """One custody transaction, the Discord reads (no workspace transaction open, none per read), one final
        transaction. A read persists nothing except the throttle counters and the reconciliation of an expired claim."""
        names_on, nickname_on = names_enabled(), nickname_enabled()
        provider = self.s.oauth._provider('discord')
        mode = 'post' if writing else 'get'
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, first, first_stamp = self.custody(cur, state, actor, fresh=False, require_authorizer=False,
                                                       live=bool(getattr(provider, 'webhook_v1_enabled', False)))
            self._limit(cur, mode, self.workspace, 15 if writing else 40)
            self._limit(cur, mode, f'{self.workspace}:{self.connection}', 6 if writing else 12)
            if writing:
                self.s.oauth.repository.assert_fresh(self.token, actor)   # a fresh sign-in, before anything else
            claim = copy.deepcopy(channel.get('discordSenderEdit'))
            saved = channel.get('discordSenderName')
            stale = not writing and self._stale_session(actor)
        kind = 'webhook' if first['kind'] == 'webhook' else 'bot'
        reasons = self.policy_reasons(kind, first['_authorizing'], names_on, nickname_on, provider_ready(provider, webhook=kind == 'webhook'))
        if reasons:
            # Answered without Discord: nothing here needs a provider read, and none is made on behalf of a refusal.
            if writing:
                unavailable(reasons)
            if claim:
                reasons.append({'code': 'edit_pending', 'retryAfterSeconds': self._pending_seconds(claim)})
            if stale:
                reasons.append({'code': 'session_reverification_required'})
            return self._profile(kind, first, first_stamp, saved, None, None, reasons, names_on, nickname_on), first, first_stamp
        if precheck is not None:
            precheck(kind, first, first_stamp)
        if claim and (not reconcile or not isinstance(claim, dict)
                      or not self._finite(claim.get('expiresAt'))
                      or self.s.oauth.clock() < claim['expiresAt']):
            fail('A sender-name change is pending. Wait two minutes, then reload to verify it.', 409,
                 code='discord_sender_edit_pending', retryAfterSeconds=self._pending_seconds(claim))
        envelope, stamp = first, first_stamp
        if writing and kind == 'bot':
            # Refresh a linked identity that has merely aged out (outside any SQL lock), then re-prove custody. A
            # settings page never marks a connection unverified: only the explicit verify actions do that.
            self.s._fresh_identity(self.workspace, None, first['identityConnectionId'])
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, envelope, stamp = self.custody(cur, state, actor, fresh=True)
                if channel.get('discordSenderEdit') != claim:
                    fail()
        adapter = self.s.adapter
        observed_at = self.s.oauth.clock()
        member_nick = None
        if kind == 'webhook':
            from .webhooks import verify_resource
            resource = self._provider_reads(lambda: verify_resource(adapter, envelope))
            observed = resource.get('senderName')
        else:
            def read_server():
                bot = adapter._bot_identity()
                if bot != envelope['botUserId']:
                    fail('Discord returned a different bot.', 409, code='discord_connection_required')
                guild = adapter._json(adapter._bot('GET', '/guilds/' + envelope['guild']), dict)
                if guild.get('id') != envelope['guild']:
                    fail('Discord returned a different server.', 409, code='discord_connection_required')
                roles = adapter._member_roles(envelope['guild'], envelope['user'])
                member = {}
                bot_roles = adapter._member_roles(envelope['guild'], bot, member_out=member)   # roles AND nickname: one request
                if bot_roles is None:
                    fail('The bot is not an active member of this server. Reconnect the installation.', 409,
                         code='discord_connection_required')
                return bot, guild, roles, bot_roles, member
            bot, guild, roles, bot_roles, member = self._provider_reads(read_server)
            if roles is None or not adapter._permissions(guild, roles, envelope['user']) & MANAGE_NICKNAMES:
                reasons.append({'code': 'person_missing_manage_nicknames'})
            elif not _above(guild, roles, bot_roles, envelope['user']):
                reasons.append({'code': 'person_role_below_bot'})
            if not adapter._permissions(guild, bot_roles, bot) & CHANGE_NICKNAME:
                reasons.append({'code': 'bot_missing_change_nickname'})
            observed = member.get('nick') or (member.get('user') or {}).get('global_name') or (member.get('user') or {}).get('username')
            member_nick = member.get('nick') if isinstance(member.get('nick'), str) else None
        if not isinstance(observed, str) or not observed or len(observed) > 80:
            fail('Discord did not return a valid current sender name.', 502, code='upstream_error')
        # The final transaction: re-prove custody (the reads above ran without one), reconcile an expired claim, then
        # (bot) consult the other workspaces' installations under the guild lock.
        from ..hosted import audit
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, _, current = self.custody(cur, state, actor, fresh=writing)
            if current != stamp or channel.get('discordSenderEdit') != claim:
                fail()
            if claim:
                # Explicit GET after the bounded write deadline observes Discord before retiring an interrupted or
                # uncertain local claim. A POST cannot silently clear it or replay the old provider write.
                if self.s.oauth.clock() < claim['expiresAt']:
                    fail()
                abandoned = self._resolve_admission(cur, envelope, claim)
                channel.pop('discordSenderEdit', None)
                channel.update(discordSenderName=observed, discordSenderRevision=str(uuid.uuid4()),
                               discordBotNickname={'value': member_nick, 'observedAt': observed_at})
                saved = observed
                self.s.save_state(cur, self.workspace, state)
                audit(cur, self.workspace, actor, 'discord.sender_name_claim_abandoned' if abandoned else 'discord.sender_name_reconciled',
                      self.connection, {'scope': 'server', 'guildId': envelope['guild']})
                _, _, stamp = self.custody(cur, state, actor, fresh=writing)
            if kind == 'bot' and self.s.nickname_contenders(cur, self.workspace, self.connection, envelope['guild']):
                reasons.append({'code': 'nickname_authority_other_workspace'})
        if stale and not writing:
            reasons.append({'code': 'session_reverification_required'})
        profile = self._profile(kind, envelope, stamp, saved, observed, observed_at, reasons, names_on, nickname_on,
                                member_nick=member_nick)
        if writing and reasons:
            unavailable(reasons)
        return profile, envelope, stamp

    def _resolve_admission(self, cur, envelope, claim):
        """Retire the claim's rate admission after a fresh read of the member. True when the claim had to be abandoned
        without resolving its admission (the coordinator could not match it, for instance after the bot token was
        rotated, for longer than the grace period): the orphan is then left to the coordinator's own age bound."""
        if not claim.get('rateAdmissionId'):
            return False
        from .rate_limits import Permit, RateCoordinatorUnavailable, _digest
        adapter = self.s.adapter
        limiter = adapter.rate_limiter
        if not adapter.rate_v1_enabled or limiter is None:
            fail('Discord request coordination must be restored before this name change can be reconciled.', 409,
                 code='discord_sender_edit_pending', retryAfterSeconds=60)
        try:
            by_id = getattr(limiter, 'reconcile_nickname_by_id', None)   # independent of the bot token, when offered
            if callable(by_id):
                by_id(cur, claim['rateAdmissionId'], envelope['guild'])
            else:
                limiter.reconcile_nickname(cur, Permit(claim['rateAdmissionId'], limiter.application_key, 'PATCH',
                                                       _digest(f'/guilds/{envelope["guild"]}/members/@me'),
                                                       adapter._rate_identity('bot'), None, claim['rateExpiresAt']),
                                           envelope['guild'])
            return False
        except RateCoordinatorUnavailable:
            if self.s.oauth.clock() < claim['expiresAt'] + CLAIM_GRACE_SECONDS:
                # The coordinator cannot settle the admission yet (for instance after the bot credential changed). The
                # person sees the same pending answer as before the deadline, not the coordinator's own error.
                fail('A sender-name change is still being settled. Try again in a few minutes.', 409,
                     code='discord_sender_edit_pending', retryAfterSeconds=60)
            return True

    def _profile(self, kind, envelope, stamp, saved, observed, observed_at, reasons, names_on, nickname_on, *, member_nick=None):
        reasons = sorted(reasons, key=lambda r: REASON_ORDER.index(r['code']))
        if kind == 'webhook':
            if names_on and saved is not None:
                effective, source = saved, 'saved_override'
            elif observed is not None:
                effective, source = observed, 'webhook_default'
            else:
                effective, source = None, 'none'
            external = False
        else:
            effective = observed
            source = 'none' if observed is None else 'observed_nickname' if member_nick else 'bot_username'
            external = observed is not None and saved is not None and observed != saved
        shown = effective if effective is not None else (saved or '')
        # A webhook's name part is the saved setting (Rafii-side, no Discord read needed); a bot nickname's is the
        # nickname Discord reported, so a native rename makes an older form stale.
        name_part = (saved or '') if kind == 'webhook' else (observed if observed is not None else (saved or ''))
        return {'contractVersion': CONTRACT_VERSION, 'connectionId': self.connection, 'senderKind': kind,
                'scope': 'connection' if kind == 'webhook' else 'server', 'guildId': envelope['guild'],
                'state': 'verified', 'maxLength': LIMITS[kind], 'rules': _rules(kind),
                'name': shown, 'effectiveName': effective, 'nameSource': source,
                'savedName': saved,
                'observedName': observed, 'observedAt': observed_at, 'externalChange': external,
                'fingerprint': fingerprint_of(stamp, name_part),
                'feature': {'senderNames': names_on, 'botNickname': nickname_on},
                'editable': not reasons, 'unavailable': reasons,
                'preview': {'currentDisplayName': effective, 'badge': 'APP',
                            'audience': 'this_connection' if kind == 'webhook' else 'everyone_in_server',
                            'queuedPostsKeepApprovedName': kind == 'webhook',
                            'queuedBotPostsHoldIfNicknameChanges': kind == 'bot'}}

    def get(self):
        return self.observe(reconcile=True)[0]

    def write_guard(self, stamp, claim_id):
        """The last check before the provider write. A refusal here is known unsent: transport has not been reached."""
        try:
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, envelope, current = self.custody(cur, state, actor)
                claim = channel.get('discordSenderEdit') or {}
                if current != stamp or claim.get('id') != claim_id or self.s.oauth.clock() >= claim.get('expiresAt', 0):
                    fail()
                # The switches, and that no other Rafii workspace can have appeared as a second writer of this
                # server's shared nickname since the preflight (taken under the guild lock).
                if not names_enabled():
                    unavailable([{'code': 'sender_names_disabled'}])
                if not nickname_enabled():
                    unavailable([{'code': 'bot_nickname_disabled'}])
                if self.s.nickname_contenders(cur, self.workspace, self.connection, envelope['guild']):
                    unavailable([{'code': 'nickname_authority_other_workspace'}])
        except AlphaError as refused:
            self.denied = refused
            raise
        return True

    def release_claim(self, claim_id):
        """Retire a claim whose write is known unsent (the guard refused, or Discord definitely refused it)."""
        try:
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, _, _ = self.custody(cur, state, actor, fresh=False)
                if (channel.get('discordSenderEdit') or {}).get('id') == claim_id:
                    channel.pop('discordSenderEdit', None)
                    self.s.save_state(cur, self.workspace, state)
        except Exception:
            pass   # the claim then simply runs to its deadline and a later read reconciles it

    def _refuse_failed_write(self, caught, claim_id, progress):
        """Translate an exception from the nickname PATCH call. Always raises.

        Proven unsent (the final guard refused; or the coordinator refused before the guard's second pass and either no
        admission had been recorded or the exception is RateDelayed, which `consume` raises only before it commits the
        `sent` state): the claim is released at once and the refusal says nothing was sent. Anything else may have reached
        Discord (transport failure, an observation failure): the claim stays until a later read settles it."""
        from .rate_limits import RateCoordinatorUnavailable, RateDelayed
        if caught is self.denied:
            self.release_claim(claim_id)
            raise caught
        unsent = progress['passes'] < 2 and (progress['admitted'] is None or isinstance(caught, RateDelayed))
        if not unsent:
            fail('Discord did not confirm the nickname change. Wait two minutes, then reload its current value.', 409,
                 code='discord_sender_edit_pending', retryAfterSeconds=PENDING_SECONDS)
        self.release_claim(claim_id)
        if isinstance(caught, RateDelayed):
            fail('Discord is waiting for shared request capacity. Try again shortly; nothing was changed.', 429,
                 code='discord_rate_delayed', retryAfterSeconds=max(1, math.ceil(caught.retry_after_seconds)))
        if isinstance(caught, AlphaError) and not isinstance(caught, RateCoordinatorUnavailable):
            raise caught    # for instance custody changing while the admission was recorded: its own, honest refusal
        unavailable([{'code': 'provider_unavailable'}])

    def audit_reason(self, guild):
        """X-Audit-Log-Reason for the nickname PATCH: Discord shows it in the server's audit log, so a server admin can
        see that Rafii (not a person) changed the nickname and which opaque reference to quote to Rafii. A one-way
        digest of workspace and server: it names no workspace, member or customer text."""
        reference = hashlib.sha256(f'rafii-nickname:{self.s.adapter.client_id}:{guild}:{self.workspace}'.encode()).hexdigest()[:16]
        return f'Rafii shared bot nickname change (ref {reference})'

    def set(self, body):
        if (not isinstance(body, dict) or set(body) - ALLOWED_BODY or body.get('confirmed') is not True
                or not isinstance(body.get('fingerprint'), str) or ('reset' in body and body['reset'] is not True)
                or ('reset' in body and 'name' in body)):
            fail('Review and confirm the sender name before saving.', 400, code='discord_sender_name_unconfirmed')
        reset = body.get('reset') is True

        def precheck(kind, first, first_stamp):
            if not body['fingerprint'].startswith(digest(['rafii-state', first_stamp])[:32]):
                fail()      # stale Rafii-side state: refused before any Discord read
            if reset:
                if kind == 'bot':
                    fail('A bot nickname cannot be cleared from Rafii; choose the nickname you want.', 400,
                         code='discord_sender_reset_unsupported')
                return
            validate_name(body.get('name'), kind)
            if kind == 'bot' and body.get('sharedServerConfirmed') is not True:
                fail('Confirm that this bot nickname is shared by everyone in this server.', 400,
                     code='discord_sender_name_shared_unconfirmed')
        profile, envelope, stamp = self.observe(writing=True, precheck=precheck)
        kind = profile['senderKind']
        if body['fingerprint'] != profile['fingerprint']:
            fail()
        name = None if reset else body['name']
        from ..hosted import audit
        if kind == 'bot':
            claim_id = str(uuid.uuid4())
            with self.s.local(self.workspace, self.token) as (cur, state, actor):
                channel, _, current = self.custody(cur, state, actor)
                if current != stamp or channel.get('discordSenderEdit'):
                    fail()
                channel['discordSenderEdit'] = {'id': claim_id, 'name': name,
                                               'expiresAt': self.s.oauth.clock() + PENDING_SECONDS}
                self.s.save_state(cur, self.workspace, state)
                _, _, stamp = self.custody(cur, state, actor)

            # How far the write got: the transport call comes right after the SECOND time the guard passes, so fewer than
            # two passes means nothing can have been sent. `admitted` is the coordinator admission recorded in the claim.
            progress = {'passes': 0, 'admitted': None}

            def admitted(permit):
                nonlocal stamp
                with self.s.local(self.workspace, self.token) as (cur, state, actor):
                    channel, _, current = self.custody(cur, state, actor)
                    if current != stamp or (channel.get('discordSenderEdit') or {}).get('id') != claim_id:
                        fail()
                    channel['discordSenderEdit'].update(rateAdmissionId=permit.id, rateExpiresAt=permit.expires_at)
                    self.s.save_state(cur, self.workspace, state)
                    _, _, stamp = self.custody(cur, state, actor)
                progress['admitted'] = permit.id

            def guard():
                allowed = self.write_guard(stamp, claim_id)
                progress['passes'] += 1
                return allowed
            self.denied = None
            try:
                response = self.s.adapter._bot('PATCH', f'/guilds/{envelope["guild"]}/members/@me', body={'nick': name},
                    headers={'X-Audit-Log-Reason': self.audit_reason(envelope['guild'])},
                    write_authorize=guard, write_admitted=admitted)
            except Exception as caught:
                self._refuse_failed_write(caught, claim_id, progress)
            member, status = response.get('body'), response.get('status')
            if isinstance(status, int) and 400 <= status < 500:
                # Discord answered and refused (permission, hierarchy, rate limit): the nickname is unchanged, so the
                # claim must not make the next attempt wait. Never retried here: the person decides after fixing it.
                self.release_claim(claim_id)
                fail('Discord refused the nickname change. Check the permissions of the bot and of your role, then try again.',
                     409, code='discord_sender_write_refused')
            if (status != 200 or not isinstance(member, dict)
                    or (member.get('user') or {}).get('id') != envelope['botUserId'] or member.get('nick') != name):
                fail('Discord did not confirm the new nickname. Reload to check its current value before trying again.', 409,
                     code='discord_sender_write_unconfirmed')
            try:
                observed = self.s.adapter._json(self.s.adapter._bot('GET',
                    f'/guilds/{envelope["guild"]}/members/{envelope["botUserId"]}'), dict)
            except Exception:
                # The write was accepted: the claim stays so a later read settles it, and the wording must not say
                # "nothing was sent" (which a rate-delayed read-back would otherwise report).
                fail('Discord accepted the nickname change but it could not be verified yet. Reload to check its current value.',
                     409, code='discord_sender_write_unconfirmed')
            if (observed.get('user') or {}).get('id') != envelope['botUserId'] or observed.get('nick') != name:
                fail('The server nickname changed during verification. Reload before trying again.', 409,
                     code='discord_sender_write_unconfirmed')
        with self.s.local(self.workspace, self.token) as (cur, state, actor):
            channel, _, current = self.custody(cur, state, actor)
            if current != stamp:
                fail()
            if reset:
                channel.pop('discordSenderName', None)
            else:
                channel['discordSenderName'] = name
            channel['discordSenderRevision'] = str(uuid.uuid4())
            channel.pop('discordSenderEdit', None)
            if kind == 'bot':
                channel['discordBotNickname'] = {'value': name, 'observedAt': self.s.oauth.clock()}
            self.s.save_state(cur, self.workspace, state)
            audit(cur, self.workspace, actor, 'discord.sender_name_reset' if reset else 'discord.sender_name_updated', self.connection,
                  {'senderKind': kind, 'scope': profile['scope'], 'guildId': envelope['guild']})
            _, _, saved_stamp = self.custody(cur, state, actor)
        saved = self._profile(kind, envelope, saved_stamp, name, name if kind == 'bot' else profile['observedName'],
                              self.s.oauth.clock(), [], names_enabled(), nickname_enabled(),
                              member_nick=name if kind == 'bot' else None)
        return {**saved, 'saved': True, **({'reset': True} if reset else {})}
