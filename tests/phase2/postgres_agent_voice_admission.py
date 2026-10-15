"""Pre-provider voice settlement on disposable PostgreSQL, with no network calls.

Admission uses the direct database-login binding used by hosted_app.postgres_factory.
After the reserve commits, cleanup uses real service_role (ledger SELECT/INSERT
only). Identity and provider transport are synthetic; membership removal is SQL.
"""
import json
import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

import psycopg
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.agent_runtime_v2 import config, live

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')


def admin_connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def connection():
    db = admin_connection()
    db.execute('SET ROLE service_role')
    assert db.execute('SELECT current_user').fetchone()[0] == 'service_role'
    return db


class VoiceAdmissionPostgres(unittest.TestCase):
    def setUp(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals as engine_approvals
        engine_approvals.install()
        self.now = time.time()
        self.owner = str(uuid.uuid4())
        self.token = 'synthetic-session-' + uuid.uuid4().hex
        self.tokens = {self.token: self.owner}

        def verify(token):
            if token not in self.tokens:
                raise AlphaError('Verified session required.', 401)
            return self.tokens[token]
        verify.session_id = lambda token, principal: 'synthetic-voice-' + principal
        verify.auth_time = lambda token, principal: self.now
        with admin_connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.owner,))
        # The consumer SQL runtime does not SET ROLE. Migration007 deliberately
        # denies ledger UPDATE to service_role; existing reserve self-linking
        # uses the configured direct-login role. Do not expand production grants
        # to make a new fixture's stronger role assumption pass.
        self.service = HostedWorkspaceService(admin_connection, verify, clock=lambda: self.now)
        self.wid = self.service.bootstrap(self.token, 'studio')['workspaceId']
        approve_budgets(connection, self.wid)
        cfg = config.RuntimeConfig.from_environment({
            'OPENAI_API_KEY': 'offline', 'RAFII_VOICE_ENABLED': '1', 'RAFII_AGENT_V2_ENABLED': '1',
            'RAFII_AGENT_PERMISSIONS_ENABLED': '1', 'RAFII_AGENT_PERMISSIONS_ENFORCED': '1',
            'RAFII_AGENT_PERMISSIONS_WORKSPACES': self.wid, 'RAFII_TASK_ENGINE_ENABLED': '1',
            'RAFII_TASK_ENGINE_AUTHORITATIVE': '1', 'RAFII_TASK_ENGINE_WORKSPACES': self.wid,
        })
        self.assertEqual(cfg.permissions_for(self.wid), 'enforce')
        self.transport = mock.Mock(side_effect=AssertionError('This drill must never contact a provider.'))
        self.voice = live.VoiceSessions(SimpleNamespace(service=self.service, cfg=cfg, clock=lambda: self.now), self.transport)
        with connection() as db:
            self.assertEqual(db.execute('SELECT current_user').fetchone()[0], 'service_role')
            self.assertEqual(db.execute("SELECT has_table_privilege(current_user,'public.pr_usage_ledger','SELECT'),has_table_privilege(current_user,'public.pr_usage_ledger','INSERT'),has_table_privilege(current_user,'public.pr_usage_ledger','UPDATE')").fetchone(),(True,True,False))

    def rows(self, sql, params=()):
        with connection() as db:
            return db.execute(sql, params).fetchall()

    def admission(self):
        """Create an exact existing reserve through the real ledger, no transport."""
        self.service.repository.connection_factory = admin_connection
        with self.service.repository.transaction(self.token, self.wid) as (cur, _row, principal):
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Voice fixture') RETURNING id", (self.wid, principal))
            conversation = cur.fetchone()[0]
            cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                        "VALUES(%s,%s,%s,'running','synthetic-voice','quick',%s,%s,%s,'{}') RETURNING id::text",
                        (conversation, self.wid, principal, 'a' * 64, 'b' * 64, 'voice:' + uuid.uuid4().hex))
            run_id = cur.fetchone()[0]
            reserve = self.service.ledger.reserve(cur, self.wid, principal, 'tool', 1000, 'voice:' + run_id,
                charge_batch=False, provider='openai', model='synthetic-voice', run_id=run_id)
            artifact = {'voice': {'state': 'connecting', 'startedAt': self.now, 'reservationId': reserve['reservationId']}}
            cur.execute('UPDATE public.pr_agent_runs SET artifact=%s::jsonb WHERE id=%s', (json.dumps(artifact), run_id))
        # From here the bookkeeping path must work with the append-only role.
        self.service.repository.connection_factory = connection
        return live._VoiceAdmission(self.wid, principal, run_id, reserve['reservationId'])

    def test_session_or_membership_removed_after_reserve_closes_without_provider(self):
        # Separate workspaces prevent a deleted membership affecting the next case.
        for boundary in ('session', 'membership'):
            with self.subTest(boundary=boundary):
                if boundary == 'membership':
                    self.setUp()
                original = live.session_config

                def revoke_then_configure(*args, **kwargs):
                    # start() has committed its reserve before session_config.
                    # Exercise its real exception cleanup under restricted SQL
                    # authority, even though the user can no longer authenticate.
                    self.service.repository.connection_factory = connection
                    if boundary == 'session':
                        self.tokens.clear()
                    else:
                        with connection() as db:
                            db.execute('DELETE FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s', (self.wid, self.owner))
                    return original(*args, **kwargs)

                with mock.patch.object(live, 'session_config', side_effect=revoke_then_configure), \
                     mock.patch.object(live, 'record_session') as record, self.assertRaises(AlphaError) as denied:
                    self.voice.start(self.wid, self.token, {'sdp': 'v=0\r\n'})
                self.assertEqual(denied.exception.status, 401 if boundary == 'session' else 403)
                self.transport.assert_not_called()
                record.assert_not_called()
                runs = self.rows("SELECT id::text,status,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key LIKE 'voice:%%'", (self.wid,))
                self.assertEqual(len(runs), 1)
                run_id, status, artifact = runs[0]
                self.assertEqual(status, 'failed')
                self.assertEqual(artifact['voice']['billingBasis'], 'provider not contacted')
                reservation = artifact['voice']['reservationId']
                self.assertEqual(self.rows("SELECT kind,cost_state,actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='settle' AND reservation_id::text=%s", (self.wid, reservation)), [('settle', 'actual', 0)])
                self.assertEqual(self.rows('SELECT kind FROM public.pr_agent_events WHERE workspace_id=%s AND run_id::text=%s', (self.wid, run_id)), [('run.failed',)])
                self.now += 3600
                with connection() as db:
                    self.voice._reap(db.cursor(), self.wid, self.owner)
                self.assertEqual(len(self.rows("SELECT id FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='settle' AND reservation_id::text=%s", (self.wid, reservation))), 1)

    def test_exact_cleanup_is_replay_safe_with_one_settlement_and_event(self):
        admission = self.admission()
        self.voice._close_before_dispatch(admission)
        self.voice._close_before_dispatch(admission)
        self.assertEqual(self.rows("SELECT cost_state,actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='settle' AND reservation_id::text=%s", (self.wid, admission.reservation_id)), [('actual', 0)])
        self.assertEqual(self.rows('SELECT kind FROM public.pr_agent_events WHERE run_id::text=%s', (admission.run_id,)), [('run.failed',)])
        self.transport.assert_not_called()

    def test_foreign_reservation_is_rejected_without_changing_either_run(self):
        first, second = self.admission(), self.admission()
        forged = live._VoiceAdmission(self.wid, self.owner, first.run_id, second.reservation_id)
        with self.assertRaises(AlphaError) as denied:
            self.voice._close_before_dispatch(forged)
        self.assertEqual(denied.exception.status, 404)
        self.assertEqual(self.rows("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind IN ('settle','release')", (self.wid,)), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s AND status='running'", (self.wid,)), [(2,)])
        self.transport.assert_not_called()

    def test_existing_unknown_outcome_and_started_admission_cannot_become_free(self):
        admission = self.admission()
        with connection() as db:
            self.service.ledger.settle(db.cursor(), self.wid, admission.reservation_id, 'unknown', None)
        with self.assertRaises(AlphaError) as denied:
            self.voice._close_before_dispatch(admission)
        self.assertEqual(denied.exception.status, 409)
        self.assertEqual(self.rows("SELECT cost_state,actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='settle' AND reservation_id::text=%s", (self.wid, admission.reservation_id)), [('estimated_unknown', None)])
        started = self.admission()
        started.begin_dispatch()
        with self.assertRaises(AlphaError):
            self.voice._close_before_dispatch(started)
        self.assertEqual(self.rows("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='settle' AND reservation_id::text=%s", (self.wid, started.reservation_id)), [(0,)])
        self.transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
