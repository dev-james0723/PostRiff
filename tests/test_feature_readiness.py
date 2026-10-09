import unittest
from datetime import datetime, timezone

from postriff_phase2 import feature_readiness as fr


class ReadinessContract(unittest.TestCase):
    def test_no_blockers_is_ready_with_exact_keys(self):
        payload = fr.resolve()
        self.assertEqual(set(payload), set(fr.KEYS))
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["reasonCodes"], [])
        self.assertTrue(payload["canRead"] and payload["canRun"])
        self.assertIsNone(payload["nextStep"])
        fr.validate(payload)

    def test_precedence_picks_most_blocking_state_and_keeps_all_reasons(self):
        payload = fr.resolve([
            fr.blocker("insufficient_data", "no_projections_yet", blocks_run=False),
            fr.blocker("setup_required", "enrollment_required", next_kind="consent", href="/app/trends#enroll"),
            fr.blocker("feature_disabled", "trends_off", blocks_read=True),
        ])
        self.assertEqual(payload["state"], "feature_disabled")
        self.assertEqual(payload["reasonCodes"], ["trends_off", "enrollment_required", "no_projections_yet"])
        self.assertFalse(payload["canRead"])
        self.assertFalse(payload["canRun"])
        # The step shown belongs to the winning state only; disabled offers none.
        self.assertIsNone(payload["nextStep"])

    def test_precedence_order_is_fixed(self):
        self.assertEqual(fr.PRECEDENCE, ("feature_disabled", "unsupported", "not_entitled", "setup_required",
                                         "temporarily_unavailable", "insufficient_data", "ready"))

    def test_insufficient_data_can_still_read(self):
        payload = fr.resolve([fr.blocker("insufficient_data", "no_verified_publications", blocks_run=False)])
        self.assertTrue(payload["canRead"])
        self.assertTrue(payload["canRun"])

    def test_outage_never_asks_for_setup(self):
        with self.assertRaises(fr.ReadinessError):
            fr.blocker("temporarily_unavailable", "provider_unavailable", next_kind="connect", href="/app/channels")
        ok = fr.resolve([fr.blocker("temporarily_unavailable", "provider_unavailable", next_kind="wait")],
                        last_successful_read_at=datetime(2026, 10, 5, 13, 45, tzinfo=timezone.utc))
        self.assertEqual(ok["nextStep"], {"kind": "wait"})
        self.assertEqual(ok["lastSuccessfulReadAt"], "2026-10-05T13:45:00Z")
        bad = dict(ok, nextStep={"kind": "connect", "href": "/app/channels"})
        with self.assertRaises(fr.ReadinessError):
            fr.validate(bad)

    def test_rejects_external_or_malformed_hrefs_and_reasons(self):
        for href in ("https://evil.example/app", "//evil.example", "/api/workspaces", "/app/../x", "javascript:alert(1)"):
            with self.assertRaises(fr.ReadinessError, msg=href):
                fr.blocker("setup_required", "enrollment_required", next_kind="consent", href=href)
        for reason in ("", "Has Spaces", "x", "provider said: 500", "a" * 80):
            with self.assertRaises(fr.ReadinessError, msg=reason):
                fr.blocker("setup_required", reason)
        with self.assertRaises(fr.ReadinessError):
            fr.blocker("ready", "fine")
        with self.assertRaises(fr.ReadinessError):
            fr.blocker("setup_required", "enrollment_required", next_kind="email_james")

    def test_owner_steps_route_everyone_else_to_the_owner(self):
        self.assertEqual(fr.owner_step("consent", "/app/growth#consent", role="owner"),
                         {"next_kind": "consent", "href": "/app/growth#consent"})
        for role in ("admin", "editor", "approver", "viewer", None):
            self.assertEqual(fr.owner_step("consent", "/app/growth#consent", role=role),
                             {"next_kind": "contact_owner", "href": None})

    def test_validate_fails_closed(self):
        good = fr.resolve()
        for broken in (None, [], dict(good, extra=1), dict(good, state="maybe"), dict(good, canRead="yes"),
                       dict(good, canRun=True, canRead=False), dict(good, reasonCodes=["x y"]),
                       dict(good, reasonCodes=["growth_off"]), dict(good, lastSuccessfulReadAt="2026-10-09"),
                       dict(good, nextStep={"kind": "retry", "href": "https://x"})):
            with self.assertRaises(fr.ReadinessError, msg=repr(broken)[:80]):
                fr.validate(broken)

    def test_reasons_are_bounded(self):
        blockers = [fr.blocker("insufficient_data", "reason_%02d" % i, blocks_run=False) for i in range(12)]
        self.assertEqual(len(fr.resolve(blockers)["reasonCodes"]), fr.MAX_REASONS)


if __name__ == "__main__":
    unittest.main()
