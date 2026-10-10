"""Synthetic bounded publishing-agent regressions. No real Google acceptance."""
import copy
import json
import math
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.youtube.agent import (
    YouTubePublishingAgent, activate_policy, assert_job_authority, change_policy, draft_digest,
    find_draft, prepare_draft, prepare_policy, queue_draft, root,
)
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE
from postriff_phase2.youtube.service import YouTubeCreatorService
from postriff_phase2.api_tokens import route_scope

NOW = 1_800_000_000
CHANNEL = 'UC' + 'a' * 22
CONNECTION = 'youtube-one'
ASSET = 'a' * 32


def local(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M')


def state():
    value = initial_phase2_state('workspace-one', 'owner', 'Owner', 'studio', NOW, execution='hosted-candidate')
    value['speaker']['activeRevision'] = 1
    value['phase2']['channels'] = [{'id': CONNECTION, 'platform': 'YouTube', 'account': 'Channel A', 'providerAccountId': CHANNEL,
        'configured': True, 'identityVerified': True, 'capabilityVerified': True, 'revoked': False,
        'expiresAt': NOW + 7200, 'verifiedAt': NOW, 'capabilityVersion': 1, 'evidenceSource': 'synthetic',
        'scopes': [READ, UPLOAD, MANAGE]}]
    value['phase2']['assets'] = [{'id': ASSET, 'hash': 'f' * 64, 'mime': 'video/mp4', 'processing': 'ready',
        'originalFilename': 'A_real_video.mp4', 'width': 1080, 'height': 1920, 'bytes': 1000, 'duration': 60,
        'durationSource': 'container', 'bucket': 'media', 'objectName': ASSET + '.mp4', 'etag': 'immutable',
        'verified': {'container': True, 'locationChecked': True}, 'deleted': False}]
    return value


def body(at=NOW + 7200, **updates):
    return {'assetId': ASSET, 'rightsConfirmed': True, 'localTime': local(at), 'timeZone': 'UTC', 'fold': 0,
        'publishOptions': {'title': 'Approved title', 'description': 'Approved description', 'privacyStatus': 'private',
                           'madeForKids': False, 'containsSyntheticMedia': False}, **updates}


def draft_and_policy(value):
    draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
    policy = prepare_policy(value, CONNECTION, {'draftIds': [draft['id']], 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}, 'owner', NOW)
    activate_policy(value, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'], 'confirmationChannelId': CHANNEL}, 'owner', NOW)
    return draft, policy


class LibraryPlanTests(unittest.TestCase):
    def test_manual_approval_queues_normal_manifest_and_duplicate_is_reused(self):
        value = state()
        draft = prepare_draft(value, CONNECTION, body(), 'editor', NOW)
        commands = HostedPhase2Commands(clock=lambda: NOW)
        result = queue_draft(commands, value, CONNECTION, draft['id'], 'owner', NOW)
        job = value['phase2']['jobs'][0]
        self.assertEqual(result['jobId'], job['id'])
        self.assertEqual(job['manifest']['media'][0]['id'], ASSET)
        self.assertEqual(job['manifest']['providerAccountId'], CHANNEL)
        self.assertEqual(job['manifest']['actor'], 'owner')
        self.assertEqual(job['nextAt'], NOW)
        self.assertNotIn('youtubeAgent', job)
        queue_draft(commands, value, CONNECTION, draft['id'], 'owner', NOW)
        self.assertEqual(len(value['phase2']['jobs']), 1)
        self.assertEqual(len(value['phase2']['reviews']), 1)

    def test_queue_upload_later_has_separate_time_from_publication(self):
        value = state()
        options = body()['publishOptions'] | {'privacyStatus': 'public'}
        draft = prepare_draft(value, CONNECTION, body(uploadWorkflow='upload_later', uploadLocalTime=local(NOW + 3600), uploadFold=0,
                              publishOptions=options), 'owner', NOW)
        queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'owner', NOW)
        job = value['phase2']['jobs'][0]
        self.assertLess(job['nextAt'], job['manifest']['timing']['timestamp'])
        self.assertEqual(job['nextAt'], draft['uploadAt'])
        self.assertIn('publishAt', job['manifest']['publishOptions'])
        self.assertEqual(job['manifest']['publishOptions']['privacyStatus'], 'public')

    def test_publication_in_past_never_becomes_immediate(self):
        value = state()
        draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        with self.assertRaisesRegex(AlphaError, 'expired'):
            queue_draft(HostedPhase2Commands(clock=lambda: NOW + 9000), value, CONNECTION, draft['id'], 'owner', NOW + 9000)
        self.assertEqual(value['phase2']['jobs'], [])

    def test_nonexistent_dst_time_rejected_and_ambiguous_time_requires_choice(self):
        for local_time in ('2027-03-14T02:30', '2027-11-07T01:30'):
            with self.subTest(time=local_time), self.assertRaises(AlphaError):
                prepare_draft(state(), CONNECTION, body(localTime=local_time, timeZone='America/New_York', fold=None), 'owner', NOW)

    def test_media_rights_and_audience_are_not_inferred(self):
        with self.assertRaises(AlphaError):
            prepare_draft(state(), CONNECTION, body(rightsConfirmed=False), 'owner', NOW)
        options = body()['publishOptions']; options.pop('madeForKids')
        with self.assertRaises(AlphaError):
            prepare_draft(state(), CONNECTION, body(publishOptions=options), 'owner', NOW)

    def test_foreign_asset_and_connection_are_unavailable(self):
        with self.assertRaises(AlphaError):
            prepare_draft(state(), 'foreign-connection', body(), 'owner', NOW)
        with self.assertRaises(AlphaError):
            prepare_draft(state(), CONNECTION, body(assetId='foreign-asset'), 'owner', NOW)

    def test_metadata_or_media_change_voids_plan(self):
        for change in ('metadata', 'asset'):
            value = state(); draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
            if change == 'metadata':
                value['variants'][0]['text'] = 'Changed after review'
            else:
                value['phase2']['assets'][0]['hash'] = 'e' * 64
            with self.subTest(change=change), self.assertRaises(AlphaError):
                queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'owner', NOW)
            self.assertEqual(value['phase2']['jobs'], [])

    def test_too_late_queued_upload_does_not_silently_use_publication_time(self):
        with self.assertRaisesRegex(AlphaError, 'ten minutes'):
            prepare_draft(state(), CONNECTION, body(uploadWorkflow='upload_later', uploadLocalTime=local(NOW + 7200)), 'owner', NOW)

    def test_future_unlisted_plan_cannot_expose_video_before_planned_time(self):
        with self.assertRaisesRegex(AlphaError, 'Unlisted timing'):
            prepare_draft(state(), CONNECTION, body(publishOptions=body()['publishOptions'] | {'privacyStatus': 'unlisted'}), 'owner', NOW)

    def test_pending_plan_limit_does_not_become_a_lifetime_creator_limit(self):
        value = state()
        history = [{'id': 'queued-' + str(i), 'status': 'queued', 'jobId': 'receipt-' + str(i)} for i in range(100)]
        expired = [{'id': 'expired-' + str(i), 'status': 'proposed', 'timing': {'timestamp': NOW - 1}} for i in range(100)]
        root(value)['drafts'] = copy.deepcopy(history + expired)
        prepared = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        self.assertEqual(root(value)['drafts'][:200], history + expired, 'Completed receipts and expired plans remain intact.')
        self.assertEqual(prepared['status'], 'proposed')
        root(value)['drafts'].extend([{'id': 'future-' + str(i), 'status': 'proposed', 'timing': {'timestamp': NOW + 10000}} for i in range(99)])
        with self.assertRaisesRegex(AlphaError, 'pending future'):
            prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        self.assertEqual(len(root(value)['drafts']), 300)


