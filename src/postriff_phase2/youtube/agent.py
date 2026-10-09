"""Bounded Library publishing plans. No paid model calls or implied publication consent.

Drafting is local and reviewable. Autopilot authority names finite exact drafts,
assets, channel, times and limits; dispatch uses the ordinary approval/worker path.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from postriff_alpha import learning
from ..asset_kinds import is_postable_video
from ..contracts import digest, resolve_time
from .model import READ, UPLOAD, MANAGE, has_scopes, resource_id, validate_video, project_public_gate

MAX_PLANS = 100
MAX_POLICY_DAYS = 30
DRAFT_FIELDS = ('id', 'connectionId', 'channelId', 'assetId', 'assetHash', 'variantId', 'variantRevision',
                'publishOptions', 'timing', 'uploadWorkflow', 'uploadAt', 'rightsConfirmed', 'createdBy')
POLICY_FIELDS = ('id', 'connectionId', 'channelId', 'drafts', 'assetIds', 'timeZone', 'startsAt', 'endsAt', 'maxDaily')


def root(state):
    return state.setdefault('youtubeAgent', {'drafts': [], 'policies': []})


def draft_digest(draft):
    return digest({key: draft.get(key) for key in DRAFT_FIELDS})


def policy_digest(policy):
    return digest({key: policy.get(key) for key in POLICY_FIELDS})


def policy_authorization(policy):
    """Exact authority generation, separate from the owner's approved rules digest."""
    return {'policyId': policy.get('id'), 'policyDigest': policy_digest(policy),
            'grantedBy': policy.get('grantedBy'), 'grantedAt': policy.get('grantedAt'),
            'authorizationGeneration': policy.get('authorizationGeneration'), 'status': policy.get('status')}


def fleet_authorization_current(state, candidate):
    policy = next((p for p in root(state)['policies']
                   if p.get('id') == candidate[2] and p.get('connectionId') == candidate[1]), None)
    if not policy or len(candidate) != 6 or candidate[5] != policy_authorization(policy):
        return False
    return candidate[4] is None or root(state).get('fleetLease', {}).get('authorization') == candidate[5]


def find_draft(state, connection, identifier):
    draft = next((d for d in root(state)['drafts'] if d.get('id') == identifier and d.get('connectionId') == connection), None)
    if not draft:
        raise AlphaError('YouTube plan unavailable.', 404)
    return draft


def _channel(state, connection):
    channel = next((c for c in state.get('phase2', {}).get('channels', [])
                    if c.get('id') == connection and c.get('platform') == 'YouTube' and not c.get('revoked')), None)
    if not channel:
        raise AlphaError('Connection unavailable.', 404)
    resource_id(channel.get('providerAccountId'), 'channel')
    return channel


def _asset(state, identifier):
    asset = next((a for a in state.get('phase2', {}).get('assets', []) if a.get('id') == identifier), None)
    if not is_postable_video(asset, 'YouTube'):
        raise AlphaError('Choose an inspected, immutable video from this workspace Library.', 409)
    return asset


