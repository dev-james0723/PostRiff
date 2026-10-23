"""Incoming webhook protocol. Same worker admission and vault; no URL input."""
import re
from postriff_alpha.domain import AlphaError
from .authorization import snowflake


def require_enabled(provider):
    if (not getattr(provider, 'webhook_v1_enabled', False) or not getattr(provider, 'execution_enabled', True)
            or not getattr(provider, 'authorization_v2_enabled', False) or not getattr(provider, 'connections_v2_enabled', False)):
        raise AlphaError('Discord webhook publishing is unavailable pending qualification.', 503)


def path(session, *, message=None, execute=False):
    if (session.get('kind') != 'webhook' or not snowflake(session.get('webhookId'))
            or not isinstance(session.get('secret'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,256}', session['secret'])):
        raise AlphaError('Reconnect this authorized Discord webhook.', 409)
    result = '/webhooks/' + session['webhookId'] + '/' + session['secret']
    if message is not None:
        if not snowflake(message): raise AlphaError('Discord receipt unavailable.', 409)
        result += '/messages/' + message
    return result + ('?wait=true' if execute else '')


def request(provider, method, session, *, message=None, body=None, **kwargs):
    require_enabled(provider)
    if session.get('applicationId') != provider.client_id:
        raise AlphaError('Discord webhook application changed.', 409)
    return provider._discord_http(method, path(session, message=message, execute=method == 'POST'),
        credential_kind='webhook', bearer=session['secret'],
        headers={'User-Agent': f'DiscordBot ({provider.website}, 1)'}, **({'body': body} if body is not None else {}), **kwargs)


def verify_resource(provider, session, *, read_authorize=None):
    response = request(provider, 'GET', session, read_authorize=read_authorize)
    body = response.get('body')
    if (response.get('status') != 200 or not isinstance(body, dict) or body.get('type') != 1
            or any(body.get(k) != session.get(v) for k, v in
                   [('id', 'webhookId'), ('application_id', 'applicationId'), ('guild_id', 'guild'), ('channel_id', 'channel')])):
        raise AlphaError('Discord did not verify this exact webhook and channel. Reconnect it.', 409)
    return {'id': session['channel'], 'name': session['channel'], 'kind': 'webhook',
            'senderKind': 'webhook', 'credentialKind': 'webhook', 'webhookId': session['webhookId'],
            'applicationId': session['applicationId'], 'linkedUserId': session['user'], 'guildId': session['guild'],
            'channelId': session['channel'], 'guildName': session['guild'], 'channelName': session['channel'],
            'selected': session.get('destinationAuthorized') is True, 'senderName': body.get('name')}


def owner_permissions(provider, session, *, read_authorize=None):
    """Only current owners/admins bypass channel overwrites without a bot.

    The server-side resolver rechecks the selected identity's encrypted custody,
    generation, expiry and active Rafii membership. No permission proof is cached.
    """
    resolver = getattr(provider, 'webhook_authorizer', None)
    identity = resolver(session) if callable(resolver) else None
    if identity is None:
        return None
    if (not isinstance(identity, dict) or not isinstance(identity.get('scopes'), list)
            or any(not isinstance(s, str) for s in identity['scopes'])
            or identity.get('userId') != session.get('user')
            or not isinstance(identity.get('bearer'), str) or not identity['bearer']):
        raise AlphaError('The webhook authorizer changed. Reconnect it.', 409)
    if 'guilds' not in identity['scopes']:
        return None
    def read(route, expected):
        return provider._json(provider._discord_http('GET', route,
            credential_kind='user', bearer=identity['bearer'], user_id=identity['userId'],
            headers={'Authorization': 'Bearer ' + identity['bearer'],
                     'User-Agent': f'DiscordBot ({provider.website}, 1)'},
            read_authorize=read_authorize), expected)
    info = read('/oauth2/@me', dict)
    if (not isinstance(info.get('application'), dict) or info['application'].get('id') != provider.client_id
            or not isinstance(info.get('user'), dict) or info['user'].get('id') != session['user']
            or not isinstance(info.get('scopes'), list) or any(not isinstance(s, str) for s in info['scopes'])
            or not {'identify', 'guilds'}.issubset(info['scopes'])):
        raise AlphaError('Discord did not confirm the webhook authorizer and server-list consent.', 409)
    guilds = read('/users/@me/guilds?limit=200', list)
    seen, proof = set(), None
    if len(guilds) > 200:
        raise AlphaError('Discord returned an invalid server list.', 409)
    for guild in guilds:
        if not isinstance(guild, dict) or not snowflake(guild.get('id')) or guild['id'] in seen:
            raise AlphaError('Discord returned an invalid server list.', 409)
        seen.add(guild['id'])
        if guild['id'] != session['guild']:
            continue
        permissions = guild.get('permissions')
        if guild.get('owner') is True:
            proof = 'current_owner_oauth'
        elif isinstance(permissions, str) and re.fullmatch(r'[0-9]{1,128}', permissions) and int(permissions) & (1 << 3):
            proof = 'current_admin_oauth'
    return proof


def verify(provider, session, *, read_authorize=None):
    """Webhook custody alone cannot prove current authorizer permissions.

    Owners/admins use their separately linked OAuth identity. Other members need
    the installed app's current channel overwrite evidence; missing proof holds.
    """
    resource = verify_resource(provider, session, read_authorize=read_authorize)
    if any(not snowflake(session.get(k)) for k in ('guild', 'channel', 'user')):
        raise AlphaError('Discord webhook permission evidence is unavailable.', 409)
    proof = owner_permissions(provider, session, read_authorize=read_authorize)
    if proof:
        return {**resource, 'userPermissions': provider.VIEW_CHANNEL | provider.SEND_MESSAGES,
                'permissionProof': proof}
    bot = provider._bot_identity(read_authorize=read_authorize)
    guild = provider._json(provider._bot('GET', '/guilds/' + session['guild'], read_authorize=read_authorize), dict)
    if guild.get('id') != session['guild']:
        raise AlphaError('Discord returned a different server.', 409)
    roles = provider._member_roles(session['guild'], session['user'], read_authorize=read_authorize)
    bot_roles = provider._member_roles(session['guild'], bot, read_authorize=read_authorize)
    if roles is None or bot_roles is None:
        raise AlphaError('Discord server membership was removed or restricted. Nothing was posted.', 409)
    channels = provider._json(provider._bot('GET', '/guilds/' + session['guild'] + '/channels', read_authorize=read_authorize), list)
    matches = [c for c in channels if isinstance(c, dict) and c.get('id') == session['channel']]
    if len(matches) != 1 or type(matches[0].get('type')) is not int or matches[0]['type'] not in (0, 5):
        raise AlphaError('This exact text channel is no longer available.', 409)
    channel = matches[0]
    allowed = provider._permissions(guild, roles, session['user'], channel)
    observer = provider._permissions(guild, bot_roles, bot, channel)
    required = provider.VIEW_CHANNEL | provider.SEND_MESSAGES
    if allowed & required != required or not observer & provider.VIEW_CHANNEL:
        raise AlphaError('The authorizer no longer has channel publishing permission. Nothing was posted.', 409)
    return {**resource, 'userPermissions': allowed, 'permissionProof': 'current_app_read'}


def message_matches(body, manifest, message_id):
    target = manifest['discord']['target']
    return (isinstance(body, dict) and body.get('id') == message_id and body.get('channel_id') == target['channelId']
            and body.get('webhook_id') == target['webhookId'] and (body.get('author') or {}).get('id') == target['webhookId']
            and (body.get('author') or {}).get('bot') is True and body.get('content') == manifest['payload']['text']
            and ('discordSenderName' not in manifest or (body.get('author') or {}).get('username') == manifest['discordSenderName'])
            and body.get('mentions') == [] and body.get('mention_roles') == [] and body.get('mention_everyone') is False
            and body.get('attachments') == [] and body.get('embeds') == [])
