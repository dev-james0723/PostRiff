"""Delete attributable YouTube runtime outputs without rewriting approvals.

The workspace row must be locked before credentials or upload journals. The
30-day sweep is cron-only and selects at most 100 workspaces per invocation.
API identifiers embedded in immutable approval snapshots remain a separate,
unresolved public-compliance boundary; this helper never changes their digest.
"""
import copy
import json
import math
import re
import time

from postriff_alpha.domain import AlphaError
from ..contracts import digest

KEY = 'youtubeProviderOutput'
REMOVED = 'youtubeProviderDataRemoved'
INGESTED = 'youtubeProviderDataIngestedAt'
IDENTITY_INGESTED = 'youtubeIdentityIngestedAt'
RETENTION_SECONDS = 30 * 86400
NOTICE = 'YouTube runtime data was removed. This operation is held and will not upload again. A schedule already accepted by YouTube is not canceled by data removal.'


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def youtube_job(job, connection=None):
    manifest = job.get('manifest') or {}
    return (manifest.get('platform') == 'YouTube' and isinstance(manifest.get('channelId'), str)
            and bool(manifest['channelId']) and (connection is None or manifest['channelId'] == connection))


def has_output(job):
    return any(key in job for key in ('providerReference', 'url', 'container', 'progress', 'providerConfirmed',
                                      'verification', 'insights', 'comments')) and not job.get(REMOVED)


def source(workspace, job, generation, now):
    """Only the canonical worker may stamp output; cached receipts cannot extend it."""
    manifest = job['manifest']
    previous = job.get(KEY) if isinstance(job.get(KEY), dict) else {}
    same = (previous.get('workspaceId') == workspace and previous.get('connectionId') == manifest['channelId']
            and previous.get('actor') == job.get('approvedBy') and previous.get('authorizationGeneration') == generation)
    ingested = number(previous.get('ingestedAt')) if same else None
    if ingested is None and has_output(job):
        ingested = number(job.get('approvedAt'))
    ingested = now if ingested is None else min(ingested, now)
    return {'workspaceId': workspace, 'connectionId': manifest['channelId'], 'actor': job['approvedBy'],
            'authorizationGeneration': generation, 'ingestedAt': ingested, 'expiresAt': ingested + RETENTION_SECONDS}


def assert_completion(cur, workspace, job, claimed, now):
    """Fence an already-returned response in the SAME transaction as its save."""
    manifest, prior = job.get('manifest') or {}, claimed.get('job') or {}
    generation = claimed.get('youtubeAuthorizationGeneration')
    actor = job.get('approvedBy')
    if (not youtube_job(job) or manifest.get('workspaceId') != workspace or not actor
            or actor != manifest.get('actor') or actor != prior.get('approvedBy')
            or job.get('approvalDigest') != digest(manifest) or job.get('approvalDigest') != prior.get('approvalDigest')
            or manifest != prior.get('manifest') or job.get(REMOVED) or job.get('privacyErased') or manifest.get('privacyErased')
            or not isinstance(generation, str) or not generation):
        raise AlphaError('The YouTube result no longer belongs to the current approved operation.', 409, code='youtube_stale_completion')
    stamp = job.get(KEY) if isinstance(job.get(KEY), dict) else {}
    if stamp and (stamp.get('workspaceId') != workspace or stamp.get('connectionId') != manifest['channelId']
                  or stamp.get('actor') != actor or stamp.get('authorizationGeneration') != generation
                  or number(stamp.get('expiresAt')) is None or stamp['expiresAt'] <= now):
        raise AlphaError('The YouTube runtime data expired or its authorization changed.', 409, code='youtube_stale_completion')
    # The caller already owns workspace FOR UPDATE. Match disconnect's lock
    # order and retain this credential fence until the workspace UPDATE commits.
    cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE",
                (workspace, manifest['channelId']))
    row = cur.fetchone()
    if not row or row[0] != generation:
        raise AlphaError('The YouTube result arrived after disconnect or replacement consent.', 409, code='youtube_stale_completion')
    cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p",
                (workspace, actor))
    member = cur.fetchone()
    from ..permissions import Membership
    if not member or not Membership.from_row(member[0], can_publish=member[1]).allows('approve') or (job.get('youtubeAgent') and member[0] != 'owner'):
        raise AlphaError('The YouTube approver no longer has publishing authority.', 409, code='youtube_stale_completion')
    return generation


