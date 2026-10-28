"""The release-candidate superset proof flags what a merge drops and passes what it keeps (throwaway git repo; no network)."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rc_superset_proof', ROOT / 'scripts/rc_superset_proof.py')
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)

ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid', 'GIT_COMMITTER_NAME': 't',
       'GIT_COMMITTER_EMAIL': 't@example.invalid', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_SYSTEM': '/dev/null',
       'PATH': '/usr/bin:/bin:/usr/local/bin'}

VERCEL = {'crons': [{'path': '/api/cron/worker', 'schedule': '* * * * *'}], 'git': {'deploymentEnabled': False}}


class Repo:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.run('init', '-q', '-b', 'main')

    def run(self, *args):
        done = subprocess.run(['git', '-C', str(self.dir), *args], capture_output=True, text=True, env=ENV)
        if done.returncode:
            raise AssertionError(done.stderr)
        return done.stdout.strip()

    def write(self, path, text):
        target = self.dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        self.run('add', '-A')
        self.run('commit', '-q', '-m', message)
        return self.run('rev-parse', 'HEAD')

    def proof(self, live, rc, base, allow=None):
        argv = ['--live', live, '--rc', rc, '--base', base]
        out = Path(tempfile.mkdtemp()) / 'out.json'
        argv += ['--json', str(out)]
        if allow is not None:
            allowed = out.parent / 'allow.json'
            allowed.write_text(json.dumps(allow))
            argv += ['--allow', str(allowed)]
        previous = os.getcwd()
        os.chdir(self.dir)  # the tool reads the repository it is run in
        try:
            with patch('sys.argv', ['rc_superset_proof.py', *argv]), patch('builtins.print'):
                code = proof.main()
        finally:
            os.chdir(previous)
        return code, json.loads(out.read_text())


class SupersetProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(self.tmp.name)
        r = self.repo
        r.write('vercel.json', json.dumps(VERCEL))
        r.write('src/app.py', 'ROUTE = "/api/health"\nFLAG = "POSTRIFF_ALPHA_FLAG"\n\ndef run():\n    return "base line one"\n')
        r.write('migrations/postriff/001_first.sql', 'select 1;\n')
        r.write('tests/test_app.py', 'def test(): pass\n')
        self.base = r.commit('base')
        r.run('checkout', '-q', '-b', 'live')
        r.write('src/app.py', 'ROUTE = "/api/health"\nFLAG = "POSTRIFF_ALPHA_FLAG"\nOTHER = "/api/live/only"\n\ndef run():\n    return "base line one"\n')
        r.write('migrations/postriff/002_live.sql', 'select 2;\n')
        self.live = r.commit('live adds a route and a migration')
        r.run('checkout', '-q', '-b', 'rc', self.live)

    def test_a_candidate_that_keeps_everything_is_proven(self):
        self.repo.write('src/extra.py', 'EXTRA = "/api/extra"\n')
        rc = self.repo.commit('rc adds a file')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual((code, report['ok']), (0, True))

    def test_a_dropped_file_is_found(self):
        self.repo.run('rm', '-q', 'migrations/postriff/002_live.sql')
        rc = self.repo.commit('rc drops the migration')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertIn('migrations/postriff/002_live.sql', report['checks']['files']['problems'])
        self.assertIn('migrations/postriff/002_live.sql', report['checks']['migrations']['problems'])

    def test_a_line_the_live_line_added_and_the_merge_lost_is_found(self):
        self.repo.write('src/app.py', 'ROUTE = "/api/health"\nFLAG = "POSTRIFF_ALPHA_FLAG"\n\ndef run():\n    return "base line one"\n')
        rc = self.repo.commit('rc loses the live route')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertTrue(any('OTHER = "/api/live/only"' in p for p in report['checks']['lines']['problems']))
        self.assertIn('/api/live/only', report['checks']['routes']['problems'])

    def test_an_explained_rewrite_passes_and_an_unexplained_one_does_not(self):
        self.repo.write('src/app.py', 'ROUTE = "/api/health"\nFLAG = "POSTRIFF_ALPHA_FLAG"\nOTHER = "/api/live/only"  # moved\n\ndef run():\n    return "rewritten"\n')
        rc = self.repo.commit('rc rewrites the live line on purpose')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        explained = {'lines': {p: 'resolution of a conflict in the test' for p in report['checks']['lines']['problems']}}
        code, report = self.repo.proof(self.live, rc, self.base, allow=explained)
        self.assertEqual(code, 0)
        self.assertEqual(len(report['checks']['lines']['allowed']), len(explained['lines']))

    def test_a_removed_cron_and_a_changed_git_setting_are_found(self):
        self.repo.write('vercel.json', json.dumps({'crons': [], 'git': {'deploymentEnabled': True}}))
        rc = self.repo.commit('rc drops the cron')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertEqual(report['checks']['crons']['problems'], ['missing cron /api/cron/worker * * * * *'])
        self.assertIn('"deploymentEnabled": true', report['checks']['crons']['note'])

    def test_a_flag_that_is_no_longer_read_is_found(self):
        self.repo.write('src/app.py', 'ROUTE = "/api/health"\nOTHER = "/api/live/only"\n\ndef run():\n    return "base line one"\n')
        rc = self.repo.commit('rc stops reading the flag')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertEqual(report['checks']['flags']['problems'], ['POSTRIFF_ALPHA_FLAG'])

    def test_a_removed_test_module_is_found(self):
        self.repo.run('rm', '-q', 'tests/test_app.py')
        rc = self.repo.commit('rc drops a test')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertEqual(report['checks']['tests']['problems'], ['tests/test_app.py'])

    def test_a_candidate_that_does_not_contain_the_live_commit_fails_ancestry(self):
        self.repo.run('checkout', '-q', '-b', 'sideways', self.base)
        self.repo.write('src/other.py', 'X = 1\n')
        rc = self.repo.commit('unrelated branch')
        code, report = self.repo.proof(self.live, rc, self.base)
        self.assertEqual(code, 1)
        self.assertFalse(report['checks']['ancestry']['ok'])


if __name__ == '__main__':
    unittest.main()
