"""Task state → existing notification outbox. In-app only, creator only, no private task text.

A bounded scan catches transitions committed by any worker and retries failed outbox writes.
Events are deduped by the authoritative task/version/state; no provider is contacted here.
"""
from __future__ import annotations

import time
from ...notifications import catalog
from . import flags, store

STATES = {
    'awaiting_approval': ('approval_required', 'approvals', 'action', 'A task needs your review'),
    'blocked': ('blocked', 'automation', 'warning', 'A task needs attention'),
    'failed': ('failed', 'automation', 'warning', 'A task stopped with an error'),
    'completed': ('completed', 'automation', 'info', 'A task finished'),
}
EVENTS = {'agent.task_' + suffix: {'category': category, 'severity': severity, 'audience': 'actor',
          'email': 'off', 'push': 'off', 'sms': 'off', 'template': 'needs_input'}
          for suffix, category, severity, _title in STATES.values()}
catalog.register_extension_events(EVENTS)


def event_for(task):
    """No titles, reasons, drafts, approval bodies or model data enter notifications."""
    state = task.get('state')
    if state not in STATES or not store._uuid(task.get('taskId')) or not store._uuid(task.get('createdBy')):
        return None
    version = task.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        return None
    suffix, _category, _severity, title = STATES[state]
    task_id = task['taskId']
    return {'workspace_id': task['workspaceId'], 'event_type': 'agent.task_' + suffix,
            'dedupe_key': f'agent-task:{task_id}:{version}:{state}', 'entity_type': 'agent_task', 'entity_id': task_id,
            'actor': task['createdBy'], 'grouping_key': 'agent-task:' + task_id,
            'payload': {'title': title, 'href': '/app/tasks?task=' + task_id,
                        'reason': 'Open Tasks to inspect the recorded result.' if state == 'completed' else 'Open Tasks to review the current status.'},
            'occurred_at': task.get('updatedAt'), 'channel_filter': ('in_app',)}



def recipe_baseline(cur, task):
    """Suppress delivery, but persist its dedupe event, unless a current stored policy permits it."""
    if task.get('origin') != 'recipe':
        return False
    if not store._uuid(task.get('autopilotPolicyId')):
        return True
    cur.execute("SELECT to_regclass('public.pr_workflow_recipes')")
    if not cur.fetchone()[0]:
        return True
    cur.execute("""SELECT p.constraints->>'notificationPolicy' FROM public.pr_agent_autopilot_policies p
       JOIN public.pr_workflow_recipes r ON r.policy_id=p.id AND r.workspace_id=p.workspace_id AND r.created_by=p.user_id
       JOIN public.pr_agent_permission_state g ON g.workspace_id=p.workspace_id AND g.user_id=p.user_id
       WHERE p.id=%s AND p.workspace_id=%s AND p.user_id=%s AND p.revoked_at IS NULL
         AND p.starts_at<=now() AND p.expires_at>now() AND p.created_epoch=g.epoch
         AND r.status='active' AND p.constraints->>'recipeId'=replace(r.id::text,'-','')
         AND p.constraints->>'recipeVersion'=r.version::text
         AND p.constraints->>'notificationPolicy'=r.config->>'notificationPolicy'""",
       (task['autopilotPolicyId'], task['workspaceId'], task['createdBy']))
    row = cur.fetchone()
    mode = row[0] if row else 'none'
    return not (mode == 'all' or mode == 'failures_and_approvals' and task.get('state') in ('failed', 'blocked', 'awaiting_approval'))


def scan(runtime, *, limit=50, budget_seconds=2.0):
    """Fresh current membership, flags and task state under the workspace lock. Disabled = zero writes."""
    service = runtime.service
    notifications = getattr(service, 'notifications', None)
    cfg = getattr(runtime, 'cfg', None)
    if not notifications or not notifications.enabled() or not flags.anywhere(cfg):
        return {'status': 'disabled', 'created': 0}
    limit = max(1, min(int(limit), 100))
    started = time.monotonic()
    configured = getattr(cfg, 'task_engine_workspaces', None)
    if configured is None:
        setting = flags.settings()
        configured = {'*'} if setting.everywhere else setting.workspaces
    scopes = sorted(str(w).lower() for w in configured if w != '*')
    everywhere = '*' in configured
    with service.repository.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_agent_tasks'),to_regclass('public.pr_notification_events')")
        if not all(cur.fetchone()):
            return {'status': 'schema_unavailable', 'created': 0}
        cur.execute("""SELECT t.workspace_id::text,t.id::text FROM public.pr_agent_tasks t
          JOIN public.pr_memberships m ON m.workspace_id=t.workspace_id AND m.user_id=t.created_by AND m.status='active'
          WHERE t.state IN ('awaiting_approval','blocked','failed','completed')
            AND (%s OR t.workspace_id::text=ANY(%s))
            AND t.updated_at > now()-interval '7 days'
            AND NOT EXISTS (SELECT 1 FROM public.pr_notification_events e WHERE e.workspace_id=t.workspace_id
              AND e.dedupe_key='agent-task:'||t.id::text||':'||t.version::text||':'||t.state)
          ORDER BY t.updated_at,t.id LIMIT %s""", (everywhere, scopes, limit))
        rows = cur.fetchall()
    created = failed = scanned = 0
    for workspace_id, task_id in rows:
        if time.monotonic() - started >= budget_seconds:
            break
        if not flags.enabled_for(workspace_id, cfg):
            continue
        try:
            with store.service_tx(service, workspace_id, skip_locked=True) as cur:
                if cur is None:
                    continue
                # Re-read under lock: a queued retry or revoked creator must not get the previous failure notice.
                task = store.load_task(cur, workspace_id, task_id)
                event = event_for(task) if task else None
                if not event or not flags.enabled_for(workspace_id, cfg):
                    continue
                cur.execute("SELECT 1 FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active'",
                            (workspace_id, task['createdBy']))
                if not cur.fetchone():
                    continue
                if recipe_baseline(cur, task):
                    event['baseline'] = True
                result = notifications.emit(cur, **event)
                created += int(bool(result.get('created')))
                scanned += 1
        except Exception:  # notification failure leaves the authoritative task intact and can be retried next tick
            failed += 1
    return {'status': 'partial' if failed else 'available', 'created': created, 'failed': failed, 'scanned': scanned}
