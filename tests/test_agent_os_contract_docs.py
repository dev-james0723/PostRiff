"""Static checks on the PROPOSED Rafii agent OS P0 contracts (docs/design/rafii-agent-os, CF-1/CF-2/CF-3).

The contracts are documentation until lane J copies the proposed DDL into migrations/postriff/. These checks keep the
amended proposal internally consistent (the corrections folded into it stay folded in) and, once the real migration files
exist, keep them byte-identical to the frozen proposal: after a migration is applied anywhere the runner's checksum
ledger forbids editing it (scripts/postriff_migrate.py), so a change must be a new forward migration instead.

The migration numbers are proposals until J creates the real files. These checks name the agent OS files exactly and never
reserve a number range, so another lane's migration with a neighbouring number never fails this module.

The real-database behaviour of the same DDL (RLS, grants, guards, cascades) is exercised by
tests/phase2/postgres_agent_os_ddl.py in the disposable-PostgreSQL CI suite.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/design/rafii-agent-os"
DDL_PERMISSIONS = DOCS / "migrations/109_agent_permissions.sql"     # CF-2; 107 is taken by PR #162 (youtube planner)
DDL_TASKS = DOCS / "migrations/108_agent_tasks.sql"                 # CF-3
PG_SUITE = ROOT / "tests/phase2/postgres_agent_os_ddl.py"
REAL = ROOT / "migrations/postriff"
FILES = ("00-README.md", "CF-1-capability-registry.md", "CF-2-authz-consent.md", "CF-3-task-engine.md", "DECISIONS-NEEDED.md",
         "migrations/" + DDL_PERMISSIONS.name, "migrations/" + DDL_TASKS.name)
CODE = re.compile(r"`([a-z][a-z0-9_]{2,63})`")


def read(name: str) -> str:
    return (DOCS / name).read_text()


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


def subsection(text: str, heading_prefix: str) -> str:
    """The body of the first '### ' subsection whose heading starts with heading_prefix (ends at the next heading)."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            if inside:
                break
            inside = line.startswith(heading_prefix)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def table_rows(body: str, first_cell: str) -> dict[str, list[str]]:
    """Markdown table rows of body keyed by their first cell, for rows whose first cell matches first_cell (a regex)."""
    rows = {}
    for line in body.splitlines():
        if line.startswith("|"):
            parts = [p.strip().replace("\0", "|") for p in line.replace("\\|", "\0").strip().strip("|").split("|")]
            if parts and re.fullmatch(first_cell, parts[0]):
                rows[parts[0]] = parts
    return rows


def sql_block(body: str) -> str:
    """The first fenced ```sql block of body."""
    match = re.search(r"```sql\n(.*?)```", body, re.S)
    return match.group(1) if match else ""


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


class MigrationNumbers(unittest.TestCase):
    """Review of #160: PR #162 claims 107. The check names exact files and never blocks a number another lane may use."""

    def test_real_migration_files_match_the_proposal_by_name_and_bytes(self):
        for proposal in (DDL_PERMISSIONS, DDL_TASKS):
            suffix = proposal.name.split("_", 1)[1]                         # e.g. 'agent_permissions.sql'
            real = sorted(REAL.glob(f"[0-9][0-9][0-9]_{suffix}"))
            if real:
                self.assertEqual([p.name for p in real], [proposal.name], "renumber the proposal together with the real file")
                self.assertEqual(real[0].read_bytes(), proposal.read_bytes(), f"{real[0].name} differs from its frozen proposal")

    def test_allocated_numbers_have_no_other_real_migration(self):
        for proposal in (DDL_PERMISSIONS, DDL_TASKS):
            occupants = sorted(p.name for p in REAL.glob(proposal.name[:3] + "_*.sql"))
            self.assertTrue(set(occupants) <= {proposal.name}, f"allocated number collision: {occupants}")

    def test_no_neighbouring_number_is_reserved(self):
        # Another lane's migration that shares a number with no agent OS file must never fail this module.
        source = Path(__file__).read_text()
        self.assertNotRegex(source, r"glob\(\"10\[")

    def test_every_mention_uses_the_proposed_numbers(self):
        texts = {name: read(name) for name in FILES}
        texts[PG_SUITE.name] = PG_SUITE.read_text()
        for proposal in (DDL_PERMISSIONS, DDL_TASKS):
            suffix = proposal.name.split("_", 1)[1]
            for name, text in texts.items():
                for number in re.findall(r"\b(\d{3})_" + re.escape(suffix), text):
                    self.assertEqual(number, proposal.name[:3], f"{name} names {number}_{suffix}")
        # 107 now belongs to PR #162. The contracts and DDL never mention it (code line refs like `:107` are fine); a README
        # line may mention it only to record #162's claim.
        number = r"(?<![:.\w-])107(?!\d)"
        for name, text in texts.items():
            if name != "00-README.md":
                self.assertNotRegex(text, number, name)
        for line in read("00-README.md").splitlines():
            if re.search(number, line):
                self.assertIn("#162", line, line)

    def test_register_records_the_claim_on_107(self):
        register = section(read("00-README.md"), "## 5.")
        self.assertIn("107_youtube_planner_fairness", register)
        self.assertIn("#162", register)
        self.assertNotIn("No open PR or local lane claims 107", register)


