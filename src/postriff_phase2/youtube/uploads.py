"""Durable resumable upload. Every uncertain chunk is probed before sending more bytes."""
import copy
import hashlib
import json
import re
import time
from urllib.parse import urlencode, urlsplit

from postriff_alpha.domain import AlphaError
from .model import METHODS, YouTubeError, api_error, resource_id, upload_body, validate_video, lifecycle

CHUNK_ALIGNMENT = 256 * 1024
CHUNK_SIZE = 8 * 1024 * 1024  # matches the private-storage range ceiling; fixed memory per lease
MAX_CHUNK_SIZE = CHUNK_SIZE


def configured_chunk_size(value=None):
    try:
        result = CHUNK_SIZE if value is None else int(value)
    except (ValueError, TypeError, OverflowError):
        result = 0
    if isinstance(value, bool) or not CHUNK_ALIGNMENT <= result <= MAX_CHUNK_SIZE or result % CHUNK_ALIGNMENT:
        raise AlphaError('YouTube upload chunks must be aligned to 256 KiB and at most 8 MiB.', 503, code='youtube_chunk_configuration')
    return result


def session_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme == 'https' and parsed.hostname == 'www.googleapis.com' and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and not parsed.fragment
                and parsed.path == '/upload/youtube/v3/videos' and 'upload_id=' in parsed.query):
            return url
    except (ValueError, TypeError):
        pass
    raise AlphaError('YouTube returned an invalid resumable session address. No media was sent.', 502, code='youtube_invalid_upload_session')


def upload_view(state):
    return {key: copy.deepcopy(state.get(key)) for key in ('stage', 'bytesSent', 'totalBytes', 'videoId', 'publishAt',
            'privacyStatus', 'processing', 'steps', 'errorCategory', 'retryAt', 'cancelRequested', 'quotaDelay') if key in state}


