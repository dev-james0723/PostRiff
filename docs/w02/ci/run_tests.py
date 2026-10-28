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
    # A failure must be diagnosable from the artifact alone: every child process's own output is kept.
    for name in ('seed-*.out', 'seed-plan.json', 'pooler.out', 'pgbouncer.out', 'mock.out', 'harness.log',
                 'pgbouncer/pgbouncer.log', 'postgres.log', 'admissions.jsonl', 'invocations-summary.json', 'attempts.jsonl',
                 'health-samples.jsonl'):
        check('the artifact keeps %s' % name, '${{ runner.temp }}/capacity/*/' + name in paths)
    check('every artifact path is under the run directories', all(
        line.strip().startswith('${{ runner.temp }}/capacity/*/') for line in paths.splitlines() if line.strip()))
    # The lock benchmark profile: its own step, only for its own matrix entry; the scenario step never runs for it.
    scenario_step = step('capacity', 'Run the scenario')
    bench_step = step('capacity', 'Run the coordinator lock benchmark')
    check('the scenario step does not run for the lock benchmark', scenario_step.get('if') == "matrix.scenario != 'lockbench'")
    check('the lock benchmark step runs only for the lock benchmark', bench_step.get('if') == "matrix.scenario == 'lockbench'")
    check('the lock benchmark runs the harness script on the tree under test with the pool size',
          'python -B harness/scripts/discord_lane_cap_lockbench.py --source-tree "$GITHUB_WORKSPACE/tree"' in bench_step['run']
          and '--pool-size "$POOL"' in bench_step['run'])
    check('the lock benchmark includes the reviewed 25/s policy and a Discord answer time',
          '--policy 25' in bench_step['run'] and '--think-ms' in bench_step['run'])
    for name in ('lockbench.json', 'LOCKBENCH.md'):
        check('the artifact keeps %s' % name, '${{ runner.temp }}/capacity/*/' + name in paths)
    check('the step summary carries the lock benchmark table', 'LOCKBENCH.md' in step('capacity', 'The receipt')['run'])
    check('the receipt goes to the step summary', 'GITHUB_STEP_SUMMARY' in step('capacity', 'The receipt')['run'])
    check('the baseline scenario runs on the frozen tree, every other scenario on the tree under test',
          step('capacity', 'Fetch the harness')['env']['TREE_SHA']
          == "${{ matrix.scenario == 'baseline' && needs.plan.outputs.baseline || needs.plan.outputs.sha }}")
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
    code, out, values = fix.read_request({**good, 'profile': 'lockbench', 'pools': '30'}, 'claude/discord-capacity-run-lockbench-l1')
    check('a lock benchmark request is one job per pool', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': 'lockbench', 'pool': 30}], out[-400:])
    code, out, values = fix.read_request({**good, 'profile': 'baseline', 'pools': '20'}, 'claude/discord-capacity-run-baseline-b1')
    check('a baseline request is one job and carries the frozen tree', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': 'baseline', 'pool': 20}] and values.get('baseline') == rc, out[-400:])
    code, out, values = fix.read_request({**good, 'profile': 's1levers', 'pools': '20'}, 'claude/discord-capacity-run-s1levers-d1')
    check('an s1levers request is S1 as control plus the three lever variants', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': name, 'pool': 20} for name in ('S1', 'S1-lane58', 'S1-lane70', 'S1-warm')], out[-400:])
    code, out, values = fix.read_request({**good, 'profile': 'devset', 'pools': '20'}, 'claude/discord-capacity-run-devset-d1')
    check('a devset request is the development measurement set, one job each', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': name, 'pool': 20} for name in ('S1', 'S0-100', 'Fdb', 'Fcrash', 'F429')], out[-400:])
    for profile, scenario in (('s0100', 'S0-100'), ('fdb', 'Fdb'), ('fcrash', 'Fcrash'), ('f429', 'F429')):
        code, out, values = fix.read_request({**good, 'profile': profile, 'pools': '20'}, 'claude/discord-capacity-run-%s-r1' % profile)
        check('a %s request is the %s scenario alone, to run it again' % (profile, scenario), code == 0 and json.loads(
            values.get('matrix', '[]')) == [{'scenario': scenario, 'pool': 20}], out[-400:])
    code, out, values = fix.read_request({**good, 'profile': 's2sizes', 'pools': '20'}, 'claude/discord-capacity-run-s2sizes-z1')
    check('an s2sizes request is S2 with a hot workspace of 100, 300 and 1,000 posts', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': name, 'pool': 20} for name in ('S2-100', 'S2-300', 'S2-1000')], out[-400:])
    code, out, values = fix.read_request({**good, 'profile': 's2', 'pools': '20'}, 'claude/discord-capacity-run-s2-z1')
    check('the s2 profile is still the 3,000-post S2 alone', code == 0 and json.loads(values.get('matrix', '[]')) == [
        {'scenario': 'S2', 'pool': 20}], out[-400:])
    # Every scenario a profile names must exist in the harness (a typo would only show on the runner).
    named = set()
    for line in step('plan', 'Read the request')['run'].splitlines():
        match = re.match(r"\s*[a-z0-9]+\) scenarios='([^']*)' ;;", line)
        if match:
            named.update(match.group(1).split())
    harness = subprocess.run([sys.executable, '-B', os.path.join(HERE, '..', '..', '..', 'scripts', 'discord_lane_capacity_run.py'),
                              'scenarios'], capture_output=True, text=True)
    known = {line.split()[0] for line in harness.stdout.splitlines() if line.strip() and not line.startswith('profile ')}
    check('every scenario a profile names exists in the harness', harness.returncode == 0 and (named - {'lockbench'}) <= known,
          repr(sorted(named - {'lockbench'} - known)) + harness.stderr[-300:])
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
    done = subprocess.run(['bash', MAKER, 'lockbench', 'lb1', tree, harness, '--pools', '30'], capture_output=True, text=True, env=env)
    work = re.search(r'work tree:\s+(\S+)', done.stdout).group(1) if done.returncode == 0 else None
    check('make_request_branch.sh builds a lock benchmark request', work is not None and json.loads(
        open(os.path.join(work, 'capacity/REQUEST.json')).read())['profile'] == 'lockbench'
        and git('rev-parse', '--abbrev-ref', 'HEAD', cwd=work, env=fix.env) == 'claude/discord-capacity-run-lockbench-lb1',
        done.stdout + done.stderr)
    for profile in ('s2sizes', 'devset', 'fdb', 's0100'):
        done = subprocess.run(['bash', MAKER, profile, 'p1', tree, harness], capture_output=True, text=True, env=env)
        work = re.search(r'work tree:\s+(\S+)', done.stdout).group(1) if done.returncode == 0 else None
        check('make_request_branch.sh builds a %s request' % profile, work is not None and git(
            'rev-parse', '--abbrev-ref', 'HEAD', cwd=work, env=fix.env) == 'claude/discord-capacity-run-%s-p1' % profile
            and json.loads(open(os.path.join(work, 'capacity/REQUEST.json')).read())['profile'] == profile, done.stdout + done.stderr)
    for name, args in (('an unknown profile', ['all', 'x', tree, harness]), ('a bad suffix', ['s1', 'A_B', tree, harness]),
                       ('a short SHA', ['s1', 'x', 'abc', harness]), ('a bad pool', ['s1', 'x', tree, harness, '--pools', '200']),
                       ('a bad latency', ['s1', 'x', tree, harness, '--latency', 'fast']),
                       ('an unknown option', ['s1', 'x', tree, harness, '--force'])):
        done = subprocess.run(['bash', MAKER, *args], capture_output=True, text=True, env=env)
        check('make_request_branch.sh refuses ' + name, done.returncode == 2, done.stdout + done.stderr)


# --- the scenario settings the workflow's command line reaches --------------------------------------------------------

def command_line():
    """The workflow passes the matrix pool and the request's round trip to every scenario (Fdb's own 6-connection pool and
    8 ms round trip were silently replaced by them on the first GitHub-hosted run): parse the exact arguments it passes with
    the harness's own parser, and check what each scenario ends up with."""
    sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
    try:
        import discord_lane_capacity_run as runner
    except ImportError as error:
        check('the harness imports (for the command-line checks)', False, repr(error))
        return
    line = ' '.join(re.sub(r'\\\s*\n', ' ', step('capacity', 'Run the scenario')['run']).split())
    match = re.search(r'discord_lane_capacity_run\.py (run .*?) uptime', line)
    check('the workflow runs the harness with run --scenario and the pool and round trip options', bool(match)
          and '--max-db-connections "$POOL"' in match.group(1) and '--db-latency-ms "$LATENCY"' in match.group(1), line[-300:])
    if not match:
        return

    def settings(scenario, pool='20', latency='2'):
        argv = match.group(1).replace('"$SCENARIO"', scenario).replace('"$GITHUB_WORKSPACE/tree"', '/tree')
        argv = argv.replace('"$RUNNER_TEMP/capacity"', '/out').replace('"gha-pool${POOL}"', 'gha-pool' + pool)
        argv = argv.replace('"$POOL"', pool).replace('"$LATENCY"', latency)
        args = runner.build_parser().parse_args(argv.split())
        return runner.settings_for(args.scenario, runner.overrides_from(args))
    fdb, s1 = settings('Fdb'), settings('S1')
    check('Fdb keeps its 6-connection pool, 8 ms round trip and 1.5 s statement timeout under the workflow\'s arguments',
          (fdb['max_db_connections'], fdb['db_latency_ms'], fdb['db_statement_timeout_ms']) == (6, 8.0, 1500), repr(fdb))
    check('the receipt is told what Fdb ignored', fdb['pinnedOverridesIgnored'] == {'max_db_connections': 20, 'db_latency_ms': 2.0},
          repr(fdb.get('pinnedOverridesIgnored')))
    check('every other scenario takes the matrix pool and the request\'s round trip',
          all(settings(name)['max_db_connections'] == 20 and settings(name)['db_latency_ms'] == 2.0
              for name in runner.SCENARIOS if name != 'Fdb') and s1['pinnedOverridesIgnored'] is None)
    check('a pool of 60 and 5 ms reach S1 and are ignored by Fdb',
          (settings('S1', '60', '5')['max_db_connections'], settings('S1', '60', '5')['db_latency_ms']) == (60, 5.0)
          and settings('Fdb', '60', '5')['max_db_connections'] == 6)


# --- the multi-process seeding path ----------------------------------------------------------------------------------------

def seeding():
    """The harness's own seeding at a small scale with four processes released together (the path that failed on the
    GitHub-hosted runner), and a slice that fails on purpose: its own output must reach harness.log and the error.
    Needs PostgreSQL server binaries (POSTRIFF_PG_BIN), psycopg and the application tree; skipped otherwise."""
    root = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
    runner = os.path.join(root, 'scripts', 'discord_lane_capacity_run.py')
    try:
        import psycopg  # noqa: F401
        has_driver = True
    except ImportError:
        has_driver = False
    if not os.environ.get('POSTRIFF_PG_BIN') or not has_driver or not os.path.isdir(os.path.join(root, 'src', 'postriff_phase2')):
        print('skip the four-process seeding checks (need POSTRIFF_PG_BIN, psycopg and the application tree)')
        return

    def seed_check(label, extra_env):
        out = tempfile.mkdtemp(prefix='cap-ci-seed-')
        try:
            done = subprocess.run([sys.executable, '-B', runner, 'seed-check', '--scenario', 'smoke', '--source-tree', root,
                                   '--out', out, '--label', label, '--workspaces', '16', '--posts', '32',
                                   '--seed-processes', '4', '--lead-seconds', '30'], capture_output=True, text=True,
                                  timeout=900, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', **extra_env})
            logs = ''
            for run_dir in os.listdir(out):
                path = os.path.join(out, run_dir, 'harness.log')
                if os.path.exists(path):
                    logs += open(path).read()
            return done, logs
        finally:
            shutil.rmtree(out, ignore_errors=True)
    done, _ = seed_check('ci-tests', {})
    summary = {}
    try:
        summary = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    check('four seeding processes released together all finish', done.returncode == 0 and summary.get('posts') == 32
          and len(summary.get('slices') or []) == 4, (done.stdout + done.stderr)[-1500:])
    done, logs = seed_check('ci-fail', {'CAP_SEED_FAIL_SLICE': '2'})
    check('a failing seeding slice stops the run', done.returncode != 0)
    check("the failing slice's own output is in harness.log", 'seeding process seed-2 exited with 1' in logs
          and 'seeding slice 2/4 fails on purpose' in logs, logs[-1200:])
    check("the error names the slice and quotes the end of its output",
          'seed-2 exit 1' in done.stderr and 'seed-2.out ends with' in done.stderr
          and 'fails on purpose' in done.stderr, done.stderr[-1200:])
    # The lock benchmark at the smallest size: it runs, accumulates configurations, writes its table.
    out = tempfile.mkdtemp(prefix='cap-ci-bench-')
    try:
        bench = [sys.executable, '-B', os.path.join(root, 'scripts', 'discord_lane_cap_lockbench.py'), '--source-tree', root,
                 '--out', out, '--processes', '1,2', '--latency-ms', '0', '--seconds', '2']
        first = subprocess.run(bench, capture_output=True, text=True, timeout=600, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        second = subprocess.run(bench + ['--policy', '25'], capture_output=True, text=True, timeout=600,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        store = os.path.join(out, 'lockbench.json')
        runs = json.loads(open(store).read())['runs'] if os.path.exists(store) else []
        check('the lock benchmark runs and keeps every configuration', first.returncode == 0 and second.returncode == 0
              and len(runs) == 2 and all(len(r['rows']) == 2 and all(row['admissionsPerSecond'] > 0 for row in r['rows'])
                                         for r in runs), (first.stderr + second.stderr)[-1200:])
        table = open(os.path.join(out, 'LOCKBENCH.md')).read() if os.path.exists(os.path.join(out, 'LOCKBENCH.md')) else ''
        check('the lock benchmark table names the tree and the machine', table.count('### Lock benchmark') == 2
              and 'Tree `' in table and 'vCPU' in table, table[-600:])
    finally:
        shutil.rmtree(out, ignore_errors=True)


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
        command_line()
        validators(fix)
    finally:
        shutil.rmtree(fix.root, ignore_errors=True)
    seeding()
    failed = [r for r in RESULTS if not r[1]]
    print('%d checks, %d failed' % (len(RESULTS), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
