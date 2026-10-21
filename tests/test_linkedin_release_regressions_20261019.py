"""Regressions first observed in the October 19 integration candidate; no live transport."""
import unittest
from unittest.mock import Mock
from postriff_phase2.connection_health import access
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import invoke

class LinkedInReleaseRegressions(unittest.TestCase):
    def test_expired_stored_verified_nonrefreshable_grant_is_not_active(self):
        row = {"connectionState": "publish_verified", "expiresAt": 100, "refreshSupported": False}
        self.assertEqual(access(row, 101)["status"], "expired")

    def test_exact_expiry_boundary_is_expired(self):
        row = {"connectionState": "read_verified", "expiresAt": 100, "refreshSupported": False}
        self.assertEqual(access(row, 100)["status"], "expired")

    def test_dedicated_cron_auth_precedes_runtime(self):
        app = HostedApplication(cron_secret="synthetic-cron-secret-0000000000")
        app._runtime = Mock(side_effect=AssertionError("Unauthenticated LinkedIn cron initialized runtime"))
        for value in ("", "Bearer wrong-secret", "Bearer ordinary-user-session"):
            with self.subTest(authorization=value):
                status, _, _ = invoke(app, "GET", "/api/cron/linkedin/worker", {}, {"Authorization": value})
                self.assertEqual(status, 401)
        app._runtime.assert_not_called()
