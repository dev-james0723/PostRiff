"""Production-baseline preservation and no-standing-authority Bluesky release fence.

No provider network calls, database writes, or real credentials.
"""
import json
from pathlib import Path
import unittest

from postriff_phase2.hosted_worker import PostgresWorker, _bluesky_automation_human_approved
from postriff_phase2.atproto_oauth import BlueskyProvider


class NoDatabaseCursor:
    def execute(self, *_a, **_k):
        raise AssertionError("Legacy Bluesky standing authority must be rejected before SQL")

    def fetchone(self):
        raise AssertionError("Legacy Bluesky standing authority must be rejected before SQL")


class ProductionPortTests(unittest.TestCase):
    def test_bluesky_legacy_standing_jobs_fail_before_database_or_provider(self):
        for receipt in (
            {"approvedVia": "owner_preauthorization"},
            {"approvedVia": "auto"},
            {},
            None,
            "human",
        ):
            with self.subTest(receipt=receipt):
                job = {"manifest": {"platform": "Bluesky"}, "automation": receipt}
                self.assertFalse(_bluesky_automation_human_approved(job))
                # Passing 'object()' as self fails if any other worker method or I/O runs.
                self.assertFalse(PostgresWorker._approved(object(), NoDatabaseCursor(), "workspace", {}, job))

    def test_bluesky_manual_jobs_and_other_platforms_keep_existing_gates(self):
        self.assertTrue(_bluesky_automation_human_approved({"manifest": {"platform": "Bluesky"}}))
        self.assertTrue(_bluesky_automation_human_approved(
            {"manifest": {"platform": "Bluesky"}, "automation": {"approvedVia": "human"}}
        ))
        self.assertTrue(_bluesky_automation_human_approved(
            {"manifest": {"platform": "LinkedIn"}, "automation": {"approvedVia": "owner_preauthorization"}}
        ))

    def test_existing_production_oauth_client_origin_remains_unchanged(self):
        # This is a synthetic signing JWK; no Production private key is read.
        key = {"kty": "EC", "crv": "P-256", "kid": "fixture"}
        prod_origin = "https://postriff-phase2-private.vercel.app"
        provider = BlueskyProvider(key, "https://rafii.io", client_origin=prod_origin,
                                   transport=lambda *args: (_ for _ in ()).throw(
                                       AssertionError("No provider calls allowed")))
        metadata = provider.client_metadata()
        self.assertEqual(metadata["client_id"], prod_origin + BlueskyProvider.METADATA_PATH)
        self.assertEqual(metadata["redirect_uris"],
                         [prod_origin + "/api/oauth/bluesky/callback"])
        self.assertEqual(metadata["jwks_uri"], prod_origin + BlueskyProvider.JWKS_PATH)
        self.assertNotIn(BlueskyProvider.LEGACY_SCOPE, provider.SCOPES["publish"])
        self.assertEqual(provider.SCOPES["identity"], ["atproto"])

    def test_new_release_branch_cannot_automatically_deploy(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
        d = config["git"]["deploymentEnabled"]
        self.assertIs(d["codex/rafii-bluesky-prod-20261013"], False)
        self.assertIs(d["codex/rafii-bluesky-p0-20261013"], False)
        self.assertIs(d["codex/rafii-linkedin-production-release-20261012"], False)


if __name__ == "__main__":
    unittest.main()
