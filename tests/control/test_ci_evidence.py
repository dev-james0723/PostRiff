"""Exact-SHA CI evidence (ci_evidence, migration 071) without network or database: GitHub API fixtures → evaluation →
evidence rows, the server's verdict over them (GET /engineering, GET /engineering/checks), the GitHub Actions entry point,
and drift guards tying the manifest to the workflow files, the workflow to its trust boundary and 071 to its scope.
The PostgreSQL half is test_ci_evidence_pg.py."""
from contextlib import nullcontext
import copy
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from rafii_control import ci_evidence
from rafii_control.auth import ControlError
from rafii_control.intelligence import QueryService, TRUSTED_MANIFEST_PROVENANCE, engineering_state

ROOT = Path(__file__).resolve().parents[2]
# Placeholder SHAs: the tip M (a merge commit), the PR head H, the base before the merge B, their shared tree T.
M, H, B, T = '7' * 40, '8' * 40, '6' * 40, 'e' * 40
OBSERVED = '2026-10-01T10:05:00+00:00'
REPO = '/repos/dev-james0723/PostRiff'
KEYS = [check['key'] for check in ci_evidence.REQUIRED_CHECKS]


def load_routes():
    raw = (Path(__file__).parent / 'fixtures/ci-evidence-merged-pr.json').read_text()
    for name, value in (('{M}', M), ('{H}', H), ('{B}', B), ('{T}', T)):
        raw = raw.replace(name, value)
    return json.loads(raw)['routes']


def runs_key(sha):
    return f'{REPO}/actions/runs?head_sha={sha}&page=1&per_page=100'


def jobs_key(run_id):
    return f'{REPO}/actions/runs/{run_id}/jobs?filter=latest&per_page=100'


STATUSES_KEY = f'{REPO}/commits/{M}/statuses?per_page=100'
FILES_KEY = f'{REPO}/pulls/90/files?page=1&per_page=100'
PULLS_KEY = f'{REPO}/commits/{M}/pulls?per_page=100'


