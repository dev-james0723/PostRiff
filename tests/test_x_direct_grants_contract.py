"""Offline guard for the X direct operations Data API grant contract.

Run: python3 -m unittest tests.test_x_direct_grants_contract -v
This test does not access a database, browser, production, or paid services.
The SQL role-level test is tests/phase2/x_direct_grants_contract.sql.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/postriff/132_x_direct_operations.sql"


class DirectXGrantContractTests(unittest.TestCase):
    def setUp(self):
        self.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_explicit_grants_survive_secure_defaults(self):
        # PostgreSQL stores old inherited grants on a new table until revoked.
        self.assertRegex(
            self.sql,
            r"revoke\s+all\s+on\s+public\.pr_x_direct_operations\s+from\s+service_role\s*;",
        )
        self.assertRegex(
            self.sql,
            r"grant\s+select\s*,\s*insert\s*,\s*update\s+on\s+public\.pr_x_direct_operations\s+to\s+service_role\s*;",
        )

    def test_private_client_roles_and_forced_rls(self):
        self.assertIn(
            "alter table public.pr_x_direct_operations force row level security;",
            self.sql,
        )
        self.assertRegex(
            self.sql,
            r"revoke\s+all\s+on\s+public\.pr_x_direct_operations\s+from\s+public\s*,\s*anon\s*,\s*authenticated\s*;",
        )

    def test_no_grant_all_or_destructive_service_role_grant(self):
        self.assertNotRegex(
            self.sql,
            r"grant\s+all\s+on\s+public\.pr_x_direct_operations",
        )
        self.assertNotRegex(
            self.sql,
            r"grant\s+[^;]*(?:delete|truncate|references|trigger)[^;]*"
            r"on\s+public\.pr_x_direct_operations\s+to\s+service_role",
        )

    def test_revoke_precedes_grant(self):
        revoke = self.sql.index(
            "revoke all on public.pr_x_direct_operations from service_role;"
        )
        grant = self.sql.index(
            "grant select, insert, update on public.pr_x_direct_operations to service_role;"
        )
        self.assertLess(revoke, grant)


if __name__ == "__main__":
    unittest.main()
