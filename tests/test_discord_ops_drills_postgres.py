"""H-07 isolated drills as tests (tests/discord_ops_drills.py), plus an offline check of the phone runbook's statements.

The drills start their own disposable PostgreSQL (POSTRIFF_PG_BIN) with a mock Discord and never read a credential or
reach a network except 127.0.0.1. They take about four minutes (one drill keeps a request budget saturated for a
minute) and are skipped where PostgreSQL is not available or under the synthetic transport fence.
"""
import hashlib
import re
import unittest

import discord_lane_fixture as F
import discord_ops_drills as drills


class RunbookStatements(unittest.TestCase):
    def test_the_runbook_carries_the_drilled_statements(self):
        statements = drills.runbook_statements()
        self.assertEqual(set(statements), {'HOLD_ON', 'HOLD_OFF', 'HOLD_READBACK', 'HOLD_INSERT', 'DRAIN_CHECK'})
        body = {name: ' '.join(line for line in text.splitlines() if not line.startswith('--')).strip()
                for name, text in statements.items()}
        # The same statement RUNBOOK-INCIDENT step 2 and docs/w02/AS-BUILT.md give, on the coordinator's policy row.
        self.assertEqual(body['HOLD_ON'], "UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy';")
        self.assertEqual(body['HOLD_OFF'], "UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE kind = 'policy';")
        for name in ('HOLD_READBACK', 'DRAIN_CHECK'):
            self.assertIsNone(re.search(r'\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP)\b', body[name]), name)

    def test_the_fallback_insert_names_the_coordinators_own_policy_row(self):
        statement = drills.runbook_statements()['HOLD_INSERT']
        self.assertIn("'00:' || encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex')", statement)
        budget = drills.SharedPostgresBudget(lambda: None, F.APP)
        self.assertEqual(budget.application_key, hashlib.sha256(F.APP.encode('utf-8')).hexdigest())
        self.assertIn('manual_hold = true', statement)


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class IsolatedDrills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = drills.Lab()

    @classmethod
    def tearDownClass(cls):
        cls.lab.close()

    def drill(self, function):
        signal = drills.security_signals.DenialSignal()
        with drills.patch.object(drills.security_signals, 'SIGNAL', signal):
            record = function(self.lab)
        failed = [check for check in record['checks'] if not check['pass']]
        self.assertEqual(failed, [], record['id'])
        self.assertEqual(record['result'], 'PASS')

    def test_d0_baseline(self):
        self.drill(drills.d0_baseline)

    def test_d1_backlog(self):
        self.drill(drills.d1_backlog)

    def test_d2_delivery(self):
        self.drill(drills.d2_delivery)

    def test_d3_rate_limit(self):
        self.drill(drills.d3_rate_limit)

    def test_d4_silent_halt(self):
        self.drill(drills.d4_silent_halt)

    def test_d5_cross_tenant(self):
        self.drill(drills.d5_cross_tenant)

    def test_d6_config_drift(self):
        self.drill(drills.d6_config_drift)

    def test_o1_hold(self):
        self.drill(drills.o1_hold)

    def test_o2_rollback_order(self):
        self.drill(drills.o2_rollback_order)


if __name__ == '__main__':
    unittest.main()
