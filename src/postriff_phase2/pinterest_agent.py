"""A bounded Pinterest discovery tool in Rafii's existing metered Agent SDK.

OAuth, approval, scheduling, disconnection and publication continue through the
existing reviewed UI/proposal flows. This extension exposes no write operation.
"""
import re
from postriff_alpha.domain import AlphaError


def enabled():
    from .coworker import flags
    values = flags._source()
    # User connection-domain consent alone cannot authorize sharing Pinterest API
    # data with a model provider. Require a separately reviewed provider permission.
    return values.get('POSTRIFF_PINTEREST_AGENT_ENABLED') == '1' and values.get('POSTRIFF_PINTEREST_AGENT_PROVIDER_DATA_APPROVED') == '1'


def requested(text):
    from .youtube.agent_tools import _human_prose
    value = _human_prose(str(text or ''))
    return bool(re.search(r'\bpinterest\b', value, re.I)
                and re.search(r'\b(show|list|read|check|choose|find)\b|查看|顯示|显示|列出|選擇|选择', value, re.I)
                and not re.search(r'\b(how to|how do|how can|tutorial|example|hypothetical)\b|如何|教我|例子', value, re.I)
                and not re.search(r"\b(do not|don't|never|stop)\b|不要|唔好|停止", value, re.I))


def boards(ctx, args):
    if not enabled():
        raise AlphaError('Pinterest agent discovery needs reviewed provider data-sharing permission. Use the board selector directly.', 503, code='feature_disabled')
    if not requested(ctx.request_text):
        raise AlphaError('Ask to view your Pinterest boards in this message.', 403, code='explicit_request_required')
    ident = args.get('connectionId')
    if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', ident):
        raise AlphaError('Choose a connected Pinterest account.', 400)
    # Tenant and current member permission come from the authenticated OAuth service,
    # never model-supplied workspace/account fields. It renews the locked vault grant.
    snapshot = ctx.snapshot()['state']
    channel = next((c for c in (snapshot.get('phase2') or {}).get('channels', []) if c.get('id') == ident), None)
    if not channel or channel.get('platform') != 'Pinterest' or channel.get('revoked'):
        raise AlphaError('This Pinterest connection is unavailable in your workspace.', 404)
    result = ctx.service.oauth.destinations(ctx.workspace_id, ctx.token, ident, board_id=args.get('boardId'))
    return {'ok': True, 'verified': True, 'connectionId': ident, 'boardId': args.get('boardId'),
            'destinations': result['destinations'], 'evidence': 'authorized_provider_read',
            'note': 'No Pin, schedule, approval or connection was changed.'}


def register():
    if not enabled():
        return
    from .agent_runtime_v2 import contracts, specialists, capability_registry
    from .agent_runtime_v2.tool_adapter import REGISTRY, register as register_tool
    name = 'pinterest_boards'
    capability_registry.TOOL_POLICY[name] = {'category': 'read_analyze', 'risk': 'R0',
        'data_grants': ('connections',), 'explicit_request': True, 'feature_flag': 'POSTRIFF_PINTEREST_AGENT_ENABLED'}
    if name not in REGISTRY:
        register_tool(contracts.ToolSpec(name, contracts.READ, 'approve',
            'Read boards or sections for an exact connected Pinterest account requested in this message. Returns eligible destinations. Never publishes, approves or activates automation.', idempotent=True),
            {'connectionId': {'type': 'string', 'pattern': r'^[A-Za-z0-9_.:-]{1,120}$', 'required': True},
             'boardId': {'type': 'string', 'pattern': r'^\d{1,30}$'}}, 'Checked Pinterest destinations')(boards)
    for scope in ('rafii_manager', 'content', 'publishing_ops'):
        specialists.extend_scope(scope, [name])