class BoundedPolicyTests(unittest.TestCase):
    def test_unexpired_policy_limit_preserves_history_without_lifetime_cap(self):
        value = state()
        draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        history = [{'id': 'revoked-' + str(i), 'status': 'revoked', 'endsAt': NOW + 86400} for i in range(100)]
        expired = [{'id': 'expired-' + str(i), 'status': 'active', 'endsAt': NOW - 1} for i in range(100)]
        root(value)['policies'] = copy.deepcopy(history + expired)
        options = {'draftIds': [draft['id']], 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}
        prepared = prepare_policy(value, CONNECTION, options, 'owner', NOW)
        self.assertEqual(root(value)['policies'][:200], history + expired, 'Revoked and expired authority remains auditable.')
        self.assertEqual(prepared['status'], 'prepared')
        root(value)['policies'].extend([{'id': 'pending-' + str(i), 'status': 'paused', 'endsAt': NOW + 86400} for i in range(99)])
        with self.assertRaisesRegex(AlphaError, 'unexpired'):
            prepare_policy(value, CONNECTION, options, 'owner', NOW)
        self.assertEqual(len(root(value)['policies']), 300)

    def test_server_policy_route_requires_owner_even_if_editor_can_publish(self):
        @contextmanager
        def transaction(*_):
            yield SimpleNamespace(), (1, state(), 'editor', True, False, False, True), 'editor'
        repository = SimpleNamespace(transaction=transaction, command=Mock())
        creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
        creator.service = SimpleNamespace(); creator.repository = repository; creator.clock = lambda: NOW
        with self.assertRaises(AlphaError) as caught:
            YouTubePublishingAgent(creator).policy_preview('workspace-one', 'session', CONNECTION, {'revision': 1})
        self.assertEqual(caught.exception.status, 403)
        repository.command.assert_not_called()

    def test_activation_requires_fresh_interactive_owner_signin(self):
        @contextmanager
        def transaction(*_):
            yield SimpleNamespace(), (1, state(), 'owner', True, False, False, True), 'owner'
        repository = SimpleNamespace(transaction=transaction, command=Mock(),
            assert_fresh=Mock(side_effect=AlphaError('Sign in again.', 403, code='step_up_required')))
        creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
        creator.service = SimpleNamespace(); creator.repository = repository; creator.clock = lambda: NOW
        agent = YouTubePublishingAgent(creator); agent._agentic_gate = Mock()
        with self.assertRaises(AlphaError) as caught:
            agent.policy_action('workspace-one', 'session', CONNECTION, 'policy', 'activate', {'revision': 1})
        self.assertEqual(caught.exception.code, 'step_up_required')
        agent._agentic_gate.assert_not_called()

    def test_api_token_scope_does_not_authorize_agent_routes(self):
        for method, suffix in (('GET', []), ('POST', ['drafts']), ('POST', ['policies', 'preview'])):
            self.assertIsNone(route_scope(method, ['api', 'workspaces', 'workspace-one', 'youtube', CONNECTION, 'agent', *suffix]))

    def test_pause_and_revoke_stop_claim_authority(self):
        for action in ('pause', 'revoke'):
            value = state(); draft, policy = draft_and_policy(value)
            queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'owner', NOW, policy=policy)
            job = value['phase2']['jobs'][0]
            assert_job_authority(value, job, NOW)
            change_policy(value, CONNECTION, policy['id'], action, 'owner', NOW + 1)
            with self.subTest(action=action), self.assertRaises(AlphaError):
                assert_job_authority(value, job, NOW + 1)
            self.assertEqual(job['state'], 'scheduled')  # No invented provider cancellation.

    def test_exact_channel_confirmation_and_digest_required(self):
        value = state(); draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        policy = prepare_policy(value, CONNECTION, {'draftIds': [draft['id']], 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}, 'owner', NOW)
        with self.assertRaises(AlphaError):
            activate_policy(value, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'], 'confirmationChannelId': 'UC' + 'b' * 22}, 'owner', NOW)

    def test_daily_limit_applies_to_planned_publication_day(self):
        value = state(); one = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        two = prepare_draft(value, CONNECTION, body(at=NOW + 7300), 'owner', NOW)
        with self.assertRaisesRegex(AlphaError, 'daily'):
            prepare_policy(value, CONNECTION, {'draftIds': [one['id'], two['id']], 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}, 'owner', NOW)

    def test_expired_revoked_and_tampered_policies_cannot_resume(self):
        value = state(); draft, policy = draft_and_policy(value)
        change_policy(value, CONNECTION, policy['id'], 'revoke', 'owner', NOW)
        with self.assertRaises(AlphaError):
            activate_policy(value, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'], 'confirmationChannelId': CHANNEL}, 'owner', NOW)
        policy['status'] = 'paused'; policy['maxDaily'] = 20
        with self.assertRaises(AlphaError):
            activate_policy(value, CONNECTION, policy['id'], {'confirmed': True, 'digest': policy['digest'], 'confirmationChannelId': CHANNEL}, 'owner', NOW)

    def test_plan_scope_does_not_authorize_other_library_video(self):
        value = state(); draft, policy = draft_and_policy(value)
        policy['assetIds'] = []
        with self.assertRaises(AlphaError):
            queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'owner', NOW, policy=policy)

    def test_policy_cannot_outlive_30_days_or_include_unbounded_sources(self):
        value = state(); draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        for ids, expiry in ((['*'], NOW + 86400), ([draft['id']], NOW + 31 * 86400)):
            with self.subTest(ids=ids), self.assertRaises(AlphaError):
                prepare_policy(value, CONNECTION, {'draftIds': ids, 'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': expiry}, 'owner', NOW)

    def test_dispatch_actor_must_match_standing_authority_owner(self):
        value = state(); draft, policy = draft_and_policy(value)
        with self.assertRaises(AlphaError):
            queue_draft(HostedPhase2Commands(clock=lambda: NOW), value, CONNECTION, draft['id'], 'other-owner', NOW, policy=policy)

    def test_standard_oauth_never_reused_for_agentic_provider_calls(self):
        oauth = SimpleNamespace(provider_for_connection=Mock(return_value=SimpleNamespace(authorization_lane='standard')), token_for_worker=Mock())
        creator = SimpleNamespace(service=SimpleNamespace(), repository=SimpleNamespace(), clock=lambda: NOW, oauth=oauth)
        agent = YouTubePublishingAgent(creator)
        with self.assertRaises(AlphaError) as caught:
            agent._agentic_gate('workspace-one', CONNECTION)
        self.assertEqual(caught.exception.code, 'youtube_agentic_oauth_required')
        oauth.token_for_worker.assert_not_called()

    def test_legal_agentic_route_requires_exact_protected_client_binding(self):
        provider = SimpleNamespace(authorization_lane='agentic', client_id='agentic-client', creator_enabled=True, execution_enabled=True)
        oauth = SimpleNamespace(provider_for_connection=lambda *_: provider, token_for_worker=lambda *_: {
            'accessToken': json.dumps({'v': 2, 'clientId': 'other-client', 'authorizationLane': 'agentic'}),
            'authorizationLane': 'agentic'})
        creator = SimpleNamespace(service=SimpleNamespace(), repository=SimpleNamespace(), clock=lambda: NOW, oauth=oauth)
        with patch('postriff_phase2.youtube.agent.project_public_gate', return_value=True), self.assertRaises(AlphaError):
            YouTubePublishingAgent(creator)._agentic_gate('workspace-one', CONNECTION)

    def test_agentic_activation_requires_actual_scopes_and_deployment_enablement(self):
        provider = SimpleNamespace(authorization_lane='agentic', client_id='agentic-client', creator_enabled=True, execution_enabled=True)
        grant = {'accessToken': json.dumps({'v': 2, 'clientId': provider.client_id, 'authorizationLane': 'agentic'}),
                 'authorizationLane': 'agentic', 'scopes': [READ]}
        oauth = SimpleNamespace(provider_for_connection=lambda *_: provider, token_for_worker=Mock(return_value=grant))
        creator = SimpleNamespace(service=SimpleNamespace(), repository=SimpleNamespace(), clock=lambda: NOW, oauth=oauth)
        agent = YouTubePublishingAgent(creator)
        with patch('postriff_phase2.youtube.agent.project_public_gate', return_value=True):
            with self.assertRaises(AlphaError) as caught:
                agent._agentic_gate('workspace-one', CONNECTION)
            self.assertEqual(caught.exception.code, 'youtube_agentic_scope_required')
            grant['scopes'] = [READ, UPLOAD, MANAGE]
            self.assertEqual(agent._agentic_gate('workspace-one', CONNECTION)['authorizationLane'], 'agentic')
            oauth.token_for_worker.reset_mock(); provider.execution_enabled = False
            with self.assertRaises(AlphaError):
                agent._agentic_gate('workspace-one', CONNECTION)
            oauth.token_for_worker.assert_not_called()


class AgentDatabase:
    def __init__(self, value, owner_role='owner'):
        self.state, self.owner_role, self.result, self.revision = value, owner_role, None, 1
    @contextmanager
    def factory(self): yield self
    @contextmanager
    def cursor(self): yield self
    def execute(self, sql, params=()):
        if sql.startswith('SELECT to_regclass'):
            self.result = (None, None, False)  # Legacy selector; indexed claims have real PG coverage.
        elif sql.startswith('SELECT id::text,state'):
            self.result = [('workspace-one', copy.deepcopy(self.state))]
        elif sql.startswith('SELECT revision,state'):
            self.result = (self.revision, copy.deepcopy(self.state))
        elif sql.startswith('SELECT m.role,m.can_publish'):
            self.result = (self.owner_role, True)
        elif sql.startswith('SELECT state'):
            self.result = (copy.deepcopy(self.state),)
        elif sql.startswith('UPDATE public.pr_workspaces'):
            self.state = json.loads(params[0]); self.revision += 1
        elif sql.startswith('INSERT INTO public.pr_audit_events'):
            pass
        else:
            raise AssertionError('Unexpected synthetic SQL: ' + sql)
    def fetchone(self): return self.result
    def fetchall(self): return self.result


class IndexedCandidateDatabase(AgentDatabase):
    """A thin statement-snapshot hint precedes hydration of current source state."""
    def __init__(self, states, *, claim_rotation=True):
        super().__init__(None)
        self.states = copy.deepcopy(states)
        self.hints = [(workspace,) for workspace in states]
        self.hydrated, self.written = [], []
        self.claim_rotation, self.selections = claim_rotation, []

    def claim_order(self, workspace):
        data = root(self.states[workspace])
        for name in ('lastPlannerClaimAt', 'lastDispatchAt'):
            value = data.get(name)
            if type(value) not in (int, float):
                continue
            try:
                if math.isfinite(value) and 0 <= value < 253402300799:
                    return (0 if value < .000001 else value, workspace)
            except OverflowError:
                continue
        return (0, workspace)

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.split())
        if sql.startswith('SELECT to_regclass'):
            self.result = ('pr_youtube_operations', 'pr_youtube_planner_candidates', True)
        elif normalized == ("SELECT EXISTS(SELECT 1 FROM pg_attribute "
                "WHERE attrelid=to_regclass('public.pr_youtube_operations') "
                "AND attname='last_planner_claim' AND NOT attisdropped)"):
            self.result = (self.claim_rotation,)
        elif sql.startswith('SELECT w.id::text'):
            # Deliberately stale lease hints: do not filter these against the
            # newer lease that the next source hydration will observe.
            if len(params) != 4 or ' FOR UPDATE OF w SKIP LOCKED' not in sql:
                raise AssertionError('Expected a bounded, locked fleet selection')
            if self.claim_rotation:
                if 'ORDER BY o.last_planner_claim,w.id LIMIT 100' not in sql:
                    raise AssertionError('Migrated fleet selection must use the durable claim cursor')
            elif ('ORDER BY coalesce(' not in sql or 'lastPlannerClaimAt' not in sql
                    or 'lastDispatchAt' not in sql or ',w.id LIMIT 100' not in sql):
                raise AssertionError('Pre-107 selection must retain the safe state claim-cursor fallback')
            self.selections.append((sql, params))
            excluded = set(params[2])
            self.result = sorted((hint for hint in self.hints if hint[0] not in excluded),
                                 key=lambda hint: self.claim_order(hint[0]))[:100]
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            workspace = params[0]
            self.hydrated.append(workspace)
            self.result = (copy.deepcopy(self.states[workspace]),)
        elif sql.startswith("UPDATE public.pr_workspaces SET state=state#-'{youtubeAgent,fleetLease}'"):
            workspace, lease_id = params
            data = root(self.states[workspace])
            if (data.get('fleetLease') or {}).get('id') == lease_id:
                data.pop('fleetLease')
                self.written.append(workspace)
        elif sql.startswith('UPDATE public.pr_workspaces'):
            workspace = params[1]
            self.states[workspace] = json.loads(params[0])
            self.written.append(workspace)
        else:
            raise AssertionError('Unexpected indexed candidate SQL: ' + sql)


