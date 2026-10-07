"""Read-only activation gates. Configuration never substitutes for canary proof.

The same F01-F24 manifest feeds the API and release artifact. No credentials,
customer content, model dispatch or automatic policy changes occur here.
"""
import os
from datetime import datetime, timezone

from . import founder_ops, http
from .auth import ControlError
from .founder_contact import truthy

FEATURES = (
    ('F01', 'Founder authentication', (), (), 'Verify existing login, fresh factor, CSRF, logout and non-Founder denial.'),
    ('F02', 'Portal pages', (), (), 'Verify all pages in Live and Demo at 390, 768 and 1440 pixels.'),
    ('F03', 'Customers and workspace integrity', (), (), 'Reconcile bounded projections against customer A/B and internal tenants.'),
    ('F04', 'Internal Ops workspace', (), (), 'Finish the reserved workspace through authenticated fresh MFA.'),
    ('F05', 'Founder text agent', ('RAFII_AGENT_V2_ENABLED',), ('H2',), 'Run one capped owner turn and match its tools, receipts and cost.'),
    ('F06', 'Jobs and continuity', (), (), 'Reconcile stale runs against leases/provider evidence; verify cancellation and continuity.'),
    ('F07', 'Browser voice', ('RAFII_FOUNDER_VOICE_ENABLED',), ('H2', 'H5'), 'Owner microphone consent, bounded voice/delegation/end and settlement canary.'),
    ('F08', 'Outbound calls', ('RAFII_FOUNDER_CALLS_ENABLED',), ('H2', 'H3', 'H5'), 'Verified owner destination, contact policy, quiet hours, caps and one approved call.'),
    ('F09', 'In-app notices', (), (), 'Create one safe notice, retry, follow its link and acknowledge it.'),
    ('F10', 'Founder email', ('RAFII_FOUNDER_EMAIL_ENABLED',), ('H1', 'H2', 'H3'), 'Approve sender and Founder cutover; verify accepted and signed delivered receipts.'),
    ('F11', 'Customer transactional email', (), ('H1', 'H2'), 'Approve customer cutover; qualify new V2 events and legacy durable outbox.'),
    ('F12', 'Founder push', ('RAFII_FOUNDER_PUSH_ENABLED',), ('H2', 'H5'), 'Owner device gesture/subscription, expiry, lock-screen delivery and click/read proof.'),
    ('F13', 'Briefings', (), ('H3',), 'Approve schedules; verify DST, overlap, coalescing, retries and receipt coverage.'),
    ('F14', 'Incidents and follow-ups', (), (), 'Synthetic staging trigger/recovery; observe production detector without customer disruption.'),
    ('F15', 'Revenue and payments', (), ('H4',), 'Qualify approved catalog and signed Stripe test lifecycle; preserve empty real revenue.'),
    ('F16', 'AI cost and attempts', (), (), 'Trace attempts and reserve/settle/late cost; retain unknown historical reservations.'),
    ('F17', 'Product and retention', (), (), 'Trace fresh journeys and watermarks; wait for mature cohorts before measuring retention.'),
    ('F18', 'Operations and connections', (), (), 'Verify per-stage health, telemetry gaps, queues, source lag and revoked connections.'),
    ('F19', 'Support tickets', (), ('H6',), 'Verify the in-app ticket source, tenant isolation, reply/reopen/resolve, masked metadata and audited reveal.'),
    ('F20', 'Credits and top-ups', ('POSTRIFF_CREDITS_ENABLED','POSTRIFF_CREDIT_PURCHASES_ENABLED'), ('H4',), 'Approve catalog; test grants, reserve/settle and signed top-ups before live charges.'),
    ('F21', 'Scoped administrative actions', (), (), 'Verify MFA, typed confirmation, CAS, dedupe and bounded reversible account canary.'),
    ('F22', 'Refund execution', (), ('H4',), 'Verify fresh-factor typed confirmation, signed Stripe receipts and read-only recovery; actual refunds require per-action confirmation.'),
    ('F23', 'Engineering and audit receipts', (), (), 'Match exact candidate SHA, required CI, deployment and evidence manifest.'),
    ('F24', 'Marketing and attribution', (), ('H6',), 'Authorize actual GSC/acquisition/spend sources and wait for qualified history.'),
)


