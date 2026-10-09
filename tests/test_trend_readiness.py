"""Trends readiness (FeatureReadiness): every branch, scope isolation and no writes."""
import unittest
from datetime import datetime, timezone

from postriff_phase2 import feature_readiness as R
from postriff_phase2.growth.trends import readiness

WID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SHARED = "shared:rafii-trend-corpus"
ON = {"RAFII_TREND_INTELLIGENCE_ENABLED": "1", "RAFII_TREND_RADAR_ENABLED": "1",
      "RAFII_TREND_TRUST_RECEIPTS_ENABLED": "1"}
READ_ONLY = ("SELECT", "SAVEPOINT", "RELEASE", "ROLLBACK TO")


class Cursor:
    """Answers only the aggregate reads readiness may issue; any write fails the test."""

    def __init__(self, *, tables=True, enrolled=None, cohort=0, scopes=None, policy=True, health=(),
                 last_read=None, projections=True, fail_on=None):
        self.tables = tables
        self.enrolled = enrolled
        self.cohort = cohort
        self.scopes = scopes if scopes is not None else {WID: ["workspace:" + WID]}
        self.policy = policy
        self.health = list(health)
        self.last_read = last_read
        self.projections = projections
        self.fail_on = fail_on
        self.queries = []
        self.result = []

    def execute(self, sql, args=()):
        q = " ".join(sql.split())
        self.queries.append((q, args))
        if not q.startswith(READ_ONLY):
            raise AssertionError("readiness wrote: " + q)
        if self.fail_on and self.fail_on in q:
            raise RuntimeError("synthetic aggregate failure")
        self.result = []
        if q.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK TO")):
            return
        if q.startswith("SELECT to_regclass"):
            name = args[0] if args else q.split("'")[1]
            if name == "public.pr_feature_enrollments":
                self.result = [(self.enrolled is not None,)]
            else:
                self.result = [(self.tables is True or name.split(".")[1] in self.tables,)]
        elif "FROM public.pr_feature_enrollments WHERE workspace_id" in q:
            self.result = [(self.enrolled,)] if self.enrolled else []
        elif "count(*) FROM public.pr_feature_enrollments" in q:
            self.result = [(self.cohort,)]
        elif "FROM public.pr_trend_scopes s" in q:
            assert args == (WID, WID), "scopes are read for the caller's workspace only"
            self.result = [(s,) for s in self.scopes.get(args[0], [])]
        elif "FROM public.pr_trend_source_policies p" in q:
            self._only_own(args[0])
            self.result = [(self.policy,)]
        elif "FROM public.pr_trend_source_health" in q:
            self._only_own(args[0])
            self.result = [(h[0], h[1], h[2], h[3]) for h in self.health]
        elif "FROM public.pr_trend_ingestion_batches" in q:
            self._only_own(args[0])
            self.result = [(self.last_read,)]
        elif "FROM public.pr_trend_projections p" in q:
            self._only_own(args[0])
            self.result = [(self.projections,)]
        else:
            raise AssertionError("unexpected query: " + q)

    def _only_own(self, scopes):
        assert set(scopes) <= set(self.scopes.get(WID, [])), "aggregate left the caller's authorized scopes"

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


def ready(cur, role="owner", values=None):
    return readiness.trend_readiness(cur, WID, role=role, values=values if values is not None else {**ON, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID})


