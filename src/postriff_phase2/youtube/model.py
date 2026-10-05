"""Audited 2026-10-05 API rules. Execution permission and real acceptance are separate."""
import copy
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError

SCOPE = 'https://www.googleapis.com/auth/'
READ, UPLOAD, MANAGE = (SCOPE + name for name in ('youtube.readonly', 'youtube.upload', 'youtube.force-ssl'))
ANALYTICS, MONEY, MEMBERS = (SCOPE + name for name in ('yt-analytics.readonly', 'yt-analytics-monetary.readonly', 'youtube.channel-memberships.creator'))
CONTRACT = json.loads(Path(__file__).with_name('official-contract.json').read_text())
METHODS = CONTRACT['methods']

# The scope listed is a minimum alternative, not a request for every scope in Google's method schema.
CAPABILITIES = {
    'connected': ('Google connection', (), None), 'identity': ('Channel identity', (READ,), None),
    'upload': ('Upload video', (UPLOAD,), None), 'private_publish': ('Private video', (UPLOAD,), None),
    'public_publish': ('Public video', (MANAGE,), 'public'), 'unlisted_publish': ('Unlisted video', (MANAGE,), 'public'),
    'schedule': ('YouTube scheduled publishing', (MANAGE,), 'public'), 'shorts': ('Shorts', (UPLOAD,), None),
    'thumbnail': ('Custom thumbnails', (UPLOAD,), 'thumbnail'), 'captions': ('Caption tracks', (MANAGE,), None),
    'metadata_edit': ('Edit video', (MANAGE,), None), 'delete': ('Delete video', (MANAGE,), None),
    'playlists': ('Playlists', (MANAGE,), None), 'podcasts': ('Podcast playlists', (MANAGE,), None),
    'comment_read': ('Read comments', (MANAGE,), None), 'top_level_comment': ('Post a comment', (MANAGE,), None),
    'reply': ('Reply to a comment', (MANAGE,), None), 'comment_edit': ('Edit own comment', (MANAGE,), None),
    'comment_delete': ('Delete own comment', (MANAGE,), None), 'moderation': ('Moderate comments', (MANAGE,), 'moderation'),
    'analytics': ('Creator analytics', (ANALYTICS,), None), 'shorts_analytics': ('Shorts analytics', (ANALYTICS,), None),
    'monetary_analytics': ('Revenue analytics', (MONEY,), 'monetary'), 'reporting': ('Bulk YouTube reports', (ANALYTICS,), None),
    'live_broadcast': ('Live broadcasts', (MANAGE,), 'live'), 'live_schedule': ('Schedule Live', (MANAGE,), 'live'),
    'live_stream': ('Live streams', (MANAGE,), 'live'), 'live_chat_read': ('Read Live Chat', (READ,), 'chat'),
    'live_chat_write': ('Write Live Chat', (MANAGE,), 'chat'), 'live_moderation': ('Moderate Live Chat', (MANAGE,), 'live_moderation'),
    'memberships': ('Channel memberships', (MEMBERS,), 'memberships'),
    'localization': ('Localized metadata', (MANAGE,), None), 'made_for_kids': ('Audience declaration', (UPLOAD,), None),
    'synthetic_media': ('Altered or synthetic media declaration', (UPLOAD,), None),
    'subscriber_notifications': ('Subscriber notification choice', (UPLOAD,), None),
    'community_posts': ('Community Post publishing', (), 'unsupported'), 'article': ('Native YouTube Article', (), 'unsupported'),
}


def has_scopes(granted, required):
    granted = set(granted or ())
    for scope in required:
        alternatives = {scope}
        if scope in (READ, UPLOAD):
            alternatives |= {MANAGE, SCOPE + 'youtube'}
        elif scope == MANAGE:
            alternatives.add(SCOPE + 'youtube')
        elif scope == ANALYTICS:
            # The monetary scope explicitly includes non-monetary Analytics reports.
            alternatives.add(MONEY)
        if not granted & alternatives:
            return False
    return True


def project_public_gate(provider):
    """A legacy REVIEWED boolean is never evidence of Google's distinct approval gates."""
    evidence = getattr(provider, 'project_evidence', {}) or {}
    for key in ('oauthVerification', 'youtubeComplianceAudit', 'publicUploadEligibility'):
        item = evidence.get(key, {})
        if not (item.get('status') == 'verified' and item.get('source') == 'google_platform'
                and item.get('reference') and fresh_evidence(item.get('observedAt'))):
            return False
    return bool(evidence.get('projectId') and evidence.get('clientId') == getattr(provider, 'client_id', None))


