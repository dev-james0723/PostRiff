"""Founder Connections: one prioritised attention queue and the provider approval registry (Rafii API connections
ENGINEERING-SPEC §13.2-§13.3, acceptance A29-A31).

Every row answers: what is wrong, how many are affected, who owns it and what happens next. Inputs are the existing
restricted projections only: rafii_control.business_connection_health (hourly, cron connection_health) and the open
founder incidents. This module never reads credentials, never calls a provider and never writes anything.

Honest states.
- Freshness: every status carries one envelope (value, evidence source/ref, observedAt, lastCheckedAt, age, cadence, staleAfter,
  coverage, fresh|stale|unknown|not_applicable). A missing timestamp, a timestamp in the future beyond the skew tolerance, or
  a check older than its observation is 'unknown', never fresh. Only fresh evidence with complete coverage can be green.
- Impact: users, tenants, connections and jobs are counted separately with their own countState (exact, estimated,
  lower_bound, unknown). A count that cannot be observed is None with 'unknown', never 0. The queue summary takes the union
  of distinct tenants across items; it never adds item counts together.
- Approvals: one row per (provider, appRef, environment, product, lane) and requirement. Brand verification, sensitive scope
  review, app review, audits, callbacks and quotas are separate requirements; nothing aggregates them into one green badge.
  'submitted' is not 'approved'. An approval needs a decision time, a provider receipt reference and approved scopes that
  cover the request. The checked-in registry below is code-reviewed evidence intake: it starts at 'unknown' for every
  requirement because no provider decision receipt has been recorded here yet.
- Acknowledged items stay in the queue (acknowledgement is not resolution); unassigned owners say so.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from . import http, live_metrics
from .live_metrics import excluded, parse_stamp
from .store import MetricStatement

CONNECTION_VIEW = 'rafii_control.business_connection_health'
H_WORKSPACE = 'h."workspaceId"'
MAX_CONNECTION_ROWS = 5000
MAX_ITEMS = 100
CLOCK_SKEW_SECONDS = 300
CONNECTION_CADENCE_SECONDS = 3600            # founder_metrics_ops.connection_health_stage refreshes hourly
CONNECTION_STALE_SECONDS = 2 * 3600          # §13.3: connection hourly projection > 2 h is stale
REGISTRY_STALE_SECONDS = 7 * 86400           # §13.3: review/domain/callback metadata > 7 days is stale
FRESHNESS = ('fresh', 'stale', 'unknown', 'not_applicable')
COUNT_STATES = ('exact', 'estimated', 'lower_bound', 'unknown')
ITEM_STATES = ('open', 'acknowledged', 'action_pending', 'blocked', 'recovered', 'closed')
PRIORITIES = ('P0', 'P1', 'P2', 'P3')
UNASSIGNED = 'Unassigned — coordinator action required'

# ---- freshness envelope ------------------------------------------------------------------------------------------------------
def _epoch(value):
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    try:
        return parse_stamp(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def _iso(epoch):
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z')


def freshness(*, now, observed_at, last_checked_at=None, stale_after, cadence=None, source, evidence_ref=None, value=None, coverage='complete'):
    """The shared freshness envelope. Age runs from the last completed check (a failed check must not move observedAt, so
    callers pass the last successful check). Missing or impossible timestamps are 'unknown'; so is unknown coverage."""
    observed, checked = _epoch(observed_at), _epoch(last_checked_at)
    checked = observed if checked is None else checked
    reason, state, age = None, 'unknown', None
    if observed is None:
        reason = 'missing_timestamp'
    elif observed - now > CLOCK_SKEW_SECONDS or checked - now > CLOCK_SKEW_SECONDS:
        reason = 'clock_skew'
    elif checked + CLOCK_SKEW_SECONDS < observed:
        reason = 'check_precedes_observation'
    elif stale_after is None:
        reason = 'missing_cadence'
    elif coverage not in ('complete', 'partial'):
        reason = 'coverage_unknown'
    else:
        age = max(0, int(now - checked))
        state = 'fresh' if age <= stale_after else 'stale'
        reason = 'stale_after_exceeded' if state == 'stale' else None
    return {'value': value, 'evidenceSource': source, 'evidenceRef': evidence_ref, 'observedAt': _iso(observed), 'lastCheckedAt': _iso(checked if observed is not None else None),
            'ageSeconds': age, 'expectedCadenceSeconds': cadence, 'staleAfterSeconds': stale_after, 'coverage': coverage, 'freshness': state, 'reason': reason}


def green(envelope):
    """Health may be shown green only for fresh evidence with complete coverage."""
    return bool(envelope) and envelope['freshness'] == 'fresh' and envelope['coverage'] == 'complete'


# ---- provider approval registry ------------------------------------------------------------------------------------------------
REQUIREMENT_KINDS = ('brand_verification', 'sensitive_scope', 'restricted_scope', 'app_review', 'business_verification', 'api_audit',
                     'domain_ownership', 'callback_registration', 'production_audience', 'quota_entitlement')
APPROVAL_STATUSES = ('unknown', 'not_required_evidenced', 'testing_only', 'submitted', 'approved', 'rejected', 'suspended')
EVIDENCE_REF = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{2,160}$')   # opaque references only: no query strings, fragments or credentials
REGISTRY_VERSION = 1
NEXT_ACTIONS = {
    'brand_verification': 'Record the Google brand verification decision for this exact project and client.',
    'sensitive_scope': 'Record the sensitive-scope decision for exactly these scopes; brand approval does not cover it.',
    'restricted_scope': 'Record the restricted-scope decision and any security assessment for exactly these scopes.',
    'app_review': 'Record the provider app review decision for each requested permission or product.',
    'business_verification': 'Record the provider business verification decision for this app.',
    'api_audit': 'Record the provider API audit decision; until then the provider may limit content to private or test audiences.',
    'domain_ownership': 'Record proof that the provider console verified ownership of the deployed origin.',
    'callback_registration': 'Record the exact callback URI registered with the provider for this environment.',
    'production_audience': 'Record whether the app may serve ordinary accounts or only app-role test users.',
    'quota_entitlement': 'Record the provider quota allotted to this project; local reservations are not provider quota.',
}
GOOGLE = ('brand_verification', 'sensitive_scope', 'domain_ownership', 'callback_registration', 'production_audience')
META = ('app_review', 'business_verification', 'callback_registration', 'production_audience')
REGISTRY_KINDS = {'youtube': GOOGLE + ('api_audit', 'quota_entitlement'), 'google_business_profile': GOOGLE,
                  'instagram': META, 'threads': META, 'facebook': META, 'tiktok': ('app_review', 'api_audit', 'callback_registration', 'production_audience')}
DEFAULT_KINDS = ('app_review', 'callback_registration', 'production_audience')
SIGN_IN_APP = {'provider': 'google', 'appRef': 'rafii-sign-in', 'environment': 'production', 'product': 'sign_in', 'lane': 'identity',
               'requestedScopes': ['openid', 'email', 'profile'], 'kinds': ('brand_verification', 'domain_ownership', 'callback_registration')}
# Recorded provider decisions, keyed (provider, appRef, environment, kind). Each entry needs status, decidedAt, providerReceiptRef,
# approvedScopes, verifiedBy, evidenceObservedAt and lastCheckedAt. Empty: no decision receipt has been reviewed into this
# registry yet (2026-10-09), so every requirement reports 'unknown' / check required.
RECORDED_DECISIONS = {}
# The provider(s) the first launch covers. Empty until James records the launch scope; registry blockers are launch blockers
# only for providers listed here, and an empty scope is itself an attention item.
LAUNCH_SCOPE = ()


def _requested_scopes(cls):
    return list(getattr(cls, 'documented_scopes', ())) or sorted({scope for scopes in getattr(cls, 'SCOPES', {}).values() for scope in scopes})


def registry_entries(adapters=None, decisions=None):
    """Registry rows from the adapter classes (secret-free class attributes: platform and requested scopes) plus the sign-in app.
    `decisions` overrides RECORDED_DECISIONS (tests). Credentials, callbacks and console state are never read here."""
    if adapters is None:
        try:
            from postriff_phase2.providers import ADAPTERS as adapters
        except Exception:
            adapters = {}
    decisions = RECORDED_DECISIONS if decisions is None else decisions
    apps = [dict(SIGN_IN_APP)] + [{'provider': pid, 'appRef': pid, 'environment': 'production', 'product': 'social_connection', 'lane': 'standard',
                                    'requestedScopes': _requested_scopes(cls), 'kinds': REGISTRY_KINDS.get(pid, DEFAULT_KINDS)} for pid, cls in adapters.items()]
    entries = []
    for app in apps:
        requirements = []
        for kind in app['kinds']:
            recorded = decisions.get((app['provider'], app['appRef'], app['environment'], kind)) or {}
            requirements.append({'kind': kind, 'requestedScopes': list(recorded.get('requestedScopes') or app['requestedScopes']), **recorded})
        entries.append({key: app[key] for key in ('provider', 'appRef', 'environment', 'product', 'lane')} | {'requirements': requirements,
                                                                                                         'launchScope': app['provider'] in LAUNCH_SCOPE})
    return entries


def evaluate_requirement(requirement, now, *, environment):
    """One requirement row with its effective standing: satisfied | stale | pending | check_required | blocked."""
    kind, status = requirement.get('kind'), requirement.get('status') or 'unknown'
    if kind not in REQUIREMENT_KINDS or status not in APPROVAL_STATUSES:
        raise ValueError('invalid approval requirement')
    ref = requirement.get('providerReceiptRef')
    ref = ref if isinstance(ref, str) and EVIDENCE_REF.fullmatch(ref) else None
    requested, approved = set(requirement.get('requestedScopes') or ()), set(requirement.get('approvedScopes') or ())
    envelope = freshness(now=now, observed_at=requirement.get('evidenceObservedAt'), last_checked_at=requirement.get('lastCheckedAt'),
                         stale_after=REGISTRY_STALE_SECONDS, cadence=REGISTRY_STALE_SECONDS, source=requirement.get('evidenceSource') or 'not_recorded',
                         evidence_ref=ref, value=status)
    expires = _epoch(requirement.get('expiresAt'))
    blockers = []
    if requirement.get('environment') not in (None, environment):
        standing, blockers = 'blocked', ['environment_mismatch']
    elif status in ('rejected', 'suspended'):
        standing, blockers = 'blocked', ['provider_' + status]
    elif status == 'testing_only':
        standing, blockers = 'blocked', ['testing_only_audience']
    elif status == 'submitted':
        standing, blockers = 'pending', ['provider_decision_pending']
    elif status == 'unknown':
        standing, blockers = 'check_required', ['no_decision_recorded']
    elif ref is None or _epoch(requirement.get('decidedAt')) is None:
        standing, blockers = 'check_required', ['decision_receipt_missing']
    elif status == 'approved' and kind in ('sensitive_scope', 'restricted_scope', 'app_review') and not requested <= approved:
        standing, blockers = 'blocked', ['approved_scopes_do_not_cover_request']
    elif expires is not None and expires <= now:
        standing, blockers = 'blocked', ['approval_expired']
    elif envelope['freshness'] != 'fresh':
        standing, blockers = 'stale', ['applicability_not_rechecked' if envelope['freshness'] == 'stale' else 'evidence_time_' + (envelope['reason'] or 'unknown')]
    else:
        standing = 'satisfied'
    return {'kind': kind, 'status': status, 'standing': standing, 'blockers': blockers,
            'requestedScopes': sorted(requested), 'approvedScopes': sorted(approved), 'missingScopes': sorted(requested - approved) if status == 'approved' else [],
            'requestedAt': _iso(_epoch(requirement.get('requestedAt'))), 'decidedAt': _iso(_epoch(requirement.get('decidedAt'))),
            'expiresAt': _iso(expires), 'providerReceiptRef': ref, 'verifiedBy': requirement.get('verifiedBy') if isinstance(requirement.get('verifiedBy'), str) else None,
            'freshness': envelope, 'ownerLane': requirement.get('ownerLane') or 'provider_app_owner',
            'nextAction': None if standing == 'satisfied' else {'kind': 'record_provider_evidence', 'label': NEXT_ACTIONS[kind], 'requiresHuman': True},
            'revision': int(requirement.get('revision') or 0)}


def evaluate_registry(entries, now):
    """Per app: requirement rows and a readiness that is 'ready' only when every requirement is satisfied by fresh evidence.
    Separate apps never merge (a Google sign-in brand approval says nothing about a YouTube or Gmail client)."""
    out = []
    for entry in entries:
        rows = [evaluate_requirement(req, now, environment=entry['environment']) for req in entry['requirements']]
        standings = {row['standing'] for row in rows}
        readiness = 'ready' if rows and standings == {'satisfied'} else 'blocked' if 'blocked' in standings else 'check_required' if 'check_required' in standings else 'pending' if 'pending' in standings else 'stale'
        out.append({key: entry[key] for key in ('provider', 'appRef', 'environment', 'product', 'lane', 'launchScope')}
                   | {'readiness': readiness, 'requirements': rows, 'unsatisfied': sorted(row['kind'] for row in rows if row['standing'] != 'satisfied')})
    return out


# ---- attention items ----------------------------------------------------------------------------------------------------------
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
NO_TENANT_IMPACT = ('launch_scope', 'launch_blocker')   # future eligibility gaps, not current customer impact


def count(value, state):
    """One impact dimension; an unobservable count is None/'unknown', never 0."""
    if state not in COUNT_STATES:
        raise ValueError('invalid count state')
    return {'value': None if state == 'unknown' else int(value), 'countState': state}


UNKNOWN = {'value': None, 'countState': 'unknown'}


def _owner(lane, assignee=None):
    return {'lane': lane, 'assigneeRef': assignee, 'assignmentState': 'assigned' if assignee else 'unassigned', 'label': None if assignee else UNASSIGNED}


def item(*, category, priority, environment, title, reason, summary, owner_lane, next_action, envelope, first_seen=None, last_observed=None,
         provider=None, app_ref=None, operation=None, users=UNKNOWN, tenants=UNKNOWN, connections=UNKNOWN, jobs=UNKNOWN, tenant_keys=None,
         state='open', launch_blocker=False, evidence_refs=(), incident_ref=None, follow_up_ref=None, revision=0, as_of=None):
    if priority not in PRIORITIES or state not in ITEM_STATES:
        raise ValueError('invalid attention item')
    dedupe = ':'.join(str(part) for part in (environment, category, provider or '-', app_ref or '-', operation or '-', reason, incident_ref or '-'))
    return {'id': 'att_' + hashlib.sha256(dedupe.encode()).hexdigest()[:20], 'episodeKey': dedupe, 'dedupeKey': dedupe,
            'category': category, 'severity': priority, 'priority': priority, 'state': state, 'launchBlocker': bool(launch_blocker),
            'provider': provider, 'appRef': app_ref, 'environment': environment, 'operation': operation,
            'title': title, 'safeReasonCode': reason, 'summary': summary,
            'affected': {'users': users, 'tenants': tenants, 'connections': connections, 'jobs': jobs, 'asOf': as_of or envelope.get('observedAt'), 'coverage': envelope.get('coverage')},
            'owner': _owner(owner_lane), 'nextAction': next_action,
            'firstSeenAt': _iso(_epoch(first_seen)) or envelope.get('observedAt'), 'lastObservedAt': _iso(_epoch(last_observed)) or envelope.get('observedAt'),
            'lastCheckedAt': envelope.get('lastCheckedAt'), 'freshness': envelope, 'evidenceRefs': list(evidence_refs),
            'incidentRef': incident_ref, 'followUpRef': follow_up_ref, 'revision': int(revision), '_tenantKeys': tenant_keys}


def _impact(entry):
    affected = entry['affected']
    for key in ('tenants', 'jobs', 'connections', 'users'):
        if affected[key]['countState'] != 'unknown':
            return affected[key]['value'] or 0
    return 0


def queue(items, limit=MAX_ITEMS):
    """Deterministic order: priority, launch blockers first, larger observed impact, oldest first seen. Blocked or acknowledged
    items stay visible. The summary is a union of distinct tenants, never a sum of item counts."""
    ordered = sorted(items, key=lambda entry: (PRIORITY_RANK[entry['priority']], not entry['launchBlocker'], -_impact(entry),
                                               entry['firstSeenAt'] or '9999', entry['id']))
    tenants, partial = set(), False
    for entry in ordered:
        keys, state = entry.get('_tenantKeys'), entry['affected']['tenants']['countState']
        if keys is not None:
            tenants |= set(keys)
            partial = partial or state == 'lower_bound'
        elif entry['category'] not in NO_TENANT_IMPACT:
            partial = True                       # impact without tenant identities (or unobserved): the union is only a lower bound
    public = [{key: value for key, value in entry.items() if not key.startswith('_')} for entry in ordered[:limit]]
    by_priority = {name: sum(1 for entry in ordered if entry['priority'] == name) for name in PRIORITIES}
    return {'items': public, 'truncated': len(ordered) > limit, 'total': len(ordered), 'byPriority': by_priority,
            'summary': {'tenants': {'value': len(tenants), 'countState': 'lower_bound' if partial else 'exact'},
                        'users': UNKNOWN, 'unassigned': sum(1 for entry in ordered if entry['owner']['assignmentState'] == 'unassigned'),
                        'launchBlockers': sum(1 for entry in ordered if entry['launchBlocker'])}}


# ---- sources: connection health projection -------------------------------------------------------------------------------------
CONNECTION_ATTENTION = {
    'reauthorization_required': ('reconnect_required', 'P2', 'Connections need the account holder to reconnect'),
    'token_expired': ('reconnect_required', 'P2', 'Connection grants expired and cannot refresh'),
    'client_binding_missing': ('reconnect_required', 'P2', 'Connections need new consent for the current client'),
    'scope_missing': ('scope_missing', 'P2', 'Connections are missing a required permission'),
    'identity_known': ('identity_unverified', 'P2', 'Connected accounts have no verified identity'),
}
RECONNECT_ACTION = {'kind': 'request_account_holder_reconnect', 'label': 'Ask the account holder to reconnect through the normal Channels flow. Founder cannot consent for them.',
                    'targetRef': None, 'requiresHuman': True, 'blockedBy': ['account_holder_consent']}
COVERAGE_SQL = f'SELECT max(h."refreshedAt") AS latest, count(*) AS total FROM {CONNECTION_VIEW} h WHERE {excluded(H_WORKSPACE)}'
ATTENTION_SQL = (f'SELECT h."workspaceId" AS wid, h."connectionId" AS cid, h.provider, h."connectionState" AS cstate, h."refreshedAt" AS at FROM {CONNECTION_VIEW} h '
                 f'WHERE h."connectionState" = ANY(%s) AND {excluded(H_WORKSPACE)} '
                 'ORDER BY h.provider, h."connectionState", h."workspaceId", h."connectionId" LIMIT %s')


def connection_items(rows, coverage, now, environment, *, truncated=False):
    """Items per (provider, connection state) from projection rows (customer workspaces only). Tenants and connections are exact
    distinct counts (lower bounds when the read was truncated); users and jobs are not in the projection, so they are unknown."""
    latest = (coverage or {}).get('latest')
    envelope = freshness(now=now, observed_at=latest, stale_after=CONNECTION_STALE_SECONDS, cadence=CONNECTION_CADENCE_SECONDS,
                         source=CONNECTION_VIEW, coverage='partial' if truncated else 'complete')
    groups = {}
    for row in rows:
        if row.get('cstate') in CONNECTION_ATTENTION:
            group = groups.setdefault((row.get('provider') or 'unknown', row['cstate']), {'tenants': set(), 'connections': set(), 'first': None})
            group['tenants'].add(row['wid'])
            group['connections'].add((row['wid'], row['cid']))
    state = 'lower_bound' if truncated else 'exact'
    out = []
    for (provider, cstate), group in sorted(groups.items()):
        category, priority, title = CONNECTION_ATTENTION[cstate]
        out.append(item(category=category, priority=priority, environment=environment, provider=provider, operation='identity', title=title,
                        reason=cstate, summary=f'{len(group["connections"])} {provider} connection(s) in {len(group["tenants"])} workspace(s) report {cstate.replace("_", " ")}.',
                        owner_lane='connections', next_action=RECONNECT_ACTION, envelope=envelope,
                        tenants=count(len(group['tenants']), state), connections=count(len(group['connections']), state), tenant_keys=sorted(group['tenants'])))
    if envelope['freshness'] != 'fresh':
        out.append(item(category='stale_telemetry', priority='P3', environment=environment, title='Connection health is not current',
                        reason='connection_health_' + (envelope['reason'] or envelope['freshness']),
                        summary='The hourly connection projection is stale or unobserved. Reconnect counts are last-known values, not live state.',
                        owner_lane='ops', envelope=envelope,
                        next_action={'kind': 'restore_observation', 'label': 'Check the connection_health cron stage and its source table.', 'targetRef': 'cron:connection_health',
                                     'requiresHuman': False, 'blockedBy': []}))
    return out, envelope


def read_connection_health(service, now, environment):
    """(items, envelope, sourceState) through the restricted reader. A missing projection is source_not_configured: one P3 item
    with unknown impact, never an empty 'all clear'."""
    coverage = live_metrics.execute(service, MetricStatement('connections_attention:coverage', COVERAGE_SQL), (), limit=1)
    if coverage is None:
        envelope = freshness(now=now, observed_at=None, stale_after=CONNECTION_STALE_SECONDS, cadence=CONNECTION_CADENCE_SECONDS, source=CONNECTION_VIEW)
        return [item(category='stale_telemetry', priority='P3', environment=environment, title='Connection health is not observed', reason='connection_health_source_not_configured',
                     summary='The connection projection is not installed or not readable. Affected connections are unknown.', owner_lane='ops', envelope=envelope,
                     next_action={'kind': 'restore_observation', 'label': 'Install or grant the connection health projection (migration 066).', 'targetRef': CONNECTION_VIEW,
                                  'requiresHuman': True, 'blockedBy': ['operator_configuration']})], envelope, 'source_not_configured'
    coverage = coverage[0] if coverage else {}
    rows = live_metrics.execute(service, MetricStatement('connections_attention:rows', ATTENTION_SQL), (sorted(CONNECTION_ATTENTION), MAX_CONNECTION_ROWS + 1),
                                limit=MAX_CONNECTION_ROWS + 1) or []
    truncated = len(rows) > MAX_CONNECTION_ROWS
    items, envelope = connection_items(rows[:MAX_CONNECTION_ROWS], coverage, now, environment, truncated=truncated)
    return items, envelope, 'not_instrumented' if not coverage.get('latest') else 'connected'


# ---- sources: founder incidents --------------------------------------------------------------------------------------------------
INCIDENT_ATTENTION = {   # detector -> (category, priority when critical, priority when warning, owner lane, next action label)
    'publish_failure_rate': ('publishing', 'P1', 'P1', 'publishing',
                             'Inspect the exact failed and uncertain jobs and their provider receipts. Never retry a post whose outcome is unknown.'),
    'source_silence': ('stale_telemetry', 'P1', 'P3', 'ops', 'Restore the silent source; its metrics are last-known values until it reports again.'),
    'cost_anomaly': ('budget', 'P1', 'P3', 'billing', 'Review reservations and settlements in the AI ledger; readers cannot raise a budget.'),
    'payment_failure_spike': ('billing', 'P1', 'P3', 'billing', 'Review the failed payments with the billing owner.'),
}
INCIDENT_STATES = {'open': 'open', 'acknowledged': 'acknowledged', 'investigating': 'action_pending', 'mitigated': 'action_pending'}


def incident_items(rows, now, environment):
    out = []
    for row in rows:
        spec, state = INCIDENT_ATTENTION.get(row.get('detector')), INCIDENT_STATES.get(row.get('state'))
        if spec is None or state is None:
            continue
        category, critical, warning, lane, label = spec
        opened = _epoch(row.get('opened_at'))
        envelope = freshness(now=now, observed_at=opened, stale_after=None, source='rafii_control.founder_incidents', value=row.get('severity'))
        envelope.update(freshness='not_applicable', reason='episode_record')   # an episode record, not a periodic observation
        affected = int(row.get('affected_count') or 0)
        out.append(item(category=category, priority=critical if row.get('severity') == 'critical' else warning, environment=environment,
                        title=f"{row['detector'].replace('_', ' ').capitalize()} · {str(row.get('scope') or 'global').replace('_', ' ')}", reason=row['detector'],
                        summary='Open founder incident. Impact counts are the detector evidence, not distinct customers.', owner_lane=lane, envelope=envelope,
                        jobs=count(affected, 'estimated') if row['detector'] == 'publish_failure_rate' else UNKNOWN,
                        state=state, first_seen=opened, incident_ref=row['id'], revision=row.get('version') or 0,
                        next_action={'kind': 'review_incident', 'label': label, 'targetRef': '/founder/operations?incident=' + str(row['id']),
                                     'requiresHuman': True, 'blockedBy': []}))
    return out


# ---- sources: approval registry -----------------------------------------------------------------------------------------------
def registry_items(evaluated, now, environment):
    out = []
    in_scope = [app for app in evaluated if app['launchScope']]
    if not in_scope:
        envelope = freshness(now=now, observed_at=None, stale_after=REGISTRY_STALE_SECONDS, source='founder_connections.LAUNCH_SCOPE')
        out.append(item(category='launch_scope', priority='P3', environment=environment, title='No launch provider scope is recorded', reason='launch_scope_not_recorded',
                        summary='Approval gaps cannot be ranked as launch blockers until the first launch provider and operation are chosen.', owner_lane='coordinator',
                        envelope=envelope, next_action={'kind': 'record_launch_scope', 'label': 'Choose and record the first launch provider, operation and account type.',
                                                        'targetRef': None, 'requiresHuman': True, 'blockedBy': ['owner_decision']}))
    for app in in_scope:
        if app['readiness'] == 'ready':
            continue
        missing = [row for row in app['requirements'] if row['standing'] != 'satisfied']
        checked = [row['freshness'] for row in missing if row['freshness']['observedAt']]
        envelope = checked[0] if checked else freshness(now=now, observed_at=None, stale_after=REGISTRY_STALE_SECONDS, source='founder_connections.RECORDED_DECISIONS')
        out.append(item(category='launch_blocker', priority='P2', environment=environment, provider=app['provider'], app_ref=app['appRef'], operation=app['product'],
                        title=f"{app['provider']} approval evidence is incomplete", reason='approval_' + app['readiness'],
                        summary='Unsatisfied requirements: ' + ', '.join(row['kind'] for row in missing) + '.', owner_lane='provider_app_owner', envelope=envelope,
                        launch_blocker=True, evidence_refs=[row['providerReceiptRef'] for row in app['requirements'] if row['providerReceiptRef']],
                        next_action={'kind': 'record_provider_evidence', 'label': missing[0]['nextAction']['label'], 'targetRef': f"registry:{app['provider']}:{app['appRef']}",
                                     'requiresHuman': True, 'blockedBy': sorted({blocker for row in missing for blocker in row['blockers']})}))
    return out


# ---- route --------------------------------------------------------------------------------------------------------------------
def build(*, connection_source, incident_source, registry, now, environment):
    """Assemble the response from already-read sources (pure; the route and the Demo fixture share it)."""
    conn_items, conn_envelope, conn_state = connection_source
    incidents, incident_state = incident_source
    if incident_state != 'connected':
        envelope = freshness(now=now, observed_at=None, stale_after=None, source='rafii_control.founder_incidents')
        incidents = [item(category='stale_telemetry', priority='P3', environment=environment, title='Founder incidents are not readable', reason='incidents_' + incident_state,
                          summary='Open incidents could not be read; their impact is unknown, not zero.', owner_lane='ops', envelope=envelope,
                          next_action={'kind': 'restore_observation', 'label': 'Check the founder incident store (migration 055).', 'targetRef': 'rafii_control.founder_incidents',
                                       'requiresHuman': True, 'blockedBy': []})]
    evaluated = evaluate_registry(registry, now)
    result = queue(conn_items + incidents + registry_items(evaluated, now, environment))
    return {'asOf': _iso(now), 'environment': environment, **result, 'registry': evaluated, 'registryVersion': REGISTRY_VERSION,
            'sources': {'connectionHealth': {'state': conn_state, 'freshness': conn_envelope}, 'incidents': {'state': incident_state}},
            'liveVerified': False, 'limits': ['Connection health is the hourly projection, not live token validity.',
                                              'Users are not in the projection, so user impact is unknown.',
                                              'Approval rows are code-reviewed evidence references, not a console readback.']}


def attention(app, principal, request):
    """GET /connections/attention?mode= (control.read): the prioritised attention queue and the approval registry. Read-only.
    Demo answers with the shared synthetic fixture and says so."""
    now = float(request['now'])
    if request['mode'] == 'demo':
        return {**demo(now), 'mode': 'demo', '_dataState': 'synthetic'}
    environment = getattr(getattr(getattr(app, 'boundary', None), 'config', None), 'environment', None) or 'unknown'
    connection_source = read_connection_health(app.queries, now, environment)
    try:
        incidents = app.founder_store().open_incidents()
        incident_source = (incident_items(incidents, now, environment), 'connected')
    except Exception:   # noqa: BLE001 - a missing incident store (055) is a visible unknown, not a failed queue
        incident_source = ([], 'unavailable')
    return {**build(connection_source=connection_source, incident_source=incident_source, registry=registry_entries(), now=now, environment=environment),
            'mode': 'live', '_dataState': 'live'}


def demo(now):
    """Synthetic, deterministic: two workspaces with reconnect-required connections (one shared), one acknowledged publishing
    incident and the real (all-unknown) registry. Never mixed with Live."""
    rows = [{'wid': 'demo-w1', 'cid': 'c1', 'provider': 'linkedin', 'cstate': 'token_expired'},
            {'wid': 'demo-w1', 'cid': 'c2', 'provider': 'linkedin', 'cstate': 'token_expired'},
            {'wid': 'demo-w2', 'cid': 'c3', 'provider': 'youtube', 'cstate': 'scope_missing'}]
    conn_items, envelope = connection_items(rows, {'latest': now - 600}, now, 'demo')
    incidents = incident_items([{'id': 'demo-incident', 'detector': 'publish_failure_rate', 'scope': 'global', 'severity': 'warning', 'state': 'acknowledged',
                                 'opened_at': now - 1800, 'affected_count': 3, 'version': 2}], now, 'demo')
    return build(connection_source=(conn_items, envelope, 'connected'), incident_source=(incidents, 'connected'), registry=registry_entries(), now=now, environment='demo')


http.register_route('GET', r'/connections/attention', 'control.read', 'founder_connections', 'attention', demo_ok=True)
