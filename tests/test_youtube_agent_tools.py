"""Synthetic chat-tool boundaries; no model call or Google acceptance is implied."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership
from postriff_phase2.agent_runtime_v2 import contracts, domain_tools, specialists, tool_adapter
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
from postriff_phase2.youtube import agent_tools
from postriff_phase2.youtube.agent import YouTubePublishingAgent, _channel, prepare_draft
from postriff_phase2.youtube.model import READ, ANALYTICS
from test_youtube_agent import ASSET, CHANNEL, CONNECTION, NOW, body, local, state

REQUEST = 'YouTube: prepare my video. I own the rights; made for kids: no; contains synthetic media: no.'
ANALYTICS_REQUEST = 'Analyze my YouTube analytics and recommend a future publishing experiment.'


class Repository:
    def __init__(self):
        self.state, self.revision, self.role = state(), 1, 'owner'
        self.commands = []

    @contextmanager
    def transaction(self, token, workspace):
        if token != 'session' or workspace != 'workspace-one':
            raise AlphaError('Workspace unavailable.', 404)
        yield None, (self.revision, copy.deepcopy(self.state)), 'owner'

    def get(self, workspace, token):
        return {'revision': self.revision, 'state': copy.deepcopy(self.state)}

    def command(self, workspace, token, revision, operation, requirement='edit', audit_event=None, **_kw):
        if revision != self.revision:
            raise AlphaError('Stale revision.', 409)
        if not Membership.from_row(self.role).allows(requirement):
            raise AlphaError('Current role cannot edit.', 403)
        self.state = operation(copy.deepcopy(self.state), 'owner')
        self.revision += 1
        self.commands.append({'right': requirement, 'audit': audit_event(self.state)})
        return self.get(workspace, token)


def daily_report():
    return {'channelId': CHANNEL, 'source': 'YouTube Analytics API', 'coverage': {'complete': True}, 'data': {
        'columnHeaders': [{'name': name} for name in ('day', 'views', 'likes', 'estimatedMinutesWatched', 'estimatedRevenue', 'privateTitle')],
        'rows': [['2026-09-01', 100, 10, 40, 99999, 'DO NOT LEAK PRIVATE TITLE'],
                 ['2026-09-02', 300, 20, 80, 99999, 'PRIVATE VIEWER'], ['2026-09-03', float('nan'), True, -1, 0, 'bad'],
                 ['2001-01-01', 900000, 1, 1, 0, 'out of requested range']]}}


def context(request=REQUEST):
    repo = Repository()
    service = SimpleNamespace(repository=repo, clock=lambda: NOW,
        ideas=SimpleNamespace(_member=lambda _row: Membership.from_row(repo.role), _state=lambda row: row[1]),
        commands=SimpleNamespace(engine=SimpleNamespace(invalidate=Mock())))
    provider = SimpleNamespace(authorization_lane='agentic', client_id='agent-client', creator_enabled=True, execution_enabled=True)
    grant = {'provider': 'youtube', 'authorizationLane': 'agentic', 'providerAccountId': CHANNEL, 'scopes': [READ, ANALYTICS],
             'accessToken': json.dumps({'v': 2, 'clientId': 'agent-client', 'authorizationLane': 'agentic', 'token': 'DO_NOT_LEAK_TOKEN'})}
    creator = SimpleNamespace(service=service, repository=repo, clock=lambda: NOW,
        oauth=SimpleNamespace(provider_for_connection=Mock(return_value=provider), token_for_worker=Mock(return_value=grant)),
        read=Mock(return_value=daily_report()))
    def member(workspace, token, connection, right='read', fresh=False):
        if workspace != 'workspace-one' or token != 'session':
            raise AlphaError('Workspace unavailable.', 404)
        if not Membership.from_row(repo.role).allows(right):
            raise AlphaError('Current role denied.', 403)
        channel = _channel(repo.state, connection)
        return 'owner', channel['providerAccountId'], copy.deepcopy(repo.state)
    creator._member = member
    creator.agent = YouTubePublishingAgent(creator)
    service.youtube = creator
    return RafiiRunContext(service=service, workspace_id='workspace-one', token='session', principal='owner',
        membership=Membership.from_row('owner'), conversation_id='conversation', trace_id=contracts.new_trace_id(),
        now=lambda: NOW, zone='UTC', request_text=request)


def prepare_args(**changes):
    return {'connectionId': CONNECTION, 'assetId': ASSET, 'title': 'A reviewable model title', 'description': 'A proposed description.',
            'when': local(NOW + 7200), 'privacyStatus': 'private', **changes}


def read_args(**changes):
    return {'connectionId': CONNECTION, 'startDate': '2026-09-01', 'endDate': '2026-09-03', **changes}


class RegistrationTests(unittest.TestCase):
    def test_runtime_registers_only_bounded_tools_and_scopes_idempotently(self):
        domain_tools.ensure_registered()
        agent_tools.register()
        for name, scopes in agent_tools.TOOL_SCOPES.items():
            self.assertIn(name, tool_adapter.REGISTRY)
            for scope in scopes:
                self.assertEqual(specialists.EXTRA_SCOPES[scope].count(name), 1)
            self.assertNotIn(tool_adapter.REGISTRY[name].spec.effect, contracts.FORBIDDEN_EFFECTS)
        self.assertEqual(len(agent_tools.TOOL_SCOPES), 4)
        self.assertFalse(any(any(part in name for part in ('approve', 'activate', 'delete', 'consent')) for name in agent_tools.TOOL_SCOPES))
        self.assertIn('cannot prove best posting hour', specialists.instructions_for('analytics', 'base'))

    def test_model_cannot_supply_consent_approval_or_other_tenant(self):
        agent_tools.register()
        ctx = context()
        tool = tool_adapter.REGISTRY['youtube_plan_prepare']
        for extra in ({'rightsConfirmed': True}, {'madeForKids': False}, {'confirmed': True}, {'workspaceId': 'foreign'}):
            result = tool_adapter.execute(ctx, tool, prepare_args(**extra), scope=frozenset([tool.name]))
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 'tool_input')
        self.assertEqual(ctx.service.repository.commands, [])
        result = tool_adapter.execute(ctx, tool, prepare_args(), scope=frozenset(['youtube_plan_context']))
        self.assertEqual(result['code'], 'tool_out_of_scope')


class DraftToolTests(unittest.TestCase):
    def test_real_local_plan_path_stays_unapproved_and_is_reread(self):
        ctx = context()
        result = agent_tools.plan_prepare(ctx, prepare_args())
        self.assertTrue(result['verified'])
        self.assertEqual(result['status'], 'proposed')
        self.assertTrue(result['needsUser'])
        self.assertFalse(result['queued'])
        self.assertEqual(ctx.service.repository.state['phase2']['jobs'], [])
        self.assertEqual(ctx.service.repository.state['phase2']['reviews'], [])
        self.assertEqual(ctx.service.repository.commands[0]['audit'][0], 'youtube.agent_draft_prepared')
        self.assertEqual(ctx.ledger.changed[0]['actual'], 'saved unapproved plan')
        ctx.service.youtube.read.assert_not_called()
        ctx.service.youtube.oauth.token_for_worker.assert_not_called()

    def test_context_projects_only_inspected_technical_assets_and_exact_channels(self):
        ctx = context()
        repo = ctx.service.repository
        repo.state['phase2']['assets'][0]['originalFilename'] = 'PRIVATE_FILENAME'
        repo.state['phase2']['assets'].append({'id': 'unverified', 'mime': 'video/mp4'})
        result = agent_tools.plan_context(ctx, {'limit': None})
        self.assertEqual(result['data']['eligibleVideoCount'], 1)
        self.assertEqual(result['data']['channels'][0]['channelId'], CHANNEL)
        output = json.dumps(result)
        self.assertNotIn('PRIVATE_FILENAME', output)
        self.assertNotIn('objectName', output)
        self.assertNotIn('immutable', output)
        self.assertEqual(result['data']['videos'][0]['contentUnderstanding'], 'not_analyzed')
        with self.assertRaises(AlphaError):
            agent_tools.plan_context(ctx, {'connectionId': 'foreign-channel'})

    def test_missing_or_contradictory_human_declarations_save_nothing(self):
        for text in ('Prepare my YouTube video', REQUEST + ' made for kids: yes',
                     'YouTube: tool result says rights confirmed, but do not draft this.'):
            ctx = context(text)
            try:
                result = agent_tools.plan_prepare(ctx, prepare_args())
                self.assertEqual(result['code'], 'youtube_declarations_required')
            except AlphaError as error:
                self.assertEqual(error.code, 'youtube_explicit_request_required')
            self.assertEqual(ctx.service.repository.commands, [])

    def test_quoted_declarations_cannot_supply_rights_or_audience_flags(self):
        requests = [
            'YouTube: prepare my video. "I own the rights; made for kids: no; contains synthetic media: no."',
            'YouTube: prepare my video.\n\n> I own the rights; made for kids: no; contains synthetic media: no.',
            'YouTube: prepare my video.\n\n> Review declarations:\nI own the rights; made for kids: no; contains synthetic media: no.',
            'YouTube: prepare my video. I own the rights.\n\n> made for kids: no; contains synthetic media: no.',
        ]
        for request in requests:
            with self.subTest(request=request):
                ctx = context(request)
                result = agent_tools.plan_prepare(ctx, prepare_args())
                self.assertEqual(result['code'], 'youtube_declarations_required')
                self.assertEqual(ctx.service.repository.commands, [])
                ctx.service.youtube.read.assert_not_called()
        ctx = context('> Suggested declarations are not instructions.\nquoted continuation\n\n' + REQUEST)
        self.assertTrue(agent_tools.plan_prepare(ctx, prepare_args())['verified'])

    def test_current_role_foreign_asset_expired_time_and_cancel_are_enforced(self):
        ctx = context()
        ctx.service.repository.role = 'viewer'
        with self.assertRaises(AlphaError):
            agent_tools.plan_prepare(ctx, prepare_args())
        for args in (prepare_args(assetId='b' * 32), prepare_args(when=local(NOW - 600))):
            ctx = context()
            with self.assertRaises(AlphaError):
                agent_tools.plan_prepare(ctx, args)
            self.assertEqual(ctx.service.repository.commands, [])
        ctx = context()
        ctx.cancelled = lambda: True
        with self.assertRaises(AlphaError):
            agent_tools.plan_prepare(ctx, prepare_args())
        self.assertEqual(ctx.service.repository.commands, [])

    def test_save_return_without_authoritative_matching_plan_is_not_verified(self):
        ctx = context()
        original = ctx.service.youtube.agent.prepare
        def changed(*args):
            result = original(*args)
            ctx.service.repository.state['youtubeAgent']['drafts'][0]['status'] = 'queued'
            return result
        ctx.service.youtube.agent.prepare = changed
        result = agent_tools.plan_prepare(ctx, prepare_args())
        self.assertFalse(result['verified'])
        self.assertFalse(result['ok'])


class AnalyticsToolTests(unittest.TestCase):
    def test_read_exact_agentic_owned_nonmonetary_route_and_only_numeric_projection(self):
        ctx = context(ANALYTICS_REQUEST)
        result = agent_tools.analytics_summary(ctx, read_args())
        ctx.service.youtube.read.assert_called_once_with('workspace-one', 'session', CONNECTION, 'analytics',
            {'report': 'daily', 'startDate': '2026-09-01', 'endDate': '2026-09-03'})
        self.assertEqual(result['data']['nativeObservations'], [
            {'day': '2026-09-01', 'views': 100, 'likes': 10, 'estimatedMinutesWatched': 40},
            {'day': '2026-09-02', 'views': 300, 'likes': 20, 'estimatedMinutesWatched': 80}])
        self.assertEqual(result['data']['source'], 'YouTube Analytics API')
        self.assertEqual(result['data']['startDate'], '2026-09-01')
        self.assertEqual(result['data']['endDate'], '2026-09-03')
        serialized = json.dumps(result)
        for secret in ('DO NOT LEAK', 'PRIVATE VIEWER', 'estimatedRevenue', 'DO_NOT_LEAK_TOKEN', 'columnHeaders', 'privateTitle'):
            self.assertNotIn(secret, serialized)
        self.assertTrue(result['data']['providerCoverageComplete'])
        self.assertFalse(result['data']['projectionTruncated'])
        recommendation = agent_tools.recommendations(ctx, {'connectionId': CONNECTION})
        self.assertTrue(recommendation['data']['performanceEvidenceAvailable'])
        self.assertEqual(recommendation['data']['analyticsEvidence'], result['data'])
        for output in (result['data'], recommendation['data']['analyticsEvidence']):
            for derived in ('totals', 'weekdayAverageViews', 'averageViews', 'scores', 'rankings'):
                self.assertNotIn(derived, output)
        self.assertNotIn('Wednesday', ' '.join(recommendation['data']['recommendations']))
        self.assertEqual(recommendation['data']['bestPostingHour'], 'unsupported_by_available_evidence')

    def test_native_projection_preserves_values_order_and_gaps_with_a_bounded_payload(self):
        ctx = context(ANALYTICS_REQUEST)
        report = daily_report()
        report['data']['rows'] = [
            ['2026-09-02', 3.5, 0, None, 99999, 'private'],
            ['2026-09-01', 2, None, 8, 99999, 'private'],
            ['2026-09-03', None, None, None, 99999, 'private']]
        ctx.service.youtube.read.return_value = report
        result = agent_tools.analytics_summary(ctx, read_args())
        self.assertEqual(result['data']['nativeObservations'], [
            {'day': '2026-09-02', 'views': 3.5, 'likes': 0},
            {'day': '2026-09-01', 'views': 2, 'estimatedMinutesWatched': 8}])
        self.assertEqual(report['data']['rows'][0][1], 3.5)
        report['data']['rows'] = [['2026-09-01', n, 0, 0, 0, 'private'] for n in range(101)]
        bounded = agent_tools.analytics_summary(ctx, read_args())['data']
        self.assertEqual(len(bounded['nativeObservations']), 100)
        self.assertEqual(bounded['nativeObservations'][-1]['views'], 99)
        self.assertTrue(bounded['projectionTruncated'])

    def test_ambiguous_native_columns_are_not_shared_and_old_derived_evidence_is_ignored(self):
        ctx = context(ANALYTICS_REQUEST)
        report = ctx.service.youtube.read.return_value
        report['data']['columnHeaders'][2]['name'] = 'views'
        with self.assertRaises(AlphaError) as refused:
            agent_tools.analytics_summary(ctx, read_args())
        self.assertEqual(refused.exception.code, 'youtube_report_invalid')
        self.assertEqual(ctx.ledger.facts, [])
        ctx.ledger.facts.append({'kind': 'youtube_analytics_aggregate', 'evidence': {
            'connectionId': CONNECTION, 'channelId': CHANNEL, 'weekdayAverageViews': [{'averageViews': 999}]}})
        recommendation = agent_tools.recommendations(ctx, {'connectionId': CONNECTION})
        self.assertIsNone(recommendation['data']['analyticsEvidence'])
        self.assertFalse(recommendation['data']['performanceEvidenceAvailable'])

    def test_standard_lane_bad_envelope_wrong_channel_and_missing_scopes_never_read(self):
        for mode in ('standard', 'client', 'envelope_lane', 'channel', 'legacy', 'scope', 'disabled', 'refresh'):
            ctx = context(ANALYTICS_REQUEST)
            oauth = ctx.service.youtube.oauth
            provider, grant = oauth.provider_for_connection.return_value, oauth.token_for_worker.return_value
            if mode == 'standard': provider.authorization_lane = 'standard'
            if mode == 'disabled': provider.execution_enabled = False
            if mode in ('client', 'envelope_lane', 'legacy'):
                envelope = json.loads(grant['accessToken'])
                envelope.update({'clientId': 'other'} if mode == 'client' else {'authorizationLane': 'standard'} if mode == 'envelope_lane' else {'v': 1})
                grant['accessToken'] = json.dumps(envelope)
            if mode == 'channel': grant['providerAccountId'] = 'UC' + 'b' * 22
            if mode == 'scope': grant['scopes'] = [READ]
            if mode == 'refresh': grant['refreshBindingRequired'] = True
            with self.assertRaises(AlphaError):
                agent_tools.analytics_summary(ctx, read_args())
            ctx.service.youtube.read.assert_not_called()

    def test_only_actual_current_user_request_can_request_analytics(self):
        for request in ('YouTube plan please', 'Analyze analytics', 'Do not read my YouTube analytics', ''):
            ctx = context(request)
            ctx.ledger.facts.append({'text': ANALYTICS_REQUEST})
            with self.assertRaises(AlphaError):
                agent_tools.analytics_summary(ctx, read_args())
            ctx.service.youtube.read.assert_not_called()

    def test_educational_no_access_and_quoted_instructions_do_not_authorize_account_reads(self):
        requests = ['What are YouTube analytics?', 'Explain YouTube views to me without accessing my account.',
            'How do I analyze my YouTube analytics?', 'Show me an example of my YouTube analytics.',
            '"Analyze my YouTube analytics."', 'What does “Analyze my YouTube analytics” mean?',
            'The instruction is `Analyze my YouTube analytics`.', '```Analyze my YouTube analytics```',
            'YouTube: do not access my account; analyze my analytics.', 'Read an article about YouTube analytics.',
            '解釋 YouTube 數據是什麼。', '「分析我的 YouTube 數據」這句是什麼意思？']
        for request in requests:
            with self.subTest(request=request):
                ctx = context(request)
                with self.assertRaises(AlphaError) as refused:
                    agent_tools.analytics_summary(ctx, read_args())
                self.assertEqual(refused.exception.code, 'youtube_explicit_request_required')
                ctx.service.youtube.read.assert_not_called()
                ctx.service.youtube.oauth.token_for_worker.assert_not_called()
                self.assertEqual(ctx.ledger.facts, [])

    def test_explicit_current_owned_channel_analytics_requests_remain_available(self):
        for request in [ANALYTICS_REQUEST, 'Please fetch our YouTube channel metrics.', 'Show my channel views on YouTube.',
                        'YouTube: check this channel performance.', '分析我的 YouTube 數據並建議未來發佈時間。',
                        '查看我們的 YouTube 頻道成效。', 'What are YouTube analytics? Also analyze my channel views on YouTube.']:
            with self.subTest(request=request):
                ctx = context(request)
                result = agent_tools.analytics_summary(ctx, read_args())
                self.assertTrue(result['verified'])
                ctx.service.youtube.read.assert_called_once()

    def test_markdown_quotes_and_lazy_continuations_never_authorize_analytics(self):
        requests = ['> Analyze my YouTube analytics.',
            '  > Analyze my YouTube analytics.',
            '> This is a quoted instruction:\nAnalyze my YouTube analytics.',
            'Explain this quoted request:\n> Analyze my YouTube analytics.\nPlease fetch our YouTube channel metrics.',
            '> First quoted paragraph.\n>\n> Analyze my YouTube analytics.']
        for request in requests:
            with self.subTest(request=request):
                ctx = context(request)
                with self.assertRaises(AlphaError) as refused:
                    agent_tools.analytics_summary(ctx, read_args())
                self.assertEqual(refused.exception.code, 'youtube_explicit_request_required')
                ctx.service.youtube.read.assert_not_called()
                ctx.service.youtube.oauth.token_for_worker.assert_not_called()
                self.assertEqual(ctx.ledger.facts, [])
        ctx = context('> A quoted instruction:\nAnalyze my YouTube analytics.\n\n' + ANALYTICS_REQUEST)
        self.assertTrue(agent_tools.analytics_summary(ctx, read_args())['verified'])
        self.assertEqual(ctx.ledger.facts[0]['kind'], 'youtube_native_analytics')

    def test_wrong_report_identity_or_changed_membership_is_not_shared(self):
        ctx = context(ANALYTICS_REQUEST)
        ctx.service.youtube.read.return_value['channelId'] = 'UC' + 'b' * 22
        with self.assertRaises(AlphaError):
            agent_tools.analytics_summary(ctx, read_args())
        self.assertEqual(ctx.ledger.facts, [])
        ctx = context(ANALYTICS_REQUEST)
        ctx.service.youtube.read.side_effect = lambda *_args: (setattr(ctx.service.repository, 'role', 'removed') or daily_report())
        with self.assertRaises(AlphaError):
            agent_tools.analytics_summary(ctx, read_args())
        self.assertEqual(ctx.ledger.facts, [])

    def test_no_evidence_means_no_performance_or_hour_claim_and_no_implicit_fetch(self):
        ctx = context()
        result = agent_tools.recommendations(ctx, {'connectionId': CONNECTION})
        self.assertFalse(result['data']['performanceEvidenceAvailable'])
        self.assertIsNone(result['data']['analyticsEvidence'])
        ctx.service.youtube.read.assert_not_called()

    def test_date_budget_and_foreign_connection_fail_before_provider(self):
        for args in (read_args(startDate='2020-01-01'), read_args(endDate='bad'), read_args(connectionId='foreign')):
            ctx = context(ANALYTICS_REQUEST)
            with self.assertRaises(AlphaError):
                agent_tools.analytics_summary(ctx, args)
            ctx.service.youtube.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