def fresh_evidence(value):
    """Rafii's conservative 30-day proof freshness rule; not a Google approval expiry."""
    try:
        if isinstance(value, str):
            observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if observed.tzinfo is None:
                if len(value) != 10:
                    return False
                observed = observed.replace(tzinfo=timezone.utc)
        elif type(value) in (int, float) and math.isfinite(value):
            observed = datetime.fromtimestamp(value, timezone.utc)
        else:
            return False
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        return -300 <= age <= 30 * 86400
    except (ValueError, OverflowError, OSError):
        return False


def capability_matrix(provider, granted=(), identity=None, evidence=None, authorizations=None):
    """No Full Access aggregate. Unknown eligibility and absent real evidence remain visible."""
    identity, evidence, authorizations = identity or {}, evidence or {}, authorizations or {}
    channel_id = identity.get('id') or identity.get('providerAccountId')
    enabled = bool(provider and getattr(provider, 'creator_enabled', False) and getattr(provider, 'execution_enabled', True))
    eligibility = identity.get('eligibility', {})
    result = {}
    for key, (label, scopes, gate) in CAPABILITIES.items():
        state, reason, usable = 'IMPLEMENTED / E2E NOT PROVEN', 'Real creator acceptance has not been proven.', enabled
        if gate == 'unsupported':
            state, reason, usable = 'UNSUPPORTED BY OFFICIAL API', 'No documented public write resource or method.', False
        elif gate in ('monetary', 'memberships') and authorizations.get(gate) is not True:
            state, reason, usable = 'NOT AUTHORIZED', 'Enable this sensitive capability intentionally and separately.', False
        elif not channel_id or not has_scopes(granted, scopes):
            state, reason, usable = 'NOT AUTHORIZED', 'Connect this channel or grant the named creator capability.', False
        elif gate == 'public' and not project_public_gate(provider):
            state, reason, usable = 'BLOCKED — GOOGLE APPROVAL', 'OAuth verification, YouTube project audit and public-upload eligibility need independent evidence.', False
        elif gate in ('thumbnail', 'live', 'chat', 'moderation', 'live_moderation', 'monetary', 'memberships') and eligibility.get(gate) is not True:
            state, reason, usable = 'BLOCKED — ACCOUNT ELIGIBILITY', 'Channel eligibility or action authority is unproven or unavailable.', False
        elif not enabled:
            reason, usable = 'Creator execution is disabled in this deployment.', False
        proof = evidence.get(key) or {}
        if (usable and proof.get('status') == 'PASS' and proof.get('execution') == 'real'
                and proof.get('channelId') == channel_id and proof.get('reference') and fresh_evidence(proof.get('verifiedAt'))):
            state, reason = 'READY', 'Supported by real official API acceptance evidence for this channel.'
        result[key] = {'label': label, 'state': state, 'canExecute': usable, 'officialSupported': gate != 'unsupported',
                       'reason': reason, 'evidence': proof if state == 'READY' else None}
    return result


def resource_id(value, kind='video'):
    patterns = {'video': r'[A-Za-z0-9_-]{11}', 'channel': r'UC[A-Za-z0-9_-]{22}',
                'resource': r'[A-Za-z0-9_.:-]{1,256}'}
    if not isinstance(value, str) or not re.fullmatch(patterns.get(kind, patterns['resource']), value):
        raise AlphaError('A valid YouTube resource ID is required.', 400, code='youtube_invalid_metadata')
    return value


def rfc3339(value, future=False, now=None):
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or (future and parsed <= (now or datetime.now(timezone.utc))):
            raise ValueError()
    except (ValueError, TypeError):
        raise AlphaError('Use a future publication time with a time zone.' if future else 'Use a date with a time zone.', 400, code='youtube_invalid_scheduling_state') from None
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _text(value, label, limit, *, byte_limit=False, required=False, allow_angles=False):
    if not isinstance(value, str) or (required and not value.strip()) or (not allow_angles and ('<' in value or '>' in value)):
        raise AlphaError(f'{label} must be text without < or >.', 400, code='youtube_invalid_metadata')
    try:
        encoded = value.encode('utf-8')
    except UnicodeError:
        raise AlphaError(f'{label} must contain valid Unicode text.', 400, code='youtube_invalid_metadata') from None
    length = len(encoded) if byte_limit else len(value)
    if length > limit:
        raise AlphaError(f'{label} exceeds {limit} ' + ('UTF-8 bytes.' if byte_limit else 'characters.'), 400, code='youtube_invalid_metadata')
    return value


