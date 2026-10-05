"""Durable upload adapters for the remaining official social APIs.

Upload session URLs are encrypted. Each forward mutation requires the worker's
persisted intent; ambiguous post creation is never replayed. YouTube alone resumes
an ambiguous byte transfer using its documented resumable status query.
"""
import base64
import json
import re
import secrets
from urllib.parse import quote, urlencode, urlsplit
from postriff_alpha.domain import AlphaError
from .official_publishers import _unknown, _upload_host

CHUNK_BYTES = 4 * 1024 * 1024


def multipart(parameters, raw, mime):
    boundary = 'rafii-' + secrets.token_hex(16)
    segments = []
    for key, value in parameters.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key) or not isinstance(value, str) or '\r' in value or '\n' in value:
            raise AlphaError('Invalid media upload form.', 502)
        segments.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    segments += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="media.mp4"\r\nContent-Type: {mime}\r\n\r\n'.encode(), raw, f'\r\n--{boundary}--\r\n'.encode()]
    return b''.join(segments), 'multipart/form-data; boundary=' + boundary


class AdditionalPublishers:
    def __init__(self, owner): self.owner, self.host = owner, owner.host

    def seal(self, upload):
        ciphertext, key = self.host.oauth.vault.encrypt(json.dumps(upload, separators=(',', ':')))
        return {'ciphertext': ciphertext, 'keyId': key}

    def opened(self, job):
        upload = job.get('providerUpload') or {}
        return json.loads(self.host.oauth.vault.decrypt(upload['ciphertext'], upload['keyId']))

    def progress(self, stage, identifier, assets=(), upload=None):
        result = self.owner._progress(stage, str(identifier), assets)
        if upload is not None: result['providerUpload'] = self.seal(upload)
        return result

    def advance(self, manifest, job, action, provider, grant):
        method = getattr(self, provider.id, None)
        if not method: return {'state': 'held', 'confirmed': 'This official format is not implemented'}
        return method(manifest, job, action, provider, grant)

    def youtube(self, m, job, action, p, grant):
        token, options = grant['accessToken'], m.get('publishOptions') or {}
        asset = m['media'][0]
        if action == 'create':
            if options.get('privacyStatus') in ('public','unlisted') or options.get('publishAt'):
                proof = getattr(p,'official_approvals',{}).get('youtube_public_upload',{})
                if proof.get('state') != 'approved' or not proof.get('evidenceRef') or proof.get('appId') != p.client_id:
                    return {'state':'held','confirmed':'Public/unlisted/native-scheduled publishing: BLOCKED — YOUTUBE COMPLIANCE AUDIT. Google OAuth verification is a separate release gate.'}
            status = {'privacyStatus': options['privacyStatus'], 'selfDeclaredMadeForKids': options['madeForKids']}
            if 'containsSyntheticMedia' in options: status['containsSyntheticMedia'] = options['containsSyntheticMedia']
            if options.get('publishAt'): status.update(privacyStatus='private', publishAt=options['publishAt'])
            body = {'snippet': {'title': options['title'], 'description': m['payload']['text'], 'categoryId': options.get('categoryId', '22')}, 'status': status}
            if options.get('localizations'): body['localizations'] = options['localizations']
            query = {'uploadType': 'resumable', 'part': ','.join(body), 'notifySubscribers': str(options.get('notifySubscribers', True)).lower()}
            response = p.api(token, 'POST', p.UPLOAD + '?' + urlencode(query), headers={'X-Upload-Content-Type': asset['mime'], 'X-Upload-Content-Length': str(asset['bytes'])}, body=body)
            location = (response.get('headers') or {}).get('location')
            if response.get('status') not in (200, 201) or not location: return _unknown('YouTube upload initialization inconclusive')
            _upload_host(location, ('www.googleapis.com',))
            return self.progress('upload_session', 'youtube_upload', upload={'url': location, 'offset': 0, 'total': asset['bytes']})
        upload = self.opened(job)
        location = _upload_host(upload['url'], ('www.googleapis.com',))
        total, offset = upload['total'], upload['offset']
        if action == 'status':
            response = p.api(token, 'PUT', location, headers={'Content-Length': '0', 'Content-Range': f'bytes */{total}'}, data=b'')
        elif action == 'upload':
            raw = self.owner.bytes(m, asset)
            end = min(total, offset + 8*1024*1024)
            if not 0 <= offset < end <= len(raw): return _unknown('YouTube upload offset is invalid')
            response = p.api(token, 'PUT', location, headers={'Content-Type': asset['mime'], 'Content-Length': str(end-offset), 'Content-Range': f'bytes {offset}-{end-1}/{total}'}, data=raw[offset:end])
        else: return _unknown('Invalid YouTube upload transition')
        status, body = response.get('status'), response.get('body') or {}
        if status in (200, 201) and re.fullmatch(r'[A-Za-z0-9_-]{11}', str(body.get('id', ''))):
            return {'state': 'provider_accepted', 'reference': body['id'], 'confirmed': 'YouTube upload complete; processing, visibility and schedule need provider read-back'}
        if status == 308:
            extent = (response.get('headers') or {}).get('range')
            if extent is None:
                position = 0
            elif re.fullmatch(r'bytes=0-\d+', extent): position = int(extent.split('-')[1])+1
            else: return _unknown('YouTube resumable status did not give a valid byte range')
            if position < offset or position > total: return _unknown('YouTube resumable offset regressed or exceeded the approved file')
            upload['offset'] = position
            return self.progress('upload_session', 'youtube_upload', upload=upload)
        return _unknown('YouTube upload session requires reconciliation; no new upload started')

    def pinterest(self, m, job, action, p, grant):
        token, media, options = grant['accessToken'], m.get('media') or [], m.get('publishOptions') or {}
        asset = media[0]
        video = asset['mime'].startswith('video/')
        if action == 'create' and video:
            response = p.api(token, 'POST', '/v5/media', content=True, body={'media_type': 'video'})
            body = response.get('body') or {}
            mid = body.get('media_id')
            if response.get('status') != 201 or not isinstance(mid, str) or not mid.isdigit(): return _unknown('Pinterest media registration inconclusive')
            address = _upload_host(body.get('upload_url'), ('pinterest-media-upload.s3-accelerate.amazonaws.com',))
            data, content_type = multipart(body.get('upload_parameters') or {}, self.owner.bytes(m, asset), asset['mime'])
            uploaded = self.host.transport('POST', address, headers={'Content-Type': content_type}, data=data)
            if uploaded.get('status') not in (200, 201, 204): return _unknown('Pinterest media transfer inconclusive', container=mid)
            return self.progress('assets_uploaded', mid, [{'id': mid, 'kind': 'video', 'assetId': asset['id']}])
        if action == 'status':
            response = p.api(token, 'GET', '/v5/media/'+quote(job['container'], safe=''), content=True)
            body = response.get('body') or {}
            if response.get('status') in (401, 403): return {'state': 'held', 'confirmed': 'Pinterest media processing permission lost'}
            if body.get('status') == 'failed': return {'state': 'failed', 'confirmed': 'Pinterest video processing failed'}
            return self.progress('container_ready' if response.get('status') == 200 and body.get('status') == 'succeeded' else 'assets_uploaded', job['container'], job.get('providerAssets', []))
        if action not in ('create', 'publish'): return _unknown('Invalid Pinterest transition')
        # Never duplicate a Pin after an uncertain POST. The worker persists publish intent.
        body = {'board_id': options['boardId'], 'title': options.get('title', ''), 'description': m['payload']['text'], 'alt_text': asset.get('alt', '')}
        if options.get('sectionId'): body['board_section_id'] = options['sectionId']
        if options.get('link'): body['link'] = options['link']
        if video:
            if action != 'publish' or not asset.get('poster'): return {'state': 'held', 'confirmed': 'Pinterest video requires an immutable approved cover frame and processed media'}
            cover = {'id':asset['id'], 'mime':'image/jpeg', 'rightsConfirmed':True, **asset['poster']}
            body['media_source'] = {'source_type': 'video_id', 'media_id': job['container'], 'cover_image_url': self.owner.media_url(m, cover)}
        else:
            body['media_source'] = {'source_type': 'image_base64', 'content_type': asset['mime'], 'data': base64.b64encode(self.owner.bytes(m, asset)).decode()}
        response = p.api(token, 'POST', '/v5/pins', content=True, body=body)
        pid = str((response.get('body') or {}).get('id', ''))
        if response.get('status') == 201 and pid.isdigit(): return {'state': 'provider_accepted', 'reference': pid, 'confirmed': 'Pinterest Pin created; read-back pending'}
        return _unknown('Pinterest Pin create outcome inconclusive')

    def tiktok(self, m, job, action, p, grant):
        options, media, token = m.get('publishOptions') or {}, m.get('media') or [], grant['accessToken']
        if action != 'create': return _unknown('TikTok publication is reconciled through publish status')
        if options.get('mode') != 'inbox' and options.get('privacyLevel') != 'SELF_ONLY':
            proof = getattr(p,'official_approvals',{}).get('tiktok_public_publishing',{})
            if proof.get('state') != 'approved' or not proof.get('evidenceRef') or proof.get('appId') != p.client_id:
                return {'state':'held','confirmed':'Public Publishing: BLOCKED — TIKTOK AUDIT. Review a SELF_ONLY post for an unaudited client.'}
        creator = {'privacyLevelOptions': [None]} if options.get('mode') == 'inbox' else p.creator_info(token)  # TikTok requires fresh information immediately before dispatch.
        privacy = options.get('privacyLevel')
        if privacy not in creator.get('privacyLevelOptions', []): return {'state': 'held', 'confirmed': 'TikTok creator privacy choices changed; review again'}
        if any(options.get(option) and creator.get(disabled) for option, disabled in [('allowComment', 'commentDisabled'), ('allowDuet', 'duetDisabled'), ('allowStitch', 'stitchDisabled')]):
            return {'state': 'held', 'confirmed': 'TikTok creator interaction controls changed; review again'}
        photos = all(a['mime'].startswith('image/') for a in media)
        if photos:
            verified = getattr(p, 'verified_media_domains', frozenset())
            urls = [self.owner.media_url(m, a) for a in media]
            if any(urlsplit(u).hostname not in verified for u in urls): return {'state': 'held', 'confirmed': 'TikTok URL transfer requires an explicitly verified media domain'}
            commercial = options.get('commercial') or {}
            inbox = options.get('mode') == 'inbox'
            post_info = {'title': options.get('title', ''), 'description': m['payload']['text']}
            if not inbox:
                post_info.update(privacy_level=privacy, disable_comment=not options['allowComment'], brand_content_toggle=commercial.get('brandedContent') is True, brand_organic_toggle=commercial.get('yourBrand') is True)
                if 'autoAddMusic' in options: post_info['auto_add_music'] = options['autoAddMusic']
            body = {'media_type': 'PHOTO', 'post_mode': 'MEDIA_UPLOAD' if inbox else 'DIRECT_POST', 'post_info': post_info, 'source_info': {'source': 'PULL_FROM_URL', 'photo_images': urls, 'photo_cover_index': options.get('coverIndex', 0)}}
            if 'isAigc' in options: body['is_aigc'] = options['isAigc']
            response = p.api(token, 'POST', '/v2/post/publish/content/init/', body=body)
            value, error = (response.get('body') or {}).get('data') or {}, (response.get('body') or {}).get('error') or {}
            if response.get('status') == 200 and error.get('code') == 'ok' and value.get('publish_id'):
                return {'state': 'provider_accepted', 'reference': value['publish_id'], 'confirmed': 'TikTok photo inbox transfer accepted; creator must complete publication.' if inbox else 'TikTok photo transfer accepted; publication status pending'}
            return self.host._tiktok_rejection(response.get('status'), error) or _unknown('TikTok photo create outcome inconclusive')
        if options.get('mode') != 'inbox': return self.host._submit_tiktok(m, p, token)
        video, refusal = self.host._video(m)
        if refusal: return refusal
        raw, asset = video
        size = len(raw)
        chunk, count = p.chunks(size)
        source={'source':'FILE_UPLOAD','video_size':size,'chunk_size':chunk,'total_chunk_count':count}
        if options.get('transferMode')=='url':
            address=self.owner.media_url(m,asset)
            if urlsplit(address).hostname not in getattr(p,'verified_media_domains',()): return {'state':'held','confirmed':'TikTok inbox URL transfer requires a verified media domain; no upload initialized.'}
            source={'source':'PULL_FROM_URL','video_url':address}
        response = p.api(token, 'POST', '/v2/post/publish/inbox/video/init/', body={'source_info':source})
        value = (response.get('body') or {}).get('data') or {}
        reference, address = value.get('publish_id'), value.get('upload_url')
        error=(response.get('body') or {}).get('error') or {}
        if response.get('status') != 200 or error.get('code') not in (None,'ok') or not reference or (source['source']=='FILE_UPLOAD' and not address): return self.host._tiktok_rejection(response.get('status'),error) or _unknown('TikTok inbox initialization inconclusive')
        if source['source']=='PULL_FROM_URL': return {'state':'provider_accepted','reference':reference,'confirmed':'TikTok inbox URL transfer accepted; creator must complete publication.'}
        _upload_host(address, ('.tiktokapis.com',))
        offset = 0
        for index in range(count):
            end = size if index == count-1 else offset+chunk
            response = self.host.transport('PUT', address, headers={'Content-Type': asset['mime'], 'Content-Range': f'bytes {offset}-{end-1}/{size}'}, data=raw[offset:end])
            if response.get('status') not in (200, 201, 206): return _unknown('TikTok inbox transfer interrupted', reference=reference)
            offset = end
        return {'state': 'provider_accepted', 'reference': reference, 'confirmed': 'TikTok inbox upload accepted; creator must finish publication in TikTok'}

    def facebook(self, m, job, action, p, grant):
        page = p.revalidate_page(grant['accessToken'], 'CREATE_CONTENT')
        media, options, text = m.get('media') or [], m.get('publishOptions') or {}, m['payload']['text']
        assets = job.get('providerAssets') or []
        form = options.get('format', 'feed')
        video = bool(media and media[0]['mime'].startswith('video/'))
        if action == 'create' and video and form in ('reel', 'story'):
            edge = 'video_reels' if form == 'reel' else 'video_stories'
            response = p.graph('POST', '/'+page['id']+'/'+edge, page['token'], form={'upload_phase': 'start'})
            body = response.get('body') or {};mid = str(body.get('video_id') or '')
            if response.get('status') != 200 or not mid.isdigit(): return _unknown('Facebook video initialization inconclusive')
            address = _upload_host(body.get('upload_url'), ('rupload.facebook.com',))
            raw = self.owner.bytes(m, media[0])
            response = self.host.transport('POST', address, headers={'Authorization': 'OAuth '+page['token'], 'offset': '0', 'file_size': str(len(raw)), 'Content-Type': 'application/octet-stream'}, data=raw)
            if response.get('status') != 200 or (response.get('body') or {}).get('success') is not True: return _unknown('Facebook video transfer inconclusive', container=mid)
            return self.progress('assets_uploaded', mid, [{'id': mid, 'kind': edge, 'assetId': media[0]['id']}])
        if action == 'status':
            response = p.graph('GET', '/'+job['container'], page['token'], {'fields': 'status'})
            status = (response.get('body') or {}).get('status') or {}
            if status.get('video_status') == 'error' or (status.get('processing_phase') or {}).get('status') == 'error': return {'state': 'failed', 'confirmed': 'Facebook video processing failed'}
            ready = (status.get('processing_phase') or {}).get('status') == 'complete' or status.get('video_status') == 'ready'
            return self.progress('container_ready' if response.get('status') == 200 and ready else 'assets_uploaded', job['container'], assets)
        if action == 'publish' and video:
            edge = assets[0]['kind']
            fields = {'upload_phase': 'finish', 'video_id': job['container'], 'description': text}
            if edge == 'video_reels': fields['video_state'] = 'PUBLISHED'
            response = p.graph('POST', '/'+page['id']+'/'+edge, page['token'], form=fields)
            if response.get('status') == 200 and (response.get('body') or {}).get('success') is True:
                return {'state': 'provider_accepted', 'reference': job['container'], 'confirmed': 'Facebook video publication requested; processing/read-back pending'}
            return _unknown('Facebook video publish outcome inconclusive', container=job['container'])
        if action != 'create': return _unknown('Invalid Facebook transition')
        if media and not video:
            for asset in media:
                response = p.graph('POST', '/'+page['id']+'/photos', page['token'], form={'url': self.owner.media_url(m, asset), 'published': 'false', 'alt_text_custom': asset.get('alt', '')})
                mid = str((response.get('body') or {}).get('id', ''))
                if response.get('status') != 200 or not mid.isdigit(): return _unknown('Facebook photo transfer inconclusive', providerAssets=assets)
                assets.append({'id': mid, 'kind': 'photo', 'assetId': asset['id']})
            if form == 'story':
                response = p.graph('POST', '/'+page['id']+'/photo_stories', page['token'], form={'photo_id': assets[0]['id']})
            else:
                fields = {'message': text, 'attached_media': json.dumps([{'media_fbid': a['id']} for a in assets])}
                if options.get('scheduledPublishTime'): fields.update(published='false', scheduled_publish_time=options['scheduledPublishTime'])
                response = p.graph('POST', '/'+page['id']+'/feed', page['token'], form=fields)
        elif video:
            response = p.graph('POST', '/'+page['id']+'/videos', page['token'], form={'file_url': self.owner.media_url(m, media[0]), 'description': text})
        else:
            fields = {'message': text}
            if options.get('link'): fields['link'] = options['link']
            if options.get('scheduledPublishTime'): fields.update(published='false', scheduled_publish_time=options['scheduledPublishTime'])
            response = p.graph('POST', '/'+page['id']+'/feed', page['token'], form=fields)
        body = response.get('body') or {};reference = str(body.get('post_id') or body.get('id') or '')
        if response.get('status') == 200 and re.fullmatch(r'\d{5,30}(?:_\d{5,30})?', reference): return {'state': 'provider_accepted', 'reference': reference, 'providerAssets': assets, 'confirmed': 'Facebook accepted Page content; native schedule/publication read-back pending'}
        return self.host._facebook_rejection(response) or _unknown('Facebook Page publication result inconclusive')

    def x(self, m, job, action, p, grant):
        from .official_operations import OfficialAPI
        gate = OfficialAPI(p, grant)
        def call(method, path, **kw):
            gate._x_budget()
            return p.api(grant['accessToken'], method, path, **kw)
        media, options = m.get('media') or [], m.get('publishOptions') or {}
        if options.get('quoteId'):
            try: gate.x_product('x_enterprise')
            except AlphaError as error: return {'state':'held','confirmed':str(error)}
        assets = job.get('providerAssets') or []
        if action == 'create' and media:
            asset = media[len(assets)]
            raw = self.owner.bytes(m, asset)
            category = 'tweet_video' if asset['mime'].startswith('video/') else 'tweet_gif' if asset['mime'] == 'image/gif' else 'tweet_image'
            response = call('POST', '/2/media/upload/initialize', body={'media_type': asset['mime'], 'media_category': category, 'total_bytes': len(raw)})
            value = (response.get('body') or {}).get('data') or {};mid = str(value.get('id') or '')
            if response.get('status') not in (200, 201) or not mid.isdigit(): return _unknown('X media initialization inconclusive')
            return self.progress('upload_session', mid, assets, {'mediaId': mid, 'index': len(assets), 'offset': 0, 'segment': 0, 'total': len(raw)})
        if action == 'upload':
            upload = self.opened(job);asset = media[upload['index']];raw = self.owner.bytes(m, asset)
            offset, total = upload['offset'], upload['total'];end = min(total, offset+CHUNK_BYTES)
            response = call('POST', '/2/media/upload/'+upload['mediaId']+'/append', body={'media': base64.b64encode(raw[offset:end]).decode(), 'segment_index': upload['segment']})
            if response.get('status') not in (200, 201, 204): return _unknown('X media append outcome inconclusive', container=upload['mediaId'])
            upload.update(offset=end, segment=upload['segment']+1)
            return self.progress('upload_finalizable' if end == total else 'upload_session', upload['mediaId'], assets, upload)
        if action == 'finalize':
            upload = self.opened(job)
            response = call('POST', '/2/media/upload/'+upload['mediaId']+'/finalize')
            if response.get('status') not in (200, 201, 202): return _unknown('X media finalization inconclusive', container=upload['mediaId'])
            return self.progress('assets_uploaded', upload['mediaId'], assets, upload)
        if action == 'status':
            upload = self.opened(job);mid = upload['mediaId']
            response = call('GET', '/2/media/upload?'+urlencode({'media_id': mid}))
            value = (response.get('body') or {}).get('data') or {};status = (value.get('processing_info') or {}).get('state')
            if response.get('status') in (402, 429): return {'state': 'held', 'confirmed': 'X media status requires credits or quota; no post created'}
            if status == 'failed': return {'state': 'failed', 'confirmed': 'X media processing failed'}
            if response.get('status') != 200 or status in ('pending', 'in_progress'): return self.progress('assets_uploaded', mid, assets, upload)
            if status != 'succeeded' and not (str(value.get('id')) == mid and 'processing_info' not in value): return _unknown('X media processing is not proven')
            return self.progress('metadata_pending', mid, assets, upload)
        if action == 'metadata':
            upload = self.opened(job);mid = upload['mediaId'];asset = media[upload['index']]
            if asset.get('alt'):
                response = call('POST', '/2/media/metadata', body={'id': mid, 'metadata': {'alt_text': {'text': asset['alt']}}})
                if response.get('status') not in (200, 201, 204): return {'state': 'held', 'confirmed': 'X did not accept approved alt text'}
            assets.append({'id': mid, 'kind': 'media', 'assetId': asset['id']})
            return self.progress('container_ready' if len(assets) == len(media) else 'next_asset', mid, assets)
        if action not in ('create', 'publish'): return _unknown('Invalid X publication transition')
        thread = list(job.get('providerThread') or [])
        parts = [m['payload']['text'], *(options.get('thread') or [])]
        if len(thread) >= len(parts): return _unknown('X thread is already submitted; reconcile without another create')
        payload = {'text': parts[len(thread)]}
        if thread:
            payload['reply'] = {'in_reply_to_tweet_id': thread[-1]}
        elif media:
            if len(assets) != len(media): return {'state': 'held', 'confirmed': 'X media not ready'}
            payload['media'] = {'media_ids': [a['id'] for a in assets]}
        if not thread:
            if options.get('replyToId'): payload['reply'] = {'in_reply_to_tweet_id': options['replyToId']}
            if options.get('quoteId'): payload['quote_tweet_id'] = options['quoteId']
            if options.get('poll'): payload['poll'] = options['poll']
        response = call('POST', '/2/tweets', body=payload)
        value = (response.get('body') or {}).get('data') or {};reference = str(value.get('id') or '')
        if response.get('status') == 201 and reference.isdigit():
            thread.append(reference)
            result = {'state': 'provider_accepted', 'reference': thread[0], 'providerThread': thread, 'providerAssets': assets, 'confirmed': 'X posts created; metered read-back pending'}
            if len(thread) < len(parts):
                result.update(state='processing', container=thread[0], progress={'version': 1, 'stage': 'thread_ready'}, confirmed='X thread partly created; next approved reply awaits its own durable intent')
            return result
        return _unknown('X post create outcome inconclusive')
