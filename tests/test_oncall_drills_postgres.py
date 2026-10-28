"""H-07 on-call drill rows (tests/oncall_drills.py) as tests, on a disposable PostgreSQL 16 with migration 140 applied
twice, the Discord schema for the end-to-end and hold rows, and fake push, e-mail and phone providers.

They prove the engine's decisions and the Postgres store's guarantees, not delivery to a person (docs/ops/H07-EVIDENCE.md).
Skipped where PostgreSQL is not available or under the synthetic transport fence.
"""
import unittest

import discord_lane_fixture as F
import oncall_drills as drills


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class OnCallDrillRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = drills.Lab()

    @classmethod
    def tearDownClass(cls):
        cls.lab.close()

    def rows(self, function):
        result = function(self.lab)
        for record in result if isinstance(result, list) else [result]:
            with self.subTest(row=record['id']):
                self.assertEqual([c for c in record['checks'] if not c['pass']], [], record['id'])
                self.assertEqual(record['result'], 'PASS')

    def test_r01_roster(self):
        self.rows(drills.r01_roster)

    def test_r02_r03_r04_p0_chain(self):
        self.rows(drills.r02_r03_r04_p0)

    def test_r05_p1(self):
        self.rows(drills.r05_p1)

    def test_r06_p2(self):
        self.rows(drills.r06_p2)

    def test_r07_acknowledgement(self):
        self.rows(drills.r07_ack)

    def test_r08_delivery_fallback(self):
        self.rows(drills.r08_delivery)

    def test_r09_dedupe(self):
        self.rows(drills.r09_dedupe)

    def test_r10_suppression(self):
        self.rows(drills.r10_suppression)

    def test_r11_storm(self):
        self.rows(drills.r11_storm)

    def test_r12_audit_trail_in_postgres(self):
        self.rows(drills.r12_audit)

    def test_r13_heartbeat(self):
        self.rows(drills.r13_heartbeat)

    def test_r14_end_to_end(self):
        self.rows(drills.r14_end_to_end)

    def test_r15_auto_hold_owner_decision(self):
        self.rows(drills.r15_auto_hold)


if __name__ == '__main__':
    unittest.main()