def language(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', value):
        raise AlphaError('Use a valid language code.', 400, code='youtube_invalid_metadata')
    return value


def validate_video(options, media, description='', now=None):
    """Preserve exact content; the published body is never silently truncated or auto-declared."""
    if not isinstance(options, dict) or len(media) != 1 or not str(media[0].get('mime', '')).startswith('video/'):
        raise AlphaError('YouTube needs one verified video asset. Convert other content to video explicitly.', 409, code='youtube_video_required')
    allowed = {'mode', 'publicationMode', 'title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage', 'localizations',
               'privacyStatus', 'publishAt', 'license', 'embeddable', 'publicStatsViewable', 'madeForKids',
               'containsSyntheticMedia', 'recordingDate', 'notifySubscribers', 'thumbnailAssetId', 'captionTracks', 'playlistIds', 'podcastPlaylistId'}
    if set(options) - allowed:
        raise AlphaError('Unknown YouTube publishing option.', 400, code='youtube_invalid_metadata')
    out = copy.deepcopy(options)
    if 'publicationMode' in out and out['publicationMode'] not in ('now', 'schedule'):
        raise AlphaError('Choose publish after processing or schedule.', 400, code='youtube_invalid_metadata')
    if out.get('publicationMode') == 'now' and out.get('publishAt'):
        raise AlphaError('Immediate publication cannot also carry a native future schedule.', 400, code='youtube_invalid_scheduling_state')
    out['title'] = _text(options.get('title'), 'Title', 100, required=True)
    out['description'] = _text(options.get('description', description), 'Description', 5000, byte_limit=True)
    if out.get('privacyStatus') not in ('private', 'unlisted', 'public'):
        raise AlphaError('Choose private, unlisted or public visibility.', 400, code='youtube_invalid_metadata')
    for key in ('madeForKids', 'containsSyntheticMedia'):
        if type(out.get(key)) is not bool:
            raise AlphaError('Explicitly declare the audience and whether this video contains realistic altered or synthetic media.', 400, code='youtube_declaration_required')
    for key in ('embeddable', 'publicStatsViewable', 'notifySubscribers'):
        if key in out and type(out[key]) is not bool:
            raise AlphaError(f'{key} must be a boolean.', 400, code='youtube_invalid_metadata')
    if 'tags' in out:
        tags = out['tags']
        if not isinstance(tags, list) or any(not isinstance(t, str) or not t or '<' in t or '>' in t for t in tags):
            raise AlphaError('Tags must be nonempty text values.', 400, code='youtube_invalid_metadata')
        if sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(0, len(tags) - 1) > 500:
            raise AlphaError('Tags exceed YouTube’s combined 500-character limit, including separators and quoted spaces.', 400, code='youtube_invalid_metadata')
    if not re.fullmatch(r'[0-9]{1,10}', str(out.get('categoryId', '22'))):
        raise AlphaError('Choose a YouTube video category.', 400, code='youtube_invalid_metadata')
    out['categoryId'] = str(out.get('categoryId', '22'))
    for key in ('defaultLanguage', 'defaultAudioLanguage'):
        if key in out:
            language(out[key])
    if 'localizations' in out:
        if not out.get('defaultLanguage') or not isinstance(out['localizations'], dict) or len(out['localizations']) > 100:
            raise AlphaError('Localized metadata needs a default language and language-keyed translations.', 400, code='youtube_invalid_metadata')
        for locale, entry in out['localizations'].items():
            language(locale)
            if not isinstance(entry, dict) or set(entry) - {'title', 'description'}:
                raise AlphaError('A localization contains unsupported fields.', 400, code='youtube_invalid_metadata')
            _text(entry.get('title'), 'Localized title', 100, required=True)
            _text(entry.get('description', ''), 'Localized description', 5000, byte_limit=True)
    if out.get('license', 'youtube') not in ('youtube', 'creativeCommon'):
        raise AlphaError('Choose a supported YouTube license.', 400, code='youtube_invalid_metadata')
    if out.get('publishAt'):
        if out['privacyStatus'] != 'public':
            raise AlphaError('Native scheduling publishes publicly; choose public as the intended visibility.', 400, code='youtube_invalid_scheduling_state')
        out['publishAt'] = rfc3339(out['publishAt'], future=True, now=now)
    if 'recordingDate' in out:
        out['recordingDate'] = rfc3339(out['recordingDate'])
    mode = out.get('mode', 'video')
    if mode not in ('video', 'short'):
        raise AlphaError('Choose Video or Short for a video upload.', 400, code='youtube_invalid_metadata')
    if mode == 'short':
        asset = media[0]
        width, height, duration = asset.get('width'), asset.get('height'), asset.get('duration')
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in (width, height, duration)):
            raise AlphaError('Shorts need inspected video dimensions and duration.', 409, code='youtube_short_format_unknown')
        if width > height or duration > 180:
            raise AlphaError('Shorts must be square or vertical and at most three minutes long. Format eligibility does not prove YouTube classification.', 400, code='youtube_short_format_invalid')
    for key in ('playlistIds',):
        if key in out and (not isinstance(out[key], list) or len(out[key]) > 20):
            raise AlphaError('Choose at most 20 playlists.', 400, code='youtube_invalid_metadata')
        for playlist in out.get(key, []):
            resource_id(playlist, 'resource')
    if out.get('podcastPlaylistId'):
        resource_id(out['podcastPlaylistId'], 'resource')
    if not isinstance(out.get('captionTracks', []), list) or len(out.get('captionTracks', [])) > 20:
        raise AlphaError('Add at most 20 caption tracks.', 400, code='youtube_invalid_metadata')
    if out.get('thumbnailAssetId'):
        resource_id(out['thumbnailAssetId'], 'resource')
    for track in out.get('captionTracks', []):
        from .api import validate_caption
        validate_caption(track)
    return out


