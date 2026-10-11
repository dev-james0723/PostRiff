"""Account-aware Mastodon planning in Rafii's existing metered Agent SDK.

No executor can approve, publish, delete or grant automation authority. Private
statuses and notification bodies have no model-facing read tool.
"""
import re

from postriff_alpha.domain import AlphaError
from .agent_runtime_v2 import contracts
from .agent_runtime_v2.tool_adapter import REGISTRY, register as register_tool
from .mastodon_management import MastodonManagement
from .mastodon_protocol import ID
from .youtube.agent_tools import _human_prose

SCOPES = {
    'mastodon_account_context': ('rafii_manager', 'content', 'publishing_ops', 'analytics'),
    'mastodon_analytics_summary': ('analytics',),
    'mastodon_action_prepare': ('content', 'publishing_ops'),
}
IDENTIFIER = {'type': 'string', 'pattern': r'^[A-Za-z0-9_.:-]{1,120}$', 'required': True}


def requested(ctx, analytics=False):
    text = _human_prose(str(ctx.request_text or ''))
    negative = re.search(r"\b(?:don't|do not|never|stop|without)\b|不要|唔好|禁止|停止", text, re.I)
    educational = re.search(r'\b(?:how to|what is|tutorial|hypothetical|example)\b|是什麼|是什么|如何|教我|例子', text, re.I)
    owned = re.search(r'\b(?:my|our|connected)\b|我的|我們的|我们的|我個|這個|这个', text, re.I)
    read = re.search(r'\b(?:analy[sz]e|show|check|review|compare|fetch|read)\b|分析|顯示|显示|檢查|检查|查看|查詢|查询|讀取|读取', text, re.I)
    metrics = re.search(r'\b(?:analytics|engagement|performance|metrics|followers|results)\b|成效|互動|互动|數據|数据|粉絲|粉丝', text, re.I)
    if not re.search(r'\bmastodon\b', text, re.I) or negative or (analytics and (educational or not (owned and read and metrics))):
        raise AlphaError('Ask explicitly to analyze your connected Mastodon account in this message.' if analytics else
                         'Ask for Mastodon planning in this message.', 403, code='mastodon_explicit_request_required')
    if analytics and ctx.modality == 'voice':
        raise AlphaError('Request Mastodon analytics in the text panel.', 409)


def account_context(ctx, args):
    requested(ctx)
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        if not member.allows('read'):
            raise AlphaError('Your role cannot read connections.', 403)
        channels = [c for c in state.get('phase2', {}).get('channels', []) if c.get('platform') == 'Mastodon' and not c.get('revoked')]
        if args.get('connectionId'):
            channels = [c for c in channels if c.get('id') == args['connectionId']]
            if not channels:
                raise AlphaError('Choose a currently connected Mastodon account.', 404)
        accounts = [{'connectionId': c['id'], 'accountId': c.get('providerAccountId'),
                     'instance': str(c.get('providerAccountId', '')).rsplit('@', 1)[-1],
                     'permissions': c.get('scopes', []), 'health': c.get('health'),
                     'configured': c.get('configured', False)} for c in channels[:20]]
    return {'ok': True, 'verified': True, 'data': {'accounts': accounts, 'truncated': len(channels) > 20,
            'next': 'Use draft_create/draft_rewrite for Brand Brain writing; choose the exact destination before preparing a calendar proposal. Channels handles connection and revocation.',
            'approvalPolicy': 'External actions require exact human approval. Full management OAuth scopes do not authorize automation.'}}


