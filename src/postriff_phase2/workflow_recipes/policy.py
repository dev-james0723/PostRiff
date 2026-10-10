"""Trusted exact-recipe validator and bounded operation reservation for the Task Engine seam."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
from ..agent_runtime_v2 import authz
from . import catalog
from .service import load, policy_constraints


def validate_task_policy(cur, task, step, policy, now):
    """Called at claim and before each actual read. Return only a reservation-adjusted usage view.

    A retry of one step/generation consumes one operation; its attempts remain capped by Task Engine.
    All state is locked by the engine's existing workspace transaction. No new dispatch authority.
    """
    if os.environ.get('RAFII_WORKFLOW_RECIPES_ENABLED') != '1' or task['workspaceId'] not in os.environ.get('RAFII_WORKFLOW_RECIPES_WORKSPACES', '').split(','):
        raise authz.AuthzError('Workflow recipes are disabled.', 'agent_permission_revoked')
    constraint = policy.constraints or {}
    recipe = load(cur, task['workspaceId'], task['createdBy'], constraint.get('recipeId'))
    if (recipe['status'] != 'active' or recipe.get('policyId') != policy.id
            or constraint != policy_constraints(recipe) or recipe['config']['expiresAt'] <= now
            or task.get('cancelRequestedAt') is not None):
        raise authz.AuthzError('This recipe policy is no longer current.', 'agent_permission_revoked')
    template = catalog.TEMPLATES.get(recipe['config']['templateId'])
    if (not template or template['version'] != recipe['config']['templateVersion'] or template['risk'] != 'R0'
            or template['capabilityId'] != 'tool.' + str(step.get('capabilityId', '')).removeprefix('tool.')):
        raise authz.AuthzError('This recipe needs a new native approval.', 'agent_permission_denied')
    limits = {key: recipe['config'][key] for key in ('actionsPerDay', 'actionsTotal', 'usdMicroPerDay')}
    if limits != policy.limits or limits['usdMicroPerDay'] != 0 or task.get('budgetCeilingUsdMicro') != 0:
        raise authz.AuthzError('Recipe cost limits changed.', 'agent_permission_denied')
    cur.execute('SELECT inputs FROM public.pr_workflow_recipe_runs WHERE workspace_id=%s AND created_by=%s AND task_id=%s AND recipe_id=%s AND recipe_version=%s AND policy_id=%s FOR UPDATE',
                (task['workspaceId'], task['createdBy'], task['taskId'], recipe['id'], recipe['version'], policy.id))
    occurrence = cur.fetchone()
    if not occurrence or occurrence[0] != step.get('inputs'):
        raise authz.AuthzError('The recipe action differs from its saved scope.', 'agent_permission_denied')
    key = f"{task['taskId']}:{step['stepKey']}:{step['generation']}"
    today = datetime.fromtimestamp(now, ZoneInfo(recipe['config']['timeZone'])).date().isoformat()
    usage = dict(policy.usage or {})
    reservations = dict(usage.get('reservations') or {})
    used_total = len(reservations)
    used_today = sum(1 for entry in reservations.values() if entry.get('day') == today)
    own = reservations.get(key)
    if own and own.get('inputDigest') != step['inputDigest']:
        raise authz.AuthzError('A reserved recipe step changed.', 'agent_permission_denied')
    if not own:
        if used_total >= limits['actionsTotal'] or used_today >= limits['actionsPerDay']:
            raise authz.AuthzError('This recipe reached its operation limit.', 'agent_permission_denied')
        reservations[key] = {'day': today, 'inputDigest': step['inputDigest']}
        used_total += 1
        used_today += 1
    usage.update(reservations=reservations, actionsTotal=used_total, actionsToday=used_today, day=today, spentUsdMicro=0)
    cur.execute('UPDATE public.pr_agent_autopilot_policies SET usage=%s::jsonb WHERE id=%s AND workspace_id=%s AND user_id=%s AND revoked_at IS NULL',
                (json.dumps(usage), policy.id, task['workspaceId'], task['createdBy']))
    # The static gate tests remaining capacity. This operation already owns its reservation.
    adjusted = {**usage, 'actionsTotal': used_total - 1,
                'actionsToday': used_today - int(reservations[key]['day'] == today)}
    return replace(policy, usage=adjusted)
