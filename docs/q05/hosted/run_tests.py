"""Offline tests of the run blocks of q05-hosted-run.yml against a stub curl, a stub probe and
local git repositories. Nothing leaves this machine and no real host is contacted: `curl` is a
stub that answers the fixed Supabase and app endpoints, the probe fetched by the workflow is a
stub that emits a controlled receipt and exit code, and the GitHub URL is rewritten (insteadOf) to
a local bare repository. `git`, `jq`, `python3` and `sed` are the real ones.

Run: python3 docs/q05/hosted/run_tests.py   (needs PyYAML, jq, git, bash)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else 'q05-hosted-run.yml')
REAL_GIT = shutil.which('git')
REPO = 'dev-james0723/PostRiff'
PROBE_BRANCH = 'claude/discord-q05-probe-20261023'
GITHUB_URL = f'https://github.com/{REPO}.git'
FAKE_TOKEN = 'fake-access-token-ZZZZ'
FAKE_WS = 'fake-ws-00000000'
FAKE_STATE = 'fakestate-ABCDEF'
EMAIL_A, EMAIL_B = 'q05.a@throwaway.invalid', 'q05.b@throwaway.invalid'
CODE_A, CODE_B = '123456', '654321'

doc = yaml.safe_load(open(WORKFLOW))
BASE_URL = doc['env']['BASE_URL']
SUPABASE_URL = doc['env']['SUPABASE_URL']
RC_BRANCH = doc['env']['RC_BRANCH']
STEPS = {s.get('name', ''): s for s in doc['jobs']['probe']['steps']}


def step(prefix, d=None):
    src = {s.get('name', ''): s for s in (d or doc)['jobs']['probe']['steps']}
    matches = [s for name, s in src.items() if name.startswith(prefix)]
    assert len(matches) == 1, (prefix, list(src))
    return matches[0]


REQ = step('Read the request')['run']
FETCH = step('Fetch the probe')['run']
SIGNIN = step('Sign in both accounts')['run']

STUB_CURL = r'''#!/usr/bin/env bash
# stub curl: answers the fixed Supabase and app endpoints; failure knobs via env. Never a real socket.
method=GET; url=""; data=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2;;
    --data) data="$2"; shift 2;;
    -H) shift 2;;
    -sS|-s|-S) shift;;
    http://*|https://*) url="$1"; shift;;
    *) shift;;
  esac
done
echo "CURL $method $url" >> "$CURLLOG"
case "$url" in
  *"/channels/discord/oauth/start"*)
    if [ -n "${FAIL_START:-}" ]; then printf '{"error":"discord not enabled"}\n'; exit 0; fi
    printf '{"authorizeUrl":"https://discord.com/oauth2/authorize?client_id=1&state=%s&scope=identify"}\n' "${FAKE_STATE}";;
  *"/auth/v1/verify"*)
    if [ -n "${FAIL_VERIFY:-}" ]; then printf '{"error":"invalid otp","leaky_echo":%s}\n' "$data"; exit 0; fi
    printf '{"access_token":"%s","token_type":"bearer","expires_in":3600}\n' "${FAKE_TOKEN}";;
  *"/api/auth/verify"*) printf '{"workspaceId":"%s"}\n' "${FAKE_WS}";;
  *"/api/workspaces")
    case "${WS_COUNT:-1}" in
      0) printf '{"workspaces":[]}\n';;
      2) printf '{"workspaces":[{"workspaceId":"w1"},{"workspaceId":"w2"}]}\n';;
      *) printf '{"workspaces":[{"workspaceId":"%s"}]}\n' "${FAKE_WS}";;
    esac;;
  *) printf '{}\n';;
esac
'''

# A stand-in for scripts/q05_tenant_probe.py. Carries the marker the fetch step greps for, records the
# Q05_* environment it was handed (so tests can assert the workflow resolved and passed them), writes a
# templated receipt and a cases.jsonl, and exits PROBE_EXIT.
STUB_PROBE = r'''#!/usr/bin/env python3
"""Q-05 cross-tenant isolation probe (TEST STUB)."""
import json, os, sys
out_md = out_json = None
a = sys.argv[1:]
for i, v in enumerate(a):
    if v == "--out-md": out_md = a[i + 1]
    if v == "--out-json": out_json = a[i + 1]
keys = ("Q05_BASE_URL", "Q05_TOKEN_A", "Q05_TOKEN_B", "Q05_WORKSPACE_A", "Q05_WORKSPACE_B",
        "Q05_VICTIM_A_OAUTH_STATE", "Q05_VICTIM_B_OAUTH_STATE")
env = {k: os.environ.get(k, "") for k in keys}
env["smoke"] = "--smoke" in a
open(os.path.join(os.path.dirname(os.path.abspath(out_json or "x")) or ".", "probe_env.json"), "w").write(json.dumps(env))
cases = json.loads(os.environ.get("PROBE_CASES") or "[]")
if out_json:
    with open(out_json, "w") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
        fh.write(json.dumps({"summary": {"cases": len(cases)}}) + "\n")
if out_md:
    open(out_md, "w").write("# Q-05 receipt (stub)\n\nroutes only, no ids.\n")
sys.exit(int(os.environ.get("PROBE_EXIT", "0")))
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


def git(*args, cwd=None, env=None):
    full = dict(os.environ)
    full.update({'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    full.update(env or {})
    return subprocess.run([REAL_GIT, *args], cwd=cwd, env=full, capture_output=True, text=True, check=True)


def commit_all(repo, when=None):
    env = {}
    if when is not None:
        stamp = f'{int(when)} +0000'
        env = {'GIT_AUTHOR_DATE': stamp, 'GIT_COMMITTER_DATE': stamp}
    git('add', '-A', cwd=repo, env=env)
    git('commit', '-q', '--allow-empty', '-m', 'x', cwd=repo, env=env)
    return git('rev-parse', 'HEAD', cwd=repo).stdout.strip()


def workspace(probe_body=STUB_PROBE, gitlinks=True):
    root = tempfile.mkdtemp(prefix='q05wf-', dir=os.environ.get('TMPDIR'))
    for sub in ('bin', 'tmp', 'work', 'origin'):
        os.makedirs(os.path.join(root, sub))
    curl = os.path.join(root, 'bin', 'curl')
    open(curl, 'w').write(STUB_CURL)
    os.chmod(curl, 0o755)
    # the "origin": a repo holding the probe at scripts/q05_tenant_probe.py on the probe branch
    src = os.path.join(root, 'src')
    os.makedirs(os.path.join(src, 'scripts'))
    git('init', '-q', src)
    open(os.path.join(src, 'scripts', 'q05_tenant_probe.py'), 'w').write(probe_body)
    if gitlinks:
        for name in ('vendor/a-gitlink', 'vendor/b-gitlink'):
            git('update-index', '--add', '--cacheinfo', f'160000,{"1" * 40},{name}', cwd=src)
    sha = commit_all(src)
    alt = commit_all(src)  # a second, existing commit so "not the tip" tests can point elsewhere
    bare = os.path.join(root, 'origin', 'PostRiff.git')
    git('clone', '-q', '--bare', src, bare)
    git('update-ref', f'refs/heads/{PROBE_BRANCH}', sha, cwd=bare)  # tip = the probe commit
    req = os.path.join(root, 'work', 'request')
    os.makedirs(os.path.join(req, 'probe'))
    git('init', '-q', req)
    return root, sha, alt


def write_request(root, body, age=60):
    req = os.path.join(root, 'work', 'request')
    open(os.path.join(req, 'probe', 'REQUEST.json'), 'w').write(body if isinstance(body, str) else json.dumps(body))
    commit_all(req, when=time.time() - age)


def run(script, root, extra_env=None):
    path = os.path.join(root, 'step.sh')
    open(path, 'w').write('#!/usr/bin/env bash\n' + script)
    bare = os.path.join(root, 'origin', 'PostRiff.git')
    env = {
        'PATH': os.path.join(root, 'bin') + ':' + os.environ['PATH'],
        'HOME': root,
        'RUNNER_TEMP': os.path.join(root, 'tmp'),
        'GITHUB_OUTPUT': os.path.join(root, 'out.txt'),
        'GITHUB_STEP_SUMMARY': os.path.join(root, 'summary.md'),
        'GITHUB_WORKSPACE': os.path.join(root, 'work'),
        'GITHUB_REPOSITORY': REPO,
        'RC_BRANCH': RC_BRANCH,
        'BASE_URL': BASE_URL,
        'SUPABASE_URL': SUPABASE_URL,
        'CURLLOG': os.path.join(root, 'curl.log'),
        'FAKE_TOKEN': FAKE_TOKEN,
        'FAKE_WS': FAKE_WS,
        'FAKE_STATE': FAKE_STATE,
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': f'url.{bare}.insteadOf',
        'GIT_CONFIG_VALUE_0': GITHUB_URL,
        'GIT_TERMINAL_PROMPT': '0',
    }
    env.update(extra_env or {})
    done = subprocess.run(['bash', path], cwd=os.path.join(root, 'work'), env=env, capture_output=True, text=True)
    out = open(os.path.join(root, 'out.txt')).read() if os.path.exists(os.path.join(root, 'out.txt')) else ''
    return done.returncode, done.stdout + done.stderr, out


def read(root, name):
    p = os.path.join(root, name)
    return open(p).read() if os.path.exists(p) else ''


def strip_masks(text):
    """Drop the ::add-mask::VALUE directive lines; the real runner consumes them to redact. A secret
    that appears ONLY on such lines is correctly protected; anywhere else is a leak."""
    return '\n'.join(l for l in text.splitlines() if '::add-mask::' not in l)


# --------------------------------------------------------------------------- request step
def req_case(label, body, branch, expect_ok, age=60, wrong_tip=False, attempt='1'):
    root, sha, alt = workspace()
    if wrong_tip:
        git('update-ref', f'refs/heads/{PROBE_BRANCH}', alt, cwd=os.path.join(root, 'origin', 'PostRiff.git'))
    if isinstance(body, dict):
        body = json.loads(json.dumps(body).replace('SHA', sha))
    write_request(root, body, age=age)
    code, text, out = run(REQ, root, {'REF_NAME': branch, 'GITHUB_RUN_ATTEMPT': attempt})
    check(label, (code == 0) == expect_ok, f'(exit {code}) {text[-200:]}')
    if expect_ok:
        lines = out.splitlines()
        check(f'  outputs are two clean lines ({label})', len(lines) == 2 and lines[0].startswith('sha=') and lines[1].startswith('mode='), repr(out))
    shutil.rmtree(root)
    return text


RUN_G = 'claude/discord-q05-run-generic-1'
RUN_T = 'claude/discord-q05-run-gate-1'


def main_suite():
    print('request step')
    req_case('generic request passes', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, True)
    req_case('gate request passes', {'sha': 'SHA', 'mode': 'gate'}, RUN_T, True)
    req_case('a missing mode is refused', {'sha': 'SHA'}, RUN_G, False)
    req_case('an unknown mode is refused', {'sha': 'SHA', 'mode': 'deploy'}, RUN_G, False)
    req_case('a mode holding a line break is refused', {'sha': 'SHA', 'mode': 'generic\nx'}, RUN_G, False)
    req_case('a non-hex sha is refused', {'sha': 'g' * 40, 'mode': 'generic'}, RUN_G, False)
    req_case('an upper-case sha is refused', {'sha': 'A' * 40, 'mode': 'generic'}, RUN_G, False)
    req_case('a short sha is refused', {'sha': 'abc', 'mode': 'generic'}, RUN_G, False)
    req_case('a sha holding a line break is refused', '{"sha":"%s\\nmode=gate","mode":"generic"}' % ('a' * 40), RUN_G, False)
    req_case('an unexpected branch is refused', {'sha': 'SHA', 'mode': 'generic'}, 'claude/other', False)
    t = req_case('a re-run (attempt 2) is refused', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, False, attempt='2')
    check('  ... and says why', 're-runs are refused' in t, t[-160:])
    t = req_case('an old request (>12h) is refused', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, False, age=13 * 3600)
    check('  ... and says why', 'last twelve hours' in t, t[-160:])
    req_case('an eleven-hour-old request passes', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, True, age=11 * 3600)
    req_case('a future-dated request is refused', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, False, age=-3600)
    t = req_case('a sha that is not the probe-branch tip is refused', {'sha': 'SHA', 'mode': 'generic'}, RUN_G, False, wrong_tip=True)
    check('  ... and says why', 'not the current tip' in t, t[-160:])

    print('fetch step')
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha})
    check('the probe is fetched at the exact SHA despite orphan gitlinks', code == 0 and 'Q-05 cross-tenant isolation probe' in read(root, 'work/probe.py'), text[-200:])
    shutil.rmtree(root)
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': '2' * 40})
    check('a SHA that does not exist is refused', code != 0)
    shutil.rmtree(root)
    root, sha, alt = workspace(probe_body='print("not the probe")\n')
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha})
    check('a fetched file that is not the probe is refused', code != 0 and 'not the Q-05 probe' in text, text[-160:])
    shutil.rmtree(root)

    print('sign-in + probe step')
    secrets_otp = {'Q05_EMAIL_A': EMAIL_A, 'Q05_CODE_A': CODE_A, 'Q05_EMAIL_B': EMAIL_B, 'Q05_CODE_B': CODE_B,
                   'Q05_SUPABASE_PUBLISHABLE_KEY': 'pk_test_publishable_1234567890'}
    secrets_tok = {'Q05_TOKEN_A': 'ready-token-AAAA', 'Q05_TOKEN_B': 'ready-token-BBBB'}

    def signin(mode, secrets, probe_exit='0', cases=None, knobs=None, place_probe=True):
        root, sha, alt = workspace()
        if place_probe:
            open(os.path.join(root, 'work', 'probe.py'), 'w').write(STUB_PROBE)
        env = {'MODE': mode, 'PROBE_EXIT': probe_exit, 'PROBE_CASES': json.dumps(cases or [])}
        env.update(secrets)
        env.update(knobs or {})
        code, text, _ = run(SIGNIN, root, env)
        penv = read(root, 'work/probe_env.json')
        penv = json.loads(penv) if penv else {}
        summary = read(root, 'summary.md')
        curl = read(root, 'curl.log')
        shutil.rmtree(root)
        return code, text, penv, summary, curl

    # happy: OTP mode, generic
    code, text, penv, summary, curl = signin('generic', secrets_otp)
    check('generic OTP run succeeds and runs the probe', code == 0 and penv.get('Q05_BASE_URL') == BASE_URL and penv.get('Q05_TOKEN_A') == FAKE_TOKEN and penv.get('Q05_WORKSPACE_A') == FAKE_WS, text[-300:])
    check('generic passes --smoke to the probe', penv.get('smoke') is True)
    check('the receipt is written to the step summary', 'Q-05 hosted probe (generic)' in summary and 'routes only' in summary)
    check('the OTP code is exchanged at the FIXED Supabase verify endpoint only', f'CURL POST {SUPABASE_URL}/auth/v1/verify' in curl and 'grant_type=password' not in curl)
    check('no secret appears outside an add-mask line (generic OTP)', all(s not in strip_masks(text) for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS, 'pk_test_publishable_1234567890')), strip_masks(text)[-300:])
    check('every secret is masked at least once', all(f'::add-mask::{s}' in text for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS)))

    # gate mode mints a victim OAuth state and passes it to the probe
    code, text, penv, summary, curl = signin('gate', secrets_otp, cases=[{'case': 'x', 'verdict': 'PASS', 'blast': ''}])
    check('gate run succeeds and mints a victim OAuth state', code == 0 and penv.get('Q05_VICTIM_A_OAUTH_STATE') == FAKE_STATE, text[-300:])
    check('gate does NOT pass --smoke', penv.get('smoke') is False)
    check('gate calls the discord connect-start on the FIXED base URL', f'{BASE_URL}/api/workspaces/{FAKE_WS}/channels/discord/oauth/start' in curl)
    check('the minted state is masked', f'::add-mask::{FAKE_STATE}' in text and FAKE_STATE not in strip_masks(text))

    # ready-made token mode: no Supabase call at all
    code, text, penv, summary, curl = signin('generic', secrets_tok)
    check('ready-made tokens are used and no Supabase verify is called', code == 0 and penv.get('Q05_TOKEN_A') == 'ready-token-AAAA' and '/auth/v1/verify' not in curl, curl[-200:])

    # failures / leaks
    code, text, *_ = signin('generic', {})
    check('no credentials at all fails, with a hint and no values', code != 0 and 'set Q05_EMAIL_A' in text)
    code, text, _penv, _s, _c = signin('generic', {**secrets_otp, 'Q05_CODE_A': CODE_A}, knobs={'FAIL_VERIFY': '1'})
    check('a rejected OTP code fails the run', code != 0 and 'did not verify' in text, text[-200:])
    check('a leaky verify response never prints the e-mail or code', EMAIL_A not in strip_masks(text) and CODE_A not in strip_masks(text), strip_masks(text)[-300:])
    code, text, *_ = signin('generic', secrets_otp, knobs={'WS_COUNT': '0'})
    check('zero workspaces fails the run (account not signed up / not bootstrapped)', code != 0 and 'workspace resolution failed' in text)
    code, text, *_ = signin('generic', secrets_otp, knobs={'WS_COUNT': '2'})
    check('two workspaces fails the run (ambiguous)', code != 0 and 'workspace resolution failed' in text)
    code, text, *_ = signin('generic', secrets_otp, probe_exit='1')
    check('a non-zero probe exit fails the job', code != 0 and 'probe exit: 1' in text)
    # gate completeness: a non-send NOT RUN fails gate; a send NOT RUN is allowed
    code, text, *_ = signin('gate', secrets_otp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}])
    check('gate fails when a non-send case is NOT RUN', code != 0 and 'were NOT RUN that must run' in text, text[-200:])
    code, text, *_ = signin('gate', secrets_otp, cases=[{'case': 'write.send.y', 'verdict': 'NOT_RUN', 'blast': 'send'}])
    check('gate tolerates a send-blast case being NOT RUN (send-risk off)', code == 0, text[-200:])
    # smoke tolerates undiscovered: generic with a non-send NOT RUN and probe exit 0 still passes the job
    code, text, *_ = signin('generic', secrets_otp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}])
    check('generic/smoke does not fail the job on a NOT RUN case', code == 0, text[-200:])

    print('workflow shape')
    shape_checks(doc, WORKFLOW)


def shape_checks(d, path):
    job = d['jobs']['probe']
    text = open(path).read()
    check('only push triggers exist, with exactly one branch pattern', list(d[True].keys()) == ['push'] and d[True]['push']['branches'] == ['claude/discord-q05-run-*'])
    check('the job if restricts repository and actor', job.get('if') == "github.repository == 'dev-james0723/PostRiff' && github.actor == 'dev-james0723'")
    check('concurrency sits under the job, not at the top', 'concurrency' in job and 'concurrency' not in d)
    check('the environment is rafii-q05-probe', job.get('environment') == 'rafii-q05-probe')
    check('permissions are contents:read only', d.get('permissions') == {'contents': 'read'})
    check('no VERCEL_TOKEN or build secret is referenced (comments aside)',
          'secrets.VERCEL' not in text and not any('VERCEL' in k.upper() for s in job['steps'] for k in (s.get('env') or {})))
    check('the base URL and Supabase URL are hard-coded literals', d['env']['BASE_URL'] == 'https://rafii.io' and d['env']['SUPABASE_URL'] == 'https://buoyhkbodnhzngaotoel.supabase.co')
    check('no run block reads base_url/supabase from the request', all('REQUEST.json' not in s.get('run', '') or ('base_url' not in s.get('run', '').lower() and 'supabase' not in s.get('run', '').lower()) for s in job['steps']))
    check('the request step reads only sha and mode from REQUEST.json', REQ.count('REQUEST.json') == 2 and '"sha"' in REQ and '"mode"' in REQ.replace('("mode","")', '').replace('.get("mode"', 'X') or '.get("mode"' in REQ)
    check('no run block interpolates a ${{ }} expression', all('${{' not in s.get('run', '') for s in job['steps']))
    check('every action is pinned to a full 40-hex SHA', all(len(s['uses'].split('@')[1].split(' ')[0]) == 40 for s in job['steps'] if 'uses' in s))
    secret_steps = sorted(n for n, s in STEPS.items() if any('secrets.' in str(v) for v in (s.get('env') or {}).values()))
    check('secrets are referenced only in the sign-in step', secret_steps == ['Sign in both accounts, resolve their workspaces, and run the probe'], secret_steps)
    signin_run = step('Sign in both accounts', d)['run']
    check('generic passes --smoke, gate never enables send-risk', '--smoke' in signin_run and '--allow-send-risk' not in signin_run)
    check('the step exits with the probe return code', 'exit "$rc"' in signin_run)
    check('the gate check exempts only send-blast NOT RUN', '.verdict == "NOT_RUN" and .blast != "send"' in signin_run)


# --------------------------------------------------------------------------- mutation harness
def evaluate(path):
    """A compact representative subset for the mutation harness. Returns True if ALL pass."""
    global failures, passes
    saved_f, saved_p = failures, passes
    failures, passes = [], 0
    try:
        d = yaml.safe_load(open(path))
    except Exception:
        return False
    try:
        reqrun = step('Read the request', d)['run']
        signinrun = step('Sign in both accounts', d)['run']
    except Exception:
        return False
    results = []

    # req: generic passes, bad mode refused, not-tip refused, re-run refused
    def req(body, branch, age=60, attempt='1', wrong_tip=False):
        root, sha, alt = workspace()
        if wrong_tip:
            git('update-ref', f'refs/heads/{PROBE_BRANCH}', alt, cwd=os.path.join(root, 'origin', 'PostRiff.git'))
        b = json.loads(json.dumps(body).replace('SHA', sha)) if isinstance(body, dict) else body
        write_request(root, b, age=age)
        code, _t, _o = run(reqrun, root, {'REF_NAME': branch, 'GITHUB_RUN_ATTEMPT': attempt})
        shutil.rmtree(root)
        return code
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G) == 0)
    results.append(req({'sha': 'SHA', 'mode': 'deploy'}, RUN_G) != 0)
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G, wrong_tip=True) != 0)
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G, attempt='2') != 0)

    # signin: happy OTP, leak check, probe-exit propagation, gate NOT-RUN, URL fixity
    def signin(mode, secrets, probe_exit='0', cases=None, knobs=None):
        root, sha, alt = workspace()
        open(os.path.join(root, 'work', 'probe.py'), 'w').write(STUB_PROBE)
        env = {'MODE': mode, 'PROBE_EXIT': probe_exit, 'PROBE_CASES': json.dumps(cases or [])}
        env.update(secrets); env.update(knobs or {})
        code, text, _ = run(signinrun, root, env)
        penv = read(root, 'work/probe_env.json'); penv = json.loads(penv) if penv else {}
        curl = read(root, 'curl.log')
        shutil.rmtree(root)
        return code, text, penv, curl
    sotp = {'Q05_EMAIL_A': EMAIL_A, 'Q05_CODE_A': CODE_A, 'Q05_EMAIL_B': EMAIL_B, 'Q05_CODE_B': CODE_B,
            'Q05_SUPABASE_PUBLISHABLE_KEY': 'pk_test_publishable_1234567890'}
    code, text, penv, curl = signin('generic', sotp)
    results.append(code == 0 and penv.get('Q05_TOKEN_A') == FAKE_TOKEN and penv.get('smoke') is True)
    results.append(all(s not in strip_masks(text) for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS)))
    results.append(f'CURL POST {SUPABASE_URL}/auth/v1/verify' in curl and 'grant_type=password' not in curl)
    code, text, *_ = signin('generic', sotp, knobs={'FAIL_VERIFY': '1'})
    results.append(code != 0 and EMAIL_A not in strip_masks(text) and CODE_A not in strip_masks(text))
    code, _t, *_ = signin('generic', sotp, probe_exit='1')
    results.append(code != 0)
    code, _t, *_ = signin('gate', sotp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}])
    results.append(code != 0)

    # shape
    try:
        job = d['jobs']['probe']
        results.append(list(d[True].keys()) == ['push'] and d[True]['push']['branches'] == ['claude/discord-q05-run-*'])
        results.append("github.actor == 'dev-james0723'" in (job.get('if') or ''))
        results.append('concurrency' in job and 'concurrency' not in d)
        results.append(d['env']['BASE_URL'] == 'https://rafii.io' and d['env']['SUPABASE_URL'] == 'https://buoyhkbodnhzngaotoel.supabase.co')
        results.append(all(len(s['uses'].split('@')[1].split(' ')[0]) == 40 for s in job['steps'] if 'uses' in s))
        results.append('--smoke' in signinrun and '--allow-send-risk' not in signinrun)
        results.append('exit "$rc"' in signinrun)
    except Exception:
        results.append(False)

    failures, passes = saved_f, saved_p
    return all(results)


MUTATIONS = [
    ('widen the branch trigger to claude/*', "- 'claude/discord-q05-run-*'", "- 'claude/*'"),
    ('add a second trigger', "on:\n  push:", "on:\n  workflow_dispatch:\n  push:"),
    ('drop the actor from the job if', " && github.actor == 'dev-james0723'", ""),
    ('move concurrency to the top level', "jobs:\n  probe:", "concurrency:\n  group: x\njobs:\n  probe:"),
    ('unpin the checkout action', "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1", "actions/checkout@v7"),
    ('point the base URL elsewhere', "BASE_URL: https://rafii.io", "BASE_URL: https://evil.example"),
    ('point the Supabase URL elsewhere', "SUPABASE_URL: https://buoyhkbodnhzngaotoel.supabase.co", "SUPABASE_URL: https://evil.supabase.co"),
    ('echo the raw verify response (leak)', 'tok="$(printf \'%s\' "$resp" | jq -r \'.access_token // empty\'', 'echo "$resp"; tok="$(printf \'%s\' "$resp" | jq -r \'.access_token // empty\''),
    ('drop the add-mask of the access token', 'TOKEN_A="$(mint_token A)" || exit 1; echo "::add-mask::$TOKEN_A"', 'TOKEN_A="$(mint_token A)" || exit 1; echo "token A ready: $TOKEN_A"'),
    ('accept a password grant again', '"$SUPABASE_URL/auth/v1/verify"', '"$SUPABASE_URL/auth/v1/token?grant_type=password"'),
    ('stop exiting with the probe code', 'exit "$rc"', 'exit 0'),
    ('let gate accept any NOT RUN case', '.verdict == "NOT_RUN" and .blast != "send"', '.verdict == "NOT_RUN" and .blast == "send"'),
    ('widen the mode check to anything', "generic|gate) : ;;", "generic|gate|*) : ;;"),
    ('drop the run_attempt guard', "[ \"${GITHUB_RUN_ATTEMPT:-1}\" = 1 ] || { echo 're-runs are refused; push a new request'; exit 1; }", "true"),
    ('drop the tip-of-branch check', '[ "$tip" = "$sha" ] || { echo "the request SHA is not the current tip of ${RC_BRANCH}"; exit 1; }', 'true'),
]


def mutation_suite():
    print('mutation checks (each weakening must be caught by at least one test)')
    base = open(WORKFLOW).read()
    caught, survivors = 0, []
    for label, old, new in MUTATIONS:
        if old not in base:
            survivors.append(label + ' [HUNK NOT FOUND]')
            print(f'  FAIL mutation hunk not found: {label}')
            failures.append('mutation hunk: ' + label)
            continue
        mpath = os.path.join(tempfile.mkdtemp(prefix='q05mut-'), 'wf.yml')
        open(mpath, 'w').write(base.replace(old, new, 1))
        ok = evaluate(mpath)
        shutil.rmtree(os.path.dirname(mpath), ignore_errors=True)
        if ok:
            survivors.append(label)
            print(f'  survived (not caught): {label}')
        else:
            caught += 1
            print(f'  ok   caught: {label}')
    print(f'  mutations caught {caught}/{len(MUTATIONS)}; survivors: {survivors or "none"}')
    # sanity: the unmutated workflow passes evaluate()
    check('the unmutated workflow passes the representative subset', evaluate(WORKFLOW))
    check('all mutations are caught', not survivors, str(survivors))


if __name__ == '__main__':
    assert REAL_GIT, 'git is required'
    main_suite()
    mutation_suite()
    print(f'\n{passes} passed, {len(failures)} failed')
    if failures:
        print('FAILED:', failures)
        sys.exit(1)
