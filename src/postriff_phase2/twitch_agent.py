"""Bounded Twitch tools in Rafii's existing permissioned agent runtime.

The current human request can authorize safe connection facts, a selected native
counter read, or an unapproved native action draft. Nothing in this module can
approve, dispatch, change OAuth consent, retrieve stream keys or copy chat/viewer
text into a model. Full agent permission still requires the human's native-page
approval of the exact prepared action. All provider calls remain in TwitchService.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime

from postriff_alpha.domain import AlphaError
from .agent_runtime_v2 import authz, contracts
from .agent_runtime_v2.tool_adapter import REGISTRY, register as register_tool

_ID = r'^[A-Za-z0-9_.:-]{1,120}$'
_TIME = r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$'
_TWITCH = re.compile(r'(?<![A-Za-z0-9_])twitch(?![A-Za-z0-9_])', re.I)
_OWN = re.compile(r'\b(?:my|our|me|this|connected)\b|我|我們|我们|呢個|這個|这个', re.I)
_READ = re.compile(r'\b(?:show|list|read|check|fetch|inspect|review|summari[sz]e|report|analy[sz]e)\b|查看|檢查|检查|查詢|查询|顯示|显示|列出|分析|總結|总结|睇', re.I)
_PREPARE = re.compile(r'\b(?:prepare|draft|propose|schedule|update|send|reply|ban|timeout|delete|create|cancel|start|change)\b|準備|准备|草擬|草拟|提議|提议|排程|更新|發送|发送|回覆|回复|封禁|刪除|删除|建立|更改', re.I)
_METRIC = re.compile(r'\b(?:viewers?|followers?|counts?|metrics?|analytics|live status)\b|觀眾|观众|追蹤|追踪|粉絲|粉丝|數據|数据|人數|人数|直播狀態|直播状态', re.I)
_EDUCATIONAL = re.compile(r'\b(?:what (?:is|are|would|could|does)|how to|how (?:can|do|would|could|should) (?:i|we)|explain|describe|teach|tutorial|example|hypothetical|definition)\b|是什麼|是什么|如何|教我|示例|例子', re.I)
_NO_READ = re.compile(r"\b(?:do not|don't|never|without|stop)\b.{0,60}\b(?:read|fetch|access|check|show|share|list|inspect|review|report|summari[sz]e|analy[sz]e)\b|(?:不要|唔好|禁止|停止).{0,25}(?:讀|读|查看|檢查|检查|取得|顯示|显示|分享|列出|分析|總結|总结|睇)", re.I)
_NO_PREPARE = re.compile(r"\b(?:do not|don't|never|stop)\b.{0,60}\b(?:prepare|draft|propose|schedule|update|send|reply|ban|timeout|delete|create|cancel|start|change)\b|(?:不要|唔好|禁止|停止).{0,25}(?:準備|准备|草擬|草拟|提議|提议|排程|更新|發送|发送|回覆|回复|封禁|刪除|删除|建立|更改)", re.I)
_METRIC_ACTIONS = {'live_viewers': 'twitch.analytics.stream.snapshot', 'followers': 'twitch.channel.followers.total'}
TOOL_SCOPES = {
    'twitch_connection_context': ('rafii_manager', 'content', 'publishing_ops', 'analytics'),
    'twitch_metrics_snapshot': ('analytics',),
    'twitch_action_prepare': ('content', 'publishing_ops'),
}


def _tools_enabled():
    from .coworker import flags
    values = flags._source()
    return all(str(values.get(name, '')).lower() == 'true'
               for name in ('RAFII_TWITCH_PUBLIC_CONNECT', 'RAFII_TWITCH_COMMERCIAL_APPROVED'))


def requested(text, *, kind='context'):
    # Reuse the runtime's tested removal of quoted prose, code and lazy Markdown
    # quotations; retrieved messages and tool arguments are never authority.
    from .youtube.agent_tools import _human_prose
    prose = _human_prose(str(text or ''))
    if kind not in ('context', 'metrics', 'prepare'):
        return False
    if (_NO_PREPARE if kind == 'prepare' else _NO_READ).search(prose):
        return False
    for clause in re.split(r'[.!?;\n，,。！？；]+', prose):
        if not _TWITCH.search(clause) or _EDUCATIONAL.search(clause):
            continue
        if kind == 'prepare':
            if _PREPARE.search(clause):
                return True
        elif _READ.search(clause) and _OWN.search(clause) and (kind == 'context' or _METRIC.search(clause)):
            return True
    return False


def _guard(ctx, kind):
    if not _tools_enabled() or getattr(ctx.service, 'twitch', None) is None:
        raise AlphaError('Twitch agent tools are unavailable in this deployment.', 503, code='feature_disabled')
    service = ctx.service.twitch
    if kind != 'context' and getattr(service, 'agent_processing_approved', False) is not True:
        raise AlphaError('Twitch AI processing is awaiting separate purpose authorization.', 409, code='twitch_agent_processing_blocked')
    if not requested(ctx.request_text, kind=kind):
        raise AlphaError('Ask for this Twitch action explicitly in your current message.', 403, code='twitch_explicit_request_required')
    if ctx.modality != 'text':
        raise AlphaError('Use the text panel for Twitch tools and exact action review.', 409, code='twitch_text_required')
    if not authz.IN_TOOL.get():
        raise AlphaError('Use the permissioned Twitch tool path.', 403, code='twitch_tool_context_required')
    ctx.check_cancelled()
    return service


def _membership(member, right):
    if not member.allows(right):
        raise AlphaError('Your current workspace role cannot use this Twitch tool.', 403, code='tool_forbidden')


def _connection(state, connection):
    if not isinstance(connection, str) or not re.fullmatch(_ID, connection):
        raise AlphaError('Choose a connected Twitch account.', 400, code='tool_input')
    found = next((item for item in state.get('phase2', {}).get('channels', [])
                  if item.get('id') == connection and item.get('platform') == 'Twitch'
                  and not item.get('revoked') and item.get('identityVerified') is True), None)
    if found is None:
        raise AlphaError('Twitch connection unavailable.', 404, code='not_found')
    return found


def connection_context(ctx, args):
    service = _guard(ctx, 'context')
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        requested_connection = args.get('connectionId')
        if requested_connection:
            _connection(state, requested_connection)
        allowed = {c['id'] for c in state.get('phase2', {}).get('channels', [])
                   if c.get('platform') == 'Twitch' and not c.get('revoked') and c.get('identityVerified') is True}
    result = service.list_connections(ctx.workspace_id, ctx.token)
    rows = result.get('connections') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise AlphaError('Twitch connection facts could not be verified.', 503, code='twitch_facts_unavailable')
    facts = []
    for row in rows[:100]:
        if (not isinstance(row, dict) or row.get('id') not in allowed
                or requested_connection and row['id'] != requested_connection):
            continue
        ident = row.get('providerAccountId')
        if not isinstance(ident, str) or re.fullmatch(r'[1-9][0-9]{0,29}', ident) is None:
            continue
        status = row.get('status')
        facts.append({'connectionId': row['id'], 'twitchUserId': ident,
                      'status': status if status in ('active', 'connected', 'disconnected', 'revoked', 'reauthorization_required', 'unverified') else 'unverified'})
        ctx.ledger.reference('channel', row['id'], 'Connected Twitch account')
        if len(facts) == 20:
            break
    return {'ok': True, 'verified': True, 'data': {'connections': facts},
            'href': '/app/twitch', 'providerVerified': False,
            'note': 'Local connection facts only. No chat history, stream key, private profile text or live analytics was read.'}


def _integer(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


def metrics_snapshot(ctx, args):
    service = _guard(ctx, 'metrics')
    metric = args.get('metric')
    if metric not in _METRIC_ACTIONS:
        raise AlphaError('Choose a supported native Twitch counter.', 400, code='tool_input')
    connection = args['connectionId']
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        selected = _connection(state, connection)
        subject = selected.get('providerAccountId')
    result = service.read(ctx.workspace_id, ctx.token, connection, _METRIC_ACTIONS[metric], {'payload': {}})
    if (not isinstance(result, dict) or result.get('confirmed') is not True
            or result.get('action') != _METRIC_ACTIONS[metric]):
        raise AlphaError('The selected Twitch counter was not confirmed.', 503, code='twitch_metrics_unavailable')
    observations = []
    if metric == 'followers':
        total = _integer(result.get('total'))
        if total is not None:
            observations.append({'metric': 'total', 'value': total, 'meaning': 'follower_count'})
    else:
        rows = result.get('data')
        if not isinstance(rows, list) or len(rows) > 1:
            raise AlphaError('Twitch stream identity could not be verified.', 503, code='twitch_metrics_unavailable')
        for row in rows:
            if not isinstance(row, dict) or row.get('user_id') != subject:
                raise AlphaError('Twitch stream identity did not match.', 409, code='twitch_account_changed')
            count = _integer(row.get('viewer_count'))
            if count is not None:
                observation = {'metric': 'viewer_count', 'value': count, 'meaning': 'live_viewer_snapshot'}
                started = _timestamp(row.get('started_at'))
                if started:
                    observation['streamStartedAt'] = started
                observations.append(observation)
    # Any provider strings, usernames, chat and titles disappear at this explicit
    # projection. An absent/invalid count is not converted to a zero.
    observed = ctx.now()
    if type(observed) not in (float, int) or not math.isfinite(observed):
        raise AlphaError('Twitch observation time could not be verified.', 503)
    fact = {'kind': 'twitch_native_counter', 'connectionId': connection,
            'action': _METRIC_ACTIONS[metric], 'observedAt': observed, 'observations': observations,
            'source': 'Twitch Helix API', 'sourceUrl': 'https://dev.twitch.tv/docs/api/reference/',
            'limitation': 'Current snapshot only. Missing means unavailable; these counters do not establish unique viewers, watch time, retention, revenue or causes.'}
    ctx.ledger.facts.append(fact)
    return {'ok': True, 'verified': True, 'data': fact, 'providerVerified': True,
            'contentRead': False, 'executed': False}


def action_prepare(ctx, args):
    service = _guard(ctx, 'prepare')
    from .twitch_native import OPERATIONS
    action = args.get('action')
    operation = OPERATIONS.get(action) if isinstance(action, str) else None
    if operation is None or not operation.write or operation.risk == 'secret':
        raise AlphaError('Choose a native action that can be prepared for human review.', 409, code='twitch_native_review_required')
    payload = args.get('payload')
    if not isinstance(payload, dict):
        raise AlphaError('Supply the exact native action fields.', 400, code='tool_input')
    try:
        if len(json.dumps(payload, allow_nan=False).encode()) > 16384:
            raise ValueError()
    except (TypeError, ValueError, RecursionError):
        raise AlphaError('The Twitch draft is too large or invalid.', 400, code='tool_input') from None
    connection = args['connectionId']
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'edit')
        _connection(state, connection)
    body = {'action': action, 'payload': payload}
    if args.get('executeAt') is not None:
        when = args['executeAt']
        if not isinstance(when, str) or re.fullmatch(_TIME, when) is None or _timestamp(when) is None:
            raise AlphaError('Choose a valid action time for review.', 400, code='tool_input')
        body['executeAt'] = when
    ctx.check_cancelled()
    saved = service.preview(ctx.workspace_id, ctx.token, connection, body)
    if (not isinstance(saved, dict) or saved.get('state') != 'draft' or saved.get('action') != action
            or not isinstance(saved.get('id'), str) or not re.fullmatch(_ID, saved['id'])
            or not isinstance(saved.get('payloadHash'), str) or not re.fullmatch(r'[a-f0-9]{64}', saved['payloadHash'])):
        raise AlphaError('The unapproved Twitch draft could not be verified.', 503, code='twitch_draft_unconfirmed')
    ctx.ledger.reference('twitch_draft', saved['id'], 'Twitch action awaiting human review')
    ctx.ledger.changed.append({'type': 'twitch_draft', 'id': saved['id'], 'change': 'prepared for human review',
                               'expected': 'unapproved draft', 'actual': 'unapproved draft', 'verified': True})
    return {'ok': True, 'verified': True, 'needsUser': True, 'id': saved['id'], 'action': action,
            'payloadHash': saved['payloadHash'], 'state': 'draft', 'href': '/app/twitch',
            'queued': False, 'executed': False, 'providerVerified': False,
            'note': 'Review the exact fields and time in Twitch. This tool cannot approve or dispatch the action, including with Full agent permission.'}


def _instructions(key, base):
    if not _tools_enabled() or key not in ('rafii_manager', 'content', 'publishing_ops', 'analytics'):
        return base
    text = base + '\nTwitch: respond to explicit requests in this human turn only. twitch_connection_context returns local connected IDs. Never read chat/viewer text, tokens, download URLs or stream keys into a model.'
    from .coworker import flags
    if str(flags._source().get('RAFII_TWITCH_AI_PROCESSING_APPROVED', '')).lower() != 'true':
        return text + ' Native provider reads and draft preparation require separate Twitch AI-purpose authorization; these tools remain blocked.'
    return text + ' twitch_metrics_snapshot returns selected unchanged live-viewer or follower counts; do not invent Creator Dashboard analytics, retention, unique viewers or revenue. twitch_action_prepare creates an unapproved exact native action draft; direct the person to /app/twitch for approval. No tool can approve, dispatch, send messages, ban users, start an encoder or change consent. Full agent permission does not remove native human approval.'


def register():
    from .agent_runtime_v2 import specialists
    specs = (
        ('twitch_connection_context', contracts.READ, 'read',
         'Read bounded local Twitch connection facts only after an explicit current human request. No profile prose, viewer identities, chat, tokens or live analytics.',
         {'connectionId': {'type': 'string', 'pattern': _ID}}, connection_context),
        ('twitch_metrics_snapshot', contracts.READ, 'read',
         'Read one selected native Twitch live-viewer or follower-count snapshot after the person explicitly requests their Twitch metrics this turn. Returns numeric counters only; never chat, viewer identities, private titles or derived Creator Dashboard metrics.',
         {'connectionId': {'type': 'string', 'pattern': _ID, 'required': True},
          'metric': {'type': 'string', 'enum': list(_METRIC_ACTIONS), 'required': True}}, metrics_snapshot),
        ('twitch_action_prepare', contracts.CREATE_DRAFT, 'edit',
         'Prepare an unapproved exact Twitch native action draft for the current human request. The person must review and approve on the Twitch page. No execution, approval, OAuth, stream keys or download credentials.',
         {'connectionId': {'type': 'string', 'pattern': _ID, 'required': True},
          'action': {'type': 'string', 'pattern': r'^twitch\.[a-z0-9_.]{1,100}$', 'required': True},
          'payload': {'type': 'object', 'required': True},
          'executeAt': {'type': 'string', 'pattern': _TIME, 'description': 'Optional RFC3339 date and time with an explicit time-zone offset.'}}, action_prepare),
    )
    for name, effect, right, description, schema, executor in specs:
        if name not in REGISTRY:
            register_tool(contracts.ToolSpec(name, effect, right, description, voice=False,
                          idempotent=effect == contracts.READ, since=2), schema,
                          'Prepared an unapproved Twitch draft' if effect == contracts.CREATE_DRAFT else 'Checked selected Twitch facts')(executor)
        for scope in TOOL_SCOPES[name]:
            specialists.extend_scope(scope, [name])
    if _instructions not in specialists.INSTRUCTION_HOOKS:
        specialists.INSTRUCTION_HOOKS.append(_instructions)