class FakeGitHub:
    """Serves fixture responses by path and sorted query; an Exception value is raised; anything else is a 404."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, params=None):
        key = path + ('?' + urlencode(sorted(params.items())) if params else '')
        self.calls.append(key)
        if key not in self.routes:
            raise ci_evidence.CollectorError('github_http_404')
        value = self.routes[key]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def evaluate(routes=None, observed=OBSERVED, client=None):
    client = client or FakeGitHub(routes if routes is not None else load_routes())
    return ci_evidence.evaluate(ci_evidence.gather(client), observed_at=observed, collector={'runId': 77, 'runAttempt': 1, 'event': 'push'})


def check_of(evaluation, key):
    return next(check for check in evaluation['checks'] if check['key'] == key)


def state_of(evaluation):
    return engineering_state(ci_evidence.evidence_rows(evaluation, 'production'), evaluation['exactSha'], evaluation['requiredCount'])


def job(run_id, **change):
    """A copy of a fixture job retargeted at another run."""
    base = copy.deepcopy(load_routes()[jobs_key(1001)]['jobs'][0])
    base.update(run_id=run_id, id=run_id + 1000)
    base.update(change)
    return {'total_count': 1, 'jobs': [base]}


class CollectorTests(unittest.TestCase):
    def evaluate(self, routes=None):
        self.client = FakeGitHub(routes if routes is not None else load_routes())
        return evaluate(client=self.client)

    def test_merged_pr_head_with_identical_tree_attests_every_required_check_for_the_exact_tip(self):
        evaluation = self.evaluate()
        self.assertEqual(evaluation['exactSha'], M)
        self.assertEqual(evaluation['pullRequest'], dict(number=90, headSha=H, headRef='claude/founder-activation', treeIdentical=True,
                                                         baseContained=True, qualified=True, reason='tree_identical_base_contained'))
        self.assertEqual((evaluation['qualification'], evaluation['requiredCount']), ('required_checks_succeeded', 5))
        self.assertEqual([check['key'] for check in evaluation['checks']], KEYS)
        for check in evaluation['checks']:
            self.assertEqual((check['required'], check['outcome'], check['conclusion'], check['attested']), (True, 'success', 'success', True), check['key'])
        local = check_of(evaluation, 'consumer-ready/local-gates')
        self.assertEqual((local['source'], local['runId'], local['jobId'], local['headSha'], local['requiredReason']), ('pull_request_head', 1001, 2001, H, 'always'))
        self.assertEqual(check_of(evaluation, 'rafii-control/local-foundation')['requiredReason'], 'ran')
        vercel = check_of(evaluation, 'vercel/production')
        self.assertEqual((vercel['source'], vercel['statusId']), ('exact_sha_status', 3002), 'the newest Vercel status wins over the earlier pending one')
        rows = ci_evidence.evidence_rows(evaluation, 'production')
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row['exact_sha'] == M and row['state'] == 'checks_passed' and row['attested'] and row['required'] and row['kind'] == 'check'
                            for row in rows))
        self.assertEqual([row['external_id'] for row in rows], [f'ci/{M}/{key}' for key in KEYS])
        self.assertTrue(all(len(row['external_id']) <= 160 for row in rows))
        self.assertEqual([row['provider'] for row in rows], ['github'] * 4 + ['vercel'])
        self.assertEqual(rows, ci_evidence.evidence_rows(evaluation, 'production'), 'row ids are deterministic, so re-ingest updates in place')
        self.assertNotEqual(rows[0]['id'], ci_evidence.evidence_rows(evaluation, 'staging')[0]['id'])
        self.assertEqual(engineering_state(rows, M, evaluation['requiredCount']), 'checks_passed')
        self.assertEqual(ci_evidence.summarize(evaluation, M)['requiredCount'], 5)
        self.assertFalse(any('/files' in call for call in self.client.calls), 'every filtered workflow ran: no changed-file listing needed')
        self.assertEqual(evaluation['collector'], {'runId': 77, 'runAttempt': 1, 'event': 'push'})
        self.assertLess(len(json.dumps(evaluation)), 131072, '052 caps a manifest payload at 128 KiB')
        later = evaluate(observed='2026-10-01T11:00:00+00:00')
        self.assertEqual(later['evaluationDigest'], evaluation['evaluationDigest'], 'the digest ignores when it was observed')

    def test_pr_results_that_did_not_test_the_exact_tree_are_recorded_but_never_attested(self):
        cases = {
            'tree_differs': lambda routes: routes[f'{REPO}/git/commits/{H}']['tree'].update(sha='d' * 40),
            'base_not_contained': lambda routes: routes[f'{REPO}/compare/{B}...{H}?per_page=1'].update(status='diverged', behind_by=2, merge_base_commit={'sha': '5' * 40}),
            'merge_parent_mismatch': lambda routes: routes[f'{REPO}/git/commits/{M}']['parents'][1].update(sha='9' * 40),
        }
        for reason, change in cases.items():
            with self.subTest(reason=reason):
                routes = load_routes()
                change(routes)
                evaluation = self.evaluate(routes)
                self.assertEqual((evaluation['pullRequest']['qualified'], evaluation['pullRequest']['reason']), (False, reason))
                for check in evaluation['checks'][:4]:
                    self.assertEqual((check['conclusion'], check['attested'], check['note']), ('success', False, reason), check['key'])
                self.assertEqual(evaluation['qualification'], 'required_checks_not_attested')
                rows = ci_evidence.evidence_rows(evaluation, 'production')
                self.assertEqual([row['state'] for row in rows], ['suspected'] * 4 + ['checks_passed'])
                self.assertEqual(engineering_state(rows, M, 5), 'suspected')

    def test_fork_pull_requests_and_foreign_or_renamed_workflows_never_count(self):
        routes = load_routes()
        routes[PULLS_KEY][0]['head']['repo'] = {'full_name': 'someone/PostRiff'}
        for run in routes[runs_key(H)]['workflow_runs']:
            run['head_repository'] = {'full_name': 'someone/PostRiff'}
        evaluation = self.evaluate(routes)
        self.assertEqual(evaluation['pullRequest']['reason'], 'fork_pull_request')
        self.assertTrue(all(check['outcome'] == 'missing' and not check['attested'] for check in evaluation['checks'][:4]))
        self.assertEqual(state_of(evaluation), 'suspected')
        # A newer same-named workflow in another file, or a newer run belonging to another repository, is not the pinned check.
        routes = load_routes()
        runs = routes[runs_key(H)]['workflow_runs']
        runs.append(dict(copy.deepcopy(runs[0]), id=1999, run_number=999, path='.github/workflows/evil.yml'))
        runs.append(dict(copy.deepcopy(runs[1]), id=1998, run_number=998, repository={'full_name': 'someone/PostRiff'}))
        routes[runs_key(H)]['total_count'] = 6
        routes[jobs_key(1001)]['jobs'][0]['conclusion'] = 'failure'
        routes[jobs_key(1999)] = job(1999, conclusion='success')
        routes[jobs_key(1998)] = job(1998, name='local-foundation', conclusion='failure')
        evaluation = self.evaluate(routes)
        local, control = check_of(evaluation, 'consumer-ready/local-gates'), check_of(evaluation, 'rafii-control/local-foundation')
        self.assertEqual((local['runId'], local['outcome']), (1001, 'failure'))
        self.assertEqual((control['runId'], control['outcome']), (1002, 'success'))
        self.assertNotIn(jobs_key(1999), self.client.calls)
        self.assertNotIn(jobs_key(1998), self.client.calls)

    def test_every_conclusion_but_an_attested_success_is_suspected(self):
        expected = {'failure': ('failure', 'failure', 'unknown'), 'startup_failure': ('failure', 'failure', 'infrastructure'),
                    'timed_out': ('timed_out', 'failure', 'unknown'), 'action_required': ('action_required', 'failure', 'unknown'),
                    'cancelled': ('cancelled', 'cancelled', None), 'skipped': ('skipped', 'skipped', None),
                    'neutral': ('neutral', 'neutral', None), 'stale': ('unknown', 'unknown', None)}
        for conclusion, (stored, outcome, failure_class) in expected.items():
            with self.subTest(conclusion=conclusion):
                routes = load_routes()
                routes[jobs_key(1003)]['jobs'][0]['conclusion'] = conclusion
                evaluation = self.evaluate(routes)
                scenes = check_of(evaluation, 'rafii-browser/scenes')
                self.assertEqual((scenes['conclusion'], scenes['outcome'], scenes['failureClass'], scenes['attested']), (stored, outcome, failure_class, True))
                self.assertNotEqual(evaluation['qualification'], 'required_checks_succeeded')
                rows = ci_evidence.evidence_rows(evaluation, 'production')
                self.assertEqual(next(row for row in rows if row['external_id'].endswith('/rafii-browser/scenes'))['state'], 'suspected')
                self.assertEqual(engineering_state(rows, M, 5), 'suspected')
                self.assertTrue(ci_evidence.summarize(evaluation)['valid'])
        for change, outcome in ((dict(status='in_progress', conclusion=None), 'incomplete'), (dict(name='scenes-renamed'), 'missing')):
            with self.subTest(change=change):
                routes = load_routes()
                routes[jobs_key(1003)]['jobs'][0].update(change)
                evaluation = self.evaluate(routes)
                scenes = check_of(evaluation, 'rafii-browser/scenes')
                self.assertEqual((scenes['outcome'], scenes['conclusion'], scenes['attested']), (outcome, None, False))
                self.assertEqual(evaluation['qualification'], 'required_checks_incomplete')
                self.assertEqual(state_of(evaluation), 'suspected')

    def test_the_newest_run_of_the_pinned_workflow_decides(self):
        routes = load_routes()
        runs = routes[runs_key(H)]['workflow_runs']
        runs.append(dict(copy.deepcopy(runs[0]), id=1000, run_number=400))
        routes[jobs_key(1000)] = job(1000, conclusion='failure')
        routes[runs_key(H)]['total_count'] = 5
        self.assertEqual(check_of(self.evaluate(routes), 'consumer-ready/local-gates')['runId'], 1001, 'an older failed run is superseded')
        runs.append(dict(copy.deepcopy(runs[0]), id=1010, run_number=510))
        routes[jobs_key(1010)] = job(1010, conclusion='failure', run_attempt=2)
        local = check_of(self.evaluate(routes), 'consumer-ready/local-gates')
        self.assertEqual((local['runId'], local['outcome']), (1010, 'failure'), 'a newer failed run is never hidden by an older green one')

    def test_an_exact_sha_push_run_on_consumer_saas_outranks_the_pull_request_head(self):
        routes = load_routes()
        push = dict(copy.deepcopy(routes[runs_key(H)]['workflow_runs'][0]), id=1101, run_number=601, event='push', head_branch='consumer-saas', head_sha=M)
        routes[runs_key(M)] = {'total_count': 1, 'workflow_runs': [push]}
        routes[jobs_key(1101)] = job(1101, head_sha=M, head_branch='consumer-saas', conclusion='failure')
        evaluation = self.evaluate(routes)
        local = check_of(evaluation, 'consumer-ready/local-gates')
        self.assertEqual((local['source'], local['runId'], local['headSha'], local['outcome'], local['attested']), ('exact_sha', 1101, M, 'failure', True))
        self.assertEqual(evaluation['qualification'], 'required_check_failed')
        # An exact-SHA run is attested even when the PR head did not test the same tree; the PR-head ones are not.
        routes[jobs_key(1101)]['jobs'][0]['conclusion'] = 'success'
        routes[f'{REPO}/git/commits/{H}']['tree']['sha'] = 'd' * 40
        evaluation = self.evaluate(routes)
        self.assertTrue(check_of(evaluation, 'consumer-ready/local-gates')['attested'])
        self.assertFalse(check_of(evaluation, 'rafii-control/local-foundation')['attested'])
        # A pull_request run on the tip's SHA is not an exact-SHA push run.
        routes = load_routes()
        routes[runs_key(M)] = {'total_count': 1, 'workflow_runs': [dict(push, event='pull_request', head_branch='claude/other')]}
        routes[jobs_key(1101)] = job(1101, head_sha=M, conclusion='failure')
        self.assertEqual(check_of(self.evaluate(routes), 'consumer-ready/local-gates')['runId'], 1001)

    def test_vercel_counts_only_its_own_bot_status_on_the_exact_sha(self):
        def status(identifier, state, context='Vercel', login='vercel[bot]'):
            return dict(id=identifier, state=state, context=context, creator={'login': login, 'type': 'Bot'}, updated_at='2026-10-01T10:03:00Z')
        cases = [
            ([status(3003, 'success', login='github-actions[bot]'), status(3001, 'pending')], ('incomplete', None, False, 3001, None)),
            ([status(3004, 'error')], ('failure', 'failure', True, 3004, 'infrastructure')),
            ([status(3005, 'failure')], ('failure', 'failure', True, 3005, 'unknown')),
            ([status(3006, 'success', context='Vercel Preview Comments')], ('missing', None, False, None, None)),
            ([], ('missing', None, False, None, None)),
        ]
        for statuses, expected in cases:
            with self.subTest(statuses=statuses):
                routes = load_routes()
                routes[STATUSES_KEY] = statuses
                evaluation = self.evaluate(routes)
                vercel = check_of(evaluation, 'vercel/production')
                self.assertEqual((vercel['outcome'], vercel['conclusion'], vercel['attested'], vercel['statusId'], vercel['failureClass']), expected)
                self.assertEqual(state_of(evaluation), 'suspected')
        self.assertIn(STATUSES_KEY, self.client.calls)
        self.assertFalse(any(f'/commits/{H}/statuses' in call for call in self.client.calls), 'Vercel is read on the exact SHA only')

    def test_a_path_filtered_check_is_exempt_only_with_positive_proof(self):
        routes = load_routes()
        routes[runs_key(H)]['workflow_runs'] = [run for run in routes[runs_key(H)]['workflow_runs'] if run['id'] != 1002]
        routes[runs_key(H)]['total_count'] = 3
        routes[FILES_KEY] = [{'filename': 'web/src/app/page.tsx', 'status': 'modified'},
                             {'filename': 'docs/notes.md', 'status': 'renamed', 'previous_filename': 'docs/old-notes.md'}]
        evaluation = self.evaluate(routes)
        control = check_of(evaluation, 'rafii-control/local-foundation')
        self.assertEqual((control['required'], control['requiredReason'], control['outcome']), (False, 'paths_unmatched', 'missing'))
        self.assertEqual((evaluation['requiredCount'], evaluation['qualification']), (4, 'required_checks_succeeded'))
        self.assertEqual(evaluation['changedFiles'], {'complete': True, 'count': 3})
        rows = ci_evidence.evidence_rows(evaluation, 'production')
        self.assertEqual(len(rows), 4, 'an exempt check writes no row')
        self.assertEqual(engineering_state(rows, M, 4), 'checks_passed')
        self.assertEqual(engineering_state(rows, M, 5), 'suspected', 'the count is the manifest of this exact evaluation')
        for files in ([{'filename': 'migrations/postriff/071_founder_engineering_evidence.sql'}], [{'filename': 'docs/x.md', 'previous_filename': 'tests/control/test_x.py'}]):
            with self.subTest(files=files):
                matched = copy.deepcopy(routes)
                matched[FILES_KEY] = files
                evaluation = self.evaluate(matched)
                control = check_of(evaluation, 'rafii-control/local-foundation')
                self.assertEqual((control['required'], control['requiredReason'], control['outcome']), (True, 'paths_matched', 'missing'))
                self.assertIn(control['matchedPath'], {files[0]['filename'], files[0].get('previous_filename')})
                self.assertEqual(state_of(evaluation), 'suspected')
        unknown = copy.deepcopy(routes)
        unknown[FILES_KEY] = ci_evidence.CollectorError('github_http_502')
        incomplete_runs = copy.deepcopy(routes)
        incomplete_runs[runs_key(H)]['total_count'] = 250
        for name, case, reason in (('files unreadable', unknown, 'paths_unknown'), ('run listing incomplete', incomplete_runs, 'runs_unknown')):
            with self.subTest(case=name):
                control = check_of(self.evaluate(case), 'rafii-control/local-foundation')
                self.assertEqual((control['required'], control['requiredReason']), (True, reason))
        many = copy.deepcopy(routes)
        many[FILES_KEY] = [{'filename': f'docs/page-{index}.md'} for index in range(100)]
        with patch.object(ci_evidence, 'MAX_FILE_PAGES', 1):
            evaluation = self.evaluate(many)
        self.assertEqual(check_of(evaluation, 'rafii-control/local-foundation')['requiredReason'], 'paths_unknown', 'a truncated file list proves nothing')
        self.assertEqual(evaluation['changedFiles'], {'complete': False, 'count': 100})
        self.assertEqual(ci_evidence.applicability(dict(paths=('web/?.ts',)), ran=False, runs_complete=True, pr={'number': 90},
                                                   files={'complete': True, 'names': ['docs/a.md']}), (True, 'paths_unknown', None))
        # A changed file name is printed in the job log: it can never start a line, so never a workflow command.
        hostile = ci_evidence.applicability(dict(paths=('tests/control/**',)), ran=False, runs_complete=True, pr={'number': 90},
                                            files={'complete': True, 'names': ['tests/control/a\n::error::forged.py']})
        self.assertEqual(hostile, (True, 'paths_matched', 'tests/control/a?::error::forged.py'))

    def test_a_direct_push_without_its_merged_pull_request_stays_suspected(self):
        routes = load_routes()
        routes[PULLS_KEY] = []
        evaluation = self.evaluate(routes)
        self.assertIsNone(evaluation['pullRequest'])
        self.assertEqual([(check['required'], check['requiredReason'], check['outcome']) for check in evaluation['checks'][:4]],
                         [(True, 'always', 'missing')] + [(True, 'no_pull_request', 'missing')] * 3)
        self.assertNotIn(runs_key(H), self.client.calls)
        self.assertEqual(state_of(evaluation), 'suspected')
        for change in (dict(merged_at=None), dict(merge_commit_sha=H), dict(base={'ref': 'main', 'repo': {'full_name': ci_evidence.REPOSITORY}}),
                       dict(base={'ref': 'consumer-saas', 'repo': {'full_name': 'someone/PostRiff'}})):
            with self.subTest(change=change):
                pulls = load_routes()[PULLS_KEY]
                pulls[0].update(change)
                self.assertIsNone(ci_evidence.merged_pull_request(pulls, M))
        pulls = load_routes()[PULLS_KEY]
        self.assertIsNone(ci_evidence.merged_pull_request(pulls + copy.deepcopy(pulls), M), 'two candidates are ambiguous, never guessed')

    def test_an_unreadable_branch_or_commit_fails_closed(self):
        for key, value in ((f'{REPO}/git/ref/heads/consumer-saas', {'object': {'sha': 'main', 'type': 'commit'}}),
                           (f'{REPO}/git/ref/heads/consumer-saas', {'object': {'sha': M, 'type': 'tag'}}),
                           (f'{REPO}/git/commits/{M}', {'sha': H})):
            with self.subTest(key=key, value=value):
                routes = load_routes()
                routes[key] = value
                with self.assertRaises(ci_evidence.CollectorError):
                    self.evaluate(routes)

    def test_path_globs_follow_the_github_filter_syntax(self):
        cases = {
            'migrations/postriff/07[0-9]_*': (['migrations/postriff/071_founder_engineering_evidence.sql'],
                                              ['migrations/postriff/080_x.sql', 'migrations/postriff/07a_x.sql', 'migrations/postriff/071_x/y.sql']),
            'web/**': (['web/a.ts', 'web/src/deep/b.tsx'], ['webx/a.ts', 'src/web/a.ts']),
            'scripts/rafii_control_*': (['scripts/rafii_control_pg.py'], ['scripts/rafii_control/x.py', 'scripts/postriff_dev_hosted.py']),
            'api/control.py': (['api/control.py'], ['api/controlxpy', 'api/control.pyc']),
            '**/README.md': (['README.md', 'docs/a/README.md'], ['docs/README.mdx']),
        }
        for pattern, (hits, misses) in cases.items():
            regex = ci_evidence.glob(pattern)
            for name in hits:
                self.assertTrue(regex.fullmatch(name), (pattern, name))
            for name in misses:
                self.assertFalse(regex.fullmatch(name), (pattern, name))
        for unsupported in ('web/?.ts', '!web/**', 'web/{a,b}/**', 'web/[!a]*', 'src/a+', 'web/]'):
            with self.subTest(pattern=unsupported), self.assertRaises(ValueError):
                ci_evidence.glob(unsupported)


def pull_request_paths(text):
    """`on.pull_request.paths` of a workflow file in the two forms these files use (flow list, block list), or None."""
    lines = text.splitlines()
    start = lines.index('on:')
    index = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('  pull_request:')) + 1
    while index < len(lines) and (lines[index].startswith('    ') or not lines[index].strip()):
        line = lines[index].strip()
        if line.startswith('paths:'):
            rest = line[len('paths:'):].strip()
            if rest:
                return [item.strip().strip('\'"') for item in rest.strip('[]').split(',')]
            items, index = [], index + 1
            while index < len(lines) and lines[index].strip().startswith('- '):
                items.append(lines[index].strip()[2:].strip().strip('\'"'))
                index += 1
            return items
        index += 1
    return None


class DriftTests(unittest.TestCase):
    def test_the_manifest_is_the_required_workflow_files(self):
        try:
            import yaml
        except ImportError:
            yaml = None
        for check in ci_evidence.ACTIONS_CHECKS:
            text = (ROOT / check['workflowPath']).read_text()
            expected = None if check['paths'] is None else list(check['paths'])
            with self.subTest(workflow=check['workflowPath']):
                self.assertRegex(text, rf"(?m)^name: {re.escape(check['workflowName'])}$")
                self.assertRegex(text, rf"(?m)^  {re.escape(check['job'])}:$")
                self.assertEqual(pull_request_paths(text), expected, 'a workflow path filter changed: update ci_evidence.REQUIRED_CHECKS')
                for pattern in check['paths'] or ():
                    ci_evidence.glob(pattern)
                if yaml:
                    document = yaml.safe_load(text)
                    triggers = document.get('on', document.get(True))
                    self.assertEqual((triggers['pull_request'] or {}).get('paths'), expected)
                    self.assertIn(check['job'], document['jobs'])
        evidence = (ROOT / '.github/workflows/founder-engineering-evidence.yml').read_text()
        listed = re.search(r'workflows: \[([^\]]*)\]', evidence).group(1)
        self.assertEqual(sorted(item.strip().strip("'") for item in listed.split(',')), sorted(check['workflowName'] for check in ci_evidence.ACTIONS_CHECKS))
        self.assertEqual(ci_evidence.manifest()['checks'][0]['paths'], None)
        self.assertTrue(all(check['why'] for check in ci_evidence.REQUIRED_CHECKS), 'the manifest says why each check is required')

    def test_the_workflow_is_read_only_and_never_hands_the_secret_to_untrusted_code(self):
        text = (ROOT / '.github/workflows/founder-engineering-evidence.yml').read_text()
        permissions = re.search(r'(?m)^permissions:\n((?:  .+\n)+)', text).group(1)
        self.assertEqual(dict(line.strip().split(': ') for line in permissions.splitlines()),
                         {'actions': 'read', 'contents': 'read', 'pull-requests': 'read', 'statuses': 'read'})
        self.assertNotRegex(text, r'(?m)^\s*(pull_request|pull_request_target):')
        self.assertEqual(text.count('secrets.'), 1)
        self.assertIn('RAFII_ENGINEERING_INGEST_DSN: ${{ secrets.RAFII_ENGINEERING_INGEST_DSN }}', text)
        for guard in ("github.repository == 'dev-james0723/PostRiff'", "github.ref == 'refs/heads/consumer-saas'",
                      "github.event.workflow_run.event == 'push'", "github.event.workflow_run.head_branch == 'consumer-saas'",
                      'github.event.workflow_run.head_repository.full_name == github.repository'):
            self.assertIn(guard, text)
        self.assertIn('persist-credentials: false', text)
        self.assertNotRegex(text, r'download-artifact|actions/cache|cache:|head_sha|head_commit|ref: \$\{\{')
        self.assertIn('run: python -m rafii_control.ci_evidence', text)
        self.assertIn('cancel-in-progress: false', text)

    def test_migration_071_is_additive_scoped_and_reapplicable_by_construction(self):
        sql = (ROOT / 'migrations/postriff/071_founder_engineering_evidence.sql').read_text()
        code = re.sub(r'--[^\n]*', '', sql).lower()
        self.assertRegex(sql, r'(?m)^begin;$')
        self.assertRegex(sql, r'(?m)^commit;$')
        self.assertNotRegex(code, r'\b(drop table|drop policy|alter policy|truncate|delete from|create role|alter role|security definer)\b')
        grants = re.findall(r'(?m)^grant [^\n]*$', code)
        self.assertTrue(grants and all(line.rstrip(';').endswith('to rafii_control_ingest') for line in grants), grants)
        self.assertNotRegex(code, r'grant[^;]*\b(delete|truncate|references|trigger|all)\b')
        for policy in ('rc_github_ci_insert', 'control_ingest_insert', 'control_ingest_update'):
            self.assertIn(f"policyname='{policy}'", code, 'each policy is created only when absent')
        for constraint in re.findall(r'add constraint (\w+)', code):
            self.assertIn(f'drop constraint if exists {constraint};', code)
        self.assertIn("conname not like 'rc\\_github\\_%'", code, "052's unnamed checks are found by expression, never this file's own")
        self.assertIn('`071_founder_engineering_evidence`', (ROOT / 'docs/postriff-migration-numbering.md').read_text())


class SummaryTests(unittest.TestCase):
    def test_summarize_rederives_every_count_and_rejects_tampering(self):
        evaluation = evaluate()
        self.assertTrue(ci_evidence.summarize(evaluation)['valid'])
        cases = {
            'count': lambda item: item.update(requiredCount=4),
            'required_flag': lambda item: item['checks'][1].update(required=False),
            'success_without_outcome': lambda item: item['checks'][0].update(outcome='failure'),
            'attested_without_conclusion': lambda item: item['checks'][4].update(conclusion=None, outcome='incomplete'),
            'stale_qualification': lambda item: item['checks'][0].update(conclusion='failure', outcome='failure'),
            'schema': lambda item: item.update(schemaVersion=1),
            'provenance': lambda item: item.update(provenance='synthetic'),
            'order': lambda item: item['checks'].reverse(),
            'repository': lambda item: item.update(repository='someone/PostRiff'),
            'conclusion': lambda item: item['checks'][0].update(conclusion='stale'),
            'missing_checks': lambda item: item.pop('checks'),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                tampered = copy.deepcopy(evaluation)
                change(tampered)
                summary = ci_evidence.summarize(tampered)
                self.assertEqual((summary['valid'], summary['requiredCount'], summary['qualification']), (False, None, 'invalid_manifest'))
        self.assertFalse(ci_evidence.summarize(evaluation, 'b' * 40)['valid'], 'a manifest speaks only for its own SHA')
        self.assertFalse(ci_evidence.summarize(None)['valid'])


class EvidenceStore:
    """The two reads GET /engineering and GET /engineering/checks make, over in-memory rows (newest first, like the SQL)."""
    environment = 'production'

    def __init__(self, rows, snapshots):
        self.rows, self.snapshots = rows, snapshots

    def read(self, kind, identifier=None):
        return copy.deepcopy(self.rows) if kind == 'engineering' else []

    def check_snapshots(self):
        return copy.deepcopy(self.snapshots)

    def check_snapshot(self, identifier):
        return next((copy.deepcopy(row['payload']) for row in self.snapshots if row['id'] == identifier), None)


def read_rows(evaluation, environment='production'):
    """engineering_evidence rows as the reader's SELECT returns them."""
    keys = ('id', 'kind', 'provider', 'external_id', 'exact_sha', 'state', 'conclusion', 'failure_class', 'attested', 'required', 'observed_at')
    return [{key: row[key] for key in keys} for row in ci_evidence.evidence_rows(evaluation, environment)]


