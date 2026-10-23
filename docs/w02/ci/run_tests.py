"""Offline tests of docs/w02/ci/discord-lane-capacity.yml.txt and make_request_branch.sh (nothing leaves this machine).

The workflow's run blocks are executed with bash against local git repositories: the GitHub URL is rewritten to a local
bare repository (url.<path>.insteadOf in a private git config), so every fetch is local. Shape checks pin what must
never change: push trigger on claude/discord-capacity-run-* only, contents: read, no secret, no environment, no generic
checkout, every action pinned to a reviewed commit, PostgreSQL 17 from the signed repository as the qualification
workflow installs it, PgBouncer as the pooler, the harness run unchanged. Optional: action-validator and shellcheck
(paths in ACTION_VALIDATOR and SHELLCHECK, or found on PATH).

  python3 docs/w02/ci/run_tests.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, 'discord-lane-capacity.yml.txt')
MAKER = os.path.join(HERE, 'make_request_branch.sh')
GITHUB_URL = 'https://github.com/dev-james0723/PostRiff.git'
HARNESS_BRANCH = 'claude/discord-w02-capacity-20261023'
ALLOWED_ACTIONS = {
    'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97',   # v7.0.0, as consumer-ready and qualification
    'actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a',  # as agent-ui and rafii-control
}
TEXT = open(WORKFLOW).read()
DOC = yaml.safe_load(TEXT)
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(('ok   ' if ok else 'FAIL ') + name + (('  -- ' + detail) if detail and not ok else ''))


def step(job, prefix):
    matches = [s for s in DOC['jobs'][job]['steps'] if s.get('name', '').startswith(prefix)]
    assert len(matches) == 1, (job, prefix)
    return matches[0]


def git(*args, cwd=None, env=None):
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


# --- shape -----------------------------------------------------------------------------------------------------------

def shape():
    on = DOC.get('on', DOC.get(True))
    check('trigger is push on claude/discord-capacity-run-* only', on == {'push': {'branches': ['claude/discord-capacity-run-*']}}, repr(on))
    check('top-level permissions are contents: read only', DOC.get('permissions') == {'contents': 'read'})
    check('no job widens permissions', all('permissions' not in job for job in DOC['jobs'].values()))
    check('no secret is referenced', 'secrets.' not in TEXT and 'secrets[' not in TEXT)
    check('no environment is used', all('environment' not in job for job in DOC['jobs'].values()))
    check('no other trigger (dispatch, pull_request_target, schedule)', not re.search(r'workflow_dispatch|pull_request|schedule:|workflow_run', TEXT))
    uses = [s['uses'] for job in DOC['jobs'].values() for s in job['steps'] if 'uses' in s]
    check('no generic checkout (orphan vendor gitlinks)', not any(u.startswith('actions/checkout') for u in uses))
    check('every action pinned to a reviewed commit', all(u in ALLOWED_ACTIONS for u in uses), repr(uses))
    plan = DOC['jobs']['plan']
    check('the plan job runs only in the repository and for the owner', plan.get('if') == "github.repository == 'dev-james0723/PostRiff' && github.actor == 'dev-james0723'")
    check('every job has a time limit within the 6-hour hosted limit', all(0 < job.get('timeout-minutes', 0) <= 360 for job in DOC['jobs'].values()))
    check('standard hosted runner', all(job.get('runs-on') == 'ubuntu-24.04' for job in DOC['jobs'].values()))
    cap = DOC['jobs']['capacity']
    check('the matrix comes from the plan only', cap['strategy']['matrix'] == {'include': '${{ fromJSON(needs.plan.outputs.matrix) }}'} and cap['needs'] == 'plan')
    install = step('capacity', 'PostgreSQL 17')['run']
    for line in ('sudo apt-get install -y postgresql-common', 'sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y',
                 'sudo apt-get install -y postgresql-17 pgbouncer', 'sudo chmod 1777 /var/run/postgresql'):
        check('database install: ' + line, line in install)
    run = step('capacity', 'Run the scenario')['run']
    check('the harness runs unchanged: run --scenario through PgBouncer with the pool size',
          'harness/scripts/discord_lane_capacity_run.py run --scenario "$SCENARIO"' in run
          and '--pooler pgbouncer --pgbouncer-bin /usr/sbin/pgbouncer --max-db-connections "$POOL"' in run)
    upload = step('capacity', 'Keep the receipt')
    paths = upload['with']['path']
    check('the artifact never includes the per-run environment files', 'env-' not in paths and 'env*' not in paths)
    check('the receipt goes to the step summary', 'GITHUB_STEP_SUMMARY' in step('capacity', 'The receipt')['run'])
    fetch = step('capacity', 'Fetch the harness')['run']
    check('each fetched tree is verified at its exact SHA and clean', 'test "$(git -C "$dir" rev-parse HEAD)" = "$want"' in fetch
          and 'status --porcelain' in fetch)


# --- the request reader ------------------------------------------------------------------------------------------------

class Fixture:
    """A local bare repository standing in for GitHub, with the harness branch and request branches."""
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='cap-ci-tests-')
        self.bare = os.path.join(self.root, 'origin.git')
        git('init', '-q', '--bare', self.bare)
        self.gitconfig = os.path.join(self.root, 'gitconfig')
        with open(self.gitconfig, 'w') as handle:
            handle.write('[url "%s"]\n\tinsteadOf = %s\n[user]\n\tname = t\n\temail = t@example.invalid\n'
                         '[init]\n\tdefaultBranch = main\n' % (self.bare, GITHUB_URL))
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': self.gitconfig, 'GIT_CONFIG_NOSYSTEM': '1'}
        work = os.path.join(self.root, 'harness-work')
        git('init', '-q', work, env=self.env)
        self.harness = []
        for number in range(3):
            with open(os.path.join(work, 'f%d' % number), 'w') as handle:
                handle.write(str(number))
            git('add', '-A', cwd=work, env=self.env)
            git('commit', '-q', '-m', 'h%d' % number, cwd=work, env=self.env)
            self.harness.append(git('rev-parse', 'HEAD', cwd=work, env=self.env))
        git('push', '-q', self.bare, 'HEAD:refs/heads/' + HARNESS_BRANCH, cwd=work, env=self.env)
        git('checkout', '-q', '--orphan', 'other', cwd=work, env=self.env)
        with open(os.path.join(work, 'x'), 'w') as handle:
            handle.write('x')
        git('add', '-A', cwd=work, env=self.env)
        git('commit', '-q', '-m', 'unrelated', cwd=work, env=self.env)
        self.unrelated = git('rev-parse', 'HEAD', cwd=work, env=self.env)
        git('push', '-q', self.bare, 'HEAD:refs/heads/unrelated', cwd=work, env=self.env)

    def request(self, request, *, files=None, age=0):
        """A request commit like make_request_branch.sh builds, pushed to the fake origin; returns its SHA."""
        work = tempfile.mkdtemp(dir=self.root)
        git('init', '-q', work, env=self.env)
        os.makedirs(os.path.join(work, '.github/workflows'))
        os.makedirs(os.path.join(work, 'capacity'))
        shutil.copy(WORKFLOW, os.path.join(work, '.github/workflows/discord-lane-capacity.yml'))
        with open(os.path.join(work, 'capacity/REQUEST.json'), 'w') as handle:
            handle.write(request if isinstance(request, str) else json.dumps(request))
        with open(os.path.join(work, 'vercel.json'), 'w') as handle:
            handle.write('{"git": {"deploymentEnabled": false}}\n')
        for name in files or ():
            with open(os.path.join(work, name), 'w') as handle:
                handle.write('extra')
        git('add', '-A', cwd=work, env=self.env)
        stamp = '%d +0000' % (time.time() - age)
        git('commit', '-q', '-m', 'request', cwd=work, env={**self.env, 'GIT_COMMITTER_DATE': stamp, 'GIT_AUTHOR_DATE': stamp})
        sha = git('rev-parse', 'HEAD', cwd=work, env=self.env)
        git('push', '-q', '-f', self.bare, 'HEAD:refs/heads/request-%s' % sha[:8], cwd=work, env=self.env)
        return sha

    def run_block(self, script, env, cwd):
        output = os.path.join(cwd, 'github-output')
        open(output, 'w').close()
        done = subprocess.run(['bash', '-e', '-c', script], cwd=cwd, capture_output=True, text=True,
                              env={**self.env, 'GITHUB_REPOSITORY': 'dev-james0723/PostRiff', 'GITHUB_OUTPUT': output,
                                   'HARNESS_BRANCH': HARNESS_BRANCH, **env})
        values = {}
        for line in open(output).read().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                values[key] = value
        return done.returncode, done.stdout + done.stderr, values

    def read_request(self, request, branch, **kw):
        sha = self.request(request, **kw)
        cwd = tempfile.mkdtemp(dir=self.root)
        fetch = step('plan', 'Fetch the request commit')['run']
        code, out, _ = self.run_block(fetch, {'REQUEST_SHA': sha}, cwd)
        assert code == 0, out
        return self.run_block(step('plan', 'Read the request')['run'], {'REF_NAME': branch}, cwd)


def request_reader(fix):
    tree, rc = 'a' * 40, '2a5a523d788eef67a5c7dbed609a98efa6650eef'
    good = {'profile': 's1', 'sha': tree, 'baseline_sha': rc, 'harness_sha': fix.harness[-1], 'pools': '15,30,60',
            'db_latency_ms': '2'}
    code, out, values = fix.read_request(good, 'claude/discord-capacity-run-s1-test1')
    check('a good request is accepted', code == 0, out[-600:])
    matrix = json.loads(values.get('matrix', '[]'))
    check('the matrix is the profile times the pools', matrix == [{'scenario': 'S1', 'pool': 15}, {'scenario': 'S1', 'pool': 30},
                                                                   {'scenario': 'S1', 'pool': 60}], repr(matrix))
    check('the outputs carry the exact SHAs and latency', values.get('sha') == tree and values.get('baseline') == rc
          and values.get('harness') == fix.harness[-1] and values.get('latency') == '2')
    code, _, values = fix.read_request({**good, 'profile': 'release', 'pools': '20'}, 'claude/discord-capacity-run-release-x')
    names = [m['scenario'] for m in json.loads(values.get('matrix', '[]'))]
    check('the release profile has every scenario once', code == 0 and len(names) == 16 and len(set(names)) == 16
          and {'S1', 'S2', 'S0-100', 'S0-250', 'baseline', 'Fcrash', 'Nceiling'} <= set(names), repr(names))
    code, _, values = fix.read_request({**good, 'harness_sha': fix.harness[0], 'pools': '20'}, 'claude/discord-capacity-run-s1-old')
    check('an older harness commit on the branch is accepted', code == 0)
    bad = [
        ('a short tree SHA', {**good, 'sha': 'abc'}, 'claude/discord-capacity-run-s1-t'),
        ('an upper-case tree SHA', {**good, 'sha': 'A' * 40}, 'claude/discord-capacity-run-s1-t'),
        ('a tree SHA with a line break', {**good, 'sha': tree + '\nx=y'}, 'claude/discord-capacity-run-s1-t'),
        ('a missing baseline', {k: v for k, v in good.items() if k != 'baseline_sha'}, 'claude/discord-capacity-run-s1-t'),
        ('a harness commit not on the harness branch', {**good, 'harness_sha': fix.unrelated}, 'claude/discord-capacity-run-s1-t'),
        ('a harness SHA that does not exist', {**good, 'harness_sha': 'b' * 40}, 'claude/discord-capacity-run-s1-t'),
        ('a profile that differs from the branch', {**good, 'profile': 's2'}, 'claude/discord-capacity-run-s1-t'),
        ('an unknown profile', {**good, 'profile': 'all'}, 'claude/discord-capacity-run-all-t'),
        ('a pool of 10', {**good, 'pools': '10'}, 'claude/discord-capacity-run-s1-t'),
        ('a pool of 121', {**good, 'pools': '121'}, 'claude/discord-capacity-run-s1-t'),
        ('five pools', {**good, 'pools': '15,20,30,40,60'}, 'claude/discord-capacity-run-s1-t'),
        ('a pool list with a semicolon', {**good, 'pools': '15;20'}, 'claude/discord-capacity-run-s1-t'),
        ('a latency of 100 ms', {**good, 'db_latency_ms': '100'}, 'claude/discord-capacity-run-s1-t'),
        ('a latency with two decimals', {**good, 'db_latency_ms': '1.25'}, 'claude/discord-capacity-run-s1-t'),
        ('a numeric (not string) pool', {**good, 'pools': 20}, 'claude/discord-capacity-run-s1-t'),
        ('a branch with an upper-case suffix', good, 'claude/discord-capacity-run-s1-Test'),
        ('a branch with a long suffix', good, 'claude/discord-capacity-run-s1-abcdefghijklm'),
    ]
    for name, request, branch in bad:
        code, out, values = fix.read_request(request, branch)
        check('refused: ' + name, code != 0 and 'matrix' not in values, out[-300:])
    code, out, _ = fix.read_request('not json', 'claude/discord-capacity-run-s1-t')
    check('refused: a request that is not JSON', code != 0)
    code, out, _ = fix.read_request(good, 'claude/discord-capacity-run-s1-t', files=['extra.sh'])
    check('refused: a request branch with an extra file', code != 0 and 'unexpected files' in out, out[-300:])
    code, out, _ = fix.read_request(good, 'claude/discord-capacity-run-s1-t', age=13 * 3600)
    check('refused: a request older than twelve hours', code != 0 and 'twelve hours' in out, out[-300:])


def fetch_step(fix):
    cwd = tempfile.mkdtemp(dir=fix.root)
    block = step('capacity', 'Fetch the harness')['run']
    code, out, _ = fix.run_block(block, {'HARNESS_SHA': fix.harness[1], 'TREE_SHA': fix.unrelated}, cwd)
    ok = code == 0 and git('-C', os.path.join(cwd, 'harness'), 'rev-parse', 'HEAD') == fix.harness[1] \
        and git('-C', os.path.join(cwd, 'tree'), 'rev-parse', 'HEAD') == fix.unrelated
    check('the fetch step checks out the harness and the tree at their exact SHAs', ok, out[-400:])
    cwd = tempfile.mkdtemp(dir=fix.root)
    code, out, _ = fix.run_block(block, {'HARNESS_SHA': 'c' * 40, 'TREE_SHA': fix.unrelated}, cwd)
    check('the fetch step fails on a SHA that does not exist', code != 0)


# --- the request-branch script ------------------------------------------------------------------------------------------

def maker(fix):
    tree, harness = 'd' * 40, 'e' * 40
    env = {**fix.env, 'TMPDIR': fix.root}
    done = subprocess.run(['bash', MAKER, 's2', 'abc1', tree, harness, '--pools', '15,60', '--latency', '5'],
                          capture_output=True, text=True, env=env)
    check('make_request_branch.sh builds a request without pushing', done.returncode == 0 and 'pushed' not in done.stdout, done.stderr)
    work = re.search(r'work tree:\s+(\S+)', done.stdout).group(1) if done.returncode == 0 else None
    if work:
        files = git('ls-files', cwd=work, env=fix.env).split('\n')
        check('the request commit holds exactly the workflow, the request and vercel.json',
              files == ['.github/workflows/discord-lane-capacity.yml', 'capacity/REQUEST.json', 'vercel.json'], repr(files))
        check('the workflow on the request branch is this file byte for byte',
              open(os.path.join(work, '.github/workflows/discord-lane-capacity.yml')).read() == TEXT)
        request = json.loads(open(os.path.join(work, 'capacity/REQUEST.json')).read())
        check('the request records profile, SHAs, pools and latency',
              request == {'profile': 's2', 'sha': tree, 'baseline_sha': '2a5a523d788eef67a5c7dbed609a98efa6650eef',
                          'harness_sha': harness, 'pools': '15,60', 'db_latency_ms': '5'}, repr(request))
        check('vercel.json keeps Git deployments off', json.loads(open(os.path.join(work, 'vercel.json')).read()) == {'git': {'deploymentEnabled': False}})
        check('the branch name matches the trigger', git('rev-parse', '--abbrev-ref', 'HEAD', cwd=work, env=fix.env) == 'claude/discord-capacity-run-s2-abc1')
        message = git('log', '-1', '--format=%B', cwd=work, env=fix.env)
        check('the commit message carries the trailers', 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>' in message
              and 'Claude-Session: https://claude.ai/code/session_01E9guaNuzCqsXR8cbB5CRhv' in message)
        check('the commit is an orphan (no history)', git('rev-list', '--count', 'HEAD', cwd=work, env=fix.env) == '1')
    for name, args in (('an unknown profile', ['all', 'x', tree, harness]), ('a bad suffix', ['s1', 'A_B', tree, harness]),
                       ('a short SHA', ['s1', 'x', 'abc', harness]), ('a bad pool', ['s1', 'x', tree, harness, '--pools', '200']),
                       ('a bad latency', ['s1', 'x', tree, harness, '--latency', 'fast']),
                       ('an unknown option', ['s1', 'x', tree, harness, '--force'])):
        done = subprocess.run(['bash', MAKER, *args], capture_output=True, text=True, env=env)
        check('make_request_branch.sh refuses ' + name, done.returncode == 2, done.stdout + done.stderr)


# --- external validators -------------------------------------------------------------------------------------------------

def validators(fix):
    validator = os.environ.get('ACTION_VALIDATOR') or shutil.which('action-validator')
    if validator and os.path.exists(validator):
        copy = os.path.join(fix.root, 'discord-lane-capacity.yml')
        shutil.copy(WORKFLOW, copy)
        done = subprocess.run([validator, copy], capture_output=True, text=True)
        check('action-validator reports nothing', done.returncode == 0 and not done.stdout.strip(), done.stdout + done.stderr)
    else:
        print('skip action-validator (set ACTION_VALIDATOR)')
    shellcheck = os.environ.get('SHELLCHECK') or shutil.which('shellcheck')
    if shellcheck and os.path.exists(shellcheck):
        done = subprocess.run([shellcheck, MAKER], capture_output=True, text=True)
        check('shellcheck: make_request_branch.sh', done.returncode == 0, done.stdout)
        for job, item in [(j, s) for j in DOC['jobs'] for s in DOC['jobs'][j]['steps'] if 'run' in s]:
            body = re.sub(r'\$\{\{[^}]*\}\}', 'x', item['run'])
            path = os.path.join(fix.root, 'block.sh')
            with open(path, 'w') as handle:
                handle.write('#!/usr/bin/env bash\n' + body)
            done = subprocess.run([shellcheck, '-s', 'bash', path], capture_output=True, text=True)
            check('shellcheck: %s / %s' % (job, item['name'][:50]), done.returncode == 0, done.stdout)
    else:
        print('skip shellcheck (set SHELLCHECK)')


def main():
    shape()
    fix = Fixture()
    try:
        request_reader(fix)
        fetch_step(fix)
        maker(fix)
        validators(fix)
    finally:
        shutil.rmtree(fix.root, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print('%d checks, %d failed' % (len(RESULTS), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