def upload_body(options):
    snippet = {key: options[key] for key in ('title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage') if key in options}
    status = {'privacyStatus': 'private', 'selfDeclaredMadeForKids': options['madeForKids'], 'containsSyntheticMedia': options['containsSyntheticMedia']}
    status.update({key: options[key] for key in ('license', 'embeddable', 'publicStatsViewable') if key in options})
    body = {'snippet': snippet, 'status': status}
    if options.get('localizations'):
        body['localizations'] = options['localizations']
    if options.get('recordingDate'):
        body['recordingDetails'] = {'recordingDate': options['recordingDate']}
    return body


MUTABLE = {
    'videos': {'snippet': {'title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage'},
               'status': {'privacyStatus', 'publishAt', 'license', 'embeddable', 'publicStatsViewable', 'selfDeclaredMadeForKids', 'containsSyntheticMedia'},
               'recordingDetails': {'recordingDate'}, 'localizations': None},
    'playlists': {'snippet': {'title', 'description', 'defaultLanguage'}, 'status': {'privacyStatus', 'podcastStatus'}, 'localizations': None},
    'liveBroadcasts': {'snippet': {'title', 'description', 'categoryId', 'scheduledStartTime', 'scheduledEndTime'},
                       'status': {'privacyStatus', 'selfDeclaredMadeForKids'},
                       'contentDetails': {'enableDvr', 'enableEmbed', 'recordFromStart', 'enableAutoStart', 'enableAutoStop', 'latencyPreference', 'monitorStream', 'projection', 'closedCaptionsType'}},
    'liveStreams': {'snippet': {'title', 'description'}, 'cdn': {'frameRate', 'resolution', 'ingestionType'}, 'contentDetails': {'isReusable'}},
}


def merged_update(resource, current, patch):
    allowed = MUTABLE.get(resource)
    if not allowed or not isinstance(patch, dict) or not patch or set(patch) - set(allowed):
        raise AlphaError('Unsupported editable resource fields.', 400, code='youtube_invalid_metadata')
    result = {'id': resource_id(current.get('id'), 'video' if resource == 'videos' else 'resource')}
    for part, value in patch.items():
        if not isinstance(value, dict) or (allowed[part] is not None and set(value) - allowed[part]):
            raise AlphaError('Unsupported editable fields.', 400, code='youtube_invalid_metadata')
        kept = copy.deepcopy(current.get(part) or {})
        if allowed[part] is not None:
            kept = {k: v for k, v in kept.items() if k in allowed[part]}
        for key, item in value.items():
            if item is None:
                kept.pop(key, None)  # An explicit null is a deliberate removal, unlike omission.
            elif part == 'localizations' and isinstance(item, dict):
                kept[key] = {**kept.get(key, {}), **item}
            else:
                kept[key] = item
        result[part] = kept
    return result