def prepare_draft(state, connection, body, actor, now):
    channel, asset = _channel(state, connection), _asset(state, body.get('assetId'))
    if body.get('rightsConfirmed') is not True:
        raise AlphaError('Confirm the rights to this Library video before preparing its plan.', 400)
    if sum(1 for draft in root(state)['drafts'] if draft.get('status') == 'proposed'
           and draft.get('timing', {}).get('timestamp', 0) > now) >= MAX_PLANS:
        raise AlphaError('This workspace has reached its 100 pending future YouTube plan limit.', 409)
    timing = resolve_time(body.get('localTime'), body.get('timeZone'), body.get('fold'), now)
    options = copy.deepcopy(body.get('publishOptions') or {})
    suggested = re.sub(r'[_-]+', ' ', re.sub(r'\.[A-Za-z0-9]{1,8}$', '', str(asset.get('displayTitle') or asset.get('originalFilename') or asset.get('name') or ''))).strip()
    options.setdefault('title', suggested[:100] or 'Untitled video')
    options.setdefault('description', '')
    if options.get('privacyStatus') not in ('private', 'public'):
        raise AlphaError('Library plans support private uploads or native future public publication. Unlisted timing requires a separate exact creator workflow.', 400)
    # Audience/synthetic declarations and visibility are never inferred from video appearance.
    options = validate_video(options, [asset], now=datetime.fromtimestamp(now, timezone.utc))
    options['publicationMode'] = 'schedule'
    if options.get('publishAt'):
        expected = datetime.fromtimestamp(timing['timestamp'], timezone.utc).isoformat().replace('+00:00', 'Z')
        if options['publishAt'] != expected:
            raise AlphaError('The publication date and native YouTube schedule must match.', 400)
    workflow = body.get('uploadWorkflow', 'upload_now')
    if workflow not in ('upload_now', 'upload_later'):
        raise AlphaError('Choose upload now or queue upload for later.', 400)
    upload_at = now
    if workflow == 'upload_later':
        upload_time = resolve_time(body.get('uploadLocalTime'), timing['timeZone'], body.get('uploadFold'), now)
        upload_at = upload_time['timestamp']
        if upload_at > timing['timestamp'] - 600:
            raise AlphaError('Queue the upload at least ten minutes before the planned publication. Processing may take longer.', 400)
    elif options['privacyStatus'] == 'private':
        # Private upload has no automatic future public transition.
        upload_at = now
    identifier, variant_id = uuid.uuid4().hex, uuid.uuid4().hex
    text = options['description'] or options['title']
    variant = {'id': variant_id, 'platform': 'YouTube', 'channelId': connection, 'language': body.get('language', 'en'),
               'text': text, 'revision': 1, 'sourceIds': [], 'unknowns': [], 'warnings': [], 'needsReview': True,
               'blockedByRetraction': False, 'voiceRevision': state['speaker']['activeRevision'],
               'styleRevision': learning.revision(state), 'speakerId': state['speaker']['id'],
               'briefRevision': state['brief']['revision'], 'openings': [options['title']] * 3, 'selectedOpening': 0,
               'customized': True, 'runId': 'youtube-library-plan:' + identifier,
               'origin': 'user_or_filename_suggestion', 'revisions': [{'revision': 1, 'text': text, 'at': now, 'origin': 'youtube_library_plan'}]}
    state.setdefault('variants', []).append(variant)
    draft = {'id': identifier, 'connectionId': connection, 'channelId': channel['providerAccountId'],
             'assetId': asset['id'], 'assetHash': asset['hash'], 'variantId': variant_id, 'variantRevision': 1,
             'publishOptions': options, 'timing': timing, 'uploadWorkflow': workflow, 'uploadAt': upload_at,
             'rightsConfirmed': True, 'createdBy': actor, 'createdAt': now, 'status': 'proposed',
             'goal': str(body.get('goal') or '')[:1000], 'recommendations': [
                 'Review the title and description against the actual video before approval.',
                 'Allow extra upload and processing time; the selected time is your choice, not an audience-performance prediction.'
             ], 'execution': 'local_planning_only', 'metadataOrigin': 'user_or_filename_suggestion'}
    draft['digest'] = draft_digest(draft)
    root(state)['drafts'].append(draft)
    return draft


def review_payload(draft):
    timing = draft['timing']
    return {'variantId': draft['variantId'], 'channelId': draft['connectionId'], 'assetId': draft['assetId'],
            'rightsConfirmed': draft['rightsConfirmed'], 'acknowledgedWarnings': [],
            'localTime': timing['local'], 'timeZone': timing['timeZone'], 'fold': timing['fold'],
            'publishOptions': copy.deepcopy(draft['publishOptions'])}