class DispatchTests(unittest.TestCase):
    def agent(self, db):
        service = SimpleNamespace(connection_factory=db.factory, commands=HostedPhase2Commands(clock=lambda: NOW))
        creator = SimpleNamespace(service=service, repository=SimpleNamespace(), clock=lambda: NOW,
            oauth=SimpleNamespace(reverify_for_worker=Mock(return_value={'ready': True})))
        agent = YouTubePublishingAgent(creator); agent._agentic_gate = Mock(return_value={'authorizationLane': 'agentic'})
        return agent

    def indexed_states(self, first_lease):
        first, later = state(), state()
        draft_and_policy(first); draft_and_policy(later)
        root(first)['fleetLease'] = copy.deepcopy(first_lease)
        root(later)['fleetLease'] = {'id': 'expired-later-lease', 'until': NOW - 1}
        return {'workspace-one': first, 'workspace-two': later}

    def test_stale_indexed_hint_rechecks_hydrated_active_lease_and_selects_later_workspace(self):
        lease = {'id': 'already-claimed-by-another-worker', 'until': NOW + 120,
                 'authorization': {'policyId': 'retained-current-owner-authorization'}}
        db = IndexedCandidateDatabase(self.indexed_states(lease))
        untouched = copy.deepcopy(db.states['workspace-one'])
        candidate = self.agent(db)._select_candidate(fleet=True)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate[0], 'workspace-two')
        self.assertEqual(db.hydrated, ['workspace-one', 'workspace-two'])
        self.assertEqual(db.written, ['workspace-two'])
        self.assertEqual(db.states['workspace-one'], untouched, 'A stale hint cannot overwrite an active source lease or its authority.')
        selected_lease = root(db.states['workspace-two'])['fleetLease']
        self.assertEqual(selected_lease['id'], candidate[4])
        self.assertEqual(selected_lease['until'], NOW + 120)
        self.assertEqual(selected_lease['authorization'], candidate[5])

    def test_indexed_hint_accepts_expired_equal_and_missing_lease_clocks(self):
        for lease in ({'id': 'expired', 'until': NOW - 1}, {'id': 'expires-now', 'until': NOW},
                      {'id': 'zero', 'until': 0}, {'id': 'missing-clock'}, {'id': 'null-clock', 'until': None}, None):
            with self.subTest(lease=lease):
                db = IndexedCandidateDatabase(self.indexed_states(lease))
                approved = copy.deepcopy(root(db.states['workspace-one'])['policies'])
                candidate = self.agent(db)._select_candidate(fleet=True)
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate[0], 'workspace-one')
                self.assertEqual(db.hydrated, ['workspace-one'])
                self.assertEqual(db.written, ['workspace-one'])
                new_lease = root(db.states['workspace-one'])['fleetLease']
                self.assertEqual(new_lease['id'], candidate[4])
                self.assertEqual(new_lease['until'], NOW + 120)
                self.assertEqual(root(db.states['workspace-one'])['policies'], approved, 'Lease renewal does not rewrite standing approval.')

    def test_stale_indexed_hint_rejects_bad_nonfinite_or_overflowed_source_lease(self):
        bad_leases = ({'until': True}, {'until': '0'}, {'until': 'malformed'}, {'until': float('nan')},
                      {'until': float('inf')}, {'until': float('-inf')}, {'until': 10 ** 400},
                      False, [], 'malformed-lease')
        for lease in bad_leases:
            with self.subTest(lease=lease):
                db = IndexedCandidateDatabase(self.indexed_states(lease))
                original = db.states['workspace-one']
                candidate = self.agent(db)._select_candidate(fleet=True)
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate[0], 'workspace-two')
                self.assertEqual(db.hydrated, ['workspace-one', 'workspace-two'])
                self.assertEqual(db.written, ['workspace-two'])
                self.assertIs(db.states['workspace-one'], original, 'Malformed lease state cannot be replaced through a stale indexed hint.')

    def test_fleet_claim_rotates_without_dispatch_progress_even_when_clock_stalls(self):
        from postriff_phase2.youtube.fleet import release_planner
        for migrated in (True, False):
            with self.subTest(claim_rotation_column=migrated):
                states = {}
                for workspace in ('workspace-one', 'workspace-two', 'workspace-three'):
                    value = state()
                    draft_and_policy(value)
                    root(value)['lastDispatchAt'] = NOW
                    states[workspace] = value
                db = IndexedCandidateDatabase(states, claim_rotation=migrated)
                agent = self.agent(db)
                selected, first_claim = [], None
                for _ in range(4):
                    candidate = agent._select_candidate(fleet=True)
                    self.assertIsNotNone(candidate)
                    selected.append(candidate[0])
                    claimed = root(db.states[candidate[0]])['lastPlannerClaimAt']
                    self.assertTrue(math.isfinite(claimed))
                    self.assertGreater(claimed, NOW)
                    if first_claim is None:
                        first_claim = claimed
                    elif len(selected) == 4:
                        self.assertGreater(claimed, first_claim, 'A stalled wall clock cannot stall repeated claim rotation.')
                    release_planner(agent, candidate)
                self.assertEqual(selected, ['workspace-one', 'workspace-three', 'workspace-two', 'workspace-one'])
                for workspace, original in states.items():
                    current = db.states[workspace]
                    self.assertEqual(root(current)['lastDispatchAt'], NOW)
                    self.assertEqual(root(current)['policies'], root(original)['policies'])
                    self.assertEqual(root(current)['drafts'], root(original)['drafts'])
                    self.assertEqual(current['phase2']['jobs'], [], 'Claim fairness never grants publication authority or queues a job.')
                    self.assertNotIn('fleetLease', root(current))
                agent._agentic_gate.assert_not_called()
                agent.creator.oauth.reverify_for_worker.assert_not_called()

    def test_indexed_claim_discards_invalid_cursor_and_honors_workspace_exclusion(self):
        invalid = (True, '0', float('nan'), float('inf'), float('-inf'), -1, 10 ** 400, 253402300799)
        for previous in invalid:
            with self.subTest(previous=previous):
                states = self.indexed_states(None)
                root(states['workspace-two'])['lastPlannerClaimAt'] = previous
                root(states['workspace-two'])['lastDispatchAt'] = NOW - 1
                db = IndexedCandidateDatabase(states)
                agent = self.agent(db)
                candidate = agent._select_candidate(fleet=True, exclude_workspaces=('workspace-one',))
                self.assertEqual(candidate[0], 'workspace-two')
                self.assertEqual(db.hydrated, ['workspace-two'])
                self.assertEqual(db.written, ['workspace-two'])
                self.assertEqual(db.selections[0][1][2], ['workspace-one'])
                claimed = root(db.states['workspace-two'])['lastPlannerClaimAt']
                self.assertEqual(claimed, NOW)
                self.assertTrue(math.isfinite(claimed))
                self.assertEqual(root(db.states['workspace-one']), root(states['workspace-one']))
                self.assertEqual(root(db.states['workspace-two'])['policies'], root(states['workspace-two'])['policies'])
                agent._agentic_gate.assert_not_called()

    def test_dispatcher_queues_exact_plan_once_without_provider_submission(self):
        value = state(); draft_and_policy(value); db = AgentDatabase(value)
        agent = self.agent(db)
        with patch('postriff_phase2.billing.require_publishing'):
            first = agent.dispatch_one(); second = agent.dispatch_one()
        self.assertTrue(first['dispatched']); self.assertFalse(first['providerVerified'])
        self.assertFalse(second['dispatched'])
        self.assertEqual(len(db.state['phase2']['jobs']), 1)
        self.assertEqual(db.state['phase2']['jobs'][0]['youtubeAgent']['draftId'], root(db.state)['drafts'][0]['id'])
        self.assertEqual(root(db.state)['drafts'][0]['approvalMode'], 'authorized_autopilot')

    def test_owner_loss_creates_paused_intervention_and_no_job(self):
        value = state(); draft_and_policy(value); db = AgentDatabase(value, owner_role='editor')
        result = self.agent(db).dispatch_one()
        self.assertTrue(result['interventionRequired'])
        self.assertEqual(root(db.state)['policies'][0]['status'], 'paused')
        self.assertEqual(db.state['phase2']['jobs'], [])


if __name__ == '__main__':
    unittest.main()
