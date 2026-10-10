"""A bounded native projection of existing opportunities, never a new producer.

No retrieval, model, scheduler or new store. Decisions use each source's existing
records. Navigation only opens a review; only campaign actions create agent tasks.
"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import quote

from postriff_alpha.domain import AlphaError
from .. import insights, research, suggestions
from ..contracts import digest
from ..coworker import attention, flags, listening, performance
from ..hosted import audit
from ..notifications import store as notices
from ..permissions import require
from . import creator_pipeline

VERSION = 'opportunity-feed/1'
LIMIT = 50


def _href(path):
    """Only native destinations used by these existing source adapters."""
    if not isinstance(path, str) or not re.fullmatch(r'/app/(?:queue|channels|automations|weekly|analytics|library|ideas|account|tasks|workspace/personalization)(?:\?[A-Za-z0-9_=:%&.-]+)?', path):
        return '/app/weekly'
    return path


def _item(family, ident, title, reason, *, source, action, state='open', priority=80, at=None, expires=None, evidence=None, benefit=None, dismissal='workspace', **extra):
    value = {'id': family + ':' + ident, 'family': family, 'sourceId': ident, 'title': str(title)[:250], 'reason': str(reason)[:700],
             'source': source, 'state': state, 'priority': priority, 'observedAt': at, 'expiresAt': expires, 'evidence': evidence or [],
             'action': action, 'dismissalScope': dismissal, 'expectedBenefit': {'kind': 'estimate', 'text': benefit or 'Review may resolve this specific issue. No improvement has been measured.'},
             'cost': {'state': 'no_provider_call', 'text': 'Opening or dismissing this item makes no model or provider call. Any later paid work needs its own approval.'}, **extra}
    value['digest'] = digest(value)
    return value


def _suggestions(state, now, tasks):
    result = []
    for raw in ((state.get('raffi') or {}).get('suggestions') or [])[-100:]:
        try:
            item = suggestions.current(state, raw['id'], now)
        except AlphaError:
            continue
        evidence = item['evidence'][0]
        task = tasks.get(item['id'])
        supported = item['kind'] in ('campaign_gap', 'upcoming_event')
        if supported:
            try:
                creator_pipeline.plan(state, state['workspace']['id'], {'suggestionId': item['id'], 'platforms': ['Threads'], 'budgetCeilingUsdMicro': 0}, now)
            except AlphaError:
                supported = False
        if task:
            action = {'kind': 'open', 'label': 'Inspect existing task', 'href': '/app/tasks?task=' + task['taskId']}
        elif supported:
            action = {'kind': 'prepare_task', 'label': 'Review draft task', 'suggestionId': item['id']}
        else:
            target = '/app/library' if evidence['type'] == 'asset' else '/app/automations' if evidence['type'] == 'campaign' else '/app/queue?job=' + quote(evidence['id'], safe='') if evidence['type'] == 'job' else '/app/ideas'
            action = {'kind': 'open', 'label': 'Open asset for review' if evidence['type'] == 'asset' else 'Open for review', 'href': target}
        result.append(_item('suggestion', item['id'], item['kind'].replace('_', ' ').capitalize(), item['reason'],
            source='Current workspace activity', action=action, at=item.get('createdAt'), evidence=item['evidence'],
            state=task['state'] if task else item['status'], priority=50, task=task,
            permissions=['Workspace edit', 'Current source and agent grants for draft tasks'],
            preview='Review the complete source facts and spending ceiling before saving a task.' if supported else 'The existing native editor opens. An asset name is not asset content.'))
    return result


def _attention(cur, wid, principal, member, state, now):
    # Only actual personal deliveries can offer personal dismissal. No notification
    # is generated merely to fill the feed; account/founder-wide rows are excluded.
    if not flags.enabled('RAFII_NOTIFICATIONS_V2_ENABLED'):
        return []
    current = {i['id']: i for i in attention.build(cur, wid, principal, member, state, now)['items']}
    cur.execute("SELECT d.id::text,e.dedupe_key,extract(epoch from e.occurred_at),d.status FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id "
                "WHERE e.workspace_id=%s AND d.workspace_id=%s AND d.user_id=%s AND d.channel='in_app' AND d.status IN ('delivered','read','acted','dismissed') ORDER BY d.created_at DESC LIMIT 60", (wid, wid, principal))
    out = []
    for delivery, key, at, status in cur.fetchall():
        item = current.get(key)
        if not item or item['type'] == 'opportunity.detected':
            continue
        out.append(_item('attention', delivery, item['title'], item['why'], source='Current workflow and your in-app notifications',
            action={'kind': 'open', 'label': 'Open current issue', 'href': _href(item['href'])}, at=float(at) if at else None,
            evidence=[item['evidence']], priority=item['priority'], state='dismissed' if status == 'dismissed' else 'open', dismissal='person', permissions=['Current role permission for this workflow'],
            preview='Opening this issue does not retry publishing or change a connection.'))
    return out


def _listening(state, now):
    if not flags.enabled('RAFII_LISTENING_ENABLED') or not research.allowed(state):
        return []
    out = []
    for item in listening.view(state, now)['opportunities'][:50]:
        if item['status'] not in ('open', 'watching') or item.get('expiresAt', 0) <= now or item.get('actionType') == 'skip':
            continue
        # Complex scout/trend dependencies remain in their original current-source
        # panel. This projection never copies their evidence or execution plans.
        if item.get('version') == 'scout.v1.2':
            continue
        out.append(_item('listening', item['id'], item['title'], item['why'], source='Consented public-web listening lead',
            action={'kind': 'open', 'label': 'Review source and plan', 'href': '/app/weekly?tab=opportunities'},
            at=item.get('createdAt'), expires=item.get('expiresAt'), state=item['status'],
            evidence=[{'type': 'public_web', 'url': str(e.get('url') or '')[:2000]} for e in item.get('evidence', [])[:3]],
            confidence=item.get('confidence'), permissions=['Workspace edit', 'Current web-research consent'],
            preview='A search lead needs source review. Opening it neither drafts content nor verifies its claims.'))
    return out


def _performance(cur, wid, member, state, now):
    if not flags.enabled('RAFII_PERFORMANCE_LEARNING_ENABLED'):
        return []
    # Current account and Direct analytics authority, followed by the original
    # like-for-like observation/hypothesis functions. Stored prose alone is not evidence.
    cur.execute("SELECT connection_id FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability='analytics' AND level='Direct'", (wid,))
    direct = {r[0] for r in cur.fetchall()}
    connected = {c['id'] for c in state.get('phase2', {}).get('channels', []) if not c.get('revoked')}
    scoped = {**state, 'phase2': {**state.get('phase2', {}), 'jobs': [j for j in state.get('phase2', {}).get('jobs', [])
        if j.get('manifest', {}).get('channelId') in direct & connected]}}
    rows = [r for r in performance.observations(cur, wid, scoped, now) if r.get('readOffset') == insights.COMPARISON_BASIS]
    fresh = performance.hypotheses_from(rows, now)
    cur.execute("SELECT id::text,dimension,cohort,metric,revision,status,experiment,extract(epoch from expires_at),statement,sample_a,sample_b,effect,evidence_ids,counter_evidence_ids,arm_a,arm_b FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND status IN ('candidate','experiment','supported') AND expires_at>to_timestamp(%s) ORDER BY created_at DESC LIMIT 50", (wid, now))
    out = []
    for ident, dimension, cohort, metric, revision, status, experiment, expires, statement, sample_a, sample_b, effect, evidence_ids, counter_ids, arm_a, arm_b in cur.fetchall():
        basis = next((h for h in fresh if h['dimension'] == dimension and h['cohort'] == cohort and h['metric'] == metric), None)
        if (basis is None or statement != basis['statement'] or (sample_a, sample_b) != (basis['sample_a'], basis['sample_b'])
                or (arm_a, arm_b) != (basis['arm_a'], basis['arm_b'])
                or effect is None or round(float(effect), 3) != basis['effect']
                or set(evidence_ids) != set(basis['evidence_ids']) or set(counter_ids) != set(basis['counter_evidence_ids'])):
            continue
        account = next(c for c in state['phase2']['channels'] if c['id'] == cohort['connectionId'])
        comparison = {'accountId': account['id'], 'accountLabel': str(account.get('account') or account['id'])[:250],
                      'provider': cohort.get('provider'), 'language': cohort.get('language'), 'contentTypeId': cohort.get('contentTypeId'),
                      'dimension': dimension, 'armA': arm_a, 'armB': arm_b}
        action = {'kind': 'experiment', 'label': 'Define comparison experiment'} if member.role == 'owner' and status == 'candidate' else {'kind': 'open', 'label': 'Review performance experiment', 'href': '/app/workspace/personalization'}
        out.append(_item('performance', ident, basis['statement'], 'Comparable native observations support a hypothesis, not a causal claim.',
            source='Authorized account performance', action=action, at=basis['date_to'], expires=float(expires), state=status, priority=65,
            evidence=[{'type': 'job', 'id': key} for key in basis['evidence_ids']],
            measurement={'kind': 'observed', 'metric': metric, 'definitionVersion': cohort.get('definitionVersion'), 'window': insights.COMPARISON_BASIS,
                         'dateRange': [basis['date_from'], basis['date_to']], 'samples': {'a': basis['sample_a'], 'b': basis['sample_b']},
                         'counterEvidenceIds': basis['counter_evidence_ids'], 'causal': False, 'comparison': comparison}, revision=revision, experiment=experiment,
            permissions=['Owner permission to define or dismiss a strategy experiment', 'Current Direct analytics permission'],
            canDismiss=member.role == 'owner', preview='Alternate the two arms for the next comparable posts, then compare the same native metric and reading window. No content is generated or published.'))
    return out


def _project(runtime, cur, wid, principal, member, state):
    now = runtime.clock()
    cur.execute("SELECT t.id::text,t.state,r.usage->'creatorPipeline'->>'suggestionId' FROM public.pr_agent_tasks t JOIN public.pr_agent_runs r ON r.id=t.id AND r.workspace_id=t.workspace_id WHERE t.workspace_id=%s AND t.created_by=%s AND r.usage->'creatorPipeline'->>'version'=%s ORDER BY t.created_at DESC LIMIT 100", (wid, principal, creator_pipeline.VERSION))
    tasks = {}
    for task, status, suggestion in cur.fetchall():
        if suggestion not in tasks:
            tasks[suggestion] = {'taskId': task, 'state': status}
    groups = (_suggestions(state, now, tasks), _attention(cur, wid, principal, member, state, now), _listening(state, now), _performance(cur, wid, member, state, now))
    items = [item for group in groups for item in group]
    items.sort(key=lambda i: (i['priority'], i['id']))
    # A held-job suggestion and a personal workflow issue should not repeat the
    # same action. Prefer the existing attention item and its personal dismissal.
    attention_jobs = {e.get('entityId') for i in items if i['family'] == 'attention' for e in i['evidence'] if e.get('entityType') == 'job'}
    items = [i for i in items if i['state'] != 'dismissed' and not (i['family'] == 'suggestion' and any(e.get('type') == 'job' and e.get('id') in attention_jobs for e in i['evidence']))]
    return {'version': VERSION, 'workspaceId': wid, 'items': items[:LIMIT], 'hasMore': len(items) > LIMIT,
            'coverage': 'Current deterministic suggestions, your delivered workflow issues, consented listening leads and supported native performance hypotheses. Scout and trend plans remain in their source panel; missing or unpermitted evidence is withheld.',
            'sourceLinks': [{'label': 'Review listening and scout plans', 'href': '/app/weekly?tab=opportunities'}, {'label': 'Review analytics and outcomes', 'href': '/app/analytics'}]}


def listing(runtime, wid, token):
    with runtime.service.repository.transaction(token, wid) as (cur, row, principal):
        member = runtime.service.ideas._member(row)
        require(member, 'edit')
        creator_pipeline._enabled(runtime, wid)
        return _project(runtime, cur, wid, principal, member, runtime.service.ideas._state(row))


def refresh(runtime, wid, token):
    service = runtime.service
    with service.repository.transaction(token, wid) as (cur, row, principal):
        require(service.ideas._member(row), 'edit')
        creator_pipeline._enabled(runtime, wid)
        state = copy.deepcopy(service.ideas._state(row))
        suggestions.refresh(state, runtime.clock())
        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), wid))
        audit(cur, wid, principal, 'opportunity.suggestions_refreshed', '', {})
    return listing(runtime, wid, token)


def decide(runtime, wid, token, payload):
    if not isinstance(payload, dict) or payload.get('decision') not in ('dismiss', 'experiment') or not isinstance(payload.get('id'), str):
        raise AlphaError('Choose a current opportunity decision.', 400)
    service = runtime.service
    with service.repository.transaction(token, wid) as (cur, row, principal):
        member = service.ideas._member(row)
        require(member, 'edit')
        creator_pipeline._enabled(runtime, wid)
        state = copy.deepcopy(service.ideas._state(row))
        item = next((i for i in _project(runtime, cur, wid, principal, member, state)['items'] if i['id'] == payload['id']), None)
        if item is None:
            raise AlphaError('Opportunity unavailable or already decided. Refresh the feed.', 404)
        if payload.get('digest') != item['digest']:
            raise AlphaError('This opportunity changed. Review its current evidence.', 409, code='opportunity_stale')
        family, ident = item['family'], item['sourceId']
        if payload['decision'] == 'experiment' and (family != 'performance' or item['action']['kind'] != 'experiment'):
            raise AlphaError('This source does not support an experiment action.', 409)
        decision = 'experiment' if payload['decision'] == 'experiment' else 'dismissed'
        if family == 'performance':
            require(member, 'owner')
            # Same durable hypothesis/experiment contract as hypothesis_decide.
            # The workspace lock plus current evidence above bind this exact review.
            experiment = {'startedAt': runtime.clock(), 'design': 'alternate the two arms for the next comparable posts',
                          'measurementWindow': item['measurement']['window'], 'metric': item['measurement']['metric'],
                          'definitionVersion': item['measurement']['definitionVersion'], 'comparison': item['measurement']['comparison'], 'sourceDigest': item['digest'], 'outcome': 'unmeasured'}
            cur.execute("UPDATE public.pr_strategy_hypotheses SET status=%s,decided_by=%s,decided_at=now(),experiment=CASE WHEN %s='experiment' THEN %s::jsonb ELSE experiment END WHERE workspace_id=%s AND id::text=%s AND revision=%s AND status=%s RETURNING id", (decision, principal, decision, json.dumps(experiment), wid, ident, item['revision'], item['state']))
            if cur.fetchone() is None:
                raise AlphaError('This hypothesis changed. Refresh the feed.', 409)
        elif family == 'attention':
            if not notices.mark(cur, principal, ident, 'dismissed')['verified']:
                raise AlphaError('The notification could not be dismissed.', 409)
        else:
            if family == 'suggestion':
                suggestions.apply_action(state, 'raffi_suggestion_dismiss', {'suggestionId': ident}, principal, runtime.clock())
            elif family == 'listening':
                listening.decide(state, ident, 'dismiss', principal, runtime.clock())
            else:
                raise AlphaError('This source has no dismissal adapter.', 409)
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), wid))
        audit(cur, wid, principal, 'opportunity.' + decision, ident, {'family': family, 'sourceDigest': item['digest']})
        return {'workspaceId': wid, 'id': item['id'], 'state': decision, 'verified': True,
                'href': '/app/workspace/personalization' if decision == 'experiment' else None,
                'note': 'Experiment defined; outcomes are unmeasured and no content was generated.' if decision == 'experiment' else 'Dismissed in its existing source record.'}
