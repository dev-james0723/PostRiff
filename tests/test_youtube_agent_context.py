"""Synthetic provider-context lifecycle tests; no Google/model/network calls."""
import asyncio
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config, contracts, manager, tool_adapter
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
from postriff_phase2.agent_runtime_v2.live import VoiceSessions
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.permissions import Membership
from postriff_phase2.site_agent.service import SiteAgentService
from postriff_phase2.youtube import agent_context as private

NOW = 1800000000
SOURCE = private.source('workspace-one', 'youtube-one', 'UC' + 'a' * 22, 'generation-one', NOW)
WORDS = 'Native YouTube views were 918273 on 2026-09-01.'


def result(tagged=True):
    value = contracts.empty_result(contracts.new_trace_id(), 'text')
    value.update(answerText=WORDS, speakableSummary=WORDS, composedBy='manager', facts=[{'kind': 'youtube_native_analytics',
        'evidence': {'connectionId': SOURCE['connectionId'], 'channelId': SOURCE['channelId'], 'nativeObservations': [{'views': 918273}]}}])
    if tagged:
        value[private.KEY] = [copy.deepcopy(SOURCE)]
    return value


class Cursor:
    def __init__(self, rows=()):
        self.rows, self.sql, self.saved = list(rows), [], []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        if sql.startswith('UPDATE public.pr_messages SET body=') or sql.startswith('UPDATE public.pr_agent_runs SET status='):
            self.saved.append(json.loads(params[0] if 'pr_messages' in sql else params[1]))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def runtime():
    ideas = SimpleNamespace(_append_message=Mock(return_value={'messageId': 'message-one'}), _insert_event=Mock())
    creator = SimpleNamespace(journal=SimpleNamespace(assert_authorized=Mock()))
    service = SimpleNamespace(ideas=ideas, youtube=creator, clock=lambda: NOW)
    rt = AgentRuntimeService(service, cfg=config.RuntimeConfig.from_environment({}), model_factory=Mock())
    return rt


def context(rt):
    return RafiiRunContext(service=rt.service, workspace_id='workspace-one', token='synthetic-session', principal='owner',
        membership=Membership.from_row('owner'), conversation_id='conversation-one', trace_id=contracts.new_trace_id(), now=lambda: NOW)


def persist(rt, cur, value):
    rt._persist(cur, 'workspace-one', 'conversation-one', 'run-one', value,
        [{'type': 'text', 'text': value['answerText']}], [], [], trace={'traceId': value['traceId'], 'extension': WORDS},
        status='completed', usage={'billing': 'scripted'})


