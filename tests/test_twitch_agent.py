"""Offline tests of the real Rafii tool adapter and Twitch service boundary.

Provider and repository responses are synthetic. No model call, Twitch call,
production PostgreSQL/RLS acceptance or commercial permission is implied.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import twitch_agent
from postriff_phase2.permissions import Membership
from postriff_phase2.coworker import flags
from postriff_phase2.agent_runtime_v2 import (agent_permissions, authz, capability_registry,
    contracts, domain_tools, specialists, tool_adapter)
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext

NOW = 1_790_000_000.0
WORKSPACE, CONNECTION, SUBJECT = 'workspace-one', 'twitch-connection-one', '123456'
ENABLED = {'RAFII_TWITCH_PUBLIC_CONNECT': 'true', 'RAFII_TWITCH_COMMERCIAL_APPROVED': 'true',
           'RAFII_TWITCH_AI_PROCESSING_APPROVED': 'true'}
READ_REQUEST = 'Show my connected Twitch accounts.'
METRIC_REQUEST = 'Check my Twitch live viewers and follower counts.'
PREPARE_REQUEST = 'Twitch: prepare a chat message for my channel.'
SENSITIVE = 'PRIVATE_PROVIDER_TEXT_OR_SECRET'


class Repository:
    def __init__(self):
        self.role, self.actor, self.reads = 'owner', 'owner', []
        self.state = {'phase2': {'channels': [
            {'id': CONNECTION, 'platform': 'Twitch', 'providerAccountId': SUBJECT,
             'identityVerified': True, 'revoked': False, 'account': SENSITIVE},
            {'id': 'youtube-one', 'platform': 'YouTube', 'providerAccountId': 'yt-account',
             'identityVerified': True, 'revoked': False},
            {'id': 'unverified', 'platform': 'Twitch', 'providerAccountId': '888',
             'identityVerified': False, 'revoked': False},
        ]}}

    @contextmanager
    def transaction(self, token, workspace):
        if token != 'session' or workspace != WORKSPACE:
            raise AlphaError('Workspace unavailable.', 404)
        self.reads.append((token, workspace))
        yield None, (1, copy.deepcopy(self.state)), self.actor


def context(request=PREPARE_REQUEST):
    repo = Repository()
    service = SimpleNamespace(repository=repo, clock=lambda: NOW,
        ideas=SimpleNamespace(_member=lambda _row: Membership.from_row(repo.role), _state=lambda row: row[1]))
    native = SimpleNamespace(agent_processing_approved=True)
    native.list_connections = Mock(return_value={'connections': [
        {'id': CONNECTION, 'providerAccountId': SUBJECT, 'status': 'active', 'account': SENSITIVE,
         'scopes': [SENSITIVE], 'accessToken': SENSITIVE},
        {'id': 'foreign', 'providerAccountId': '999', 'status': 'active', 'account': SENSITIVE},
        {'id': 'unverified', 'providerAccountId': '888', 'status': 'active'},
        {'id': 'youtube-one', 'providerAccountId': '333', 'status': 'active'}],
        'readiness': {'details': SENSITIVE}, 'capabilities': [{'text': SENSITIVE}]})

    def read(workspace, token, connection, action, body):
        assert (workspace, token, connection) == (WORKSPACE, 'session', CONNECTION)
        assert body == {'payload': {}}
        assert authz.IN_TOOL.get() is True
        if action == 'twitch.channel.followers.total':
            return {'action': action, 'confirmed': True, 'status': 'confirmed', 'total': 812,
                    'data': [{'user_name': SENSITIVE, 'user_id': SENSITIVE}], 'provenance': {'private': SENSITIVE}}
        return {'action': action, 'confirmed': True, 'status': 'confirmed', 'data': [
            {'user_id': SUBJECT, 'viewer_count': 43, 'started_at': '2026-09-22T09:00:00Z',
             'user_name': SENSITIVE, 'title': SENSITIVE, 'game_name': SENSITIVE, 'stream_key': SENSITIVE}],
            'provenance': {'private': SENSITIVE}}

    def preview(workspace, token, connection, body):
        assert (workspace, token, connection) == (WORKSPACE, 'session', CONNECTION)
        assert authz.IN_TOOL.get() is True
        assert set(body) <= {'action', 'payload', 'executeAt'}
        return {'id': 'draft-one', 'payloadHash': 'b' * 64, 'action': body['action'], 'state': 'draft',
                'generation': 'a' * 32, 'expiresAt': NOW + 3600, 'executeAt': body.get('executeAt'),
                'payload': body['payload'], 'effects': [SENSITIVE], 'risk': SENSITIVE}

    native.read, native.preview = Mock(side_effect=read), Mock(side_effect=preview)
    # Deliberately absent: approve, dispatch, token, OAuth or stream-key interfaces.
    service.twitch = native
    return RafiiRunContext(service=service, workspace_id=WORKSPACE, token='session', principal='owner',
        membership=Membership.from_row('owner'), conversation_id='conversation', trace_id=contracts.new_trace_id(),
        now=lambda: NOW, request_text=request)


def prepare_args(**updates):
    return {'connectionId': CONNECTION, 'action': 'twitch.chat.send',
            'payload': {'message': 'Please review this exact human-requested draft.'}, **updates}


def metric_args(**updates):
    return {'connectionId': CONNECTION, 'metric': 'live_viewers', **updates}


def call(ctx, name, args, scope=None):
    return tool_adapter.execute(ctx, tool_adapter.REGISTRY[name], args,
                                scope=frozenset([name]) if scope is None else scope)


class TwitchToolTests(unittest.TestCase):
    def setUp(self):
        enabled = patch.object(flags, '_values', ENABLED)
        enabled.start()
        self.addCleanup(enabled.stop)
        domain_tools.ensure_registered()
        twitch_agent.register()

    def assert_no_service_calls(self, ctx):
        ctx.service.twitch.list_connections.assert_not_called()
        ctx.service.twitch.read.assert_not_called()
        ctx.service.twitch.preview.assert_not_called()

    def test_registered_once_with_small_scopes_and_no_effect_tools(self):
        twitch_agent.register()
        self.assertEqual(set(twitch_agent.TOOL_SCOPES), {'twitch_connection_context', 'twitch_metrics_snapshot', 'twitch_action_prepare'})
        for name, scopes in twitch_agent.TOOL_SCOPES.items():
            spec = tool_adapter.REGISTRY[name].spec
            self.assertEqual(spec.since, 2)
            self.assertFalse(spec.voice)
            self.assertNotIn(spec.effect, contracts.FORBIDDEN_EFFECTS)
            for scope in scopes:
                self.assertEqual(specialists.EXTRA_SCOPES[scope].count(name), 1)
            self.assertTrue(capability_registry.for_tool(name).explicit_request)
            self.assertNotIn('tool.' + name, capability_registry.legacy_baseline_v1())
        self.assertNotIn('twitch_metrics_snapshot', specialists.EXTRA_SCOPES.get('research', []))
        self.assertEqual(tool_adapter.REGISTRY['twitch_action_prepare'].spec.effect, contracts.CREATE_DRAFT)
        self.assertFalse(tool_adapter.REGISTRY['twitch_action_prepare'].spec.idempotent)

    def test_both_operator_flags_required_before_any_workspace_or_native_call(self):
        for values in ({}, {'RAFII_TWITCH_PUBLIC_CONNECT': 'true'},
                       {'RAFII_TWITCH_COMMERCIAL_APPROVED': 'true'},
                       {'RAFII_TWITCH_PUBLIC_CONNECT': '1', 'RAFII_TWITCH_COMMERCIAL_APPROVED': 'true'},
                       {'RAFII_TWITCH_PUBLIC_CONNECT': 'true', 'RAFII_TWITCH_COMMERCIAL_APPROVED': 'false'}):
            with self.subTest(values=values), patch.object(flags, '_values', values):
                ctx = context(PREPARE_REQUEST + ' ' + METRIC_REQUEST + ' ' + READ_REQUEST)
                for name, args in (('twitch_connection_context', {}), ('twitch_metrics_snapshot', metric_args()),
                                   ('twitch_action_prepare', prepare_args())):
                    self.assertEqual(call(ctx, name, args)['code'], 'feature_disabled')
                self.assertEqual(ctx.service.repository.reads, [])
                self.assert_no_service_calls(ctx)
                self.assertEqual(twitch_agent._instructions('content', 'BASE'), 'BASE')

    def test_instructions_explain_native_human_approval_and_metric_limits(self):
        for scope in ('rafii_manager', 'content', 'publishing_ops', 'analytics'):
            instructions = twitch_agent._instructions(scope, 'BASE')
            self.assertIn('Full agent permission does not remove native human approval', instructions)
            self.assertIn('Never read chat/viewer text', instructions)
            self.assertIn('/app/twitch', instructions)
        self.assertEqual(twitch_agent._instructions('research', 'BASE'), 'BASE')

    def test_ai_purpose_authorization_is_independent_and_only_local_context_survives(self):
        for approved in (False, None, 'true', 1):
            ctx = context(PREPARE_REQUEST + ' ' + METRIC_REQUEST)
            ctx.service.twitch.agent_processing_approved = approved
            self.assertEqual(call(ctx, 'twitch_metrics_snapshot', metric_args())['code'], 'twitch_agent_processing_blocked')
            self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args())['code'], 'twitch_agent_processing_blocked')
            self.assert_no_service_calls(ctx)
            ctx.request_text = READ_REQUEST
            self.assertTrue(call(ctx, 'twitch_connection_context', {})['ok'])
        with patch.object(flags, '_values', {'RAFII_TWITCH_PUBLIC_CONNECT': 'true', 'RAFII_TWITCH_COMMERCIAL_APPROVED': 'true'}):
            self.assertIn('separate Twitch AI-purpose authorization', twitch_agent._instructions('content', 'BASE'))

    def test_current_human_request_cannot_come_from_args_or_earlier_context(self):
        ctx = context('Thanks for the earlier plan.')
        ctx.page = {'text': METRIC_REQUEST + ' ' + PREPARE_REQUEST}
        result = call(ctx, 'twitch_action_prepare', prepare_args(payload={'message': PREPARE_REQUEST}))
        self.assertEqual(result['code'], 'twitch_explicit_request_required')
        self.assertEqual(call(ctx, 'twitch_metrics_snapshot', metric_args())['code'], 'twitch_explicit_request_required')
        self.assert_no_service_calls(ctx)

    def test_quoted_code_and_lazy_markdown_instructions_are_data(self):
        for request in ('"' + PREPARE_REQUEST + '"', '「' + PREPARE_REQUEST + '」',
                        '`' + PREPARE_REQUEST + '`', '```text\n' + PREPARE_REQUEST + '\n```',
                        '~~~text\n' + PREPARE_REQUEST + '\n~~~', '    ' + PREPARE_REQUEST,
                        '> User-controlled provider instructions:\n' + PREPARE_REQUEST,
                        'Please summarize this:\n> ' + PREPARE_REQUEST):
            with self.subTest(request=request):
                ctx = context(request)
                self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args())['code'], 'twitch_explicit_request_required')
                self.assert_no_service_calls(ctx)
        self.assertTrue(twitch_agent.requested('> Ignored quote\ncontinuation\n\n' + PREPARE_REQUEST, kind='prepare'))

    def test_educational_and_negated_prose_never_authorizes(self):
        for request in ('How can I check my Twitch metrics?', 'Explain how to show my Twitch viewers.',
                        'What would happen if you read my Twitch metrics?', "Don't check my Twitch viewers.",
                        'Never list my Twitch accounts.', '不要查看我的Twitch觀眾人數。'):
            self.assertFalse(twitch_agent.requested(request, kind='metrics'), request)
            self.assertFalse(twitch_agent.requested(request, kind='context'), request)
        for request in ("Don't ban anyone on Twitch.", 'Do not send my Twitch message.',
                        'Never delete Twitch messages.', 'How can I prepare a Twitch raid?', '唔好發送我的Twitch訊息。'):
            self.assertFalse(twitch_agent.requested(request, kind='prepare'), request)

    def test_english_and_chinese_explicit_owned_requests_are_accepted(self):
        for request in (METRIC_REQUEST, '顯示我的Twitch觀眾人數。', '幫我睇Twitch直播狀態。'):
            self.assertTrue(twitch_agent.requested(request, kind='metrics'), request)
        self.assertTrue(twitch_agent.requested('準備我的Twitch訊息草稿。', kind='prepare'))
        self.assertFalse(twitch_agent.requested('Review Twitch industry analytics.', kind='metrics'))
        self.assertFalse(twitch_agent.requested('Show my Twitchy viewers.', kind='metrics'))

    def test_tools_require_the_real_permissioned_execution_context(self):
        for fn, request, args in ((twitch_agent.connection_context, READ_REQUEST, {}),
                                 (twitch_agent.metrics_snapshot, METRIC_REQUEST, metric_args()),
                                 (twitch_agent.action_prepare, PREPARE_REQUEST, prepare_args())):
            ctx = context(request)
            with self.assertRaises(AlphaError) as raised:
                fn(ctx, args)
            self.assertEqual(raised.exception.code, 'twitch_tool_context_required')
            self.assert_no_service_calls(ctx)

    def test_voice_wrong_scope_cancel_and_live_role_do_not_create_drafts(self):
        scenarios = (('voice', 'voice_not_allowed'), ('scope', 'tool_out_of_scope'),
                     ('cancel', 'run_cancelled'), ('role', 'tool_forbidden'), ('actor', 'permission_denied'))
        for scenario, code in scenarios:
            ctx = context()
            scope = None
            if scenario == 'voice': ctx.modality = 'voice'
            if scenario == 'scope': scope = frozenset(['twitch_connection_context'])
            if scenario == 'cancel': ctx.cancelled = lambda: True
            if scenario == 'role': ctx.service.repository.role = 'viewer'  # cached owner cannot override new role
            if scenario == 'actor': ctx.service.repository.actor = 'different-human'
            with self.subTest(scenario=scenario):
                self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args(), scope=scope)['code'], code)
                self.assert_no_service_calls(ctx)

    def test_model_cannot_select_workspace_token_consent_approval_or_dispatch(self):
        for extra in ({'workspaceId': 'other'}, {'token': 'foreign-session'}, {'approved': True},
                      {'rightsConfirmed': True}, {'dispatch': True}, {'consent': True}):
            ctx = context()
            self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args(**extra))['code'], 'tool_input')
            self.assert_no_service_calls(ctx)

    def test_foreign_non_twitch_unverified_and_revoked_connections_fail_before_service(self):
        for connection in ('foreign', 'youtube-one', 'unverified', CONNECTION):
            for name, request, args in (('twitch_action_prepare', PREPARE_REQUEST, prepare_args(connectionId=connection)),
                                        ('twitch_metrics_snapshot', METRIC_REQUEST, metric_args(connectionId=connection)),
                                        ('twitch_connection_context', READ_REQUEST, {'connectionId': connection})):
                ctx = context(request)
                if connection == CONNECTION:
                    ctx.service.repository.state['phase2']['channels'][0]['revoked'] = True
                with self.subTest(connection=connection, tool=name):
                    self.assertEqual(call(ctx, name, args)['code'], 'not_found')
                    self.assert_no_service_calls(ctx)

    def test_connection_facts_are_workspace_bound_and_strip_all_provider_prose(self):
        ctx = context(READ_REQUEST)
        result = call(ctx, 'twitch_connection_context', {})
        self.assertEqual(result['data']['connections'], [{'connectionId': CONNECTION, 'twitchUserId': SUBJECT, 'status': 'active'}])
        self.assertFalse(result['providerVerified'])
        self.assertNotIn(SENSITIVE, json.dumps(result) + json.dumps(ctx.ledger.references))
        ctx.service.twitch.list_connections.assert_called_once_with(WORKSPACE, 'session')
        ctx.service.twitch.read.assert_not_called()
        ctx.service.twitch.preview.assert_not_called()

    def test_connection_projection_is_bounded_and_malformed_rows_are_not_reported(self):
        ctx = context(READ_REQUEST)
        channels, rows = [], []
        for number in range(30):
            channels.append({'id': f'c{number}', 'platform': 'Twitch', 'identityVerified': True})
            rows.append({'id': f'c{number}', 'providerAccountId': str(number + 1), 'status': SENSITIVE})
        ctx.service.repository.state['phase2']['channels'] = channels
        ctx.service.twitch.list_connections.return_value = {'connections': [None, {'id': 'c0', 'providerAccountId': True}] + rows}
        result = call(ctx, 'twitch_connection_context', {})
        self.assertEqual(len(result['data']['connections']), 20)
        self.assertTrue(all(row['status'] == 'unverified' for row in result['data']['connections']))
        self.assertNotIn(SENSITIVE, json.dumps(result))

    def test_native_metrics_are_exact_numeric_snapshots_without_private_text(self):
        for metric, key, count in (('live_viewers', 'viewer_count', 43), ('followers', 'total', 812)):
            ctx = context(METRIC_REQUEST)
            result = call(ctx, 'twitch_metrics_snapshot', metric_args(metric=metric))
            self.assertTrue(result['providerVerified'])
            self.assertFalse(result['contentRead'])
            self.assertEqual(result['data']['observations'][0]['metric'], key)
            self.assertEqual(result['data']['observations'][0]['value'], count)
            self.assertEqual(result['data']['observedAt'], NOW)
            self.assertNotIn(SENSITIVE, json.dumps(result) + json.dumps(ctx.ledger.facts))
            self.assertIn('not establish unique viewers', result['data']['limitation'])
            ctx.service.twitch.preview.assert_not_called()

    def test_invalid_and_missing_counters_never_become_a_zero(self):
        for value in (None, True, -1, 2**53, '42', 42.0, float('nan'), float('inf')):
            for metric in ('live_viewers', 'followers'):
                ctx = context(METRIC_REQUEST)
                action = twitch_agent._METRIC_ACTIONS[metric]
                ctx.service.twitch.read.side_effect = None
                ctx.service.twitch.read.return_value = {'action': action, 'confirmed': True,
                    'data': [{'user_id': SUBJECT, 'viewer_count': value}], 'total': value}
                result = call(ctx, 'twitch_metrics_snapshot', metric_args(metric=metric))
                with self.subTest(metric=metric, value=value):
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['data']['observations'], [])

    def test_no_live_stream_is_not_reported_as_zero_viewers(self):
        ctx = context(METRIC_REQUEST)
        ctx.service.twitch.read.side_effect = None
        ctx.service.twitch.read.return_value = {'action': twitch_agent._METRIC_ACTIONS['live_viewers'], 'confirmed': True, 'data': []}
        result = call(ctx, 'twitch_metrics_snapshot', metric_args())
        self.assertEqual(result['data']['observations'], [])

    def test_wrong_subject_accepted_unconfirmed_and_wrong_shapes_are_blocked(self):
        action = twitch_agent._METRIC_ACTIONS['live_viewers']
        for result in ({'action': action, 'confirmed': False, 'status': 'accepted', 'data': []},
                       {'action': 'twitch.other.read', 'confirmed': True, 'data': []},
                       {'action': action, 'confirmed': True, 'data': {'viewer_count': 40}},
                       {'action': action, 'confirmed': True, 'data': [{'user_id': '999', 'viewer_count': 50}]},
                       {'action': action, 'confirmed': True, 'data': [{'user_id': SUBJECT}] * 2}):
            ctx = context(METRIC_REQUEST)
            ctx.service.twitch.read.side_effect = None
            ctx.service.twitch.read.return_value = result
            self.assertFalse(call(ctx, 'twitch_metrics_snapshot', metric_args())['ok'])
            self.assertEqual(ctx.ledger.facts, [])

    def test_prepare_only_calls_preview_under_agent_context_and_remains_unapproved(self):
        ctx = context()
        args = prepare_args(executeAt=datetime.fromtimestamp(NOW + 1800, timezone.utc).isoformat())
        result = call(ctx, 'twitch_action_prepare', args)
        self.assertTrue(result['ok'])
        self.assertTrue(result['needsUser'])
        self.assertFalse(result['queued'])
        self.assertFalse(result['executed'])
        self.assertFalse(result['providerVerified'])
        self.assertEqual((result['state'], result['id'], result['payloadHash']), ('draft', 'draft-one', 'b' * 64))
        self.assertNotIn('payload', result)
        self.assertNotIn(SENSITIVE, json.dumps(result) + json.dumps(ctx.ledger.changed))
        ctx.service.twitch.preview.assert_called_once_with(WORKSPACE, 'session', CONNECTION,
            {'action': args['action'], 'payload': args['payload'], 'executeAt': args['executeAt']})
        ctx.service.twitch.list_connections.assert_not_called()
        ctx.service.twitch.read.assert_not_called()
        self.assertEqual(ctx.ledger.proposals, [])  # no generic proposal_apply authority
        self.assertEqual(ctx.ledger.changed[0]['actual'], 'unapproved draft')

    def test_agent_schedule_contract_matches_native_service_rfc3339(self):
        from postriff_phase2.twitch_service import _when
        ctx = context()
        timestamp = datetime.fromtimestamp(NOW + 1800, timezone.utc).isoformat()
        result = call(ctx, 'twitch_action_prepare', prepare_args(executeAt=timestamp))
        self.assertTrue(result['ok'])
        body = ctx.service.twitch.preview.call_args.args[3]
        self.assertEqual(_when(body['executeAt'], NOW), NOW + 1800)

    def test_no_oauth_stream_key_download_read_or_unsupported_action_can_be_prepared(self):
        for action in ('twitch.oauth.approve', 'twitch.stream.key.get', 'twitch.clip.download',
                       'twitch.stream.get', 'twitch.stream.start', 'twitch.video.upload', 'twitch.fake.write'):
            ctx = context()
            result = call(ctx, 'twitch_action_prepare', prepare_args(action=action))
            self.assertEqual(result['code'], 'twitch_native_review_required', action)
            self.assert_no_service_calls(ctx)

    def test_non_finite_large_payloads_and_times_never_reach_preview(self):
        for changes in ({'payload': {'x': float('nan')}}, {'payload': {'message': 'x' * 17000}},
                        {'executeAt': float('inf')}, {'executeAt': True}, {'payload': []}):
            ctx = context()
            self.assertFalse(call(ctx, 'twitch_action_prepare', prepare_args(**changes))['ok'])
            self.assert_no_service_calls(ctx)

    def test_upstream_approval_claims_and_malformed_receipts_do_not_enter_effect_ledger(self):
        for saved in ({'id': 'd', 'action': 'twitch.chat.send', 'state': 'approved', 'payloadHash': 'b' * 64},
                      {'id': 'd', 'action': 'twitch.ban.create', 'state': 'draft', 'payloadHash': 'b' * 64},
                      {'id': SENSITIVE + '\n', 'action': 'twitch.chat.send', 'state': 'draft', 'payloadHash': 'b' * 64},
                      {'id': 'd', 'action': 'twitch.chat.send', 'state': 'draft', 'payloadHash': SENSITIVE}):
            ctx = context()
            ctx.service.twitch.preview.side_effect = None
            ctx.service.twitch.preview.return_value = saved
            self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args())['code'], 'twitch_draft_unconfirmed')
            self.assertEqual(ctx.ledger.changed, [])
            self.assertEqual(ctx.ledger.proposals, [])

    def test_permissions_intersect_current_request_domain_role_and_generation(self):
        full = agent_permissions.from_scopes(WORKSPACE, 'owner', agent_permissions.preset_scopes('full'),
            preset='full', spend='none', generation=2)
        tool = authz.capability_for(tool_adapter.REGISTRY['twitch_action_prepare'].spec)
        surface = authz.Surface('specialist', tool.name, 'none')
        def decision(grants=full, request=PREPARE_REQUEST, role='owner', kind='agent'):
            return authz.decide(tool, surface=surface, member=Membership.from_row(role), grants=grants,
                state={}, actor=authz.Actor(kind, 'owner', request), now=NOW)
        self.assertEqual(decision().outcome, 'allow')  # permits preparation, never native execution
        self.assertEqual(decision(request='Continue.').reason, 'explicit_request_required')
        self.assertEqual(decision(kind='autopilot').reason, 'explicit_request_required')
        self.assertEqual(decision(role='viewer').reason, 'role')
        self.assertEqual(decision(agent_permissions.legacy(WORKSPACE, 'owner')).reason, 'not_in_baseline')
        narrow = agent_permissions.from_scopes(WORKSPACE, 'owner', {'category:create_edit': 'assist', 'domain:content': True}, preset='custom')
        self.assertEqual(decision(narrow).reason, 'domain_off')
        old_full = agent_permissions.from_scopes(WORKSPACE, 'owner', agent_permissions.preset_scopes('full'),
            preset='full', spend='none', generation=1)
        self.assertEqual(decision(old_full).outcome, 'confirm')
        # A permissible Full decision executes the same draft-only function.
        ctx = context()
        ctx.grants = full
        self.assertEqual(call(ctx, 'twitch_action_prepare', prepare_args())['state'], 'draft')
        self.assertFalse(hasattr(ctx.service.twitch, 'approve'))
        self.assertFalse(hasattr(ctx.service.twitch, 'dispatch'))


if __name__ == '__main__':
    unittest.main()
