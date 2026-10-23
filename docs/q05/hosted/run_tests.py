"""Offline tests of the run blocks of q05-hosted-run.yml against a stub curl, a stub probe and
local git repositories. Nothing leaves this machine and no real host is contacted: `curl` is a
stub that answers the fixed Supabase and app endpoints, the probe fetched by the workflow is a
stub that emits a controlled receipt and exit code, and the GitHub URL is rewritten (insteadOf) to
a local bare repository. `git`, `jq`, `python3` and `sed` are the real ones.

Run: python3 docs/q05/hosted/run_tests.py   (needs PyYAML, jq, git, bash)
"""
import base64
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
# It records its own argv (ARGVLOG: secrets must never appear there), reads -H @file header files and a
# --data/--data-binary @- body from stdin exactly like curl, and records the apikey it was given.
printf 'curl %s\n' "$*" >> "$ARGVLOG"
method=GET; url=""; data=""; hfiles=()
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2;;
    --data|--data-binary) data="$2"; shift 2;;
    -H) case "$2" in @*) hfiles+=("${2#@}");; esac; shift 2;;
    --connect-timeout|--max-time) shift 2;;
    -sS|-s|-S) shift;;
    http://*|https://*) url="$1"; shift;;
    *) shift;;
  esac
done
[ "$data" = "@-" ] && data="$(cat)"
for f in "${hfiles[@]}"; do
  sed -n 's/^apikey: //p' "$f" >> "$APIKEYLOG"
done
echo "CURL $method $url" >> "$CURLLOG"
case "$url" in
  *"/channels/discord/oauth/start"*)
    if [ -n "${FAIL_START:-}" ]; then printf '{"error":"discord not enabled"}\n'; exit 0; fi
    printf '{"authorizeUrl":"https://discord.com/oauth2/authorize?client_id=1&state=%s&scope=identify"}\n' "${FAKE_STATE}";;
  *"/channels")
    # the connections-v2 flag read used before minting an OAuth state
    printf '{"providers":[{"id":"discord","discordConnectionsV2":%s}]}\n' "${V2_ON:-true}";;
  *"/auth/v1/verify"*)
    printf '%s\n' "$data" >> "$VERIFYLOG"
    if [ -n "${FAIL_VERIFY:-}" ]; then printf '{"error":"invalid otp","leaky_echo":%s}\n' "$data"; exit 0; fi
    if [ -n "${FAIL_VERIFY_FOR:-}" ]; then
      case "$data" in *"$FAIL_VERIFY_FOR"*) printf '{"error":"invalid otp"}\n'; exit 0;; esac
    fi
    printf '{"access_token":"%s","token_type":"bearer","expires_in":3600}\n' "${FAKE_TOKEN}";;
  *"/auth/v1/logout"*) printf '{}\n';;
  *"/api/auth/verify"*) printf '{"workspaceId":"%s"}\n' "${FAKE_WS}";;
  *"/api/health"*)
    if [ -n "${HEALTH_REV:-}" ]; then printf '{"sourceRevision":"%s"}\n' "$HEALTH_REV"; else printf '{"sourceRevision":null}\n'; fi;;
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
env["inherited_secret_seen"] = os.environ.get("INHERITED_SECRET", "")  # must be "" under env -i
env["victim_is_synthetic_flag"] = "--victim-is-synthetic" in a
open("probe_env.json", "w").write(json.dumps(env))  # cwd is the workspace dir (preserved by env -i)
# knobs come from a FILE, not env, because the workflow runs the probe under `env -i` (M2 minimal env)
try:
    knobs = json.load(open("probe_knobs.json"))
except Exception:
    knobs = {}
cases = knobs.get("cases", [])
if out_json:
    with open(out_json, "w") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
        fh.write(json.dumps({"summary": {"cases": len(cases)}}) + "\n")
if out_md:
    open(out_md, "w").write("# Q-05 receipt (stub)\n\nroutes only, no ids.\n")
