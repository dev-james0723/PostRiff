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
            'selected': session.get('destinationAuthorized') is True}


def verify(provider, session, *, read_authorize=None):
    """A webhook token is not proof of the author's current channel permission.

    Sending remains webhook-authenticated. Rafii's already installed app supplies
    read-only membership/role/channel evidence; absent evidence holds publishing.
    Identity connection and webhook custody do not require this extra read access.
    """
    resource = verify_resource(provider, session, read_authorize=read_authorize)
    if any(not snowflake(session.get(k)) for k in ('guild', 'channel', 'user')):
        raise AlphaError('Discord webhook permission evidence is unavailable.', 409)
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
            and body.get('mentions') == [] and body.get('mention_roles') == [] and body.get('mention_everyone') is False
            and body.get('attachments') == [] and body.get('embeds') == [])
