"""Exact, server-owned recipe policy binding at claim and every effect boundary.

Recipe admission owns its current version and per-occurrence reservations. This
seam owns the persisted task/attempt identity and current CF2 permission epoch.
No matching alternative policy can stand in for the policy the person enabled.
"""
from dataclasses import replace
import copy

from postriff_alpha.domain import AlphaError

from . import flags, model, store

_VALIDATORS = []


def register_policy_validator(fn):
    """fn(cur, task, step, policy, now) -> same policy with current usage, or None.

    A recipe callback checks its immutable scope/version and reserves one bounded
    action per task/step/generation. It discounts that same reservation on replay.
    This is a server startup hook, never request data.
    """
    _VALIDATORS[:] = [fn] if fn is not None else []


def required(task):
    return task.get('origin') == 'recipe' or task.get('autonomyMode') == 'autopilot' or bool(task.get('autopilotPolicyId'))


def _refused():
    return AlphaError('This recipe permission changed. Review the recipe again.', 403, code='agent_permission_revoked')


def for_step(cur, task, step, grants, now):
    """Narrow current grants to one exact policy in the caller's workspace lock."""
    if not required(task):
        return grants
    policy_id = task.get('autopilotPolicyId')
    if (task.get('origin') != 'recipe' or task.get('autonomyMode') != 'autopilot' or not store._uuid(policy_id)
            or grants is None or grants.source != 'explicit' or grants.ended or not _VALIDATORS):
        raise _refused()
    policy = next((p for p in grants.autopilot if p.id == policy_id), None)
    if policy is None or policy.expires_at <= now:
        raise _refused()
    cur.execute('SELECT 1 FROM public.pr_agent_autopilot_policies WHERE id=%s AND workspace_id=%s AND user_id=%s '
                'AND revoked_at IS NULL AND created_epoch=%s AND starts_at<=to_timestamp(%s) AND expires_at>to_timestamp(%s) FOR UPDATE',
                (policy_id, task['workspaceId'], task['createdBy'], grants.user_epoch, now, now))
    if not cur.fetchone():
        raise _refused()
    adjusted = _VALIDATORS[0](cur, task, step, copy.deepcopy(policy), now)
    if adjusted is None or type(adjusted) is not type(policy) or replace(adjusted, usage=policy.usage) != policy:
        raise _refused()
    return replace(grants, autopilot=(adjusted,))


def actor_for(task, actor):
    from ..authz import Actor
    return Actor('autopilot', task['createdBy'], '', {**(actor.evidence or {}), 'autopilotPolicyId': task['autopilotPolicyId']})


def for_context(cur, ctx, cap, args, grants, actor, now):
    """Reconstruct authority from live stored task/attempt; context evidence is not authority."""
    binding = getattr(ctx, 'step_binding', None)
    if not isinstance(binding, dict) or not binding.get('autopilotPolicyId') and actor.kind != 'autopilot':
        return grants, actor
    task = store.load_task(cur, ctx.workspace_id, binding.get('taskId'))
    if not task or not required(task) or task.get('autopilotPolicyId') != binding.get('autopilotPolicyId'):
        raise _refused()
    if (not flags.enabled_for(ctx.workspace_id, ctx.config) or binding.get('modelCall')
            or binding.get('workspaceId') != ctx.workspace_id or binding.get('principal') != ctx.principal
            or task['createdBy'] != ctx.principal or task['cancelRequestedAt'] is not None or task['hardExpiresAt'] <= now):
        raise _refused()
    step = store.load_step(cur, ctx.workspace_id, task['taskId'], binding.get('stepKey'))
    clean = {key: value for key, value in (args or {}).items() if key != 'stepId'}
    if (not step or step['stepId'] != binding.get('stepId') or step['state'] != 'running' or step['capabilityId'] != cap.name
            or step['inputDigest'] != model.input_digest(cap.name, clean) or step['inputDigest'] != binding.get('inputDigest')):
        raise _refused()
    cur.execute("SELECT 1 FROM public.pr_agent_step_attempts WHERE id::text=%s AND workspace_id=%s AND task_id::text=%s AND step_id::text=%s "
                "AND actor=%s AND generation=%s AND state='running' AND lease_owner=%s AND lease_expires_at>to_timestamp(%s)",
                (binding.get('attemptId'), ctx.workspace_id, task['taskId'], step['stepId'], ctx.principal, step['generation'], binding.get('leaseOwner'), now))
    if not cur.fetchone():
        raise _refused()
    return for_step(cur, task, step, grants, now), actor_for(task, actor)
