"""Read existing publication receipts and native measurements for one rendered video revision."""
from datetime import date, datetime, time, timedelta
import math
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from . import asset_kinds, insights
from .creative_video_media import MAX_DURATION_MS, MAX_MEDIA_BYTES
from .growth.metric_schedule import NATIVE_ANALYTICS_SCOPES, analytics_direct, purge_pending
from .youtube import workspace_provider_data
from .youtube.agent_tools import _native_metrics
from .youtube.model import READ, capability_matrix, has_scopes
from .youtube.service import fingerprint


def _youtube_readable(oauth, cur, workspace, job, actor, token, grant, now):
    manifest = job['manifest']
    stamp = job.get(workspace_provider_data.KEY) or {}
    provider = oauth.providers.get('youtube') if oauth else None
    progress = job.get('progress') or {}
    generation = grant[2]
    if (not provider or not getattr(provider, 'creator_enabled', False) or not has_scopes(grant[1] or (), [READ])
            or progress.get('stage') != 'published' or progress.get('privacyStatus') not in ('public', 'unlisted')
            or progress.get('videoId') != job['providerReference'] or not job.get('approvedBy')
            or not isinstance(stamp, dict) or not generation or stamp.get('authorizationGeneration') != generation
            or stamp.get('actor') != job.get('approvedBy') or stamp.get('workspaceId') != workspace
            or stamp.get('connectionId') != manifest['channelId'] or workspace_provider_data._expired_job(job, now)):
        return False
    try:
        policy = oauth.youtube_policy
        policy.require_user(cur, workspace, actor, token, provider, force=True)
        policy.assert_connection(workspace, manifest['channelId'], provider, generation=generation, force=True, cur=cur)
        return True
    except AlphaError as error:
        if error.code in ('youtube_policy_not_ready', 'youtube_policy_acceptance_required'):
            return False
        raise


def _youtube_metrics(cur, workspace, connection, account, video_id):
    """An expiry-bounded cached daily report is usable only if its opaque key includes this exact video."""
    cur.execute("""SELECT cache_key,data->'coverage'->>'startDate',data->'coverage'->>'endDate'
                   FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s
                   AND expires_at>now() AND source='YouTube Analytics API' AND data->>'report'='daily'
                   AND data->>'channelId'=%s ORDER BY refreshed_at DESC,cache_key""", (workspace, connection, account))
    for key, first, last in cur.fetchall():
        if not first or not last:
            continue
        query = {'resource':'analytics', 'videoId':video_id, 'startDate':first, 'endDate':last}
        if key not in ('analytics:' + fingerprint(query), 'analytics:' + fingerprint({**query, 'report':'daily'})):
            continue
        cur.execute("""SELECT data FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s
                       AND cache_key=%s AND expires_at>now() AND source='YouTube Analytics API'
                       AND data->>'report'='daily' AND data->>'channelId'=%s""", (workspace, connection, key, account))
        row = cur.fetchone()
        if not row:
            continue
        report = row[0]
        observed = workspace_provider_data.number(report.get('ingestedAt'))
        coverage = report.get('coverage') or {}
        if (observed is None or report.get('source') != 'YouTube Analytics API'
                or coverage.get('startDate') != first or coverage.get('endDate') != last):
            continue
        try:
            first_day, last_day = date.fromisoformat(first), date.fromisoformat(last)
            data = report.get('data') or {}
            rows = data.get('rows') or []
            if not isinstance(rows, list) or len(rows) > 1000:
                continue
            days = []
            for i in range(0, len(rows), 100):
                batch = {**report, 'data': {**data, 'rows': rows[i:i + 100]}}
                days.extend(_native_metrics(batch, first_day, last_day)['nativeObservations'])
        except (AlphaError, TypeError, ValueError):
            continue
        if not days:
            continue
        # The panel shows the latest measured day of the most recently refreshed matching report.
        # Keep native values and dates together even when the report spans hundreds of days.
        latest = max(days, key=lambda row: row['day'])
        pacific = ZoneInfo('America/Los_Angeles')
        start = datetime.combine(date.fromisoformat(latest['day']), time.min, pacific)
        return [{'name': name, 'value': value, 'availability': 'available',
                 'unit': 'minutes' if name == 'estimatedMinutesWatched' else 'count',
                 'definitionVersion': 'youtube-analytics-v2', 'source': 'youtube_analytics',
                 'observedAt': observed, 'periodStart': start.timestamp(),
                 'periodEnd': (start + timedelta(days=1)).timestamp(), 'readOffset': None}
                for name, value in latest.items() if name != 'day']
    return []


