"""Bounded official methods, owned-resource checks and reviewable creator operations."""
import copy
import io
import json
import re
import secrets
import time
from datetime import date
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from .model import (METHODS, MANAGE, READ, ANALYTICS, MONEY, MEMBERS, YouTubeError,
                    api_error, has_scopes, merged_update, resource_id, rfc3339, _text, language)

ANALYTICS_REPORTS = {
    'daily': ('day', 'engagedViews,views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained,subscribersLost'),
    'content_type': ('day,creatorContentType', 'engagedViews,views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained,subscribersLost'),
    'geography': ('country', 'views,estimatedMinutesWatched'),
    'traffic': ('insightTrafficSourceType', 'views,estimatedMinutesWatched'),
    'device': ('deviceType', 'views,estimatedMinutesWatched'),
    'playback_location': ('insightPlaybackLocationType', 'views,estimatedMinutesWatched'),
    'demographics': ('ageGroup,gender', 'viewerPercentage'),
    'retention': ('elapsedVideoTimeRatio', 'audienceWatchRatio,relativeRetentionPerformance'),
    'playlist': ('day', 'playlistViews,playlistEstimatedMinutesWatched,playlistStarts'),
    'live': ('liveOrOnDemand', 'views,estimatedMinutesWatched'),
    'revenue': ('day', 'estimatedRevenue,estimatedAdRevenue,monetizedPlaybacks,playbackBasedCpm,cpm,adImpressions'),
}

ACTION_CAPABILITY = {
    'video.edit': 'metadata_edit', 'video.schedule': 'schedule', 'video.cancel_schedule': 'schedule', 'video.delete': 'delete',
    'thumbnail.set': 'thumbnail', 'caption.insert': 'captions', 'caption.update': 'captions', 'caption.delete': 'captions',
    'playlist.create': 'playlists', 'playlist.edit': 'playlists', 'playlist.delete': 'playlists',
    'playlist.add': 'playlists', 'playlist.remove': 'playlists', 'playlist.reorder': 'playlists',
    'podcast.enable': 'podcasts', 'podcast.disable': 'podcasts', 'playlist.image': 'podcasts',
    'comment.create': 'top_level_comment', 'comment.reply': 'reply', 'comment.edit': 'comment_edit',
    'comment.delete': 'comment_delete', 'comment.moderate': 'moderation',
    'broadcast.create': 'live_broadcast', 'broadcast.edit': 'live_broadcast', 'broadcast.delete': 'live_broadcast',
    'broadcast.bind': 'live_broadcast', 'broadcast.transition': 'live_broadcast',
    'stream.create': 'live_stream', 'stream.edit': 'live_stream', 'stream.delete': 'live_stream',
    'chat.send': 'live_chat_write', 'chat.poll': 'live_chat_write', 'chat.close_poll': 'live_chat_write',
    'chat.delete': 'live_moderation', 'chat.ban': 'live_moderation', 'chat.unban': 'live_moderation',
    'chat.add_moderator': 'live_moderation', 'chat.remove_moderator': 'live_moderation',
    'reporting.create': 'reporting', 'reporting.delete': 'reporting',
}
DESTRUCTIVE = frozenset(name for name in ACTION_CAPABILITY if name.endswith(('.delete', '.remove', '.unban', '.remove_moderator')))