def analytics_summary(ctx, args):
    requested(ctx, analytics=True)
    report = MastodonManagement(ctx.service).read(ctx.workspace_id, ctx.token, args['connectionId'], 'analytics')
    # Account text, usernames, follower identities and private status bodies are
    # deliberately excluded. Untrusted server strings never become instructions.
    def count(value):
        return value if type(value) is int and value >= 0 else None
    def timestamp(value):
        from datetime import datetime, timezone
        if not isinstance(value, str) or len(value) > 40:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
        except (ValueError, OverflowError):
            return None
    observations = [{k: count(row.get(k)) for k in ('favourites', 'boosts', 'replies')}
                    | {'id': str(row['id']), 'createdAt': timestamp(row.get('createdAt'))}
                    for row in report['posts'][:40] if ID.fullmatch(str(row.get('id', '')))]
    history = report.get('historicalTrends')
    readings = []
    if isinstance(history, dict):
        for row in history.get('readings', [])[:500]:
            if isinstance(row, dict) and ID.fullmatch(str(row.get('postId', ''))) and row.get('metric') in ('likes', 'reposts', 'replies'):
                at, value = timestamp(row.get('observedAt')), count(row.get('value'))
                if at and value is not None:
                    readings.append({'postId': str(row['postId']), 'metric': row['metric'], 'value': value, 'observedAt': at,
                                     'readOffset': row.get('readOffset') if row.get('readOffset') in ('t0', '1h', '24h', '7d', 'backfill') else None})
    historical = {'readings': readings, 'truncated': bool(isinstance(history, dict) and history.get('truncated')),
                  'coverage': 'At most 500 legitimate native readings over 90 days for currently public/unlisted posts in the latest 40 account posts. Compare posts only at the same read offset; limited samples do not establish optimal posting times.'}
    evidence = {'connectionId': args['connectionId'], 'instance': report['instance'], 'observedAt': ctx.now(),
                'followers': count(report['followers']), 'following': count(report['following']),
                'postCount': count(report['postCount']), 'observations': observations,
                'coverage': report['coverage'], 'unavailableMetrics': report['unavailableMetrics'],
                'historicalTrends': historical}
    return {'ok': True, 'verified': True, 'data': evidence, 'providerState': 'read_only',
            'modelDisclosure': 'These requested numeric observations enter this text conversation. No private statuses, account biographies, follower identities or credentials are shared.',
            'limitation': 'Counts reflect this instance’s observations. They do not establish Fediverse-wide reach, best posting time or causation.'}


def action_prepare(ctx, args):
    requested(ctx)
    ctx.check_cancelled()
    if args['action'] == 'thread_prepare':
        return thread_prepare(ctx, args)
    payload = {key: value for key, value in args.items() if key != 'connectionId'}
    result = MastodonManagement(ctx.service).preview(ctx.workspace_id, ctx.token, args['connectionId'], payload)
    return {'ok': True, 'verified': True, 'needsUser': True, 'actionId': result['actionId'],
            'preview': result['preview'], 'expiresAt': result['expiresAt'], 'executed': False,
            'href': '/app/channels?mastodonAction=' + result['actionId'] + '&connection=' + args['connectionId'],
            'note': 'Review and approve this exact action in Channels. This tool grants no external or automation authority.'}


def thread_prepare(ctx, args):
    # Existing composer, Brand Brain draft and one exact Queue review. Never
    # acknowledge draft warnings or resolve unknown facts on the user's behalf.
    if not re.search(r'\bthread\b|串文|串連|串联|討論串|讨论串', _human_prose(str(ctx.request_text or '')), re.I):
        raise AlphaError('Ask explicitly to prepare a Mastodon thread in this message.', 403)
    for field in ('variantId', 'threadParts', 'localTime', 'timeZone'):
        if field not in args: raise AlphaError('Choose the reviewed draft, additional parts and local publication time.', 400)
    saved = ctx.service.repository.get(ctx.workspace_id, ctx.token)
    state = saved['state']; p2 = state.get('phase2') or {}
    channel = next((c for c in p2.get('channels', []) if c['id'] == args['connectionId'] and c.get('platform') == 'Mastodon' and not c.get('revoked')), None)
    variant = next((v for v in state.get('variants', []) if v['id'] == args['variantId'] and v.get('platform') == 'Mastodon'), None)
    if not channel or not variant: raise AlphaError('Choose a current Mastodon draft and connection in this workspace.', 404)
    if variant.get('warnings') or variant.get('unknowns') or variant.get('needsReview'):
        return {'ok': False, 'needsUser': True, 'executed': False, 'href': '/app/queue',
                'note': 'Review draft warnings and unsupported facts in the composer before preparing the thread.'}
    from .mastodon_threads import parts
    parts({'platform': 'Mastodon', 'payload': {'text': variant['text'], 'threadParts': args['threadParts']}})
    if not args['threadParts']: raise AlphaError('A thread needs at least one additional post.', 400)
    payload = {key: args[key] for key in ('variantId', 'threadParts', 'localTime', 'timeZone')}
    payload.update(channelId=args['connectionId'], acknowledgedWarnings=[], publishOptions={'visibility': 'public'})
    ctx.check_cancelled()
    updated = ctx.service.mutate(ctx.workspace_id, ctx.token, saved['revision'], 'p2_review', payload)
    reviews = updated['state']['phase2']['reviews']
    review = reviews[-1]
    return {'ok': True, 'needsUser': True, 'executed': False, 'reviewId': review['id'], 'href': '/app/queue',
            'note': 'The exact thread is saved for Queue review. Read every part and approve once before any post can be sent.'}


