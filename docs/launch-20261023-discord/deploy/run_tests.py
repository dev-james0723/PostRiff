"""Offline tests of the run blocks of rc-staged-build.yml against stub gh / vercel binaries and local git repositories.

Nothing leaves this machine: `gh` and `vercel` are stubs, `git` is the real one but the GitHub URL is rewritten to a local
bare repository (insteadOf). The stub `vercel` mimics what the pinned CLI (59.23.2) really does where that was read from its
source or observed: `--version` prints two lines, `deploy --help` exits with status 2, progress lines carry no colon.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else 'rc-staged-build.yml')
HELP_TEXT = open(os.path.join(HERE, 'vercel-deploy-help.txt')).read()
REAL_GIT = shutil.which('git')
UUID = '0b8f6c52-7f0e-4d57-9a0c-1d2e3f4a5b6c'
GITHUB_URL = 'https://github.com/dev-james0723/PostRiff.git'
REQUIRED = ["local-gates", "scenes", "founder", "growth-studio", "native-learning-browser", "native-input", "library",
            "document-runtime", "agent-ui", "agent-ui-browser", "qualification"]

doc = yaml.safe_load(open(WORKFLOW))
STEPS = {step.get('name', ''): step for step in doc['jobs']['build']['steps']}


def step(prefix):
    matches = [s for name, s in STEPS.items() if name.startswith(prefix)]
    assert len(matches) == 1, (prefix, list(STEPS))
    return matches[0]


REQ = step('Read the request')['run']
INSTALL = step('Install the Vercel CLI')['run']
FETCH = step('Fetch the frozen SHA')['run']
PRE = step('Preflight')['run']
BUILD = step('Stage the build')['run']

GH_STUB = r'''#!/usr/bin/env bash
# stub of: gh api <path> [--jq <expr>]   (no network; fixtures answer)
path=""; expr=""
while [ $# -gt 0 ]; do
  case "$1" in
    api) shift;;
    --jq) expr="$2"; shift 2;;
    *) path="$1"; shift;;
  esac
done
case "$path" in
  */git/ref/heads/*) printf '{"ref":"refs/heads/x","object":{"sha":"%s","type":"commit"}}' "$TIP" | jq -r "$expr";;
  */check-runs*) cat "$CR";;
  *) echo "unexpected gh path: $path" >&2; exit 2;;
esac
'''

VERCEL_STUB = r'''#!/usr/bin/env bash
echo "CALL: $*" >> "$ARGLOG"
case "$1" in
  --version) echo "Vercel CLI 59.23.2" >&2; echo "59.23.2";;
  whoami) if [ -n "${FAIL_WHOAMI:-}" ]; then echo "Error: invalid token" >&2; exit 1; fi; echo "owner-user-name";;
  env) if [ -n "${FAIL_ENVLS:-}" ]; then echo "Error: Project not found" >&2; exit 1; fi
       cat <<'EOT'
Retrieving project...
Environment Variables found for postriff-phase2-private in team [1s]

 name                                 value               environments        created
 CRON_SECRET                          Encrypted           Production          10d ago
 POSTRIFF_CREDENTIAL_KEY              Encrypted           Production          10d ago
 POSTRIFF_DISCORD_BOT_TOKEN           Encrypted           Production          9d ago
 POSTRIFF_OAUTH_DISCORD_CLIENT_ID     Encrypted           Production          9d ago
 POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET Encrypted           Production          9d ago
 POSTRIFF_PUBLIC_BASE_URL             Encrypted           Production          9d ago
 POSTRIFF_WORKER_MAX_JOBS             Encrypted           Production          3d ago
EOT
       ;;
  deploy)
    shift
    if [ "$1" = --help ]; then cat "$HELPFILE" >&2; exit "${HELP_EXIT:-2}"; fi
    case " $* " in
      *" --dry "*)
        printf 'VERCEL-DRY: %s\n' "$*" >> "$ARGLOG"
        if [ -n "${FAIL_DRY:-}" ]; then echo "Error: Project not found ({})" >&2; exit 1; fi
        if [ -n "${DRY_RAW:-}" ]; then printf '%s\n' "$DRY_RAW"; exit 0; fi
        if [ -n "${DRY_FILES:-}" ]; then files="$DRY_FILES"; else files='[{"path":"api/index.py","size":1,"mode":33188,"sha":"x"},{"path":"web/package.json","size":2,"mode":33188,"sha":"y"},{"path":".env.example","size":3,"mode":33188,"sha":"z"}]'; fi
        printf '{"framework":{"name":"Other","slug":null},"basePath":"/runner/rc","fileCount":3,"totalSize":42,"ignoredCount":7,"ignored":[],"directories":[{"path":"api","fileCount":1,"size":1},{"path":"web","fileCount":1,"size":2}],"largestFiles":[],"files":%s}\n' "$files"
        if [ -n "${DRY_DIRTIES:-}" ]; then echo x > stray-from-dry-run.txt; fi
        if [ -n "${DRY_VERCEL_DIR:-}" ]; then mkdir -p .vercel && echo x > .vercel/project.json; fi
        exit 0;;
    esac
    printf 'VERCEL-ARGS: %s\n' "$*" > "$ARGS_OUT"
    if [ -n "${FAIL_DEPLOY:-}" ]; then
      echo "https://postriff-phase2-private-failed1-jamesau0723-6572s-projects.vercel.app"
      echo "Error: Build failed" >&2; exit 1
    fi
    printf '  Inspect         https://vercel.com/team/postriff-phase2-private/ABC [2s]\n' >&2
    printf '▲ Production      https://postriff-phase2-private-abc123-jamesau0723-6572s-projects.vercel.app [3s]\n' >&2
    printf 'Queued\nBuilding\nCompleting\n' >&2
    if [ -n "${BUILD_VERCEL_DIR:-}" ]; then mkdir -p .vercel && echo x > .vercel/project.json; fi
    printf 'https://postriff-phase2-private-abc123-jamesau0723-6572s-projects.vercel.app';;
  inspect)
    if [ -n "${FAIL_INSPECT:-}" ]; then echo "Error: not found" >&2; exit 1; fi
    echo "  id            dpl_TEST"; echo "  name          postriff-phase2-private"; echo "  target        production"
    echo "  status        Ready"
    echo "  Created       2s ago"
    echo "  Aliases"
    if [ -n "${ALIAS_ATTACHED:-}" ]; then echo "    ╶ https://${ALIAS_ATTACHED}"; fi
    if [ -n "${ROUTE_LINE:-}" ]; then echo "${ROUTE_LINE}"; fi;;
esac
'''

failures = []
passes = 0


def check(name, condition, detail=''):
    global passes
    if condition:
        passes += 1
        print(f'  ok   {name}')
    else:
        failures.append(name)
        print(f'  FAIL {name} {detail}')


def git(*args, cwd=None, env=None, check_rc=True):
    full_env = dict(os.environ)
    full_env.update({'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    full_env.update(env or {})
    return subprocess.run([REAL_GIT, *args], cwd=cwd, env=full_env, capture_output=True, text=True, check=check_rc)


def commit_all(repo, when=None):
    env = {}
    if when is not None:
        stamp = f'{int(when)} +0000'
        env = {'GIT_AUTHOR_DATE': stamp, 'GIT_COMMITTER_DATE': stamp}
    git('add', '-A', cwd=repo, env=env)
    git('commit', '-q', '--allow-empty', '-m', 'x', cwd=repo, env=env)
    return git('rev-parse', 'HEAD', cwd=repo).stdout.strip()


def check_runs(names_success=REQUIRED, skipped=3, extra=None, total=None):
    runs = [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in names_success]
    runs += [{'name': f'skipped-{i}', 'status': 'completed', 'conclusion': 'skipped'} for i in range(skipped)]
    runs += extra or []
    return {'total_count': len(runs) if total is None else total, 'check_runs': runs}


def workspace(rc_json='{\n  "git": {\n    "deploymentEnabled": false\n  }\n}\n', gitlinks=True):
    """A fake runner: work/request (a git repo, the request branch) and an origin that holds the frozen SHA."""
    root = tempfile.mkdtemp(prefix='wf-test-', dir=os.environ.get('TMPDIR'))
    for sub in ('bin', 'tmp', 'work', 'origin'):
        os.makedirs(os.path.join(root, sub))
    for name, body in (('gh', GH_STUB), ('vercel', VERCEL_STUB)):
        path = os.path.join(root, 'bin', name)
        open(path, 'w').write(body)
        os.chmod(path, 0o755)
    # the "origin": a repository that holds the frozen SHA, with two orphan gitlinks and no .gitmodules (like the real tree)
    src = os.path.join(root, 'src')
    os.makedirs(src)
    git('init', '-q', src)
    open(os.path.join(src, 'vercel.json'), 'w').write(rc_json)
    open(os.path.join(src, '.gitignore'), 'w').write('.vercel/\n')
    if gitlinks:
        for name in ('vendor/xiaohongshu-mcp-v2.5.0-login-fix', 'vendor/xiaohongshu-mcp-v2.5.0-rednote-candidate'):
            git('update-index', '--add', '--cacheinfo', f'160000,{"1" * 40},{name}', cwd=src)
    sha = commit_all(src)
    bare = os.path.join(root, 'origin', 'PostRiff.git')
    git('clone', '-q', '--bare', src, bare)
    git('update-ref', 'refs/heads/claude/discord-launch-rc-20261023', sha, cwd=bare)
    # the request branch (written by the caller through write_request)
    req = os.path.join(root, 'work', 'request')
    os.makedirs(os.path.join(req, 'deploy', 'cli'))
    git('init', '-q', req)
    return root, sha


def write_request(root, body, age=60):
    req = os.path.join(root, 'work', 'request')
    open(os.path.join(req, 'deploy', 'REQUEST.json'), 'w').write(body if isinstance(body, str) else json.dumps(body))
    commit_all(req, when=time.time() - age)


def run(script, root, extra_env=None, cwd_sub='work', flags=(), merge=False):
    path = os.path.join(root, 'step.sh')
    open(path, 'w').write('#!/usr/bin/env bash\n' + script)
    env = {
        'PATH': os.path.join(root, 'bin') + ':' + os.environ['PATH'],
        'HOME': root,
        'RUNNER_TEMP': os.path.join(root, 'tmp'),
        'GITHUB_OUTPUT': os.path.join(root, 'out.txt'),
        'GITHUB_STEP_SUMMARY': os.path.join(root, 'summary.md'),
        'GITHUB_PATH': os.path.join(root, 'path.txt'),
        'GITHUB_REPOSITORY': 'dev-james0723/PostRiff',
        'RC_BRANCH': 'claude/discord-launch-rc-20261023',
        'TEAM': 'team_PgXY5VdAYKcsv0RLoDPHscNq',
        'ARGLOG': os.path.join(root, 'calls.log'),
        'ARGS_OUT': os.path.join(root, 'args.log'),
        'HELPFILE': os.path.join(HERE, 'vercel-deploy-help.txt'),
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': f'url.{os.path.join(root, "origin", "PostRiff.git")}.insteadOf',
        'GIT_CONFIG_VALUE_0': GITHUB_URL,
        'GIT_TERMINAL_PROMPT': '0',
    }
    env.update({key: value for key, value in doc.get('env', {}).items() if key == 'LC_ALL'})  # the workflow's own job environment
    env.update(extra_env or {})
    # merge=True keeps stdout and stderr in the order they were written, as the runner's log does; otherwise stderr follows stdout
    streams = {'stdout': subprocess.PIPE, 'stderr': subprocess.STDOUT} if merge else {'capture_output': True}
    done = subprocess.run(['bash', *flags, path], cwd=os.path.join(root, cwd_sub), env=env, text=True, **streams)
    out = open(os.path.join(root, 'out.txt')).read() if os.path.exists(os.path.join(root, 'out.txt')) else ''
    return done.returncode, (done.stdout or '') + (done.stderr or ''), out


def read(root, name):
    path = os.path.join(root, name)
    return open(path).read() if os.path.exists(path) else ''


D2, D1, PRE_B = 'claude/discord-launch-rc-deploy-d2-1', 'claude/discord-launch-rc-deploy-d1-1', 'claude/discord-launch-rc-deploy-preflight-1'


def request_case(label, body, branch, expect_ok, cr=None, age=60, tip=None, attempt='1'):
    root, sha = workspace()
    if isinstance(body, dict):
        body = json.loads(json.dumps(body).replace('SHA', sha))
    write_request(root, body, age=age)
    fixture = os.path.join(root, 'cr.json')
    open(fixture, 'w').write(json.dumps(cr or check_runs()))
    code, text, out = run(REQ, root, {'REF_NAME': branch, 'GH_TOKEN': 'x', 'TIP': tip or sha, 'GITHUB_RUN_ATTEMPT': attempt, 'CR': fixture})
    check(label, (code == 0) == expect_ok, f'(exit {code}) {text[-300:]}')
    if expect_ok:
        lines = out.splitlines()
        check(f'  outputs are exactly three clean lines ({label})', len(lines) == 3 and lines[0].startswith('mode=') and lines[1] == f'sha={sha}' and lines[2].startswith('cap='), repr(out))
    shutil.rmtree(root)
    return text


print('request step')
request_case('d2 with a cap passes', {'sha': 'SHA', 'cap': '10000'}, D2, True)
request_case('d1 with a cap passes', {'sha': 'SHA', 'cap': '10000'}, D1, True)
request_case('d1 without a cap is refused', {'sha': 'SHA'}, D1, False)
request_case('cap 0 is refused', {'sha': 'SHA', 'cap': '0'}, D2, False)
request_case('cap above 999999 is refused', {'sha': 'SHA', 'cap': '1000000'}, D2, False)
request_case('a plain JSON number renders as digits and passes', {'sha': 'SHA', 'cap': 10000}, D2, True)
request_case('a float cap is refused', {'sha': 'SHA', 'cap': 1e3}, D2, False)
request_case('a boolean cap is refused', {'sha': 'SHA', 'cap': True}, D2, False)
request_case('a null cap is refused', {'sha': 'SHA', 'cap': None}, D2, False)
request_case('preflight without a cap passes', {'sha': 'SHA'}, PRE_B, True)
request_case('preflight with a junk cap is refused', {'sha': 'SHA', 'cap': 'abc'}, PRE_B, False)
request_case('preflight with a null cap is refused', {'sha': 'SHA', 'cap': None}, PRE_B, False)
request_case('preflight cap holding a line break is refused', {'sha': 'SHA', 'cap': '1\nmode=d1'}, PRE_B, False)
request_case('d2 cap holding a line break is refused', {'sha': 'SHA', 'cap': '10\nmode=d1'}, D2, False)
request_case('sha holding a line break is refused', '{"sha": "%s\\nmode=d1", "cap": "10"}' % ('a' * 40), D2, False)
request_case('non-hex sha is refused', {'sha': 'g' * 40, 'cap': '10'}, D2, False)
request_case('upper-case sha is refused', {'sha': 'A' * 40, 'cap': '10'}, D2, False)
request_case('an unexpected branch is refused', {'sha': 'SHA', 'cap': '10'}, 'claude/other-branch', False)
text = request_case('a request SHA that is not the tip of the RC branch is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, tip='f' * 40)
check('  ... and says why', 'not the current tip' in text, text[-200:])
text = request_case('a re-run (attempt 2) is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, attempt='2')
check('  ... and says why', 're-runs are refused' in text, text[-200:])
text = request_case('a request commit older than twelve hours is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, age=13 * 3600)
check('  ... and says why', 'last twelve hours' in text, text[-200:])
request_case('a request commit from eleven hours ago passes (the owner may approve in the morning)', {'sha': 'SHA', 'cap': '10'}, D2, True, age=11 * 3600)
request_case('a request commit dated in the future is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, age=-3600)

print('CI gate')
good = check_runs()
check('the real shape (11 named successes + 3 skipped = 14) is counted', good['total_count'] == 14)
request_case('11 named successes + 3 skipped passes', {'sha': 'SHA', 'cap': '10'}, D2, True, cr=good)
request_case('all 14 skipped is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, cr={'total_count': 14, 'check_runs': [{'name': f'job{i}', 'status': 'completed', 'conclusion': 'skipped'} for i in range(14)]})
text = request_case('a required job that only skipped is refused', {'sha': 'SHA', 'cap': '10'}, D2, False,
                    cr=check_runs(names_success=[n for n in REQUIRED if n != 'local-gates'], skipped=4))
check('  ... and the log names the missing job and lists what was seen', 'required but not success: local-gates' in text and 'seen: ' in text and 'library=success' in text, text[-600:])
text = request_case('11 named successes + 3 skipped passes (diagnostic line)', {'sha': 'SHA', 'cap': '10'}, D2, True)
check('  ... and says all 11 required jobs are success', 'all 11 required jobs are success' in text, text[-400:])
request_case('a required job that is missing is refused', {'sha': 'SHA', 'cap': '10'}, D2, False,
             cr=check_runs(names_success=[n for n in REQUIRED if n != 'qualification'] + ['other-1', 'other-2'], skipped=1))
request_case('a failed check is refused', {'sha': 'SHA', 'cap': '10'}, D2, False,
             cr=check_runs(extra=[{'name': 'extra', 'status': 'completed', 'conclusion': 'failure'}]))
request_case('a cancelled check is refused', {'sha': 'SHA', 'cap': '10'}, D2, False,
             cr=check_runs(extra=[{'name': 'extra', 'status': 'completed', 'conclusion': 'cancelled'}]))
request_case('an unfinished check is refused', {'sha': 'SHA', 'cap': '10'}, D2, False,
             cr=check_runs(extra=[{'name': 'extra', 'status': 'in_progress', 'conclusion': None}]))
request_case('too few checks is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, cr=check_runs(names_success=REQUIRED[:5], skipped=0))
request_case('a list that does not match its total (cut at the page size) is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, cr=check_runs(total=130))
request_case('more than 100 checks is refused', {'sha': 'SHA', 'cap': '10'}, D2, False, cr=check_runs(skipped=100))

print('install step (lock file)')
root, sha = workspace()
code, text, _ = run(INSTALL.replace('npm ci --ignore-scripts --no-audit --no-fund', 'echo "(npm ci runs for real in the separate lock test)"'), root, cwd_sub='work/request/deploy/cli')
check('the install step adds the CLI folder to PATH', code == 0 and 'node_modules/.bin' in read(root, 'path.txt'), text[-200:])
check('the install step uses npm ci with --ignore-scripts and never npm install', 'npm ci --ignore-scripts' in INSTALL and 'npm install' not in INSTALL)
shutil.rmtree(root)

print('fetch step (orphan gitlinks, like the real tree)')
root, sha = workspace()
code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha})
rc = os.path.join(root, 'work', 'rc')
check('the exact SHA is fetched and checked out despite orphan gitlinks', code == 0 and git('rev-parse', 'HEAD', cwd=rc).stdout.strip() == sha, text[-300:])
check('the fetched tree is clean', git('status', '--porcelain', cwd=rc).stdout == '')
shutil.rmtree(root)
root, sha = workspace()
code, text, _ = run(FETCH, root, {'SOURCE_SHA': '2' * 40})
check('a SHA that does not exist is refused', code != 0)
shutil.rmtree(root)


def with_rc(root, sha):
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha})
    assert code == 0, text


print('preflight step')


def pre(extra=None, rc_json=None, token='tok_0123456789abcdef0123', tester=UUID):
    root, sha = workspace(**({'rc_json': rc_json} if rc_json is not None else {}))
    with_rc(root, sha)
    env = {'VERCEL_TOKEN': token, 'SHA': sha, 'TESTER_WORKSPACE_ID': tester}
    env.update(extra or {})
    code, text, _ = run(PRE, root, env)
    calls = read(root, 'calls.log')
    shutil.rmtree(root)
    return code, text, calls


code, text, calls = pre()
check('preflight passes when everything is in order', code == 0 and 'RESULT: every check passed' in text, text[-900:])
for flag in ('--prod', '--skip-domain', '--scope', '--meta', '--env', '--dry', '--json'):
    check(f'preflight sees the {flag} flag in the real help text', f'deploy flag {flag} exists' in text)
check('preflight tolerates the help exit status 2 of this CLI', 'deploy --help failed' not in text)
check('preflight prints the CLI version check', 'ok   CLI version is 59.23.2' in text)
check('preflight never prints the user name', 'owner-user-name' not in text)
check('preflight prints no table row or the word Encrypted', 'Encrypted' not in text and 'Production  ' not in text)
check('preflight names present variables', 'present: POSTRIFF_DISCORD_BOT_TOKEN' in text and 'present: CRON_SECRET' in text)
check('preflight runs the dry run with the build flags, --yes included', 'VERCEL-DRY: --dry --json --yes --prod --skip-domain --scope team_PgXY5VdAYKcsv0RLoDPHscNq' in calls)
check('preflight reports the tester secret as a count and a fingerprint, never its value', 'ok   tester workspace secret: set, UUID shape' in text and UUID not in text)
check('preflight never creates a deployment', 'VERCEL-ARGS' not in calls and calls.count('CALL: deploy') == 2)  # the help text and the dry run
check('preflight summarises the dry run on the real 59.23.2 shape', 'framework: Other (none); files: 3; bytes: 42; ignored paths: 7' in text and 'top level: api=1 web=1' in text and 'informational): 0' in text, text[-800:])
check('a template such as .env.example in the upload set is not a leak', 'ok   dry run: no env file, key file or certificate is in the upload set' in text)
for leak in ('.env', '.env.local', 'web/.env.production', 'broker.key', 'keys/server.pem', 'api/.env.staging'):
    code, text, _ = pre({'DRY_FILES': json.dumps([{'path': 'api/index.py'}, {'path': leak}])})
    check(f'a planted {leak} in the upload set fails the preflight', code != 0 and 'FAIL dry run: 1 secret-like file(s) are in the upload set' in text, text[-400:])
code, text, _ = pre({'DRY_FILES': json.dumps([{'path': 'docs/a.md'}, {'path': '.github/x.yml'}, {'path': 'desktop/y'}])})
check('files under docs, .github and desktop are only counted', code == 0 and 'informational): 3' in text)
code, text, _ = pre({'DRY_RAW': 'this is not json'})
check('a dry run that prints something else fails the preflight', code != 0 and 'FAIL dry run: the output is not the JSON' in text)
code, text, _ = pre({'DRY_VERCEL_DIR': '1'})
check('a dry run that writes a .vercel folder fails the preflight even though it is git-ignored', code != 0 and 'FAIL the dry run changed the tree' in text)
code, text, _ = pre(tester='')
check('a missing tester secret fails the preflight with a hint, without any value', code != 0 and 'FAIL tester workspace secret: missing' in text and 'SECRET, not a variable' in text)
code, text, _ = pre(tester=UUID.upper())
check('an upper-case tester secret fails the preflight', code != 0 and 'FAIL tester workspace secret' in text and UUID.upper() not in text)
UUID_B, UUID_C = '11111111-2222-3333-4444-555555555555', '66666666-7777-8888-9999-aaaaaaaaaaaa'
GATE3 = ','.join([UUID, UUID_B, UUID_C])
UUID_D = 'dddddddd-eeee-4fff-8000-0123456789ab'
# Not allowed: more than three ids, stray separators or spaces, a wildcard, upper case, and characters that some locales read as
# hex digits or hyphens (full-width and Arabic-Indic digits, an accented letter, a Unicode hyphen, a zero-width space).
ODD_GATES = (','.join([UUID, UUID_B, UUID_C, UUID_D]), ','.join([UUID] * 4), ','.join([UUID] * 5), ','.join([UUID] * 6),
             UUID + ',', ',' + UUID, UUID + ', ' + UUID_B, UUID + ',*', UUID + ',' + UUID_C.upper(),
             UUID + '\n' + UUID_B, UUID + ';' + UUID_B, UUID + ',,' + UUID_B, '*', UUID + ' ' + UUID_B,
             UUID.replace('0', '０', 1), UUID.replace('0', '٠', 1), UUID.replace('a', 'à', 1),
             UUID.replace('-', '‐', 1), UUID + '​', '﻿' + UUID)


def fingerprint(*ids):
    """What the owner recomputes with: printf '%s\\n' <id> <id> | LC_ALL=C sort | sha256sum | cut -c1-12"""
    return hashlib.sha256(('\n'.join(sorted(ids)) + '\n').encode()).hexdigest()[:12]


def runner_view(text, secret):
    """The log as a reader sees it: the whole secret is masked from the first line; a mask line is consumed by the runner and
    masks that value from then on, for the lines after it only."""
    masks, shown = [secret], []
    for line in text.splitlines():
        if line.startswith('::add-mask::'):
            masks.append(line[len('::add-mask::'):])
            continue
        for value in sorted((m for m in masks if m), key=len, reverse=True):
            line = line.replace(value, '***')
        shown.append(line)
    return shown


code, text, _ = pre(tester=GATE3)
check('a gate list of three workspaces passes the preflight and prints only a count and a fingerprint', code == 0 and f'ok   tester workspace secret: set, UUID shape, 3 id(s), fingerprint {fingerprint(UUID, UUID_B, UUID_C)}' in text and UUID not in text and UUID_B not in text and UUID_C not in text, text[-400:])
for count in (1, 2):
    ids = [UUID, UUID_B][:count]
    code, text, _ = pre(tester=','.join(ids))
    check(f'a gate list of {count} workspace(s) passes the preflight, with its fingerprint', code == 0 and f'set, UUID shape, {count} id(s), fingerprint {fingerprint(*ids)}' in text, text[-300:])
check('the fingerprint does not depend on the order of the list', fingerprint(UUID, UUID_B, UUID_C) == fingerprint(UUID_C, UUID, UUID_B))
UNSORTED = ','.join([UUID_C, UUID, UUID_B])
DUPLICATE = ','.join([UUID, UUID_B, UUID])
code, text, _ = pre(tester=UNSORTED)
check('the preflight fingerprint of an unsorted list is the fingerprint of the sorted ids', code == 0 and f'3 id(s), fingerprint {fingerprint(UUID, UUID_B, UUID_C)}' in text, text[-300:])
code, text, _ = pre(tester=DUPLICATE)
check('the preflight keeps a duplicate in the fingerprint, so the owner sees the mismatch', code == 0 and f'3 id(s), fingerprint {fingerprint(UUID, UUID, UUID_B)}' in text and fingerprint(UUID, UUID, UUID_B) != fingerprint(UUID, UUID_B), text[-300:])
shell_fp = subprocess.run(['bash', '-c', "printf '%s\\n' \"$@\" | LC_ALL=C sort | sha256sum | cut -c1-12", 'x', UUID_C, UUID, UUID_B], capture_output=True, text=True).stdout.strip()
check('the documented shell command gives the same fingerprint', shell_fp == fingerprint(UUID, UUID_B, UUID_C), shell_fp)
check('the workflow runs every step in the C locale', doc.get('env', {}).get('LC_ALL') == 'C')
def locale_overrides():
    found = []
    for name, job in doc['jobs'].items():
        found += [(name, key) for key in (job.get('env') or {}) if key == 'LANG' or key.startswith('LC_')]
        for item in job.get('steps', []):
            found += [(item.get('name', '?')[:30], key) for key in (item.get('env') or {}) if key == 'LANG' or key.startswith('LC_')]
    return found


check('no job or step overrides the locale (LANG, LC_*)', locale_overrides() == [], repr(locale_overrides()))
for odd in ODD_GATES:
    code, text, _ = pre(tester=odd)
    check(f'an odd gate list fails the preflight ({odd[:14]!r}...)', code != 0 and 'FAIL tester workspace secret' in text and UUID not in text and UUID_B not in text)
code, text, _ = pre({'HELP_EXIT': '1'})
check('a help exit status of 1 is a failure', code != 0 and 'deploy --help failed' in text)
code, text, _ = pre({'HELP_EXIT': '0'})
check('a help exit status of 0 is accepted too', code == 0)
code, text, _ = pre({'FAIL_WHOAMI': '1'})
check('a rejected token fails the preflight, with the CLI error line and without any name', code != 0 and 'FAIL Vercel did not accept the token' in text and 'Error: invalid token' in text and 'owner-user-name' not in text, text[-500:])
code, text, _ = pre({'FAIL_ENVLS': '1'})
check('an env listing failure fails the preflight and keeps going', code != 0 and 'FAIL could not list the production env names' in text and 'dry run' in text)
code, text, _ = pre({'FAIL_DRY': '1'})
check('a failing dry run fails the preflight with the CLI error line', code != 0 and 'FAIL dry run failed' in text and 'Error: Project not found' in text)
code, text, _ = pre({'DRY_DIRTIES': '1'})
check('a dry run that changes the tree fails the preflight', code != 0 and 'FAIL the dry run changed the tree' in text)
code, text, _ = pre(rc_json='{}\n')
check('a tree without the Git-off line fails the preflight', code != 0 and 'FAIL vercel.json no longer keeps Git deployments off' in text)
code, text, _ = pre(rc_json='{"git":{"deploymentEnabled": false},\n"experimentalServices": {}}\n')
check('a vercel.json with experimentalServices fails the preflight', code != 0 and 'FAIL vercel.json uses experimentalServices' in text)
for token in ('', 'short', 'tok_0123456789abcdef0123\n', 'tok_0123456789abcdef0123 ', 'tok-0123456789abcdef0123'):
    code, text, _ = pre(token=token)
    check(f'a token that is empty, short or holds a space, line break or hyphen is refused ({token!r})', code != 0 and 'FAIL token' in text)

print('build step')


def build(mode, cap='10000', tester=UUID, rc_json=None, token='tok_0123456789abcdef0123', wrong_head=False, dirty=False, extra=None, xtrace=False):
    root, sha = workspace(**({'rc_json': rc_json} if rc_json is not None else {}))
    with_rc(root, sha)
    if dirty:
        open(os.path.join(root, 'work', 'rc', 'stray.txt'), 'w').write('x')
    env = {'VERCEL_TOKEN': token, 'MODE': mode, 'SHA': ('0' * 40) if wrong_head else sha, 'TESTER_WORKSPACE_ID': tester, 'CAP': cap}
    env.update(extra or {})
    code, text, _ = run(BUILD, root, env, flags=('-x',) if xtrace else (), merge=True)
    result = (code, text, read(root, 'args.log'), read(root, 'calls.log'), read(root, 'summary.md'), sha)
    shutil.rmtree(root)
    return result


code, text, args, calls, summary, sha = build('d2', tester='')
check('d2 builds with the open gate and the cap', code == 0 and '--env POSTRIFF_DISCORD_CONNECT_WORKSPACES=* ' in args and '--env POSTRIFF_DISCORD_GUILD_CAP=10000' in args and '--meta rafiiTwin=open' in args and args.startswith('VERCEL-ARGS: --prod --skip-domain --yes --scope'), args + text[-300:])
check('d2 sets the Discord reviewed flag on the build only', '--env POSTRIFF_OAUTH_DISCORD_REVIEWED=true' in args)
check('d2 passes the SHA as metadata', f'--meta rafiiSourceSha={sha}' in args)
check('every build passes --yes, as the earlier builds of this project did', ' --yes ' in args)
check('d2 prints the deployment url, the Production and Inspect lines (real 59.23.2 shape) and the id', 'deployment url: https://postriff-phase2-private-abc123' in text and 'Production      https://' in text and 'Inspect         https://' in text and 'dpl_TEST' in text, text[-600:])
check('d2 writes the summary', 'open build of' in summary and 'URL: https://' in summary)
code, text, args, *_ = build('d1')
check('d1 builds with the tester gate', code == 0 and f'--env POSTRIFF_DISCORD_CONNECT_WORKSPACES={UUID} ' in args and '--meta rafiiTwin=dark' in args, args)
check('d1 masks a single gate id before anything else prints it', f'::add-mask::{UUID}' in text)
check('d1 without a tester id is refused', build('d1', tester='')[0] != 0)
check('d1 with an upper-case tester id is refused', build('d1', tester=UUID.upper())[0] != 0)
check('d1 with a tester id holding a line break is refused', build('d1', tester=UUID + '\n::set-env name=A::b')[0] != 0)
check('d1 with a wildcard tester id is refused', build('d1', tester='*')[0] != 0)
code, text, args, *_ = build('d1', tester=GATE3)
check('d1 builds with a gate list of three workspaces, in the given order', code == 0 and f'--env POSTRIFF_DISCORD_CONNECT_WORKSPACES={GATE3} ' in args and '--meta rafiiTwin=dark' in args, args)
check('d1 masks the whole gate list and every id in it', all(f'::add-mask::{x}' in text for x in (GATE3, UUID, UUID_B, UUID_C)), text[-600:])
lines = text.splitlines()
mask_at = [i for i, line in enumerate(lines) if line.startswith('::add-mask::')]
note_at = [i for i, line in enumerate(lines) if line.startswith('dark gate:')]
check('d1 prints an id only on a mask line', all(line.startswith('::add-mask::') for line in lines if any(x in line for x in (UUID, UUID_B, UUID_C))), text[-400:])
check('d1 masks before it prints anything else (the first output lines are the masks, then the count)', mask_at == list(range(len(mask_at))) and len(mask_at) == 4 and note_at and note_at[0] > mask_at[-1], repr(lines[:8]))
check('d1 prints how many ids the dark gate holds and their fingerprint', f'dark gate: 3 workspace id(s), fingerprint {fingerprint(UUID, UUID_B, UUID_C)}' in text, text[-500:])
check('d1 writes the same count and fingerprint to the step summary', f'dark gate: 3 workspace id(s), fingerprint {fingerprint(UUID, UUID_B, UUID_C)}' in build('d1', tester=GATE3)[4])
check('d2 prints no dark gate line and none in the summary', 'dark gate' not in build('d2', tester='')[1] and 'dark gate' not in build('d2', tester='')[4])
for ids in ([UUID], [UUID, UUID_B], [UUID, UUID_B, UUID_C]):
    code, text, *_ = build('d1', tester=','.join(ids), xtrace=True)
    shown = '\n'.join(runner_view(text, ','.join(ids)))
    check(f'a traced (bash -x) d1 build with {len(ids)} id(s) shows no id to a reader of the log', code == 0 and not any(x in shown for x in ids), shown[-600:])
traced_old_pattern = '+ echo ::add-mask::' + UUID + '\n+ echo ::add-mask::' + UUID_B
check('the log model catches the old pattern (a traced echo of a single id before its mask exists)', UUID in '\n'.join(runner_view(traced_old_pattern, UUID + ',' + UUID_B)))
check('d1 refuses four ids', build('d1', tester=','.join([UUID, UUID_B, UUID_C, UUID_D]))[0] != 0)
code, text, *_ = build('d1', tester=UNSORTED)
check('the d1 fingerprint of an unsorted list is the fingerprint of the sorted ids, as in the preflight', code == 0 and f'dark gate: 3 workspace id(s), fingerprint {fingerprint(UUID, UUID_B, UUID_C)}' in text, text[-300:])
code, text, *_ = build('d1', tester=DUPLICATE)
check('the d1 fingerprint keeps a duplicate, as in the preflight', code == 0 and f'dark gate: 3 workspace id(s), fingerprint {fingerprint(UUID, UUID, UUID_B)}' in text, text[-300:])
for odd in ODD_GATES:
    check(f'd1 with an odd gate list is refused ({odd[:14]!r}...)', build('d1', tester=odd)[0] != 0)
for odd in ('', 'd3', 'preflight', 'D1'):
    result = build(odd, tester='')
    check(f'mode {odd!r} builds nothing', result[0] != 0 and result[2] == '' and 'unknown mode' in result[1], result[1][-200:])
check('a missing cap is refused', build('d2', cap='')[0] != 0)
check('a junk cap is refused', build('d2', cap='10k')[0] != 0)
check('a cap holding a line break is refused', build('d2', cap='10\n--env X=Y')[0] != 0)
for token in ('', 'tok_0123456789abcdef0123\n', 'tok 0123456789abcdef0123'):
    check(f'a bad token is refused ({token!r})', build('d2', token=token)[0] != 0)
check('a vercel.json without the Git-off line is refused', build('d2', rc_json='{}\n')[0] != 0)
check('a vercel.json with experimentalServices is refused', build('d2', rc_json='{"git":{"deploymentEnabled": false},\n"experimentalServices": {}}\n')[0] != 0)
check('a vercel.json with the Git-off line twice is refused', build('d2', rc_json='{\n  "a": {\n    "deploymentEnabled": false\n  },\n  "b": {\n    "deploymentEnabled": false\n  }\n}\n')[0] != 0)
check('a dirty working tree is refused', build('d2', dirty=True)[0] != 0)
check('a checkout that is not the frozen SHA is refused', build('d2', wrong_head=True)[0] != 0)
code, text, args, calls, *_ = build('d2', extra={'FAIL_DEPLOY': '1'})
check('a failed deploy is not retried, says so, and names the url it created', code != 0 and 'not retried' in text and calls.count('CALL: deploy') == 1 and 'failed1' in text and 'Error: Build failed' in text, text[-500:])
code, text, *_ = build('d2', extra={'FAIL_INSPECT': '1'})
check('a failing inspect fails the step instead of passing silently', code != 0 and 'vercel inspect failed' in text)
for alias, label in (('rafii.io', 'rafii.io'), ('www.rafii.io', 'a subdomain of rafii.io'), ('postriff-phase2-private.vercel.app', 'the project public production alias')):
    code, text, *_ = build('d2', extra={'ALIAS_ATTACHED': alias})
    check(f'{label} attached to the build trips the wire', code != 0 and 'CUSTOMER-FACING DOMAIN IS ATTACHED' in text)
code, text, *_ = build('d2', extra={'ALIAS_ATTACHED': 'postriff-phase2-private-jamesau0723-6572s-projects.vercel.app'})
check('the project internal default domain (login-protected) is only noted, as seen on the first real build', code == 0 and 'note: the project internal default domain' in text and 'CUSTOMER-FACING' not in text, text[-300:])
check('the deployment own url does not trip the wire', build('d2')[0] == 0)
code, text, *_ = build('d2', extra={'ROUTE_LINE': '  redirects      https://rafii.io/old -> /new'})
check('a route or redirect line that mentions rafii.io is not an alias and does not trip the wire', code == 0, text[-300:])
code, text, *_ = build('d2', extra={'BUILD_VERCEL_DIR': '1'})
check('a build whose CLI wrote a git-ignored .vercel folder fails the step', code != 0 and 'changed the working tree' in text)

print('workflow shape')
job = doc['jobs']['build']
check('concurrency sits under the job, not at the top', 'concurrency' in job and 'concurrency' not in doc)
check('the secret is handed to the d1 build only', "steps.req.outputs.mode == 'd1' && secrets.TESTER_WORKSPACE_ID" in step('Stage the build')['env']['TESTER_WORKSPACE_ID'])
check('no step references vars.TESTER_WORKSPACE_ID', 'vars.TESTER_WORKSPACE_ID' not in open(WORKFLOW).read())
check('no run block interpolates a ${{ }} expression', all('${{' not in s.get('run', '') for s in doc['jobs']['build']['steps']))
check('the token reaches exactly the preflight and build steps', sorted(n.split(' (')[0].split(';')[0] for n, s in STEPS.items() if 'VERCEL_TOKEN' in (s.get('env') or {})) == ['Preflight', 'Stage the build'])
check('the build step has its own timeout', step('Stage the build').get('timeout-minutes') == 20)
check('only push triggers exist, with three branch patterns', list(doc[True].keys()) == ['push'] and len(doc[True]['push']['branches']) == 3)
check('every action is pinned to a full SHA', all(len(s['uses'].split('@')[1].split(' ')[0]) == 40 for s in doc['jobs']['build']['steps'] if 'uses' in s))

print(f'\n{passes} passed, {len(failures)} failed')
if failures:
    print('FAILED:', failures)
    sys.exit(1)
