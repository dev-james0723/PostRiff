"""Static checks on the PROPOSED Rafii agent OS P0 contracts (docs/design/rafii-agent-os, CF-1/CF-2/CF-3).

The contracts are documentation until lane J copies the proposed DDL into migrations/postriff/. These checks keep the
amended proposal internally consistent (the corrections folded into it stay folded in) and, once the real migration files
exist, keep them byte-identical to the frozen proposal: after a migration is applied anywhere the runner's checksum
ledger forbids editing it (scripts/postriff_migrate.py), so a change must be a new forward migration instead.

The real-database behaviour of the same DDL (RLS, grants, guards, cascades) is exercised by
tests/phase2/postgres_agent_os_ddl.py in the disposable-PostgreSQL CI suite.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/design/rafii-agent-os"
DDL_107 = DOCS / "migrations/107_agent_permissions.sql"
DDL_108 = DOCS / "migrations/108_agent_tasks.sql"
FILES = ("00-README.md", "CF-1-capability-registry.md", "CF-2-authz-consent.md", "CF-3-task-engine.md", "DECISIONS-NEEDED.md",
         "migrations/107_agent_permissions.sql", "migrations/108_agent_tasks.sql")
CODE = re.compile(r"`([a-z][a-z0-9_]{2,63})`")


def tables(sql: str) -> list[str]:
    return re.findall(r"create table if not exists public\.(\w+)", sql)


def rls_loop_tables(sql: str) -> set[str]:
    """Tables named in the DO-block arrays that enable/force RLS and reset privileges."""
    names = set()
    for block in re.findall(r"array\[([^\]]+)\]", sql):
        names.update(re.findall(r"'(pr_agent_\w+)'", block))
    return names


def section(text: str, heading_prefix: str) -> str:
    """The body of the first '## ' section whose heading starts with heading_prefix."""
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line.startswith(heading_prefix)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def table_column(body: str, column: str) -> list[str]:
    """Cells of one named column across every markdown table in body."""
    cells, index = [], None
    for line in body.splitlines():
        if not line.startswith("|"):
            index = None
            continue
        # An escaped pipe (`a\|b`) is cell content, not a column boundary.
        parts = [p.strip().replace("\0", "|") for p in line.replace("\\|", "\0").strip().strip("|").split("|")]
        if index is None:
            index = parts.index(column) if column in parts else -1
            continue
        if index >= 0 and index < len(parts) and not set(parts[index]) <= set("-: "):
            cells.append(parts[index])
    return cells


class ContractDocsPresent(unittest.TestCase):
    def test_every_contract_file_exists(self):
        for name in FILES:
            self.assertTrue((DOCS / name).is_file(), name)


class ProposedDDL(unittest.TestCase):
    def setUp(self):
        self.sql107 = DDL_107.read_text()
        self.sql108 = DDL_108.read_text()

    def test_real_migration_files_stay_byte_identical_to_the_frozen_proposal(self):
        for proposal, real in ((DDL_107, ROOT / "migrations/postriff/107_agent_permissions.sql"),
                               (DDL_108, ROOT / "migrations/postriff/108_agent_tasks.sql")):
            if real.exists():
                self.assertEqual(real.read_bytes(), proposal.read_bytes(), f"{real.name} differs from its frozen proposal")
        numbered = sorted(p.name for p in (ROOT / "migrations/postriff").glob("10[78]_*.sql"))
        self.assertTrue(set(numbered) <= {"107_agent_permissions.sql", "108_agent_tasks.sql"}, numbered)

    def test_approvals_live_only_in_108(self):
        # X1: one pr_agent_approvals table, created by 108; 107 must not create a second, incompatible one.
        self.assertNotIn("pr_agent_approvals", tables(self.sql107))
        self.assertIn("pr_agent_approvals", tables(self.sql108))

    def test_every_table_is_service_only_with_forced_rls(self):
        for sql in (self.sql107, self.sql108):
            created = set(tables(sql))
            self.assertTrue(created)
            self.assertEqual(created - rls_loop_tables(sql), set(), "tables missing from the RLS/privilege loop")
            self.assertIn("force row level security", sql)
            self.assertIn("from public, anon, authenticated, service_role", sql)
            self.assertNotRegex(sql, r"(?i)grant[^;]*\bto\s+(anon|authenticated)\b")
            self.assertIn("create policy service_only", sql)

    def test_history_is_append_only(self):
        # Correction 12: no server DELETE on consent history; grants only gain revoked_* values.
        grants = re.findall(r"(?i)grant\s+([a-z ,()_]+?)\s+on\s+public\.(pr_agent_\w+)\s+to\s+service_role", self.sql107)
        privileges = {table: verbs.lower() for verbs, table in grants}
        for table in ("pr_agent_permission_state", "pr_agent_consent_receipts", "pr_agent_grants", "pr_agent_autopilot_policies"):
            self.assertIn(table, privileges)
            self.assertNotIn("delete", privileges[table], table)
        self.assertNotIn("update", privileges["pr_agent_consent_receipts"])
        self.assertIn("update (revoked_epoch, revoked_by, revoked_at, revoke_reason)", privileges["pr_agent_grants"])
        self.assertIn("on delete restrict", self.sql107)
        self.assertIn("ended_at timestamptz", self.sql107)
        self.assertIn("request_fingerprint", self.sql107)

    def test_tasks_are_scoped_to_their_creator(self):
        # Correction 1: one open chat task per person per conversation, never per conversation.
        self.assertRegex(self.sql108, r"pr_agent_tasks_one_open_chat\s+on public\.pr_agent_tasks \(workspace_id, conversation_id, created_by\)")
        self.assertIn("agent_task_anchor_guard", self.sql108)
        self.assertIn("agent_attempt_guard", self.sql108)

    def test_authorization_basis_is_a_token_compared_for_equality(self):
        # Correction 3: no epoch counter ordered with '>'; a 64-hex token compared with '<>'.
        self.assertNotIn("authz_epoch", self.sql108)
        self.assertGreaterEqual(self.sql108.count("authz_token text not null check (authz_token ~ '^[0-9a-f]{64}$')"), 3)

    def test_child_rows_carry_composite_workspace_keys(self):
        # Correction 13: every child row is tied to its parent's workspace by a composite key.
        self.assertIn("unique (id, workspace_id)", self.sql108)
        self.assertIn("unique (id, task_id, workspace_id)", self.sql108)
        self.assertGreaterEqual(self.sql108.count("references public.pr_agent_tasks(id, workspace_id)"), 6)
        self.assertGreaterEqual(self.sql108.count("references public.pr_agent_steps(id, task_id, workspace_id)"), 5)

    def test_cron_cannot_run_anything_but_reads_and_observers(self):
        # Correction 9: background claims are limited to R0 reads, delegate polls and waits.
        self.assertIn("background_allowed boolean not null default false", self.sql108)
        self.assertIn("(kind = 'tool' and risk_class = 'R0' and effect = 'READ') or kind in ('delegate','wait')", self.sql108)

    def test_spoken_or_typed_yes_cannot_decide_new_approval_kinds(self):
        # Correction 17 / DP-5: text and voice decide only legacy schedule and automation proposals.
        self.assertIn("decision_surface not in ('text','voice')", self.sql108)
        self.assertIn("proposal_type in ('schedule_draft','reschedule_post','automation_change')", self.sql108)


class OneErrorVocabulary(unittest.TestCase):
    def test_task_api_errors_come_from_the_single_client_visible_table(self):
        # Correction 16: CF-3 may only use codes defined in CF-2's one client-visible table.
        cf2 = (DOCS / "CF-2-authz-consent.md").read_text()
        cf3 = (DOCS / "CF-3-task-engine.md").read_text()
        table = section(cf2, "## 13.")
        defined = {m for cell in table_column(table, "Code") for m in CODE.findall(cell)}
        self.assertGreaterEqual(len(defined), 20, "CF-2 §13 must hold the client-visible error-code table")
        used = {m for cell in table_column(cf3, "Errors") for m in CODE.findall(cell)}
        self.assertTrue(used, "CF-3's HTTP table must list its error codes in an 'Errors' column")
        self.assertEqual(used - defined, set(), "CF-3 uses error codes CF-2 does not define")
        for retired in ("permission_revoked", "permission_missing", "agent_approval_closed", "agent_approval_expired",
                        "agent_approval_digest", "agent_approval_stale"):
            self.assertNotIn(retired, defined, retired)


if __name__ == "__main__":
    unittest.main()
