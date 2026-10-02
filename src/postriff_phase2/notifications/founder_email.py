"""Original internal tenant, saved Reply-To and shared provider spending guard.

The qualified ceiling reserves potential provider spend; it is never booked as
actual cost. Provider acceptance/delivery does not prove the billing amount.
"""
from postriff_alpha.domain import AlphaError
from ..billing import ops_metadata
from ..founder_policy import policy_from_marker


def context(worker, user):
    if worker.founder_ledger is None or worker.environment not in ('production', 'staging', 'local'):
        raise AlphaError('Founder spending context is unavailable.', 503)
    if type(worker.email_cost_ceiling) is not int or not 0 < worker.email_cost_ceiling <= 50_000_000 or not worker.email_cost_qualification:
        raise AlphaError('Email provider cost ceiling is not qualified.', 503)
    with worker.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT w.id::text FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id "
                    "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.user_id=%s AND m.role='owner' AND m.status='active' "
                    "AND p.deleted_at IS NULL AND w.name LIKE 'Rafii Ops (founder)%%' AND w.state->'founderOps'->>'operatorId'=%s "
                    "AND w.state->'founderOps'->>'environment'=%s LIMIT 2", (user, user, worker.environment))
        rows = cur.fetchall()
        if len(rows) != 1:
            raise AlphaError('Founder internal tenant is not qualified.', 503)
        workspace = rows[0][0]
        marker = ops_metadata(cur, workspace)
        if not marker or marker['operatorId'] != user:
            raise AlphaError('Founder internal owner is unavailable.', 403)
        return workspace, policy_from_marker(marker)


def reserve(worker, cur, user, workspace, settings, key):
    marker = ops_metadata(cur, workspace)
    current = policy_from_marker(marker)
    if not marker or marker['operatorId'] != user or current['approvalRef'] != settings['approvalRef']:
        raise AlphaError('Founder delivery settings changed; prepare a new delivery.', 409)
    worker.founder_ledger.reserve(cur, workspace, user, 'tool', worker.email_cost_ceiling, 'founder-email:' + key,
        charge_batch=False, provider='resend', model='transactional_email',
        meta={'via': 'rafii_founder_email', 'service': 'email', 'action': 'email.send',
              'costBasis': 'qualified_provider_ceiling', 'costQualificationRef': worker.email_cost_qualification})