def assert_draft_current(state, draft, now):
    if draft.get('privacyErased'):
        raise AlphaError('This plan contains erased YouTube API identity data. Prepare and approve a new plan.', 409, code='youtube_privacy_erased')
    if draft.get('digest') != draft_digest(draft):
        raise AlphaError('The publishing plan changed. Prepare a new plan.', 409)
    channel, asset = _channel(state, draft['connectionId']), _asset(state, draft['assetId'])
    variant = next((v for v in state.get('variants', []) if v.get('id') == draft['variantId']), None)
    if (channel['providerAccountId'] != draft['channelId'] or asset.get('hash') != draft['assetHash'] or not variant
            or variant.get('revision') != draft['variantRevision']
            or variant.get('text') != (draft['publishOptions'].get('description') or draft['publishOptions']['title'])
            or variant.get('unknowns') or variant.get('warnings') or variant.get('proposedUpdate')):
        raise AlphaError('The channel, Library video or metadata changed. Prepare a new plan.', 409)
    if draft['timing']['timestamp'] <= now:
        raise AlphaError('The planned publication time expired. Reschedule explicitly; nothing was published.', 409,
                         code='youtube_invalid_scheduling_state')
    return variant


def prepare_policy(state, connection, body, actor, now):
    channel = _channel(state, connection)
    identifiers = body.get('draftIds')
    if (not isinstance(identifiers, list) or not 1 <= len(identifiers) <= MAX_PLANS
            or any(not isinstance(identifier, str) for identifier in identifiers) or len(set(identifiers)) != len(identifiers)):
        raise AlphaError('Select between one and 100 exact publishing plans.', 400)
    drafts = [find_draft(state, connection, identifier) for identifier in identifiers]
    for draft in drafts:
        if draft.get('status') != 'proposed':
            raise AlphaError('Standing authority can cover only unqueued plans.', 409)
        assert_draft_current(state, draft, now)
    zone_name = body.get('timeZone')
    try:
        ZoneInfo(zone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise AlphaError('Use a valid IANA time zone for the daily limit.', 400) from None
    daily = body.get('maxDaily')
    if type(daily) is not int or not 1 <= daily <= 20:
        raise AlphaError('Choose an explicit daily publication limit from one to 20.', 400)
    end = body.get('endsAt')
    if type(end) not in (int, float) or not now < end <= now + MAX_POLICY_DAYS * 86400:
        raise AlphaError('Standing authority must expire within 30 days.', 400)
    if any(d['timing']['timestamp'] > end for d in drafts):
        raise AlphaError('Each planned publication must be inside the authority period.', 400)
    days = {}
    for draft in drafts:
        day = datetime.fromtimestamp(draft['timing']['timestamp'], timezone.utc).astimezone(ZoneInfo(zone_name)).date().isoformat()
        days[day] = days.get(day, 0) + 1
    if any(count > daily for count in days.values()):
        raise AlphaError('The selected plans exceed the daily publication limit.', 409)
    policy = {'id': uuid.uuid4().hex, 'connectionId': connection, 'channelId': channel['providerAccountId'],
              'drafts': [{'id': d['id'], 'digest': d['digest']} for d in drafts],
              'assetIds': sorted({d['assetId'] for d in drafts}), 'timeZone': zone_name, 'startsAt': now,
              'endsAt': end, 'maxDaily': daily, 'status': 'prepared', 'preparedBy': actor, 'createdAt': now,
              'mode': 'authorized_autopilot', 'allowedOperations': ['upload', 'metadata', 'schedule'],
              'contentScope': 'exact_reviewed_library_plans', 'providerExecution': 'not_started'}
    policy['digest'] = policy_digest(policy)
    policies = root(state)['policies']
    if sum(1 for item in policies if item.get('status') in ('prepared', 'active', 'paused')
           and item.get('endsAt', 0) > now) >= MAX_PLANS:
        raise AlphaError('This workspace has reached its 100 unexpired YouTube policy limit.', 409)
    policies.append(policy)
    return policy


def activate_policy(state, connection, identifier, body, actor, now):
    policy = next((p for p in root(state)['policies'] if p.get('id') == identifier and p.get('connectionId') == connection), None)
    if not policy:
        raise AlphaError('YouTube policy unavailable.', 404)
    if policy.get('privacyErased'):
        raise AlphaError('This policy contains erased YouTube API identity data. Prepare a new policy.', 409, code='youtube_privacy_erased')
    if (body.get('confirmed') is not True or body.get('digest') != policy.get('digest')
            or policy.get('digest') != policy_digest(policy) or body.get('confirmationChannelId') != policy['channelId']):
        raise AlphaError('Confirm the exact channel, plans, source videos, times and limits.', 400)
    if policy.get('status') not in ('prepared', 'paused') or policy['endsAt'] <= now:
        raise AlphaError('Prepare a new policy after revocation or expiry.', 409)
    # Editing drafts never inherits an earlier authorization.
    for entry in policy['drafts']:
        draft = find_draft(state, connection, entry['id'])
        if draft['digest'] != entry['digest']:
            raise AlphaError('A selected plan changed. Prepare a new policy.', 409)
        if draft.get('status') == 'proposed':
            assert_draft_current(state, draft, now)
    for existing in root(state)['policies']:
        if existing.get('connectionId') == connection and existing.get('status') == 'active' and existing['id'] != policy['id']:
            existing.update(status='revoked', revokedAt=now, revokedBy=actor)
    policy.update(status='active', grantedBy=actor, grantedAt=now, authorizationGeneration=uuid.uuid4().hex)
    return policy


def change_policy(state, connection, identifier, action, actor, now):
    policy = next((p for p in root(state)['policies'] if p.get('id') == identifier and p.get('connectionId') == connection), None)
    if not policy or action not in ('pause', 'revoke'):
        raise AlphaError('YouTube policy unavailable.', 404)
    if policy.get('status') == 'revoked':
        return policy
    policy.update(status='paused' if action == 'pause' else 'revoked', updatedAt=now, updatedBy=actor)
    return policy


def assert_policy(state, policy, draft, now):
    if policy.get('privacyErased') or draft.get('privacyErased'):
        raise AlphaError('Erased YouTube approvals cannot authorize publication.', 409, code='youtube_privacy_erased')
    if (policy.get('status') != 'active' or policy.get('digest') != policy_digest(policy)
            or not policy['startsAt'] <= now < policy['endsAt'] or not policy.get('grantedBy')
            or policy.get('channelId') != draft.get('channelId') or policy.get('connectionId') != draft.get('connectionId')
            or draft.get('assetId') not in policy.get('assetIds', [])
            or not any(e.get('id') == draft['id'] and e.get('digest') == draft.get('digest') for e in policy.get('drafts', []))):
        raise AlphaError('Autopilot authority is paused, revoked, expired or outside this exact plan.', 409,
                         code='youtube_agent_authority_required')
    planned = draft['timing']['timestamp']
    if not policy['startsAt'] <= planned <= policy['endsAt']:
        raise AlphaError('This publication is outside the authorized date range.', 409)
    day = datetime.fromtimestamp(planned, timezone.utc).astimezone(ZoneInfo(policy['timeZone'])).date()
    used = sum(1 for d in root(state)['drafts'] if d.get('status') == 'queued' and d.get('policyId') == policy['id']
               and d['id'] != draft['id'] and datetime.fromtimestamp(d['timing']['timestamp'], timezone.utc).astimezone(ZoneInfo(policy['timeZone'])).date() == day)
    if used >= policy['maxDaily']:
        raise AlphaError('Autopilot daily publication limit reached.', 409, code='youtube_agent_daily_limit')


def assert_job_authority(state, job, now):
    """Claim/forward guard. Pausing stops further API writes; accepted schedules need separate cancellation."""
    authority = job.get('youtubeAgent')
    if not authority:
        return
    policy = next((p for p in root(state)['policies'] if p.get('id') == authority.get('policyId')), None)
    draft = find_draft(state, job['manifest']['channelId'], authority.get('draftId'))
    if not policy or policy.get('grantedBy') != job.get('approvedBy') or policy.get('digest') != authority.get('policyDigest'):
        raise AlphaError('Autopilot owner authority changed.', 409, code='youtube_agent_authority_required')
    assert_policy(state, policy, draft, now)


def queue_draft(commands, state, connection, identifier, actor, now, *, policy=None):
    draft = find_draft(state, connection, identifier)
    if draft.get('privacyErased'):
        raise AlphaError('This plan contains erased YouTube API identity data. Prepare and approve a new plan.', 409, code='youtube_privacy_erased')
    if draft.get('jobId'):
        return draft  # Immutable job ID fences repeated manual/worker dispatch.
    variant = assert_draft_current(state, draft, now)
    if policy:
        assert_policy(state, policy, draft, now)
        if actor != policy['grantedBy']:
            raise AlphaError('Only the standing-authority owner may dispatch this policy.', 403)
    commands(state, actor, 'p2_variant_review', {'variantId': variant['id'], 'variantRevision': variant['revision'],
             'confirmed': True, 'excludedUnknowns': []})
    commands(state, actor, 'p2_review', review_payload(draft))
    review = state['phase2']['reviews'][-1]
    commands(state, actor, 'p2_approve', {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
    job = next(j for j in state['phase2']['jobs'] if j['id'] == review['jobId'])
    job['nextAt'] = max(now, draft['uploadAt']) if draft['uploadWorkflow'] == 'upload_later' else now
    if policy:
        job['youtubeAgent'] = {'policyId': policy['id'], 'policyDigest': policy['digest'], 'draftId': draft['id']}
        draft['policyId'] = policy['id']
    draft.update(status='queued', jobId=job['id'], approvedBy=actor, approvedAt=now,
                 approvalMode='authorized_autopilot' if policy else 'manual_approval')
    return draft


class YouTubePublishingAgent:
    def __init__(self, creator):
        self.creator, self.service = creator, creator.service
        self.repository, self.clock = creator.repository, creator.clock

    def _member(self, workspace, token, connection, right='read', fresh=False, *, policy_required=True):
        return self.creator._member(workspace, token, connection, right, fresh=fresh, policy_required=policy_required)

    def overview(self, workspace, token, connection):
        # Local standing-authority controls stay visible for pause/revoke even
        # when a legal revision blocks new Creator/provider execution.
        _, channel, state = self._member(workspace, token, connection, policy_required=False)
        view = copy.deepcopy(root(state))
        view['drafts'] = [d for d in view['drafts'] if d.get('connectionId') == connection]
        view['policies'] = [p for p in view['policies'] if p.get('connectionId') == connection]
        view['channelId'] = channel
        view['planningMode'] = 'local_rules_no_model_calls'
        view['executionState'] = 'IMPLEMENTED BUT UNVERIFIED'
        try:
            provider = self.creator.oauth.provider_for_connection(workspace, connection)
        except AlphaError:
            provider = None
        policy_ready = True
        try:
            with self.repository.transaction(token, workspace) as (cur, _, actor):
                self.creator.oauth.youtube_policy.require_user(cur, workspace, actor, token, provider, force=True)
        except AlphaError as error:
            if error.code not in ('youtube_policy_not_ready', 'youtube_policy_acceptance_required', 'youtube_policy_interactive_required'):
                raise
            policy_ready = False
        view['autopilotGate'] = {'canActivate': bool(policy_ready and getattr(provider, 'authorization_lane', None) == 'agentic'
            and getattr(provider, 'creator_enabled', False) and getattr(provider, 'execution_enabled', True) and project_public_gate(provider)),
            'reason': 'A separate, actually routed agentic OAuth client and verified Google/YouTube approvals are required.'}
        view['pauseNotice'] = 'Pause stops new uploads and API writes. A video already scheduled on YouTube must be cancelled separately in Creator.'
        return view

    def _write(self, workspace, token, connection, body, operation, *, right='edit', fresh=False, billing=False, policy_required=True):
        from ..billing import require_publishing
        from ..source_policy import stamp
        revision = body.get('revision')
        self._member(workspace, token, connection, right, fresh=fresh, policy_required=policy_required)
        output = {}
        def apply(state, actor):
            output.update(operation(state, actor))
            stamp(state)
            self.service.commands.engine.invalidate(state)
            return state
        saved = self.repository.command(workspace, token, revision, apply, requirement=right, step_up=fresh,
            audit_event=lambda state: ('youtube.agent_' + body.get('_event', 'changed'), connection,
                {'draftId': output.get('id') if 'assetId' in output else None, 'policyId': output.get('id') if 'drafts' in output else None,
                 'status': output.get('status'), 'connectionId': connection}),
            after=(lambda cur, state, actor: require_publishing(cur, workspace, self.clock())) if billing else None)
        return {'revision': saved['revision'], 'result': output, 'queued': output.get('status') == 'queued',
                'executed': False, 'providerVerified': False}

    def prepare(self, workspace, token, connection, body):
        return self._write(workspace, token, connection, {**body, '_event': 'draft_prepared'},
            lambda state, actor: prepare_draft(state, connection, body, actor, self.clock()))

    def approve(self, workspace, token, connection, identifier, body):
        if body.get('confirmed') is not True:
            raise AlphaError('Review and approve this exact publication plan.', 400)
        _, _, state = self._member(workspace, token, connection, 'approve')
        draft = find_draft(state, connection, identifier)
        if body.get('digest') != draft.get('digest'):
            raise AlphaError('The exact publishing plan changed. Reload it.', 409)
        self.creator.oauth.refresh_for_composer(workspace, token, body.get('revision'), 'p2_review', review_payload(draft))
        return self._write(workspace, token, connection, {**body, '_event': 'draft_approved'},
            lambda state, actor: queue_draft(self.service.commands, state, connection, identifier, actor, self.clock()), right='approve', billing=True)

    def policy_preview(self, workspace, token, connection, body):
        return self._write(workspace, token, connection, {**body, '_event': 'policy_prepared'},
            lambda state, actor: prepare_policy(state, connection, body, actor, self.clock()), right='owner')

    def _agentic_gate(self, workspace, connection):
        # Selecting a human OAuth client for agentic API calls is prohibited. No fallback.
        provider = self.creator.oauth.provider_for_connection(workspace, connection)
        if getattr(provider, 'authorization_lane', None) != 'agentic':
            raise AlphaError('Connect this channel through the separate agentic Google OAuth client before enabling autopilot.', 409,
                             code='youtube_agentic_oauth_required')
        if not getattr(provider, 'creator_enabled', False) or not getattr(provider, 'execution_enabled', True):
            raise AlphaError('Agentic creator execution is disabled in this deployment.', 409,
                             code='youtube_agentic_execution_disabled')
        if not project_public_gate(provider):
            raise AlphaError('Autopilot is held until the actual OAuth client has verified Google and YouTube public approvals.', 409,
                             code='youtube_project_restriction')
        grant = self.creator.oauth.token_for_worker(workspace, connection)
        try:
            binding = json.loads(grant.get('accessToken', ''))
        except (ValueError, TypeError):
            binding = {}
        if (grant.get('authorizationLane') != 'agentic' or binding.get('v') != 2 or binding.get('clientId') != provider.client_id
                or binding.get('authorizationLane') != 'agentic' or grant.get('refreshBindingRequired') is True):
            raise AlphaError('This connection has no exact agentic OAuth client binding. Reconnect explicitly.', 409,
                             code='youtube_agentic_oauth_required')
        if not has_scopes(grant.get('scopes'), (READ, UPLOAD, MANAGE)):
            raise AlphaError('Grant the actual agentic channel read, upload and scheduling scopes before enabling autopilot.', 409,
                             code='youtube_agentic_scope_required')
        return grant

    def policy_action(self, workspace, token, connection, identifier, action, body):
        if action == 'activate':
            self._member(workspace, token, connection, 'owner', fresh=True)
            self._agentic_gate(workspace, connection)
            return self._write(workspace, token, connection, {**body, '_event': 'policy_activated'},
                lambda state, actor: activate_policy(state, connection, identifier, body, actor, self.clock()), right='owner', fresh=True)
        if action not in ('pause', 'revoke'):
            raise AlphaError('YouTube policy action unavailable.', 404)
        return self._write(workspace, token, connection, {**body, '_event': 'policy_' + action},
            lambda state, actor: change_policy(state, connection, identifier, action, actor, self.clock()),
            right='owner', policy_required=False)

    def _select_candidate(self, *, fleet=False, exclude_workspaces=()):
        """Fleet selection commits a 120-second fenced lease before OAuth I/O."""
        candidate = None
        filters = ''
        extra = ()
        if fleet:
            filters = " AND NOT (id=ANY(%s::uuid[])) AND coalesce((state#>>'{youtubeAgent,fleetLease,until}')::float8,0)<=%s"
            extra = (list(exclude_workspaces), self.clock())
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT id::text,state FROM public.pr_workspaces WHERE state ? 'youtubeAgent'
                AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
                AND EXISTS(SELECT 1 FROM jsonb_array_elements(state#>'{youtubeAgent,policies}') p,
                    jsonb_array_elements(state#>'{youtubeAgent,drafts}') d
                    WHERE p->>'status'='active' AND (p->>'startsAt')::float8<=%s AND (p->>'endsAt')::float8>%s
                      AND d->>'status'='proposed' AND d->>'connectionId'=p->>'connectionId'
                      AND (d->>'uploadWorkflow'<>'upload_later' OR (d->>'uploadAt')::float8<=%s)
                      AND EXISTS(SELECT 1 FROM jsonb_array_elements(p->'drafts') e WHERE e->>'id'=d->>'id'))
                """ + filters + """ ORDER BY coalesce((state#>>'{youtubeAgent,lastDispatchAt}')::float8,0),id LIMIT 100""" +
                (' FOR UPDATE SKIP LOCKED' if fleet else ''),
                (self.clock(), self.clock(), self.clock() + 1800) + extra)
            for workspace, raw in cur.fetchall():
                state = json.loads(raw) if isinstance(raw, str) else raw
                for policy in root(state)['policies']:
                    if policy.get('status') != 'active' or not policy['startsAt'] <= self.clock() < policy['endsAt']:
                        continue
                    for entry in policy['drafts']:
                        try:
                            draft = find_draft(state, policy['connectionId'], entry['id'])
                        except AlphaError:
                            continue
                        if draft.get('status') == 'proposed' and (draft['uploadWorkflow'] != 'upload_later' or draft['uploadAt'] <= self.clock() + 1800):
                            candidate = (workspace, policy['connectionId'], policy['id'], draft['id'])
                            break
                    if candidate: break
                if candidate:
                    authorization = policy_authorization(policy)
                    lease_id = None
                    if fleet:
                        lease_id = uuid.uuid4().hex
                        root(state)['fleetLease'] = {'id': lease_id, 'until': self.clock() + 120,
                                                    'authorization': authorization}
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                                    (json.dumps(state), workspace))
                    candidate = (*candidate, lease_id, authorization)
                    break
        return candidate

    def dispatch_one(self, *, fleet=False, exclude_workspaces=()):
        """At most one finite plan; fleet mode adds a durable workspace claim."""
        candidate = self._select_candidate(fleet=fleet, exclude_workspaces=exclude_workspaces)
        if not candidate:
            return {'dispatched': False, 'providerVerified': False}
        if not fleet:
            return self._dispatch_candidate(candidate)
        from .fleet import release_planner
        try:
            return {**self._dispatch_candidate(candidate), '_workspace': candidate[0]}
        finally:
            release_planner(self, candidate)

    def _dispatch_candidate(self, candidate):
        from ..hosted import audit
        from ..billing import require_publishing
        if not candidate:
            return {'dispatched': False, 'providerVerified': False}
        if len(candidate) != 6:
            return {'dispatched': False, 'authorityChanged': True, 'providerVerified': False}
        workspace, connection, policy_id, draft_id = candidate[:4]
        leased = candidate[4] is not None
        try:
            self._agentic_gate(workspace, connection)
            verification = self.creator.oauth.reverify_for_worker(workspace, connection)
            if verification.get('state') == 'verification_unavailable':
                return {'dispatched': False, 'deferred': True, 'providerVerified': False}
            if leased and (verification.get('state') != 'read_verified' or verification.get('ready') is not True):
                raise AlphaError('Reconnect the exact agentic channel before dispatch.', 409, code='youtube_agentic_oauth_required')
            with self.service.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
                row = cur.fetchone()
                if not row:
                    return {'dispatched': False, 'providerVerified': False}
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                if leased:
                    lease = root(state).get('fleetLease', {})
                    if lease.get('id') != candidate[4] or lease.get('until', 0) <= self.clock():
                        return {'dispatched': False, 'leaseLost': True, 'providerVerified': False}
                if not fleet_authorization_current(state, candidate):
                    return {'dispatched': False, 'authorityChanged': True, 'providerVerified': False}
                if state.get('accountBlock') or state.get('accountDeletion'):
                    raise AlphaError('Workspace unavailable.', 403)
                policy = next((p for p in root(state)['policies'] if p.get('id') == policy_id), None)
                if policy is None:
                    raise AlphaError('The finite publishing policy is unavailable.', 409, code='youtube_agent_policy_changed')
                cur.execute("""SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                    WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p""",
                    (workspace, policy.get('grantedBy')))
                member = cur.fetchone()
                if not member or member[0] != 'owner':
                    raise AlphaError('The autopilot owner no longer has workspace authority.', 403)
                require_publishing(cur, workspace, self.clock())
                result = queue_draft(self.service.commands, state, connection, draft_id, policy['grantedBy'], self.clock(), policy=policy)
                policy.pop('intervention', None)
                root(state)['lastDispatchAt'] = self.clock()
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                            (json.dumps(state), workspace, row[0]))
                audit(cur, workspace, policy['grantedBy'], 'youtube.agent_dispatched', result['jobId'],
                      {'policyId': policy_id, 'draftId': draft_id, 'connectionId': connection})
            return {'dispatched': True, 'jobId': result['jobId'], 'providerVerified': False}
        except AlphaError as error:
            if getattr(error, 'capacity_reason', None) == 'fleet_budget':
                return {'dispatched': False, 'deferred': True, 'providerVerified': False}
            # One durable actionable intervention, no automatic duplicate provider submission.
            with self.service.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
                row = cur.fetchone()
                if row:
                    state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    if leased:
                        lease = root(state).get('fleetLease', {})
                        if lease.get('id') != candidate[4] or lease.get('until', 0) <= self.clock():
                            return {'dispatched': False, 'leaseLost': True, 'providerVerified': False}
                    if not fleet_authorization_current(state, candidate):
                        return {'dispatched': False, 'authorityChanged': True, 'providerVerified': False}
                    policy = next((p for p in root(state)['policies'] if p.get('id') == policy_id), None)
                    if policy and policy.get('status') == 'active':
                        policy.update(status='paused', intervention={'code': error.code or 'youtube_agent_held', 'message': str(error), 'at': self.clock()})
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
                        audit(cur, workspace, policy.get('grantedBy'), 'youtube.agent_intervention_required', policy_id,
                              {'code': error.code or 'youtube_agent_held', 'draftId': draft_id})
            return {'dispatched': False, 'interventionRequired': True, 'code': error.code, 'providerVerified': False}
