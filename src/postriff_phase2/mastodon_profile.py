"""Exact profile updates; local decoded images stay bound to workspace custody."""
import hashlib
import re

from postriff_alpha.domain import AlphaError
from .asset_kinds import is_postable_image
from .mastodon_protocol import version_at_least
from .mastodon_media import ASSET_ID, HASH

BOOLEAN_VERSION = {'locked': (2, 3, 0), 'bot': (1, 1, 1), 'discoverable': (2, 7, 0),
                   'hide_collections': (4, 1, 0), 'indexable': (4, 2, 0)}
IMAGE_FIELDS = ('id', 'hash', 'mime', 'bytes', 'objectName')


def profile_fields(payload, capabilities):
    fields, media = payload.get('profile', {}), payload.get('profileMedia', {})
    if (not isinstance(fields, dict) or not isinstance(media, dict) or not (fields or media)
            or set(fields) - {'display_name', 'note', 'avatar_description', 'header_description', 'source', 'fields_attributes', 'attribution_domains', *BOOLEAN_VERSION}
            or set(media) - {'avatar', 'header'}):
        raise AlphaError('Choose supported profile fields or Library images.', 400)
    version = capabilities.get('version', '')
    limits = capabilities.get('profileLimits') or {}
    for key, value in fields.items():
        if key in ('display_name', 'note', 'avatar_description', 'header_description'):
            limit_key = 'max_' + key + '_length'
            fallback = 30 if key == 'display_name' else 500 if key == 'note' else 1500
            if key.endswith('_description') and not version_at_least(version, (4, 6, 1)):
                raise AlphaError('Profile image descriptions require Mastodon 4.6.1 or later.', 409)
            if not isinstance(value, str) or len(value) > limits.get(limit_key, fallback):
                raise AlphaError('The profile text exceeds supported limits.', 400)
        elif key in BOOLEAN_VERSION:
            if type(value) is not bool:
                raise AlphaError('Choose valid profile preferences.', 400)
            if not version_at_least(version, BOOLEAN_VERSION[key]):
                raise AlphaError('This profile preference is unavailable on this server version.', 409)
        elif key == 'source':
            if not isinstance(value, dict) or not value or set(value) - {'privacy', 'sensitive', 'language', 'quote_policy'}:
                raise AlphaError('Choose supported default post preferences.', 400)
            for name, entry in value.items():
                if not version_at_least(version, (4, 5, 0) if name == 'quote_policy' else (2, 4, 2) if name == 'language' else (2, 4, 0)):
                    raise AlphaError('This default post preference is unavailable on this server version.', 409)
                if ((name == 'privacy' and entry not in ('public', 'unlisted', 'private'))
                        or (name == 'sensitive' and type(entry) is not bool)
                        or (name == 'language' and (not isinstance(entry, str) or not re.fullmatch(r'[a-z]{2}|', entry)))
                        or (name == 'quote_policy' and entry not in ('public', 'followers', 'nobody'))):
                    raise AlphaError('Choose valid default post preferences.', 400)
        elif key == 'fields_attributes':
            if not version_at_least(version, (2, 4, 0)):
                raise AlphaError('Profile metadata is unavailable on this server version.', 409)
            if not isinstance(value, list) or len(value) > limits.get('max_profile_fields', 4):
                raise AlphaError(f"Choose up to {limits.get('max_profile_fields', 4)} profile metadata fields.", 400)
            for item in value:
                if (not isinstance(item, dict) or set(item) != {'name', 'value'}
                        or any(not isinstance(v, str) or len(v) > limits.get('profile_field_' + k + '_limit', 255) for k, v in item.items())):
                    raise AlphaError('Profile metadata exceeds this server’s name or value limits.', 400)
        elif key == 'attribution_domains':
            if not version_at_least(version, (4, 4, 0)):
                raise AlphaError('Website attribution is unavailable on this server version.', 409)
            if (not isinstance(value, list) or len(value) > 10
                    or any(not isinstance(v, str) or not re.fullmatch(r'(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', v) or '.' not in v for v in value)):
                raise AlphaError('Choose up to ten website domains without URL paths.', 400)
    for role, item in media.items():
        if (not isinstance(item, dict) or set(item) != {'assetId', 'rightsConfirmed'}
                or not isinstance(item['assetId'], str) or not ASSET_ID.fullmatch(item['assetId'])
                or item['rightsConfirmed'] is not True):
            raise AlphaError('Choose Library profile images and confirm their rights.', 400)
    return fields


def freeze_images(state, media):
    frozen = {}
    for role, item in media.items():
        asset = next((a for a in state.get('phase2', {}).get('assets', []) if a.get('id') == item['assetId']), None)
        if (not is_postable_image(asset) or asset.get('mime') not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
                or type(asset.get('bytes')) is not int or not 0 < asset['bytes'] <= 2 * 1024**2
                or not HASH.fullmatch(str(asset.get('hash', '')))
                or not re.fullmatch(item['assetId'] + r'\.[a-z0-9]{1,12}', str(asset.get('objectName', '')))):
            raise AlphaError('Choose a decoded Library profile image up to 2 MB. Larger images need resizing first.', 409)
        frozen[role] = {**{k: asset[k] for k in IMAGE_FIELDS}, 'rightsConfirmed': True}
    return frozen


def approved_images(service, workspace, state, media):
    if media and service.assets is None:
        raise AlphaError('Private profile image storage is unavailable. No update was sent.', 503)
    files = []
    for role, frozen in media.items():
        current = freeze_images(state, {role: {'assetId': frozen['id'], 'rightsConfirmed': True}})[role]
        if current != frozen:
            raise AlphaError('A profile image changed. Prepare a new exact approval.', 409)
        raw = service.assets.storage.get(workspace, 'media', frozen['objectName'])
        if not isinstance(raw, bytes) or len(raw) != frozen['bytes'] or hashlib.sha256(raw).hexdigest() != frozen['hash']:
            raise AlphaError('The approved profile image bytes changed. No update was sent.', 409)
        files.append((role, frozen['objectName'], frozen['mime'], raw))
    return files


def form_fields(fields):
    """Flatten allowlisted nested values for the documented form/multipart endpoint."""
    result = []
    for key, value in fields.items():
        if key == 'source':
            result.extend((f'source[{k}]', str(v).lower() if type(v) is bool else v) for k, v in value.items())
        elif key == 'fields_attributes':
            if not value: result.extend((('fields_attributes[0][name]', ''), ('fields_attributes[0][value]', '')))
            else: result.extend((f'fields_attributes[{i}][{k}]', v) for i, item in enumerate(value) for k, v in item.items())
        elif key == 'attribution_domains':
            result.extend(('attribution_domains[]', v) for v in value)
            if not value: result.append(('attribution_domains[]', ''))
        else:
            result.append((key, str(value).lower() if type(value) is bool else value))
    return result