def redacted(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if k.lower() in {'streamname', 'accesstoken', 'refreshtoken', 'authorization', 'uploadurl', 'clientsecret'} else redacted(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


def validate_image(raw, podcast=False):
    from PIL import Image, UnidentifiedImageError
    if not isinstance(raw, bytes) or not raw or len(raw) > 50_000_000:
        raise AlphaError('Podcast artwork and video thumbnails must be at most 50 MB under the current API media contract.', 400, code='youtube_invalid_metadata')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height, fmt = image.width, image.height, image.format
            image.verify()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise AlphaError('Use a valid JPEG or PNG image.', 400, code='youtube_invalid_metadata') from None
    if fmt not in ('JPEG', 'PNG') or (podcast and width != height):
        raise AlphaError('Podcast artwork must be square JPEG or PNG; thumbnails must be JPEG or PNG.', 400, code='youtube_invalid_metadata')
    # The minimum is documented for thumbnails; podcast image insert documents square geometry, not a mandatory pixel count.
    if not podcast and min(width, height) < 1:
        raise AlphaError('A thumbnail needs positive image dimensions.', 400, code='youtube_invalid_metadata')
    return 'image/jpeg' if fmt == 'JPEG' else 'image/png'


def validate_caption(track):
    if not isinstance(track, dict) or set(track) - {'id', 'language', 'name', 'isDraft', 'format', 'text'}:
        raise AlphaError('Unsupported caption track fields.', 400, code='youtube_invalid_metadata')
    language(track.get('language', 'en'))
    name = track.get('name', '')
    if not isinstance(name, str) or len(name) > 150 or type(track.get('isDraft', False)) is not bool:
        raise AlphaError('Use a caption name up to 150 characters and an explicit draft state.', 400, code='youtube_invalid_metadata')
    text = track.get('text')
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 1_000_000:
        raise AlphaError('Rafii accepts timed caption files up to 1 MB.', 400, code='youtube_invalid_metadata')
    fmt = track.get('format', 'srt')
    if fmt not in ('srt', 'vtt') or '-->' not in text or (fmt == 'vtt' and not text.lstrip('\ufeff').startswith('WEBVTT')):
        raise AlphaError('Provide a timed SRT or WebVTT file; automatic caption generation is not controlled by this API.', 400, code='youtube_invalid_metadata')
    return text.encode('utf-8'), 'text/vtt' if fmt == 'vtt' else 'application/x-subrip'


class YouTubeApi:
    def __init__(self, provider, grant, channel_id, *, clock=time.time, account_usage=None, chat_resource=None, on_error=None):
        self.provider, self.grant, self.channel_id, self.clock = provider, grant, resource_id(channel_id, 'channel'), clock
        self.account_usage = account_usage or (lambda *_: None)
        self.chat_resource = chat_resource
        self.on_error = on_error or (lambda *_: None)

    def call(self, method, params=None, body=None, *, data=None, mime=None, headers=None):
        rule = METHODS.get(method)
        if not rule:
            raise AlphaError('This operation is not in the audited official YouTube API contract.', 400)
        params = dict(params or {})
        allowed = rule['parameters']
        if set(params) - set(allowed) or any(k.startswith('onBehalfOf') for k in params):
            raise AlphaError('Unsupported YouTube method parameters.', 400, code='youtube_invalid_metadata')
        for key, constraint in allowed.items():
            if constraint.get('required') and key not in params:
                raise AlphaError('A required YouTube method parameter is missing.', 400, code='youtube_invalid_metadata')
            if key in params and constraint.get('enum') and params[key] not in constraint['enum']:
                raise AlphaError('Unsupported YouTube method parameter value.', 400, code='youtube_invalid_metadata')
            if key in params and constraint.get('type') == 'integer':
                value = params[key]
                if type(value) is not int or ('minimum' in constraint and value < int(constraint['minimum'])) or ('maximum' in constraint and value > int(constraint['maximum'])):
                    raise AlphaError('A YouTube integer parameter is outside the official range.', 400, code='youtube_invalid_metadata')
            if key in params and constraint.get('type') == 'boolean' and type(params[key]) is not bool:
                raise AlphaError('Use an explicit boolean API parameter.', 400, code='youtube_invalid_metadata')
        if not set(self.grant.get('scopes') or ()) & set(rule['scopes']):
            # Some public read methods also accept API keys, but this connector exclusively uses the channel's OAuth grant.
            raise YouTubeError('scope_missing', 'Grant the creator capability required for this official method.')
        base = 'https://youtubeanalytics.googleapis.com/' if method.startswith('analytics.') else 'https://youtubereporting.googleapis.com/' if method.startswith('reporting.') else 'https://www.googleapis.com/'
        path = rule['path']
        for key in list(params):
            if '{' + key + '}' in path:
                path = path.replace('{' + key + '}', resource_id(params.pop(key), 'resource'))
        if '{' in path:
            raise AlphaError('A resource path parameter is missing.', 400)
        kwargs = {}
        if headers:
            kwargs['headers'] = dict(headers)
        if data is not None:
            media = rule.get('mediaUpload') or {}
            if not media:
                raise AlphaError('This method does not accept media.', 400)
            path = media['protocols']['simple']['path'].lstrip('/')
            if body is None:
                params['uploadType'] = 'media'
                kwargs['data'] = data
                kwargs['headers'] = {**kwargs.get('headers', {}), 'Content-Type': mime}
            else:
                boundary = 'rafii_youtube_' + secrets.token_hex(16)
                params['uploadType'] = 'multipart'
                raw = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                    + json.dumps(body, ensure_ascii=False).encode() + f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()
                    + data + f'\r\n--{boundary}--\r\n'.encode())
                kwargs['data'] = raw
                kwargs['headers'] = {**kwargs.get('headers', {}), 'Content-Type': 'multipart/related; boundary=' + boundary}
        elif body is not None:
            kwargs['body'] = body
        encoded = {k: str(v).lower() if type(v) is bool else v for k, v in params.items()}
        url = base + path + ('?' + urlencode(encoded, doseq=True) if params else '')
        # Record attempted usage even on invalid/failed requests. This is app accounting, not the project's remaining quota.
        self.account_usage(method, rule['bucket'], rule['cost'])
        try:
            response = self.provider.api(self.grant['accessToken'], rule['httpMethod'], url, **kwargs)
        except AlphaError as error:
            read = rule['httpMethod'] == 'GET'
            raise YouTubeError('network', 'The official API result is unknown. Reconcile before another write.', status=503, retryable=read, ambiguous=not read) from error
        if response.get('status') not in (200, 201, 204):
            error = api_error(response, method, self.clock())
            self.on_error(error, method)
            raise error
        return response.get('body') if isinstance(response.get('body'), dict) else {}

    def owned(self, resource, identifier, part=None):
        identifier = resource_id(identifier, 'video' if resource == 'videos' else 'resource')
        parts = part or {'videos': 'snippet,status,contentDetails,processingDetails,localizations,recordingDetails',
                         'playlists': 'snippet,status,localizations', 'liveBroadcasts': 'snippet,status,contentDetails',
                         'liveStreams': 'snippet,cdn,status,contentDetails'}.get(resource, 'snippet')
        items = self.call(resource + '.list', {'id': identifier, 'part': parts}).get('items', [])
        if len(items) != 1 or items[0].get('id') != identifier or items[0].get('snippet', {}).get('channelId') != self.channel_id:
            raise AlphaError('This resource is not owned by the connected YouTube channel.', 403, code='youtube_resource_owner_mismatch')
        return items[0]

    def comment(self, identifier, own_comment=False):
        items = self.call('comments.list', {'id': resource_id(identifier, 'resource'), 'part': 'snippet'}).get('items', [])
        if len(items) != 1:
            raise AlphaError('Comment unavailable.', 404)
        comment = items[0]
        snippet = comment.get('snippet', {})
        self.owned('videos', snippet.get('videoId'))
        if own_comment and (snippet.get('authorChannelId') or {}).get('value') != self.channel_id:
            raise AlphaError('Only comments authored by the connected channel may be edited or deleted.', 403)
        return comment

    def owned_chat(self, chat_id, broadcast_id):
        current = self.owned('liveBroadcasts', broadcast_id)
        if current.get('snippet', {}).get('liveChatId') != resource_id(chat_id, 'resource'):
            raise AlphaError('This Live Chat does not belong to the approved broadcast.', 403)
        return current

    def analytics(self, kind, start, end, *, video_id=None, playlist_id=None, monetary_authorized=False):
        if kind not in ANALYTICS_REPORTS or (kind == 'revenue' and not monetary_authorized):
            raise AlphaError('This analytics report is unavailable or revenue access was not intentionally authorized.', 403)
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if first > last or (last - first).days > 730:
                raise ValueError()
        except (ValueError, TypeError):
            raise AlphaError('Choose a valid analytics date range of at most two years.', 400) from None
        dimensions, metrics = ANALYTICS_REPORTS[kind]
        filters = []
        if video_id:
            self.owned('videos', video_id)
            filters.append('video==' + video_id)
        if kind == 'retention' and not video_id:
            raise AlphaError('Retention needs one owned video.', 400)
        if kind == 'playlist':
            if not playlist_id:
                raise AlphaError('Playlist performance needs an owned playlist.', 400)
            self.owned('playlists', playlist_id)
            filters.append('playlist==' + playlist_id)
        params = {'ids': 'channel==' + self.channel_id, 'startDate': start, 'endDate': end, 'dimensions': dimensions, 'metrics': metrics, 'maxResults': 200}
        if filters:
            params['filters'] = ';'.join(filters)
        rows, body, complete = [], {}, False
        for page in range(5):
            body = self.call('analytics.reports.query', {**params, 'startIndex': page * 200 + 1})
            batch = body.get('rows') or []
            rows.extend(batch)
            if len(batch) < 200:
                complete = True
                break
        body['rows'] = rows
        return {'source': 'YouTube Analytics API', 'report': kind, 'channelId': self.channel_id,
                'coverage': {'startDate': start, 'endDate': end, 'complete': complete, 'rowBudget': 1000},
                'limitation': None if complete else 'The 1,000-row interactive budget was reached. Narrow the date range or use an authorized Reporting dataset.',
                'ingestedAt': self.clock(), 'data': body,
                'metrics': [{'name': metric, 'provenance': 'YouTube Analytics API'} for metric in metrics.split(',')],
                'classification': 'creatorContentType is provider-reported; absent rows are unavailable, not zero'}

    def plan(self, action, inputs, *, never_published=False):
        """Reads may resolve ownership; writes are returned as an exact review plan, never executed here."""
        if action not in ACTION_CAPABILITY or not isinstance(inputs, dict):
            raise AlphaError('Unsupported YouTube creator action.', 400)
        x = copy.deepcopy(inputs)
        method, params, body, media = None, {}, None, None
        ident = x.get('id')
        if action.startswith('video.'):
            current = self.owned('videos', ident)
            if action == 'video.delete':
                method, params = 'videos.delete', {'id': ident}
            else:
                patch = x.get('patch', {})
                if action == 'video.schedule':
                    if current.get('status', {}).get('privacyStatus') != 'private' or not never_published:
                        raise AlphaError('Native scheduling requires a private video with verified never-published history.', 409, code='youtube_invalid_scheduling_state')
                    patch = {'status': {'privacyStatus': 'private', 'publishAt': rfc3339(x.get('publishAt'), future=True)}}
                elif action == 'video.cancel_schedule':
                    patch = {'status': {'privacyStatus': 'private', 'publishAt': None}}
                body = merged_update('videos', current, patch)
                if body.get('status', {}).get('publishAt') and not never_published:
                    raise AlphaError('Scheduling needs verified never-published history.', 409, code='youtube_invalid_scheduling_state')
                from .model import validate_video
                snippet = {**current.get('snippet', {}), **body.get('snippet', {})}
                status = {**current.get('status', {}), **body.get('status', {})}
                check = {k: v for k, v in snippet.items() if k in ('title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage')}
                check.update({k: status[k] for k in ('privacyStatus', 'license', 'embeddable', 'publicStatsViewable') if k in status})
                check['madeForKids'] = status.get('selfDeclaredMadeForKids', False)
                check['containsSyntheticMedia'] = status.get('containsSyntheticMedia', False)
                if 'localizations' in body:
                    check['localizations'] = body['localizations']
                validate_video(check, [{'mime': 'video/mp4'}])
                for part, values in body.items():
                    if part in ('snippet', 'localizations'):
                        for key, value in (values.items() if part == 'snippet' else []):
                            if key in ('title', 'description'):
                                _text(value, key, 100 if key == 'title' else 5000, byte_limit=key == 'description', required=key == 'title')
                    if part == 'status' and values.get('publishAt'):
                        rfc3339(values['publishAt'], future=True)
                        if values.get('privacyStatus') != 'private':
                            raise AlphaError('A scheduled video must remain private until YouTube publishes it.', 400)
                method, params = 'videos.update', {'part': ','.join(k for k in body if k != 'id')}
        elif action == 'thumbnail.set':
            self.owned('videos', ident)
            method, params, media = 'thumbnails.set', {'videoId': ident}, {'assetId': x.get('assetId'), 'kind': 'thumbnail'}
        elif action.startswith('caption.'):
            self.owned('videos', x.get('videoId'))
            if action == 'caption.delete':
                tracks = self.call('captions.list', {'videoId': x['videoId'], 'part': 'snippet'}).get('items', [])
                if ident not in {item['id'] for item in tracks}:
                    raise AlphaError('Caption does not belong to this video.', 403)
                method, params = 'captions.delete', {'id': resource_id(ident, 'resource')}
            else:
                track = x.get('track', {})
                validate_caption(track)
                body = {'snippet': {'videoId': x['videoId'], 'language': track.get('language', 'en'), 'name': track.get('name', ''), 'isDraft': track.get('isDraft', False)}}
                if action == 'caption.update':
                    tracks = self.call('captions.list', {'videoId': x['videoId'], 'part': 'snippet'}).get('items', [])
                    if ident not in {item['id'] for item in tracks}:
                        raise AlphaError('Caption does not belong to this video.', 403)
                    body = {'id': resource_id(ident, 'resource'), 'snippet': {'isDraft': track.get('isDraft', False)}}
                method, params, media = 'captions.' + ('insert' if action == 'caption.insert' else 'update'), {'part': 'snippet'}, {'track': track, 'kind': 'caption'}
        elif action in ('playlist.create', 'playlist.edit', 'playlist.delete', 'podcast.enable', 'podcast.disable'):
            if action == 'playlist.create':
                snippet = x.get('snippet', {})
                _text(snippet.get('title'), 'Playlist title', 150, required=True)
                _text(snippet.get('description', ''), 'Playlist description', 5000, byte_limit=True)
                if set(snippet) - {'title', 'description', 'defaultLanguage'} or x.get('privacyStatus') not in ('private', 'unlisted', 'public'):
                    raise AlphaError('Review playlist metadata and visibility.', 400)
                method, params, body = 'playlists.insert', {'part': 'snippet,status'}, {'snippet': snippet, 'status': {'privacyStatus': x['privacyStatus']}}
            else:
                current = self.owned('playlists', ident)
                if action == 'playlist.delete':
                    method, params = 'playlists.delete', {'id': ident}
                else:
                    patch = x.get('patch', {})
                    if action.startswith('podcast.'):
                        if action == 'podcast.enable' and not self.call('playlistImages.list', {'playlistId': ident, 'part': 'snippet'}).get('items'):
                            raise AlphaError('Upload square podcast artwork before enabling podcast status.', 409)
                        patch = {'status': {'podcastStatus': 'enabled' if action == 'podcast.enable' else 'disabled'}}
                    body = merged_update('playlists', current, patch)
                    if body.get('status', {}).get('privacyStatus') not in (None, 'private', 'unlisted', 'public'):
                        raise AlphaError('Choose a supported playlist privacy.', 400)
                    if 'snippet' in body:
                        _text(body['snippet'].get('title'), 'Playlist title', 150, required=True)
                        _text(body['snippet'].get('description', ''), 'Playlist description', 5000, byte_limit=True)
                    if body.get('localizations'):
                        if not current.get('snippet', {}).get('defaultLanguage') and not body.get('snippet', {}).get('defaultLanguage'):
                            raise AlphaError('Playlist translations need a default language.', 400)
                        for locale, translation in body['localizations'].items():
                            language(locale)
                            _text(translation.get('title'), 'Localized playlist title', 150, required=True)
                            _text(translation.get('description', ''), 'Localized playlist description', 5000, byte_limit=True)
                    method, params = 'playlists.update', {'part': ','.join(k for k in body if k != 'id')}
        elif action == 'playlist.image':
            self.owned('playlists', x.get('playlistId'))
            method, params, body, media = 'playlistImages.insert', {'part': 'snippet'}, {'snippet': {'playlistId': x['playlistId'], 'type': 'hero'}}, {'assetId': x.get('assetId'), 'kind': 'podcast'}
        elif action in ('playlist.add', 'playlist.remove', 'playlist.reorder'):
            self.owned('playlists', x.get('playlistId'))
            if action == 'playlist.add':
                self.owned('videos', x.get('videoId'))
                existing = self.call('playlistItems.list', {'part': 'snippet', 'playlistId': x['playlistId'], 'videoId': x['videoId'], 'maxResults': 50}).get('items', [])
                if existing:
                    return {'action': action, 'capability': ACTION_CAPABILITY[action], 'noop': True, 'result': {'id': existing[0]['id'], 'alreadyPresent': True}}
                snippet = {'playlistId': x['playlistId'], 'resourceId': {'kind': 'youtube#video', 'videoId': x['videoId']}}
                if 'position' in x:
                    if type(x['position']) is not int or x['position'] < 0:
                        raise AlphaError('Playlist position must be a nonnegative integer.', 400)
                    snippet['position'] = x['position']
                method, params, body = 'playlistItems.insert', {'part': 'snippet'}, {'snippet': snippet}
            else:
                items = self.call('playlistItems.list', {'part': 'snippet', 'id': resource_id(ident, 'resource')}).get('items', [])
                if len(items) != 1 or items[0].get('snippet', {}).get('playlistId') != x['playlistId']:
                    raise AlphaError('This item does not belong to the approved playlist.', 403)
                if action == 'playlist.remove':
                    method, params = 'playlistItems.delete', {'id': ident}
                else:
                    if type(x.get('position')) is not int or x['position'] < 0:
                        raise AlphaError('Playlist position must be a nonnegative integer.', 400)
                    old = items[0]['snippet']
                    method, params, body = 'playlistItems.update', {'part': 'snippet'}, {'id': ident, 'snippet': {'playlistId': x['playlistId'], 'resourceId': old['resourceId'], 'position': x['position']}}
        elif action.startswith('comment.'):
            if action == 'comment.create':
                self.owned('videos', x.get('videoId'))
                method, params, body = 'commentThreads.insert', {'part': 'snippet'}, {'snippet': {'channelId': self.channel_id, 'videoId': x['videoId'], 'topLevelComment': {'snippet': {'textOriginal': _text(x.get('text'), 'Comment', 10000, required=True, allow_angles=True)}}}}
            else:
                current = self.comment(ident, own_comment=action in ('comment.edit', 'comment.delete'))
                if action == 'comment.reply':
                    if current.get('snippet', {}).get('parentId'):
                        raise AlphaError('Replies must target the top-level comment ID.', 400)
                    method, params, body = 'comments.insert', {'part': 'snippet'}, {'snippet': {'parentId': ident, 'textOriginal': _text(x.get('text'), 'Reply', 10000, required=True, allow_angles=True)}}
                elif action == 'comment.edit':
                    method, params, body = 'comments.update', {'part': 'snippet'}, {'id': ident, 'snippet': {'textOriginal': _text(x.get('text'), 'Comment', 10000, required=True, allow_angles=True)}}
                elif action == 'comment.delete':
                    method, params = 'comments.delete', {'id': ident}
                else:
                    if x.get('moderationStatus') not in ('published', 'heldForReview', 'rejected') or type(x.get('banAuthor', False)) is not bool:
                        raise AlphaError('Choose a supported moderation decision.', 400)
                    method, params = 'comments.setModerationStatus', {'id': ident, 'moderationStatus': x['moderationStatus'], 'banAuthor': x.get('banAuthor', False)}
        elif action.startswith(('broadcast.', 'stream.')):
            resource = 'liveBroadcasts' if action.startswith('broadcast.') else 'liveStreams'
            if action.endswith('.create'):
                patch = x.get('body', {})
                body = merged_update(resource, {'id': 'new'}, patch)
                body.pop('id')
                _text(body.get('snippet', {}).get('title'), 'Live title', 100 if resource == 'liveBroadcasts' else 128, required=True)
                _text(body.get('snippet', {}).get('description', ''), 'Live description', 5000 if resource == 'liveBroadcasts' else 10000)
                if resource == 'liveBroadcasts':
                    snippet, status = body.get('snippet', {}), body.get('status', {})
                    snippet['scheduledStartTime'] = rfc3339(snippet.get('scheduledStartTime'), future=True)
                    if snippet.get('scheduledEndTime'):
                        snippet['scheduledEndTime'] = rfc3339(snippet['scheduledEndTime'])
                        if snippet['scheduledEndTime'] <= snippet['scheduledStartTime']:
                            raise AlphaError('Live end must follow its start.', 400)
                    if status.get('privacyStatus') not in ('private', 'unlisted', 'public') or type(status.get('selfDeclaredMadeForKids')) is not bool:
                        raise AlphaError('Declare Live visibility and audience explicitly.', 400)
                else:
                    cdn = body.get('cdn', {})
                    if cdn.get('ingestionType') not in ('rtmp', 'dash', 'hls') or cdn.get('resolution') not in ('240p', '360p', '480p', '720p', '1080p', '1440p', '2160p', 'variable') or cdn.get('frameRate') not in ('30fps', '60fps', 'variable'):
                        raise AlphaError('Choose a documented ingestion type, resolution and frame rate.', 400)
                method, params = resource + '.insert', {'part': ','.join(body)}
            else:
                current = self.owned(resource, ident)
                if action.endswith('.delete'):
                    method, params = resource + '.delete', {'id': ident}
                elif action == 'broadcast.bind':
                    if x.get('streamId'):
                        self.owned('liveStreams', x['streamId'])
                    method, params = 'liveBroadcasts.bind', {'id': ident, 'part': 'id,snippet,contentDetails,status'}
                    if x.get('streamId'):
                        params['streamId'] = x['streamId']
                elif action == 'broadcast.transition':
                    target = x.get('broadcastStatus')
                    transitions = {'ready': {'testing', 'live'}, 'testing': {'live'}, 'live': {'complete'}}
                    if target not in transitions.get(current.get('status', {}).get('lifeCycleStatus'), set()):
                        raise AlphaError('This broadcast transition is not valid from its current YouTube state.', 409)
                    if target in ('testing', 'live'):
                        bound = current.get('contentDetails', {}).get('boundStreamId')
                        if not bound or self.owned('liveStreams', bound).get('status', {}).get('streamStatus') != 'active':
                            raise AlphaError('Testing and going Live require the bound stream to be active at YouTube.', 409, code='youtube_invalid_live_state')
                    method, params = 'liveBroadcasts.transition', {'id': ident, 'part': 'id,snippet,status,contentDetails', 'broadcastStatus': target}
                else:
                    body = merged_update(resource, current, x.get('patch', {}))
                    if resource == 'liveStreams':
                        if any(body.get('cdn', {}).get(k) != current.get('cdn', {}).get(k) for k in body.get('cdn', {})) or ('contentDetails' in body and body['contentDetails'].get('isReusable') != current.get('contentDetails', {}).get('isReusable')):
                            raise AlphaError('Ingestion settings and stream reuse cannot change after creation. Create and bind a separately approved stream.', 400)
                        # Update requires these immutable CDN values even when changing only the title.
                        body.pop('contentDetails', None)
                        body['cdn'] = {k: current.get('cdn', {})[k] for k in ('frameRate', 'resolution', 'ingestionType') if k in current.get('cdn', {})}
                    snippet = body.get('snippet', current.get('snippet', {}))
                    _text(snippet.get('title'), 'Live title', 100 if resource == 'liveBroadcasts' else 128, required=True)
                    _text(snippet.get('description', ''), 'Live description', 5000 if resource == 'liveBroadcasts' else 10000)
                    if resource == 'liveBroadcasts' and 'scheduledStartTime' in x.get('patch', {}).get('snippet', {}):
                        snippet['scheduledStartTime'] = rfc3339(snippet['scheduledStartTime'], future=True)
                    method, params = resource + '.update', {'part': ','.join(k for k in body if k != 'id')}
            if resource == 'liveBroadcasts' and body:
                snippet, status, details = body.get('snippet', {}), body.get('status', {}), body.get('contentDetails', {})
                if snippet.get('categoryId') and not re.fullmatch(r'\d+', str(snippet['categoryId'])):
                    raise AlphaError('Choose a documented YouTube video category.', 400)
                if 'privacyStatus' in status and status['privacyStatus'] not in ('private', 'unlisted', 'public'):
                    raise AlphaError('Choose a supported broadcast privacy.', 400)
                for key in ('selfDeclaredMadeForKids',):
                    if key in status and type(status[key]) is not bool:
                        raise AlphaError('Use an explicit audience declaration.', 400)
                for key in ('enableDvr', 'enableEmbed', 'recordFromStart', 'enableAutoStart', 'enableAutoStop'):
                    if key in details and type(details[key]) is not bool:
                        raise AlphaError('Use explicit Live configuration booleans.', 400)
                if snippet.get('scheduledEndTime'):
                    snippet['scheduledEndTime'] = rfc3339(snippet['scheduledEndTime'])
                    if snippet.get('scheduledStartTime') and snippet['scheduledEndTime'] <= snippet['scheduledStartTime']:
                        raise AlphaError('Scheduled Live end must follow its start.', 400)
        elif action.startswith('chat.'):
            self.owned_chat(x.get('liveChatId'), x.get('broadcastId'))
            if action in ('chat.delete', 'chat.close_poll', 'chat.unban', 'chat.remove_moderator'):
                kind = {'chat.delete': 'message', 'chat.close_poll': 'poll', 'chat.unban': 'ban', 'chat.remove_moderator': 'moderator'}[action]
                if not self.chat_resource or not self.chat_resource(kind, resource_id(ident, 'resource'), x['liveChatId']):
                    raise AlphaError('Read this chat or select a recorded creator action before moderating its exact resource. Its chat ownership is unproven.', 403, code='youtube_resource_owner_mismatch')
            if action in ('chat.send', 'chat.poll'):
                snippet = {'liveChatId': x['liveChatId'], 'type': 'textMessageEvent' if action == 'chat.send' else 'pollEvent'}
                if action == 'chat.send':
                    snippet['textMessageDetails'] = {'messageText': _text(x.get('text'), 'Chat message', 200, required=True, allow_angles=True)}
                else:
                    poll = x.get('poll', {})
                    if not isinstance(poll, dict) or len(poll.get('options', [])) not in (2, 3, 4):
                        raise AlphaError('A Live Chat poll needs two to four choices.', 400)
                    snippet['pollDetails'] = {'metadata': {'questionText': _text(poll.get('question'), 'Poll question', 100, required=True, allow_angles=True), 'options': [{'optionText': _text(t, 'Poll option', 35, required=True, allow_angles=True)} for t in poll['options']]}}
                method, params, body = 'liveChatMessages.insert', {'part': 'snippet'}, {'snippet': snippet}
            elif action == 'chat.close_poll':
                method, params = 'liveChatMessages.transition', {'id': resource_id(ident, 'resource'), 'status': 'closed', 'part': 'snippet'}
            elif action == 'chat.delete':
                method, params = 'liveChatMessages.delete', {'id': resource_id(ident, 'resource')}
            elif action == 'chat.ban':
                permanent = x.get('permanent') is True
                snippet = {'liveChatId': x['liveChatId'], 'type': 'permanent' if permanent else 'temporary', 'bannedUserDetails': {'channelId': resource_id(x.get('channelId'), 'channel')}}
                if not permanent:
                    duration = x.get('durationSeconds')
                    if type(duration) is not int or duration <= 0:
                        raise AlphaError('Use a positive timeout duration.', 400)
                    snippet['banDurationSeconds'] = duration
                method, params, body = 'liveChatBans.insert', {'part': 'snippet'}, {'snippet': snippet}
            elif action == 'chat.unban':
                method, params = 'liveChatBans.delete', {'id': resource_id(ident, 'resource')}
            elif action == 'chat.add_moderator':
                method, params, body = 'liveChatModerators.insert', {'part': 'snippet'}, {'snippet': {'liveChatId': x['liveChatId'], 'moderatorDetails': {'channelId': resource_id(x.get('channelId'), 'channel')}}}
            else:
                method, params = 'liveChatModerators.delete', {'id': resource_id(ident, 'resource')}
        elif action == 'reporting.create':
            types = self.call('reporting.reportTypes.list').get('reportTypes', [])
            if x.get('reportTypeId') not in {item.get('id') for item in types}:
                raise AlphaError('Select a report type available to this creator.', 400)
            method, body = 'reporting.jobs.create', {'reportTypeId': x['reportTypeId'], 'name': _text(x.get('name'), 'Report job name', 100, required=True)}
        elif action == 'reporting.delete':
            job = self.call('reporting.jobs.get', {'jobId': resource_id(ident, 'resource')})
            if job.get('id') != ident:
                raise AlphaError('Reporting job is not owned by this creator.', 403)
            method, params = 'reporting.jobs.delete', {'jobId': resource_id(ident, 'resource')}
        if params.get('part'):
            # PostgreSQL JSONB reorders object keys. API part order is semantically
            # irrelevant, but the exact review fingerprint must remain stable.
            params['part'] = ','.join(sorted(params['part'].split(',')))
        return {'action': action, 'capability': ACTION_CAPABILITY[action], 'method': method, 'params': params, 'body': body,
                **({'reportTypeId': job.get('reportTypeId')} if action == 'reporting.delete' else {}),
                **({'videoId': x.get('videoId')} if action.startswith('caption.') else {}),
                'media': media, 'destructive': action in DESTRUCTIVE or bool(x.get('banAuthor')),
                'targetId': ident or x.get('channelId') or x.get('videoId') or x.get('playlistId') or x.get('broadcastId') or self.channel_id}

    def execute(self, plan, *, media_reader=None):
        if plan.get('noop'):
            return plan['result']
        media = plan.get('media')
        raw, mime = None, None
        if media:
            if media['kind'] == 'caption':
                raw, mime = validate_caption(media['track'])
            elif media_reader:
                raw = media_reader(media['assetId'])
                mime = validate_image(raw, podcast=media['kind'] == 'podcast')
            else:
                raise AlphaError('Private workspace media storage is required.', 503)
        return self.call(plan['method'], plan.get('params'), plan.get('body'), data=raw, mime=mime)
