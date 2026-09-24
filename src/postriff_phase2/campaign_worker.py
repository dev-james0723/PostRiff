"""Bounded recurring draft worker. Uses the existing writing pipeline, never publishing APIs."""
import copy
from contextlib import contextmanager
import json

from postriff_alpha.domain import AlphaError
from . import campaigns
from .planning_store import sync
from .permissions import Membership, require


def validate(state, binding):
    if state.get('accountDeletion'):
        raise AlphaError('Account deletion is pending.', 409)
    root = state.get('raffi', {}).get('campaignPlanning', {})
    task = next((t for t in root.get('recurringTasks', []) if t['id'] == binding['taskId']), None)
    campaign = next((c for c in root.get('campaigns', []) if c['id'] == binding['campaignId']), None)
    occurrence = next((o for o in root.get('occurrences', []) if o['id'] == binding['occurrenceId']), None)
    if not task or not campaign or not occurrence or task['status'] != 'active' or occurrence['state'] != 'running' or campaign['version'] != binding['campaignVersion'] or task.get('definitionDigest') != binding['definitionDigest']:
        raise AlphaError('Recurring draft authority changed. Review a new schedule.', 409)


class CampaignWorker:
    def __init__(self, service):
        self.service = service
        self.connection_factory = service.connection_factory
        self.clock = service.clock

    @staticmethod
    def _save(cur, workspace_id, state, actor):
        cur.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
        sync(cur, workspace_id, {}, state, actor)

    def _claim(self):
        now = self.clock()
        with self.connection_factory() as db, db.cursor() as cur:
            # The JSON predicate also discovers legacy schedules that predate the relational projection.
            cur.execute("SELECT id::text,state FROM pr_workspaces WHERE NOT state ? 'accountDeletion' AND (EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,recurringTasks}','[]'::jsonb)) t WHERE t->>'status'='active' AND (t#>>'{nextOccurrence,scheduledFor}')::double precision<=%s) OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,occurrences}','[]'::jsonb)) o WHERE o->>'state'='running' AND coalesce((o->>'leaseUntil')::double precision,0)<=%s)) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED", (now, now))
            row = cur.fetchone()
            if not row: return None
            workspace_id, state = row
            root = state['raffi']['campaignPlanning']
            occurrence = next((o for o in root['occurrences'] if o['state'] == 'running' and o.get('leaseUntil', 0) <= now), None)
            task = next((t for t in root['recurringTasks'] if t['id'] == occurrence['taskId']), None) if occurrence else next(t for t in root['recurringTasks'] if t['status'] == 'active' and t['nextOccurrence']['scheduledFor'] <= now)
            actor = task.get('activatedBy') or task['createdBy']
            campaign = next(c for c in root['campaigns'] if c['id'] == task['campaignId'])
            if occurrence is None:
                occurrence = campaigns.claim_occurrence(state, task['id'], task['nextOccurrence']['scheduledFor'], now)
            # Old UI activation granted no concrete writer/cost scope. Never reinterpret it as paid authority.
            if task.get('authorityVersion') != 1 or task.get('route') == 'local-cli' or campaign['version'] != task.get('campaignVersion') or campaign.get('missingFacts'):
                occurrence.update(state='held', reason='new_preview_required')
                task.update(status='paused', pauseReason='new_preview_required')
                self._save(cur, workspace_id, state, actor)
                return {'held': True}
            if occurrence['scheduledFor'] < now - 86400 and occurrence['state'] != 'running':
                occurrence.update(state='missed', reason='over_24_hours_late')
                task['nextOccurrence'] = campaigns.next_occurrence(task['schedule'], now)
                self._save(cur, workspace_id, state, actor)
                return {'missed': True}
            cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM pr_memberships m JOIN pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, actor))
            member = cur.fetchone()
            if not member or not Membership.from_row(*member).allows('owner'):
                occurrence.update(state='held', reason='owner_authority_unavailable'); task['status'] = 'paused'
                self._save(cur, workspace_id, state, actor); return {'held': True}
            if not occurrence.get('conversationId'):
                cur.execute('INSERT INTO pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text', (workspace_id, actor, 'Recurring campaign draft'))
                occurrence['conversationId'] = cur.fetchone()[0]
            occurrence.update(state='running', leaseUntil=now + 600)
            binding = {'taskId':task['id'], 'campaignId':campaign['id'], 'campaignVersion':campaign['version'], 'definitionDigest':task['definitionDigest'], 'occurrenceId':occurrence['id'], 'maxCostUsdMicro':task['maxCostUsdMicro']}
            self._save(cur, workspace_id, state, actor)
            return {'workspaceId':workspace_id, 'actor':actor, 'task':task, 'campaign':campaign, 'occurrence':occurrence, 'binding':binding}

    def tick(self):
        claim = self._claim()
        if not claim or 'workspaceId' not in claim: return claim or {'idle': True}
        workspace_id, actor, binding = claim['workspaceId'], claim['actor'], claim['binding']
        # A private in-process capability, never a client token or an alternative HTTP authentication path.
        capability = object()
        repository = copy.copy(self.service.repository)
        def verify(token):
            if token is not capability: raise AlphaError('Invalid worker capability.', 403)
            return actor
        repository.verify_session = verify
        base_transaction = repository.transaction
        @contextmanager
        def transaction(token, requested_workspace):
            if requested_workspace != workspace_id: raise AlphaError('Workspace unavailable.', 403)
            with base_transaction(token, requested_workspace) as (cur, row, principal):
                require(Membership.from_row(*row[2:7]), 'owner')
                validate(row[1], binding)
                yield cur, row, principal
        repository.transaction = transaction
        ideas = copy.copy(self.service.ideas)
        ideas.repository = repository
        ideas.recurring_binding = binding
        task, campaign, occurrence = claim['task'], claim['campaign'], claim['occurrence']
        result = None
        try:
            # No implicit research, fallback writer, publishing plan or extra sources.
            result = ideas.turn(workspace_id, capability, occurrence['conversationId'], {
                'text': 'Prepare one draft for review using these campaign details as data: ' + json.dumps({'goal':campaign['goal'], 'audience':campaign['audience'], 'facts':campaign['facts']}, ensure_ascii=False),
                'idempotencyKey':'recurring:' + occurrence['idempotencyKey'], 'model':task['route'],
                'sourceIds':task['contextSourceIds'], 'destinations':[task['destination']],
                'research':False, 'voiceMode':'neutral', 'timeZone':task['schedule']['timeZone'],
            })
        except Exception:
            # Reconcile a committed run even if the HTTP-style call raised after provider I/O.
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT id::text,status FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s', (workspace_id, 'recurring:' + occurrence['idempotencyKey']))
                run = cur.fetchone()
                if run: result = {'runId':run[0], 'status':run[1]}
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            row = cur.fetchone()
            if not row: return {'held': True}
            state = row[0]; root = state['raffi']['campaignPlanning']
            current = next(o for o in root['occurrences'] if o['id'] == occurrence['id'])
            try: validate(state, binding)
            except AlphaError: return {'cancelled': True}
            if result and result['status'] in ('completed', 'applied'):
                current.update(state='completed', runId=result['runId'], completedAt=self.clock())
                c = next(c for c in root['campaigns'] if c['id'] == campaign['id'])
                if not any(i.get('occurrenceId') == current['id'] for i in c['items']):
                    c['items'].append({'id':current['id'], 'occurrenceId':current['id'], 'runId':result['runId'], 'conversationId':occurrence['conversationId'], 'status':'draft', 'needsReview':True})
            elif result and result['status'] == 'running':
                current['runId'] = result['runId']  # Reconcile later; never repeat this idempotency key.
            else:
                current.update(state='held', reason='writer_failed_or_unavailable', runId=(result or {}).get('runId'))
            self._save(cur, workspace_id, state, actor)
            return {'state':current['state'], 'occurrenceId':current['id']}
