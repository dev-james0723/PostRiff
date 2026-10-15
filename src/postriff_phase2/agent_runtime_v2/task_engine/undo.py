"""One read-only eligibility plan for native Undo and Task Center affordances.

The POST boundary admits only a signed-in human. This planner binds that click to
an existing verified effect, its current generation, compensation window and
unchanged target. Its prospective actor is never accepted from request JSON or
persisted as reusable approval authority. The caller consumes the compensation
and writes the unique inverse receipt in this same workspace transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from . import authz_seam, compensation, errors, model, store


@dataclass(frozen=True)
class Plan:
    inputs: dict
    effect_key: str
    action: str | None
    payload: dict | None
    inverse: compensation.Inverse | None
    activation_id: str


def prepare(cur, task, step, record, principal, member, state, *, now, config=None):
    from .. import capability_registry, domain_tools, tool_adapter
    if principal != task['createdBy']:
        raise errors.error('task_forbidden')
    if (step is None or record is None or record['taskId'] != task['taskId']
            or record['stepId'] != step['stepId']):
        raise errors.error('undo_unavailable')
    if record['state'] == 'expired' or record['undoUntil'] <= now:
        raise errors.error('undo_expired')
    if record['state'] != 'available':
        raise errors.error('undo_unavailable' if record['state'] == 'applied' else 'undo_conflict')
    original = store.receipt(cur, task['workspaceId'], record['effectKey'])
    if (not original or original['state'] != 'done' or original['outcome'] != 'applied'
            or original['verified'] is not True or original['principal'] != principal
            or original['taskId'] != task['taskId'] or original['stepId'] != step['stepId']):
        raise errors.error('undo_unavailable')
    cur.execute('SELECT generation FROM public.pr_agent_step_attempts WHERE workspace_id=%s AND task_id::text=%s AND step_id::text=%s AND id::text=%s AND actor=%s',
                (task['workspaceId'], task['taskId'], step['stepId'], original['attemptId'], principal))
    attempt = cur.fetchone()
    if not attempt or int(attempt[0]) != int(step['generation']):
        raise errors.error('undo_conflict')
    domain_tools.ensure_registered()
    capability_id = original['capabilityId']
    try:
        policy = capability_registry.for_tool(capability_id)
        inverse_policy = capability_registry.for_tool(record['inverseCapabilityId'])
    except LookupError:
        raise errors.error('undo_unavailable') from None
    if policy is None or inverse_policy is None or policy.risk != 'R1' or inverse_policy.risk != 'R1':
        raise errors.error('undo_unavailable')
    tool = tool_adapter.REGISTRY.get(record['inverseCapabilityId'])
    if tool is None or member is None or not member.allows(tool.spec.permission):
        raise errors.error('agent_permission_revoked')
    if compensation.current_digest(cur, task['workspaceId'], record, capability_id) != record['postImageDigest']:
        raise errors.error('undo_conflict')
    inverse = compensation.INVERSES.get(capability_id)
    inputs = dict(record['inverseInputs'] or {})
    if inverse.validate_in:
        inverse.validate_in(cur, task['workspaceId'], principal, inputs)
    relational = inverse if inverse.apply_in else None
    action, payload = None, None
    if capability_id == 'draft_edit':
        draft = next((v for v in state.get('variants', []) if v.get('id') == inputs.get('draftId')), None)
        old = next((r for r in (draft or {}).get('revisions', []) if r.get('revision') == inputs.get('restoreRevision')), None)
        if not draft or not old or not old.get('text'):
            raise errors.error('undo_unavailable')
        if any((j.get('manifest') or {}).get('variantId') == draft['id'] and j.get('state') not in ('canceled', 'failed')
               for j in (state.get('phase2') or {}).get('jobs', [])):
            raise errors.error('undo_conflict')
        inputs = {'draftId': draft['id'], 'revision': draft['revision'], 'text': old['text']}
        action = 'variant_edit'
        payload = {'variantId': draft['id'], 'variantRevision': draft['revision'], 'text': old['text']}
    elif record['inverseCapabilityId'] in ('campaign_link', 'campaign_unlink'):
        action, payload = 'raffi_' + record['inverseCapabilityId'], inputs
    elif relational is None:
        raise errors.error('undo_unavailable')
    effect_key = ('undo:' + record['effectKey'])[:120]
    if store.receipt(cur, task['workspaceId'], effect_key) is not None:
        raise errors.error('undo_unavailable')
    # Native confirmation is valid only for this computed inverse at this exact
    # task/step version and post-image. No field of the proof comes from the body.
    activation = model.sha256({'workspaceId': task['workspaceId'], 'principal': principal,
        'taskId': task['taskId'], 'taskVersion': task['version'], 'stepId': step['stepId'],
        'generation': step['generation'], 'capabilityVersion': inverse_policy.version,
        'compensationId': record['compensationId'], 'originalEffectKey': original['effectKey'],
        'inverseEffectKey': effect_key, 'inputDigest': model.input_digest(record['inverseCapabilityId'], inputs),
        'target': [record['targetType'], record['targetId']], 'postImageDigest': record['postImageDigest'],
        'undoUntil': record['undoUntil']})
    actor = authz_seam.Actor('human_ui', principal, evidence={'activationId': 'undo:' + activation,
                                                            'capabilityId': inverse_policy.capability_id})
    verdict = authz_seam.decide_for_step(cur, task, {**step, 'kind': 'tool',
        'capabilityId': record['inverseCapabilityId'], 'inputs': inputs}, actor=actor, now=now, config=config)
    if verdict.verdict != 'allow':
        raise errors.error('agent_permission_revoked')
    return Plan(inputs, effect_key, action, payload, relational, activation)
