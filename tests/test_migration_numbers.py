"""Hosted migrations keep unique numbers, and 031 chat media keeps its contract (chat-context SPEC §10)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import postriff_migrate  # noqa: E402

CHAT_MEDIA = ROOT / "migrations" / "postriff" / "031_chat_media.sql"
PRODUCTIVITY_CONNECTORS = ROOT / "migrations" / "postriff" / "032_productivity_connectors.sql"


class MigrationNumberTests(unittest.TestCase):
    def test_numbers_are_unique(self):
        paths = postriff_migrate.migrations()
        numbers = [p.name.split("_")[0] for p in paths]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertIn("031_chat_media.sql", [p.name for p in paths])

    def test_duplicate_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "migrations" / "postriff"
            folder.mkdir(parents=True)
            (folder / "031_a.sql").write_text("select 1;")
            (folder / "031_b.sql").write_text("select 1;")
            with self.assertRaises(ValueError):
                postriff_migrate.migrations(Path(tmp))


class ChatMediaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.sql = CHAT_MEDIA.read_text()

    def test_forward_only_idempotent(self):
        self.assertTrue(self.sql.startswith("-- Chat attachments"))
        self.assertRegex(self.sql, r"(?m)^begin;$")
        self.assertRegex(self.sql, r"(?m)^commit;$")
        for statement in re.findall(r"(?im)^\s*create (?:table|index)\b[^\n]*", self.sql):
            self.assertIn("if not exists", statement.lower())
        self.assertNotRegex(self.sql.lower(), r"\bdrop\b|\btruncate\b")

    def test_service_only_and_no_storage_ddl(self):
        lower = self.sql.lower()
        self.assertNotIn("storage.", lower)
        self.assertIn("force row level security", lower)
        self.assertIn("revoke all on public.%i from public, anon, authenticated", lower)
        self.assertIn("create policy service_only", lower)
        self.assertNotRegex(lower, r"grant [^;]* to (authenticated|anon)")

    def test_rls_harness_loads_it_in_order(self):
        harness = (ROOT / "tests" / "phase2" / "rls.sql").read_text()
        loaded = re.findall(r"migrations/postriff/(\d{3})_", harness)
        self.assertEqual(loaded, sorted(loaded))
        self.assertIn("031", loaded)
        self.assertIn("'pr_media_uploads','pr_media_notes'", harness)


class ProductivityConnectorMigrationTests(unittest.TestCase):
    def test_service_only_opaque_ids_and_cleanup_relations(self):
        sql = PRODUCTIVITY_CONNECTORS.read_text()
        lower = sql.lower()
        self.assertRegex(sql, r"\^pc_\[0-9a-f\]\{32\}\$")
        self.assertRegex(sql, r"\^ci_\[0-9a-f\]\{32\}\$")
        self.assertIn("force row level security", lower)
        self.assertIn("create policy service_only", lower)
        self.assertIn("foreign key(workspace_id,connection_id)", lower)
        self.assertNotRegex(lower, r"grant [^;]* to (authenticated|anon)")

    def test_rls_harness_loads_connector_migration_and_denies_browser_tables(self):
        harness = (ROOT / "tests" / "phase2" / "rls.sql").read_text()
        self.assertIn("032_productivity_connectors.sql", harness)
        for table in ("pr_connector_oauth_transactions", "pr_connector_credentials", "pr_connector_selections", "pr_connector_fetches"):
            self.assertIn(table, harness)


if __name__ == "__main__":
    unittest.main()