class ContextLifecycleTests(unittest.TestCase):
    def test_machine_sources_and_human_prose_have_distinct_history_eligibility(self):
        body = {'text': WORDS, 'agent': result()}
        self.assertFalse(private.history_eligible('assistant', body))
        self.assertTrue(private.history_eligible('user', body))
        self.assertTrue(private.history_eligible('assistant', {'text': 'User said YouTube views were 918273.'}))
        self.assertFalse(private.history_eligible('assistant', {'text': WORDS, 'agent': result(tagged=False)}))
        self.assertTrue(private.history_eligible('assistant', {'text': 'Ordinary answer', 'agent': {'facts': {'malformed': True}}}))
        self.assertFalse(private.history_eligible('assistant', private.redact_message(body)))

    def test_all_three_model_history_readers_exclude_only_provider_assistant_output(self):
        rows = [('assistant', {'text': 'An unrelated answer.'}), ('assistant', {'text': WORDS, 'agent': result()}),
                ('user', {'text': 'My own analytics notes.'})]
        rt = runtime()
        manager_history = rt._history(Cursor(rows), 'workspace-one', 'conversation-one')
        site_history = SiteAgentService._history(SimpleNamespace(), Cursor(rows), 'workspace-one', 'conversation-one')
        voice_history = VoiceSessions._history(SimpleNamespace(cfg=None), Cursor(rows), 'workspace-one', 'conversation-one')
        for history in (manager_history, site_history, voice_history):
            self.assertNotIn('918273', str(history))
            self.assertIn('unrelated answer', str(history))
        self.assertIn('My own analytics notes', str(site_history))
        self.assertIn('My own analytics notes', voice_history)

    def test_current_source_persists_with_exact_transaction_fence(self):
        rt, cur = runtime(), Cursor()
        persist(rt, cur, result())
        rt.service.youtube.journal.assert_authorized.assert_called_once_with('workspace-one', 'youtube-one', 'generation-one', cursor=cur, locked=True)
        self.assertIn('918273', json.dumps(cur.saved))
        self.assertIn(private.KEY, cur.saved[-1]['result'])

    def test_late_revoked_or_replaced_source_cannot_persist_any_native_copy(self):
        for event in ('revoked', 'replacement'):
            with self.subTest(event=event):
                rt, cur = runtime(), Cursor()
                rt.service.youtube.journal.assert_authorized.side_effect = AlphaError('Synthetic ' + event, 409, code='youtube_revoked_oauth')
                persist(rt, cur, result())
                serialized = json.dumps(cur.saved) + str(rt.service.ideas._append_message.call_args) + str(rt.service.ideas._insert_event.call_args_list)
                self.assertNotIn('918273', serialized)
                self.assertNotIn('nativeObservations', serialized)
                self.assertIn(private.NOTICE, serialized)

    def test_wrong_tenant_expired_and_unverifiable_context_fail_closed(self):
        for change in ({'workspaceId': 'another-workspace'}, {'expiresAt': NOW}, {'authorizationGeneration': None}):
            creator = SimpleNamespace(journal=SimpleNamespace(assert_authorized=Mock()))
            value = {**SOURCE, **change}
            if change.get('authorizationGeneration', 'present') is None:
                creator.journal.assert_authorized.side_effect = AlphaError('Missing generation.', 409)
            with self.assertRaises(AlphaError):
                private.assert_current(creator, 'workspace-one', [value], now=NOW)
        with self.assertRaises(AlphaError):
            private.assert_current(None, 'workspace-one', [SOURCE], now=NOW)

    def test_ordinary_chat_does_not_gain_provider_checks_or_redaction(self):
        rt, cur = runtime(), Cursor()
        ordinary = contracts.empty_result(contracts.new_trace_id(), 'text')
        ordinary.update(answerText='Your unrelated campaign draft is ready.', composedBy='manager')
        persist(rt, cur, ordinary)
        rt.service.youtube.journal.assert_authorized.assert_not_called()
        self.assertEqual(cur.saved[-1]['result']['answerText'], ordinary['answerText'])
        self.assertTrue(private.history_eligible('assistant', cur.saved[0]))

    def test_optional_followup_model_and_paused_state_are_narrowly_disabled(self):
        rt, ctx, cur = runtime(), None, Cursor()
        ctx = context(rt)
        ctx.ledger.youtube_provider_context.append(SOURCE)
        rt.followup_transport = Mock(side_effect=AssertionError('Private data must not reach a chip model.'))
        self.assertEqual(rt._manager_follow_ups(ctx, 'run-one', None, WORDS, 'en', 'model')['skipped'], 'youtube_private_context')
        rt.followup_transport.assert_not_called()
        self.assertFalse(rt._store_pending_run(cur, 'workspace-one', 'task-one', WORDS, [], youtube_provider_context=[SOURCE]))
        self.assertEqual(cur.sql, [])
        ordinary = Cursor([({'task': {'title': 'Unrelated work'}},)])
        rt._store_pending_run(ordinary, 'workspace-one', 'task-one', 'ordinary SDK state', [])
        self.assertIn('ordinary SDK state', ordinary.sql[-1][1][0])
        self.assertIsNone(rt._resume_pending_run('workspace-one', 'session', 'conversation-one', 'proposal', ('task-one', {private.KEY: [SOURCE]}),
                                                run_id='run-one', trace_id=ctx.trace_id, modality='text', zone='UTC'))

    def test_after_native_read_no_untracked_draft_task_or_external_read_copy_is_created(self):
        rt, executors = runtime(), []
        ctx = context(rt)
        for name, effect in (('draft_edit', contracts.CREATE_DRAFT), ('task_plan', contracts.READ), ('task_update', contracts.READ),
                             ('web_research', contracts.READ), ('image_analyze', contracts.READ)):
            executor = Mock(return_value={'ok': True})
            tool = tool_adapter.Tool(contracts.ToolSpec(name, effect, 'read', 'Synthetic tool'), {'type': 'object', 'properties': {}}, executor, name)
            self.assertTrue(tool_adapter.execute(ctx, tool, {})['ok'])
            ctx.ledger.youtube_provider_context.append(SOURCE)
            self.assertEqual(tool_adapter.execute(ctx, tool, {})['code'], 'youtube_analytics_read_only')
            self.assertEqual(executor.call_count, 1)
            ctx.ledger.youtube_provider_context.clear()
            executors.append(executor)
        ctx.ledger.youtube_provider_context.append(SOURCE)
        safe = tool_adapter.Tool(contracts.ToolSpec('youtube_recommendations', contracts.READ, 'read', 'Synthetic'),
                                {'type': 'object', 'properties': {}}, Mock(return_value={'ok': True}), 'Read native context')
        self.assertTrue(tool_adapter.execute(ctx, safe, {})['ok'])

    def test_deletion_removes_text_facts_state_and_trace_extensions_preserving_effect_receipts(self):
        artifact = {'result': result(), 'pendingRun': {'state': WORDS}, 'trace': {'traceId': 'trace', 'runtime': 'runtime', 'extension': WORDS},
                    'task': {'title': 'Unrelated earlier plan'}}
        artifact['result']['changedEntities'] = [{'id': 'draft-one', 'verified': True}]
        scrubbed = private.redact_artifact(artifact)
        self.assertNotIn('918273', json.dumps(scrubbed))
        self.assertNotIn('pendingRun', scrubbed)
        self.assertEqual(scrubbed['task'], artifact['task'])
        self.assertEqual(scrubbed['result']['changedEntities'], artifact['result']['changedEntities'])
        self.assertIn('918273', json.dumps(artifact))  # pure scrub must not mutate callers


