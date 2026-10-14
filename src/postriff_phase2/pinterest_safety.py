"""Pinterest v1 safety rules shared by review, worker and account revocation.

These rules do not grant publication authority. The existing approved manifest,
workspace membership, worker fence and provider gates remain authoritative.
"""
import ipaddress
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError

IMAGE_MIMES = frozenset({'image/jpeg', 'image/png'})
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # Rafii v1 limit, not a claimed provider maximum.


def https_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname or ''
        if parts.scheme != 'https' or not host or parts.username or parts.password or port not in (None, 443):
            return False
        if host.lower() in ('localhost', 'localhost.localdomain') or host.lower().endswith(('.localhost', '.local')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return '.' in host and '\\' not in value
    except ValueError:
        return False


def image(media):
    if len(media) != 1 or media[0].get('mime') not in IMAGE_MIMES:
        raise AlphaError('A Pin needs one JPEG or PNG image.', 409)
    size = media[0].get('bytes')
    if type(size) is not int or not 0 < size <= MAX_IMAGE_BYTES:
        raise AlphaError('Upload a verified JPEG or PNG of up to 10 MiB for this Pin.', 409)
    alt = media[0].get('alt', '')
    if not isinstance(alt, str) or len(alt) > 500:
        raise AlphaError('Pin alt text allows 500 characters. Review the image again.', 400)


def revoke_authority(state, connection_id, now):
    """Called while holding the workspace and credential locks. No reconnect resumes an old approval."""
    data = state.get('phase2') or {}
    for channel in data.get('channels', []):
        if channel.get('id') == connection_id and channel.get('platform') == 'Pinterest':
            channel.update(revoked=True, identityVerified=False, capabilityVerified=False)
    for review in data.get('reviews', []):
        manifest = review.get('manifest') or {}
        if manifest.get('channelId') == connection_id and manifest.get('platform') == 'Pinterest':
            review['status'] = 'stale'
    canceled, uncertain = 0, 0
    for job in data.get('jobs', []):
        manifest = job.get('manifest') or {}
        if manifest.get('channelId') != connection_id or manifest.get('platform') != 'Pinterest':
            continue
        if job.get('state') in ('verified', 'failed', 'canceled'):
            continue
        inflight = job.get('state') in ('submitting', 'provider_accepted', 'processing', 'uncertain')
        job.update(cancelRequested=True, leaseOwner=None, leaseUntil=0, leaseId=None,
                   state='uncertain' if inflight else 'canceled')
        job.setdefault('events', []).append({'at': now, 'state': job['state'],
            'execution': manifest.get('execution', 'synthetic'),
            'message': 'Pinterest disconnected. Provider acceptance requires manual reconciliation.' if inflight
                       else 'Pinterest disconnected. Canceled before provider submission.'})
        uncertain += int(inflight)
        canceled += int(not inflight)
    planning = ((state.get('raffi') or {}).get('campaignPlanning') or {})
    for task in planning.get('recurringTasks', []):
        if any(d.get('channelId') == connection_id for d in task.get('destinations', [])):
            task.update(status='paused', pauseReason='Pinterest disconnected', pausedAt=now)
            task.pop('pausedUntil', None)
    return {'canceledJobs': canceled, 'uncertainJobs': uncertain}
