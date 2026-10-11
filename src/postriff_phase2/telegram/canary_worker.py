"""Server-owned Telegram acceptance scope for the isolated scheduling lane."""
import copy
from uuid import UUID

from postriff_alpha.domain import AlphaError
from .qualification import positive_number


def worker_scope(scope, now):
    """Reject invalid or expired grants before any worker database access."""
    try:
        valid = (isinstance(scope, dict)
                 and all(isinstance(scope.get(key), str) and str(UUID(scope[key])) == scope[key]
                         for key in ('workspaceId', 'actorId'))
                 and type(scope.get('botId')) is int and 0 < scope['botId'] < 2**52
                 and positive_number(scope.get('expiresAt')) and now < scope['expiresAt'] <= now + 86400
                 and isinstance(scope.get('destinations'), list) and 0 < len(scope['destinations']) <= 4)
        chats = [destination['chatId'] for destination in scope['destinations']
                 if isinstance(destination, dict) and destination.get('mode') == 'bot'
                 and type(destination.get('chatId')) is int and 0 < abs(destination['chatId']) < 2**52
                 and isinstance(destination.get('capabilities'), list)
                 and {'publish', 'schedule'} <= set(destination['capabilities'])] if valid else []
    except (ValueError, TypeError, KeyError):
        chats = []
    if not chats:
        raise AlphaError('The Telegram owner scheduling acceptance grant is unavailable.', 503,
                         code='telegram_canary_unavailable')
    result = copy.deepcopy(scope)
    result['chatIds'] = sorted(set(chats))
    return result


def selected(item, scope, connection_ids):
    """Do not invalidate or claim other approvals in the owner's workspace."""
    manifest = item.get('manifest', {})
    return (manifest.get('platform') == 'Telegram' and manifest.get('workspaceId') == scope['workspaceId']
            and manifest.get('actor') == scope['actorId'] and manifest.get('channelId') in connection_ids
            and item.get('approvedBy') == scope['actorId'])
