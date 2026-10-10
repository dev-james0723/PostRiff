"""Memory correction and voice privacy parity; no provider requests or database writes."""
import copy
from contextlib import contextmanager
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import authz, config, live, memory_layers
import test_agent_permissions as permissions
from test_agent_runtime import workspace_state
from test_agent_voice_sessions import Fixture, successful_response


def bookkeeping_fixture(fixture):
    """Exercise the real service_tx lock/commit path without a session or provider."""
    original_execute = fixture.cursor.execute
    fixture.bookkeeping_outcome = False
    fixture.bookkeeping_connections = 0
    fixture.bookkeeping_locked = False

    def execute(sql, params=None):
        if sql.startswith("SELECT 1 FROM public.pr_workspaces WHERE id="):
            fixture.cursor.one = (1,) if params == (permissions.WS,) else None
        elif sql.startswith("SELECT r.artifact,r.status FROM public.pr_agent_runs r JOIN public.pr_usage_ledger u"):
            fixture.cursor.one = ((copy.deepcopy(fixture.cursor.artifact), fixture.cursor.status)
                if params == ('voice-run', permissions.WS, 'owner', 'reservation') else None)
        elif sql.startswith("SELECT pg_advisory_xact_lock(hashtextextended"):
            if params != ('pr_ledger:reservation',):
                raise AssertionError('Bookkeeping must lock the exact existing reservation.')
            fixture.bookkeeping_locked = True
            fixture.cursor.one = None
        elif sql.startswith("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id="):
            if not fixture.bookkeeping_locked:
                raise AssertionError('Outcome proof must be serialized with normal ledger settlement.')
            fixture.cursor.one = (1,) if fixture.bookkeeping_outcome else None
        else:
            original_execute(sql, params)
    fixture.cursor.execute = execute

    class Connection:
        def __init__(self):
            fixture.bookkeeping_connections += 1
            self.before = (copy.deepcopy(fixture.cursor.artifact), fixture.cursor.status,
                           len(fixture.settlements), len(fixture.events))
        def cursor(self): return fixture.cursor
        def commit(self): pass
        def rollback(self):
            fixture.cursor.artifact, fixture.cursor.status = self.before[:2]
            del fixture.settlements[self.before[2]:]
            del fixture.events[self.before[3]:]
        def close(self): pass
    fixture.voice.service.repository.connection_factory = Connection
    return fixture


