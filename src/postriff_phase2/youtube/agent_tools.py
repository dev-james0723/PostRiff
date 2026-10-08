"""YouTube planning inside Rafii's existing metered chat runtime.

Only local drafts and bounded nonmonetary reads are available. Publication, OAuth
consent, standing authority, approval and destructive operations have no tools.
Google results reach the model only as selected native metrics requested this turn.
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import date

from postriff_alpha.domain import AlphaError
from ..asset_kinds import is_postable_video
from ..agent_runtime_v2 import contracts
from ..agent_runtime_v2.tool_adapter import REGISTRY, register as register_tool
from .agent import _channel, find_draft, draft_digest
from .model import READ, ANALYTICS, has_scopes

_ID = r'^[A-Za-z0-9_.:-]{1,120}$'
_ASSET = r'^[0-9a-f]{32}$'
TOOL_SCOPES = {
    'youtube_plan_context': ('rafii_manager', 'content', 'publishing_ops'),
    'youtube_plan_prepare': ('content', 'publishing_ops'),
    'youtube_analytics_summary': ('analytics',),
    'youtube_recommendations': ('analytics', 'content', 'publishing_ops'),
}
_YOUTUBE = re.compile(r'\byoutube\b|油管', re.I)
_ANALYTICS = re.compile(r'\banalytics\b|\bmetrics\b|\bperformance\b|\bresults\b|\bviews\b|成效|數據|数据|分析|觀看|观看', re.I)
_NEGATIVE = re.compile(r"\b(?:do not|don't|never|stop)\b.{0,60}\b(?:read|fetch|share|analy[sz]e|prepare|draft)\b|不要|唔好|禁止|停止", re.I)
_NO_ACCESS = re.compile(r"\b(?:without|no|not|never|don't|do not|must not)\b.{0,60}\b(?:access(?:ing)?|fetch(?:ing)?|read(?:ing)?|retriev(?:e|ing)|query(?:ing)?|shar(?:e|ing)|us(?:e|ing)|analy[sz](?:e|ing))\b", re.I)
_EDUCATIONAL = re.compile(r'\b(?:what (?:is|are)|how to|how (?:can|do|would|could|should) (?:i|we)|definition|tutorial|example|hypothetical|meaning)\b|是什麼|是什么|如何|怎樣|怎样|教我|示例|例子|意思', re.I)
_OWNED_READ = re.compile(r'\b(?:read|fetch|retrieve|access|check|show|analy[sz]e|inspect|query|review|compare|summari[sz]e|report)\b.{0,50}\b(?:my|our|this|the connected)\b.{0,80}\b(?:youtube|channel|account|analytics|metrics|performance|views|results)\b|(?:讀取|读取|查詢|查询|檢查|检查|查看|分析|比較|比较|總結|总结|顯示|显示|取得|获取).{0,30}(?:我的|我們的|我们的|我個|我个|這個|这个|本).{0,50}(?:YouTube|油管|頻道|频道|帳戶|账户|數據|数据|成效)', re.I)
_METRICS = ('views', 'engagedViews', 'estimatedMinutesWatched', 'likes', 'comments', 'shares', 'subscribersGained', 'subscribersLost')


def _tools_enabled():
    # Reuse the hosted app's isolated configuration snapshot, including explicit
    # test/dev attachments. Read the same exact flag used to mount the creator
    # provider; an unrelated skill-registry flag must not enable YouTube tools.
    from ..coworker import flags
    return flags._source().get('POSTRIFF_YOUTUBE_CREATOR_ENABLED') == '1'


def _human_prose(text):
    # Quoted instructions and code are data even when the person supplied them.
    # Preserve apostrophes inside contractions, but remove standalone quotations.
    # A Markdown quote can continue lazily on unmarked lines in the same
    # paragraph. Conservatively discard through the next blank line; only a
    # separate unquoted paragraph can provide fresh human authority.
    lines, quoted_paragraph, fence = [], False, None
    for line in text.splitlines():
        if fence:
            if re.match(r'^[ \t]*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*$', line):
                fence = None
            lines.append('')
            continue
        marker = re.match(r'^[ \t]*(`{3,}|~{3,})', line)
        if marker:
            fence = marker.group(1)
            lines.append('')
            continue
        if line.expandtabs(4).startswith('    '):
            lines.append('')
            continue
        if re.match(r'^\s*>', line):
            quoted_paragraph = True
            lines.append('')
        elif quoted_paragraph and line.strip():
            lines.append('')
        else:
            quoted_paragraph = False
            lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'```.*?(?:```|$)', ' ', text, flags=re.S)
    text = re.sub(r'`[^`]*(?:`|$)|"[^"\n]*"|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』', ' ', text)
    return re.sub(r"(?<!\w)'[^'\n]*'(?!\w)", ' ', text)


def _requested(ctx, *, analytics=False):
    if not _tools_enabled():
        raise AlphaError('YouTube creator tools are unavailable in this deployment.', 503, code='feature_disabled')
    # Only the current human message can authorize these reads, never tool args,
    # a stored video title, retrieved data, a model's paraphrase or earlier consent.
    text = _human_prose(str(ctx.request_text or ''))
    explicit_read = any(_YOUTUBE.search(clause) and _ANALYTICS.search(clause) and _OWNED_READ.search(clause)
                        and not _EDUCATIONAL.search(clause) for clause in re.split(r'[.!?;\n，,。！？；]+', text))
    if not _YOUTUBE.search(text) or _NEGATIVE.search(text) or (analytics and (_NO_ACCESS.search(text) or not explicit_read)):
        raise AlphaError('Ask explicitly for YouTube analytics in this message.' if analytics else
                         'Ask explicitly for YouTube planning in this message.', 403, code='youtube_explicit_request_required')


def _creator(ctx):
    creator = getattr(ctx.service, 'youtube', None)
    if creator is None:
        raise AlphaError('YouTube creator tools are unavailable in this deployment.', 503, code='feature_disabled')
    return creator


def _membership(member, right):
    if not member.allows(right):
        raise AlphaError('Your current workspace role cannot use this YouTube tool.', 403, code='tool_forbidden')


def plan_context(ctx, args):
    _requested(ctx)
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        channels = [c for c in state.get('phase2', {}).get('channels', [])
                    if c.get('platform') == 'YouTube' and not c.get('revoked')]
        if args.get('connectionId'):
            chosen = _channel(state, args['connectionId'])
            channels = [chosen]
        assets = [a for a in state.get('phase2', {}).get('assets', []) if is_postable_video(a, 'YouTube')]
        limit = max(1, min(args.get('limit') if type(args.get('limit')) is int else 12, 20))
        # No storage path, raw video, filename, transcript or private goals leave
        # through this projection. Content understanding uses the existing
        # consented image_analyze/Library approved-facts tools separately.
        videos = [{'assetId': a['id'], 'durationSeconds': a['duration'], 'width': a.get('width'), 'height': a.get('height'),
                   'bytes': a['bytes'], 'containerVerified': True, 'contentUnderstanding': 'not_analyzed',
                   'portraitOrSquare': bool(a.get('height', 0) >= a.get('width', 0))} for a in assets[:limit]]
        accounts = [{'connectionId': c['id'], 'channelId': c['providerAccountId'],
                     'authorizationLane': c.get('authorizationLane', 'standard')} for c in channels[:20]]
    for video in videos:
        ctx.ledger.reference('asset', video['assetId'], 'Inspected Library video')
    return {'ok': True, 'verified': True, 'data': {'channels': accounts, 'videos': videos, 'eligibleVideoCount': len(assets),
        'goalContext': 'Use this turn’s instruction and the existing consented memory_context tool. No private stored goals were read.',
        'limitation': 'Technical eligibility only. No video content, audience preferences or Shorts classification was inferred.',
        'next': 'Choose the exact destination and video. Supply rights, audience and synthetic-media declarations before preparing a reviewable plan.'}}


def _declarations(text):
    """Conservative, current-turn human declarations; ambiguous wording asks again."""
    rights = bool(re.search(r'\b(?:I own (?:the |all )?(?:copyright|rights)|I have (?:the |all )?(?:publishing |necessary )?rights|rights confirmed)\b|我(?:擁有|拥有|持有).{0,12}(?:版權|版权|發佈權|发布权)|版權已確認|版权已确认', text, re.I))
    def value(pattern):
        hits = re.findall(pattern, text, re.I)
        answers = {hit.lower() in ('true', 'yes', '是') for hit in hits}
        return next(iter(answers)) if len(answers) == 1 else None
    kids = value(r'(?:made\s+for\s+kids|兒童內容|儿童内容)\s*[:=：]\s*(true|false|yes|no|是|否)\b')
    synthetic = value(r'(?:contains\s+synthetic\s+media|合成媒體|合成媒体)\s*[:=：]\s*(true|false|yes|no|是|否)\b')
    return rights, kids, synthetic


def plan_prepare(ctx, args):
    from ..agent_runtime_v2.domain_tools import resolve_when
    _requested(ctx)
    creator = _creator(ctx)
    rights, kids, synthetic = _declarations(_human_prose(str(ctx.request_text or '')))
    if not rights or kids is None or synthetic is None:
        return {'ok': False, 'verified': False, 'needsUser': True, 'code': 'youtube_declarations_required',
                'question': 'Confirm rights and both declarations in your message, for example: “YouTube: I own the rights; made for kids: no; contains synthetic media: no”. Rafii cannot infer these from the video.'}
    local_time, question = resolve_when(args['when'], ctx.now(), ctx.zone)
    if question:
        return {'ok': False, 'verified': False, 'needsUser': True, 'code': 'needs_time', 'question': question}
    body = {'assetId': args['assetId'], 'rightsConfirmed': True, 'localTime': local_time,
            'timeZone': ctx.zone, 'fold': args.get('fold'), 'uploadWorkflow': 'upload_now',
            'publishOptions': {'title': args['title'], 'description': args['description'], 'privacyStatus': args['privacyStatus'],
                               'madeForKids': kids, 'containsSyntheticMedia': synthetic},
            'goal': str(args.get('goal') or '')[:1000]}
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'edit')
        _channel(state, args['connectionId'])
    ctx.check_cancelled()
    # Draft preparation calls no Google API and grants no publishing authority.
    # It uses the same membership, immutable asset, future-time and audit path.
    snapshot = ctx.snapshot()
    result = creator.agent.prepare(ctx.workspace_id, ctx.token, args['connectionId'], {**body, 'revision': snapshot['revision']})
    identifier = result['result']['id']
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        saved = copy.deepcopy(find_draft(state, args['connectionId'], identifier))
        verified = (saved.get('status') == 'proposed' and saved.get('assetId') == args['assetId']
                    and saved.get('digest') == draft_digest(saved) and saved.get('publishOptions') == result['result'].get('publishOptions')
                    and not saved.get('jobId'))
    ctx.ledger.reference('youtube_plan', identifier, 'YouTube plan awaiting review')
    ctx.ledger.reference('draft', saved['variantId'], 'YouTube draft')
    ctx.ledger.changed.append({'type': 'youtube_plan', 'id': identifier, 'change': 'prepared for manual review',
        'expected': 'saved unapproved plan', 'actual': 'saved unapproved plan' if verified else 'unconfirmed', 'verified': verified})
    return {'ok': verified, 'verified': verified, 'needsUser': True, 'draftId': identifier, 'variantId': saved['variantId'],
        'channelId': saved['channelId'], 'assetId': saved['assetId'], 'title': saved['publishOptions']['title'],
        'description': saved['publishOptions']['description'], 'timing': saved['timing'], 'status': saved['status'],
        'metadataOrigin': 'chat_model_proposal_requires_video_review', 'href': '/app/youtube',
        'queued': False, 'executed': False, 'providerVerified': False,
        'note': 'Review the exact video, metadata and time in YouTube Creator. This chat tool cannot approve, publish or enable autopilot.'}


def _analytics_gate(ctx, connection):
    _requested(ctx, analytics=True)
    creator = _creator(ctx)
    # Membership and immutable channel identity precede access to server credentials.
    _actor, channel, _state = creator._member(ctx.workspace_id, ctx.token, connection, 'read')
    provider = creator.oauth.provider_for_connection(ctx.workspace_id, connection)
    if (getattr(provider, 'authorization_lane', None) != 'agentic' or not getattr(provider, 'creator_enabled', False)
            or not getattr(provider, 'execution_enabled', True)):
        raise AlphaError('Connect a separately authorized agentic YouTube account before AI analytics reads.', 409,
                         code='youtube_agentic_oauth_required')
    grant = creator.oauth.token_for_worker(ctx.workspace_id, connection)
    try:
        envelope = json.loads(grant.get('accessToken', ''))
    except (TypeError, ValueError):
        envelope = {}
    if (grant.get('authorizationLane') != 'agentic' or grant.get('providerAccountId') != channel
            or envelope.get('v') != 2 or envelope.get('clientId') != provider.client_id
            or envelope.get('authorizationLane') != 'agentic' or grant.get('refreshBindingRequired') is True):
        raise AlphaError('Reconnect this channel to its exact agentic OAuth client.', 409, code='youtube_agentic_oauth_required')
    if not has_scopes(grant.get('scopes'), (READ, ANALYTICS)):
        raise AlphaError('Grant the actual channel-read and nonmonetary Analytics scopes first.', 409, code='youtube_agentic_scope_required')
    return creator, channel


def _range(args):
    try:
        first, last = date.fromisoformat(args['startDate']), date.fromisoformat(args['endDate'])
        if first > last or (last - first).days > 90:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise AlphaError('Choose a valid explicit analytics range of at most 90 days.', 400, code='tool_input') from None
    return first, last


def _native_metrics(report, first, last):
    """Project unchanged provider values; never calculate scores, totals or averages."""
    data, observations = report.get('data') or {}, []
    headers = [item.get('name') for item in data.get('columnHeaders') or [] if isinstance(item, dict)]
    if not all(isinstance(name, str) for name in headers) or len(headers) != len(set(headers)) or 'day' not in headers:
        raise AlphaError('YouTube returned ambiguous native metric columns.', 502, code='youtube_report_invalid')
    rows = data.get('rows') or []
    for row in rows[:100]:
        if not isinstance(row, list) or len(row) != len(headers):
            continue
        values = dict(zip(headers, row))
        try:
            day = date.fromisoformat(values.get('day'))
            if not first <= day <= last or day.isoformat() != values['day']:
                continue
        except (ValueError, TypeError):
            continue
        observation = {'day': values['day']}
        for metric in _METRICS:
            value = values.get(metric)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                observation[metric] = value
        if len(observation) > 1:
            observations.append(observation)
    return {'nativeObservations': observations, 'projectionTruncated': len(rows) > 100,
            'providerCoverageComplete': (report.get('coverage') or {}).get('complete') is True,
            'source': 'YouTube Analytics API', 'startDate': first.isoformat(), 'endDate': last.isoformat(),
            'limitation': 'Selected native metric values and day labels are unchanged. Other fields, invalid values and out-of-range dates are omitted, never replaced by zero. No independent totals, averages, rankings or predictions are calculated. Daily views cannot identify the best posting hour or prove causation.'}


def analytics_summary(ctx, args):
    first, last = _range(args)
    creator, channel = _analytics_gate(ctx, args['connectionId'])
    # Existing creator read path rechecks role, throttles, exact client binding,
    # scope/capability and owned-channel identity. No monetary report or ids=mine.
    report = creator.read(ctx.workspace_id, ctx.token, args['connectionId'], 'analytics',
                          {'report': 'daily', 'startDate': first.isoformat(), 'endDate': last.isoformat()})
    if report.get('channelId') != channel or report.get('source') != 'YouTube Analytics API':
        raise AlphaError('The returned analytics do not match this authorized channel.', 409, code='youtube_identity_mismatch')
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        if _channel(state, args['connectionId'])['providerAccountId'] != channel:
            raise AlphaError('This connection changed during analytics retrieval.', 409, code='youtube_identity_mismatch')
    native = _native_metrics(report, first, last)
    evidence = {'connectionId': args['connectionId'], 'channelId': channel, 'observedAt': ctx.now(), **native}
    ctx.ledger.facts.append({'kind': 'youtube_native_analytics', 'evidence': evidence,
                             'text': 'Requested nonmonetary YouTube analytics, selected unchanged native metric values and dates only.'})
    return {'ok': True, 'verified': True, 'data': evidence, 'providerState': 'read_only',
            'modelDisclosure': 'Only requested selected native numeric metrics and their original dates are shared with this turn’s configured model. No revenue, viewer identities, video text or credentials.'}


def recommendations(ctx, args):
    _requested(ctx)
    with ctx.workspace() as (_cur, _row, _actor, member, state):
        _membership(member, 'read')
        channel = _channel(state, args['connectionId'])['providerAccountId']
    # No background fetch and no stale persisted evidence imported into chat.
    evidence = next((fact['evidence'] for fact in reversed(ctx.ledger.facts)
                     if fact.get('kind') == 'youtube_native_analytics'
                     and fact.get('evidence', {}).get('connectionId') == args['connectionId']
                     and fact['evidence'].get('channelId') == channel), None)
    suggestions = ['Choose publication dates in your time zone and reserve upload plus processing time.',
                   'Use the existing consented video-frame/approved-fact analysis before proposing titles or descriptions.',
                   'Treat any proposed thumbnail, title or schedule as a reviewable hypothesis.']
    if evidence and evidence['nativeObservations']:
        suggestions.append('Review the selected native metrics with their original dates and your publishing goals. Use them as observations when planning a future experiment; no score, average, ranking or posting-time prediction was calculated.')
    return {'ok': True, 'verified': True, 'data': {'channelId': channel, 'recommendations': suggestions,
            'analyticsEvidence': evidence, 'performanceEvidenceAvailable': bool(evidence and evidence['nativeObservations']),
            'contentPerformanceInference': 'unavailable_from_selected_daily_metrics', 'bestPostingHour': 'unsupported_by_available_evidence',
            'note': 'No plan, calendar entry, approval or publication was changed.'}}


def _instructions(key, base):
    if not _tools_enabled() or key not in ('rafii_manager', 'content', 'publishing_ops', 'analytics'):
        return base
    return base + '\nYouTube: use youtube_plan_context for inspected Library video eligibility. It does not understand video content. Use consented image_analyze/approved Library facts separately. youtube_plan_prepare saves only an unapproved exact channel/video/future-time plan; generate proposed metadata from supplied or consented evidence and label it for review. Ask for rights, made-for-kids and synthetic-media declarations; never infer them. Google API tools require separate agentic OAuth consent and an explicit current-turn YouTube analytics request. youtube_analytics_summary shares selected unchanged native metric values and dates only; youtube_recommendations uses evidence from this turn. Do not calculate derived metrics, independent totals, averages, ratios, scores, rankings or predictions from API data. Discuss native observations with original metric names, source and date context and the person’s goals. Daily views cannot prove best posting hour or content causation. No chat tool approves, activates autopilot, publishes, deletes, changes consent or bypasses Google review.'


def register():
    """Idempotent extension binding; normal runtime owns model calls and metering."""
    from ..agent_runtime_v2 import specialists
    specs = [
        ('youtube_plan_context', contracts.READ, 'read', 'List this workspace’s eligible inspected Library videos and YouTube connections for a current YouTube request. Technical metadata only, no video understanding or private stored goals.',
         {'connectionId': {'type': 'string', 'pattern': _ID}, 'limit': {'type': 'integer'}}, plan_context),
        ('youtube_plan_prepare', contracts.CREATE_DRAFT, 'edit', 'Save a reviewable YouTube plan from an exact Library video and destination. Propose title/description from the person’s context. Requires current-turn human rights, made-for-kids and synthetic-media declarations. Never approves or publishes. Time is the person’s words or local YYYY-MM-DDTHH:MM in their current time zone.',
         {'connectionId': {'type': 'string', 'pattern': _ID, 'required': True}, 'assetId': {'type': 'string', 'pattern': _ASSET, 'required': True},
          'title': {'type': 'string', 'maxLength': 100, 'required': True}, 'description': {'type': 'string', 'maxLength': 5000, 'required': True},
          'privacyStatus': {'type': 'string', 'enum': ['private', 'public'], 'required': True}, 'when': {'type': 'string', 'maxLength': 120, 'required': True},
          'fold': {'type': 'integer'}, 'goal': {'type': 'string', 'maxLength': 1000}}, plan_prepare),
        ('youtube_analytics_summary', contracts.READ, 'read', 'Read a maximum 90-day explicit nonmonetary YouTube daily Analytics range. Requires the person explicitly asking for YouTube analytics this turn, exact separately authorized agentic client/lane and read+Analytics scopes. Returns at most 100 selected unchanged native metric observations with original column names and dates, never calculated metrics, revenue, free text or user identities.',
         {'connectionId': {'type': 'string', 'pattern': _ID, 'required': True}, 'startDate': {'type': 'string', 'maxLength': 10, 'required': True},
          'endDate': {'type': 'string', 'maxLength': 10, 'required': True}}, analytics_summary),
        ('youtube_recommendations', contracts.READ, 'read', 'Offer reviewable planning guidance using selected native observations already requested and retrieved this turn and the person’s goals. Never calculates metrics, scores, averages, rankings or predictions; never fetches, publishes or changes a calendar. Says when performance/content/hour evidence is unavailable.',
         {'connectionId': {'type': 'string', 'pattern': _ID, 'required': True}}, recommendations),
    ]
    for name, effect, right, description, schema, executor in specs:
        if name not in REGISTRY:
            register_tool(contracts.ToolSpec(name, effect, right, description, idempotent=effect == contracts.READ), schema,
                          'Prepared a YouTube plan' if effect == contracts.CREATE_DRAFT else 'Checked YouTube planning evidence')(executor)
        for scope in TOOL_SCOPES[name]:
            specialists.extend_scope(scope, [name])
    if _instructions not in specialists.INSTRUCTION_HOOKS:
        specialists.INSTRUCTION_HOOKS.append(_instructions)
