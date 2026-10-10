"""Only trusted recipe tasks may call these R0 tools; never exposed to a Manager or voice model."""
from __future__ import annotations
import json
from postriff_alpha.domain import AlphaError
from ..agent_runtime_v2 import contracts
from ..agent_runtime_v2.tool_adapter import register
from ..agent_runtime_v2.task_engine import model, receipts, store
from . import catalog, reports
from .service import enabled, ready, scope

SCHEMA = {'recipeId': {'type': 'string', 'maxLength': 32, 'required': True},
          'recipeVersion': {'type': 'integer', 'minimum': 1, 'required': True},
          'templateId': {'type': 'string', 'enum': list(catalog.TEMPLATES), 'required': True},
          'connectionId': {'type': 'string', 'maxLength': 120},
          'collectionId': {'type': 'string', 'maxLength': 32},
          'start': {'type': 'string', 'maxLength': 10, 'required': True},
          'end': {'type': 'string', 'maxLength': 10, 'required': True},
          'timeZone': {'type': 'string', 'maxLength': 64, 'required': True},
          'assetIds': {'type': 'array', 'items': {'type': 'string', 'maxLength': 32}, 'maxItems': 20, 'required': True}}


def _execute(ctx, args, name, reader):
    binding = receipts.binding(ctx)
    if (not binding or not enabled(ctx.workspace_id, ctx.config) or binding.get('modelCall')
            or binding.get('workspaceId') != ctx.workspace_id or binding.get('principal') != ctx.principal
            or binding.get('inputDigest') != model.input_digest(name, args)):
        raise AlphaError('This read needs its active recipe task.', 403, code='agent_permission_denied')
    with ctx.workspace() as (cur, row, principal, member, state):
        # ctx.workspace rechecks the exact policy and live lease through the shared E2 guard.
        ready(cur)
        task = store.load_task(cur, ctx.workspace_id, binding['taskId'])
        step = store.load_step(cur, ctx.workspace_id, binding['taskId'], binding['stepKey'])
        if (not task or task['origin'] != 'recipe' or task['createdBy'] != principal or not step
                or step['capabilityId'] != name or step['stepId'] != binding['stepId'] or step['inputs'] != args):
            raise AlphaError('This recipe task is unavailable.', 403, code='agent_permission_denied')
        cur.execute('SELECT id::text,report,inputs FROM public.pr_workflow_recipe_runs WHERE task_id=%s AND workspace_id=%s AND created_by=%s AND policy_id=%s FOR UPDATE',
                    (task['taskId'], ctx.workspace_id, principal, task['autopilotPolicyId']))
        run = cur.fetchone()
        if not run or run[2] != args:
            raise AlphaError('The saved recipe scope changed.', 403, code='agent_permission_denied')
        if run[1] is None:
            scope(cur, ctx.workspace_id, args, state)
            report = reader(ctx.service, cur, ctx.workspace_id, principal, member, state, row, args, ctx.now())
            if len(json.dumps(report).encode()) > 95000:
                raise AlphaError('This report exceeds the saved report bound. Narrow its scope.', 413)
            cur.execute('UPDATE public.pr_workflow_recipe_runs SET report=%s::jsonb,completed_at=now() WHERE id=%s AND report IS NULL', (json.dumps(report), run[0]))
            cur.execute('SELECT report FROM public.pr_workflow_recipe_runs WHERE id=%s', (run[0],))
            if cur.fetchone()[0] != report:
                raise AlphaError('The stored report could not be verified.', 409)
        return {'ok': True, 'verified': True, 'reviewId': run[0], 'checks': [{'name': 'stored_recipe_report_verified', 'ok': True}], 'providerRequests': 0, 'costUsdMicro': 0}


def _spec(name, domains):
    return contracts.ToolSpec(name, contracts.READ, 'read', 'Read stored data for the exact authorized recipe and save its report.',
        voice=False, data_grants=domains, since=2, category='read_analyze', risk='R0', confirmation='none', cost='free',
        idempotency='read', retry_class='auto', max_attempts=3, background_eligible=True, evidence='audit', verification='reread')


@register(_spec('workflow_performance_review', ('analytics', 'connections')), SCHEMA, 'Reviewed stored performance')
def performance(ctx, args):
    return _execute(ctx, args, 'workflow_performance_review', reports.performance)


@register(_spec('workflow_library_review', ('library',)), SCHEMA, 'Reviewed Library metadata')
def library(ctx, args):
    return _execute(ctx, args, 'workflow_library_review', reports.library)


def install():
    from ..agent_runtime_v2.task_engine.autopilot import register_policy_validator
    from ..agent_runtime_v2.task_engine.tools import register_engine_tool
    from .policy import validate_task_policy
    for name in ('workflow_performance_review', 'workflow_library_review'):
        register_engine_tool(name)
    register_policy_validator(validate_task_policy)


install()
