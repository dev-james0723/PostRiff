"""LinkedIn scheduling must survive merges: production lost its worker cron once (2026-10-14) when a release
was built from a branch without it, and scheduled LinkedIn posts silently stopped."""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LinkedInReleaseGuardTests(unittest.TestCase):
    def test_vercel_schedules_the_linkedin_worker(self):
        crons = {c["path"]: c["schedule"] for c in json.loads((ROOT / "vercel.json").read_text())["crons"]}
        self.assertEqual(crons.get("/api/cron/worker"), "* * * * *")
        self.assertEqual(crons.get("/api/cron/linkedin/worker"), "* * * * *")

    def test_the_app_serves_the_linkedin_worker_route(self):
        self.assertIn("path == '/api/cron/linkedin/worker'", (ROOT / "src/postriff_phase2/hosted_app.py").read_text())

    def test_linkedin_member_publishing_is_wired(self):
        source = (ROOT / "src/postriff_phase2/providers.py").read_text()
        self.assertIn('"publish": ["openid", "profile", "w_member_social"]', source)
        self.assertIn("member_publishing_approved", (ROOT / "src/postriff_phase2/hosted_app.py").read_text())


if __name__ == "__main__":
    unittest.main()