def _growth_metrics(cur, workspace, channel, provider, post, job, scopes):
    if (provider not in insights.INSIGHT_METRICS or not NATIVE_ANALYTICS_SCOPES[provider] <= set(scopes or ())
            or not analytics_direct(cur, workspace, channel) or purge_pending(cur, workspace, channel)):
        return []
    # Use the Growth reader's available-first ordering, within one exact published post and read window.
    cur.execute("""SELECT DISTINCT ON (metric,read_offset,definition_version) metric,value,unit,availability,
                     definition_version,extract(epoch from observed_at),extract(epoch from period_start),
                     extract(epoch from period_end),read_offset FROM public.pr_metric_observations
                   WHERE workspace_id=%s AND connection_id=%s AND provider=%s AND provider_post_id=%s AND job_id=%s
                   ORDER BY metric,read_offset,definition_version,(availability='available') DESC,
                            observed_at DESC,ingested_at DESC,id DESC""", (workspace, channel, provider, post, job))
    metrics = []
    for name, value, unit, availability, version, observed, first, last, offset in cur.fetchall():
        if name not in insights.INSIGHT_METRICS[provider]:
            continue
        value = float(value) if value is not None else None
        if availability == 'available' and (value is None or not math.isfinite(value) or value < 0):
            availability = 'unavailable'
        metrics.append({'name': name, 'value': value if availability == 'available' else None,
                        'unit': unit, 'availability': availability, 'definitionVersion': version,
                        'observedAt': float(observed), 'periodStart': float(first) if first is not None else None,
                        'periodEnd': float(last) if last is not None else None, 'readOffset': offset,
                        'source':'provider_insights'})
    return metrics


def _published_media(cur, workspace, data, asset_ids, oauth, token, actor, now, *, video_id=None):
    channels = {c['id']: c for c in data.get('channels', []) if not c.get('revoked') and not c.get('deleted')}
    for job in data.get('jobs', []):
        if video_id is not None and job.get('providerReference') != video_id:
            continue
        manifest = job.get('manifest') or {}
        platform, channel = manifest.get('platform'), manifest.get('channelId')
        reference, verification = job.get('providerReference'), job.get('verification') or {}
        verified = workspace_provider_data.number(verification.get('at'))
        if (job.get('state') != 'verified' or not job.get('id') or not isinstance(reference, str) or not reference
                or verified is None or verification.get('method') != 'provider_lookup' or job.get('privacyErased')
                or job.get(workspace_provider_data.REMOVED) or manifest.get('privacyErased')
                or manifest.get('execution') != 'hosted-live' or manifest.get('workspaceId') != workspace
                or channel not in channels or channels[channel].get('platform') != platform
                # TikTok currently retains its submission operation ID even after the status read succeeds.
                or platform not in ('YouTube', 'Kuaishou', 'Instagram', 'Threads')
                or (video_id is not None and platform != 'YouTube')
                or not any(m.get('id') in asset_ids and m.get('rightsConfirmed') is True
                           for m in manifest.get('media') or [])):
            continue
        provider = platform.lower()
        cur.execute("""SELECT provider_account_id,scopes,authorization_generation::text
                       FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s
                       AND provider=%s AND revoked_at IS NULL""", (workspace, channel, provider))
        grant = cur.fetchone()
        if not grant or not grant[0] or grant[0] != manifest.get('providerAccountId'):
            continue
        if platform == 'YouTube' and not _youtube_readable(oauth, cur, workspace, job, actor, token, grant, now):
            continue
        yield job, manifest, grant