sys.exit(int(knobs.get("exit", 0)))
'''

PROBE_SHA256 = hashlib.sha256(STUB_PROBE.encode()).hexdigest()
EXPECT_REV = "c" * 40  # a 40-hex "promoted build" sourceRevision for gate-mode tests

failures = []
passes = 0
# Optional fast iteration: Q05_RT_ONLY=request,fetch,maker,signin,docs,shape,mutations runs only those
# sections. The default (unset) runs everything, which is what a review or a commit must use.
ONLY = {s for s in os.environ.get('Q05_RT_ONLY', '').split(',') if s}


def want(section):
    return not ONLY or section in ONLY


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


# argv-logging wrappers for the real jq, env and python3: they record every command line (secrets must
# never appear on one) and exec the real program. Written in Perl because Perl passes the environment
# on untouched: a bash wrapper exports SHLVL/PWD and Python coerces LC_CTYPE (PEP 538), either of which
# would (correctly) trip the workflow's minimal-environment self-check.
ARGV_WRAPPER = '''#!/usr/bin/perl
open(my $fh, '>>', '{log}') or die "argv log: $!"; print $fh "{name} " . join(' ', @ARGV) . "\\n"; close $fh;
exec {{ '{real}' }} '{real}', @ARGV or die "exec: $!";
'''


def workspace(probe_body=STUB_PROBE, gitlinks=True, git_repos=True):
    """A throwaway runner layout. git_repos=False skips the origin/request git repositories (the sign-in
    step never touches git), which makes the many sign-in runs several times faster."""
    root = tempfile.mkdtemp(prefix='q05wf-', dir=os.environ.get('TMPDIR'))
    for sub in ('bin', 'tmp', 'work', 'origin'):
        os.makedirs(os.path.join(root, sub))
    curl = os.path.join(root, 'bin', 'curl')
    open(curl, 'w').write(STUB_CURL)
    os.chmod(curl, 0o755)
    for name in ('jq', 'env', 'python3'):
        real = shutil.which(name)
        wrapper = os.path.join(root, 'bin', name)
        open(wrapper, 'w').write(ARGV_WRAPPER.format(log=os.path.join(root, 'argv.log'), name=name, real=real))
        os.chmod(wrapper, 0o755)
    if not git_repos:
        return root, None, None
    # the "origin": a repo holding the probe at scripts/q05_tenant_probe.py on the probe branch
    src = os.path.join(root, 'src')
    os.makedirs(os.path.join(src, 'scripts'))
    git('init', '-q', src)
    open(os.path.join(src, 'scripts', 'q05_tenant_probe.py'), 'w').write(probe_body)
    # another file of the probe branch: the fetch step must never download it (only the probe's blob)
    open(os.path.join(src, 'scripts', 'other_file.py'), 'w').write('OTHER FILE ' + 'x' * 4096 + '\n')
    if gitlinks:
        for name in ('vendor/a-gitlink', 'vendor/b-gitlink'):
            git('update-index', '--add', '--cacheinfo', f'160000,{"1" * 40},{name}', cwd=src)
    sha = commit_all(src)
    alt = commit_all(src)  # a second, existing commit so "not the tip" tests can point elsewhere
    bare = os.path.join(root, 'origin', 'PostRiff.git')
    git('clone', '-q', '--bare', src, bare)
    git('update-ref', f'refs/heads/{PROBE_BRANCH}', sha, cwd=bare)  # tip = the probe commit
    # served over file:// with filtering allowed, like GitHub, so the partial (blob-less) fetch is real
    git('config', 'uploadpack.allowFilter', 'true', cwd=bare)
    git('config', 'uploadpack.allowAnySHA1InWant', 'true', cwd=bare)
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
        'ARGVLOG': os.path.join(root, 'argv.log'),
        'APIKEYLOG': os.path.join(root, 'apikey.log'),
        'VERIFYLOG': os.path.join(root, 'verify.log'),
        'FAKE_TOKEN': FAKE_TOKEN,
        'FAKE_WS': FAKE_WS,
        'FAKE_STATE': FAKE_STATE,
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': f'url.file://{bare}.insteadOf',
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
        body = dict(body)
        body.setdefault('probeSha256', PROBE_SHA256)
        if body.get('mode') == 'gate':
            body.setdefault('expectSourceRevision', EXPECT_REV)
        body = json.loads(json.dumps(body).replace('SHA', sha))
    write_request(root, body, age=age)
    code, text, out = run(REQ, root, {'REF_NAME': branch, 'GITHUB_RUN_ATTEMPT': attempt})
    check(label, (code == 0) == expect_ok, f'(exit {code}) {text[-200:]}')
    if expect_ok:
        keys = sorted(l.split('=', 1)[0] for l in out.splitlines() if '=' in l)
        check(f'  outputs sha/mode/probesha/expectrev only ({label})',
              keys == ['expectrev', 'mode', 'probesha', 'sha'], repr(out))
    shutil.rmtree(root)
    return text


RUN_G = 'claude/discord-q05-run-generic-1'
RUN_T = 'claude/discord-q05-run-gate-1'
MAKER = os.path.join(HERE, 'make_request_branch.sh')


# --------------------------------------------------------------------------- request maker
def maker_repo(probe_body=STUB_PROBE):
    """A throwaway git repo laid out like this one (the maker reads the probe via `git -C <its dir>`)."""
    root = tempfile.mkdtemp(prefix='q05maker-', dir=os.environ.get('TMPDIR'))
    repo = os.path.join(root, 'repo')
    hosted = os.path.join(repo, 'docs', 'q05', 'hosted')
    os.makedirs(hosted)
    os.makedirs(os.path.join(repo, 'scripts'))
    os.makedirs(os.path.join(root, 'tmp'))
    shutil.copy(MAKER, os.path.join(hosted, 'make_request_branch.sh'))
    shutil.copy(WORKFLOW, os.path.join(hosted, 'q05-hosted-run.yml'))
    open(os.path.join(repo, 'scripts', 'q05_tenant_probe.py'), 'w').write(probe_body)
    git('init', '-q', repo)
    sha = commit_all(repo)
    return root, repo, sha


def run_maker(root, repo, *args):
    env = dict(os.environ, TMPDIR=os.path.join(root, 'tmp'), HOME=root, GIT_TERMINAL_PROMPT='0')
    done = subprocess.run(['bash', os.path.join(repo, 'docs', 'q05', 'hosted', 'make_request_branch.sh'), *args],
                          capture_output=True, text=True, env=env, cwd=repo)
    return done.returncode, done.stdout + done.stderr


def maker_suite():
    root, repo, sha = maker_repo()
    good = PROBE_SHA256
    code, text = run_maker(root, repo, 'generic', 't1', sha)
    check('the maker refuses without --reviewed-probe-sha256 (the hash must come from the review record)',
          code != 0 and 'reviewed-probe-sha256' in text and 'is required' in text, text[-200:])
    code, text = run_maker(root, repo, 'generic', 't1', sha, '--reviewed-probe-sha256', 'ab' * 32)
    check('the maker refuses a reviewed hash that does not match the probe at the SHA',
          code != 0 and 'does not match the reviewed probeSha256' in text, text[-200:])
    code, text = run_maker(root, repo, 'generic', 't1', sha, '--reviewed-probe-sha256', good[:16])
    check('the maker refuses a 16-hex prefix as the reviewed hash', code != 0 and 'is required' in text, text[-200:])
    code, text = run_maker(root, repo, 'generic', 't1', sha, '--reviewed-probe-sha256')
    check('the maker refuses a flag with no value', code != 0, text[-200:])
    code, text = run_maker(root, repo, 'generic', 't1', sha, '--reviewed-probe-sha256', good)
    request = next((l.split(':', 1)[1].strip() for l in text.splitlines() if l.startswith('request:')), '{}')
    check('the maker builds with the matching reviewed hash and pins exactly that value',
          code == 0 and json.loads(request).get('probeSha256') == good and 'expectSourceRevision' not in json.loads(request),
          text[-300:])
    code, text = run_maker(root, repo, 'gate', 't2', sha, 'c' * 40, '--reviewed-probe-sha256', good)
    request = next((l.split(':', 1)[1].strip() for l in text.splitlines() if l.startswith('request:')), '{}')
    check('gate mode pins the reviewed hash and expectSourceRevision',
          code == 0 and json.loads(request).get('probeSha256') == good
          and json.loads(request).get('expectSourceRevision') == 'c' * 40, text[-300:])
    leftovers = [n for n in os.listdir(os.path.join(root, 'tmp')) if n.startswith('q05-request-')]
    check('the maker works outside the repository and cleans up its work directory',
          not leftovers and not any(n.startswith('q05-request-') for n in os.listdir(repo)), str(leftovers))
    shutil.rmtree(root)


def main_suite():
    if want('request'):
        request_suite()
    if want('fetch'):
        fetch_suite()
    if want('maker'):
        print('request maker (make_request_branch.sh)')
        maker_suite()
    if want('signin'):
        signin_suite()
    if want('docs'):
        print('owner docs')
        docs_suite()
    if want('shape'):
        print('workflow shape')
        shape_checks(doc, WORKFLOW)


def request_suite():
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
    # N3: only the FULL 64-hex reviewed hash is accepted (a prefix would let a partial value through)
    t = req_case('a 16-hex probeSha256 prefix is refused', {'sha': 'SHA', 'mode': 'generic', 'probeSha256': PROBE_SHA256[:16]}, RUN_G, False)
    check('  ... and says why', 'full reviewed probeSha256' in t, t[-160:])
    req_case('a 63-hex probeSha256 is refused', {'sha': 'SHA', 'mode': 'generic', 'probeSha256': PROBE_SHA256[:63]}, RUN_G, False)
    req_case('an upper-case probeSha256 is refused', {'sha': 'SHA', 'mode': 'generic', 'probeSha256': PROBE_SHA256.upper()}, RUN_G, False)


def fetch_footprint(root, sha):
    """(working-tree entries of rc/, the other file's blob was downloaded?, the probe blob is present?).
    rev-list --missing=print reports absent objects WITHOUT lazily fetching them."""
    rc = os.path.join(root, 'work', 'rc')
    entries = sorted(os.listdir(rc)) if os.path.isdir(rc) else None
    src = os.path.join(root, 'src')
    other = git('rev-parse', f'{sha}:scripts/other_file.py', cwd=src).stdout.strip()
    probe_blob = git('rev-parse', f'{sha}:scripts/q05_tenant_probe.py', cwd=src).stdout.strip()
    listing = subprocess.run([REAL_GIT, '-C', rc, 'rev-list', '--objects', '--missing=print', sha],
                             capture_output=True, text=True).stdout.split()
    return entries, (other in listing and '?' + other not in listing), (probe_blob in listing)


def fetch_suite():
    print('fetch step')
    root, sha, alt = workspace()
    # The request always carries a validated probeSha256 (the req step refuses one that is missing),
    # so the fetch step always has it set; pass it here as the real workflow does.
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': PROBE_SHA256})
    check('the probe is fetched at the exact SHA despite orphan gitlinks', code == 0 and 'Q-05 cross-tenant isolation probe' in read(root, 'work/probe.py'), text[-200:])
    entries, other_downloaded, probe_present = fetch_footprint(root, sha)
    check('the fetch checks nothing out: rc/ holds only .git (delta follow-up 1)', entries == ['.git'], str(entries))
    check('only the probe file is downloaded: another file of the probe branch never is (blob-less fetch)',
          probe_present and not other_downloaded, f'probe={probe_present} other={other_downloaded}')
    shutil.rmtree(root)
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': '2' * 40, 'PROBE_SHA256': PROBE_SHA256})
    check('a SHA that does not exist is refused', code != 0)
    shutil.rmtree(root)
    root, sha, alt = workspace(probe_body='print("not the probe")\n')
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': PROBE_SHA256})
    check('a fetched file that is not the probe is refused', code != 0 and 'not the Q-05 probe' in text, text[-160:])
    shutil.rmtree(root)

    print('fetch step: probeSha256')
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': PROBE_SHA256})
    check('a matching probeSha256 is accepted', code == 0, text[-160:])
    shutil.rmtree(root)
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': 'deadbeef' * 8})
    check('a mismatched probeSha256 is refused', code != 0 and 'reviewed probeSha256' in text, text[-160:])
    shutil.rmtree(root)
    root, sha, alt = workspace()
    code, text, _ = run(FETCH, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': PROBE_SHA256[:16]})
    check('a correct 16-hex PREFIX of the probe hash is refused at fetch (full equality only)',
          code != 0 and 'reviewed probeSha256' in text, text[-160:])
    shutil.rmtree(root)


def signin_suite():
    print('sign-in + probe step')
    PUB = 'sb_publishable_test1234567890'
    secrets_otp = {'Q05_EMAIL_A': EMAIL_A, 'Q05_CODE_A': CODE_A, 'Q05_EMAIL_B': EMAIL_B, 'Q05_CODE_B': CODE_B,
                   'Q05_SUPABASE_PUBLISHABLE_KEY': PUB}

    last = {}   # side logs of the most recent signin(): argv lines, apikeys sent, verify bodies, leftovers

    def signin(mode, secrets, exit_code=0, cases=None, knobs=None):
        root, sha, alt = workspace(git_repos=False)
        open(os.path.join(root, 'work', 'probe.py'), 'w').write(STUB_PROBE)
        with open(os.path.join(root, 'work', 'probe_knobs.json'), 'w') as fh:
            json.dump({'cases': cases or [], 'exit': exit_code}, fh)
        env = {'MODE': mode, 'EXPECT_REV': EXPECT_REV, 'INHERITED_SECRET': 'leaky-inherited-value'}
        env.update(secrets)
        env.update(knobs or {})
        code, text, _ = run(SIGNIN, root, env)
        penv = read(root, 'work/probe_env.json')
        penv = json.loads(penv) if penv else {}
        summary = read(root, 'summary.md')
        curl = read(root, 'curl.log')
        last.clear()
        last.update(argv=read(root, 'argv.log'), apikeys=[l for l in read(root, 'apikey.log').splitlines() if l],
                    verify=[json.loads(l) for l in read(root, 'verify.log').splitlines() if l.strip()],
                    leftovers=[n for n in os.listdir(os.path.join(root, 'tmp')) if n.startswith('q05s.')])
        shutil.rmtree(root)
        return code, text, penv, summary, curl

    # happy: OTP, generic (serving build sourceRevision null -> smoke)
    code, text, penv, summary, curl = signin('generic', secrets_otp)
    check('generic OTP run succeeds and runs the probe', code == 0 and penv.get('Q05_BASE_URL') == BASE_URL and penv.get('Q05_TOKEN_A') == FAKE_TOKEN and penv.get('Q05_WORKSPACE_A') == FAKE_WS, text[-300:])
    check('generic passes --smoke and not the synthetic flag', penv.get('smoke') is True and penv.get('victim_is_synthetic_flag') is False)
    check('the probe ran under a minimal env (no inherited secret reached it)', penv.get('inherited_secret_seen') == '', penv)
    check('the receipt and the serving sourceRevision are in the step summary', 'Q-05 hosted probe (generic)' in summary and 'sourceRevision' in summary and 'SMOKE run' in summary)
    check('the OTP code is exchanged at the FIXED Supabase verify endpoint; no password grant', f'CURL POST {SUPABASE_URL}/auth/v1/verify' in curl and 'grant_type=password' not in curl)
    check('both sessions are signed out at the end', curl.count(f'CURL POST {SUPABASE_URL}/auth/v1/logout') == 2)
    check('no secret appears outside an add-mask line (generic OTP)', all(s not in strip_masks(text) for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS, PUB)), strip_masks(text)[-300:])
    check('every secret is masked at least once', all(f'::add-mask::{s}' in text for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS)))
    # INFO (delta review): no e-mail, code, key or token on ANY command line (curl, jq, env, python3)
    leaked = [s for s in (EMAIL_A, EMAIL_B, CODE_A, CODE_B, PUB, FAKE_TOKEN) if s in last['argv']]
    check('no e-mail, code, key or token appears in any curl/jq/env/python3 argv', not leaked and 'curl ' in last['argv'],
          f'leaked={leaked}')
    check('the private header directory is removed at the end', last['leftovers'] == [], str(last['leftovers']))

    # gate mode (serving build matches expectSourceRevision) mints a state and passes it to the probe
    code, text, penv, summary, curl = signin('gate', secrets_otp, cases=[{'case': 'x', 'verdict': 'PASS', 'blast': ''}], knobs={'HEALTH_REV': EXPECT_REV})
    check('gate run succeeds when sourceRevision matches, and mints a victim OAuth state', code == 0 and penv.get('Q05_VICTIM_A_OAUTH_STATE') == FAKE_STATE, text[-300:])
    check('gate does NOT pass --smoke', penv.get('smoke') is False)
    check('the minted state is masked', f'::add-mask::{FAKE_STATE}' in text and FAKE_STATE not in strip_masks(text))

    # gate refuses when the serving build does not match the requested expectSourceRevision (M6)
    code, text, *_ = signin('gate', secrets_otp, knobs={'HEALTH_REV': 'a' * 40})
    check('gate refuses a serving build whose sourceRevision != expectSourceRevision', code != 0 and 'does not match expectSourceRevision' in text, text[-200:])

    # gate with connections-v2 OFF mints no state (L3: never reserve a cap slot on a v2-off build)
    code, text, penv, *_ = signin('gate', secrets_otp, cases=[{'case': 'x', 'verdict': 'PASS', 'blast': ''}], knobs={'HEALTH_REV': EXPECT_REV, 'V2_ON': 'false'})
    check('gate mints no OAuth state when connections-v2 is off', penv.get('Q05_VICTIM_A_OAUTH_STATE') == '')

    # M2: a secret/service key is refused (decoded locally, never printed)
    code, text, *_ = signin('generic', {**secrets_otp, 'Q05_SUPABASE_PUBLISHABLE_KEY': 'sb_secret_abcdef123456'})
    check('a sb_secret_ key is refused', code != 0 and 'SECRET' in text)
    import base64 as _b64
    svc = 'h.' + _b64.urlsafe_b64encode(b'{"role":"service_role"}').rstrip(b'=').decode() + '.s'
    code, text, *_ = signin('generic', {**secrets_otp, 'Q05_SUPABASE_PUBLISHABLE_KEY': svc})
    check('a service_role JWT key is refused, without printing it', code != 0 and 'service_role' in text and svc not in strip_masks(text))
    anon = 'h.' + _b64.urlsafe_b64encode(b'{"role":"anon"}').rstrip(b'=').decode() + '.s'
    code, text, *_ = signin('generic', {**secrets_otp, 'Q05_SUPABASE_PUBLISHABLE_KEY': anon})
    check('an anon JWT key is accepted', code == 0)
    # N4: an ALLOWLIST after trimming — anything that is not sb_publishable_* or an anon JWT is refused
    for label, bad in (('an unknown key shape (pk_test_...)', 'pk_test_publishable_1234567890'),
                       ('an authenticated-role JWT', 'h.' + _b64.urlsafe_b64encode(b'{"role":"authenticated"}').rstrip(b'=').decode() + '.s'),
                       ('a JWT without a role', 'h.' + _b64.urlsafe_b64encode(b'{"sub":"x"}').rstrip(b'=').decode() + '.s'),
                       ('a publishable key with an inner space', 'sb_publishable_bad key')):
        code, text, _p, _s, curl = signin('generic', {**secrets_otp, 'Q05_SUPABASE_PUBLISHABLE_KEY': bad})
        check(f'N4: {label} is refused before any request', code != 0 and 'CURL POST' not in curl and bad not in strip_masks(text), text[-160:])
    code, text, penv, _s, curl = signin('generic', {**secrets_otp, 'Q05_SUPABASE_PUBLISHABLE_KEY': '  ' + PUB + '\n'})
    check('N4: a publishable key with surrounding spaces/newline is accepted and sent TRIMMED',
          code == 0 and last['apikeys'] and set(last['apikeys']) == {PUB}, f"{text[-160:]} apikeys={last['apikeys']}")
    padded = {**secrets_otp, 'Q05_EMAIL_A': ' ' + EMAIL_A + '\n', 'Q05_CODE_A': CODE_A + ' \n'}
    code, text, *_ = signin('generic', padded)
    bodies = {(b.get('email'), b.get('token')) for b in last['verify']}
    check('N4: e-mails and codes with surrounding whitespace are trimmed before the verify call',
          code == 0 and (EMAIL_A, CODE_A) in bodies and all(e == e.strip() and t == t.strip() for e, t in bodies), str(bodies))

    # N5: the sign-out trap is installed BEFORE minting: a failure on B still signs A out
    code, text, _p, _s, curl = signin('generic', {**secrets_otp}, knobs={'FAIL_VERIFY_FOR': EMAIL_B})
    check('N5: when minting B fails, A (already minted) is still signed out',
          code != 0 and 'did not verify' in text and curl.count(f'CURL POST {SUPABASE_URL}/auth/v1/logout') == 1, curl[-300:])
    code, text, _p, _s, curl = signin('generic', {**secrets_otp}, knobs={'FAIL_VERIFY': '1'})
    check('N5: when minting A fails, nothing is signed out (no empty-token logout)',
          code != 0 and f'{SUPABASE_URL}/auth/v1/logout' not in curl, curl[-300:])

    # N6: gate checks the serving build BEFORE any one-time code is spent
    code, text, _p, _s, curl = signin('gate', secrets_otp, knobs={'HEALTH_REV': 'a' * 40})
    check('N6: a gate request for the wrong build stops before any OTP code is verified (codes stay unused)',
          code != 0 and 'does not match expectSourceRevision' in text and '/auth/v1/verify' not in curl, curl[-300:])

    # M3: both e-mail local parts must carry the q05 marker
    code, text, *_ = signin('generic', {**secrets_otp, 'Q05_EMAIL_A': 'realperson@gmail.com'})
    check('an e-mail without the q05 marker is refused', code != 0 and 'marker q05' in text)

    # failures / leaks
    code, text, *_ = signin('generic', {'Q05_SUPABASE_PUBLISHABLE_KEY': PUB})
    check('no OTP credentials fails, with a hint and no values', code != 0 and 'set Q05_EMAIL_A' in text)
    code, text, *_ = signin('generic', secrets_otp, knobs={'FAIL_VERIFY': '1'})
    check('a rejected OTP code fails the run', code != 0 and 'did not verify' in text, text[-200:])
    check('a leaky verify response never prints the e-mail or code', EMAIL_A not in strip_masks(text) and CODE_A not in strip_masks(text), strip_masks(text)[-300:])
    code, text, *_ = signin('generic', secrets_otp, knobs={'WS_COUNT': '0'})
    check('zero workspaces fails the run', code != 0 and 'workspace resolution failed' in text)
    code, text, *_ = signin('generic', secrets_otp, knobs={'WS_COUNT': '2'})
    check('two workspaces fails the run (ambiguous)', code != 0 and 'workspace resolution failed' in text)
    code, text, *_ = signin('generic', secrets_otp, exit_code=1)
    check('a non-zero probe exit fails the job', code != 0 and 'probe exit: 1' in text)
    code, text, *_ = signin('gate', secrets_otp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}], knobs={'HEALTH_REV': EXPECT_REV})
    check('gate fails when a non-send case is NOT RUN', code != 0 and 'were NOT RUN that must run' in text, text[-200:])
    code, text, *_ = signin('gate', secrets_otp, cases=[{'case': 'write.send.y', 'verdict': 'NOT_RUN', 'blast': 'send'}], knobs={'HEALTH_REV': EXPECT_REV})
    check('gate tolerates a send-blast case being NOT RUN (send-risk off)', code == 0, text[-200:])
    code, text, *_ = signin('generic', secrets_otp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}])
    check('generic/smoke does not fail the job on a NOT RUN case', code == 0, text[-200:])


def docs_suite():
    """N7: the owner sheet must not offer a sign-up the workflow will refuse (a Google address has no
    q05 marker), and must describe the plus-addressed 'e-mail me a code' sign-up it accepts."""
    owner = open(os.path.join(HERE, 'OWNER-STEPS.md')).read()
    one_time = owner.split('## One time', 1)[-1].split('## Each run', 1)[0]
    check('OWNER-STEPS one-time sign-up does not offer Google (no q05 marker possible)',
          'google' not in one_time.lower(), one_time[:300])
    check('OWNER-STEPS one-time sign-up says "e-mail me a code" with a plus-addressed q05 address',
          'e-mail me a code' in one_time.lower() and '+q05' in one_time, one_time[:300])
    check('OWNER-STEPS says the captain supplies the REVIEWED probe hash (N3)',
          'reviewed-probe-sha256' in owner or 'reviewed probe hash' in owner.lower())


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
    check('the request step reads sha, mode, probeSha256 and expectSourceRevision only from REQUEST.json',
          REQ.count('REQUEST.json') == 4 and all(k in REQ for k in ('"sha"', '"mode"', '"probeSha256"', '"expectSourceRevision"')))
    check('no run block interpolates a ${{ }} expression', all('${{' not in s.get('run', '') for s in job['steps']))
    check('every action is pinned to a full 40-hex SHA', all(len(s['uses'].split('@')[1].split(' ')[0]) == 40 for s in job['steps'] if 'uses' in s))
    secret_steps = sorted(n for n, s in STEPS.items() if any('secrets.' in str(v) for v in (s.get('env') or {}).values()))
    check('secrets are referenced only in the sign-in step', secret_steps == ['Sign in both accounts, resolve their workspaces, and run the probe'], secret_steps)
    signin_run = step('Sign in both accounts', d)['run']
    check('generic passes --smoke, gate never enables send-risk', '--smoke' in signin_run and '--allow-send-risk' not in signin_run)
    check('the step exits with the probe return code', 'exit "$rc"' in signin_run)
    check('the gate check exempts only send-blast NOT RUN', '.verdict == "NOT_RUN" and .blast != "send"' in signin_run)
    # hardening (adversarial review): minimal env, pinned python, probe hash, health gate, sign-out, key/e-mail guards
    check('the probe runs under a minimal env built with builtins (no `env -i VAR=secret`) and python3 -I',
          'unset "${kv%%=*}"' in signin_run and 'not minimal' in signin_run and 'exec python3 -I' in signin_run
          and 'env -i' not in signin_run)
    check('no secret is passed on a command line: headers via -H @file, bodies on stdin',
          '-H @"$(hdr' in signin_run and '--data-binary @-' in signin_run and '-H "apikey:' not in signin_run
          and '-H "Authorization:' not in signin_run and '--arg e "$email"' not in signin_run and '--data "$body"' not in signin_run)
    pos = lambda needle: signin_run.find(needle)
    check('N5: the sign-out trap is installed before the first OTP code is spent',
          -1 < pos('trap cleanup EXIT') < pos('TOKEN_A="$(mint_token A)"'))
    check('N6: the gate build check runs before the first OTP code is spent',
          -1 < pos('[ "$REV_BEFORE" = "$EXPECT_REV" ]') < pos('TOKEN_A="$(mint_token A)"'))
    check('N4: the key check is an allowlist (sb_publishable_ or role anon)',
          'sb_publishable_*)' in signin_run and 'anon) : ;;' in signin_run)
    check('the probe is NEVER told it may send, and the synthetic flag is not passed here',
          '--allow-send-risk' not in signin_run and '--victim-is-synthetic' not in signin_run)
    check('the fetch step pins and verifies the reviewed probeSha256', 'PROBE_SHA256' in FETCH and 'reviewed probeSha256' in FETCH)
    check('gate refuses a serving build whose sourceRevision != expectSourceRevision',
          '/api/health' in signin_run and 'does not match expectSourceRevision' in signin_run)
    check('both sessions are signed out via a trap on EXIT', 'trap cleanup EXIT' in signin_run and '/auth/v1/logout' in signin_run)
    check('a secret/service-role key is refused before any sign-in', 'service_role' in signin_run and 'SECRET' in signin_run)
    check('both e-mail local parts must carry the q05 marker', 'q05' in signin_run and 'marker q05' in signin_run)
    check('every curl has a connect and max timeout', '--connect-timeout 10' in signin_run and '--max-time 30' in signin_run)


# --------------------------------------------------------------------------- mutation harness
EVAL_SECRETS = {'Q05_EMAIL_A': EMAIL_A, 'Q05_CODE_A': CODE_A, 'Q05_EMAIL_B': EMAIL_B, 'Q05_CODE_B': CODE_B,
                'Q05_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_eval1234567890'}


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
        fetchrun = step('Fetch the probe', d)['run']
        signinrun = step('Sign in both accounts', d)['run']
    except Exception:
        return False
    results = []

    # req: generic passes, bad mode refused, not-tip refused, re-run refused. Every request pins the
    # reviewed probeSha256 (and, in gate mode, expectSourceRevision) just as make_request_branch.sh does.
    def req(body, branch, age=60, attempt='1', wrong_tip=False):
        root, sha, alt = workspace()
        if wrong_tip:
            git('update-ref', f'refs/heads/{PROBE_BRANCH}', alt, cwd=os.path.join(root, 'origin', 'PostRiff.git'))
        if isinstance(body, dict):
            body = dict(body)
            body.setdefault('probeSha256', PROBE_SHA256)
            if body.get('mode') == 'gate':
                body.setdefault('expectSourceRevision', EXPECT_REV)
            body = json.loads(json.dumps(body).replace('SHA', sha))
        write_request(root, body, age=age)
        code, _t, _o = run(reqrun, root, {'REF_NAME': branch, 'GITHUB_RUN_ATTEMPT': attempt})
        shutil.rmtree(root)
        return code
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G) == 0)
    results.append(req({'sha': 'SHA', 'mode': 'deploy'}, RUN_G) != 0)       # unknown mode refused
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G, wrong_tip=True) != 0)
    results.append(req({'sha': 'SHA', 'mode': 'generic'}, RUN_G, attempt='2') != 0)
    results.append(req({'sha': 'SHA', 'mode': 'generic', 'probeSha256': PROBE_SHA256[:16]}, RUN_G) != 0)  # N3

    # fetch: the reviewed probeSha256 must EQUAL the fetched probe's hash (no prefix match), and only that
    # one file is ever downloaded, nothing checked out
    def fetch(probe_sha256, footprint=False):
        root, sha, alt = workspace()
        code, _t, _o = run(fetchrun, root, {'SOURCE_SHA': sha, 'PROBE_SHA256': probe_sha256})
        fp = fetch_footprint(root, sha) if footprint else None
        shutil.rmtree(root)
        return (code, fp) if footprint else code
    code, (entries, other_downloaded, probe_present) = fetch(PROBE_SHA256, footprint=True)
    results.append(code == 0 and entries == ['.git'] and probe_present and not other_downloaded)
    results.append(fetch('deadbeef' * 8) != 0)
    results.append(fetch(PROBE_SHA256[:16]) != 0)                                                      # N3

    # signin: the probe runs in a minimal env and reads its knobs from a FILE (never env).
    def signin(mode, secrets, exit_code=0, cases=None, knobs=None):
        root, sha, alt = workspace(git_repos=False)
        open(os.path.join(root, 'work', 'probe.py'), 'w').write(STUB_PROBE)
        with open(os.path.join(root, 'work', 'probe_knobs.json'), 'w') as fh:
            json.dump({'cases': cases or [], 'exit': exit_code}, fh)
        env = {'MODE': mode, 'EXPECT_REV': EXPECT_REV, 'INHERITED_SECRET': 'leaky-inherited-value'}
        env.update(secrets); env.update(knobs or {})
        code, text, _ = run(signinrun, root, env)
        penv = read(root, 'work/probe_env.json'); penv = json.loads(penv) if penv else {}
        curl = read(root, 'curl.log')
        argv = read(root, 'argv.log')
        shutil.rmtree(root)
        return code, text, penv, curl, argv
    sotp = EVAL_SECRETS
    code, text, penv, curl, argv = signin('generic', sotp)
    results.append(code == 0 and penv.get('Q05_TOKEN_A') == FAKE_TOKEN and penv.get('smoke') is True)
    results.append(penv.get('inherited_secret_seen') == '')                 # minimal env: no inherited secret
    results.append(all(s not in strip_masks(text) for s in (FAKE_TOKEN, EMAIL_A, CODE_A, FAKE_WS)))
    results.append(f'CURL POST {SUPABASE_URL}/auth/v1/verify' in curl and 'grant_type=password' not in curl)
    results.append(curl.count(f'CURL POST {SUPABASE_URL}/auth/v1/logout') == 2)   # both sessions signed out
    results.append(not any(s in argv for s in (EMAIL_A, CODE_A, EVAL_SECRETS['Q05_SUPABASE_PUBLISHABLE_KEY'], FAKE_TOKEN)))  # INFO
    code, text, *_ = signin('generic', sotp, knobs={'FAIL_VERIFY': '1'})
    results.append(code != 0 and EMAIL_A not in strip_masks(text) and CODE_A not in strip_masks(text))
    code, _t, _p, curl, _a = signin('generic', sotp, knobs={'FAIL_VERIFY_FOR': EMAIL_B})   # N5
    results.append(code != 0 and curl.count(f'CURL POST {SUPABASE_URL}/auth/v1/logout') == 1)
    code, _t, *_ = signin('generic', sotp, exit_code=1)
    results.append(code != 0)                                              # probe exit propagated
    # gate: health must match expectSourceRevision (checked before any code is spent), and a non-send
    # NOT-RUN case fails the gate
    code, _t, *_ = signin('gate', sotp, cases=[{'case': 'read.x', 'verdict': 'NOT_RUN', 'blast': ''}], knobs={'HEALTH_REV': EXPECT_REV})
    results.append(code != 0)
    code, _t, _p, curl, _a = signin('gate', sotp, knobs={'HEALTH_REV': 'a' * 40})
    results.append(code != 0 and '/auth/v1/verify' not in curl)          # N6 (and the M6 build gate)
    # key / e-mail guards
    svc = 'h.' + base64.urlsafe_b64encode(b'{"role":"service_role"}').rstrip(b'=').decode() + '.s'
    code, _t, *_ = signin('generic', {**sotp, 'Q05_SUPABASE_PUBLISHABLE_KEY': svc})
    results.append(code != 0)                                              # service_role JWT refused
    code, _t, *_ = signin('generic', {**sotp, 'Q05_SUPABASE_PUBLISHABLE_KEY': 'pk_test_publishable_1234567890'})
    results.append(code != 0)                                              # N4: unknown key shape refused
    code, _t, *_ = signin('generic', {**sotp, 'Q05_EMAIL_A': 'realperson@gmail.com'})
    results.append(code != 0)                                              # missing q05 marker refused

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
    ('accept any mode (drop the generic/gate allowlist)', '*) echo \'mode must be "generic" or "gate"\'; exit 1 ;;', '*) : ;;'),
    ('drop the run_attempt guard', "[ \"${GITHUB_RUN_ATTEMPT:-1}\" = 1 ] || { echo 're-runs are refused; push a new request'; exit 1; }", "true"),
    ('drop the tip-of-branch check', '[ "$tip" = "$sha" ] || { echo "the request SHA is not the current tip of ${RC_BRANCH}"; exit 1; }', 'true'),
    # adversarial-review additions
    ('accept a service_role key', "service_role) echo 'refusing: the key is a service_role JWT, not the anon/publishable key'; exit 1 ;;", "service_role) : ;;"),
    # delta-review N4: the key check is an allowlist; turning the fallback into "accept" is a denylist again
    ('accept any other key shape (denylist again)', "*) echo 'refusing: Q05_SUPABASE_PUBLISHABLE_KEY must be the publishable key (sb_publishable_...) or an anon JWT; a SECRET or unknown key is never used'; exit 1 ;;", "*) : ;;"),
    ('drop the probeSha256 verification', '[ "$actual" = "$PROBE_SHA256" ] || { echo \'the fetched probe does not match the reviewed probeSha256 in the request\'; exit 1; }', 'true'),
    # delta follow-up 1: nothing but the probe file before the hash check
    ('check out the probe-branch tree again before the hash check',
     'git -C rc show "$SOURCE_SHA:scripts/q05_tenant_probe.py"',
     'git -C rc checkout -q --detach FETCH_HEAD; git -C rc show "$SOURCE_SHA:scripts/q05_tenant_probe.py"'),
    ('download every file of the probe branch (drop the blob-less fetch)', [
        ('          git -C rc config remote.origin.partialclonefilter blob:none\n', ''),
        ('fetch -q --depth=1 --filter=blob:none origin', 'fetch -q --depth=1 origin')]),
    # delta-review N3: a hash PREFIX must never be enough, in the request or at fetch
    ('accept a 16-hex probeSha256 prefix in the request', '[[ "$probesha" =~ ^[0-9a-f]{64}$ ]]', '[[ "$probesha" =~ ^[0-9a-f]{16,64}$ ]]'),
    ('compare only a prefix of the probe hash at fetch', '[ "$actual" = "$PROBE_SHA256" ] ||', '[[ "$actual" == "$PROBE_SHA256"* ]] ||'),
    ('drop the gate health-revision gate', '[ "$REV_BEFORE" = "$EXPECT_REV" ] || { echo "gate: the serving build sourceRevision does not match expectSourceRevision in the request"; exit 1; }', "true"),
    ('drop the e-mail q05 marker check', "*) echo 'refusing: both test e-mail local parts must contain the marker q05 (e.g. name+q05a@gmail.com)'; exit 1 ;;", "*) : ;;"),
    # minimal env: keep the exports but drop the clearing loop AND its self-check -> inherited secrets reach the probe
    ('run the probe with the full inherited env (drop the clearing and its self-check)', [
        ("            while IFS= read -r -d '' kv; do unset \"${kv%%=*}\" 2>/dev/null || true; done < <(env -0)\n", ''),
        ("            [ \"$names\" = \"PATH Q05_BASE_URL Q05_TOKEN_A Q05_TOKEN_B Q05_VICTIM_A_OAUTH_STATE Q05_VICTIM_B_OAUTH_STATE Q05_WORKSPACE_A Q05_WORKSPACE_B \" ] \\\n"
         "              || { echo 'refusing: the probe environment is not minimal' >&2; exit 97; }\n", '')]),
    ('drop only the clearing loop (the self-check must stop the run)',
     "            while IFS= read -r -d '' kv; do unset \"${kv%%=*}\" 2>/dev/null || true; done < <(env -0)\n", ''),
    # delta-review N5: the trap installed only after both tokens are minted (A unsigned-out if B fails)
    ('install the sign-out trap only after both tokens are minted', [
        ('          trap cleanup EXIT\n', ''),
        ('TOKEN_B="$(mint_token B)" || exit 1; echo "::add-mask::$TOKEN_B"\n',
         'TOKEN_B="$(mint_token B)" || exit 1; echo "::add-mask::$TOKEN_B"\n          trap cleanup EXIT\n')]),
    # delta-review N6: the gate build check after the codes are spent
    ('check the gate build only after both codes are spent', [
        ('          REV_BEFORE="$(health_rev)"\n          if [ "$MODE" = gate ]; then\n'
         '            [ "$REV_BEFORE" = "$EXPECT_REV" ] || { echo "gate: the serving build sourceRevision does not match expectSourceRevision in the request"; exit 1; }\n'
         '          fi\n', ''),
        ('WS_B="$(resolve_ws "$TOKEN_B")" || { echo \'account B: workspace resolution failed\'; exit 1; }; echo "::add-mask::$WS_B"\n',
         'WS_B="$(resolve_ws "$TOKEN_B")" || { echo \'account B: workspace resolution failed\'; exit 1; }; echo "::add-mask::$WS_B"\n'
         '          REV_BEFORE="$(health_rev)"\n          if [ "$MODE" = gate ]; then\n'
         '            [ "$REV_BEFORE" = "$EXPECT_REV" ] || { echo "gate: the serving build sourceRevision does not match expectSourceRevision in the request"; exit 1; }\n'
         '          fi\n')]),
    # delta-review INFO: secrets back on command lines
    ('pass the key on the curl command line again',
     '-H @"$(hdr "apikey: $key" \'Content-Type: application/json\')"', '-H "apikey: $key" -H \'Content-Type: application/json\''),
    ('pass the e-mail and code on the jq command line again',
     'body="$(printf \'%s\\n%s\\n\' "$email" "$code" | jq -Rnc \'[inputs] as $l | {type:"email",email:$l[0],token:$l[1]}\')"',
     'body="$(jq -nc --arg e "$email" --arg t "$code" \'{type:"email",email:$e,token:$t}\')"'),
]


def mutation_suite():
    print('mutation checks (each weakening must be caught by at least one test)')
    base = open(WORKFLOW).read()
    caught, survivors = 0, []
    for entry in MUTATIONS:
        # (label, old, new) or (label, [(old, new), ...]) for a weakening that needs coordinated hunks
        label, hunks = entry[0], (entry[1] if len(entry) == 2 else [(entry[1], entry[2])])
        mutated, missing = base, False
        for old, new in hunks:
            if old not in mutated:
                missing = True
                break
            mutated = mutated.replace(old, new, 1)
        if missing:
            survivors.append(label + ' [HUNK NOT FOUND]')
            print(f'  FAIL mutation hunk not found: {label}')
            failures.append('mutation hunk: ' + label)
            continue
        mpath = os.path.join(tempfile.mkdtemp(prefix='q05mut-'), 'wf.yml')
        open(mpath, 'w').write(mutated)
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
    if want('mutations'):
        mutation_suite()
    if ONLY:
        print(f'\n(partial run: only {sorted(ONLY)}; run with Q05_RT_ONLY unset before any commit or review)')
    print(f'\n{passes} passed, {len(failures)} failed')
    if failures:
        print('FAILED:', failures)
        sys.exit(1)