def lifecycle(video):
    status, processing = video.get('status', {}), video.get('processingDetails', {})
    upload = status.get('uploadStatus')
    if upload in ('failed', 'rejected', 'deleted') or processing.get('processingStatus') in ('failed', 'terminated'):
        return {'stage': 'failed', 'errorCategory': 'rejection' if upload == 'rejected' else 'processing_failure',
                'providerReason': status.get('rejectionReason') or status.get('failureReason') or processing.get('processingFailureReason')}
    if upload != 'processed' or processing.get('processingStatus') not in (None, 'succeeded'):
        return {'stage': 'processing', 'published': False}
    privacy = status.get('privacyStatus')
    if status.get('publishAt') and privacy == 'private':
        return {'stage': 'native_scheduled', 'publishAt': status['publishAt'], 'published': False, 'sourceOfTruth': 'YouTube Data API'}
    return {'stage': 'published' if privacy in ('public', 'unlisted') else 'processed_private', 'privacyStatus': privacy,
            'published': privacy in ('public', 'unlisted'), 'sourceOfTruth': 'YouTube Data API'}


def quota_reset(now):
    local = datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles'))
    return datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=local.tzinfo).timestamp()


class YouTubeError(AlphaError):
    def __init__(self, category, message, *, status=409, retryable=False, ambiguous=False, retry_at=None):
        super().__init__(message, status, code='youtube_' + category)
        self.category, self.retryable, self.ambiguous, self.retry_at = category, retryable, ambiguous, retry_at


def api_error(response, method, now):
    status = response.get('status', 502)
    body = response.get('body') if isinstance(response.get('body'), dict) else {}
    error = body.get('error') if isinstance(body.get('error'), dict) else {}
    reasons = {x.get('reason') for x in error.get('errors', []) if isinstance(x, dict)}
    if reasons & {'quotaExceeded', 'dailyLimitExceeded', 'dailyLimitExceededUnreg'}:
        return YouTubeError('quota', 'YouTube project quota is exhausted. Further retries are held until quota is available.', retry_at=quota_reset(now))
    if 'uploadLimitExceeded' in reasons:
        return YouTubeError('upload_limit', 'This channel has reached its upload limit. Review channel eligibility before retrying.')
    if status == 401 or reasons & {'authError', 'invalidCredentials', 'youtubeSignupRequired'}:
        return YouTubeError('revoked_oauth', 'Reconnect this YouTube channel; authorization is unavailable.')
    if reasons & {'accessNotConfigured', 'forbidden', 'insufficientPermissions'}:
        return YouTubeError('project_restriction' if 'accessNotConfigured' in reasons else 'scope_missing', 'The Google project or granted creator permission does not allow this operation.')
    if reasons & {'liveStreamingNotEnabled', 'livePermissionBlocked', 'ineligible', 'forbiddenPrivacySetting', 'forbiddenBroadcast'}:
        return YouTubeError('channel_restriction', 'The connected channel is not eligible for this operation.')
    if reasons & {'invalidPublishAt', 'invalidPrivacySetting', 'invalidTransition', 'redundantTransition'}:
        return YouTubeError('invalid_scheduling_state', 'YouTube rejected this schedule or lifecycle transition. Reconcile the current resource before changing it.')
    read = method.endswith('.list') or method.endswith('.get') or method == 'analytics.reports.query'
    if status == 429 or reasons & {'rateLimitExceeded', 'userRateLimitExceeded'}:
        return YouTubeError('rate_limit', 'YouTube rate limited this operation. Wait before another request.', retryable=read)
    if status >= 500:
        return YouTubeError('network', 'YouTube did not return a conclusive result. Reconcile before repeating a write.', status=503, retryable=read, ambiguous=not read)
    if status == 404:
        return YouTubeError('resource_unavailable', 'The YouTube resource is unavailable.', status=404)
    return YouTubeError('invalid_metadata' if status == 400 else 'permission', 'YouTube rejected the metadata or action authority. Review the approved resource and settings.')
