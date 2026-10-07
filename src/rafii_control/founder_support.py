"""Bounded support operations; no customer messages are copied into Ops."""
from postriff_alpha.domain import AlphaError
from postriff_phase2 import support
from postriff_phase2.hosted import audit
from . import founder_ops, http
from .auth import ControlError


def _factory(app):
    if getattr(app, 'runtime', None) is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return founder_ops._consumer_factory(app.consumer())


def _error(error):
    if isinstance(error, AlphaError):
        raise ControlError('VALIDATION_FAILED' if error.status < 500 else 'SOURCE_UNAVAILABLE', error.status) from None
    if isinstance(error, ControlError):
        raise error
    founder_ops._unavailable(error)


def list_tickets(app, principal, request):
    store = founder_ops._store(app)
    try:
        with store.transaction(read=True) as con:
            rows = con.execute('SELECT * FROM rafii_control.business_support_tickets ORDER BY "updatedAt" DESC,id LIMIT 100').fetchall()
            metrics = con.execute('SELECT count(*) AS "ticketCount",count(*) FILTER(WHERE status<>\'resolved\') AS "openTickets",'
                'count("firstResponseAt") AS "firstResponseSampleCount",avg(extract(epoch from ("firstResponseAt"-"createdAt"))) AS "firstResponseSeconds",'
                'count("resolvedAt") AS "resolutionSampleCount",avg(extract(epoch from ("resolvedAt"-"createdAt"))) AS "resolutionSeconds",'
                'max("updatedAt") AS watermark FROM rafii_control.business_support_tickets').fetchone()
        metrics = {k: v.isoformat() if hasattr(v, 'isoformat') else float(v) if k.endswith('Seconds') and v is not None else v for k, v in dict(metrics).items()}
        return {'tickets': [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in dict(r).items()} for r in rows], 'identityVisibility': 'masked',
                'metrics': {**metrics, 'source': 'in_app_tickets', 'state': 'measured', 'window': 'retained_history',
                            'timeBasis': 'elapsed_seconds', 'businessTimeSla': 'not_configured', 'csat': 'not_collected'}}
    except Exception as error:
        _error(error)


def operate(app, principal, request):
    body = request.get('body') or {}
    operation = request['match'][1]
    actor = str(principal['operator']['user_id'])
    try:
        ticket_id = support.identifier(request['match'][0])
        with _factory(app)() as db:
            with db.cursor() as cur:
                ticket = support.row(cur, ticket_id, lock=True)
                # Classification stays behind the restricted reader projection.
                with founder_ops._store(app).transaction(read=True) as con:
                    permitted = con.execute('SELECT id FROM rafii_control.business_support_tickets WHERE id=%s AND "workspaceId"=%s', (ticket_id, ticket['workspaceId'])).fetchone()
                if not permitted:
                    raise ControlError('SCOPE_DENIED', 403)
                if operation == 'reveal':
                    if set(body) != {'confirmation', 'reasonCode'} or body.get('confirmation') != 'REVEAL' or body.get('reasonCode') not in ('support_identity', 'support_investigation'):
                        raise ControlError('VALIDATION_FAILED', 400)
                    cur.execute('SELECT email FROM auth.users WHERE id=%s', (ticket['createdBy'],))
                    found = cur.fetchone()
                    cur.execute('SELECT actor_role,body,created_at FROM public.pr_support_messages WHERE ticket_id=%s AND workspace_id=%s ORDER BY created_at,id LIMIT 200', (ticket_id, ticket['workspaceId']))
                    result = {'ticketId': ticket_id, 'email': found[0] if found else None,
                              'messages': [{'role': r[0], 'body': r[1], 'createdAt': r[2].isoformat()} for r in cur.fetchall()], 'cachePolicy': 'no_store'}
                    audit(cur, ticket['workspaceId'], actor, 'support.identity.revealed', ticket_id, {'reasonCode': body['reasonCode']})
                elif operation == 'reply':
                    if set(body) != {'requestId', 'message', 'revision'} or type(body['revision']) is not int:
                        raise ControlError('VALIDATION_FAILED', 400)
                    request_id = support.identifier(body['requestId'])
                    cur.execute('SELECT 1 FROM public.pr_support_messages WHERE workspace_id=%s AND request_id=%s', (ticket['workspaceId'], request_id))
                    duplicate = bool(cur.fetchone())
                    if not duplicate and body['revision'] != ticket['revision']:
                        raise ControlError('REVISION_CONFLICT', 409)
                    _, duplicate = support.append(cur, ticket, actor, 'founder', support.message(body['message']), request_id)
                    result = {'ticket': support.public(support.row(cur, ticket_id)), 'duplicate': duplicate, 'delivery': 'in_app'}
                else:
                    if set(body) != {'revision', 'status'} or type(body['revision']) is not int or body['status'] not in support.STATUSES:
                        raise ControlError('VALIDATION_FAILED', 400)
                    if body['revision'] != ticket['revision']:
                        raise ControlError('REVISION_CONFLICT', 409)
                    cur.execute("UPDATE public.pr_support_tickets SET status=%s,revision=revision+1,updated_at=now(),resolved_at=CASE WHEN %s='resolved' THEN now() ELSE NULL END WHERE id=%s", (body['status'], body['status'], ticket_id))
                    audit(cur, ticket['workspaceId'], actor, 'support.status.changed', ticket_id, {'status': body['status']})
                    result = {'ticket': support.public(support.row(cur, ticket_id))}
            db.commit()
        return result
    except Exception as error:
        _error(error)


http.register_route('GET', r'/support/tickets', 'customers.read', 'founder_support', 'list_tickets', demo_ok=True)
http.register_route('POST', r'/support/tickets/([0-9a-f-]{36})/(reply|status)', 'followups.write', 'founder_support', 'operate', budget='founder.action')
http.register_route('POST', r'/support/tickets/([0-9a-f-]{36})/(reveal)', 'control.settings', 'founder_support', 'operate', step_up=True, budget='founder.action')
