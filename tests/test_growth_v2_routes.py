"""The program route table: lazy slice modules, feature_disabled when a slice is absent, isolated cron steps."""
import sys
import time
import types
import unittest
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import growth_v2_routes as routes


class RoutesTest(unittest.TestCase):
    def test_handles_only_reserved_workspace_resources(self):
        self.assertTrue(routes.handles(["api", "workspaces", "w1", "results"]))
        self.assertTrue(routes.handles(["api", "workspaces", "w1", "visual-packs", "p1"]))
        self.assertFalse(routes.handles(["api", "workspaces", "w1", "growth"]))
        self.assertFalse(routes.handles(["api", "workspaces", "w1"]))
        self.assertFalse(routes.handles(["api", "results", "webhook", "c1"]))

    def test_absent_slice_answers_feature_disabled(self):
        with mock.patch.dict(routes.RESOURCES, {"series": "postriff_phase2.series_that_does_not_exist.http"}):
            with self.assertRaises(AlphaError) as caught:
                routes.handle(None, {}, None, None, "t", "GET", ["api", "workspaces", "w1", "series"])
        self.assertEqual(caught.exception.code, "feature_disabled")
        self.assertEqual(caught.exception.status, 404)

    def test_feature_state_is_off_unless_each_slice_says_on(self):
        keys = set(routes.FEATURES)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(routes.feature_state(), dict.fromkeys(keys, False))
        on = {"RAFII_SERIES_ENABLED": "1", "RAFII_FIRST_WEEK_ENABLED": "1"}
        with mock.patch.dict("os.environ", on, clear=True):
            state = routes.feature_state()
        self.assertTrue(state["series"])
        self.assertFalse(state["firstWeek"], "the first week needs the Weekly Operator too")
        with mock.patch.dict(routes.FEATURES, {"series": ("postriff_phase2.series_that_does_not_exist.model", "enabled")}), \
                mock.patch.dict("os.environ", on, clear=True):
            self.assertFalse(routes.feature_state()["series"], "a missing slice is off, never guessed on")

    def test_workspace_feature_state_needs_membership_and_public_shows_only_first_week(self):
        self.assertTrue(routes.handles(["api", "workspaces", "w1", "growth-features"]))
        self.assertFalse(routes.handles(["api", "workspaces", "w1", "growth-features", "x"]))
        sent = []
        app = types.SimpleNamespace(_json=lambda start, status, body: sent.append((status, body)) or body)
        member = types.SimpleNamespace(allows=lambda level: True)

        class Repo:
            def transaction(self, token, workspace_id):
                class Tx:
                    def __enter__(self_inner):
                        return (None, ("rev", "state"), "principal")
                    def __exit__(self_inner, *exc):
                        return False
                return Tx()
        hosted = types.SimpleNamespace(repository=Repo())
        with mock.patch("postriff_phase2.hosted._membership", return_value=member) as membership, \
                mock.patch("postriff_phase2.permissions.require") as require:
            routes.handle(app, {}, None, hosted, "t", "GET", ["api", "workspaces", "w1", "growth-features"])
        membership.assert_called_once()
        require.assert_called_once_with(member, "read")
        self.assertEqual(sent[-1][0], 200)
        self.assertEqual(set(sent[-1][1]["features"]), set(routes.FEATURES))
        with self.assertRaises(AlphaError):
            routes.handle(app, {}, None, hosted, "t", "POST", ["api", "workspaces", "w1", "growth-features"])
        routes.public(app, {}, None, "GET", "/api/growth-features")
        self.assertEqual(set(sent[-1][1]["features"]), {"firstWeek"})

    def test_public_ignores_unrelated_paths_without_importing(self):
        with mock.patch.object(routes, "_module", side_effect=AssertionError("must not import")):
            self.assertIsNone(routes.public(None, {}, None, "GET", "/api/catalog"))

    def test_cron_isolates_failures_and_respects_deadline(self):
        ok = types.SimpleNamespace(tick=lambda hosted, deadline: {"status": "ok"})
        boom = types.SimpleNamespace(tick=lambda hosted, deadline: (_ for _ in ()).throw(RuntimeError("secret detail")))
        fake = {"postriff_phase2.alpha.jobs": ok, "postriff_phase2.beta.jobs": boom}
        with mock.patch.object(routes, "CRON", tuple(fake)), mock.patch.object(routes, "_module", side_effect=fake.get):
            summary = routes.cron(object(), time.monotonic() + 5)
            self.assertEqual(summary["alpha"], {"status": "ok"})
            self.assertEqual(summary["beta"], {"status": "unavailable", "reason": "RuntimeError"})
            self.assertNotIn("secret detail", repr(summary))
            late = routes.cron(object(), time.monotonic() - 1)
            self.assertEqual(late["alpha"], {"status": "deferred"})

    def test_missing_third_party_dependency_is_not_hidden(self):
        def fake_import(name):
            raise ModuleNotFoundError("No module named 'pypdf'", name="pypdf")
        with mock.patch("importlib.import_module", side_effect=fake_import):
            with self.assertRaises(ModuleNotFoundError):
                routes._module("postriff_phase2.source_uploads.http")
        self.assertNotIn("postriff_phase2.source_uploads.http", sys.modules)


if __name__ == "__main__":
    unittest.main()
