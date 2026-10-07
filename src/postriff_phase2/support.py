"""In-app support, stored only in the customer's original tenant.

Control projections contain IDs, categories, states and timestamps. Original
messages and identity are fetched only for an explicit audited support reveal.
"""
import hashlib
import json
import uuid
from postriff_alpha.domain import AlphaError
from .hosted import audit
from .permissions import require

CATEGORIES = ('technical', 'billing', 'account', 'other')
STATUSES = ('open', 'waiting_customer', 'resolved')


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AlphaError('Invalid support request identifier.', 400) from None


def message(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 8000:
        raise AlphaError('Write a support message of up to 8000 characters.', 400)
    return value.strip()


def row(cur, ticket_id, workspace=None, lock=False):
    cur.execute('SELECT id::text,workspace_id::text,created_by::text,category,status,revision,created_at,first_response_at,resolved_at '
                'FROM public.pr_support_tickets WHERE id=%s' + (' AND workspace_id=%s' if workspace else '') + (' FOR UPDATE' if lock else ''),
                (ticket_id, workspace) if workspace else (ticket_id,))
    found = cur.fetchone()
    if not found:
        raise AlphaError('Support ticket unavailable.', 404)
    return dict(zip(('id', 'workspaceId', 'createdBy', 'category', 'status', 'revision', 'createdAt', 'firstResponseAt', 'resolvedAt'), found))


def public(ticket):
    return {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in ticket.items() if k != 'createdBy'}


def append(cur, ticket, actor, role, body, request_id):
    fingerprint = hashlib.sha256(json.dumps({'ticket': ticket['id'], 'actor': actor, 'role': role, 'body': body}, sort_keys=True).encode()).hexdigest()
    cur.execute('SELECT id::text,fingerprint FROM public.pr_support_messages WHERE workspace_id=%s AND request_id=%s', (ticket['workspaceId'], request_id))
    previous = cur.fetchone()
    if previous:
        if previous[1] != fingerprint:
            raise AlphaError('This support request key belongs to a different message.', 409)
        return previous[0], True
    cur.execute('INSERT INTO public.pr_support_messages(workspace_id,ticket_id,actor_id,actor_role,body,request_id,fingerprint) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id::text',
                (ticket['workspaceId'], ticket['id'], actor, role, body, request_id, fingerprint))
    message_id = cur.fetchone()[0]
    if role == 'founder':
        cur.execute("UPDATE public.pr_support_tickets SET first_response_at=coalesce(first_response_at,now()),status='waiting_customer',revision=revision+1,updated_at=now() WHERE id=%s", (ticket['id'],))
    else:
        cur.execute("UPDATE public.pr_support_tickets SET status='open',resolved_at=NULL,revision=revision+1,updated_at=now() WHERE id=%s", (ticket['id'],))
    audit(cur, ticket['workspaceId'], actor, 'support.message.created', ticket['id'], {'role': role, 'messageId': message_id})
    return message_id, False


def customer(service, workspace, token, method, ticket_id=None, body=None):
    body = body or {}
    with service.repository.transaction(token, workspace) as (cur, member_row, actor):
        require(service.ideas._member(member_row), 'read')
        if method == 'GET':
            if ticket_id:
                ticket = row(cur, identifier(ticket_id), workspace)
                if ticket['createdBy'] != str(actor):
                    raise AlphaError('Support ticket unavailable.', 404)
                cur.execute('SELECT actor_role,body,created_at FROM public.pr_support_messages WHERE workspace_id=%s AND ticket_id=%s ORDER BY created_at,id LIMIT 200', (workspace, ticket['id']))
                return {'ticket': public(ticket), 'messages': [{'role': r[0], 'body': r[1], 'createdAt': r[2].isoformat()} for r in cur.fetchall()]}
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
            # The ticket ID is the request ID; conflicting retries cannot create
            # a second ticket. Author and tenant are verified before any append.
            cur.execute('INSERT INTO public.pr_support_tickets(id,workspace_id,created_by,category) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING', (request, workspace, actor, category))
            ticket = row(cur, request, workspace, lock=True)
            if ticket['createdBy'] != str(actor) or ticket['category'] != category:
                raise AlphaError('Support request key conflict.', 409)
        _, duplicate = append(cur, ticket, actor, 'customer', text, request)
        return {'ticket': public(row(cur, ticket['id'], workspace)), 'duplicate': duplicate}
