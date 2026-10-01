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
