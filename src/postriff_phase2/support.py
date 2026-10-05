"""Original-tenant support with immutable, content-free workflow events."""
import hashlib
import json
import uuid
from postriff_alpha.domain import AlphaError
from .hosted import audit
from .permissions import require

CATEGORIES = ('technical', 'billing', 'account', 'other')
STATUSES = ('open', 'waiting_customer', 'resolved', 'closed', 'spam', 'duplicate')
PRIORITIES = ('low', 'normal', 'high', 'urgent')


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AlphaError('Invalid support request identifier.', 400) from None


def message(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 8000:
        raise AlphaError('Write a support message of up to 8000 characters.', 400)
    return value.strip()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def row(cur, ticket_id, workspace=None, lock=False):
    cur.execute('SELECT id::text,workspace_id::text,created_by::text,category,status,revision,created_at,first_response_at,resolved_at,'
                'updated_at,priority,assignee_id::text,duplicate_of::text FROM public.pr_support_tickets WHERE id=%s'
                + (' AND workspace_id=%s' if workspace else '') + (' FOR UPDATE' if lock else ''),
                (ticket_id, workspace) if workspace else (ticket_id,))
    found = cur.fetchone()
    if not found:
        raise AlphaError('Support ticket unavailable.', 404)
    return dict(zip(('id', 'workspaceId', 'createdBy', 'category', 'status', 'revision', 'createdAt', 'firstResponseAt', 'resolvedAt',
                     'updatedAt', 'priority', 'assigneeId', 'duplicateOfTicketId'), found))


def public(ticket):
    return {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in ticket.items() if k != 'createdBy'}


def previous_event(cur, workspace, request_id, digest):
    cur.execute('SELECT fingerprint,ticket_id::text FROM public.pr_support_workflow_events WHERE workspace_id=%s AND request_id=%s', (workspace, request_id))
    previous = cur.fetchone()
    if previous and previous[0] != digest:
        raise AlphaError('This support request key belongs to a different action.', 409)
    return bool(previous)


def event(cur, before, after, actor, role, kind, request_id, digest, *, message_id=None, related_ticket_id=None):
    cur.execute('INSERT INTO public.pr_support_workflow_events(workspace_id,ticket_id,request_id,actor_id,actor_role,kind,fingerprint,'
                'result_revision,from_status,to_status,from_priority,to_priority,from_assignee_id,to_assignee_id,related_ticket_id,message_id) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text',
                (after['workspaceId'], after['id'], request_id, actor, role, kind, digest, after['revision'],
                 before.get('status'), after['status'], before.get('priority'), after['priority'],
                 before.get('assigneeId'), after.get('assigneeId'), related_ticket_id, message_id))
    return cur.fetchone()[0]


def append(cur, ticket, actor, role, body, request_id, *, kind='message'):
    digest = fingerprint({'ticket': ticket['id'], 'actor': str(actor), 'role': role, 'body': body})
    cur.execute('SELECT id::text,fingerprint FROM public.pr_support_messages WHERE workspace_id=%s AND request_id=%s', (ticket['workspaceId'], request_id))
    previous = cur.fetchone()
    if previous:
        if previous[1] != digest:
            raise AlphaError('This support request key belongs to a different message.', 409)
        # Old messages may predate workflow collection. A retry never invents
        # an original event or moves its observed/occurred time.
        return previous[0], True
    if previous_event(cur, ticket['workspaceId'], request_id, digest):
        raise AlphaError('This support request key belongs to a different action.', 409)
    cur.execute('INSERT INTO public.pr_support_messages(workspace_id,ticket_id,actor_id,actor_role,body,request_id,fingerprint) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id::text',
                (ticket['workspaceId'], ticket['id'], actor, role, body, request_id, digest))
    message_id = cur.fetchone()[0]
    if role == 'founder':
        cur.execute("UPDATE public.pr_support_tickets SET first_response_at=coalesce(first_response_at,now()),status='waiting_customer',"
                    'duplicate_of=NULL,resolved_at=NULL,revision=revision+1,updated_at=now() WHERE id=%s', (ticket['id'],))
    else:
        cur.execute("UPDATE public.pr_support_tickets SET status='open',duplicate_of=NULL,resolved_at=NULL,revision=revision+1,updated_at=now() WHERE id=%s", (ticket['id'],))
    after = row(cur, ticket['id'])
    event(cur, ticket if kind != 'created' else {}, after, actor, role, kind, request_id, digest, message_id=message_id)
    audit(cur, ticket['workspaceId'], actor, 'support.message.created', ticket['id'], {'role': role, 'messageId': message_id})
    return message_id, False


def history(cur, ticket):
    cur.execute('SELECT kind,actor_role,result_revision,from_status,to_status,from_priority,to_priority,related_ticket_id::text,occurred_at,observed_at '
                'FROM public.pr_support_workflow_events WHERE workspace_id=%s AND ticket_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 101',
                (ticket['workspaceId'], ticket['id']))
    keys = ('kind', 'actorRole', 'revision', 'fromStatus', 'toStatus', 'fromPriority', 'toPriority', 'relatedTicketId', 'occurredAt', 'observedAt')
    rows = cur.fetchall()
    events = [{k: value.isoformat() if hasattr(value, 'isoformat') else value for k, value in zip(keys, values)} for values in reversed(rows[:100])]
    return events, len(rows) > 100


def customer(service, workspace, token, method, ticket_id=None, body=None):
    body = body or {}
    with service.repository.transaction(token, workspace) as (cur, member_row, actor):
        require(service.ideas._member(member_row), 'read')
        if method == 'GET':
            if ticket_id:
                ticket = row(cur, identifier(ticket_id), workspace)
                if ticket['createdBy'] != str(actor):
                    raise AlphaError('Support ticket unavailable.', 404)
                cur.execute('SELECT actor_role,body,created_at FROM public.pr_support_messages WHERE workspace_id=%s AND ticket_id=%s ORDER BY created_at DESC,id DESC LIMIT 201', (workspace, ticket['id']))
                rows = cur.fetchall()
                messages = [{'role': r[0], 'body': r[1], 'createdAt': r[2].isoformat()} for r in reversed(rows[:200])]
                events, has_earlier = history(cur, ticket)
                from . import support_surveys
                return {'ticket': public(ticket), 'survey': support_surveys.read(cur, ticket), 'messages': messages, 'hasEarlierMessages': len(rows) > 200,
                        'history': events, 'hasEarlierEvents': has_earlier}
            cur.execute('SELECT id::text FROM public.pr_support_tickets WHERE workspace_id=%s AND created_by=%s ORDER BY updated_at DESC LIMIT 100', (workspace, actor))
            ids = [r[0] for r in cur.fetchall()]
            return {'tickets': [public(row(cur, i, workspace)) for i in ids]}
        if method != 'POST' or set(body) - {'requestId', 'category', 'message'}:
            raise AlphaError('Invalid support request.', 400)
        request = identifier(body.get('requestId'))
        text = message(body.get('message'))
        if ticket_id:
            ticket = row(cur, identifier(ticket_id), workspace, lock=True)
            if ticket['createdBy'] != str(actor):
                raise AlphaError('Support ticket unavailable.', 404)
        else:
            category = body.get('category')
            if category not in CATEGORIES:
                raise AlphaError('Select a support category.', 400)
            cur.execute('INSERT INTO public.pr_support_tickets(id,workspace_id,created_by,category) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING', (request, workspace, actor, category))
            ticket = row(cur, request, workspace, lock=True)
            if ticket['createdBy'] != str(actor) or ticket['category'] != category:
                raise AlphaError('Support request key conflict.', 409)
        _, duplicate = append(cur, ticket, actor, 'customer', text, request, kind='message' if ticket_id else 'created')
        return {'ticket': public(row(cur, ticket['id'], workspace)), 'duplicate': duplicate}
