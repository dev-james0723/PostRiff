"""Receipt-only Task Engine entry to the native Library metadata domain.

No model scope exposes this tool. The prepared native receipt owns the exact
metadata diff, creator, target versions and expiry. No file bytes are read here.
"""
from __future__ import annotations
import json
import time
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from .. import authz, contracts
from ..tool_adapter import register
from . import flags, model, receipts, store

NAME = 'library_metadata_apply'


def reader(ideas):
    from ...library_assets import UniversalLibrary
    from ...library_metadata import LibraryMetadataChanges
    service = SimpleNamespace(ideas=ideas, repository=ideas.repository)
    return LibraryMetadataChanges(UniversalLibrary(service))


def approval_preview(cur, ideas, task, step):
    preview = reader(ideas).prepared_in(cur, task['workspaceId'], task['createdBy'], step['inputs']['receiptId'])
    entries = [{**entry, 'changedFields': sorted(entry['changedFields'])} for entry in preview['entries']]
    exact = {'receiptId': preview['receiptId'], 'expiresAt': preview['expiresAt'], 'entries': entries}
    # Approval rows are bounded to 8KiB. Never truncate a diff and approve unseen changes.
    if len(json.dumps(exact, ensure_ascii=False).encode()) > 6000:
        raise AlphaError('Choose fewer Library changes for one task approval.', 413)
    return exact


@register(contracts.ToolSpec(NAME, contracts.MUTATE_REVERSIBLE, 'edit',
          'Apply the creator\'s prepared native Library metadata receipt.', data_grants=('library',), since=2,
          idempotency='receipt_tx', retry_class='auto', evidence='receipt', verification='reread',
          compensation='inverse', inverse='tool.library_metadata_apply'),
          {'receiptId': {'type': 'string', 'maxLength': 32, 'required': True}}, 'Applied reviewed Library details')
def apply(ctx, args):
    binding = receipts.binding(ctx)
    if (not binding or not flags.enabled_for(ctx.workspace_id, ctx.config)
            or authz.mode_for(ctx.config, ctx.workspace_id) != 'enforce'
            or binding.get('modelCall') or binding.get('workspaceId') != ctx.workspace_id
            or binding.get('principal') != ctx.principal or binding.get('inputDigest') != model.input_digest(NAME, args)):
        raise AlphaError('This change needs its active task.', 403, code='agent_permission_denied')
    from ...library_metadata import LibraryMetadataChanges
    with ctx.workspace() as (cur, _row, principal, _member, _state):
        task = store.load_task(cur, ctx.workspace_id, binding['taskId'])
        step = store.load_step(cur, ctx.workspace_id, binding['taskId'], binding['stepKey'])
        if task is None or task['createdBy'] != principal or step is None or step['capabilityId'] != NAME or step['stepId'] != binding['stepId']:
            raise AlphaError('This Library change is unavailable.', 403, code='agent_permission_denied')
        replay = receipts.replayed(cur, ctx)
        if replay:
            return {'ok': replay['verified'], 'verified': replay['verified'], 'replayed': True}
        domain = LibraryMetadataChanges(ctx.service.library)
        domain.prepared_in(cur, ctx.workspace_id, principal, args['receiptId'])
        result = domain.apply_in(cur, ctx.workspace_id, principal, args['receiptId'])
        if result['status'] != 'applied' or result['verified'] is not True:
            raise AlphaError('The Library change could not be verified.', 409, code='library_metadata_conflict')
        receipts.commit_command(cur, ctx, verified=True, changed_refs=result['changedRefs'], compensation_result={'receiptId': args['receiptId']})
    ctx.ledger.changed.extend({**ref, 'verified': True} for ref in result['changedRefs'])
    return {'ok': True, 'verified': True, 'checks': result['checks'], 'changedRefs': result['changedRefs']}


def current_image(cur, workspace_id, receipt_id):
    from ...ideas import IdeasService
    ideas = SimpleNamespace(_state=IdeasService._state, repository=SimpleNamespace(clock=time.time))
    return reader(ideas).current_digest(cur, workspace_id, receipt_id)


def undo_in(runtime, cur, workspace_id, principal, inputs, effect_key):
    from ...library_metadata import LibraryMetadataChanges
    return LibraryMetadataChanges(runtime.service.library).undo_in(cur, workspace_id, principal, inputs['receiptId'], effectKey=effect_key)


def validate_undo(cur, workspace_id, principal, inputs):
    from ...ideas import IdeasService
    ideas = SimpleNamespace(_state=IdeasService._state, repository=SimpleNamespace(clock=time.time))
    domain = reader(ideas)
    row = domain._context(cur, workspace_id, principal)
    status, payload, expires, undo_expires = domain._receipt(cur, workspace_id, principal, inputs['receiptId'])
    view = domain._result(cur, row, workspace_id, inputs['receiptId'], status, payload, expires, undo_expires)
    if not view['canUndo']:
        raise AlphaError(view['undoReason'] or 'This Library change cannot be undone.', 409, code='undo_conflict')


def install_inverse():
    from .compensation import Inverse, register as inverse
    inverse(NAME, Inverse(NAME, lambda _i, result: ('library_change', result['receiptId']),
                         lambda inputs, _r: {'receiptId': inputs['receiptId']}, lambda *_a: None, current_image, undo_in, validate_undo))


from .tools import register_engine_tool
register_engine_tool(NAME)
install_inverse()
