"""RAPv2 H-1 contract, without a database: the browser session guard exists, is restrictive, cannot be called by
anon, and every later migration that lets the browser role read a table adds the same guard to it.

The behaviour itself (revoked, missing, AAL1 and deleted-account sessions read nothing) is proven against a disposable
PostgreSQL by tests/phase2/postgres_browser_session_guard.py.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "postriff"
GUARD = MIGRATIONS / "119_rapv2_browser_session_guard.sql"
BROWSER_READ = re.compile(r"grant\s+(?:all|select)\b[^;]*\bto\s+[^;]*\bauthenticated\b", re.I)


class BrowserSessionGuard(unittest.TestCase):
    def test_the_guard_checks_every_session_rule_the_hosted_api_does(self):
        sql = GUARD.read_text()
        for rule in ("pr_session_revocations", "pr_account_tombstones", "pr_mfa_enforcement", "'aal2'", "session_id"):
            self.assertIn(rule, sql)
        self.assertIn("as restrictive for select to authenticated", sql)
        self.assertIn("on storage.objects as restrictive", sql)
        self.assertIn("revoke all on function postriff_private.browser_session_ok() from public, anon", sql)
        self.assertIn("security definer set search_path = ''", sql)
        # Evaluated once per statement, not once per row.
        self.assertIn("using ((select postriff_private.browser_session_ok()))", sql)

    def test_the_harness_applies_it(self):
        self.assertIn("119_rapv2_browser_session_guard.sql", (ROOT / "tests" / "phase2" / "rls.sql").read_text())

    def test_later_browser_readable_tables_carry_the_guard(self):
        later = [path for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")) if int(path.name[:3]) > 119]
        missing = [path.name for path in later if BROWSER_READ.search(path.read_text()) and "rapv2_browser_session" not in path.read_text()]
        self.assertEqual(missing, [], "a migration that lets the browser role read a table must add the rapv2_browser_session policy")


if __name__ == "__main__":
    unittest.main()
