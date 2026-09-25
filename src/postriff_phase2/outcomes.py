"""Validate adapter results at the worker boundary, independently of transports."""
import re
from urllib.parse import urlsplit


def valid_receipt_url(url, platform):
    if not isinstance(url, str) or not 1 <= len(url) <= 2000 or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        hosts, path = {
            'Instagram': ({'instagram.com', 'www.instagram.com'}, r'/(p|reel|tv)/[A-Za-z0-9_-]+/?'),
            'Threads': ({'threads.net', 'www.threads.net', 'threads.com', 'www.threads.com'}, r'/@[A-Za-z0-9_.]+/post/[A-Za-z0-9_-]+/?'),
            'LinkedIn': ({'linkedin.com', 'www.linkedin.com'}, r'/feed/update/urn:li:(share|ugcPost):[0-9]+/?'),
            'X': ({'x.com', 'twitter.com'}, r'/[A-Za-z0-9_]{1,15}/status/[0-9]{1,25}/?'),
            'Bluesky': ({'bsky.app'}, r'/profile/[A-Za-z0-9.:_-]{3,253}/post/[a-z2-7]{13}/?'),
            'Discord': ({'discord.com'}, r'/channels/[0-9]{5,25}/[0-9]{5,25}/[0-9]{5,25}/?'),
            'Telegram': ({'t.me'}, r'/[A-Za-z0-9_]{4,32}/[0-9]{1,15}/?'),
            'Facebook': ({'www.facebook.com', 'facebook.com'}, r'/[A-Za-z0-9.]{1,100}/posts/[A-Za-z0-9_]{1,100}/?'),
            'YouTube': ({'youtu.be'}, r'/[A-Za-z0-9_-]{11}'),
            'TikTok': ({'www.tiktok.com'}, r'/@[A-Za-z0-9_.]{1,24}/video/[0-9]{5,25}/?'),
            'Pinterest': ({'www.pinterest.com'}, r'/pin/[0-9]{5,30}/?'),
        }.get(platform, (set(), r'(?!)'))
        return bool(parsed.scheme == 'https' and parsed.hostname in hosts and parsed.port is None
                    and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                    and re.fullmatch(path, parsed.path))
    except ValueError:
        return False


def unknown(message="Provider outcome is unknown; reconcile before retry"):
    return {"state": "uncertain", "confirmed": message}


def normalize_result(result, job, reconciliation=False):
    allowed = {"uncertain", "processing", "held", "scheduled", "failed", "provider_accepted", "published", "verified"}
    if (not isinstance(result, dict) or not isinstance(result.get("state"), str) or result["state"] not in allowed
            or not isinstance(result.get("confirmed"), str)
            or not 1 <= len(result["confirmed"]) <= 2000):
        return unknown("Malformed adapter response; reconcile before retry")
    reference = result.get("reference", job.get("providerReference"))
    if reference is not None and (not isinstance(reference, str) or not 1 <= len(reference) <= 500):
        return unknown("Invalid provider reference; reconcile before retry")
    if reconciliation and result["state"] in ("processing", "scheduled", "held", "failed"):
        # A lookup failure or retry suggestion cannot prove that a prior POST did not run.
        return unknown("Reconciliation did not resolve the prior submission; manual review required")
    if result["state"] in ("published", "verified") and not reference:
        return unknown("Publication receipt is missing a provider reference")
    if result["state"] == "verified" and (not isinstance(result.get("verification"), str)
                                             or not 1 <= len(result["verification"]) <= 200):
        return unknown("Publication receipt is missing verification evidence")
    if job.get("cancelRequested") and result["state"] == "scheduled":
        return {"state": "canceled", "confirmed": "Canceled after the adapter confirmed rejection before acceptance"}
    # provider_receipt: the provider's own response returned the created object (id, destination, exact text) and it
    # offers no read-back to bots (Telegram). It is still provider evidence, never a manual claim.
    if result['state'] == 'verified' and result.get('verification') not in ('provider_lookup', 'provider_receipt', 'fixture_lookup', 'disposable_lookup'):
        return unknown('Receipt is not independently verified; manual evidence is not API verification')
    container = result.get('container', job.get('container'))
    if container is not None and (not isinstance(container, str) or not re.fullmatch(r'[A-Za-z0-9_:-]{1,500}', container)):
        return unknown('Invalid provider container; manual review required')
    url = result.get('url', job.get('url'))
    if url is not None and not valid_receipt_url(url, job.get('manifest', {}).get('platform')):
        return unknown('Invalid canonical receipt URL; manual review required')
    normalized = {key: result[key] for key in ('state', 'confirmed', 'verification') if key in result}
    progress = result.get('progress')
    if progress is not None:
        if (not isinstance(progress, dict) or progress.get('version') != 1
                or progress.get('stage') not in ('container_created', 'container_ready', 'provider_accepted')
                or not container):
            return unknown('Invalid publishing progress; manual review required')
        normalized['progress'] = {'version': 1, 'stage': progress['stage']}
    normalized['schema'] = 'postriff.result.v1'
    for key, value in (('reference', reference), ('container', container), ('url', url)):
        if value is not None:
            normalized[key] = value
    if job.get('cancelRequested') and normalized['state'] == 'processing':
        normalized.update(state='canceled', confirmed='Publication canceled before publish; the unpublished container may remain')
    return normalized