class MemoryCorrectionTests(unittest.TestCase):
    def state(self):
        state = workspace_state()
        state['memoryEgress'] = {'cloud': True}
        state['learning'] = learning.initial('2026-10-10T00:00:00Z')
        learning.remember(state, {'id':'old', 'statement':'Use short openings.', 'ruleKey':'opening.style',
                                 'source':'chat', 'scope':{'platform':'LinkedIn'}}, actor='owner', now=permissions.NOW)
        return state

    def test_correction_preserves_provenance_and_removes_old_instruction_from_cloud_layer(self):
        state = self.state()
        before = memory_layers.context_revision(state)
        learning.remember(state, {'id':'new', 'statement':'Use reflective openings.', 'ruleKey':'opening.style',
                                 'source':'chat', 'replaces':'old', 'scope':{'platform':'LinkedIn'}}, actor='owner', now=permissions.NOW+1)
        view = memory_layers.read(state, layers=['preferences'])['layers']['preferences']
        rows = {row['id']:row for row in view['items']}
        self.assertEqual(rows['new']['supersedes'], 'old')
        self.assertEqual(rows['new']['statement'], 'Use reflective openings.')
        self.assertEqual(rows['old']['status'], 'retired')
        self.assertNotIn('statement', rows['old'])
        self.assertNotEqual(before, memory_layers.context_revision(state))
        self.assertEqual(learning.all_items(state)[-1]['statement'], 'Use short openings.', 'native inspection remains available')

    def test_disable_pause_retire_and_cloud_revoke_remove_instructions_and_change_pin(self):
        for action in ['disable', 'pause', 'retire', 'cloud']:
            with self.subTest(action=action):
                state = self.state()
                before = memory_layers.context_revision(state)
                if action == 'disable': state['learning']['enabled'] = False
                elif action == 'cloud': state['memoryEgress']['cloud'] = False
                else: learning.set_status(state, 'old', {'pause':'paused','retire':'retired'}[action], permissions.NOW+1)
                data = memory_layers.read(state, layers=['preferences'])
                self.assertNotIn('Use short openings.', str(data))
                self.assertNotEqual(before, memory_layers.context_revision(state))
                if action == 'disable':
                    self.assertFalse(data['layers']['preferences']['enabled'])
                    self.assertEqual(data['layers']['preferences']['items'][0]['confidence'], 'not_in_effect')

    def test_revisions_do_not_mutate_source_or_depend_on_other_workspace(self):
        first = self.state()
        second = copy.deepcopy(first)
        snapshot = copy.deepcopy(first)
        original = memory_layers.context_revision(first)
        second['learning']['revision'] += 1
        second['learning']['active'][0]['statement'] = 'Use reflective openings.'
        self.assertNotEqual(memory_layers.context_revision(second), original)
        self.assertEqual(memory_layers.context_revision(first), original)
        self.assertEqual(first, snapshot)

    def test_memory_tool_withholds_other_source_layers_under_current_domain_grants(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools
        ctx = permissions.ctx_for('enforce')
        ctx.specialist = 'memory'
        narrowed = permissions.grants(scopes={'domain:campaigns':False})
        with mock.patch.object(authz, 'load_grants', return_value=narrowed), mock.patch.object(authz, 'load_provider_view', return_value={}):
            authz.bind_context(ctx)
            result = domain_tools.memory_context(ctx, {'layers':['campaigns']})
        self.assertEqual(result['data']['layers'], {}, 'empty allowed layers must never default back to every layer')
        self.assertEqual(result['data']['withheldLayers'], ['campaigns'])


class VoicePermissionTests(unittest.TestCase):
    def context(self, mode='enforce', scopes=None):
        return SimpleNamespace(config=SimpleNamespace(permissions_for=lambda _:mode), workspace_id=permissions.WS,
                               principal=permissions.ME, membership=permissions.OWNER, now=lambda:permissions.NOW,
                               grants=permissions.grants(scopes=scopes), authz_state=workspace_state(), style={'tone':'warm'})

    def voice(self, mode='enforce'):
        return live.VoiceSessions(SimpleNamespace(service=None, cfg=SimpleNamespace(permissions_for=lambda _:mode)))

    def test_voice_history_honours_same_current_domain_revocation_as_text(self):
        cur = mock.Mock()
        cur.fetchall.return_value = [('assistant', {'text':'private draft facts', 'runId':'old-run'}), ('user', {'text':'my request'})]
        cur.fetchone.return_value = ({'capabilities':['tool.draft_get']},)
        result = self.voice()._history(cur, permissions.WS, 'conversation', permission_ctx=self.context(scopes={'domain:content':False}))
        self.assertIn('my request', result)
        self.assertNotIn('private draft facts', result)
        self.assertIn(mock.call(mock.ANY, (permissions.WS, 'old-run')), cur.execute.call_args_list)

    def test_enforce_missing_context_fails_closed_and_shadow_preserves_history(self):
        cur = mock.Mock()
        cur.fetchall.return_value = [('assistant', {'text':'old facts', 'runId':'old-run'})]
        self.assertEqual(self.voice()._history(cur, permissions.WS, 'conversation'), '')
        self.assertIn('old facts', self.voice('shadow')._history(cur, permissions.WS, 'conversation', permission_ctx=self.context('shadow')))

    def test_memory_derived_history_requires_current_correction_and_egress_pin(self):
        ctx = self.context()
        ctx.authz_used_capabilities = {'tool.memory_context'}
        ctx.authz_state['memoryEgress'] = {'cloud':True}
        ctx.authz_state['learning'] = {'enabled':True, 'revision':1, 'active':[], 'retired':[]}
        original = authz.trace_for(ctx)
        self.assertEqual(original['memoryContextRevision'], memory_layers.context_revision(ctx.authz_state))
        self.assertNotIn('files', original)
        cur = mock.Mock()
        cur.fetchone.return_value = (original,)
        body = {'runId':'memory-run', 'text':'earlier preference'}
        self.assertTrue(authz.history_eligible(cur, ctx, 'assistant', body))
        ctx.authz_state['learning']['revision'] = 2
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', body))
        ctx.authz_state['learning']['revision'] = 1
        ctx.authz_state['memoryEgress']['cloud'] = False
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', body))
        self.assertTrue(authz.history_eligible(cur, ctx, 'user', body), 'current user instructions remain their own authority')

    def test_unpinned_memory_prose_is_withheld_but_unrelated_history_is_preserved(self):
        ctx = self.context()
        cur = mock.Mock()
        cur.fetchone.return_value = ({'capabilities':['context.memory_layers']},)
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId':'old-run'}))
        cur.fetchone.return_value = ({'capabilities':['tool.draft_get']},)
        self.assertTrue(authz.history_eligible(cur, ctx, 'assistant', {'runId':'draft-run'}))

    def test_voice_replay_uses_current_memory_revision(self):
        ctx = self.context()
        ctx.authz_used_capabilities = {'tool.memory_context'}
        pin = authz.trace_for(ctx)
        ctx.authz_state['learning'] = {'revision':123, 'active':[], 'retired':[]}
        cur = mock.Mock()
        cur.fetchall.return_value = [('assistant', {'text':'stale preference prose', 'runId':'old-run'})]
        cur.fetchone.return_value = (pin,)
        self.assertEqual(self.voice()._history(cur, permissions.WS, 'conversation', permission_ctx=ctx), '')

    def test_task_source_domains_survive_trace_and_revoke_replayed_derived_prose(self):
        ctx = self.context()
        ctx.authz_used_capabilities = {'tool.draft_get'}
        ctx.authz_target_refs = [{'type':'campaign', 'id':'campaign'}]
        provenance = authz.trace_for(ctx)
        self.assertEqual(provenance['sourceDomains'], ['campaigns'])
        cur = mock.Mock()
        cur.fetchone.return_value = (provenance,)
        self.assertTrue(authz.history_eligible(cur, ctx, 'assistant', {'runId':'campaign-derived'}))
        ctx.grants = permissions.grants(scopes={'domain:campaigns':False})
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId':'campaign-derived'}))

    def test_source_domains_without_capability_evidence_fail_closed(self):
        ctx = self.context(scopes={'domain:campaigns':False})
        cur = mock.Mock()
        cur.fetchone.return_value = ({'capabilities':[], 'sourceDomains':['campaigns']},)
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId':'unproven-source'}))

    def fixture(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals as engine_approvals
        engine_approvals.install()  # Same concrete E8 registration performed by AgentRuntimeService.
        calls = []
        fixture = Fixture(lambda *_args, **kw: calls.append(kw['body']) or successful_response())
        fixture.voice.cfg = config.RuntimeConfig.from_environment({'OPENAI_API_KEY':'offline', 'RAFII_VOICE_ENABLED':'1',
             'RAFII_AGENT_V2_ENABLED':'1', 'RAFII_AGENT_PERMISSIONS_ENABLED':'1', 'RAFII_AGENT_PERMISSIONS_ENFORCED':'1',
             'RAFII_AGENT_PERMISSIONS_WORKSPACES':permissions.WS, 'RAFII_TASK_ENGINE_ENABLED':'1',
             'RAFII_TASK_ENGINE_AUTHORITATIVE':'1', 'RAFII_TASK_ENGINE_WORKSPACES':permissions.WS})
        self.assertEqual(fixture.voice.cfg.permissions_for(permissions.WS), 'enforce')
        fixture.voice.service.ideas._state = lambda _: workspace_state()
        fixture.voice.runtime.cfg = fixture.voice.cfg
        bookkeeping_fixture(fixture)
        return fixture, calls

    def test_voice_start_filters_private_style_before_provider_configuration(self):
        from postriff_phase2.agent_runtime_v2 import style
        fixture, calls = self.fixture()
        grants = permissions.grants(scopes={'domain:memory_brand':False})
        # Database seams only; bind_context, filter_context and admission execute normally.
        with mock.patch.object(authz, 'load_grants', return_value=grants), mock.patch.object(authz, 'load_provider_view', return_value={}), \
             mock.patch.object(style, 'load', return_value={'tone':'warm'}), mock.patch.object(live, 'live_prompt', wraps=live.live_prompt) as prompt:
            fixture.voice.start(permissions.WS, 'offline-session', {'sdp':'v=0\r\n', 'conversationId':'conversation'})
        self.assertIsNone(prompt.call_args.args[1])
        self.assertEqual(len(calls), 1)

    def test_consent_change_after_reservation_prevents_provider_call_and_settles_zero(self):
        fixture, calls = self.fixture()
        with mock.patch.object(authz, 'load_grants', side_effect=[permissions.grants(), permissions.grants(epoch=2)]), \
             mock.patch.object(authz, 'load_provider_view', return_value={}), self.assertRaises(AlphaError) as raised:
            fixture.voice.start(permissions.WS, 'offline-session', {'sdp':'v=0\r\n', 'conversationId':'conversation'})
        self.assertEqual(raised.exception.code, 'agent_permission_revoked')
        self.assertEqual(calls, [])
        self.assertEqual(fixture.settlements, [('reservation', 'completed', 0)])
        self.assertEqual(fixture.cursor.status, 'failed')


    def test_lost_session_or_membership_before_dispatch_closes_exact_reserve_without_provider(self):
        for status in (401, 403):
            with self.subTest(status=status):
                fixture, calls = self.fixture()
                transaction = fixture.voice.service.repository.transaction
                attempts = []
                @contextmanager
                def revoked_after_reservation(*args):
                    attempts.append(args)
                    if len(attempts) > 1:
                        raise AlphaError('Session or membership unavailable.', status)
                    with transaction(*args) as row:
                        yield row
                fixture.voice.service.repository.transaction = revoked_after_reservation
                with mock.patch.object(authz, 'load_grants', return_value=permissions.grants()), \
                     mock.patch.object(authz, 'load_provider_view', return_value={}), \
                     mock.patch.object(live, 'record_session') as record, self.assertRaises(AlphaError) as error:
                    fixture.voice.start(permissions.WS, 'offline-session', {'sdp':'v=0\r\n','conversationId':'conversation'})
                self.assertEqual(error.exception.status, status)
                self.assertEqual(len(attempts), 2, 'cleanup must not try the revoked caller token again')
                self.assertEqual(fixture.bookkeeping_connections, 1)
                self.assertEqual(calls, [])
                self.assertEqual(fixture.settlements, [('reservation','completed',0)])
                self.assertEqual(fixture.cursor.status, 'failed', 'the reaper must not bill this connecting run later')
                self.assertEqual(fixture.cursor.artifact['voice']['billingBasis'], 'provider not contacted')
                record.assert_not_called()

    def pending_fixture(self):
        fixture, calls = self.fixture()
        fixture.cursor.artifact = {'voice':{'state':'connecting','reservationId':'reservation','startedAt':1000}}
        fixture.cursor.status = 'running'
        admission = live._VoiceAdmission(permissions.WS, 'owner', 'voice-run', 'reservation')
        return fixture, calls, admission

    def test_preprovider_release_refuses_foreign_binding_and_creates_no_reservation(self):
        for field in ('workspace_id','principal','run_id','reservation_id'):
            with self.subTest(field=field):
                fixture, calls, admission = self.pending_fixture()
                setattr(admission, field, 'other')
                with self.assertRaises(AlphaError): fixture.voice._close_before_dispatch(admission)
                self.assertEqual(fixture.settlements, [])
                self.assertEqual(fixture.reservations, [])
                self.assertEqual(calls, [])
                self.assertEqual(fixture.cursor.status, 'running')

    def test_preprovider_release_cannot_make_started_unknown_or_live_usage_free(self):
        for boundary in ('dispatch','unknown_outcome','connected','live_id','failed'):
            with self.subTest(boundary=boundary):
                fixture, calls, admission = self.pending_fixture()
                if boundary == 'dispatch':
                    admission.begin_dispatch(); admission.begin_dispatch()
                elif boundary == 'unknown_outcome': fixture.bookkeeping_outcome = True
                elif boundary == 'connected': fixture.cursor.artifact['voice']['connectedAt'] = 1000
                elif boundary == 'live_id': fixture.cursor.artifact['voice']['liveSessionId'] = 'existing-provider-session'
                else: fixture.cursor.status = 'failed'
                with self.assertRaises(AlphaError): fixture.voice._close_before_dispatch(admission)
                self.assertEqual(fixture.settlements, [])
                self.assertEqual(calls, [])
                if boundary == 'dispatch': self.assertEqual(fixture.bookkeeping_connections, 0)

    def test_preprovider_cleanup_replay_is_one_zero_settlement_and_one_event(self):
        fixture, _calls, admission = self.pending_fixture()
        fixture.voice._close_before_dispatch(admission)
        fixture.voice._close_before_dispatch(admission)
        self.assertEqual(fixture.settlements, [('reservation','completed',0)])
        self.assertEqual(len(fixture.events), 1)
        self.assertEqual(fixture.cursor.status, 'failed')


if __name__ == '__main__':
    unittest.main()
