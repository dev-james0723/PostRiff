"""Bounded support workflow; originals stay in their customer tenant."""
import uuid
from postriff_alpha.domain import AlphaError
from postriff_phase2 import support, support_surveys
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


def _serialize(value):
    return {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in dict(value).items()}


def _permitted(app, ticket):
    with founder_ops._store(app).transaction(read=True) as con:
        found = con.execute('SELECT id FROM rafii_control.business_support_tickets WHERE id=%s AND "workspaceId"=%s', (ticket['id'], ticket['workspaceId'])).fetchone()
    if not found:
        raise ControlError('SCOPE_DENIED', 403)


def list_tickets(app, principal, request):
    try:
        with founder_ops._store(app).transaction(read=True) as con:
            rows = con.execute('SELECT * FROM rafii_control.business_support_tickets ORDER BY "updatedAt" DESC,id LIMIT 100').fetchall()
            metrics = con.execute('SELECT count(*) AS "ticketCount",count(*) FILTER(WHERE status IN (\'open\',\'waiting_customer\')) AS "openTickets",'
                'count("firstResponseAt") AS "firstResponseSampleCount",avg(extract(epoch from ("firstResponseAt"-"createdAt"))) AS "firstResponseSeconds",'
                'count("resolvedAt") AS "resolutionSampleCount",avg(extract(epoch from ("resolvedAt"-"createdAt"))) AS "resolutionSeconds",'
                'max("updatedAt") AS watermark FROM rafii_control.business_support_tickets').fetchone()
            survey_metrics = con.execute('SELECT count(o.id) AS offers,count(r.id) AS responses,count(r.id) FILTER(WHERE r.helpful) AS positive,max(greatest(o.\"offeredAt\",r.\"answeredAt\")) AS watermark FROM rafii_control.business_support_survey_offers o LEFT JOIN rafii_control.business_support_survey_responses r ON r.\"workspaceId\"=o.\"workspaceId\" AND r.\"surveyId\"=o.id').fetchone()
        metrics = {k: v.isoformat() if hasattr(v, 'isoformat') else float(v) if k.endswith('Seconds') and v is not None else v for k, v in dict(metrics).items()}
        return {'tickets': [_serialize(r) for r in rows], 'identityVisibility': 'masked',
                'metrics': {**metrics, 'source': 'in_app_tickets', 'state': 'measured', 'window': 'retained_history',
                            'timeBasis': 'elapsed_seconds', 'businessTimeSla': 'not_configured', 'csat': {'surveyOffers': survey_metrics['offers'], 'validResponses': survey_metrics['responses'], 'positiveResponses': survey_metrics['positive'], 'ratio': survey_metrics['positive'] / survey_metrics['responses'] if survey_metrics['responses'] else None, 'responseRate': survey_metrics['responses'] / survey_metrics['offers'] if survey_metrics['offers'] else None, 'responseRateBasis': 'observed_resolution_offers', 'coverage': 'observed_resolution_offers_only', 'sourceVersion': support_surveys.SOURCE_VERSION, 'watermark': survey_metrics['watermark'].isoformat() if survey_metrics['watermark'] else None}}}
    except Exception as error:
        _error(error)


def history(app, principal, request):
    try:
        ticket_id = support.identifier(request['match'][0])
        with founder_ops._store(app).transaction(read=True) as con:
            ticket = con.execute('SELECT id,"workspaceId" FROM rafii_control.business_support_tickets WHERE id=%s', (ticket_id,)).fetchone()
            if not ticket:
                raise ControlError('SCOPE_DENIED', 403)
            rows = con.execute('SELECT * FROM rafii_control.business_support_workflow_events WHERE "ticketId"=%s AND "workspaceId"=%s ORDER BY "occurredAt" DESC,id DESC LIMIT 101', (ticket_id, ticket['workspaceId'])).fetchall()
        return {'ticketId': ticket_id, 'events': [_serialize(r) for r in reversed(rows[:100])], 'hasEarlierEvents': len(rows) > 100, 'sourceVersion': 'in_app_support_workflow/v1',
                'coverage': 'observed_workflow_events_only', 'businessTimeSla': 'not_configured'}
    except Exception as error:
        _error(error)


