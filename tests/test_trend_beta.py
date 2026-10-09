"""Legacy strict trend_beta stays byte-compatible; readiness is a sibling key."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2 import feature_readiness as R
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.growth.trends import beta
from postriff_phase2.ideas import IdeasService

WID = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000003"
BETA_KEYS = {"state", "radar_available", "acquisition", "metric_reads_enabled", "follower_conversion"}
ON = {"RAFII_TREND_" + k + "_ENABLED": "1" for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")}
SELF_SERVE = {**ON, "RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "3"}


class EnrollmentCursor:
    """Answers the enrollment/readiness reads only. Writes fail the test."""

    def __init__(self, enrolled=None, *, scopes=(), policy=False, projections=False):
        self.enrolled, self.scopes, self.policy, self.projections = enrolled, list(scopes), policy, projections
        self.queries, self.result = [], []

    def execute(self, sql, args=()):
        q = " ".join(sql.split())
        self.queries.append(q)
        if not q.startswith(("SELECT", "SAVEPOINT", "RELEASE", "ROLLBACK TO")):
            raise AssertionError("status wrote: " + q)
        self.result = []
        if q.startswith("SELECT to_regclass"):
            self.result = [(True,)]
        elif "FROM public.pr_feature_enrollments WHERE workspace_id" in q:
            self.result = [(self.enrolled,)] if self.enrolled else []
        elif "count(*) FROM public.pr_feature_enrollments" in q:
            self.result = [(0,)]
        elif "FROM public.pr_trend_scopes s" in q:
            self.result = [(s,) for s in self.scopes]
        elif "FROM public.pr_trend_source_policies p" in q:
            self.result = [(self.policy,)]
        elif "FROM public.pr_trend_projections p" in q:
            self.result = [(self.projections,)]
        elif "pr_trend_source_health" in q or "pr_trend_ingestion_batches" in q:
            self.result = []

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class BetaStatusCompatibility(unittest.TestCase):
    def test_keys_and_domains_are_frozen(self):
        for values in ({}, ON, {**ON, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID}):
            for cur in (None, EnrollmentCursor()):
                result = beta.status(WID, values, metric_reads_enabled=False, cur=cur)
                self.assertEqual(set(result), BETA_KEYS)
                self.assertIn(result["state"], ("feature_off", "workspace_not_allowlisted", "stored_radar"))
                self.assertIn(result["acquisition"], ("none", "unverified"))

    def test_enrolled_workspace_opens_page_but_gets_no_egress(self):
        values = {**SELF_SERVE, "RAFII_TREND_PROVIDER_OPERATIONS_ENABLED": "1",
                  "RAFII_TREND_ALLOWED_OPERATIONS": "bluesky:live_sample"}
        enrolled = beta.status(WID, values, metric_reads_enabled=False, cur=EnrollmentCursor("active"))
        self.assertEqual((enrolled["state"], enrolled["radar_available"], enrolled["acquisition"]), ("stored_radar", True, "none"))
        # Without the cursor the legacy env-only answer is unchanged.
        self.assertEqual(beta.status(WID, values, metric_reads_enabled=False)["state"], "workspace_not_allowlisted")
        revoked = beta.status(WID, values, metric_reads_enabled=False, cur=EnrollmentCursor("revoked"))
        self.assertEqual((revoked["state"], revoked["radar_available"]), ("workspace_not_allowlisted", False))
        # Kill switch off: enrollment no longer admits (cohort rollback without a DB write).
        paused = beta.status(WID, ON, metric_reads_enabled=False, cur=EnrollmentCursor("active"))
        self.assertFalse(paused["radar_available"])
        allowlisted = beta.status(WID, {**values, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID}, metric_reads_enabled=False, cur=EnrollmentCursor())
        self.assertEqual((allowlisted["radar_available"], allowlisted["acquisition"]), (True, "unverified"))


class Repository:
    def __init__(self, cursor, role="owner"):
        self.cursor, self.role = cursor, role
        self.state = initial_phase2_state(WID, ACTOR, "Fixture", "studio", 1800000000)
        self.effects = []
        self.calls = []

    @contextmanager
    def transaction(self, token, wid, *, allow_deleting=False):
        self.calls.append(allow_deleting)
        if token != "session" or wid != WID:
            raise AlphaError("Workspace unavailable.", 403)
        yield self.cursor, (1, self.state, self.role, False, False, False, False), ACTOR


def coworker(cursor, values, role="owner"):
    repo = Repository(cursor, role)
    hosted = SimpleNamespace(repository=repo, connection_factory=lambda: None,
                             ideas=SimpleNamespace(_state=IdeasService._state, _member=IdeasService._member))
    return CoworkerService(hosted, values=values, clock=lambda: 1800000000), repo


class CoworkerStatusReadiness(unittest.TestCase):
    def test_sibling_readiness_and_unchanged_beta(self):
        service, repo = coworker(EnrollmentCursor(), SELF_SERVE)
        status = service.status(WID, "session")
        self.assertEqual(set(status["trend_beta"]), BETA_KEYS)
        self.assertEqual(status["trend_beta"]["state"], "workspace_not_allowlisted")
        R.validate(status["trend_readiness"])
        self.assertEqual(status["trend_readiness"]["state"], "setup_required")
        self.assertEqual(status["trend_readiness"]["nextStep"], {"kind": "consent", "href": "/app/trends#enroll"})
        self.assertEqual(repo.calls, [True], "one transaction, deletion-pending owners can still read status")

    def test_non_owner_is_routed_to_owner_and_flags_off_is_feature_disabled(self):
        service, _ = coworker(EnrollmentCursor(), SELF_SERVE, role="editor")
        self.assertEqual(service.status(WID, "session")["trend_readiness"]["nextStep"], {"kind": "contact_owner"})
        service, _ = coworker(EnrollmentCursor(), {})
        readiness = service.status(WID, "session")["trend_readiness"]
        self.assertEqual((readiness["state"], readiness["reasonCodes"]), ("feature_disabled", ["trends_off"]))

    def test_enrolled_without_shared_rights_is_source_rights_pending(self):
        service, _ = coworker(EnrollmentCursor("active"), SELF_SERVE)
        status = service.status(WID, "session")
        self.assertTrue(status["trend_beta"]["radar_available"])
        self.assertEqual(status["trend_readiness"]["reasonCodes"], ["source_rights_pending"])

    def test_foreign_workspace_is_refused_before_any_readiness(self):
        cursor = EnrollmentCursor()
        service, _ = coworker(cursor, SELF_SERVE)
        with self.assertRaises(AlphaError):
            service.status("00000000-0000-4000-8000-000000000009", "session")
        self.assertEqual(cursor.queries, [])


if __name__ == "__main__":
    unittest.main()
