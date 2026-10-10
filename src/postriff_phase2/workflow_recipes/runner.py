"""Bounded admission into the existing Task Engine, never a second executor."""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from postriff_alpha.domain import AlphaError
from ..agent_runtime_v2 import agent_permissions, authz, capability_registry
from ..agent_runtime_v2.task_engine import store
from ..coworker.weekly_operator import due, iso_week, week_start
from . import catalog
from .service import Recipes, context, enabled, load, policy_constraints, ready, scope, _audit


def inputs_for(recipe, now, asset_ids=None):
    config = recipe['config']
    day = datetime.fromtimestamp(now, ZoneInfo(config['timeZone'])).date()
    return {'recipeId': recipe['id'], 'recipeVersion': recipe['version'], 'templateId': config['templateId'],
            'connectionId': config['connectionId'] or '', 'collectionId': config['collectionId'] or '',
            'start': (day - timedelta(days=7)).isoformat(), 'end': (day - timedelta(days=1)).isoformat(),
            'timeZone': config['timeZone'], 'assetIds': asset_ids or []}


def new_assets(cur, w, recipe):
    # Scan unhandled uploaded file identities, not a timestamp high-water mark: delayed ready state and equal
    # timestamps must not lose an upload. Completed/cancelled runs consume the occurrence, never auto-replay it.
    cur.execute("""SELECT replace(a.id::text,'-','') FROM public.pr_library_assets a
      WHERE a.workspace_id=%s AND a.created_at>=to_timestamp(%s) AND a.processing_status IN ('ready','unsupported')
        AND (%s::uuid IS NULL OR EXISTS(SELECT 1 FROM public.pr_library_collection_items i
          WHERE i.workspace_id=a.workspace_id AND i.collection_id=%s::uuid AND i.asset_key=replace(a.id::text,'-','')))
        AND NOT EXISTS(SELECT 1 FROM public.pr_workflow_recipe_runs r WHERE r.recipe_id=%s AND r.recipe_version=%s
          AND r.inputs->'assetIds' @> jsonb_build_array(replace(a.id::text,'-','')))
      ORDER BY a.created_at,a.id LIMIT 20""", (w, recipe['eventCursor'], recipe['config']['collectionId'], recipe['config']['collectionId'], recipe['id'], recipe['version']))
    return [row[0] for row in cur.fetchall()]


def settle(cur, domain, w, principal, recipe, now):
    cur.execute("""SELECT r.id,t.state FROM public.pr_workflow_recipe_runs r JOIN public.pr_agent_tasks t ON t.id=r.task_id
      WHERE r.recipe_id=%s AND r.recipe_version=%s AND NOT r.settled
      AND t.state IN ('completed','failed','cancelled','expired') ORDER BY r.created_at,r.id LIMIT 50 FOR UPDATE OF r""", (recipe['id'], recipe['version']))
    failures = recipe['consecutiveFailures']
    for run, state in cur.fetchall():
        failures = 0 if state == 'completed' else failures + int(state in ('failed', 'expired'))
        cur.execute('UPDATE public.pr_workflow_recipe_runs SET settled=true WHERE id=%s', (run,))
    changed = failures != recipe['consecutiveFailures']
    if changed:
        delay = min(3600, 300 * 2 ** max(0, failures - 1)) if failures else 0
        cur.execute('UPDATE public.pr_workflow_recipes SET consecutive_failures=%s,next_attempt_at=CASE WHEN %s>0 THEN to_timestamp(%s) ELSE NULL END WHERE id=%s', (min(failures, 100), delay, now + delay, recipe['id']))
        recipe['consecutiveFailures'], recipe['nextAttemptAt'] = failures, now + delay if delay else None
    if failures >= 3:
        domain._stop(cur, w, principal, recipe, 'paused', 'failure_circuit')
        recipe['status'] = 'paused'
        return False
    return not (changed and failures > 0)