def revision_performance(cur, workspace, project, state, oauth, token, actor, now):
    receipt = project.get('export') or {}
    asset_id, revision = receipt.get('assetId'), project['revision']
    result = {'projectId':project['id'], 'revision':revision, 'exportAssetId':asset_id,
              'state':'unrendered' if not receipt else 'asset_unavailable', 'posts':[]}
    data = state.get('phase2') or {}
    asset = next((a for a in data.get('assets', []) if a.get('id') == asset_id), None)
    if not receipt or receipt.get('revision') != revision or not asset_kinds.is_postable_video(asset):
        return result
    sha = (receipt.get('manifest') or {}).get('sha256')
    provenance = asset.get('provenance') or {}
    if (not sha or asset.get('hash') != sha or provenance.get('sha256') != sha
            or provenance.get('projectId') != project['id'] or provenance.get('revision') != revision
            or provenance.get('operation') != 'composition_render'):
        return result

    result['state'] = 'unlinked'
    for job, manifest, grant in _published_media(cur, workspace, data, {asset_id}, oauth, token, actor, now):
        if not any(m.get('id') == asset_id and m.get('hash') == sha and m.get('rightsConfirmed') is True
                   for m in manifest.get('media') or []):
            continue
        platform, channel = manifest['platform'], manifest['channelId']
        provider, reference, verified = platform.lower(), job['providerReference'], job['verification']['at']
        if platform == 'YouTube':
            allowed = capability_matrix(oauth.providers['youtube'], grant[1], {'id':grant[0]})['analytics']['canExecute']
            metrics = _youtube_metrics(cur, workspace, channel, grant[0], reference) if allowed else []
        else:
            metrics = _growth_metrics(cur, workspace, channel, provider, reference, job['id'], grant[1])
        result['posts'].append({'provider':provider, 'providerPostId':reference, 'jobId':job['id'],
                                'verifiedAt':verified, 'metrics':metrics})
    result['posts'].sort(key=lambda p: (-p['verifiedAt'], p['jobId']))
    if result['posts']:
        result['state'] = 'linked'
    return result


def youtube_video_id(url):
    """Recognize a video identifier without contacting or resolving any supplied host."""
    message = "Use a YouTube watch, Shorts or share link, or upload an authorized video to your Library."
    if (not isinstance(url, str) or not url.isascii() or not 1 <= len(url) <= 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in url) or chr(92) in url):
        raise AlphaError(message)
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=32)
    except ValueError:
        raise AlphaError(message) from None
    if parts.scheme != 'https':
        raise AlphaError(message)
    host = parts.netloc.lower()
    if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com') and parts.path == '/watch':
        ids = query.get('v', [])
        candidate = ids[0] if len(ids) == 1 else ''
    elif host == 'youtu.be' and 'v' not in query:
        candidate = parts.path.removeprefix('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com') and parts.path.startswith('/shorts/') and 'v' not in query:
        candidate = parts.path.removeprefix('/shorts/')
    else:
        raise AlphaError(message)
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate):
        raise AlphaError(message)
    return candidate


def resolve_reference_link(cur, workspace, state, oauth, token, actor, now, body):
    if not isinstance(body, dict) or set(body) != {'url'}:
        raise AlphaError("Supply one published YouTube video link.")
    ident = youtube_video_id(body['url'])
    data = state.get('phase2') or {}
    assets = {asset['id']: asset for asset in data.get('assets', []) if asset_kinds.is_postable_video(asset)
              and asset['bytes'] <= MAX_MEDIA_BYTES and asset['duration'] * 1000 <= MAX_DURATION_MS}
    found = set()
    for job, manifest, grant in _published_media(cur, workspace, data, assets, oauth, token, actor, now, video_id=ident):
        progress = job.get('progress') or {}
        media = manifest.get('media') or []
        if progress.get('privacyStatus') != 'public' or progress.get('videoId') != ident or len(media) != 1:
            continue
        source = media[0]
        asset = assets.get(source.get('id'))
        if (asset and asset.get('hash') and source.get('rightsConfirmed') is True
                and all(source.get(key) == asset[key] for key in ('hash','objectName','etag','mime','bytes','bucket'))):
            found.add(asset['id'])
    if len(found) != 1:
        raise AlphaError("No single eligible Library video matches this verified public post in this workspace. "
                         "Upload an authorized MP4 or MOV up to 90 seconds and 64 MiB, then select it as the reference.",
                         404, code="creative_reference_link_unavailable")
    asset = assets[found.pop()]
    return {'assetId':asset['id'], 'durationSeconds':asset['duration']}