def feature_manifest(values, *, ops=None, policy_applied=False):
    rows = []
    for feature_id, name, flags, decisions, action in FEATURES:
        blockers = ['owner_device_consent' for decision in decisions if decision == 'H5']
        effective = {flag: truthy(values.get(flag)) for flag in flags}
        blockers.extend('flag_off:' + flag for flag, enabled in effective.items() if not enabled)
        if feature_id in ('F04', 'F05', 'F07', 'F08') and not (ops or {}).get('workspaceId'):
            blockers.append('ops_workspace_not_ready')
        if feature_id in ('F05', 'F07', 'F08') and not policy_applied:
            blockers.append('approved_policy_not_saved')
        if feature_id in ('F10', 'F11'):
            required = ('RESEND_API_KEY', 'EMAIL_FROM', 'POSTRIFF_PUBLIC_BASE_URL', 'RESEND_WEBHOOK_SECRET')
            blockers.extend('config_missing:' + key for key in required if not values.get(key))
            blockers.append('durable_cutover_and_delivery_proof_required')
        if feature_id == 'F11':
            blockers.append('legacy_outbox_not_qualified')
        if feature_id == 'F19':
            blockers.append('support_schema_and_authenticated_flow_not_verified')
        if feature_id == 'F22':
            blockers.append('stripe_provider_and_financial_confirmation_required')
        if feature_id == 'F24':
            blockers.append('authorized_sources_not_verified')
        rows.append({'id': feature_id, 'name': name, 'state': 'blocked_owner' if 'H5' in decisions else 'ready_for_verification' if not blockers else 'configured_off',
                     'blockers': blockers, 'ownerDependencies': [d for d in decisions if d == 'H5'], 'acceptedOwnerDecisions': [d for d in decisions if d != 'H5'], 'effectiveFlags': effective,
                     'activationProof': 'not_verified', 'nextAction': action})
    return rows


def telemetry(app):
    store = getattr(getattr(app, 'queries', None), 'store', None)
    if store is None:
        return {'dataState': 'unavailable', 'reason': 'source_unavailable', 'writers': []}
    try:
        with store.transaction(read=True) as con:
            rows = con.execute('SELECT writer,sum(attempted) AS attempted,sum(recorded) AS recorded,'
                               "count(*) FILTER(WHERE state='failed') AS failed_batches,"
                               "count(*) FILTER(WHERE state='suspended') AS suspended_batches,"
                               "sum(attempted) FILTER(WHERE state IN ('failed','suspended') AND NOT recovered) AS missing,"
                               'min("observedAt") AS first_seen,max("observedAt") AS last_seen '
                               'FROM rafii_control.business_telemetry_health '
                               'WHERE "observedAt">now()-interval \'24 hours\' GROUP BY writer').fetchall()
        writers = [{key: value.isoformat() if isinstance(value, datetime) else int(value) if value is not None and key not in ('writer',) else value
                    for key, value in dict(row).items()} for row in rows]
        missing_writers = sorted({'product_events', 'ai_call_events'} - {row['writer'] for row in writers})
        return {'dataState': 'partial' if missing_writers or any(row.get('missing') for row in writers) else 'measured',
                'reason': 'not_instrumented' if missing_writers else 'writer_gap' if any(row.get('missing') for row in writers) else None,
                'writers': writers, 'missingWriters': missing_writers, 'windowSeconds': 86400,
                'coverageLimit': 'Journal cannot record database-wide outages; independent probes remain required.'}
    except Exception:
        return {'dataState': 'unavailable', 'reason': 'telemetry_projection_unavailable', 'writers': []}


def readiness(app, principal, request):
    values = {**os.environ, **(getattr(app, 'flags', None) or {})}
    try:
        ops = founder_ops.get_ops(app, principal, request)
    except ControlError as error:
        ops = {'workspaceId': None, 'provisioningState': 'unavailable', 'reason': error.code}
    policy_applied = False
    if ops.get('workspaceId') and getattr(app, 'runtime', None) is not None:
        try:
            from .founder_policy import _factory, _read
            with _factory(app)() as db, db.cursor() as cur:
                _, _, policy_applied = _read(cur, ops['workspaceId'], principal['operator']['user_id'])
        except Exception:
            pass
    return {'asOf': datetime.now(timezone.utc).isoformat(), 'sourceSha': values.get('VERCEL_GIT_COMMIT_SHA'),
            'executionState': 'read_only_configuration', 'features': feature_manifest(values, ops=ops, policy_applied=policy_applied), 'ops': ops,
            'telemetry': telemetry(app), 'releaseVerified': False}


http.register_route('GET', r'/activation/readiness', 'control.read', 'founder_activation', 'readiness', demo_ok=True)