class RecordedAuthority(unittest.TestCase):
    def test_decided_release_permissions_are_not_reopened(self):
        decisions = read("DECISIONS-NEEDED.md")
        for heading in ("DP-2 — Paid live runs: US$20 total cap approved", "DP-9 — Permissions and task migrations approved", "DP-17 — Visible context approved"):
            self.assertIn(heading, decisions)
        self.assertIn("fresh action-specific confirmation", decisions)
        self.assertIn("permissions-then-tasks", decisions)
        self.assertIn("not US$20 of new remaining allowance", decisions)
        rows = table_rows(section(read("00-README.md"), "## 4."), r"DP-(2|9|17)")
        self.assertEqual(set(rows), {"DP-2", "DP-9", "DP-17"})
        for cells in rows.values():
            self.assertIn("approved", cells[1])
            self.assertNotIn("open", cells[1])


class ProposedDDL(unittest.TestCase):
    def setUp(self):
        self.sql_perm = DDL_PERMISSIONS.read_text()
        self.sql_tasks = DDL_TASKS.read_text()

    def test_approvals_live_only_in_the_task_engine_ddl(self):
        # X1: one pr_agent_approvals table, created by the task engine DDL; the permissions DDL must not create a second one.
        self.assertNotIn("pr_agent_approvals", tables(self.sql_perm))
        self.assertIn("pr_agent_approvals", tables(self.sql_tasks))

    def test_every_table_is_service_only_with_forced_rls(self):
        for sql in (self.sql_perm, self.sql_tasks):
            created = set(tables(sql))
            self.assertTrue(created)
            self.assertEqual(created - rls_loop_tables(sql), set(), "tables missing from the RLS/privilege loop")
            self.assertIn("force row level security", sql)
            self.assertIn("from public, anon, authenticated, service_role", sql)
            self.assertNotRegex(sql, r"(?i)grant[^;]*\bto\s+(anon|authenticated)\b")
            self.assertIn("create policy service_only", sql)

    def test_history_is_append_only(self):
        # Correction 12: no server DELETE on consent history; grants only gain revoked_* values.
        grants = re.findall(r"(?i)grant\s+([a-z ,()_]+?)\s+on\s+public\.(pr_agent_\w+)\s+to\s+service_role", self.sql_perm)
        privileges = {table: verbs.lower() for verbs, table in grants}
        for table in ("pr_agent_permission_state", "pr_agent_consent_receipts", "pr_agent_grants", "pr_agent_autopilot_policies"):
            self.assertIn(table, privileges)
            self.assertNotIn("delete", privileges[table], table)
        self.assertNotIn("update", privileges["pr_agent_consent_receipts"])
        self.assertIn("update (revoked_epoch, revoked_by, revoked_at, revoke_reason)", privileges["pr_agent_grants"])
        self.assertIn("on delete restrict", self.sql_perm)
        self.assertIn("ended_at timestamptz", self.sql_perm)
        self.assertIn("request_fingerprint", self.sql_perm)

    def test_tasks_are_scoped_to_their_creator(self):
        # Correction 1: one open chat task per person per conversation, never per conversation.
        self.assertRegex(self.sql_tasks, r"pr_agent_tasks_one_open_chat\s+on public\.pr_agent_tasks \(workspace_id, conversation_id, created_by\)")
        self.assertIn("agent_task_anchor_guard", self.sql_tasks)
        self.assertIn("agent_attempt_guard", self.sql_tasks)

    def test_authorization_basis_is_a_token_compared_for_equality(self):
        # Correction 3: no epoch counter ordered with '>'; a 64-hex token compared with '<>'.
        self.assertNotIn("authz_epoch", self.sql_tasks)
        self.assertGreaterEqual(self.sql_tasks.count("authz_token text not null check (authz_token ~ '^[0-9a-f]{64}$')"), 3)

    def test_child_rows_carry_composite_workspace_keys(self):
        # Correction 13: every child row is tied to its parent's workspace by a composite key.
        self.assertIn("unique (id, workspace_id)", self.sql_tasks)
        self.assertIn("unique (id, task_id, workspace_id)", self.sql_tasks)
        self.assertGreaterEqual(self.sql_tasks.count("references public.pr_agent_tasks(id, workspace_id)"), 6)
        self.assertGreaterEqual(self.sql_tasks.count("references public.pr_agent_steps(id, task_id, workspace_id)"), 5)

    def test_cron_cannot_run_anything_but_reads_and_observers(self):
        # Correction 9: background claims are limited to R0 reads, delegate polls and waits.
        self.assertIn("background_allowed boolean not null default false", self.sql_tasks)
        self.assertIn("(kind = 'tool' and risk_class = 'R0' and effect = 'READ') or kind in ('delegate','wait')", self.sql_tasks)

    def test_spoken_or_typed_yes_cannot_decide_new_approval_kinds(self):
        # Correction 17 / DP-5: text and voice decide only legacy schedule and automation proposals.
        self.assertIn("decision_surface not in ('text','voice')", self.sql_tasks)
        self.assertIn("proposal_type in ('schedule_draft','reschedule_post','automation_change')", self.sql_tasks)


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


