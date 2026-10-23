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
WEBHOOK_IDENTITY = tuple(k for k in IDENTITY if k != 'botUserId') + ('webhookId', 'senderKind', 'credentialKind')

def identity_keys(target):
    return WEBHOOK_IDENTITY if target.get('senderKind') == 'webhook' else IDENTITY

def sender_kind(target):
    return 'webhook' if target.get('senderKind') == 'webhook' else 'bot'


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
            or any(not found.get(k) for k in identity_keys(found))
            or any(not snowflake(found.get(k)) for k in (('applicationId', 'webhookId', 'linkedUserId', 'guildId', 'channelId') if sender_kind(found) == 'webhook' else ('applicationId', 'botUserId', 'linkedUserId', 'guildId', 'channelId')))):
        reject('Select an authorized Discord server and channel for this post.')
    if (sender_kind(found) == 'webhook') != (channel.get('discordConnectionKind') == 'webhook') or sender_kind(found) == 'webhook' and found.get('credentialKind') != 'webhook':
        reject('Discord sender kind changed.')
    return found


def register_destination(state, channel, evidence, generation, actor, now):
    """A default change registers one resource; it never edits another resource."""
    wid, connection = state['workspace']['id'], channel['id']
    webhook = evidence.get('senderKind') == 'webhook'
    snow_keys = ('applicationId', 'linkedUserId', 'guildId', 'channelId', 'webhookId' if webhook else 'botUserId')
    if (webhook != (channel.get('discordConnectionKind') == 'webhook') or not generation
            or webhook and evidence.get('credentialKind') != 'webhook'
            or any(not snowflake(evidence.get(k)) for k in snow_keys)):
        reject('Discord did not confirm this installation and destination.')
    selected_id = destination_id(wid, connection, evidence['guildId'], evidence['channelId'])
    records = channel.setdefault('discordDestinations', [])
    prior = next((d for d in records if d.get('id') == selected_id), None)
    identity = {k: evidence[k] for k in snow_keys}
    if webhook:
        identity.update(senderKind='webhook', credentialKind='webhook')
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
    if manifest.get('senderKind') == 'webhook' or sender_kind((manifest.get('discord') or {}).get('target') or {}) == 'webhook':
        text = (manifest.get('payload') or {}).get('text')
        if (media or manifest.get('engagementReply') or manifest.get('publishOptions')
                or not isinstance(text, str) or not text.strip() or '\x00' in text
                or len(text.encode('utf-16-le')) // 2 > 2000):
            reject('Webhook publishing supports text only, without threads, replies, attachments or sender overrides.')
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
    wire = {'content': manifest['payload']['text'], 'allowed_mentions': {'parse': []}, 'files': files}
    if manifest.get('senderKind') == 'webhook': wire['flags'] = 4  # suppress automatic embeds; exact text-only contract
    if 'discordSenderName' in manifest:
        # The per-send override is part of the frozen wire content and nothing else ever supplies it. A bot manifest
        # has no such field (the nickname is a property of the server), so one that carries it is not authentic.
        if manifest.get('senderKind') != 'webhook':
            reject('Only a webhook post can carry a custom sender name.')
        from .sender_names import validate_name
        wire['username'] = validate_name(manifest['discordSenderName'], 'webhook')
    if manifest.get('operation') == 'discord.reply':
        reply = manifest.get('engagementReply') or {}
        text = manifest['payload']['text']
        if (manifest.get('schema') != 'rafii.discord.reply.v1' or media
                or not snowflake(reply.get('parentMessageId')) or not snowflake(reply.get('parentAuthorId'))
                or not isinstance(text, str) or not text.strip() or '\x00' in text
                or len(text.encode('utf-16-le')) // 2 > 2000 or reply.get('textDigest') != digest(text)):
            reject('Review the exact Discord reply and parent message again.')
        wire['allowed_mentions']['replied_user'] = False
        wire['message_reference'] = {'type': 0, 'message_id': reply['parentMessageId'], 'fail_if_not_exists': True}
    elif manifest.get('engagementReply'):
        reject('The Discord reply operation changed.')
    return wire


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


def same_webhook_effect(original, manifest):
    """Rotating a webhook cannot erase an unresolved same-channel create."""
    old = (original.get('discord') or {}).get('target') or {}
    new = (manifest.get('discord') or {}).get('target') or {}
    if (sender_kind(old) != 'webhook' and sender_kind(new) != 'webhook'
            or original.get('workspaceId') != manifest.get('workspaceId')
            or any(not old.get(k) or old.get(k) != new.get(k) for k in ('applicationId', 'guildId', 'channelId'))):
        return False
    try:
        prior, current = wire_content(original), wire_content(manifest)
        return all(prior.get(k) == current.get(k) for k in ('content', 'allowed_mentions', 'files', 'message_reference'))
    except (AlphaError, KeyError, TypeError, ValueError):
        return False


def assert_no_unresolved_repeat(state, manifest, *, excluding=None):
    frozen = manifest['discord']
    for job in state['phase2'].get('jobs', []):
        if job.get('id') == excluding:
            continue
        original = job.get('manifest') or {}
        if (original.get('platform') == 'Discord' and unresolved_delivery(job)
                and (same_webhook_effect(original, manifest)
                     or (original.get('discord') or {}).get('deliveryDigest') == frozen['deliveryDigest']
                     or (not original.get('discord') and original.get('channelId') == manifest['channelId']
                         and original.get('payload') == manifest.get('payload')))):
            reject('An earlier Discord delivery is unresolved. Reconcile it before approving another copy.')


def freeze_manifest(state, channel, manifest, selected_id):
    record = destination(state, channel, selected_id)
    target = {k: copy.deepcopy(record.get(k)) for k in identity_keys(record) + LABELS}
    manifest['senderKind'] = sender_kind(target)
    if manifest['senderKind'] == 'webhook':
        # Frozen per connection at review: the setting of THIS connection's own channel record, validated, and only
        # while the feature is on. Unset (or the feature off) freezes nothing: the webhook's own name, as in RC1.
        from .sender_names import frozen_webhook_name
        frozen_name = frozen_webhook_name(channel)
        if frozen_name is not None:
            manifest['discordSenderName'] = frozen_name
    wire = wire_content(manifest)
    delivery_digest = digest({'workspaceId': manifest['workspaceId'],
                              'applicationId': target['applicationId'],
                              **({'sender': {'kind': 'webhook', 'id': target['webhookId']}} if sender_kind(target) == 'webhook' else {'botUserId': target['botUserId']}),
                              'guildId': target['guildId'], 'channelId': target['channelId'], 'wire': wire})
    operation = digest({'target': {k: target[k] for k in identity_keys(target)}, 'wire': wire,
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
                and all(record.get(k) == target.get(k) for k in identity_keys(target))
                and manifest.get('senderKind', 'bot') == sender_kind(target)
                and frozen['wireDigest'] == digest(wire_content(manifest))
                and frozen['operationDigest'] == digest({'target': {k: target[k] for k in identity_keys(target)},
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


def job_authorized(state, channel, job, *, now=None):
    try:
        manifest = job['manifest']
        assert_no_unresolved_repeat(state, manifest, excluding=job['id'])
        if manifest.get('operation') == 'discord.reply':
            import time
            from .engagement import reply_current
            if job.get('automation') or not reply_current(state, manifest, time.time() if now is None else now):
                return False
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


def approved_campaign_channel(channel, decision):
    """Use only the original human decision, never a request-supplied override."""
    frozen = copy.deepcopy(channel)
    if channel.get('discordConnectionKind') == 'webhook':
        if decision.get('discordSenderName') is None:
            frozen.pop('discordSenderName', None)
        else:
            from .sender_names import validate_name
            frozen['discordSenderName'] = validate_name(decision['discordSenderName'], 'webhook')
    return frozen


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
        if sender_kind(target) == 'webhook':
            return (grant.get('provider') == 'discord' and 'webhook.incoming' in grant.get('scopes', [])
                    and session.get('kind') == 'webhook' and session.get('workspaceId') == manifest['workspaceId']
                    and session.get('applicationId') == target['applicationId']
                    and session.get('webhookId') == target['webhookId'] and session.get('guild') == target['guildId']
                    and session.get('channel') == target['channelId'] and session.get('user') == target['linkedUserId']
                    and grant.get('authorizationGeneration') == target['authorizationGeneration'])
        return (session.get('kind') != 'webhook' and grant.get('provider') == 'discord' and 'bot' in grant.get('scopes', [])
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
