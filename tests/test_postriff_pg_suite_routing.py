"""Executable routing contracts; these fixtures do not validate PostgreSQL itself."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/postriff_pg_suite.py"


class PostgresSuiteRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pg-suite-routing-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scripts = self.root / "scripts"
        self.tests = self.root / "tests/phase2"
        self.pg = self.root / "fake-postgres"
        for path in (self.scripts, self.tests, self.pg):
            path.mkdir(parents=True)
        shutil.copyfile(RUNNER, self.scripts / RUNNER.name)
        self.trace = self.root / "trace.jsonl"
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "POSTRIFF_PG_BIN": str(self.pg), "ROUTING_TRACE": str(self.trace),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        record = (
            "import json, os, pathlib, sys\n"
            "with pathlib.Path(os.environ['ROUTING_TRACE']).open('a') as log:\n"
            "    log.write(json.dumps({'program': pathlib.Path(sys.argv[0]).name, "
            "'args': sys.argv[1:], 'dsn': os.environ.get('POSTRIFF_TEST_DSN')})+'\\n')\n"
        )
        for name in ("initdb", "pg_ctl", "psql"):
            p = self.pg / name
            p.write_text(f"#!{sys.executable}\n" + record, encoding="utf8")
            p.chmod(0o700)
        self.fixture_source = record
        (self.tests / "rls.sql").write_text("-- routing fixture only\n")
        self.delegate = self.scripts / "substack_pg_test.py"
        self.delegate.write_text(record + "raise SystemExit(int(os.environ.get('ROUTING_DELEGATE_EXIT', '0')))\n")

    def suite(self, name: str, exit_code: int = 0):
        (self.tests / name).write_text(self.fixture_source + f"raise SystemExit({exit_code})\n")

    def run_suite(self, *selected: str):
        result = subprocess.run([sys.executable, str(self.scripts / RUNNER.name), *selected],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=15)
        trace = [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []
        summary = next((json.loads(line) for line in reversed(result.stdout.splitlines())
                        if line.startswith('{') and '"results"' in line), None)
        return result, trace, summary

    def test_selected_substack_executes_private_runner_without_tcp_cluster(self):
        # Direct execution is a sentinel failure: only the dedicated wrapper is valid.
        self.suite("postgres_substack.py", 97)
        result, trace, summary = self.run_suite("postgres_substack")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r['program'] for r in trace], ["substack_pg_test.py"])
        self.assertEqual(trace[0]['args'], ["--pg-bin", str(self.pg)])
        self.assertIsNone(trace[0]['dsn'])
        self.assertEqual(summary['results'][0]['script'], "tests/phase2/postgres_substack.py")
        self.assertEqual(summary['results'][0]['exitCode'], 0)

    def test_full_catalogue_runs_substack_once_and_preserves_regular_suite(self):
        self.suite("postgres_alpha.py")
        self.suite("postgres_substack.py", 97)
        result, trace, summary = self.run_suite()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [r['program'] for r in trace]
        self.assertEqual(names.count('substack_pg_test.py'), 1)
        self.assertNotIn('postgres_substack.py', names)
        self.assertEqual(names.count('initdb'), 1)
        self.assertEqual(names.count('postgres_alpha.py'), 1)
        self.assertEqual(len(summary['results']), 2)

    def test_private_suite_failure_propagates_without_stopping_later_suite(self):
        self.suite("postgres_substack.py", 97)
        self.suite("postgres_zeta.py")
        self.env['ROUTING_DELEGATE_EXIT'] = '23'
        result, trace, summary = self.run_suite()
        self.assertEqual(result.returncode, 1)
        self.assertEqual([r['exitCode'] for r in summary['results']], [23, 0])
        self.assertEqual([r['program'] for r in trace].count('postgres_zeta.py'), 1)

    def test_unselected_substack_does_not_execute(self):
        self.suite("postgres_substack.py", 97)
        self.suite("postgres_alpha.py")
        result, trace, summary = self.run_suite("postgres_alpha")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('substack_pg_test.py', [r['program'] for r in trace])
        self.assertEqual(len(summary['results']), 1)

    def test_repository_and_plan_guards_remain_paired(self):
        self.suite("postgres_repository.py")
        self.suite("postgres_plan_guards.py")
        self.suite("postgres_safety.py", 99)
        result, trace, summary = self.run_suite()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([Path(r['script']).name for r in summary['results']],
                         ['postgres_repository.py', 'postgres_plan_guards.py'])
        self.assertEqual([r['program'] for r in trace].count('initdb'), 1)

    def test_instagram_and_safety_remain_paired(self):
        self.suite("postgres_instagram_lifecycle.py")
        self.suite("postgres_safety.py")
        result, trace, summary = self.run_suite()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([Path(r['script']).name for r in summary['results']],
                         ['postgres_instagram_lifecycle.py', 'postgres_safety.py'])
        self.assertEqual([r['program'] for r in trace].count('initdb'), 1)

    def test_missing_private_runner_is_failure_not_skip(self):
        self.suite("postgres_substack.py", 0)
        self.delegate.unlink()
        result, trace, summary = self.run_suite("postgres_substack")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('postgres_substack.py', [r['program'] for r in trace])

    def test_missing_postgresql_binaries_reports_unavailable(self):
        self.suite("postgres_substack.py", 97)
        (self.pg / 'initdb').unlink()
        result, trace, _ = self.run_suite()
        self.assertEqual(result.returncode, 3)
        self.assertIn('VALIDATION_UNAVAILABLE', result.stdout)
        self.assertEqual(trace, [])

    def test_unknown_selection_is_not_a_pass(self):
        self.suite("postgres_substack.py", 97)
        result, trace, _ = self.run_suite('postgres_unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No selected PostgreSQL tests', result.stderr)
        self.assertEqual(trace, [])


if __name__ == '__main__':
    unittest.main()