def snapshot(evaluation, provenance='ci_attested', observed_at=None):
    return dict(id=str(uuid.uuid4()), exact_sha=evaluation['exactSha'], provenance=provenance, observed_at=observed_at or evaluation['observedAt'], payload=evaluation)


class EngineeringReadTests(unittest.TestCase):
    """GET /engineering and /engineering/checks over CI evidence: 'checks_passed' only when the newest trusted manifest for
    the exact SHA qualifies every required row."""

    def setUp(self):
        self.evaluation = evaluate()
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'engineering.read', 'metrics.query']},
                          'session': {'environment': 'production'}}

    def dispatch(self, path, rows, snapshots):
        return QueryService(EvidenceStore(rows, snapshots)).dispatch(path, {}, self.principal, str(uuid.uuid4()))

    def test_a_qualified_ci_sha_reads_checks_passed(self):
        rows, manifest = read_rows(self.evaluation), snapshot(self.evaluation)
        result = self.dispatch('/engineering', rows, [manifest])
        self.assertEqual({row['state'] for row in result['evidence']}, {'checks_passed'})
        self.assertEqual({row['qualification'] for row in result['evidence']}, {'trusted_required_check_manifest_qualified'})
        self.assertFalse(any('observed_stage' in row for row in result['evidence']))
        self.assertEqual(result['verdict'], dict(sha=M, state='checks_passed', requiredCount=5, observedRequired=5, manifestId=manifest['id'], manifestProvenance='ci_attested'))
        self.assertEqual((result['checksDispatchEnabled'], result['patchEnabled']), (False, False))
        checks = self.dispatch('/engineering/checks', rows, [manifest])
        entry = checks['snapshots'][0]
        self.assertEqual((entry['exactSha'], entry['provenance'], entry['trusted']), (M, 'ci_attested', True))
        self.assertEqual((entry['qualification']['requiredCount'], entry['qualification']['qualification']), (5, 'required_checks_succeeded'))
        self.assertEqual([check['name'] for check in entry['qualification']['checks']], KEYS)
        self.assertEqual(checks['trustedProvenance'], list(TRUSTED_MANIFEST_PROVENANCE))
        self.assertEqual(entry['coverage']['scope'], 'exact_sha_and_merged_pull_request_head_runs')

    def test_anything_short_of_a_qualified_manifest_reads_suspected(self):
        rows, manifest = read_rows(self.evaluation), snapshot(self.evaluation)
        exempt_routes = load_routes()
        exempt_routes[runs_key(H)]['workflow_runs'] = [run for run in exempt_routes[runs_key(H)]['workflow_runs'] if run['id'] != 1002]
        exempt_routes[runs_key(H)]['total_count'] = 3
        exempt_routes[FILES_KEY] = [{'filename': 'web/src/app/page.tsx'}]
        newer = '2026-10-01T10:10:00+00:00'
        broken = copy.deepcopy(self.evaluation)
        broken['requiredCount'] = 4
        pending = copy.deepcopy(rows)
        pending[-1].update(state='suspected', attested=False, conclusion=None)
        cases = {
            'no manifest': (rows, []),
            'untrusted provenance': (rows, [snapshot(self.evaluation, provenance='synthetic')]),
            'unadmitted capture': (rows, [snapshot(self.evaluation, provenance='provider_observed_test')]),
            'newer invalid manifest is not outvoted by an older valid one': (rows, [snapshot(broken, observed_at=newer), manifest]),
            'manifest of another SHA': (rows, [dict(manifest, exact_sha='9' * 40)]),
            'count mismatch': (rows, [snapshot(evaluate(exempt_routes))]),
            'one required row pending': (pending, [manifest]),
            'one required row missing': (rows[:-1], [manifest]),
        }
        for name, (case_rows, snapshots) in cases.items():
            with self.subTest(case=name):
                result = self.dispatch('/engineering', case_rows, snapshots)
                self.assertEqual(result['verdict']['state'], 'suspected')
                self.assertEqual({row['state'] for row in result['evidence']}, {'suspected'})
                claimed = [row for row in result['evidence'] if 'observed_stage' in row]
                self.assertTrue(claimed and all(row['observed_stage'] == 'checks_passed' and row['qualification'] == 'trusted_required_check_manifest_not_qualified' for row in claimed))
        untrusted = self.dispatch('/engineering/checks', rows, [snapshot(self.evaluation, provenance='synthetic'), snapshot(broken)])['snapshots']
        self.assertEqual([entry['trusted'] for entry in untrusted], [False, False])
        self.assertIsNone(untrusted[1]['qualification']['requiredCount'])

    def test_the_newest_sha_is_judged_and_an_older_qualified_sha_keeps_its_rows(self):
        newer = '9' * 40
        older_rows = read_rows(self.evaluation)
        newer_rows = [dict(row, id=str(uuid.uuid4()), exact_sha=newer, external_id=row['external_id'].replace(M, newer), state='suspected', attested=False,
                           conclusion=None, observed_at='2026-10-01T11:00:00+00:00') for row in older_rows]
        result = self.dispatch('/engineering', newer_rows + older_rows, [snapshot(self.evaluation)])
        self.assertEqual((result['verdict']['sha'], result['verdict']['state'], result['verdict']['requiredCount']), (newer, 'suspected', None))
        self.assertEqual({row['state'] for row in result['evidence'] if row['exact_sha'] == M}, {'checks_passed'})
        self.assertEqual(self.dispatch('/engineering', [], [])['verdict'],
                         dict(sha=None, state='suspected', requiredCount=None, observedRequired=0, manifestId=None, manifestProvenance=None))

    def test_ci_manifests_feed_neither_the_check_failures_metric_nor_github_source_health(self):
        manifest = snapshot(self.evaluation)
        service = QueryService(EvidenceStore([], [manifest]))
        query = dict(metricIds=['check_failures'], interval={'start': '2026-09-30T00:00:00Z', 'end': '2026-10-02T00:00:00Z', 'timeZone': 'UTC'},
                     groupBy=['suite', 'failure_class'], filters=[], comparison='none', limit=100)
        with self.assertRaisesRegex(ControlError, 'VALIDATION_FAILED'):
            service.snapshot_rows(manifest['id'], query, self.principal)
        github = next(row for row in service.source_health() if row['source_id'] == 'github')
        self.assertEqual(github['state'], 'unavailable')


