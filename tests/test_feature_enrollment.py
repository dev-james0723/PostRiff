import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2 import feature_enrollment as fe
from postriff_phase2.growth.trends import admission

ONE = "11111111-1111-4111-8111-111111111111"
TWO = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"


class FakeCursor:
    """Answers only the reads admission needs; any write is a test failure."""

    def __init__(self, table=True, active=()):
        self.table, self.active, self.sql, self._next = table, set(active), [], None

    def execute(self, sql, params=()):
        self.sql.append(sql)
        lowered = " ".join(sql.split()).lower()
        if lowered.startswith(("insert", "update", "delete")) or "advisory" in lowered:
            raise AssertionError("unexpected write: " + sql[:60])
        if "to_regclass" in lowered:
            self._next = [(self.table,)]
        elif lowered.startswith("select status"):
            self._next = [("active",)] if (params[0], params[1]) in self.active else []
        elif lowered.startswith("select workspace_id::text"):
            self._next = sorted((w,) for w, f in self.active if f == params[0])
        elif lowered.startswith("select count(*)"):
            self._next = [(sum(1 for _, f in self.active if f == params[0]),)]
        else:
            raise AssertionError("unexpected sql: " + sql[:60])
        return self

    def fetchone(self):
        return self._next[0] if self._next else None

    def fetchall(self):
        return list(self._next or [])


OPEN = {"RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "10",
        "RAFII_TREND_INTELLIGENCE_ENABLED": "1"}


class CohortSwitches(unittest.TestCase):
    def test_cap_has_no_wildcard_and_invalid_means_zero(self):
        for raw in ("", "*", "-1", "ten", "1.5", " ", "all"):
            self.assertEqual(fe.cohort_cap("trend_radar", {"RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": raw}), 0, raw)
        self.assertEqual(fe.cohort_cap("trend_radar", {"RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "25"}), 25)
        self.assertEqual(fe.cohort_cap("trend_radar", {"RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "999999"}), fe.MAX_COHORT)

    def test_switch_is_off_unless_explicitly_on(self):
        self.assertFalse(fe.self_serve_open("trend_radar", {}))
        self.assertFalse(fe.self_serve_open("growth_measurement", {"POSTRIFF_METRIC_SELF_SERVE_ENABLED": "0"}))
        self.assertTrue(fe.self_serve_open("growth_measurement", {"POSTRIFF_METRIC_SELF_SERVE_ENABLED": "true"}))

    def test_denylist_ignores_garbage_and_denies_invalid_ids(self):
        values = {fe.DENYLIST: f"nope,{ONE}, ,*"}
        self.assertTrue(fe.denied(ONE, values))
        self.assertFalse(fe.denied(TWO, values))
        self.assertTrue(fe.denied("not-a-uuid", {}))

    def test_unknown_feature_is_refused(self):
        with self.assertRaises(KeyError):
            fe.self_serve_open("radar", {})


class AdmissionWithoutWrites(unittest.TestCase):
    def test_enrolled_workspace_is_read_admitted_but_never_egress(self):
        cur = FakeCursor(active={(ONE, "trend_radar")})
        self.assertTrue(admission.admitted(cur, ONE, OPEN))
        self.assertEqual(admission.admission_source(cur, ONE, OPEN), "self_serve")
        self.assertFalse(admission.egress_allowed(ONE, OPEN))
        self.assertFalse(admission.admitted(cur, TWO, OPEN))

    def test_legacy_allowlist_keeps_working_and_owns_egress(self):
        values = {**OPEN, "RAFII_TREND_SELF_SERVE_ENABLED": "0", "RAFII_TREND_WORKSPACE_ALLOWLIST": TWO}
        cur = FakeCursor()
        self.assertTrue(admission.admitted(cur, TWO, values))
        self.assertTrue(admission.egress_allowed(TWO, values))
        self.assertEqual(admission.admission_source(cur, TWO, values), "reviewed_cohort")

    def test_kill_switches(self):
        cur = FakeCursor(active={(ONE, "trend_radar")})
        self.assertFalse(admission.admitted(cur, ONE, {**OPEN, "RAFII_TREND_INTELLIGENCE_ENABLED": "0"}))
        self.assertFalse(admission.admitted(cur, ONE, {**OPEN, "RAFII_TREND_SELF_SERVE_ENABLED": "0"}))
        self.assertFalse(admission.admitted(cur, ONE, {**OPEN, fe.DENYLIST: ONE}))

    def test_missing_table_means_not_enrolled_not_an_error(self):
        cur = FakeCursor(table=False)
        self.assertFalse(admission.admitted(cur, ONE, OPEN))
        self.assertIsNone(fe.status(cur, ONE, "trend_radar"))
        self.assertEqual(fe.admitted_workspaces(cur, "trend_radar", OPEN), [])
        self.assertEqual(fe.eligibility(cur, ONE, "trend_radar", OPEN)["reason"], "enrollment_unavailable")

    def test_eligibility_reasons(self):
        self.assertEqual(fe.eligibility(FakeCursor(), ONE, "trend_radar", {})["reason"], "self_serve_paused")
        self.assertEqual(fe.eligibility(FakeCursor(), ONE, "trend_radar", OPEN)["reason"], "enrollment_open")
        full = {**OPEN, "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "1"}
        self.assertEqual(fe.eligibility(FakeCursor(active={(TWO, "trend_radar")}), ONE, "trend_radar", full)["reason"], "cohort_full")
        self.assertEqual(fe.eligibility(FakeCursor(active={(ONE, "trend_radar")}), ONE, "trend_radar", full)["reason"], "already_enrolled")

    def test_role_and_switch_refusals_happen_before_any_sql(self):
        for kwargs, code in (({"role": "editor", "values": OPEN}, "owner_required"),
                             ({"role": "owner", "values": {}}, "self_serve_paused"),
                             ({"role": "owner", "values": {**OPEN, fe.DENYLIST: ONE}}, "workspace_not_eligible")):
            cur = FakeCursor()
            with self.assertRaises(AlphaError) as caught:
                fe.enroll(cur, ONE, "trend_radar", actor=ACTOR, **kwargs)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(cur.sql, [])
        cur = FakeCursor()
        with self.assertRaises(AlphaError) as caught:
            fe.unenroll(cur, ONE, "trend_radar", actor=ACTOR, role="viewer")
        self.assertEqual(caught.exception.code, "owner_required")


if __name__ == "__main__":
    unittest.main()
