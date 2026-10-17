"""Exact Mastodon attachments using existing image/video assets and private Library audio.

Normalized Library files are never copied into legacy asset state. Database checks
at review, approval and fenced worker dispatch preserve their immutable binding.
"""
import re

from postriff_alpha.domain import AlphaError, clean
from . import asset_kinds

ASSET_ID = re.compile(r'[0-9a-f]{32}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
AUDIO_FIELDS = ('id', 'hash', 'mime', 'bytes', 'objectName', 'etag', 'storageKind', 'normalizedLibrary')


def audio_snapshot(cur, workspace, asset_id):
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
        raise AlphaError('Choose a verified Library audio file.', 400)
    cur.execute("SELECT kind,mime,bytes,sha256,object_name,etag,processing_status FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s FOR SHARE", (workspace, asset_id))
    row = cur.fetchone()
    if (not row or row[0] != 'audio' or not str(row[1]).startswith('audio/') or type(row[2]) is not int
            or not 0 < row[2] <= 50 * 1024**2 or not HASH.fullmatch(str(row[3] or ''))
            or not isinstance(row[4], str) or not re.fullmatch(asset_id + r'\.[a-z0-9]{1,12}', row[4])
            or not row[5] or row[6] not in ('ready', 'unsupported')):
        raise AlphaError('The audio file is missing, changed or not yet verified. Choose it again after Library processing.', 409)
    return dict(zip(AUDIO_FIELDS, (asset_id, row[3], row[1], row[2], row[4], row[5], 'file', True)))


def prepare_library(cur, workspace, state, payload):
    """Called inside authenticated review transaction; caller-supplied custody metadata is discarded."""
    payload.pop('_mastodonLibrary', None)
    channel = next((c for c in state.get('phase2', {}).get('channels', []) if c.get('id') == payload.get('channelId')), None)
    if not channel or channel.get('platform') != 'Mastodon':
        if payload.get('attachments'):
            raise AlphaError('Multiple attachment reviews are available for Mastodon only.', 409)
        return
    attachments = payload.get('attachments')
    if attachments is None:
        return
    if not isinstance(attachments, list) or len(attachments) > 4 or payload.get('assetId'):
        raise AlphaError('Choose one attachment list containing up to four Mastodon files.', 400)
    legacy = {a.get('id') for a in state.get('phase2', {}).get('assets', [])}
    library = {}
    for item in attachments:
        asset_id = item.get('assetId') if isinstance(item, dict) else None
        if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
            raise AlphaError('Choose a valid Library attachment.', 400)
        if asset_id not in legacy:
            library[asset_id] = audio_snapshot(cur, workspace, asset_id)
    payload['_mastodonLibrary'] = library


def review_media(state, payload):
    items = payload.get('attachments')
    if items is None:
        items = [{'assetId': payload['assetId'], 'alt': payload.get('alt', '')}] if payload.get('assetId') else []
    if not isinstance(items, list) or len(items) > 4:
        raise AlphaError('Choose up to four Mastodon attachments.', 400)
    media, seen = [], set()
    assets = {a['id']: a for a in state['phase2']['assets']}
    library = payload.get('_mastodonLibrary') or {}
    for item in items:
        if not isinstance(item, dict) or set(item) - {'assetId', 'alt'}:
            raise AlphaError('Choose an attachment and its description.', 400)
        asset_id = item.get('assetId')
        if not isinstance(asset_id, str) or asset_id in seen or payload.get('rightsConfirmed') is not True:
            raise AlphaError('Choose distinct attachments and confirm their rights.', 400)
        seen.add(asset_id)
        description = clean(item.get('alt', ''), 1000)
        audio = library.get(asset_id)
        if audio:
            if (not isinstance(audio, dict) or audio.get('id') != asset_id or audio.get('normalizedLibrary') is not True
                    or audio.get('storageKind') != 'file' or not ASSET_ID.fullmatch(asset_id)
                    or not HASH.fullmatch(str(audio.get('hash', ''))) or not str(audio.get('mime', '')).startswith('audio/')
                    or type(audio.get('bytes')) is not int or not 0 < audio['bytes'] <= 50 * 1024**2
                    or not re.fullmatch(asset_id + r'\.[a-z0-9]{1,12}', str(audio.get('objectName', '')))
                    or not audio.get('etag')):
                raise AlphaError('Choose a verified Library audio file.', 409)
            frozen = {k: audio[k] for k in AUDIO_FIELDS}
        else:
            asset = assets.get(asset_id)
            if asset_kinds.is_postable_image(asset):
                if not description:
                    raise AlphaError('Describe each Mastodon image before preparing review.', 400)
                frozen = {k: asset[k] for k in ('id', 'hash', 'sourceHash', 'mime', 'bytes', 'width', 'height', 'duration')}
                if asset.get('objectName'):
                    frozen['objectName'] = asset['objectName']
            elif asset_kinds.is_postable_video(asset, 'Mastodon'):
                frozen = {k: asset[k] for k in ('id', 'hash', 'mime', 'bytes', 'width', 'height', 'duration', 'durationSource', 'bucket', 'objectName', 'etag', 'verified')}
            else:
                raise AlphaError('Choose a decoded image, verified video or verified Library audio.', 409)
        media.append({**frozen, 'alt': description, 'rightsConfirmed': True})
    if len(media) > 1 and any(not a['mime'].startswith('image/') for a in media):
        raise AlphaError('Mastodon accepts multiple images or one video/audio file; do not mix them.', 400)
    return media


def library_bindings_current(cur, workspace, manifest):
    try:
        for asset in manifest.get('media', []):
            if not asset.get('normalizedLibrary'):
                continue
            if manifest.get('platform') != 'Mastodon' or asset.get('rightsConfirmed') is not True:
                return False
            current = audio_snapshot(cur, workspace, asset.get('id'))
            if any(asset.get(k) != current[k] for k in AUDIO_FIELDS):
                return False
        return True
    except AlphaError:
        return False


def validate_new_bindings(cur, workspace, before, after):
    """Review and every queue-entry path recheck Library custody in their existing transaction."""
    old = before.get('phase2', {})
    for name in ('reviews', 'jobs'):
        prior = {item.get('id'): item for item in old.get(name, [])}
        for item in after.get('phase2', {}).get(name, []):
            if item.get('id') in prior:
                continue
            manifest = item.get('manifest') or {}
            if any(a.get('normalizedLibrary') for a in manifest.get('media', [])) and not library_bindings_current(cur, workspace, manifest):
                raise AlphaError('A reviewed audio file changed or was removed. Prepare a fresh review.', 409)