class ShadowIsInvisible(unittest.TestCase):
    """Review of #160 (blocking): shadow computes and logs; only enforce may narrow, deny or add a confirmation (DP-1)."""

    def setUp(self):
        self.cf1, self.cf2 = read("CF-1-capability-registry.md"), read("CF-2-authz-consent.md")

    def test_modes_state_that_shadow_returns_exactly_the_off_result(self):
        modes = subsection(self.cf2, "### 8.2")
        self.assertIn("byte-identical to `off`", modes)
        for surface_effect in ("manifest", "permissionRevision", "confirmation.required", "receipt", "query result"):
            self.assertIn(surface_effect, modes)
        self.assertIn("Only `enforce`", modes)
        self.assertNotIn("Shadow/enforce", self.cf2)

    def test_every_enforcement_point_goes_through_the_mode_aware_gate(self):
        rows = table_rows(subsection(self.cf2, "### 8.3"), r"E\d+")
        self.assertEqual(sorted(rows, key=lambda r: int(r[1:])), [f"E{i}" for i in range(1, 13)])
        for point, cells in rows.items():
            self.assertNotRegex(cells[-1], r"(?<![_.])\bdecide\(", f"{point} calls decide() directly; use authz.gate*/recheck*")
            self.assertNotRegex(cells[-1], r"whose decide", point)

    def test_manifest_revision_changes_only_in_enforce(self):
        genui = section(self.cf1, "## 8.")
        self.assertIn("only when the permissions mode is `enforce`", genui)
        self.assertNotIn("mode is not `off`", genui)
        self.assertNotRegex(genui, r"only when `decide\(")

    def test_acceptance_compares_shadow_with_off_for_a_narrowed_person(self):
        acceptance = section(self.cf2, "## 18.")
        self.assertRegex(acceptance, r"A13 .*shadow.*byte-identical to `off`")
        self.assertIn("narrowed-grant", acceptance)


