"""Synthetic Discord fixtures must not introduce plaintext secret literals.

Use the same pinned offline detect-secrets engine as the repo-wide release gate;
never exempt an entire test file or print credential matches.
"""
import unittest
from pathlib import Path
from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    "tests/test_discord_multimode.py",
    "tests/test_discord_personal_account_contract.py",
)


class DiscordFixtureSecretScanTests(unittest.TestCase):
    def test_discord_synthetic_test_fixtures_have_no_unreviewed_secret_literals(self):
        findings = {}
        with default_settings():
            for relative in FIXTURES:
                collection = SecretsCollection()
                collection.scan_file(str(ROOT / relative))
                for matches in collection.json().values():
                    if matches:
                        findings[relative] = [(item["line_number"], item["type"]) for item in matches]
        self.assertEqual(findings, {}, "Secret scanner flagged synthetic Discord fixtures; remove literal credentials, not scanner rules.")


if __name__ == "__main__":
    unittest.main()