def scrub_job(job, reason, now):
    """Runtime fields only: immutable manifest, actor and approval evidence survive."""
    for key in ('providerReference', 'url', 'container', 'progress', 'providerConfirmed', 'verification',
                'resultSchema', 'insights', 'comments', KEY):
        job.pop(key, None)
    job.update(state='held', leaseOwner=None, leaseUntil=0, nextAt=0, nextAction=NOTICE,
               providerConfirmed=NOTICE, progress={'version': 2, 'stage': 'held', 'errorCategory': reason})
    job[REMOVED] = True
    job['youtubeDataRemovalReason'] = reason
    job.pop('leaseId', None)
    # Avoid repeated sweeps growing the immutable operational timeline.
    events = job.setdefault('events', [])
    if not events or events[-1].get('dataRemovalReason') != reason:
        events.append({'at': now, 'state': 'held', 'message': NOTICE, 'execution': 'server-data-cleanup', 'dataRemovalReason': reason})


def scrub_channel(channel):
    for key in ('providerAccountId', IDENTITY_INGESTED, 'pictureDigest'):
        channel.pop(key, None)
    channel.update(account='Disconnected YouTube channel', configured=False, identityVerified=False,
                   capabilityVerified=False, revoked=True, scopes=[], verifiedAt=0, expiresAt=0)
    channel[REMOVED] = True


def tombstone(state, reason, now):
    value = {'version': 2, 'stage': 'held', REMOVED: True, 'dataRemovalReason': reason, 'removedAt': now}
    if isinstance(state.get('manifestDigest'), str):
        value['manifestDigest'] = state['manifestDigest']
    return value


def _save_workspace(cur, workspace, state):
    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))


def _tombstones(cur, workspace, connection, reason, now, *, expired_only=False):
    predicate, params = '', (workspace, connection)
    if expired_only:
        predicate = ' AND (' + _journal_expired() + ')'
        params += (now - RETENTION_SECONDS, now - RETENTION_SECONDS, now - RETENTION_SECONDS)
    cur.execute('SELECT operation_key,state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s AND NOT coalesce((state->>\'' + REMOVED + "')::boolean,false)" + predicate + ' ORDER BY operation_key FOR UPDATE', params)
    for operation, state in cur.fetchall():
        cur.execute('UPDATE public.pr_youtube_uploads SET state=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND operation_key=%s',
                    (json.dumps(tombstone(state, reason, now)), workspace, connection, operation))


def purge_connection(cur, workspace, connection, now=None):
    """Caller owns workspace FOR UPDATE, including mark_youtube_revoked."""
    now = time.time() if now is None else now
    cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
    row = cur.fetchone()
    if row:
        state = copy.deepcopy(json.loads(row[0]) if isinstance(row[0], str) else row[0])
        data, changed = state.get('phase2') or {}, False
        for job in data.get('jobs') or []:
            if youtube_job(job, connection):
                scrub_job(job, 'youtube_disconnected_data_removed', now)
                changed = True
        for channel in data.get('channels') or []:
            if channel.get('id') == connection and channel.get('platform') == 'YouTube':
                scrub_channel(channel)
                changed = True
        if changed:
            _save_workspace(cur, workspace, state)
    _tombstones(cur, workspace, connection, 'youtube_disconnected_data_removed', now)


def _journal_expired():
    return ("jsonb_path_exists(state, '$.youtubeProviderDataIngestedAt ? (@ <= $cutoff)', jsonb_build_object('cutoff', %s))"
            " OR (jsonb_typeof(state->'youtubeProviderDataIngestedAt') IS DISTINCT FROM 'number' AND ("
            "jsonb_path_exists(state, '$.createdAt ? (@ <= $cutoff)', jsonb_build_object('cutoff', %s)) OR updated_at<=to_timestamp(%s)))")


def _expired_job(job, now):
    if not youtube_job(job) or not has_output(job):
        return False
    stamp = job.get(KEY)
    if isinstance(stamp, dict):
        expires = number(stamp.get('expiresAt'))
        return expires is None or expires <= now
    if KEY in job:
        return True  # Match SQL selection; malformed tags must not starve later batches.
    # No freeform inference: these are server-owned output slots on a YouTube
    # job. The approval clock is a conservative lower bound on ingestion.
    approved = number(job.get('approvedAt'))
    return approved is None or approved <= now - RETENTION_SECONDS