class LegacyBaselineIsExactlyToday(unittest.TestCase):
    """Review of #160: the baseline covers every kind (context and the grounded site agent), and legacy is golden-equal."""

    def setUp(self):
        self.cf1 = read("CF-1-capability-registry.md")
        self.baseline = section(self.cf1, "## 12.")

    def test_baseline_names_every_consumer_kind_including_context(self):
        contexts = set(re.findall(r"`(context\.[a-z_]+)`", section(self.cf1, "## 10.")))
        self.assertEqual(len(contexts), 5, contexts)
        self.assertIn("CONTEXT_CAPABILITIES", self.baseline)
        for capability in sorted(contexts):
            self.assertIn(capability, self.baseline)
        self.assertIn("site_capability", self.baseline)

    def test_legacy_golden_test_requires_equality_on_every_surface_and_mode(self):
        golden = self.baseline[self.baseline.index("Golden tests"):]
        self.assertIn("required == legacy_confirmation", golden)
        for case in ("no row", "ended", "LEGACY_EQUIVALENT", "`off`", "`shadow`", "`enforce`", "site_agent", "context"):
            self.assertIn(case, golden)
        self.assertNotIn("under `legacy`, `none`", golden)       # the old ≥-only wording covered legacy too

    def test_grounded_site_agent_catalogue_is_a_registry_source(self):
        registry = section(self.cf1, "## 5.")
        self.assertRegex(registry, r"def ensure\(\).*site_tools\.CATALOG")
        self.assertIn("def site_capability(tool_id", registry)
        self.assertIn("`site.automation_patch_propose`", section(self.cf1, "## 7."))
        self.assertIn("site_capability", read("CF-2-authz-consent.md"))


class TaskEngineObserversAndShadow(unittest.TestCase):
    """Review of #160: external-effect observers survive cancel and membership end; engine shadow is behaviour-preserving."""

    def setUp(self):
        self.cf3 = read("CF-3-task-engine.md")
        self.claim = sql_block(subsection(self.cf3, "### 5.2"))
        self.sql_tasks = DDL_TASKS.read_text()

    def test_claim_keeps_observers_of_a_cancelled_task_and_honours_the_allowlist(self):
        self.assertIn("(t.cancel_requested_at IS NULL OR d.observes_external)", self.claim)
        self.assertIn("(t.attempts_left > 0 OR d.kind = 'delegate')", self.claim)
        self.assertIn("'awaiting_approval'", self.claim)
        self.assertIn("d.workspace_id = ANY(%(engine_workspaces)s::uuid[])", self.claim)

    def test_derivation_never_cancels_while_an_observer_is_open(self):
        rule_one = next(line for line in subsection(self.cf3, "### 4.2").splitlines() if line.startswith("1."))
        self.assertIn("observes_external", rule_one)

    def test_an_ended_membership_is_observed_read_only(self):
        identity = subsection(self.cf3, "### 6.1")
        self.assertIn("read-only observer", identity)
        self.assertIn("authz_verdict in ('allow','approve','step_up','deny','observe')", self.sql_tasks)
        guard = self.sql_tasks[self.sql_tasks.index("function postriff_private.agent_attempt_guard()"):]
        self.assertIn("observes_external", guard[:guard.index("end $body$")])
        self.assertIn("'observe'", read("CF-2-authz-consent.md"))

    def test_shadow_leaves_legacy_state_authoritative(self):
        self.assertNotIn("adoption moves", self.cf3)
        flags = subsection(self.cf3, "### 21.1")
        self.assertIn("task_engine_for", flags)
        self.assertIn("RAFII_TASK_ENGINE_AUTHORITATIVE", flags)
        self.assertIn("copied, never moved", subsection(self.cf3, "## 11."))

    def test_member_readable_rows_carry_no_step_detail(self):
        self.assertNotIn("changes nothing members see today", self.cf3)
        mirror = subsection(self.cf3, "### 4.5")
        for field in ("outputs", "entities", "approvals", "reason"):
            self.assertIn(f"`{field}`", mirror)
        self.assertIn("pr_agent_runs", section(self.cf3, "## 22.")[section(self.cf3, "## 22.").index("13."):])


if __name__ == "__main__":
    unittest.main()
