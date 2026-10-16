"""Versioned, tenant-bound Discord authority. No credentials, IO or scheduler.

Workspace commands and the worker call these under the existing workspace row
lock. Provider checks and media reads happen before the final SQL handoff.
"""
import copy
import hashlib
import json
import math
import re
import uuid

from postriff_alpha.domain import AlphaError

SCHEMA = 'rafii.discord.publish.v2'
IDENTITY = ('workspaceId', 'connectionId', 'applicationId', 'botUserId',
            'linkedUserId', 'guildId', 'channelId', 'authorizationGeneration',
            'resourceGeneration', 'id')
LABELS = ('guildName', 'channelName', 'kind')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reject(message='Discord authorization changed. Review this exact server and channel again.'):
    raise AlphaError(message, 409, code='discord_approval_required')


def snowflake(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{5,25}', value) is not None


def destination_id(workspace_id, connection_id, guild_id, channel_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                         'rafii:discord:destination:' + digest([workspace_id, connection_id, guild_id, channel_id])))


def destination(state, channel, selected_id):
    found = next((d for d in channel.get('discordDestinations', [])
                  if isinstance(d, dict) and d.get('id') == selected_id), None)
    if (not found or found.get('status') != 'authorized' or channel.get('revoked')
            or found.get('workspaceId') != state['workspace']['id']
            or found.get('connectionId') != channel.get('id')
            or found.get('authorizationGeneration') != channel.get('discordAuthorizationGeneration')
            or any(not found.get(k) for k in IDENTITY)
            or any(not snowflake(found.get(k)) for k in ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId'))):
        reject('Select an authorized Discord server and channel for this post.')
    return found


def register_destination(state, channel, evidence, generation, actor, now):
    """A default change registers one resource; it never edits another resource."""
    wid, connection = state['workspace']['id'], channel['id']
    if not generation or any(not snowflake(evidence.get(k)) for k in
                             ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId')):
        reject('Discord did not confirm this installation and destination.')
    selected_id = destination_id(wid, connection, evidence['guildId'], evidence['channelId'])
    records = channel.setdefault('discordDestinations', [])
    prior = next((d for d in records if d.get('id') == selected_id), None)
    identity = {k: evidence[k] for k in ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId')}
    unchanged = (prior and prior.get('status') == 'authorized'
                 and prior.get('authorizationGeneration') == generation
                 and all(prior.get(k) == v for k, v in identity.items()))
    record = {**identity, 'id': selected_id, 'workspaceId': wid, 'connectionId': connection,
              'authorizationGeneration': generation,
              'resourceGeneration': prior['resourceGeneration'] if unchanged else str(uuid.uuid4()),
              'status': 'authorized', 'authorizedBy': actor, 'authorizedAt': now,
              **{k: evidence.get(k, '') for k in LABELS}}
    if prior:
        prior.update(record)
    else:
        records.append(record)
    channel['discordAuthorizationGeneration'] = generation
    channel['defaultDestinationId'] = selected_id
    return record


def revoke_destination(state, channel, selected_id, actor, now):
    record = destination(state, channel, selected_id)
    record.update(status='revoked', resourceGeneration=str(uuid.uuid4()), revokedBy=actor, revokedAt=now)
    if channel.get('defaultDestinationId') == selected_id:
        channel['defaultDestinationId'] = None


def wire_content(manifest):
    media = manifest.get('media') or []
    if len(media) > 1 or any(not str(a.get('mime', '')).startswith('image/') for a in media):
        reject('Discord posts support text and at most one approved image.')
    files = []
    for index, asset in enumerate(media):
        if (not re.fullmatch(r'[a-f0-9]{64}', str(asset.get('hash', '')))
                or type(asset.get('bytes')) is not int or asset['bytes'] <= 0):
            reject('The Discord attachment needs an immutable hash and byte count.')
        suffix = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}.get(asset['mime'])
        if suffix is None:
            reject('Choose a supported Discord image.')
        files.append({'id': index, 'filename': f'rafii.{suffix}', 'description': asset.get('alt') or '',
                      'sha256': asset['hash'], 'bytes': asset['bytes'], 'mime': asset['mime']})
    return {'content': manifest['payload']['text'], 'allowed_mentions': {'parse': []}, 'files': files}


def unresolved_delivery(job):
    """A lease or a new review cannot turn a potentially sent POST into a retry."""
    if job.get('state') == 'verified':
        return False
    intents = job.get('discordDispatchIntents') or []
    receipts = job.get('discordReceipts') or []
    if job.get('providerReference'):
        return True
    if not intents:
        return job.get('state') in ('uncertain', 'provider_accepted', 'published', 'submitting')
    for intent in intents:
        evidence = [r for r in receipts if r.get('intentId') == intent.get('id')]
        if not evidence or evidence[-1].get('deliveryEvidence') not in ('not_sent', 'rejected'):
            return True
    return False


def assert_no_unresolved_repeat(state, manifest, *, excluding=None):
    frozen = manifest['discord']
    for job in state['phase2'].get('jobs', []):
        if job.get('id') == excluding:
            continue
        original = job.get('manifest') or {}
        if (original.get('platform') == 'Discord' and unresolved_delivery(job)
                and ((original.get('discord') or {}).get('deliveryDigest') == frozen['deliveryDigest']
                     or (not original.get('discord') and original.get('channelId') == manifest['channelId']
                         and original.get('payload') == manifest.get('payload')))):
            reject('An earlier Discord delivery is unresolved. Reconcile it before approving another copy.')


def freeze_manifest(state, channel, manifest, selected_id):
    record = destination(state, channel, selected_id)
    target = {k: copy.deepcopy(record.get(k)) for k in IDENTITY + LABELS}
    wire = wire_content(manifest)
    delivery_digest = digest({'workspaceId': manifest['workspaceId'],
                              'applicationId': target['applicationId'], 'botUserId': target['botUserId'],
                              'guildId': target['guildId'], 'channelId': target['channelId'], 'wire': wire})
    operation = digest({'target': {k: target[k] for k in IDENTITY}, 'wire': wire,
                        'variantId': manifest['variantId'], 'contentRevision': manifest['contentRevision'],
                        'timing': manifest['timing']})
    ended = [j for j in state['phase2'].get('jobs', [])
             if (j.get('manifest', {}).get('discord') or {}).get('operationDigest') == operation
             and j.get('state') in ('failed', 'canceled') and not unresolved_delivery(j)]
    publication = str(uuid.uuid5(uuid.NAMESPACE_URL, 'rafii:discord:publication:' + operation + ':' + digest(manifest)
                                + (':' + ended[-1]['id'] if ended else '')))
    manifest['destinationId'] = record['id']
    manifest['discord'] = {'schema': SCHEMA, 'target': target, 'wireDigest': digest(wire),
                           'deliveryDigest': delivery_digest, 'operationDigest': operation,
                           'publicationId': publication}
    assert_no_unresolved_repeat(state, manifest)


def manifest_current(state, channel, manifest):
    try:
        frozen = manifest['discord']
        target = frozen['target']
        record = destination(state, channel, manifest['destinationId'])
        return (frozen['schema'] == SCHEMA and manifest['workspaceId'] == state['workspace']['id']
                and target['workspaceId'] == manifest['workspaceId'] and target['connectionId'] == manifest['channelId']
                and target['id'] == manifest['destinationId']
                and all(record.get(k) == target.get(k) for k in IDENTITY)
                and frozen['wireDigest'] == digest(wire_content(manifest))
                and frozen['operationDigest'] == digest({'target': {k: target[k] for k in IDENTITY},
                    'wire': wire_content(manifest), 'variantId': manifest['variantId'],
                    'contentRevision': manifest['contentRevision'], 'timing': manifest['timing']}))
    except (AlphaError, KeyError, TypeError, ValueError):
        return False


def approval(job):
    manifest = job['manifest']
    frozen = manifest['discord']
    result = {'schema': SCHEMA, 'target': copy.deepcopy(frozen['target']), 'publicationId': job['id'],
              'manifestDigest': digest(manifest), 'wireDigest': frozen['wireDigest'],
              'approvedBy': job['approvedBy'], 'approvedAt': job['approvedAt'],
              'timing': copy.deepcopy(manifest['timing'])}
    if job.get('discordHumanApproval'):
        result['humanApproval'] = copy.deepcopy(job['discordHumanApproval'])
    # A separate digest avoids a manifest <-> approval hash cycle.
    result['digest'] = digest(result)
    return result


def job_authorized(state, channel, job):
    try:
        manifest = job['manifest']
        assert_no_unresolved_repeat(state, manifest, excluding=job['id'])
        if job.get('automation'):
            if job['automation'].get('approvedVia') != 'human' or not job.get('discordHumanApproval'):
                return False
            from .. import campaigns
            run = next((r for r in campaigns._root(state)['occurrences'] if r.get('id') == job['automation']['occurrenceId']), None)
            item = next((i for i in (run or {}).get('items', []) if i.get('key') == job['automation']['itemKey']), None)
            decision = (item or {}).get('decision') or {}
            human = job['discordHumanApproval']
            if (not item or item.get('approvedVia') != 'human' or decision.get('by') != job['approvedBy']
                    or human.get('by') != decision.get('by') or human.get('at') != decision.get('at')
                    or decision.get('discord') != manifest['discord'] or decision.get('timing') != manifest['timing']
                    or item.get('publishAt') != manifest['timing']['timestamp']):
                return False
        return (manifest_current(state, channel, manifest)
                and job['id'] == manifest['discord']['publicationId']
                and job['approvedBy'] == manifest['actor']
                and type(job['approvedAt']) in (int, float) and math.isfinite(job['approvedAt'])
                and job.get('discordAuthorization') == approval(job)
                and (not job.get('automation') or job['automation'].get('approvedVia') == 'human'))
    except (AlphaError, KeyError, TypeError, ValueError):
        return False


def campaign_binding(state, channel, variant, selected_id, publish_at, zone, now):
    """Text-only automation: bind the original human decision, before queue commit."""
    import datetime as dt
    import zoneinfo
    from ..contracts import resolve_time
    if type(publish_at) not in (int, float) or not math.isfinite(publish_at) or publish_at % 60 != 0:
        reject('Choose an exact future minute for this Discord publication.')
    local = dt.datetime.fromtimestamp(publish_at, dt.timezone.utc).astimezone(zoneinfo.ZoneInfo(zone))
    timing = resolve_time(local.strftime('%Y-%m-%dT%H:%M'), zone, local.fold, now)
    if timing['timestamp'] != publish_at:
        reject('Review the exact Discord publication time again.')
    manifest = {'workspaceId': state['workspace']['id'], 'channelId': channel['id'],
                'variantId': variant['id'], 'contentRevision': variant['revision'],
                'payload': {'text': variant['text'], 'language': variant['language']}, 'media': [], 'timing': timing}
    freeze_manifest(state, channel, manifest, selected_id)
    return manifest


def grant_matches(manifest, grant, session):
    try:
        target = manifest['discord']['target']
        return (grant.get('provider') == 'discord' and 'bot' in grant.get('scopes', [])
                and grant.get('authorizationGeneration') == target['authorizationGeneration']
                and session.get('applicationId') == target['applicationId']
                and session.get('botUserId') == target['botUserId']
                and session.get('guild') == target['guildId'] and session.get('user') == target['linkedUserId'])
    except (KeyError, TypeError):
        return False


def record_receipt(job, claimed, result, now, late):
    """Append evidence even after lease expiry. It cannot overwrite a newer lease."""
    original = claimed['job']
    intent = claimed.get('discordIntent')
    if not intent:
        return False
    receipt = {'intentId': intent['id'], 'publicationId': original['id'],
               'authorizationDigest': original.get('discordAuthorization', {}).get('digest'),
               'manifestDigest': digest(original['manifest']), 'at': now, 'late': bool(late),
               'state': result['state'], 'deliveryEvidence': result.get('discordDeliveryEvidence', 'uncertain'),
               **{k: result[k] for k in ('reference', 'url', 'verification') if k in result}}
    receipt['id'] = digest({k: v for k, v in receipt.items() if k not in ('at', 'late')})
    records = job.setdefault('discordReceipts', [])
    if any(r.get('id') == receipt['id'] for r in records):
        return False
    records.append(receipt)
    return True
