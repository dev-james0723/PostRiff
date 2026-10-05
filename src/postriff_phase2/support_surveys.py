"""Original-tenant, optional yes/no feedback on observed support resolutions."""
from postriff_alpha.domain import AlphaError
from postriff_phase2 import support
from postriff_phase2.hosted import audit
from postriff_phase2.permissions import require

SOURCE_VERSION = 'in_app_support_csat_yes_no/v1'


def offer(cur, before, after, resolution_event_id):
    """Only a new, actually observed human-supported resolution creates an offer."""
    if after['resolvedAt'] is None or after['resolvedAt'] == before['resolvedAt'] or after['firstResponseAt'] is None:
        return
    cur.execute('INSERT INTO public.pr_support_survey_offers(workspace_id,ticket_id,recipient_id,resolution_event_id,resolution_revision,resolved_at,source_version) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,resolution_event_id) DO NOTHING',
                (after['workspaceId'], after['id'], after['createdBy'], resolution_event_id, after['revision'], after['resolvedAt'], SOURCE_VERSION))


def read(cur, ticket):
    cur.execute('SELECT o.id::text,o.resolved_at,o.resolution_revision,o.offered_at,o.source_version,r.helpful,r.answered_at '
                'FROM public.pr_support_survey_offers o LEFT JOIN public.pr_support_survey_responses r '
                'ON r.workspace_id=o.workspace_id AND r.survey_id=o.id '
                'WHERE o.workspace_id=%s AND o.ticket_id=%s AND o.recipient_id=%s ORDER BY o.offered_at DESC,o.id DESC LIMIT 1',
                (ticket['workspaceId'], ticket['id'], ticket['createdBy']))
    found = cur.fetchone()
    if found is None:
        return None
    eligible = ticket['status'] in ('resolved', 'closed') and ticket['resolvedAt'] == found[1]
    return {'id': found[0], 'resolutionRevision': found[2], 'offeredAt': found[3].isoformat(), 'sourceVersion': found[4],
            'helpful': found[5], 'answeredAt': found[6].isoformat() if found[6] else None,
            'state': 'answered' if found[5] is not None else 'eligible' if eligible else 'reopened',
            'question': 'Was this support resolution helpful?'}


def respond(service, workspace, token, ticket_id, body):
    if not isinstance(body, dict) or set(body) != {'requestId', 'surveyId', 'helpful'} or type(body['helpful']) is not bool:
        raise AlphaError('Choose whether this support resolution was helpful.', 400)
    ticket_id, survey_id, request_id = (support.identifier(value) for value in (ticket_id, body['surveyId'], body['requestId']))
    with service.repository.transaction(token, workspace) as (cur, member_row, actor):
        require(service.ideas._member(member_row), 'read')
        ticket = support.row(cur, ticket_id, workspace, lock=True)
        if ticket['createdBy'] != str(actor):
            raise AlphaError('Support ticket unavailable.', 404)
        digest = support.fingerprint({'ticket': ticket_id, 'survey': survey_id, 'actor': str(actor), 'helpful': body['helpful']})
        cur.execute('SELECT survey_id::text,fingerprint FROM public.pr_support_survey_responses WHERE workspace_id=%s AND request_id=%s', (workspace, request_id))
        previous = cur.fetchone()
        if previous:
            if previous != (survey_id, digest):
                raise AlphaError('This support request key belongs to a different action.', 409)
            return {'survey': read(cur, ticket), 'duplicate': True}
        cur.execute('SELECT resolved_at,source_version FROM public.pr_support_survey_offers WHERE workspace_id=%s AND id=%s AND ticket_id=%s AND recipient_id=%s',
                    (workspace, survey_id, ticket_id, actor))
        offer_row = cur.fetchone()
        if offer_row is None:
            raise AlphaError('Support survey unavailable.', 404)
        if ticket['status'] not in ('resolved', 'closed') or ticket['resolvedAt'] != offer_row[0]:
            raise AlphaError('This support resolution has reopened.', 409)
        cur.execute('SELECT 1 FROM public.pr_support_survey_responses WHERE workspace_id=%s AND survey_id=%s', (workspace, survey_id))
        if cur.fetchone():
            raise AlphaError('Feedback for this resolution has already been recorded.', 409)
        cur.execute('INSERT INTO public.pr_support_survey_responses(workspace_id,survey_id,actor_id,request_id,fingerprint,helpful,source_version) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (workspace, survey_id, actor, request_id, digest, body['helpful'], offer_row[1]))
        audit(cur, workspace, actor, 'support.survey.answered', ticket_id, {'surveyId': survey_id, 'sourceVersion': offer_row[1]})
        return {'survey': read(cur, ticket), 'duplicate': False}