def _legacy_identity_ingestion(cur, workspace, channel, now):
    """Credential creation is an older bound, never a new 30-day period."""
    identifier = channel.get('providerAccountId')
    if not isinstance(identifier, str) or not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', identifier):
        return None
    cur.execute("SELECT provider_account_id,extract(epoch from created_at) FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE",
                (workspace, channel.get('id')))
    row = cur.fetchone()
    if not row or row[0] != identifier:
        return None
    created = float(row[1]) if row[1] is not None else None
    return created if number(created) is not None and created <= now else None


def purge_expired(cur, now=None):
    """Bounded cron selection; never called by foreground overview/cache expiry."""
    now = time.time() if now is None else now
    cutoff = now - RETENTION_SECONDS
    # jsonpath compares numbers safely; missing legacy clocks expire rather
    # than gaining an invented fresh retention period.
    jobs = """EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
        WHERE j#>>'{manifest,platform}'='YouTube' AND NOT j ? 'youtubeProviderDataRemoved'
          AND (j ?| ARRAY['providerReference','url','container','progress','providerConfirmed','verification','insights','comments'])
          AND (jsonb_path_exists(j, '$.youtubeProviderOutput.expiresAt ? (@ <= $clock)', jsonb_build_object('clock', %s))
            OR (j ? 'youtubeProviderOutput' AND jsonb_typeof(j#>'{youtubeProviderOutput,expiresAt}') IS DISTINCT FROM 'number')
            OR (NOT j ? 'youtubeProviderOutput' AND (jsonb_typeof(j->'approvedAt') IS DISTINCT FROM 'number' OR jsonb_path_exists(j, '$.approvedAt ? (@ <= $cutoff)', jsonb_build_object('cutoff', %s))))))"""
    channels = """EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,channels}','[]'::jsonb)) c
        WHERE c->>'platform'='YouTube' AND c->>'evidenceSource'='live_provider' AND NOT c ? 'youtubeProviderDataRemoved'
          AND (jsonb_typeof(c->'youtubeIdentityIngestedAt') IS DISTINCT FROM 'number' OR jsonb_path_exists(c, '$.youtubeIdentityIngestedAt ? (@ <= $cutoff)', jsonb_build_object('cutoff', %s))))"""
    cur.execute('SELECT id::text FROM public.pr_workspaces w WHERE (' + jobs + ' OR ' + channels + ') OR EXISTS('
                'SELECT 1 FROM public.pr_youtube_uploads u WHERE u.workspace_id=w.id AND NOT u.state ? %s AND (' + _journal_expired().replace('state', 'u.state').replace('updated_at', 'u.updated_at') + ')) ORDER BY id LIMIT 100',
                (now, cutoff, cutoff, REMOVED, cutoff, cutoff, cutoff))
    workspaces = [row[0] for row in cur.fetchall()]
    for workspace in workspaces:
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED', (workspace,))
        row = cur.fetchone()
        if not row:
            continue
        state = copy.deepcopy(json.loads(row[0]) if isinstance(row[0], str) else row[0])
        data, changed, expired_connections = state.get('phase2') or {}, False, set()
        for channel in data.get('channels') or []:
            ingested = number(channel.get(IDENTITY_INGESTED))
            if (ingested is None and channel.get('platform') == 'YouTube' and channel.get('evidenceSource') == 'live_provider'
                    and not channel.get(REMOVED)):
                ingested = _legacy_identity_ingestion(cur, workspace, channel, now)
                if ingested is not None:
                    channel[IDENTITY_INGESTED] = ingested
                    changed = True
            if (channel.get('platform') == 'YouTube' and channel.get('evidenceSource') == 'live_provider'
                    and not channel.get(REMOVED) and (ingested is None or ingested <= cutoff)):
                expired_connections.add(channel['id'])
                scrub_channel(channel)
                changed = True
        for job in data.get('jobs') or []:
            if youtube_job(job) and (job['manifest']['channelId'] in expired_connections or _expired_job(job, now)):
                scrub_job(job, 'youtube_expired_data_removed', now)
                changed = True
        if changed:
            _save_workspace(cur, workspace, state)
        cur.execute('SELECT DISTINCT connection_id FROM public.pr_youtube_uploads WHERE workspace_id=%s AND NOT state ? %s AND (' + _journal_expired() + ')',
                    (workspace, REMOVED, cutoff, cutoff, cutoff))
        connections = {row[0] for row in cur.fetchall()} | expired_connections
        for connection in sorted(connections):
            _tombstones(cur, workspace, connection, 'youtube_expired_data_removed', now, expired_only=connection not in expired_connections)
