"""Founder account blocks in the consumer (CONTRACTS §8.F; postriff_phase2.operator_actions).

A block takes effect on session validation, API-token validation, the workspace transaction and the workers; lifting it
restores access; no other account is touched; the customer sees one fixed ACCOUNT_BLOCKED sentence. Production runs this
code before migration 062 exists, so with the table missing (or a column or the SELECT privilege missing) every request
is unaffected: the check is skipped, logged once by its error class, probed again after ten minutes, and never aborts the
caller's transaction. A small SQL-aware fake database stands in for PostgreSQL; tests/control/test_founder_actions_pg.py
runs the same enforcement against the real 062 table.
"""
import base64
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2 import automation_runs, operator_actions
from postriff_phase2.api_tokens import ApiTokens
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_app import HostedApplication, supabase_verifier
from postriff_phase2.hosted_worker import PostgresWorker

CUSTOMER = "30000000-0000-4000-8000-000000000001"
OTHER = "30000000-0000-4000-8000-000000000002"
WS = "20000000-0000-4000-8000-000000000001"
WS2 = "20000000-0000-4000-8000-000000000002"
TOKEN = "prt_" + "a" * 43
NOW = 1_790_000_000.0


class UndefinedTable(Exception):
    """Named like psycopg.errors.UndefinedTable; operator_actions matches the class name."""


class UndefinedColumn(Exception):
    pass


class InsufficientPrivilege(Exception):
    pass


ERRORS = {"UndefinedTable": UndefinedTable, "UndefinedColumn": UndefinedColumn, "InsufficientPrivilege": InsufficientPrivilege}


def jwt(payload):
    return "header." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".signature"


def session_token(user):
    return jwt({"sub": user, "session_id": "session-1234567890", "aal": "aal1"})


class FakeDatabase:
    """Answers the statements the enforcement points issue. `table` is the pr_account_blocks installation state:
    'installed', one of the UNAVAILABLE class names, or 'race' (the probe saw it, the lookup then fails)."""

    def __init__(self, table="installed"):
        self.table = table
        self.blocked_users, self.blocked_workspaces = set(), set()
        self.states = {WS: {"phase2": {"jobs": []}}, WS2: {"phase2": {"jobs": []}}}
        self.tokens = {}   # token -> (workspace, creator)
        self.executed, self.rollbacks = [], 0

    def connect(self):
        return FakeConnection(self)

    def probe(self):
        return "installed" if self.table in ("installed", "race") else self.table

    def lookup(self):
        if self.table != "installed":
            raise ERRORS.get(self.table, UndefinedTable)()

    def answer(self, sql, params):
        self.executed.append((sql, params))
        if sql.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            return []
        if "pr_mfa_enforcement" in sql:   # the session check (hosted_app.supabase_verifier)
            base = (False, False, False)
            if operator_actions.PROBE in sql:
                return [base + (self.probe(),)]
            if operator_actions.USER_BLOCKED in sql:
                self.lookup()
                return [base + (params[-1] in self.blocked_users,)]
            return [base]
        if sql == "SELECT " + operator_actions.PROBE:
            return [(self.probe(),)]
        if "pr_account_blocks" in sql:
            self.lookup()
            if sql == operator_actions.ANY_BLOCKED:
                return [(params[0] in self.blocked_users or params[1] in self.blocked_workspaces,)]
            return [(params[0] in self.blocked_users,)]
        if "FROM public.pr_api_tokens t" in sql:
            workspace, creator = self.tokens[TOKEN]
            return [("tok-1", workspace, creator, ["read"], "owner", True, True, True, True)]
        if "FOR UPDATE OF w" in sql and "pr_memberships" in sql:   # the repository transaction
            workspace, user = params
            return [(3, json.dumps(self.states[workspace]), "owner", True, True, True, True)] if workspace in self.states else []
        if "pg_try_advisory_xact_lock" in sql:
            return [(True,)]
        return []