class FakeConnection:
    """A scripted psycopg-like connection: answers the login/role checks and the newest-manifest lookup, records the rest."""

    def __init__(self, *, privileged=False, inherits=False, role='rafii_control_ingest', latest=None, conflict=False):
        self.privileged, self.inherits, self.role, self.latest, self.conflict = privileged, inherits, role, latest, conflict
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if 'FROM pg_roles WHERE rolname=session_user' in statement:
            result = (self.privileged,)
        elif statement.startswith('SELECT has_table_privilege(session_user'):
            result = (self.inherits,)
        elif 'FROM pg_roles WHERE rolname=current_user' in statement:
            result = (self.role, False)
        elif statement == ci_evidence.UPSERT:
            result = None if self.conflict else (params[0],)
        elif statement == ci_evidence.LATEST:
            result = None if self.latest is None else (self.latest,)
        elif statement == ci_evidence.SNAPSHOT:
            result = (params[0],)
        else:
            result = None
        return type('Cursor', (), {'fetchone': staticmethod(lambda: result)})()


def fail_connect():
    raise AssertionError('the database must not be contacted')


CONFIGURED = {'RAFII_ENGINEERING_INGEST_DSN': 'host=db.invalid user=ingest dbname=postgres application_name=PRIVATE_DSN_CANARY',
              'RAFII_ENGINEERING_ENVIRONMENT': 'production', 'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/consumer-saas',
              'GITHUB_REPOSITORY': 'dev-james0723/PostRiff', 'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
              'GITHUB_WORKFLOW_REF': 'dev-james0723/PostRiff/.github/workflows/founder-engineering-evidence.yml@refs/heads/consumer-saas'}