try:
    import agents  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, 'Agents SDK is required for metered model adapter coverage.')
class ModelContextFenceTests(unittest.TestCase):
    def test_stream_checks_context_before_dispatch_and_preserves_usage_metering(self):
        rt = runtime()
        dispatched = []
        completed = SimpleNamespace(type='response.completed', response=SimpleNamespace(
            usage=SimpleNamespace(input_tokens=7, output_tokens=3)))

        async def stream_response():
            dispatched.append(True)
            yield completed

        ctx = context(rt)
        ctx.ledger.youtube_provider_context.append(SOURCE)
        wrapped = manager.metered(SimpleNamespace(stream_response=stream_response), ctx,
                                  agent='rafii_manager', workload='standard_reasoning', route={})

        async def collect():
            return [event async for event in wrapped.stream_response()]

        rt.service.youtube.journal.assert_authorized.side_effect = AlphaError('Synthetic revocation.', 409)
        with self.assertRaises(manager.ModelNotDispatched):
            asyncio.run(collect())
        self.assertEqual(dispatched, [])
        self.assertEqual(ctx.ledger.model_requests, 0)
        self.assertEqual(ctx.ledger.calls, [])
        rt.service.youtube.journal.assert_authorized.side_effect = None
        self.assertEqual(asyncio.run(collect()), [completed])
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(ctx.ledger.model_requests, 1)
        self.assertEqual(ctx.ledger.spans[0]['inputTokens'], 7)
        self.assertEqual(ctx.ledger.spans[0]['outputTokens'], 3)

    def test_continuation_checks_current_grant_before_dispatch_without_false_attempt(self):
        rt, model = runtime(), SimpleNamespace(get_response=AsyncMock(return_value=SimpleNamespace(usage=None)))
        ctx = context(rt)
        ctx.ledger.youtube_provider_context.append(SOURCE)
        rt.service.youtube.journal.assert_authorized.side_effect = AlphaError('Synthetic revocation.', 409)
        wrapped = manager.metered(model, ctx, agent='rafii_manager', workload='standard_reasoning', route={})
        with self.assertRaises(manager.ModelNotDispatched):
            asyncio.run(wrapped.get_response())
        model.get_response.assert_not_called()
        self.assertEqual(ctx.ledger.model_requests, 0)
        self.assertEqual(ctx.ledger.calls, [])
        rt.service.youtube.journal.assert_authorized.side_effect = None
        asyncio.run(wrapped.get_response())
        self.assertEqual(model.get_response.call_count, 1)
        self.assertEqual(ctx.ledger.model_requests, 1)


if __name__ == '__main__':
    unittest.main()