class FakeCursor:
    def __init__(self, db):
        self.db, self.rows = db, []

    def execute(self, sql, params=None):
        self.rows = list(self.db.answer(sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def rollback(self):
        self.db.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def get_user(url, token):
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return {"status": 200, "body": {"id": payload["sub"], "email_confirmed_at": "2026-09-01T00:00:00Z"}}


class BlockTestCase(unittest.TestCase):
    def setUp(self):
        self.reset()
        self.addCleanup(self.reset)
        self.clock = [1000.0]
        patcher = mock.patch.object(operator_actions.time, "monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def reset():
        operator_actions._STATE.update(status=None, checked=0.0, logged=False)

    def verifier(self, db):
        return supabase_verifier("https://project.supabase.co", "p" * 24, db.connect, get_user=get_user)

    def assert_blocked(self, call):
        with self.assertRaises(AlphaError) as refused:
            call()
        self.assertEqual((refused.exception.status, refused.exception.code, str(refused.exception)), (403, "ACCOUNT_BLOCKED", operator_actions.MESSAGE))


class SessionBlocks(BlockTestCase):
    def test_table_present_block_takes_effect_unblock_lifts_and_others_are_untouched(self):
        db = FakeDatabase("installed")
        db.blocked_users.add(CUSTOMER)
        verify = self.verifier(db)
        self.assert_blocked(lambda: verify(session_token(CUSTOMER)))
        self.assert_blocked(lambda: verify.proof(session_token(CUSTOMER)))   # the passkey-proof path too
        db.executed.clear()
        self.assertEqual(verify(session_token(OTHER)), OTHER)
        self.assertEqual(len(db.executed), 1, "steady state: the block check is folded into the one session statement")
        self.assertIn(operator_actions.USER_BLOCKED, db.executed[0][0])
        db.blocked_users.clear()   # the block is lifted
        self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)

    def test_table_missing_requests_are_unaffected_logged_once_and_probed_again_after_ten_minutes(self):
        for missing in operator_actions.UNAVAILABLE:
            with self.subTest(missing=missing):
                self.reset()
                db = FakeDatabase(missing)
                db.blocked_users.add(CUSTOMER)   # even a row the probe cannot see changes nothing
                verify = self.verifier(db)
                with self.assertLogs("postriff.account_blocks", "WARNING") as logs:
                    self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)
                self.assertEqual([json.loads(line.split(":", 2)[2]) for line in logs.output], [{"event": "account_blocks_unavailable", "reason": missing}])
                self.assertEqual(len(db.executed), 1)
                db.executed.clear()
                with self.assertNoLogs("postriff.account_blocks", "WARNING"):
                    self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)
                self.assertNotIn("pr_account_blocks", db.executed[0][0])   # no probe, no lookup while cached
                self.clock[0] += 601
                db.table = "installed"   # 062 applied meanwhile
                self.assert_blocked(lambda: verify(session_token(CUSTOMER)))

    def test_a_lookup_that_still_fails_never_fails_the_session(self):
        db = FakeDatabase("race")
        db.blocked_users.add(CUSTOMER)
        verify = self.verifier(db)
        with self.assertLogs("postriff.account_blocks", "WARNING") as logs:
            self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)   # probe 'installed', savepoint lookup fails: allowed
            self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("UndefinedTable", logs.output[0])
        self.assertTrue(any(sql.startswith("ROLLBACK TO SAVEPOINT") for sql, _ in db.executed))
        # Folded lookup failing (cache says installed): the session's own connection rolls back and repeats its query.
        self.reset()
        operator_actions._STATE.update(status="installed", checked=1000.0, logged=True)
        db.executed.clear()
        self.assertEqual(verify(session_token(CUSTOMER)), CUSTOMER)
        self.assertEqual(db.rollbacks, 1)
        self.assertEqual([("pr_account_blocks" in sql) for sql, _ in db.executed], [True, False])
        self.assertEqual(operator_actions._STATE["status"], "UndefinedTable")

    def test_revoked_or_deleted_sessions_still_answer_401_first(self):
        db = FakeDatabase("installed")
        db.blocked_users.add(CUSTOMER)
        original = db.answer

        def revoked(sql, params):
            rows = original(sql, params)
            return [(False, True) + tuple(rows[0][2:])] if "pr_mfa_enforcement" in sql else rows
        db.answer = revoked
        with self.assertRaises(AlphaError) as refused:
            self.verifier(db)(session_token(CUSTOMER))
        self.assertEqual(refused.exception.status, 401)


class ApiTokenBlocks(BlockTestCase):
    def validate(self, db, workspace_id=WS):
        tokens = ApiTokens(SimpleNamespace(clock=lambda: NOW, connection_factory=db.connect))
        with db.connect() as con, con.cursor() as cur:
            return tokens.validate(cur, TOKEN, workspace_id)

    def test_table_present_blocked_creator_or_workspace_is_refused_and_lifting_restores(self):
        db = FakeDatabase("installed")
        db.tokens[TOKEN] = (WS, CUSTOMER)
        self.assertEqual(self.validate(db)["createdBy"], CUSTOMER)
        db.blocked_users.add(CUSTOMER)
        self.assert_blocked(lambda: self.validate(db))
        db.blocked_users.clear()
        db.blocked_workspaces.add(WS)
        self.assert_blocked(lambda: self.validate(db))
        lookups = [sql for sql, _ in db.executed if sql == operator_actions.ANY_BLOCKED]
        self.assertTrue(lookups)
        self.assertTrue(all(db.executed[i - 1][0].startswith("SAVEPOINT") for i, (sql, _) in enumerate(db.executed) if sql == operator_actions.ANY_BLOCKED))
        db.tokens[TOKEN] = (WS2, OTHER)   # another account's token is untouched by WS's block
        self.assertEqual(self.validate(db, WS2)["workspaceId"], WS2)
        db.blocked_workspaces.clear()
        db.tokens[TOKEN] = (WS, CUSTOMER)
        self.assertEqual(self.validate(db)["workspaceId"], WS)

    def test_table_missing_tokens_are_unaffected(self):
        db = FakeDatabase("UndefinedTable")
        db.tokens[TOKEN] = (WS, CUSTOMER)
        db.blocked_users.add(CUSTOMER)
        with self.assertLogs("postriff.account_blocks", "WARNING"):
            self.assertEqual(self.validate(db)["createdBy"], CUSTOMER)
        db.executed.clear()
        self.assertEqual(self.validate(db)["createdBy"], CUSTOMER)
        self.assertEqual([sql for sql, _ in db.executed if "pr_account_blocks" in sql], [])   # cached: no probe, no lookup

    def test_a_lookup_race_rolls_back_to_its_savepoint_and_allows(self):
        db = FakeDatabase("race")
        db.tokens[TOKEN] = (WS, CUSTOMER)
        db.blocked_users.add(CUSTOMER)
        with self.assertLogs("postriff.account_blocks", "WARNING"):
            self.assertEqual(self.validate(db)["createdBy"], CUSTOMER)
        statements = [sql.split(" ")[0] + (" " + sql.split(" ")[1] if sql.startswith("ROLLBACK") else "") for sql, _ in db.executed]
        self.assertEqual(statements[-3:], ["SAVEPOINT", "SELECT", "ROLLBACK TO"])