class WriteAndEntryPointTests(unittest.TestCase):
    def test_write_assumes_the_ingest_role_upserts_rows_and_inserts_only_a_changed_manifest(self):
        evaluation = evaluate()
        con = FakeConnection()
        result = ci_evidence.write('host=db.invalid', 'production', evaluation, connect=lambda: con)
        self.assertEqual(result['rows'], 5)
        self.assertEqual(result['snapshot'], next(params[0] for statement, params in con.statements if statement == ci_evidence.SNAPSHOT))
        statements = [statement for statement, _ in con.statements]
        role_at = statements.index('SET LOCAL ROLE rafii_control_ingest')
        self.assertLess(statements.index('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=session_user'), role_at)
        permission_at = statements.index("SELECT has_table_privilege(session_user,'rafii_control.engineering_evidence','INSERT')")
        environment_at = statements.index("SELECT set_config('rafii_control.environment',%s,true)")
        self.assertLess(role_at, permission_at, 'a SET-only login cannot resolve the private schema before assuming its role')
        self.assertLess(permission_at, environment_at)
        self.assertEqual(con.statements[environment_at][1], ('production',))
        self.assertLess(environment_at, statements.index(ci_evidence.UPSERT))
        upserts = [params for statement, params in con.statements if statement == ci_evidence.UPSERT]
        self.assertEqual([params[4] for params in upserts], [f'ci/{M}/{key}' for key in KEYS])
        self.assertTrue(all(params[1] == 'production' and params[5] == M and params[6] == 'checks_passed' for params in upserts))
        self.assertLess(max(i for i, s in enumerate(statements) if s == ci_evidence.UPSERT), statements.index(ci_evidence.SNAPSHOT))
        snapshot_params = next(params for statement, params in con.statements if statement == ci_evidence.SNAPSHOT)
        self.assertEqual((snapshot_params[1], snapshot_params[3], snapshot_params[4]), ('production', M, 'ci_attested'))
        self.assertRegex(snapshot_params[6], '^[0-9a-f]{64}$')
        unchanged = FakeConnection(latest=evaluation['evaluationDigest'])
        self.assertEqual(ci_evidence.write('host=db.invalid', 'production', evaluation, connect=lambda: unchanged), {'rows': 5, 'snapshot': None})
        self.assertNotIn(ci_evidence.SNAPSHOT, [statement for statement, _ in unchanged.statements])
        for con, message in ((FakeConnection(privileged=True), 'not a privileged role'), (FakeConnection(inherits=True), 'NOINHERIT'),
                             (FakeConnection(role='postgres'), 'could not assume'), (FakeConnection(conflict=True), 'another SHA')):
            with self.subTest(message=message), self.assertRaisesRegex(ci_evidence.IngestRefused, message):
                ci_evidence.write('host=db.invalid', 'production', evaluation, connect=lambda: con)
        privileged = FakeConnection(privileged=True)
        with self.assertRaises(ci_evidence.IngestRefused):
            ci_evidence.write('host=db.invalid', 'production', evaluation, connect=lambda: privileged)
        self.assertNotIn('SET LOCAL ROLE rafii_control_ingest', [statement for statement, _ in privileged.statements])
        with self.assertRaises(ValueError):
            ci_evidence.write('host=db.invalid', 'qa', evaluation, connect=fail_connect)

    def test_without_the_secret_it_prints_not_configured_dry_runs_and_passes(self):
        out = []
        self.assertEqual(ci_evidence.main({'GITHUB_TOKEN': 'unused'}, client=FakeGitHub(load_routes()), connect=fail_connect, out=out.append), 0)
        self.assertTrue(out[0].startswith('::notice title=Founder engineering evidence not configured::RAFII_ENGINEERING_INGEST_DSN is not set'))
        self.assertIn('Overall: required checks succeeded (5 required).', out)
        out = []
        self.assertEqual(ci_evidence.main({}, out=out.append), 0)
        self.assertEqual(len(out), 1, 'no token: the notice alone')
        out = []
        self.assertEqual(ci_evidence.main({}, client=FakeGitHub({}), connect=fail_connect, out=out.append), 0)
        self.assertEqual(out[-1], '::warning title=Founder engineering evidence dry run unavailable::github_http_404')

    def test_configured_runs_record_and_print_codes_and_classes_only(self):
        out, con = [], FakeConnection()
        self.assertEqual(ci_evidence.main(CONFIGURED, client=FakeGitHub(load_routes()), connect=lambda: con, out=out.append), 0, out)
        self.assertEqual(out[-1], '::notice title=Founder engineering evidence (production)::7777777: required checks succeeded '
                                  '(5 required checks; new manifest recorded).')
        payload = next(params for statement, params in con.statements if statement == ci_evidence.SNAPSHOT)[7].obj
        self.assertEqual({key: payload['collector'][key] for key in ('runId', 'runAttempt', 'event')}, {'runId': 123, 'runAttempt': 2, 'event': 'schedule'})

        class ServerError(Exception):
            pass

        def broken():
            raise ServerError('PRIVATE_SERVER_CANARY: role "ingest" does not exist')
        cases = [
            (dict(connect=broken), '::error title=Founder engineering evidence cannot write::ServerError'),
            (dict(connect=lambda: FakeConnection(privileged=True)), '::error title=Founder engineering evidence refused the login::Use the dedicated CI ingest login, not a privileged role.'),
            (dict(connect=fail_connect, client=FakeGitHub({})), '::error title=Founder engineering evidence cannot read GitHub::github_http_404'),
        ]
        for options, expected in cases:
            with self.subTest(expected=expected):
                out = []
                options.setdefault('client', FakeGitHub(load_routes()))
                self.assertEqual(ci_evidence.main(CONFIGURED, out=out.append, **options), 1)
                self.assertEqual(out[-1], expected)
                self.assertNotIn('PRIVATE_', '\n'.join(out))
        out = []
        self.assertEqual(ci_evidence.main({**CONFIGURED, 'RAFII_ENGINEERING_ENVIRONMENT': 'qa'}, client=FakeGitHub({}), connect=fail_connect, out=out.append), 1)
        self.assertTrue(out[0].startswith('::error title=Founder engineering evidence misconfigured::'))
        out = []
        self.assertEqual(ci_evidence.main({key: value for key, value in CONFIGURED.items()}, connect=fail_connect, out=out.append), 1, 'configured without a token')
        self.assertEqual(out[-1], '::error title=Founder engineering evidence misconfigured::GITHUB_TOKEN is not available to the job.')

    def test_it_refuses_to_write_from_pull_requests_forks_or_other_branches(self):
        for change in ({'GITHUB_REF': 'refs/heads/feature'}, {'GITHUB_REF': 'refs/pull/90/merge'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                       {'GITHUB_EVENT_NAME': 'pull_request_target'}, {'GITHUB_REPOSITORY': 'someone/PostRiff'}):
            with self.subTest(change=change):
                client, out = FakeGitHub(load_routes()), []
                self.assertEqual(ci_evidence.main({**CONFIGURED, **change}, client=client, connect=fail_connect, out=out.append), 1)
                self.assertEqual(client.calls, [])
                self.assertTrue(out[0].startswith('::error title=Founder engineering evidence refused::'))

    def test_the_github_client_sends_the_token_only_as_a_header_and_maps_errors_to_codes(self):
        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, limit):
                return self.body[:limit]
        seen = []

        def opener(request, timeout):
            seen.append((request, timeout))
            return Response(b'{"ok": true}')
        self.assertEqual(ci_evidence.GitHub('token-canary', opener=opener).get('/repos/x', {'a': 1}), {'ok': True})
        request, timeout = seen[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/x?a=1')
        self.assertEqual(request.get_header('Authorization'), 'Bearer token-canary')
        self.assertLessEqual(timeout, 15)

        def failing(error):
            def open_(request, timeout):
                raise error
            return open_
        for error, code in ((HTTPError('https://api.github.com/x', 403, 'PRIVATE_REASON', {}, io.BytesIO(b'PRIVATE_BODY')), 'github_http_403'),
                            (URLError('PRIVATE_HOST'), 'github_unreachable'), (TimeoutError('PRIVATE_TIMEOUT'), 'github_unreachable')):
            with self.subTest(code=code), self.assertRaises(ci_evidence.CollectorError) as caught:
                ci_evidence.GitHub('t', opener=failing(error)).get('/x')
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('PRIVATE', str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
        for body, code in ((b'x' * 11, 'github_response_too_large'), (b'not json', 'github_response_invalid')):
            with self.subTest(code=code), self.assertRaises(ci_evidence.CollectorError) as caught:
                ci_evidence.GitHub('t', opener=lambda request, timeout, body=body: Response(body), max_bytes=10).get('/x')
            self.assertEqual(caught.exception.code, code)


if __name__ == '__main__':
    unittest.main()