class UploadEngine:
    """Journal is server-only: load/save and seal/unseal use the shared encrypted credential vault.

    Each step sends at most one chunk, within the hosted worker's time budget. A crash after acceptance is
    recovered using the same session URL. No title/time heuristic can identify an ambiguous upload.
    """
    def __init__(self, journal, api_factory, media_reader, *, clock=time.time, finalize=None, account_usage=None, chunk_size=None):
        self.journal, self.api_factory, self.media_reader, self.clock = journal, api_factory, media_reader, clock
        self.finalize = finalize
        self.account_usage = account_usage
        self.chunk_size = configured_chunk_size(chunk_size)

    def _save(self, key, state):
        state['updatedAt'] = self.clock()
        self.journal.save(key, state)

    def _receipt(self, state):
        stage = state['stage']
        view = upload_view(state)
        result = {'state': 'provider_accepted', 'confirmed': 'YouTube upload is in progress; bytes uploaded are not publication.',
                  'progress': {'version': 2, **view}, 'reference': state.get('videoId')}
        if stage == 'failed':
            result.update(state='failed', confirmed='Upload validation or provider processing failed. Review the recorded error category.')
            if (state.get('processing') or {}).get('stage') == 'failed':
                result['verification'] = 'provider_lookup'
        elif stage in ('outcome_unknown', 'session_expired'):
            result.update(state='uncertain', confirmed='The upload outcome needs reconciliation. This operation will never open a replacement upload automatically.')
        elif stage == 'canceled':
            result.update(state='canceled', confirmed='Upload canceled. Any video already accepted by YouTube remains private; deletion requires separate approval.')
        elif stage == 'held':
            result.update(state='held', confirmed='The creator operation is held. Review the permission, quota or independent post-upload step.')
        elif stage == 'quota_delayed':
            result.update(confirmed='Capacity controls delayed this operation before a provider request. Rafii will resume this same approved journal after the recorded retry time; it has not published.')
        elif stage == 'native_scheduled':
            result.update(confirmed='YouTube accepted the native publication schedule. The video is still private, not published.')
        elif stage in ('processed_private', 'published'):
            result.update(state='verified', verification='provider_lookup',
                          confirmed='YouTube processing and the exact approved visibility were verified.' if stage == 'published' else 'YouTube processing and private visibility were verified; this is not a public publication.',
                          url='https://www.youtube.com/watch?v=' + state['videoId'])
        return result

    def step(self, manifest, *, cancel=False, allow_initialize=True):
        key = (manifest['workspaceId'], manifest['channelId'], manifest['idempotencyKey'])
        fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.journal.lock(key):
            state = self.journal.load(key)
            if state and state.get('manifestDigest') != fingerprint:
                raise AlphaError('The upload key was reused for different approved content.', 409, code='youtube_idempotency_conflict')
            if not state:
                if not allow_initialize or cancel:
                    return {'state': 'held', 'confirmed': 'The durable upload journal is unavailable. Reconciliation cannot initiate a replacement upload.',
                            'progress': {'version': 2, 'stage': 'held', 'errorCategory': 'youtube_missing_upload_journal'}}
                options = validate_video(manifest.get('publishOptions') or {}, manifest.get('media') or [], manifest.get('payload', {}).get('text', ''))
                asset = manifest['media'][0]
                total = asset.get('bytes') or asset.get('size')
                if type(total) is not int or total <= 0 or total > 256 * 1024**3:
                    raise AlphaError('The verified video size is missing or exceeds YouTube’s 256 GB upload limit.', 400)
                state = {'version': 2, 'manifestDigest': fingerprint, 'stage': 'validating', 'bytesSent': 0,
                         'totalBytes': total, 'options': options, 'assetId': asset['id'], 'mime': asset['mime'],
                         'createdAt': self.clock(), 'steps': {}, 'neverPublished': True,
                         'attachments': copy.deepcopy(manifest.get('youtubeAssets', []))}
                self._save(key, state)
            if cancel:
                if state.get('videoId'):
                    try:
                        api = self.api_factory(manifest)
                        current = api.owned('videos', state['videoId'])
                        status = current.get('status') or {}
                        if status.get('privacyStatus') in ('public', 'unlisted'):
                            observed = lifecycle(current)
                            state.update(observed, privacyStatus=status['privacyStatus'], neverPublished=False, processing=observed)
                            self._save(key, state)
                            result = self._receipt(state)
                            result['confirmed'] = 'YouTube already published this video. The future operation can no longer be canceled; changing visibility needs a separate review.'
                            return result
                        if status.get('publishAt'):
                            from .model import merged_update
                            state['cancelRequested'] = True
                            state['steps']['cancelSchedule'] = {'status': 'started'}
                            self._save(key, state)
                            api.call('videos.update', {'part': 'status'}, merged_update('videos', current, {'status': {'publishAt': None, 'privacyStatus': 'private'}}))
                            observed = api.owned('videos', state['videoId'])
                            if observed.get('status', {}).get('publishAt') or observed.get('status', {}).get('privacyStatus') != 'private':
                                raise YouTubeError('invalid_scheduling_state', 'YouTube did not confirm cancellation of the native schedule.', ambiguous=True)
                            state['steps']['cancelSchedule'] = {'status': 'verified', 'source': 'YouTube Data API'}
                    except AlphaError as error:
                        if getattr(error, 'category', None) == 'revoked_oauth' or error.code == 'youtube_revoked_oauth':
                            return {'state': 'held', 'confirmed': 'YouTube authorization was revoked. Authorized content was purged; reconnect and review.',
                                    'progress': {'version': 2, 'stage': 'held', 'errorCategory': 'revoked_oauth'}}
                        state.update(stage='held', cancelRequested=True, errorCategory=getattr(error, 'category', 'cancel_schedule_unproven'))
                        self._save(key, state)
                        return self._receipt(state)
                state.update(stage='canceled', cancelRequested=True)
                self._save(key, state)
                return self._receipt(state)
            if state['stage'] in ('failed', 'held', 'canceled', 'session_expired'):
                return self._receipt(state)
            if state.get('retryAt', 0) > self.clock():
                return self._receipt(state)
            if state['stage'] == 'quota_delayed':
                state['stage'] = state.pop('resumeStage', 'validating')
                state.pop('quotaDelay', None)
                state.pop('errorCategory', None)
            api = None
            try:
                api = self.api_factory(manifest)
                usage = self.account_usage or api.account_usage
                if state.get('videoId'):
                    video = api.owned('videos', state['videoId'])
                    observed = lifecycle(video)
                    state['processing'] = observed
                    if observed['stage'] == 'failed':
                        state.update(observed)
                    elif observed['stage'] == 'processing':
                        state.update(stage='processing', retryAt=self.clock() + 60)
                    elif self.finalize:
                        state = self.finalize(key, state, video, api, self._save)
                    else:
                        state.update(observed)
                    self._save(key, state)
                    return self._receipt(state)
                if not state.get('sessionCiphertext'):
                    if state['stage'] in ('session_open_attempted', 'outcome_unknown'):
                        state['stage'] = 'outcome_unknown'
                        self._save(key, state)
                        return self._receipt(state)
                    body = upload_body(state['options'])
                    params = {'uploadType': 'resumable', 'part': ','.join(body),
                              'notifySubscribers': str(state['options'].get('notifySubscribers', True)).lower()}
                    rule = METHODS['videos.insert']
                    # Admission may deny without a network request. Reserve first,
                    # then commit the remote intent; a denial is not an ambiguous POST.
                    usage('videos.insert', rule['bucket'], rule['cost'])
                    state['stage'] = 'session_open_attempted'
                    self._save(key, state)  # committed before any remote initiation
                    response = api.provider.api(api.grant['accessToken'], 'POST', api.provider.UPLOAD + '?' + urlencode(params),
                        headers={'X-Upload-Content-Length': str(state['totalBytes']), 'X-Upload-Content-Type': state['mime']}, body=body)
                    if response.get('status') not in (200, 201):
                        raise api_error(response, 'videos.insert', self.clock())
                    url = session_url(response.get('headers', {}).get('location'))
                    state['sessionCiphertext'], state['sessionKeyId'] = self.journal.seal(url)
                    state['stage'] = 'uploading'
                    self._save(key, state)  # URL durable before any video bytes leave the server
                url = session_url(self.journal.unseal(state['sessionCiphertext'], state['sessionKeyId']))
                usage('resumable.status', 'videoUploads', None)
                response = api.provider.api(api.grant['accessToken'], 'PUT', url,
                    headers={'Content-Type': state['mime'], 'Content-Length': '0', 'Content-Range': f"bytes */{state['totalBytes']}"}, data=b'')
                if response.get('status') in (200, 201):
                    self._completed(key, state, response)
                    return self._receipt(state)
                if response.get('status') in (404, 410):
                    state.update(stage='session_expired', errorCategory='upload_session_expired')
                    self._save(key, state)
                    return self._receipt(state)
                if response.get('status') != 308:
                    raise api_error(response, 'resumable.status', self.clock())
                ranged = response.get('headers', {}).get('range')
                matched = re.fullmatch(r'bytes=0-(\d+)', str(ranged)) if ranged else None
                if ranged and not matched:
                    raise YouTubeError('invalid_upload_session', 'YouTube returned an invalid resume range.', ambiguous=True)
                offset = int(matched[1]) + 1 if matched else 0
                if offset < 0 or offset > state['totalBytes']:
                    raise YouTubeError('invalid_upload_session', 'YouTube returned a resume offset outside the approved file.', ambiguous=True)
                state['bytesSent'] = offset
                self._save(key, state)
                if offset == state['totalBytes']:
                    state.update(stage='outcome_unknown')  # await the final resource response; never restart
                    self._save(key, state)
                    return self._receipt(state)
                size = min(self.chunk_size, state['totalBytes'] - offset)
                chunk = self.media_reader(manifest, offset, size)
                if not isinstance(chunk, bytes) or len(chunk) != size:
                    raise AlphaError('The approved private video asset changed or is unavailable.', 409, code='youtube_media_changed')
                usage('resumable.chunk', 'videoUploads', None)
                response = api.provider.api(api.grant['accessToken'], 'PUT', url,
                    headers={'Content-Type': state['mime'], 'Content-Length': str(size),
                             'Content-Range': f"bytes {offset}-{offset + size - 1}/{state['totalBytes']}"}, data=chunk)
                if response.get('status') in (200, 201):
                    self._completed(key, state, response)
                elif response.get('status') == 308:
                    # Acknowledgement is not assumed. The next step queries the authoritative Range again.
                    state.update(stage='uploading', retryAt=self.clock() + 1, transientFailures=0)
                    self._save(key, state)
                else:
                    raise api_error(response, 'resumable.chunk', self.clock())
            except (YouTubeError, AlphaError) as error:
                category = getattr(error, 'category', None) or ('network' if error.status >= 500 else error.code or 'invalid_metadata')
                if api:
                    api.on_error(error, 'videos.insert' if state['stage'] == 'session_open_attempted' else 'resumable.reconcile')
                if category in ('revoked_oauth', 'youtube_revoked_oauth'):
                    # The error callback already purged the journal. Never recreate authorized data after revocation.
                    return {'state': 'held', 'confirmed': 'YouTube authorization was revoked. Authorized content was purged; reconnect and review.',
                            'progress': {'version': 2, 'stage': 'held', 'errorCategory': 'revoked_oauth'}}
                state['errorCategory'] = category
                if category == 'capacity_delay':
                    state.update(resumeStage=state['stage'], stage='quota_delayed', retryAt=error.retry_at,
                                 quotaDelay={'reason': getattr(error, 'capacity_reason', 'capacity'), 'source': 'Rafii pre-request admission control',
                                             'providerRequestSent': False})
                elif category in ('quota', 'upload_limit', 'scope_missing', 'revoked_oauth', 'channel_restriction', 'project_restriction', 'youtube_capability_blocked', 'youtube_revoked_oauth',
                                   'youtube_oauth_binding_required', 'youtube_oauth_binding_changed'):
                    state['stage'] = 'held'
                    state['retryAt'] = getattr(error, 'retry_at', None)
                elif (state.get('sessionCiphertext') or state.get('videoId')) and (getattr(error, 'ambiguous', False) or category in ('network', 'rate_limit')):
                    attempts = state.get('transientFailures', 0) + 1
                    state.update(stage='outcome_unknown', transientFailures=attempts, retryAt=self.clock() + min(300, 2 ** min(attempts, 8)))
                    if attempts >= 6:
                        state['stage'] = 'held'
                elif state['stage'] == 'session_open_attempted' and category == 'network':
                    state['stage'] = 'outcome_unknown'
                elif category == 'rate_limit':
                    state['stage'] = 'held'
                else:
                    state['stage'] = 'failed'
                self._save(key, state)
            return self._receipt(state)

    def _completed(self, key, state, response):
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        try:
            video_id = resource_id(body.get('id'))
        except AlphaError:
            raise YouTubeError('invalid_upload_session', 'YouTube accepted the bytes but did not return a valid Video ID. Reconcile the same session; never create a replacement.', ambiguous=True) from None
        state.update(videoId=video_id, stage='uploaded_private', bytesSent=state['totalBytes'],
                     uploadReceipt={'videoId': body['id'], 'receivedAt': self.clock(), 'source': 'YouTube Data API', 'httpStatus': response['status']})
        state.pop('sessionCiphertext', None)
        state.pop('sessionKeyId', None)
        self._save(key, state)