class WorkspaceFreeze(BlockTestCase):
    def repository(self, db, user=CUSTOMER):
        return PostgresWorkspaceRepository(db.connect, lambda token: user)

    def test_frozen_workspace_refuses_every_transaction_until_the_marker_is_gone(self):
        db = FakeDatabase("UndefinedTable")   # the marker needs no table lookup at all
        db.states[WS][operator_actions.MARKER] = {"blockIds": ["block-1"]}
        repository = self.repository(db)
        def enter(workspace):
            with repository.transaction("session-token", workspace) as (_, row, principal):
                return principal
        self.assert_blocked(lambda: enter(WS))
        self.assertEqual(enter(WS2), CUSTOMER)   # the person's other workspace is untouched
        self.assertEqual([sql for sql, _ in db.executed if "pr_account_blocks" in sql], [])
        db.states[WS].pop(operator_actions.MARKER)
        self.assertEqual(enter(WS), CUSTOMER)
        self.assertTrue(operator_actions.frozen({"accountBlock": {"blockIds": ["b"]}}))
        self.assertFalse(operator_actions.frozen({"phase2": {}}))

    def test_account_deletion_keeps_its_own_answer(self):
        db = FakeDatabase()
        db.states[WS].update({"accountDeletion": {"status": "pending"}, operator_actions.MARKER: {"blockIds": ["b"]}})
        with self.assertRaises(AlphaError) as refused:
            with self.repository(db).transaction("session-token", WS):
                pass
        self.assertEqual(refused.exception.code, "account_deletion_pending")


class WorkerFreeze(BlockTestCase):
    PREDICATE = "NOT state ? 'accountBlock'"

    def test_publishing_and_automation_workers_skip_frozen_workspaces_like_deletion(self):
        db = FakeDatabase("UndefinedTable")
        self.assertIsNone(PostgresWorker(db.connect, clock=lambda: NOW).claim())
        self.assertIsNone(CampaignWorker(SimpleNamespace(connection_factory=db.connect, clock=lambda: NOW))._claim())
        result = automation_runs.advance(SimpleNamespace(service=SimpleNamespace(commands=SimpleNamespace(engine=None), connection_factory=db.connect), clock=lambda: NOW))
        self.assertEqual(result["workspaces"], 0)
        selects = [sql for sql, _ in db.executed if sql.lstrip().startswith("SELECT id::text") and "pr_workspaces" in sql]
        self.assertEqual(len(selects), 3)
        for sql in selects:
            self.assertIn("NOT state ? 'accountDeletion'", sql)
            self.assertIn(self.PREDICATE, sql)
        self.assertEqual([sql for sql, _ in db.executed if "pr_account_blocks" in sql], [])   # no table dependency in any worker


class CustomerCopy(BlockTestCase):
    def test_the_customer_sees_one_fixed_sentence_and_code(self):
        class Service:
            def me(self, token, client_label=""):
                raise operator_actions.blocked_error()

        app = HostedApplication(Service(), None, {"provider": "supabase"}, "c" * 24)
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/me", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""), "wsgi.url_scheme": "https",
                   "HTTP_HOST": "postriff.example", "HTTP_AUTHORIZATION": "Bearer " + "t" * 32}
        captured = {}
        body = json.loads(b"".join(app(environ, lambda status, headers: captured.update(status=status))))
        self.assertEqual((captured["status"][:3], body), ("403", {"error": "This account is paused. Contact Rafii support to restore access.", "code": "ACCOUNT_BLOCKED"}))

    def test_purge_waits_for_the_table(self):
        db = FakeDatabase("UndefinedTable")
        with self.assertLogs("postriff.account_blocks", "WARNING"):
            with db.connect() as con, con.cursor() as cur:
                self.assertEqual(operator_actions.purge_lifted(cur), {"status": "not_installed"})


if __name__ == "__main__":
    unittest.main()