def instructions(key, base):
    from .coworker import flags
    if str(flags._source().get('POSTRIFF_OAUTH_MASTODON_ENABLED', '')).lower() != 'true' or key not in ('rafii_manager', 'content', 'publishing_ops', 'analytics'):
        return base
    return base + '\nMastodon: use mastodon_account_context to choose the exact instance-qualified account. Use existing draft_create/draft_rewrite and Brand Brain for Mastodon drafts, and existing calendar proposals for managed schedules. mastodon_action_prepare saves an unapproved exact action for Channels review; thread_prepare uses an existing reviewed Mastodon draft and additional explicit parts to save one Queue review. It never executes. mastodon_analytics_summary requires an explicit current-turn request to analyze the person’s connected account and returns public/unlisted numeric observations only. Do not invent reach/impressions/demographics or federation delivery, and distinguish accepted native schedules from actual publication. No tool reads private notifications or grants full-management, background automation or publication authority.'


def register():
    from .agent_runtime_v2 import specialists
    specs = [
        ('mastodon_account_context', contracts.READ, 'read', 'Read local connected Mastodon account identity and permissions. No provider content or credentials.',
         {'connectionId': {**IDENTIFIER, 'required': False}}, account_context, ('connections',)),
        ('mastodon_analytics_summary', contracts.READ, 'read', 'Read requested Mastodon native counts for at most 40 public/unlisted authored posts. Exact connected account and current human analytics request required; no private content.',
         {'connectionId': dict(IDENTIFIER)}, analytics_summary, ('analytics', 'connections')),
        ('mastodon_action_prepare', contracts.PREPARE_EXTERNAL, 'edit', 'Save a Mastodon action preview for human review in Channels. No execution, approval or background authority.',
         {'connectionId': dict(IDENTIFIER), 'action': {'type': 'string', 'enum': ['edit', 'delete', 'favourite', 'unfavourite', 'reblog', 'unreblog', 'bookmark', 'unbookmark', 'follow', 'unfollow', 'mute', 'unmute', 'block', 'unblock', 'native_schedule', 'native_reschedule', 'native_cancel', 'thread_prepare'], 'required': True},
          'targetId': {'type': 'string', 'pattern': r'^[0-9]{1,40}$'}, 'text': {'type': 'string', 'maxLength': 100000},
          'scheduled_at': {'type': 'string', 'maxLength': 40},
          'variantId': {**IDENTIFIER, 'required': False}, 'threadParts': {'type': 'array', 'minItems': 1, 'maxItems': 9, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 500}},
          'localTime': {'type': 'string', 'maxLength': 40}, 'timeZone': {'type': 'string', 'maxLength': 100}}, action_prepare, ('content', 'connections')),
    ]
    for name, effect, right, description, schema, executor, domains in specs:
        if name not in REGISTRY:
            spec = contracts.ToolSpec(name, effect, right, description, idempotent=effect == contracts.READ,
                                      approval=effect == contracts.PREPARE_EXTERNAL,
                                      voice=False, category='manage_connected_services', data_grants=domains,
                                      risk='R0' if effect == contracts.READ else 'R1', explicit_request=True,
                                      idempotency='read' if effect == contracts.READ else 'none', since=2,
                                      retry_class='never' if effect != contracts.READ else 'manual',
                                      background_eligible=False, autopilot_eligible=False)
            register_tool(spec, schema, 'Checked Mastodon account' if effect == contracts.READ else 'Prepared Mastodon action for review')(executor)
        for scope in SCOPES[name]:
            specialists.extend_scope(scope, [name])
    if instructions not in specialists.INSTRUCTION_HOOKS:
        specialists.INSTRUCTION_HOOKS.append(instructions)
