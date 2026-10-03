"""Founder voice (CONTRACTS §8.E; PRD §6.5): POST /agent/voice/sessions and its delegation into founder_agent.turn.

Proves: the flag and the ops workspace are required (409 POLICY_DISABLED with a blocker) before anything is read; only
an AAL2 founder reaches it; the GPT-Live session is founder-scoped (founder instructions, client delegation, no tools,
store false, [founder:<mode>:<environment>] conversation, ops ledger reservation tagged costCenter='founder_ops');
delegations run the ordinary founder turn with modality 'voice' (founder tools only, receipts, the same audit) inside
the session's own conversation and data mode; end settles on the ops ledger; and the routes go through the real Control
boundary with copilot.use and the founder.voice budget.

No network: GPT-Live is a recording stand-in transport; the founder Manager is the scripted harness model; the ops
workspace is the fake cursor of test_founder_agent extended with the voice statements. No paid call, no database server.
"""
import copy
import io
import json
import time
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest import mock

try:
    import agents  # noqa: F401 — the founder turn runs on the Agents SDK
except ModuleNotFoundError as exc:  # the separate Control job installs no model SDK; the consumer job runs these
    raise unittest.SkipTest(f'Founder voice tests need the consumer requirements ({exc.name} missing)') from exc

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config as runtime_config, live
from rafii_control import founder_agent, founder_tools, founder_voice, http
from rafii_control.auth import CAPABILITIES, Boundary, Config, ControlError, VerifiedIdentity
from rafii_control.http import ControlApplication
from rafii_control.intelligence import QueryService

try:
    from test_boundary import MemoryStore, USER
    from test_founder_agent import NOW, OPS, OPERATOR, Control, DatabaseIdeas, FakeCursor, FakeDatabase, Scenarios, principal
    from test_live_metrics import ReadStore
except ImportError:  # python -m unittest control.test_founder_voice
    from control.test_boundary import MemoryStore, USER
    from control.test_founder_agent import NOW, OPS, OPERATOR, Control, DatabaseIdeas, FakeCursor, FakeDatabase, Scenarios, principal
    from control.test_live_metrics import ReadStore

PLACEHOLDER = '-'.join(('voice', 'test', 'placeholder'))   # routes resolve; nothing ever reaches OpenAI
ON = {founder_voice.FLAG: '1', founder_agent.OPS_WORKSPACE_ENV: OPS}
SDP = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\n'


def runtime_cfg(**flags):
    values = {'RAFII_AGENT_V2_ENABLED': '1', 'OPENAI_API_KEY': PLACEHOLDER, **flags}
    return runtime_config.RuntimeConfig.from_environment({k: v for k, v in values.items() if v is not None})


class Transport:
    """The GPT-Live stand-in: records each create call and answers like /v1/live/sessions (201, SDP answer, session id)."""

    def __init__(self, status=201):
        self.calls, self.status = [], status

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        self.calls.append({'method': method, 'url': url, 'headers': dict(headers or {}), 'body': copy.deepcopy(body)})
        if self.status != 201:
            return {'status': self.status, 'body': {'error': {'code': 'invalid_api_key', 'message': 'private provider text'}}, 'providerRequestId': None}
        return {'status': 201, 'body': {'session': {'id': 'live_session_1'}, 'transport': {'sdp': 'v=0\r\nanswer\r\n'}}, 'providerRequestId': None}