def _workflow(cur, ticket, actor, operation, body):
    required = {'triage': {'requestId', 'revision', 'priority', 'assignee'},
                'link': {'requestId', 'revision', 'targetTicketId', 'relation'},
                'unlink': {'requestId', 'revision'}}
    if operation == 'status':
        if set(body) not in ({'revision', 'status'}, {'requestId', 'revision', 'status'}) or body.get('status') not in support.STATUSES or body['status'] == 'duplicate':
            raise ControlError('VALIDATION_FAILED', 400)
    elif operation not in required or set(body) != required[operation]:
        raise ControlError('VALIDATION_FAILED', 400)
    if type(body.get('revision')) is not int:
        raise ControlError('VALIDATION_FAILED', 400)
    request_id = support.identifier(body.get('requestId', str(uuid.uuid4())))
    digest = support.fingerprint({'ticket': ticket['id'], 'actor': actor, 'operation': operation, 'body': body})
    if support.previous_event(cur, ticket['workspaceId'], request_id, digest):
        return {'ticket': support.public(ticket), 'duplicate': True}
    if body['revision'] != ticket['revision']:
        raise ControlError('REVISION_CONFLICT', 409)
    kind, related = operation, None
    if operation == 'triage':
        if body['priority'] not in support.PRIORITIES or body['assignee'] not in ('keep', 'me', 'unassigned'):
            raise ControlError('VALIDATION_FAILED', 400)
        assignee = ticket['assigneeId'] if body['assignee'] == 'keep' else actor if body['assignee'] == 'me' else None
        cur.execute('UPDATE public.pr_support_tickets SET priority=%s,assignee_id=%s,revision=revision+1,updated_at=now() WHERE id=%s', (body['priority'], assignee, ticket['id']))
    elif operation == 'status':
        cur.execute("UPDATE public.pr_support_tickets SET status=%s,duplicate_of=NULL,revision=revision+1,updated_at=now(),resolved_at=CASE WHEN %s IN ('resolved','closed') THEN coalesce(resolved_at,now()) ELSE NULL END WHERE id=%s", (body['status'], body['status'], ticket['id']))
    elif operation == 'unlink':
        if ticket['duplicateOfTicketId'] is None:
            raise ControlError('VALIDATION_FAILED', 400)
        kind, related = 'duplicate_unlink', ticket['duplicateOfTicketId']
        cur.execute("UPDATE public.pr_support_tickets SET duplicate_of=NULL,status='open',resolved_at=NULL,revision=revision+1,updated_at=now() WHERE id=%s", (ticket['id'],))
    else:
        related = support.identifier(body['targetTicketId'])
        if related == ticket['id'] or body['relation'] not in ('duplicate', 'verified_recurrence'):
            raise ControlError('VALIDATION_FAILED', 400)
        target = support.row(cur, related, ticket['workspaceId'], lock=True)
        if body['relation'] == 'verified_recurrence':
            if target['resolvedAt'] is None or target['resolvedAt'] > ticket['createdAt']:
                raise ControlError('VALIDATION_FAILED', 400)
            kind = 'verified_recurrence'
            cur.execute('UPDATE public.pr_support_tickets SET revision=revision+1,updated_at=now() WHERE id=%s', (ticket['id'],))
        else:
            # All Founder workflow operations lock this tenant before ticket
            # rows. Concurrent reciprocal links cannot create a cycle.
            seen = {ticket['id']}
            for _ in range(100):
                if target['id'] in seen:
                    raise ControlError('VALIDATION_FAILED', 400)
                seen.add(target['id'])
                if target['duplicateOfTicketId'] is None:
                    break
                target = support.row(cur, target['duplicateOfTicketId'], ticket['workspaceId'], lock=True)
            else:
                raise ControlError('VALIDATION_FAILED', 400)
            kind = 'duplicate_link'
            cur.execute("UPDATE public.pr_support_tickets SET duplicate_of=%s,status='duplicate',resolved_at=NULL,revision=revision+1,updated_at=now() WHERE id=%s", (related, ticket['id']))
    after = support.row(cur, ticket['id'])
    event_id = support.event(cur, ticket, after, actor, 'founder', kind, request_id, digest, related_ticket_id=related)
    if kind == 'status':
        support_surveys.offer(cur, ticket, after, event_id)
    audit(cur, ticket['workspaceId'], actor, 'support.workflow.changed', ticket['id'], {'operation': kind, 'revision': after['revision']})
    return {'ticket': support.public(after), 'duplicate': False}


def operate(app, principal, request):
    body = request.get('body') or {}
    operation = request['match'][1]
    actor = str(principal['operator']['user_id'])
    try:
        ticket_id = support.identifier(request['match'][0])
        with _factory(app)() as db:
            with db.cursor() as cur:
                initial = support.row(cur, ticket_id)
                _permitted(app, initial)
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('support-workflow:'||%s,0))", (initial['workspaceId'],))
                ticket = support.row(cur, ticket_id, lock=True)
                _permitted(app, ticket)
                if operation == 'reveal':
                    if set(body) != {'confirmation', 'reasonCode'} or body.get('confirmation') != 'REVEAL' or body.get('reasonCode') not in ('support_identity', 'support_investigation'):
                        raise ControlError('VALIDATION_FAILED', 400)
                    cur.execute('SELECT email FROM auth.users WHERE id=%s', (ticket['createdBy'],))
                    found = cur.fetchone()
                    cur.execute('SELECT actor_role,body,created_at FROM public.pr_support_messages WHERE ticket_id=%s AND workspace_id=%s ORDER BY created_at DESC,id DESC LIMIT 201', (ticket_id, ticket['workspaceId']))
                    rows = cur.fetchall()
                    result = {'ticketId': ticket_id, 'email': found[0] if found else None,
                              'messages': [{'role': r[0], 'body': r[1], 'createdAt': r[2].isoformat()} for r in reversed(rows[:200])],
                              'hasEarlierMessages': len(rows) > 200, 'cachePolicy': 'no_store'}
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
                    result = _workflow(cur, ticket, actor, operation, body)
            db.commit()
        return result
    except Exception as error:
        _error(error)


http.register_route('GET', r'/support/tickets', 'customers.read', 'founder_support', 'list_tickets', demo_ok=True)
http.register_route('GET', r'/support/tickets/([0-9a-f-]{36})/history', 'customers.read', 'founder_support', 'history')
http.register_route('POST', r'/support/tickets/([0-9a-f-]{36})/(reply|status|triage|link|unlink)', 'followups.write', 'founder_support', 'operate', budget='founder.action')
http.register_route('POST', r'/support/tickets/([0-9a-f-]{36})/(reveal)', 'control.settings', 'founder_support', 'operate', step_up=True, budget='founder.action')
