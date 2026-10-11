"""Server-owned Telegram acceptance scope for the isolated scheduling lane."""
import copy
from uuid import UUID

from postriff_alpha.domain import AlphaError
from .qualification import positive_number


def ingress_scope(provider, now):
    """Invalid acceptance configuration never restores ordinary ingestion."""
    if not getattr(provider, 'candidate_mode', False):
        return False, None
    scope = getattr(provider, 'candidate_scope', None)
    try:
        valid = (isinstance(scope, dict)
                 and all(isinstance(scope.get(key), str) and str(UUID(scope[key])) == scope[key]
                         for key in ('workspaceId', 'actorId'))
                 and type(scope.get('botId')) is int and 0 < scope['botId'] < 2**52
                 and positive_number(scope.get('expiresAt')) and now < scope['expiresAt'] <= now + 86400
                 and isinstance(scope.get('destinations'), list) and 0 < len(scope['destinations']) <= 4
                 and all(isinstance(d, dict) and type(d.get('chatId')) is int and 0 < abs(d['chatId']) < 2**52
                         and d.get('mode') in ('bot', 'business')
                         and isinstance(d.get('capabilities'), list) and all(isinstance(c, str) for c in d['capabilities'])
                         and (d['mode'] != 'business' or isinstance(d.get('businessConnectionId'), str) and bool(d['businessConnectionId']))
                         for d in scope['destinations']))
    except (ValueError, TypeError, KeyError):
        valid = False
    return True, copy.deepcopy(scope) if valid else None


def accepts_event(scope, kind, event):
    """Metadata without a chat is subsequently bound to the owner or saved poll."""
    if kind in ('business_connection', 'managed_bot', 'poll', 'poll_answer'):
        return True
    chat = ((event.get('message') or {}).get('chat') or {}) if kind == 'callback_query' else event.get('chat') or {}
    if not isinstance(chat, dict) or type(chat.get('id')) is not int:
        return False
    mode = 'business' if kind in ('business_message', 'edited_business_message', 'deleted_business_messages') else 'bot'
    return any(d['chatId'] == chat.get('id') and d['mode'] == mode
               and (mode != 'business' or d.get('businessConnectionId') == event.get('business_connection_id'))
               for d in scope['destinations'])


def owner_active(cur, scope):
    # Match the ordinary command lock order: workspace, then member/profile.
    cur.execute("""SELECT 1 FROM public.pr_workspaces WHERE id=%s
        AND state->'accountDeletion' IS NULL AND state->'accountBlock' IS NULL FOR SHARE""", (scope['workspaceId'],))
    if not cur.fetchone():
        return False
    cur.execute("""SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
        WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND m.role='owner'
          AND p.deleted_at IS NULL FOR SHARE OF m,p""", (scope['workspaceId'], scope['actorId']))
    return cur.fetchone() is not None


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