class VoiceCursor(FakeCursor):
    """test_founder_agent's fake cursor plus the statements of the voice broker (live.VoiceSessions)."""

    def execute(self, sql, params=()):
        db, text = self.db, ' '.join(sql.split())
        if text.startswith("SELECT state->'founderOps'"):
            from postriff_phase2.founder_policy import defaults
            self.rows = [({'operatorId': getattr(db, 'ops_operator', OPERATOR), 'environment': 'local', 'version': 1, 'policy': defaults()},)]
        elif text.startswith('INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact)'):
            ident = str(uuid.uuid4())
            db.runs[ident] = {'conversation_id': params[0], 'workspace_id': params[1], 'actor': params[2], 'status': 'running', 'model': params[3], 'key': params[6],
                              'artifact': json.loads(params[7])}
            self.rows = [(ident,)]
        elif text.startswith('SELECT artifact,idempotency_key,actor::text FROM public.pr_agent_runs'):
            run = db.runs.get(params[0])
            self.rows = [(copy.deepcopy(run['artifact']), run['key'], run['actor'])] if run and run['workspace_id'] == params[1] else []
        elif text.startswith('UPDATE public.pr_agent_runs SET artifact=%s::jsonb,status=%s'):
            db.runs[params[2]].update(artifact=json.loads(params[0]), status=params[1])
        elif text.startswith('UPDATE public.pr_agent_runs SET artifact=%s::jsonb,updated_at=now()'):
            db.runs[params[1]]['artifact'] = json.loads(params[0])
        elif text.startswith('SELECT conversation_id::text,status FROM public.pr_agent_runs'):
            run = db.runs.get(params[0])
            self.rows = [(run['conversation_id'], run['status'])] if run and run['workspace_id'] == params[1] else []
        elif text.startswith('SELECT id::text,artifact FROM public.pr_agent_runs') and 'idempotency_key LIKE' in text:
            self.rows = []   # nothing older than the cap to reap
        elif text.startswith('SELECT (SELECT count(*) FROM public.pr_phone_calls'):
            self.rows = [(getattr(db, 'phone_contacts', 0) + sum(1 for r in db.runs.values()
                         if r['workspace_id'] == params[4] and r['actor'] == params[5] and str(r['key']).startswith('voice:')
                         and not str(r['key']).startswith('voice:phone:') and r['status'] == 'running'),)]
        elif text.startswith('SELECT role,body FROM public.pr_messages') and 'LIMIT 16' in text:
            self.rows = [(m['role'], m['body']) for m in db.messages if m['conversation_id'] == params[0]][::-1][:16]
        else:
            return super().execute(sql, params)
        db.sql.append(text)


class VoiceRepository:
    """A repository whose transactions act as the principal the session token resolves to (principal_repository's capability)."""

    def __init__(self, db):
        self.db = db

    def verify_session(self, token):
        raise AlphaError('Sign in again.', 401)

    @contextmanager
    def transaction(self, token, workspace_id):
        acting = self.verify_session(token)
        self.db.ops_operator = acting
        yield VoiceCursor(self.db), (workspace_id, '{}', 'owner', False, False, False, False), acting


class Ledger:
    def __init__(self):
        self.reserved, self.settled = [], []

    def reserve(self, cur, workspace_id, member_id, dimension, estimate, key, *, charge_batch, provider='', model='', run_id=None, job_id=None, meta=None, credit_authority=None):
        reservation = str(uuid.uuid4())
        self.reserved.append({'reservationId': reservation, 'workspaceId': workspace_id, 'member': member_id, 'dimension': dimension, 'estimate': estimate, 'key': key,
                              'provider': provider, 'model': model, 'runId': run_id, 'meta': dict(meta or {})})
        return {'reservationId': reservation, 'duplicate': False, 'warnings': [], 'entitlement': None}

    def settle(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None):
        self.settled.append((reservation_id, outcome, actual_usd_micro))
        return {'reservationId': reservation_id, 'state': outcome}


class VoiceService:
    def __init__(self, db, clock=lambda: NOW):
        self.repository, self.ideas, self.clock, self.ledger = VoiceRepository(db), DatabaseIdeas(db), clock, Ledger()


def base(cfg=None, transport=None):
    return types.SimpleNamespace(cfg=cfg or runtime_cfg(), model_factory=None, live_transport=transport, clock=lambda: NOW)


def setUpModule():
    from unittest.mock import patch
    from rafii_control import founder_ops
    global _ops_patches
    _ops_patches = [patch('rafii_control.founder_ops.ready', return_value=True), patch('rafii_control.founder_ops.stored', side_effect=lambda store, operator: getattr(store, 'ops', None))]
    for mock in _ops_patches:
        mock.start()


def tearDownModule():
    for mock in reversed(_ops_patches):
        mock.stop()