def admit(cur, domain, w, principal, recipe, now, *, manual_key=None):
    _, member, state = context(domain.service, cur, w, principal)
    if not settle(cur, domain, w, principal, recipe, now):
        return None
    if recipe['status'] != 'active' or recipe['config']['expiresAt'] <= now:
        raise AlphaError('Enable a current recipe policy before running.', 409, code='recipe_policy_inactive')
    if recipe['nextAttemptAt'] and recipe['nextAttemptAt'] > now:
        raise AlphaError('This recipe is cooling down after a failure.', 409, code='recipe_backoff')
    scope(cur, w, recipe['config'], state)
    grants = agent_permissions.load(cur, w, principal, now=now)
    policy = next((p for p in grants.autopilot if p.id == recipe['policyId']), None)
    cur.execute('SELECT created_epoch FROM public.pr_agent_autopilot_policies WHERE id=%s AND workspace_id=%s AND user_id=%s FOR UPDATE', (recipe['policyId'], w, principal))
    epoch = cur.fetchone()
    if not policy or not epoch or epoch[0] != grants.user_epoch or policy.constraints != policy_constraints(recipe):
        raise AlphaError('Recipe permission was revoked or changed.', 403, code='agent_permission_revoked')
    # Recompute the local day from bounded reservations; yesterday's quota must not block today's admission.
    today = datetime.fromtimestamp(now, ZoneInfo(recipe['config']['timeZone'])).date().isoformat()
    reservations = (policy.usage or {}).get('reservations') or {}
    policy = replace(policy, usage={**(policy.usage or {}), 'actionsTotal': len(reservations),
                                  'actionsToday': sum(1 for entry in reservations.values() if entry.get('day') == today)})
    cap = capability_registry.get(catalog.TEMPLATES[recipe['config']['templateId']]['capabilityId'])
    decision = authz.decide(authz._registry_capability(cap), surface=authz.Surface('task_engine', cap.name, 'none'), member=member,
                           grants=replace(grants, autopilot=(policy,)), state=state, actor=authz.Actor('autopilot', principal),
                           target={'connectionId': recipe['config'].get('connectionId')}, now=now)
    if decision.outcome != 'allow':
        raise AlphaError('Current permissions or operation limits do not allow this run.', 403, code='recipe_permission_required')
    assets = []
    if manual_key:
        occurrence = 'manual:' + manual_key
    elif recipe['config']['trigger'] == 'weekly':
        if not due({**recipe['config'], 'status': recipe['status']}, now):
            return None
        occurrence = 'week:' + iso_week(week_start(now, recipe['config']['timeZone'], ahead=False))
    else:
        assets = new_assets(cur, w, recipe)
        if not assets:
            return None
        occurrence = 'uploads:' + catalog.digest(assets)
    cur.execute('SELECT task_id::text FROM public.pr_workflow_recipe_runs WHERE recipe_id=%s AND recipe_version=%s AND occurrence_key=%s', (recipe['id'], recipe['version'], occurrence))
    existing = cur.fetchone()
    if existing:
        return {**store.load_task(cur, w, existing[0]), 'recipeAdmissionCreated': False}
    # At most one unfinished occurrence per recipe; duplicate event polls cannot flood the queue before reservations.
    cur.execute("SELECT 1 FROM public.pr_workflow_recipe_runs r JOIN public.pr_agent_tasks t ON t.id=r.task_id WHERE r.recipe_id=%s AND t.state IN ('queued','running','awaiting_approval','blocked') LIMIT 1", (recipe['id'],))
    if cur.fetchone():
        raise AlphaError('This recipe already has an unfinished run. Open Tasks to inspect or cancel it.', 409, code='recipe_run_open')
    inputs = inputs_for(recipe, now, assets)
    cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text', (w, principal, recipe['config']['name']))
    conversation = cur.fetchone()[0]
    task, _ = store.create_task(cur, domain.service.ideas, workspace_id=w, conversation_id=conversation, created_by=principal,
        origin='recipe', title=recipe['config']['name'], request_key='recipe:' + catalog.digest([recipe['id'], recipe['version'], occurrence]),
        payload=inputs, steps=[{'kind': 'tool', 'capabilityId': cap.name, 'label': catalog.TEMPLATES[recipe['config']['templateId']]['name'],
                              'inputs': inputs, 'background': True}], trace_id='trace_' + uuid.uuid4().hex, autonomy_mode='autopilot',
        authz_token=grants.token(), budget_ceiling_usd_micro=0, autopilot_policy_id=policy.id)
    cur.execute('INSERT INTO public.pr_workflow_recipe_runs(recipe_id,workspace_id,created_by,recipe_version,occurrence_key,task_id,policy_id,inputs) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)',
                (recipe['id'], w, principal, recipe['version'], occurrence, task['taskId'], policy.id, json.dumps(inputs)))
    _audit(cur, w, principal, 'admitted', recipe['id'], {'taskId': task['taskId'], 'version': recipe['version']})
    return {**task, 'recipeAdmissionCreated': True}


def scan(runtime, *, limit=20, budget_seconds=2):
    domain = Recipes(runtime.service, runtime.cfg)
    started, admitted, unavailable = time.monotonic(), 0, 0
    # Explicit allowlist makes OFF a true no-query path and limits scan scope.
    import os
    workspaces = [w.strip() for w in os.environ.get('RAFII_WORKFLOW_RECIPES_WORKSPACES', '').split(',') if enabled(w.strip(), runtime.cfg)]
    if not workspaces:
        return {'status': 'disabled', 'admitted': 0}
    with runtime.service.repository.connection_factory() as db, db.cursor() as cur:
        ready(cur)
        cur.execute("SELECT workspace_id::text,created_by::text,id::text FROM public.pr_workflow_recipes WHERE workspace_id=ANY(%s::uuid[]) AND status='active' ORDER BY updated_at,id LIMIT %s", (workspaces, max(1, min(limit, 20))))
        candidates = cur.fetchall()
    for w, principal, ident in candidates:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            with store.service_tx(runtime.service, w, skip_locked=True) as cur:
                if cur is None:
                    continue
                domain._require(cur, w)
                recipe = load(cur, w, principal, ident)
                cur.execute('SAVEPOINT recipe_admission')
                try:
                    task = admit(cur, domain, w, principal, recipe, domain.clock())
                    admitted += int(bool(task and task.get('recipeAdmissionCreated')))
                except AlphaError:
                    cur.execute('ROLLBACK TO SAVEPOINT recipe_admission')
                    unavailable += 1
                cur.execute('RELEASE SAVEPOINT recipe_admission')
                cur.execute('UPDATE public.pr_workflow_recipes SET updated_at=now() WHERE id=%s', (ident,))
        except AlphaError:
            unavailable += 1
    return {'status': 'available', 'admitted': admitted, 'unavailable': unavailable}
