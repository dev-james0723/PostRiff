"""Rafii Account Protection v2, P1 item 3: account holds and hold_epoch fences.

security_holds reads pr_security_account_controls (migration 121) and fails closed (503) when it cannot, unlike the
founder block helper (operator_actions._lookup), which fails open. Everything that acts as a person without them
present re-checks it: API tokens, the campaign worker at claim and before the writer call, automation drafting and
publishing and Agent task steps (through principal_repository, every transaction), and the social publish worker at
claim and before dispatch. RAFII_SECURITY_INCIDENT_HOLD is off by default; off still enforces an active hold (RAP-104)
but fails open and runs no epoch or authorization-time fence.

Statement-level tests over a recording cursor. Monotonic epochs, the trigger and grants against a real database are in
tests/phase2/postgres_account_holds.py.
"""
import re
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import automation_runs, operator_actions, security_holds  # noqa: E402
from postriff_phase2.api_tokens import ApiTokens  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "postriff_phase2"
USER = base.PRINCIPAL
WORKSPACE = "00000000-0000-0000-0000-0000000000aa"


def holds(cursor):
    return [params for sql, params in cursor.executed if "pr_security_account_controls" in sql]


class Case(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        flags.attach({"RAFII_SECURITY_INCIDENT_HOLD": "1"})
        installed = dict(security_holds._INSTALLED)
        self.addCleanup(security_holds._INSTALLED.update, installed)
        security_holds._INSTALLED.update(readable=False, checked=float("-inf"))


class Helper(Case):
    def test_flag_off_still_enforces_an_active_hold(self):
        # RAP-104: the flag is the rollback lever for incidents and fences, not a way to reopen a held account.
        flags.attach({})
        cursor = base.FakeCursor([((True,), 1), ((True,), 1)])
        with self.assertRaises(security_holds.AccountHeld) as raised:
            security_holds.assert_clear(cursor, USER, expected_epoch=3, authorized_at=None)
        self.assertEqual(raised.exception.code, "security_account_hold")
        self.assertIn("to_regclass('public.pr_security_account_controls')", cursor.executed[0][0])
        self.assertEqual(cursor.executed[1], ("SELECT hold_active FROM public.pr_security_account_controls WHERE user_id=%s", (USER,)))
        # Once known to be readable it is not probed again; a released hold, a moved epoch or an old approval pass.
        cleared = base.FakeCursor([((False,), 1)])
        self.assertIsNone(security_holds.assert_clear(cleared, USER, expected_epoch=3, authorized_at=None))
        self.assertEqual(len(cleared.executed), 1)

    def test_flag_off_fails_open_without_the_table(self):
        flags.attach({})
        cursor = base.FakeCursor([((False,), 1)])
        self.assertIsNone(security_holds.assert_clear(cursor, USER))
        self.assertIsNone(security_holds.snapshot(cursor, USER))
        # Not readable: probed once, then nothing until the probe interval passes.
        self.assertEqual(len(cursor.executed), 1)
        self.assertIsNone(security_holds.assert_clear(base.FakeCursor(), None))

    def test_no_control_row_is_clear_at_epoch_zero(self):
        cursor = base.FakeCursor([(None, 1)])
        self.assertEqual(security_holds.snapshot(cursor, USER), 0)
        self.assertEqual(holds(cursor), [(USER,)])

    def test_an_active_hold_refuses(self):
        with self.assertRaises(security_holds.AccountHeld) as raised:
            security_holds.assert_clear(base.FakeCursor([((True, 3, None), 1)]), USER)
        self.assertEqual((raised.exception.status, raised.exception.code), (403, "security_account_hold"))

    def test_an_epoch_that_moved_since_claim_refuses_even_after_release(self):
        with self.assertRaises(security_holds.AccountHeld) as raised:
            security_holds.assert_clear(base.FakeCursor([((False, 4, None), 1)]), USER, expected_epoch=2)
        self.assertEqual(raised.exception.code, "security_hold_changed")
        self.assertEqual(security_holds.assert_clear(base.FakeCursor([((False, 4, None), 1)]), USER, expected_epoch=4), 4)

    def test_work_authorized_before_the_latest_hold_needs_a_new_approval(self):
        placed = 1_800_000_000.0
        released = base.FakeCursor([((False, 2, placed), 1)])
        with self.assertRaises(security_holds.AccountHeld) as raised:
            security_holds.assert_clear(released, USER, authorized_at=placed - 1)
        self.assertEqual(raised.exception.code, "security_hold_changed")
        for unknown in (None, "yesterday"):
            with self.assertRaises(security_holds.AccountHeld):
                security_holds.assert_clear(base.FakeCursor([((False, 2, placed), 1)]), USER, authorized_at=unknown)
        self.assertEqual(security_holds.assert_clear(base.FakeCursor([((False, 2, placed), 1)]), USER, authorized_at=placed + 1), 2)
        # Never held: any authorization time passes; a per-request check passes no time at all.
        self.assertEqual(security_holds.assert_clear(base.FakeCursor([(None, 1)]), USER, authorized_at=None), 0)
        self.assertEqual(security_holds.assert_clear(base.FakeCursor([((False, 2, placed), 1)]), USER), 2)

    def test_fenced_repository_rechecks_every_transaction(self):
        cursor = base.FakeCursor([((False, 3, None), 1), ((True, 4, 1.0), 1)])

        @contextmanager
        def transaction(token, workspace_id, **kwargs):
            yield cursor, None, USER
        fenced = security_holds.fenced_repository(SimpleNamespace(transaction=transaction), USER, 3)
        with fenced.transaction("t", WORKSPACE):
            pass
        with self.assertRaises(security_holds.AccountHeld):
            with fenced.transaction("t", WORKSPACE):
                self.fail("a held inline write ran")

    def test_unreadable_controls_fail_closed(self):
        class Broken(base.FakeCursor):
            def execute(self, sql, params=None):
                raise RuntimeError('relation "public.pr_security_account_controls" does not exist')
        for cursor, user in ((Broken(), USER), (base.FakeCursor(), None)):
            with self.assertRaises(AlphaError) as raised:
                security_holds.assert_clear(cursor, user)
            self.assertEqual((raised.exception.status, raised.exception.code), (503, "security_state_unavailable"))

    def test_place_and_release_go_through_the_epoch_function(self):
        cursor = base.FakeCursor([((5,), 1), ((6,), 1)])
        self.assertEqual(security_holds.place(cursor, USER, "incident.not_me"), 5)
        self.assertEqual(security_holds.release(cursor, USER, "incident.resolved"), 6)
        self.assertEqual([sql for sql, _ in cursor.executed], ["SELECT public.pr_security_set_hold(%s,true,%s)", "SELECT public.pr_security_set_hold(%s,false,%s)"])

    def test_it_does_not_copy_the_fail_open_founder_lookup(self):
        source = (SRC / "security_holds.py").read_text()
        self.assertNotIn("operator_actions", source.split('"""', 2)[2])
        self.assertNotIn("SAVEPOINT", source)


class ApiTokenRoutes(Case):
    def setUp(self):
        super().setUp()
        state = dict(operator_actions._STATE)
        self.addCleanup(operator_actions._STATE.update, state)
        operator_actions._STATE.update(status="not_installed", checked=float("inf"))

    def validate(self, hold_row):
        row = ("token-id", WORKSPACE, USER, ["read"], "owner", True, True, True, True)
        cursor = base.FakeCursor([(row, 1), (hold_row, 1)])
        tokens = ApiTokens(SimpleNamespace(clock=lambda: 1_800_000_000.0))
        return tokens.validate(cursor, "prt_" + "a" * 43, WORKSPACE), cursor

    def test_a_held_creator_cannot_use_their_tokens(self):
        with self.assertRaises(security_holds.AccountHeld):
            self.validate((True, 2, None))

    def test_a_clear_creator_can(self):
        grant, cursor = self.validate((False, 2, None))
        self.assertEqual(grant["createdBy"], USER)
        self.assertEqual(holds(cursor), [(USER,)])

    def test_flag_off_still_refuses_a_held_creator(self):
        flags.attach({})
        security_holds._INSTALLED.update(readable=True)
        with self.assertRaises(security_holds.AccountHeld):
            self.validate((True,))
        grant, cursor = self.validate((False,))
        self.assertEqual((holds(cursor), len(cursor.executed)), ([(USER,)], 2))


class PrincipalRepository(Case):
    """automation drafting/publishing and Agent task steps act through principal_repository."""

    def repository(self, cursor, hold_epoch=None):
        row = (1, "{}", "owner", True, True, True, True)

        @contextmanager
        def transaction(token, workspace_id, **kwargs):
            yield cursor, row, USER
        service = SimpleNamespace(repository=SimpleNamespace(transaction=transaction, verify_session=None), clock=lambda: 0)
        return automation_runs.principal_repository(service, WORKSPACE, USER, "owner", hold_epoch=hold_epoch)

    def test_every_transaction_rechecks_the_hold_and_the_claim_epoch(self):
        repository, token = self.repository(base.FakeCursor([((False, 3, None), 1)]), hold_epoch=3)
        with repository.transaction(token, WORKSPACE) as (cur, _, principal):
            self.assertEqual(principal, USER)
        repository, token = self.repository(base.FakeCursor([((True, 4, None), 1)]), hold_epoch=3)
        with self.assertRaises(security_holds.AccountHeld):
            with repository.transaction(token, WORKSPACE):
                self.fail("a held principal's transaction ran")
        repository, token = self.repository(base.FakeCursor([((False, 5, None), 1)]), hold_epoch=3)
        with self.assertRaises(security_holds.AccountHeld):
            with repository.transaction(token, WORKSPACE):
                self.fail("a job ran across a hold epoch change")


class Fences(unittest.TestCase):
    """Where each worker checks: claim, and immediately before the external call."""

    def test_campaign_worker(self):
        source = (SRC / "campaign_worker.py").read_text()
        claim = source[source.index("def _claim"):source.index("def _title")]
        self.assertIn("security_holds.snapshot(cur, actor, authorized_at=task.get('activatedAt'))", claim)
        self.assertIn("pauseReason='security_hold'", claim)
        self.assertIn("'holdEpoch':hold_epoch", claim)
        tick = source[source.index("def tick(self)"):source.index("def _lead")]
        self.assertLess(tick.index("security_holds.assert_clear(cur, actor, claim['holdEpoch'])"), tick.index("ideas.turn("))
        self.assertEqual(tick.count("security_holds.assert_clear"), 2)  # transaction wrapper + before the writer call

    def test_automation_runs(self):
        source = (SRC / "automation_runs.py").read_text()
        self.assertIn("security_holds.assert_clear(cur, principal, hold_epoch, authorized_at=authorized_at)", source)
        self.assertIn('hold_epoch=claim.get("holdEpoch")', source)
        # commit_item publishes through principal_repository, so the hold is re-read in the publishing transaction.
        commit = source[source.index("def commit_item"):]
        self.assertIn("principal_repository(service, workspace_id, principal", commit)
        self.assertIn('(item.get("decision") or {}).get("at")', commit)
        self.assertIn("authorized_at=authorized", commit)

    def test_agent_task_executor(self):
        source = (SRC / "agent_runtime_v2" / "task_engine" / "executor.py").read_text()
        execute = source[source.index("def execute("):source.index("def _category")]
        self.assertLess(execute.index('security_holds.snapshot(cur, task["createdBy"]'), execute.index("consume_approval(cur"))
        self.assertIn("hold_epoch=hold_epoch", execute)
        self.assertIn('authorized_at=current.get("createdAt")', execute)
        self.assertIn('security_holds.fenced_repository(service.repository, task["createdBy"], hold_epoch)', execute)
        self.assertIn('"security_state_unavailable": "retryable"', source)

    def test_social_publish_worker(self):
        source = (SRC / "hosted_worker.py").read_text()
        approved = source[source.index("def _approved"):source.index("def claim")]
        self.assertIn("security_holds.assert_clear(cur, job.get('approvedBy'), authorized_at=job.get('approvedAt'))", approved)


class Migration(unittest.TestCase):
    SQL = re.sub(r"--[^\n]*", "", (ROOT / "migrations" / "postriff" / "121_rapv2_account_holds.sql").read_text()).lower()

    def test_server_only_and_monotonic(self):
        sql = self.SQL
        self.assertIn("alter table public.pr_security_account_controls force row level security", sql)
        self.assertIn("revoke all on public.pr_security_account_controls from public, anon, authenticated", sql)
        self.assertIn("grant select on public.pr_security_account_controls to service_role", sql)
        self.assertNotIn("to authenticated", sql.replace("from public, anon, authenticated", ""))
        self.assertIn("new.hold_epoch <> old.hold_epoch + 1", sql)
        self.assertIn("before insert or update or delete on public.pr_security_account_controls", sql)
        self.assertIn("hold_epoch = c.hold_epoch + 1", sql)
        self.assertIn("revoke all on function public.pr_security_set_hold(uuid, boolean, text) from public, anon, authenticated", sql)
        self.assertIn("delete from public.pr_security_account_controls where user_id = p_user", sql)

    def test_the_harness_applies_it(self):
        self.assertIn("121_rapv2_account_holds.sql", (ROOT / "tests" / "phase2" / "rls.sql").read_text())


if __name__ == "__main__":
    unittest.main()