class VoiceGateTests(unittest.TestCase):
    def setUp(self):
        self.db, self.transport = FakeDatabase(), Transport()
        self.service = VoiceService(self.db)

    def start(self, values, who=None, body=None, cfg=None, mode='live'):
        return founder_voice.start(self.service, who if who is not None else principal(), {'sdp': SDP} if body is None else body, str(uuid.uuid4()), mode=mode,
                                   control=Control(Scenarios.outage), values=values, base=base(cfg), transport=self.transport)

    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def test_flag_and_ops_workspace_are_required_before_anything_is_read(self):
        for values, blocker in (({founder_agent.OPS_WORKSPACE_ENV: OPS}, 'founder_voice_disabled'), ({founder_voice.FLAG: '0', founder_agent.OPS_WORKSPACE_ENV: OPS}, 'founder_voice_disabled'),
                                ({founder_voice.FLAG: '1'}, 'ops_workspace_not_configured'), ({founder_voice.FLAG: '1', founder_agent.OPS_WORKSPACE_ENV: 'not-a-uuid'}, 'ops_workspace_invalid')):
            with self.subTest(values=values), self.assertRaises(ControlError) as caught:
                self.start(values)
            self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.blocker), ('POLICY_DISABLED', 409, blocker))
        self.assertEqual((self.db.sql, self.transport.calls, self.service.ledger.reserved), ([], [], []), 'nothing was read, reserved or created')

    def test_only_an_aal2_founder_with_copilot_use_reaches_voice(self):
        for changes, code in (({'operator.role': 'workspace_admin'}, 'FOUNDER_REQUIRED'), ({'session.assurance': 'aal1'}, 'STEP_UP_REQUIRED'),
                              ({'operator.capabilities': ['control.read', 'metrics.query']}, 'SCOPE_DENIED'), ({'session.revoked_at': 1.0}, 'AUTH_REQUIRED')):
            with self.subTest(changes=changes), self.assertRaises(ControlError) as caught:
                self.start(ON, who=principal(**changes))
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ControlError) as caught:
            self.start(ON, who='customer-bearer-token')
        self.assertEqual(caught.exception.code, 'AUTH_REQUIRED')
        self.assertEqual(self.transport.calls, [])

    def test_runtime_and_route_blockers_are_policy_answers(self):
        with self.assertRaises(founder_agent.PolicyDisabled) as caught:
            self.start(ON, cfg=runtime_cfg(RAFII_AGENT_V2_ENABLED=None))
        self.assertEqual(caught.exception.blocker, 'agent_runtime_off')
        with self.assertRaises(founder_agent.PolicyDisabled) as caught:
            self.start(ON, cfg=runtime_cfg(OPENAI_API_KEY=None))
        self.assertEqual(caught.exception.blocker, 'voice_route_unavailable')
        self.assertEqual(self.transport.calls, [])

    def test_start_body_is_strict(self):
        for body in ({}, {'sdp': SDP, 'tools': ['refund']}, {'sdp': SDP, 'mode': 'demo'}, {'sdp': SDP, 'conversationId': 'not-a-uuid'}, {'sdp': SDP, 'locale': 'x' * 30},
                     {'sdp': SDP, 'pageContext': {'section': 'admin'}}, {'sdp': 'not an offer'}):
            with self.subTest(body=body), self.assertRaises(ControlError) as caught:
                self.start(ON, body=body)
            self.assertEqual(caught.exception.code, 'VALIDATION_FAILED')
        self.assertEqual(self.transport.calls, [])

    def test_status_names_every_blocker_without_creating_anything(self):
        closed = founder_voice.status(None, principal(), values={})
        self.assertEqual((closed['available'], closed['blockers']), (False, ['founder_voice_disabled', 'ops_workspace_not_configured', 'consumer_runtime_unavailable']))
        open_ = founder_voice.status(self.service, principal(), values=ON, control=Control(Scenarios.outage), base=base())
        self.assertEqual((open_['available'], open_['blockers'], open_['model'], open_['delegation']), (True, [], 'gpt-live-1', 'client'))
        self.assertEqual(founder_voice.status(self.service, principal(), values=ON, base=base(runtime_cfg(OPENAI_API_KEY=None)))['blockers'], ['voice_route_unavailable'])
        self.assertTrue(all(sql.startswith('SELECT ') for sql in self.db.sql), 'status only reads saved owner policy')
        self.assertEqual(self.transport.calls, [])


class VoiceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def setUp(self):
        self.db, self.transport = FakeDatabase(), Transport()
        self.service = VoiceService(self.db)
        self.control = Control(Scenarios.outage)

    def start(self, mode='live', body=None, who=None):
        return founder_voice.start(self.service, who or principal(), body or {'sdp': SDP}, str(uuid.uuid4()), mode=mode, control=self.control, values=ON,
                                   base=base(), transport=self.transport)

    def delegate(self, session_id, message, mode='live', delegation='d-1', values=ON, who=None):
        return founder_voice.delegate(self.service, who or principal(), session_id, {'delegationId': delegation, 'message': message}, str(uuid.uuid4()), mode=mode,
                                      control=self.control, values=values, base=base(), model_factory=founder_agent.founder_model_factory())

    def test_start_creates_a_founder_live_session_with_client_delegation_and_no_tools(self):
        out = self.start()
        (call,) = self.transport.calls
        self.assertEqual((call['method'], call['url'], call['headers']['Authorization'].startswith('Bearer ')), ('POST', live.LIVE_ENDPOINT, True))
        session = call['body']['session']
        self.assertEqual((session['delegation'], session['store'], session['model']), ({'type': 'client'}, False, 'gpt-live-1'))
        self.assertNotIn('tools', session, 'the Live session has no tools: every request is delegated to the founder turn')
        self.assertEqual(session['client']['data_channel']['allowed_client_events'], live.ALLOWED_CLIENT_EVENTS)
        self.assertIn('founder console', session['instructions'])
        self.assertIn('Never state a number', session['instructions'])
        self.assertIn('Data mode: Live, the real business data of the local environment', session['instructions'])
        self.assertNotIn('social-content workspace', session['instructions'], 'not the customer Voice Mode prompt')
        self.assertEqual(call['body']['transport'], {'type': 'webrtc', 'sdp': SDP})
        self.assertEqual((out['sdp'], out['liveSessionId'], out['mode'], out['namespace'], out['_dataState']), ('v=0\r\nanswer\r\n', 'live_session_1', 'live', 'founder:live:local', 'not_applicable'))
        self.assertEqual(out['delegation'], {'type': 'client', 'path': f"/api/control/v2/agent/voice/sessions/{out['voiceSessionId']}/delegations", 'modality': 'voice'})
        run = self.db.runs[out['voiceSessionId']]
        self.assertEqual((run['workspace_id'], run['actor'], run['status']), (OPS, OPERATOR, 'running'))
        self.assertTrue(run['key'].startswith('voice:founder:live:local:'))
        self.assertEqual((run['artifact']['voice']['state'], run['artifact']['voice']['founder']), ('live', {'mode': 'live', 'environment': 'local', 'namespace': 'founder:live:local'}))
        self.assertEqual(self.db.conversations[out['conversationId']]['title'], '[founder:live:local] Voice conversation')
        (reserved,) = self.service.ledger.reserved
        self.assertEqual((reserved['workspaceId'], reserved['key'], reserved['provider'], reserved['meta']['costCenter'], reserved['meta']['via']),
                         (OPS, 'voice:' + out['voiceSessionId'], 'openai', 'founder_ops', 'rafii_founder_voice'))
        self.assertEqual(reserved['estimate'], runtime_cfg().live_usd_micro_per_minute * out['capMinutes'])
        with self.assertRaises(ControlError):
            self.start(mode='demo')
        founder_voice.end(self.service, principal(), out['voiceSessionId'], {}, str(uuid.uuid4()), mode='live', control=self.control, values=ON, base=base())
        demo = self.start(mode='demo')
        self.assertIn('Data mode: Demo', self.transport.calls[-1]['body']['session']['instructions'])
        self.assertEqual(self.db.conversations[demo['conversationId']]['title'], '[founder:demo:local] Voice conversation')

    def test_the_founder_workspace_from_settings_serves_voice_when_the_variable_is_unset(self):
        class SettingsStore:
            """rafii_control.founder_settings as founder_ops reads it (the workspace created from Settings)."""
            environment = 'local'
            ops = OPS

            @contextmanager
            def transaction(self, read=False):
                yield types.SimpleNamespace(execute=lambda sql, params: types.SimpleNamespace(fetchone=lambda: {'ops': OPS}))
        stored = Control(Scenarios.outage, types.SimpleNamespace(store=SettingsStore()))
        values = {founder_voice.FLAG: '1'}
        self.assertEqual(founder_voice.status(self.service, principal(), values=values, control=stored, base=base())['blockers'], [])
        out = founder_voice.start(self.service, principal(), {'sdp': SDP}, str(uuid.uuid4()), mode='live', control=stored, values=values, base=base(), transport=self.transport)
        self.assertEqual(self.db.runs[out['voiceSessionId']]['workspace_id'], OPS)
        with self.assertRaises(founder_agent.PolicyDisabled) as caught:
            founder_voice.start(self.service, principal(), {'sdp': SDP}, str(uuid.uuid4()), mode='live', control=self.control, values=values, base=base(), transport=self.transport)
        self.assertEqual(caught.exception.blocker, 'ops_workspace_not_configured', 'no variable and no stored workspace')

    def test_an_active_phone_call_uses_the_same_slot_before_browser_provider_egress(self):
        self.db.phone_contacts = 1
        with self.assertRaises(ControlError) as caught:
            self.start()
        self.assertEqual(caught.exception.blocker, 'voice_busy')
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.service.ledger.reserved, [])

    def test_conversation_must_belong_to_the_session_namespace(self):
        live_session = self.start()
        with self.assertRaises(ControlError) as caught:
            self.start(mode='demo', body={'sdp': SDP, 'conversationId': live_session['conversationId']})
        self.assertEqual((caught.exception.code, caught.exception.status), ('SOURCE_UNAVAILABLE', 404))
        founder_voice.end(self.service, principal(), live_session['voiceSessionId'], {}, str(uuid.uuid4()), mode='live', control=self.control, values=ON, base=base())
        again = self.start(body={'sdp': SDP, 'conversationId': live_session['conversationId']})
        self.assertEqual(again['conversationId'], live_session['conversationId'], 'voice continues the same founder thread')

    def test_provider_refusal_releases_the_reservation_and_names_a_blocker(self):
        self.transport.status = 401
        with self.assertRaises(ControlError) as caught:
            self.start()
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.blocker), ('SOURCE_UNAVAILABLE', 503, 'live_auth'))
        (reserved,) = self.service.ledger.reserved
        self.assertEqual(self.service.ledger.settled, [(reserved['reservationId'], 'completed', 0)], 'a refused admission costs nothing')
        (run,) = self.db.runs.values()
        self.assertEqual((run['status'], run['artifact']['voice']['state']), ('failed', 'failed'))
        self.assertNotIn('private provider text', json.dumps(run['artifact']))

    def test_delegation_runs_the_founder_turn_with_voice_modality(self):
        session = self.start(mode='demo')
        with mock.patch.object(founder_agent, 'turn', wraps=founder_agent.turn) as turn:
            out = self.delegate(session['voiceSessionId'], '整理今日最需要我處理的三件事。', mode='demo')
        (call,) = turn.call_args_list
        body = call.args[2]
        self.assertEqual((body['modality'], body['mode'], body['conversationId']), ('voice', 'demo', session['conversationId']))
        self.assertEqual(body['idempotencyKey'], f"voice:{session['voiceSessionId']}:d-1")
        self.assertEqual(out['result']['modality'], 'voice')
        tools = [activity['tool'] for activity in out['result']['toolActivity']]
        self.assertEqual(tools, ['founder_attention_list', 'founder_source_health'])
        self.assertTrue(set(tools) <= set(founder_tools.FOUNDER_TOOL_NAMES), 'founder tools only')
        self.assertTrue(out['result']['founder']['receiptIds'], 'the spoken answer has the same receipts as a typed one')
        self.assertEqual((out['voiceSessionId'], out['delegationId'], out['mode'], out['namespace']), (session['voiceSessionId'], 'd-1', 'demo', 'founder:demo:local'))
        self.assertTrue(out['speakable'])
        self.assertEqual(self.db.conversations[out['conversationId']]['title'][:22], '[founder:demo:local] V')
        kept = self.db.runs[session['voiceSessionId']]['artifact']['voice']['delegations']
        self.assertEqual([(d['id'], d['runId']) for d in kept], [('d-1', out['runId'])])
        replay = self.delegate(session['voiceSessionId'], '整理今日最需要我處理的三件事。', mode='demo')
        self.assertEqual(replay['runId'], out['runId'], 'a repeated delegation event replays the same founder turn')
        self.assertEqual(len(self.db.runs[session['voiceSessionId']]['artifact']['voice']['delegations']), 1)
        refused = self.delegate(session['voiceSessionId'], 'refund them all now', mode='demo', delegation='d-2')
        self.assertEqual((refused['result']['composedBy'], refused['result']['toolActivity']), ('deterministic', []), 'voice is refused exactly like text')

    def test_delegations_are_confined_to_their_session(self):
        demo = self.start(mode='demo')
        with self.assertRaises(ControlError) as caught:
            self.delegate(demo['voiceSessionId'], 'hi', mode='live')
        self.assertEqual((caught.exception.code, caught.exception.status), ('SOURCE_UNAVAILABLE', 404), 'a Demo session never answers in Live')
        with self.assertRaises(ControlError) as caught:
            self.delegate(str(uuid.uuid4()), 'hi', mode='demo')
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(founder_agent.PolicyDisabled) as caught:
            self.delegate(demo['voiceSessionId'], 'hi', mode='demo', values={founder_agent.OPS_WORKSPACE_ENV: OPS})
        self.assertEqual(caught.exception.blocker, 'founder_voice_disabled', 'turning the flag off stops delegations at once')
        for body in ({'message': 'hi'}, {'delegationId': 'd-3', 'message': 'hi', 'tools': []}, {'delegationId': 'bad id!', 'message': 'hi'}):
            with self.subTest(body=body), self.assertRaises(ControlError) as caught:
                founder_voice.delegate(self.service, principal(), demo['voiceSessionId'], body, str(uuid.uuid4()), mode='demo', control=self.control, values=ON, base=base())
            self.assertEqual(caught.exception.code, 'VALIDATION_FAILED')
        founder_voice.end(self.service, principal(), demo['voiceSessionId'], {'reason': 'user_ended'}, str(uuid.uuid4()), mode='demo', control=self.control, values=ON, base=base())
        with self.assertRaises(ControlError) as caught:
            self.delegate(demo['voiceSessionId'], 'hi', mode='demo', delegation='d-4')
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.blocker), ('STALE_PREVIEW', 409, 'voice_session_ended'))

    def test_another_member_cannot_touch_the_founders_session(self):
        session = self.start()
        self.db.runs[session['voiceSessionId']]['actor'] = str(uuid.uuid4())
        for operation in (lambda: self.delegate(session['voiceSessionId'], 'hi'),
                          lambda: founder_voice.end(self.service, principal(), session['voiceSessionId'], {}, str(uuid.uuid4()), mode='live', control=self.control, values=ON, base=base())):
            with self.assertRaises(ControlError) as caught:
                operation()
            self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.service.ledger.settled, [])

    def test_transcript_and_end_settle_on_the_ops_ledger(self):
        clock = {'now': NOW}
        self.service.clock = lambda: clock['now']
        session = self.start()
        stored = founder_voice.transcript(self.service, principal(), session['voiceSessionId'], {'turns': [{'role': 'user', 'text': 'How much did AI cost today?'},
                                                                                                            {'role': 'tool', 'text': 'ignored'}]},
                                          str(uuid.uuid4()), mode='live', control=self.control, values={founder_agent.OPS_WORKSPACE_ENV: OPS}, base=base())
        self.assertEqual(stored['stored'], 1, 'transcripts stay writable when the flag is off, so a call in flight can be closed')
        self.assertEqual(self.db.runs[session['voiceSessionId']]['artifact']['voice']['transcript'][0]['text'], 'How much did AI cost today?')
        ended = founder_voice.end(self.service, principal(), session['voiceSessionId'], {'usageSeconds': 1, 'reason': 'user_ended'}, str(uuid.uuid4()), mode='live',
                                  control=self.control, values={founder_agent.OPS_WORKSPACE_ENV: OPS}, base=base())
        self.assertEqual((ended['state'], ended['mode']), ('ended', 'live'))
        (reserved,) = self.service.ledger.reserved
        (settled,) = self.service.ledger.settled
        self.assertEqual(settled, (reserved['reservationId'], 'unknown', None), 'client/server clocks cannot establish provider cost')
        self.assertIsNone(ended['usageSeconds'])
        self.assertEqual(ended['costState'], 'unknown')
        again = founder_voice.end(self.service, principal(), session['voiceSessionId'], {}, str(uuid.uuid4()), mode='live', control=self.control, values=ON, base=base())
        self.assertEqual(again['note'], 'Already ended.')
        self.assertEqual(len(self.service.ledger.settled), 1)
        for body in ({'turns': [], 'extra': 1}, 'x'):
            with self.subTest(body=body), self.assertRaises(ControlError):
                founder_voice.transcript(self.service, principal(), session['voiceSessionId'], body, str(uuid.uuid4()), mode='live', control=self.control, values=ON, base=base())


class RecordingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.budgets = []

    def budget(self, purpose, actor, limit):
        self.budgets.append((purpose, limit))


class QueryStore(ReadStore):
    """Control's restricted store as the founder tools read it (sources, receipts) plus the content-free audit."""

    def __init__(self, events):
        super().__init__()
        self.events = events

    def audit(self, **event):
        self.events.append(event)


class DemoQueries(QueryService):
    """The real QueryService over the founder's Demo dataset (the scenario stands in for the persisted Demo row)."""

    def demo_data(self, principal):
        return Scenarios.outage


class VoiceRouteTests(unittest.TestCase):
    """The voice routes through the real Control boundary (copilot.use, CSRF, the founder.voice budget, the envelope)."""

    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def setUp(self):
        self.store = RecordingStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        self.time = time.time()
        self.boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), self.store, lambda token: VerifiedIdentity(USER, 'aal2', 's' * 32, self.time),
                                 clock=lambda: self.time)
        self.db, self.transport = FakeDatabase(), Transport()
        self.service = VoiceService(self.db)
        self.service._agent_runtime_v2 = base(transport=self.transport)   # runtime_for(service) returns this configured runtime

    def app(self, flags, runtime=True):
        app = ControlApplication(self.boundary, DemoQueries(QueryStore(self.store.events)), runtime=(lambda: self.service) if runtime else None, flags=flags)
        self.token, session = self.boundary.exchange('verified-token', 'http://localhost:4449')
        self.csrf = session['csrfToken']
        return app

    def request(self, app, path, method='POST', body=None):
        raw = json.dumps(body).encode() if body is not None else b''
        path, _, query = path.partition('?')
        env = dict(PATH_INFO='/api/control/v2' + path, QUERY_STRING=query, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json',
                   HTTP_HOST='localhost:4449', HTTP_ORIGIN='http://localhost:4449', HTTP_COOKIE='__Host-rafii-control=' + self.token, HTTP_X_CSRF_TOKEN=self.csrf,
                   **{'wsgi.input': io.BytesIO(raw)})
        result = {}
        data = b''.join(app(env, lambda status, headers: result.update(status=int(status[:3]))))
        return result['status'], json.loads(data)

    def test_routes_are_registered_with_copilot_use_and_their_budgets(self):
        found = {(r[0], r[1].pattern): (r[2], r[5]) for r in http.EXTENSION_ROUTES if r[3] == 'founder_voice'}
        sid = founder_voice.SESSION_ID
        self.assertEqual(found, {('GET', '/agent/voice/status'): ('copilot.use', {}),
                                 ('POST', '/agent/voice/sessions'): ('copilot.use', {'budget': 'founder.voice', 'demo_ok': True}),
                                 ('POST', f'/agent/voice/sessions/{sid}/delegations'): ('copilot.use', {'budget': 'founder.agent.turn', 'demo_ok': True}),
                                 ('POST', f'/agent/voice/sessions/{sid}/transcript'): ('copilot.use', {'budget': 'founder.agent.turn', 'demo_ok': True}),
                                 ('POST', f'/agent/voice/sessions/{sid}/end'): ('copilot.use', {'budget': 'founder.agent.turn', 'demo_ok': True})})
        self.assertEqual(ControlApplication._capability('/agent/voice/sessions', 'POST'), 'copilot.use')
        before = len(http.EXTENSION_ROUTES)
        founder_voice.register()
        self.assertEqual(len(http.EXTENSION_ROUTES), before)

    def test_policy_refusals_come_first_with_their_blocker(self):
        app = self.app({})
        status, body = self.request(app, '/agent/voice/sessions', body={'sdp': SDP})
        self.assertEqual((status, body['code'], body['blocker']), (409, 'POLICY_DISABLED', 'founder_voice_disabled'))
        self.assertEqual(self.store.budgets[-1], ('founder.voice', 5))
        self.assertEqual((self.store.events[-1]['action'], self.store.events[-1]['result'], self.store.events[-1]['error_code']), ('copilot.use', 'denied', 'POLICY_DISABLED'))
        app = self.app({founder_voice.FLAG: '1'}, runtime=False)
        status, body = self.request(app, '/agent/voice/sessions?mode=demo', body={'sdp': SDP})
        self.assertEqual((status, body['blocker']), (409, 'ops_workspace_not_configured'))
        status, body = self.request(app, '/agent/voice/status', 'GET')
        self.assertEqual((status, body['data']['available'], body['data']['blockers']), (200, False, ['ops_workspace_not_configured', 'consumer_runtime_unavailable']))
        self.assertEqual((self.db.sql, self.transport.calls), ([], []))

    def test_start_delegate_and_end_through_the_boundary(self):
        app = self.app(dict(ON))
        app.workspace.demo = lambda principal_, action=None: Scenarios.outage   # the founder's own Demo dataset
        status, body = self.request(app, '/agent/voice/sessions?mode=demo', body={'sdp': SDP, 'mode': 'demo'})
        self.assertEqual(status, 200, body)
        data = body['data']
        self.assertEqual((data['namespace'], data['sdp'], body['dataState'], body['environment']), ('founder:demo:local', 'v=0\r\nanswer\r\n', 'not_applicable', 'local'))
        self.assertEqual(self.store.budgets[-1], ('founder.voice', 5))
        self.assertEqual([(e['action'], e['result']) for e in self.store.events[-2:]], [('copilot.use', 'allowed'), ('copilot.use', 'succeeded')])
        self.assertEqual(len(self.transport.calls), 1)
        session_id = data['voiceSessionId']
        self.service._agent_runtime_v2.model_factory = founder_agent.founder_model_factory()   # the scripted founder Manager (no paid call)
        status, body = self.request(app, f'/agent/voice/sessions/{session_id}/delegations?mode=demo', body={'delegationId': 'd-1', 'message': '整理今日最需要我處理的三件事。'})
        self.assertEqual(status, 200, body)
        self.assertEqual((body['data']['result']['modality'], body['data']['delegationId']), ('voice', 'd-1'))
        self.assertTrue(body['receiptIds'])
        self.assertEqual(body['receiptIds'], body['data']['result']['founder']['receiptIds'])
        self.assertIn(('founder.agent.turn', 'succeeded'), [(e['action'], e['result']) for e in self.store.events])
        self.assertEqual(self.store.budgets[-1], ('founder.agent.turn', 20))
        status, body = self.request(app, f'/agent/voice/sessions/{session_id}/end?mode=demo', body={'reason': 'user_ended'})
        self.assertEqual((status, body['data']['state']), (200, 'ended'))
        self.assertEqual(self.service.ledger.reserved[0]['meta']['costCenter'], 'founder_ops')
        self.assertEqual(len(self.service.ledger.settled), 1)


if __name__ == '__main__':
    unittest.main()