SELF_SERVE = {**ON, "RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "5"}


class TrendReadinessTests(unittest.TestCase):
    def assertState(self, payload, state, reasons, step=None):
        R.validate(payload)
        self.assertEqual(payload["state"], state)
        self.assertEqual(payload["reasonCodes"], reasons)
        self.assertEqual(payload["nextStep"], step)

    def test_flags_off_is_feature_disabled_without_any_query(self):
        cur = Cursor()
        for values in ({}, {**ON, "RAFII_TREND_RADAR_ENABLED": "0"}, {**ON, "RAFII_TREND_TRUST_RECEIPTS_ENABLED": "0"}):
            payload = ready(cur, values=values)
            self.assertState(payload, "feature_disabled", ["trends_off"])
            self.assertFalse(payload["canRead"])
        self.assertEqual(cur.queries, [])

    def test_not_admitted_open_cohort_owner_consents_others_contact_owner(self):
        cur = Cursor(enrolled="revoked", cohort=0)  # table present, this workspace not active
        owner = ready(cur, values=SELF_SERVE)
        self.assertState(owner, "setup_required", ["enrollment_required"], {"kind": "consent", "href": "/app/trends#enroll"})
        self.assertFalse(owner["canRead"])
        for role in ("admin", "editor", "approver", "viewer"):
            other = ready(Cursor(enrolled="revoked"), role=role, values=SELF_SERVE)
            self.assertState(other, "setup_required", ["enrollment_required"], {"kind": "contact_owner"})

    def test_not_admitted_paused_full_or_denied_is_not_entitled(self):
        self.assertState(ready(Cursor(enrolled="revoked"), values={**ON}), "not_entitled", ["self_serve_paused"], {"kind": "wait"})
        self.assertState(ready(Cursor(enrolled="revoked", cohort=5), values=SELF_SERVE), "not_entitled", ["cohort_full"], {"kind": "wait"})
        denied = {**SELF_SERVE, "RAFII_FEATURE_WORKSPACE_DENYLIST": WID}
        self.assertState(ready(Cursor(enrolled="revoked"), values=denied), "not_entitled", ["workspace_not_eligible"])
        # Enrollment table not applied: the switch alone cannot admit or invite anyone.
        self.assertState(ready(Cursor(enrolled=None), values=SELF_SERVE), "not_entitled", ["self_serve_paused"], {"kind": "wait"})

    def test_enrolled_workspace_without_reviewed_shared_rights_is_source_rights_pending(self):
        cur = Cursor(enrolled="active", scopes={WID: []}, policy=False)
        payload = ready(cur, values=SELF_SERVE)
        self.assertState(payload, "unsupported", ["source_rights_pending"], {"kind": "wait"})
        self.assertFalse(payload["canRead"])
        self.assertFalse(payload["canRun"])
        self.assertFalse(any("pr_trend_source_policies" in q for q, _ in cur.queries), "no scopes means no policy read")
        # A scope exists but no reviewed policy covers it.
        self.assertState(ready(Cursor(enrolled="active", policy=False), values=SELF_SERVE), "unsupported", ["source_rights_pending"], {"kind": "wait"})

    def test_all_providers_down_is_outage_with_stored_reads_and_last_batch(self):
        at = datetime(2026, 10, 5, 13, 50, tzinfo=timezone.utc)
        cur = Cursor(health=[("bluesky", "unavailable", "provider_transient", at)], last_read=at)
        payload = ready(cur)
        self.assertState(payload, "temporarily_unavailable", ["provider_unavailable"], {"kind": "wait"})
        self.assertTrue(payload["canRead"])
        self.assertEqual(payload["lastSuccessfulReadAt"], "2026-10-05T13:50:00Z")
        gap = ready(Cursor(health=[("bluesky", "gap", "cursor_gap", at)]))
        self.assertState(gap, "temporarily_unavailable", ["coverage_gap"], {"kind": "wait"})
        # One healthy provider means no outage claim.
        mixed = ready(Cursor(health=[("bluesky", "gap", "cursor_gap", at), ("web", "healthy", "ok", at)]))
        self.assertEqual(mixed["state"], "ready")
        # Outage plus no projections: outage wins, both reasons are honest.
        both = ready(Cursor(health=[("bluesky", "unavailable", "provider_transient", at)], projections=False))
        self.assertEqual(both["reasonCodes"], ["provider_unavailable", "no_projections_yet"])
        self.assertNotEqual(both["nextStep"]["kind"], "connect")

    def test_zero_valid_projections_is_insufficient_data_but_readable(self):
        payload = ready(Cursor(projections=False))
        self.assertState(payload, "insufficient_data", ["no_projections_yet"])
        self.assertTrue(payload["canRead"])

    def test_ready_and_role_controls_only_run_flag(self):
        for role, can_run in (("owner", True), ("editor", True), ("admin", False), ("viewer", False)):
            payload = ready(Cursor(), role=role)
            self.assertState(payload, "ready", [])
            self.assertTrue(payload["canRead"])
            self.assertEqual(payload["canRun"], can_run)

    def test_missing_trend_tables_report_state_not_error(self):
        payload = ready(Cursor(tables=("pr_trend_scopes",)))
        self.assertState(payload, "temporarily_unavailable", ["trends_schema_unavailable"], {"kind": "retry"})
        self.assertFalse(payload["canRead"])

    def test_optional_health_tables_missing_still_compute(self):
        payload = ready(Cursor(tables=readiness.TABLES))
        self.assertEqual(payload["state"], "ready")

    def test_aggregates_never_leave_authorized_scopes(self):
        cur = Cursor(scopes={WID: ["workspace:" + WID, SHARED], OTHER: ["workspace:" + OTHER]})
        ready(cur)
        scoped = [args for q, args in cur.queries if "ANY(%s)" in q]
        self.assertTrue(scoped)
        for args in scoped:
            self.assertEqual(sorted(args[0]), sorted(["workspace:" + WID, SHARED]))

    def test_safe_wrapper_returns_none_and_rolls_back_to_savepoint(self):
        cur = Cursor(fail_on="pr_trend_projections")
        self.assertIsNone(readiness.safe_trend_readiness(cur, WID, role="owner", values={**ON, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID}))
        self.assertTrue(any(q.startswith("ROLLBACK TO SAVEPOINT trend_readiness") for q, _ in cur.queries))
        good = readiness.safe_trend_readiness(Cursor(), WID, role="owner", values={**ON, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID})
        self.assertEqual(good["state"], "ready")


if __name__ == "__main__":
    unittest.main()
