"""Exact-SHA CI evidence for Founder Admin › Advanced › Engineering in hosted environments (migration 071).

Why. Production is whatever Vercel builds from `consumer-saas`. Until now the only required-check manifest was a manually
captured LOCAL snapshot (052), so a hosted Engineering tab could only ever say 'suspected'.
`.github/workflows/founder-engineering-evidence.yml` runs this collector on every push to consumer-saas, every 15
minutes, on demand, and when a required workflow finishes a push run on consumer-saas. Each run judges the CURRENT TIP of
consumer-saas (the commit Vercel deploys) and records, through the dedicated ingest login:

* one `rafii_control.engineering_evidence` row per required check (kind 'check', provider 'github' or 'vercel',
  external id `ci/<sha>/<check key>`), updated in place as the check moves from pending to concluded, and
* a `rafii_control.github_check_snapshots` manifest (provenance 'ci_attested', payload schemaVersion 2) naming which
  checks were required for that exact SHA and why, inserted only when the evaluation changed.

Required checks (REQUIRED_CHECKS). The four GitHub Actions jobs that gate a change into consumer-saas, pinned by workflow
FILE and job id (a same-named workflow in another file never counts), plus Vercel's own commit status on the exact SHA.
consumer-ready `local-gates` and Vercel are required for every commit. The other three workflows run on pull_request only
when their path filter matches (copied in `paths`; tests/control/test_ci_evidence.py fails when a workflow file's filter
drifts from this copy). Such a check is required when it ran for the commit, when the merged PR changed a file its filter
matches, or when that cannot be decided (no merged PR, changed-file list incomplete, run listing incomplete, unsupported
pattern). It is exempt only when no run exists AND none of the merged PR's changed files match its filter, which is
exactly when GitHub itself did not run it.

Where evidence comes from. None of the required workflows runs on push today, so the merge commit itself usually has no
runs. For each Actions check the collector takes, in order:
1. exact SHA: the newest push/workflow_dispatch run of the pinned workflow on consumer-saas whose head SHA is the tip
   (used automatically if those workflows ever gain a push trigger); else
2. merged PR head: the newest pull_request/workflow_dispatch run on the head H of the same-repository PR whose
   merge_commit_sha is the tip. It counts for the tip only when GitHub shows (a) tree(H) == tree(tip) and (b) the tip's
   first parent (consumer-saas just before the merge) is an ancestor of H. By (b) every base a PR run was tested against
   was already inside H, so GitHub's test merge was byte-identical to H, and by (a) to the tip: the run tested exactly
   the production tree. Otherwise the PR's results are recorded but never attested.
Vercel is read from the exact SHA only: status context 'Vercel' created by 'vercel[bot]'.

What "attested" means. A row is attested only when (1) it was written by the trusted workflow running consumer-saas code
(never a pull_request or fork event, which never reach the step holding the secret) through a login that can only SET
ROLE rafii_control_ingest; (2) its conclusion was read from GitHub's REST API with the job's read-only GITHUB_TOKEN, never
from an artifact, log, output, PR text or anything else a PR author controls; and (3) it is a completed conclusion of the
pinned workflow file and job (or Vercel's bot status) on the exact SHA, or on a same-repository merged PR head meeting
(a) and (b). Pending, missing, ambiguous, fork and non-identical-tree evidence is recorded unattested, and only an
attested success may say 'checks_passed'. The collector's own run id/attempt and each check's run, attempt and job ids
are kept in the manifest. Attestation proves that the checks defined in this exact tree concluded success; whether
those checks are meaningful is the merged code's own review (a PR that weakens a workflow is part of the merged tree).

Residual assumptions (documented, not checkable from the API): consumer-saas history is never rewritten, and a PR's last
runs were made against consumer-saas (a PR retargeted after its last run, or two open PRs sharing one head SHA against
different bases, could have been tested against another base).

Never: writes from a pull_request or fork event, prints a token, DSN or server message (fixed codes and exception
classes only), dispatches or re-runs anything, or claims merged, deployed or fixed. Standard library only at import;
psycopg is imported by `write`.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = 'dev-james0723/PostRiff'
PRODUCTION_BRANCH = 'consumer-saas'
SCHEMA_VERSION = 2
MANIFEST_VERSION = 2
ADAPTER_VERSION = 'github-ci-evidence/1'
PROVENANCE = 'ci_attested'
INGEST_ROLE = 'rafii_control_ingest'
ENVIRONMENTS = ('local', 'staging', 'production')
API = 'https://api.github.com'
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/dev-james0723/PostRiff/founder-engineering-evidence')
EXACT_SHA = re.compile('[0-9a-f]{40}')
PER_PAGE = 100
MAX_RUN_PAGES = 3      # 300 runs per SHA; more leaves the run listing incomplete (filtered checks stay required)
MAX_FILE_PAGES = 30    # GitHub lists at most 3000 files of a pull request

REQUIRED_CHECKS = (
    dict(key='consumer-ready/local-gates', provider='github', workflowPath='.github/workflows/consumer-ready.yml',
         workflowName='Rafii local release gates', job='local-gates', paths=None,
         why='Release gates for every change: Python and PostgreSQL suites, web contracts, types, lint, production build, '
             'copy audit, secret scan and dependency audits.'),
    dict(key='rafii-control/local-foundation', provider='github', workflowPath='.github/workflows/rafii-control.yml',
         workflowName='Rafii Control foundation', job='local-foundation',
         paths=('src/rafii_control/**', 'control-web/**', 'api/control.py', 'migrations/postriff/049_*', 'migrations/postriff/051_*',
                'migrations/postriff/052_*', 'migrations/postriff/053_*', 'migrations/postriff/05[4-9]_*', 'migrations/postriff/06[0-9]_*',
                'migrations/postriff/07[0-9]_*', 'scripts/rafii_control_*', 'tests/control/**', 'tests/phase2/rls.sql',
                'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/**', 'docs/releases/founder-admin-2026-10-01/**', '.github/workflows/rafii-control.yml'),
         why='Founder Control boundary, restricted PostgreSQL roles and migrations; GitHub runs it when a Control path changes.'),
    dict(key='rafii-browser/scenes', provider='github', workflowPath='.github/workflows/rafii-browser.yml',
         workflowName='Rafii browser scenes', job='scenes',
         paths=('web/**', 'src/postriff_phase2/**', 'scripts/postriff_dev_hosted.py', '.github/workflows/rafii-browser.yml'),
         why='Real-input browser scenes of the consumer app; GitHub runs it when a web or agent-runtime path changes.'),
    dict(key='founder-browser/founder', provider='github', workflowPath='.github/workflows/founder-browser.yml',
         workflowName='Founder admin browser', job='founder',
         paths=('web/**', 'src/rafii_control/**', 'src/postriff_phase2/**', 'migrations/postriff/**', 'scripts/postriff_dev_hosted.py',
                'scripts/founder_signin_web.py', 'tests/founder_browser_fixture.py', 'tests/phase2/rls.sql', '.github/workflows/founder-browser.yml'),
         why='End-to-end founder surface on a production build; GitHub runs it when a web, Control, runtime or migration path changes.'),
    dict(key='vercel/production', provider='vercel', context='Vercel', creator='vercel[bot]', paths=None,
         why='Vercel builds production from consumer-saas; its own commit status on the exact SHA says whether that build succeeded.'),
)
ACTIONS_CHECKS = tuple(check for check in REQUIRED_CHECKS if check['provider'] == 'github')

# GitHub job conclusions → engineering_evidence.conclusion (049's vocabulary) and the outcome the verdict reads.
CONCLUSIONS = {'success': 'success', 'failure': 'failure', 'startup_failure': 'failure', 'timed_out': 'timed_out',
               'cancelled': 'cancelled', 'skipped': 'skipped', 'neutral': 'neutral', 'action_required': 'action_required', 'stale': 'unknown'}
EVIDENCE_CONCLUSIONS = ('success', 'failure', 'cancelled', 'skipped', 'neutral', 'timed_out', 'action_required', 'unknown')
OUTCOMES = ('success', 'failure', 'cancelled', 'skipped', 'neutral', 'unknown', 'incomplete', 'missing')
VERCEL_STATES = {'success': ('success', None), 'failure': ('failure', 'unknown'), 'error': ('failure', 'infrastructure')}
EVENTS = ('push', 'schedule', 'workflow_run', 'workflow_dispatch')


class CollectorError(Exception):
    """A fixed, content-free reason code; never a provider body, header or URL."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class IngestRefused(Exception):
    """The DSN's login is not a non-privileged, SET-only (NOINHERIT) member of rafii_control_ingest."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return value if isinstance(value, str) and EXACT_SHA.fullmatch(value) else None


def _int(value):
    return value if type(value) is int and value > 0 else None


def _text(value, limit=200):
    return value[:limit] if isinstance(value, str) else None


def _printable(value, limit=200):
    """A file name safe to store and print: no control characters, so a log line can never start a workflow command."""
    return re.sub(r'[^\x20-\x7e]', '?', value)[:limit] if isinstance(value, str) else None


def _api(path):
    return f'/repos/{REPOSITORY}{path}'


# --- path filters ----------------------------------------------------------------------------------------------------
def glob(pattern):
    """A GitHub workflow path-filter pattern as a regex: `**` (any characters), `**/` (any directories), `*` (anything
    but '/'), `[a-z0-9]` classes and literals. Anything else (`?`, `+`, `!`, braces, escapes) raises ValueError so the
    caller keeps the check required instead of guessing."""
    out, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith('**/', index):
            out.append('(?:.*/)?')
            index += 3
        elif pattern.startswith('**', index):
            out.append('.*')
            index += 2
        elif char == '*':
            out.append('[^/]*')
            index += 1
        elif char == '[':
            end = pattern.find(']', index)
            body = pattern[index + 1:end] if end > index else ''
            if not re.fullmatch(r'(?:[A-Za-z0-9](?:-[A-Za-z0-9])?)+', body):
                raise ValueError('unsupported character class')
            out.append('[' + body + ']')
            index = end + 1
        elif char in '?+!{}\\]':
            raise ValueError('unsupported pattern syntax')
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile(''.join(out), re.DOTALL)   # `**` spans every character, a newline in a file name included


def first_match(patterns, names):
    """The first changed file any pattern matches, or None. Raises ValueError for an unsupported pattern."""
    compiled = [glob(pattern) for pattern in patterns]
    return next((name for name in names if any(regex.fullmatch(name) for regex in compiled)), None)


def applicability(check, *, ran, runs_complete, pr, files):
    """(required, reason, matched file) for one Actions check of one commit; exemption needs positive proof."""
    if check.get('paths') is None:
        return True, 'always', None
    if ran:
        return True, 'ran', None
    if not runs_complete:
        return True, 'runs_unknown', None
    if pr is None:
        return True, 'no_pull_request', None
    if not isinstance(files, dict) or files.get('complete') is not True:
        return True, 'paths_unknown', None
    try:
        hit = first_match(check['paths'], files.get('names') or [])
    except ValueError:
        return True, 'paths_unknown', None
    return (True, 'paths_matched', _printable(hit)) if hit else (False, 'paths_unmatched', None)


# --- commit, pull request and run selection --------------------------------------------------------------------------
def merged_pull_request(pulls, sha):
    """The single PR merged into consumer-saas as exactly this commit: {number, sha, ref, repository} or None."""
    if not isinstance(pulls, list):
        return None
    found = [pull for pull in pulls if isinstance(pull, dict) and pull.get('merged_at') and pull.get('merge_commit_sha') == sha
             and (pull.get('base') or {}).get('ref') == PRODUCTION_BRANCH
             and ((pull.get('base') or {}).get('repo') or {}).get('full_name') == REPOSITORY]
    if len(found) != 1:
        return None
    pull, head = found[0], found[0].get('head') or {}
    if _int(pull.get('number')) is None or _sha(head.get('sha')) is None or not isinstance(head.get('ref'), str):
        return None
    return dict(number=pull['number'], sha=head['sha'], ref=head['ref'], repository=(head.get('repo') or {}).get('full_name'))


def first_parent(commit):
    parents = commit.get('parents') if isinstance(commit, dict) else None
    return _sha((parents[0] or {}).get('sha')) if isinstance(parents, list) and parents and isinstance(parents[0], dict) else None


def pr_route(pr, commit, head_commit, containment):
    """Whether the merged PR head's runs tested exactly this commit's tree. Always returns the route; `qualified` says
    whether its runs may be attested for the exact SHA, `reason` why not."""
    parents = [item.get('sha') for item in (commit.get('parents') or []) if isinstance(item, dict)]
    tree = ((commit.get('tree') or {}).get('sha'))
    head_tree = (((head_commit or {}).get('tree') or {}).get('sha')) if isinstance(head_commit, dict) else None
    identical = _sha(tree) is not None and tree == head_tree and (head_commit or {}).get('sha') == pr['sha']
    contained = (isinstance(containment, dict) and containment.get('status') in ('ahead', 'identical') and containment.get('behind_by') == 0
                 and bool(parents) and ((containment.get('merge_base_commit') or {}).get('sha')) == parents[0])
    reason = next((code for ok, code in (
        (pr['repository'] == REPOSITORY, 'fork_pull_request'),
        (len(parents) in (1, 2), 'unexpected_parents'),
        (len(parents) != 2 or parents[1] == pr['sha'], 'merge_parent_mismatch'),
        (identical, 'tree_differs'),
        (contained, 'base_not_contained'),
    ) if not ok), None)
    return dict(number=pr['number'], headSha=pr['sha'], headRef=_text(pr['ref']), treeIdentical=identical, baseContained=contained,
                qualified=reason is None, reason=reason or 'tree_identical_base_contained')


def _pinned(run, check):
    return (isinstance(run, dict) and _int(run.get('id')) is not None
            and str(run.get('path') or '').split('@', 1)[0] == check['workflowPath']
            and (run.get('repository') or {}).get('full_name') == REPOSITORY
            and (run.get('head_repository') or {}).get('full_name') == REPOSITORY)


def _newest(runs):
    return max(runs, key=lambda run: (_int(run.get('run_number')) or 0, run['id']))


def select_run(runs, check, sha, route):
    """(run, source) for one Actions check: the newest run of its pinned workflow file on the exact SHA (push or
    workflow_dispatch on consumer-saas), else on the merged same-repository PR head (pull_request, or workflow_dispatch on
    its branch), else (None, None)."""
    exact = [run for run in runs if _pinned(run, check) and run.get('head_sha') == sha
             and run.get('event') in ('push', 'workflow_dispatch') and run.get('head_branch') == PRODUCTION_BRANCH]
    if exact:
        return _newest(exact), 'exact_sha'
    if route:
        head = [run for run in runs if _pinned(run, check) and run.get('head_sha') == route['headSha']
                and run.get('head_branch') == route['headRef'] and run.get('event') in ('pull_request', 'workflow_dispatch')]
        if head:
            return _newest(head), 'pull_request_head'
    return None, None


def job_for(body, run, check):
    """(job, problem): the single job named after the check in the run's latest attempt."""
    jobs = body.get('jobs') if isinstance(body, dict) else None
    if not isinstance(jobs, list):
        return None, 'jobs_unreadable'
    matches = [job for job in jobs if isinstance(job, dict) and job.get('name') == check['job'] and job.get('run_id') == run['id']
               and job.get('head_sha') == run.get('head_sha')]
    if len(matches) != 1:
        return None, 'job_missing' if not matches else 'job_ambiguous'
    return matches[0], None


def vercel_status(statuses, check):
    """Vercel's newest own status for the SHA (context and bot creator pinned), or None."""
    if not isinstance(statuses, list):
        return None
    mine = [status for status in statuses if isinstance(status, dict) and status.get('context') == check['context']
            and (status.get('creator') or {}).get('login') == check['creator'] and _int(status.get('id')) is not None]
    return max(mine, key=lambda status: status['id']) if mine else None


# --- evaluation ------------------------------------------------------------------------------------------------------
def _entry(check, **values):
    entry = dict(key=check['key'], provider=check['provider'], required=True, requiredReason='always', matchedPath=None,
                 source='none', runId=None, runAttempt=None, jobId=None, statusId=None, headSha=None, event=None, status=None,
                 conclusion=None, outcome='missing', failureClass=None, completedAt=None, attested=False, note=None)
    entry.update(values)
    return entry


def _actions_entry(check, run, source, job, problem, route, required, reason, matched):
    base = dict(required=required, requiredReason=reason, matchedPath=matched)
    if run is None:
        return _entry(check, **base, note='no_run')
    base.update(source=source, runId=run['id'], runAttempt=_int(run.get('run_attempt')), headSha=_sha(run.get('head_sha')),
                event=_text(run.get('event'), 40))
    if job is None:
        return _entry(check, **base, note=problem)
    base.update(jobId=_int(job.get('id')), status=_text(job.get('status'), 40), completedAt=_text(job.get('completed_at'), 40))
    if job.get('status') != 'completed' or job.get('conclusion') is None:
        return _entry(check, **base, outcome='incomplete', note='incomplete')
    conclusion = CONCLUSIONS.get(job['conclusion'], 'unknown')
    outcome = 'success' if conclusion == 'success' else 'failure' if conclusion in ('failure', 'timed_out', 'action_required') else conclusion
    failure_class = 'infrastructure' if job['conclusion'] == 'startup_failure' else 'unknown' if outcome == 'failure' else None
    trusted = source == 'exact_sha' or (source == 'pull_request_head' and bool(route) and route['qualified'])
    note = None if trusted else (route or {}).get('reason', 'untrusted_source')
    return _entry(check, **base, conclusion=conclusion, outcome=outcome, failureClass=failure_class, attested=trusted, note=note)


def _vercel_entry(check, status):
    if status is None:
        return _entry(check, note='no_status')
    base = dict(source='exact_sha_status', statusId=status['id'], status=_text(status.get('state'), 40), completedAt=_text(status.get('updated_at'), 40))
    if status.get('state') not in VERCEL_STATES:
        return _entry(check, **base, outcome='incomplete', note='incomplete')
    conclusion, failure_class = VERCEL_STATES[status['state']]
    return _entry(check, **base, conclusion=conclusion, outcome=conclusion, failureClass=failure_class, attested=True)


def qualification(checks):
    """One word for a commit's required checks; only 'required_checks_succeeded' is green."""
    required = [check for check in checks if check.get('required') is True]
    if not required:
        return 'no_required_checks'
    if all(check.get('attested') is True and check.get('conclusion') == 'success' for check in required):
        return 'required_checks_succeeded'
    outcomes = {check.get('outcome') for check in required}
    if 'failure' in outcomes:
        return 'required_check_failed'
    if outcomes & {'incomplete', 'missing'}:
        return 'required_checks_incomplete'
    if any(check.get('attested') is not True for check in required):
        return 'required_checks_not_attested'
    return 'required_checks_not_green'


def manifest():
    return dict(version=MANIFEST_VERSION, repository=REPOSITORY, branch=PRODUCTION_BRANCH,
                checks=[{key: (list(value) if isinstance(value, tuple) else value) for key, value in check.items()} for check in REQUIRED_CHECKS])


def evaluate(facts, *, observed_at, collector=None):
    """The schemaVersion-2 manifest payload for the facts `gather` read (pure; no I/O)."""
    sha = _sha(facts.get('sha'))
    commit = facts.get('commit')
    if sha is None or not isinstance(commit, dict) or commit.get('sha') != sha:
        raise CollectorError('commit_unreadable')
    pr = merged_pull_request(facts.get('pulls'), sha)
    route = pr_route(pr, commit, facts.get('headCommit'), facts.get('containment')) if pr else None
    listings = facts.get('runs') or {}
    runs = [run for listing in listings.values() for run in (listing.get('runs') or [])]
    runs_complete = sha in listings and all(type(listing.get('total')) is int and listing['total'] <= len(listing.get('runs') or [])
                                            for listing in listings.values())
    files = facts.get('files')
    checks = []
    for check in REQUIRED_CHECKS:
        if check['provider'] == 'vercel':
            checks.append(_vercel_entry(check, vercel_status(facts.get('statuses'), check)))
            continue
        run, source = select_run(runs, check, sha, route)
        job, problem = job_for((facts.get('jobs') or {}).get(str(run['id'])), run, check) if run else (None, 'no_run')
        required, reason, matched = applicability(check, ran=run is not None, runs_complete=runs_complete, pr=pr, files=files)
        checks.append(_actions_entry(check, run, source, job, problem, route, required, reason, matched))
    required = [check for check in checks if check['required']]
    evaluation = dict(
        schemaVersion=SCHEMA_VERSION, adapterVersion=ADAPTER_VERSION, provenance=PROVENANCE, repository=REPOSITORY,
        branch=PRODUCTION_BRANCH, exactSha=sha, commit=dict(tree=_sha((commit.get('tree') or {}).get('sha')),
                                                             parents=[_sha((item or {}).get('sha')) for item in (commit.get('parents') or [])][:2]),
        pullRequest=route, manifest=manifest(), checks=checks, requiredCount=len(required), qualification=qualification(checks),
        changedFiles=None if not isinstance(files, dict) else dict(complete=files.get('complete') is True, count=len(files.get('names') or [])),
        coverage=dict(complete=runs_complete, runsReturned=len(runs), scope='exact_sha_and_merged_pull_request_head_runs'),
        releaseAccepted=False)
    evaluation['evaluationDigest'] = hashlib.sha256(canonical(evaluation).encode()).hexdigest()
    evaluation['observedAt'] = observed_at
    evaluation['collector'] = collector or {}
    return evaluation


def evidence_rows(evaluation, environment):
    """engineering_evidence rows (one per required check) for this evaluation; 'checks_passed' only for attested success."""
    if environment not in ENVIRONMENTS:
        raise ValueError('environment')
    sha, rows = evaluation['exactSha'], []
    for check in evaluation['checks']:
        if check['required'] is not True:
            continue
        external = f"ci/{sha}/{check['key']}"
        green = check['attested'] is True and check['conclusion'] == 'success'
        rows.append(dict(id=str(uuid.uuid5(NAMESPACE, f"{environment}/{check['provider']}/check/{external}")), environment=environment,
                         kind='check', provider=check['provider'], external_id=external, exact_sha=sha,
                         state='checks_passed' if green else 'suspected', conclusion=check['conclusion'], failure_class=check['failureClass'],
                         attested=check['attested'] is True, required=True, observed_at=evaluation['observedAt']))
    return rows


def summarize(payload, exact_sha=None):
    """Server-side re-derivation of a stored CI manifest (GET /engineering/checks). The stored summary fields are checked
    against the per-check entries, never trusted on their own; anything malformed is 'invalid_manifest' with no count."""
    try:
        if not isinstance(payload, dict) or payload.get('schemaVersion') != SCHEMA_VERSION or payload.get('adapterVersion') != ADAPTER_VERSION:
            raise ValueError('schema')
        if payload.get('repository') != REPOSITORY or payload.get('branch') != PRODUCTION_BRANCH or payload.get('provenance') != PROVENANCE:
            raise ValueError('scope')
        sha = _sha(payload.get('exactSha'))
        if sha is None or (exact_sha is not None and exact_sha != sha):
            raise ValueError('sha')
        declared = payload['manifest']
        if declared.get('version') != MANIFEST_VERSION:
            raise ValueError('manifest')
        keys = [item['key'] for item in declared['checks']]
        checks = payload['checks']
        if not isinstance(checks, list) or not 0 < len(checks) <= 20 or [check['key'] for check in checks] != keys or len(set(keys)) != len(keys):
            raise ValueError('checks')
        for check in checks:
            if type(check['required']) is not bool or type(check['attested']) is not bool or check['outcome'] not in OUTCOMES:
                raise ValueError('check')
            if check['conclusion'] is not None and check['conclusion'] not in EVIDENCE_CONCLUSIONS:
                raise ValueError('conclusion')
            if (check['conclusion'] == 'success') != (check['outcome'] == 'success') or (check['attested'] and check['conclusion'] is None):
                raise ValueError('consistency')
        required = [check for check in checks if check['required']]
        if not required or payload.get('requiredCount') != len(required) or payload.get('qualification') != qualification(checks):
            raise ValueError('count')
    except (KeyError, TypeError, ValueError, AttributeError):
        return dict(valid=False, checks=[], qualification='invalid_manifest', requiredCount=None, observedRequiredCount=0,
                    coverageComplete=False, releaseAccepted=False)
    return dict(valid=True, manifestVersion=MANIFEST_VERSION,
                checks=[dict(name=check['key'], provider=check['provider'], required=check['required'], requiredReason=check.get('requiredReason'),
                             outcome=check['outcome'], conclusion=check['conclusion'], attested=check['attested'], source=check.get('source'),
                             runId=check.get('runId'), runAttempt=check.get('runAttempt'), jobId=check.get('jobId'), note=check.get('note'))
                        for check in checks],
                qualification=qualification(checks), requiredCount=len(required),
                observedRequiredCount=sum(check['outcome'] != 'missing' for check in required),
                coverageComplete=(payload.get('coverage') or {}).get('complete') is True, releaseAccepted=False)


# --- GitHub (read-only) ----------------------------------------------------------------------------------------------
class GitHub:
    """Read-only REST client for this repository's CI metadata. The token only ever travels in the Authorization header;
    errors become fixed codes without the provider's body."""

    def __init__(self, token, *, opener=urlopen, timeout=15, max_bytes=16 * 1024 * 1024):
        self.token, self.opener, self.timeout, self.max_bytes = token, opener, timeout, max_bytes

    def get(self, path, params=None):
        url = API + path + ('?' + urlencode(params) if params else '')
        request = Request(url, headers={'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + self.token,
                                        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'rafii-founder-engineering-evidence'})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
        except HTTPError as error:
            raise CollectorError(f'github_http_{int(error.code)}') from None
        except (URLError, TimeoutError, OSError):
            raise CollectorError('github_unreachable') from None
        if len(raw) > self.max_bytes:
            raise CollectorError('github_response_too_large')
        try:
            return json.loads(raw)
        except ValueError:
            raise CollectorError('github_response_invalid') from None


def runs_for(client, sha):
    """Workflow runs whose head SHA is `sha` (all workflows, newest first), with GitHub's total for coverage."""
    runs, total = [], None
    for page in range(1, MAX_RUN_PAGES + 1):
        body = client.get(_api('/actions/runs'), {'head_sha': sha, 'per_page': PER_PAGE, 'page': page})
        batch = body.get('workflow_runs') if isinstance(body, dict) else None
        if not isinstance(batch, list):
            raise CollectorError('github_runs_unreadable')
        total = body.get('total_count')
        runs.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return dict(runs=runs, total=total if type(total) is int else None)


def pull_files(client, number):
    """Every file the merged PR changed ({complete, names}); None when unreadable (filtered checks then stay required)."""
    names = []
    for page in range(1, MAX_FILE_PAGES + 1):
        try:
            batch = client.get(_api(f'/pulls/{number}/files'), {'per_page': PER_PAGE, 'page': page})
        except CollectorError:
            return None
        if not isinstance(batch, list):
            return None
        for item in batch:
            if not isinstance(item, dict) or not isinstance(item.get('filename'), str):
                return None
            names.append(item['filename'])
            if isinstance(item.get('previous_filename'), str):
                names.append(item['previous_filename'])
        if len(batch) < PER_PAGE:
            return dict(complete=True, names=sorted(set(names)))
    return dict(complete=False, names=sorted(set(names)))


def gather(client):
    """Every GitHub fact `evaluate` needs for the current tip of consumer-saas (about a dozen read-only requests)."""
    ref = client.get(_api(f'/git/ref/heads/{PRODUCTION_BRANCH}'))
    target = (ref.get('object') or {}) if isinstance(ref, dict) else {}
    sha = _sha(target.get('sha')) if target.get('type') == 'commit' else None
    if sha is None:
        raise CollectorError('branch_tip_unreadable')
    commit = client.get(_api(f'/git/commits/{sha}'))
    pulls = client.get(_api(f'/commits/{sha}/pulls'), {'per_page': PER_PAGE})
    facts = dict(sha=sha, commit=commit, pulls=pulls, headCommit=None, containment=None, runs={}, jobs={}, files=None, statuses=[])
    pr = merged_pull_request(pulls, sha)
    if pr:
        facts['headCommit'] = client.get(_api(f"/git/commits/{pr['sha']}"))
        base = first_parent(commit)
        if base:
            facts['containment'] = client.get(_api(f"/compare/{base}...{pr['sha']}"), {'per_page': 1})
    for target_sha in [sha] + ([pr['sha']] if pr and pr['sha'] != sha else []):
        facts['runs'][target_sha] = runs_for(client, target_sha)
    route = pr_route(pr, commit, facts['headCommit'], facts['containment']) if pr and isinstance(commit, dict) else None
    runs = [run for listing in facts['runs'].values() for run in listing['runs']]
    unexplained = False
    for check in ACTIONS_CHECKS:
        run, _ = select_run(runs, check, sha, route)
        if run:
            facts['jobs'][str(run['id'])] = client.get(_api(f"/actions/runs/{run['id']}/jobs"), {'filter': 'latest', 'per_page': PER_PAGE})
        elif check['paths'] is not None:
            unexplained = True
    if pr and unexplained:
        facts['files'] = pull_files(client, pr['number'])
    facts['statuses'] = client.get(_api(f'/commits/{sha}/statuses'), {'per_page': PER_PAGE})
    return facts


# --- database (the dedicated ingest login) ---------------------------------------------------------------------------
def tls_options(dsn):
    """verify-full without sslrootcert verifies against the bundled Supabase root (store.tls_options without its imports)."""
    from psycopg.conninfo import conninfo_to_dict
    try:
        params = conninfo_to_dict(dsn)
    except Exception:
        return {}
    if params.get('sslmode') == 'verify-full' and not params.get('sslrootcert'):
        return {'sslrootcert': str(Path(__file__).resolve().parent / 'pack' / 'supabase-root-2021.crt')}
    return {}


UPSERT = ('INSERT INTO rafii_control.engineering_evidence AS e (id,environment,kind,provider,external_id,exact_sha,state,conclusion,'
          'failure_class,attested,required,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
          'ON CONFLICT(environment,provider,kind,external_id) DO UPDATE SET state=excluded.state,conclusion=excluded.conclusion,'
          'failure_class=excluded.failure_class,attested=excluded.attested,observed_at=excluded.observed_at '
          'WHERE e.exact_sha=excluded.exact_sha AND e.required RETURNING e.id')
LATEST = ("SELECT payload->>'evaluationDigest' FROM rafii_control.github_check_snapshots WHERE environment=%s AND exact_sha=%s "
          "AND provenance='ci_attested' ORDER BY observed_at DESC,id DESC LIMIT 1")
SNAPSHOT = ('INSERT INTO rafii_control.github_check_snapshots(id,environment,source_request_id,exact_sha,provenance,observed_at,'
            'payload_digest,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id')
COLUMNS = ('id', 'environment', 'kind', 'provider', 'external_id', 'exact_sha', 'state', 'conclusion', 'failure_class', 'attested', 'required', 'observed_at')


def write(dsn, environment, evaluation, *, connect=None):
    """One transaction as rafii_control_ingest: upsert the required-check rows, then insert the manifest when the
    evaluation differs from the newest manifest of this SHA. Refuses a privileged login or one that inherits the role."""
    if environment not in ENVIRONMENTS:
        raise ValueError('environment')
    rows = evidence_rows(evaluation, environment)
    collector = evaluation.get('collector') or {}
    run_id = _int(collector.get('runId'))
    request_id = uuid.uuid5(NAMESPACE, f"collector/{run_id}/{_int(collector.get('runAttempt')) or 1}") if run_id else uuid.uuid4()
    if connect is None:
        import psycopg

        def connect():
            return psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None, application_name='rafii-engineering-ingest', **tls_options(dsn))
    from psycopg.types.json import Jsonb
    with connect() as con:
        with con.transaction():
            con.execute("SET LOCAL statement_timeout = '10s'")
            login = con.execute('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=session_user').fetchone()
            if login is None or login[0]:
                raise IngestRefused('Use the dedicated CI ingest login, not a privileged role.')
            con.execute('SET LOCAL ROLE ' + INGEST_ROLE)
            role = con.execute('SELECT current_user, rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if role is None or role[0] != INGEST_ROLE or role[1]:
                raise IngestRefused('The CI ingest login could not assume rafii_control_ingest.')
            # Resolve the private relation only after the transaction assumes its allowed role. A legitimate
            # SET-only login deliberately has no schema USAGE; resolving its qualified name beforehand fails.
            # session_user still identifies the original login, so this continues to reject inherited INSERT.
            if con.execute("SELECT has_table_privilege(session_user,'rafii_control.engineering_evidence','INSERT')").fetchone()[0]:
                raise IngestRefused('The CI ingest login must be a NOINHERIT (SET-only) member of rafii_control_ingest.')
            con.execute("SELECT set_config('rafii_control.environment',%s,true)", (environment,))
            for row in rows:
                if con.execute(UPSERT, tuple(row[key] for key in COLUMNS)).fetchone() is None:
                    raise IngestRefused('An evidence row with this id belongs to another SHA or is not required.')
            latest = con.execute(LATEST, (environment, evaluation['exactSha'])).fetchone()
            snapshot = None
            if latest is None or latest[0] != evaluation['evaluationDigest']:
                snapshot = con.execute(SNAPSHOT, (str(uuid.uuid4()), environment, str(request_id), evaluation['exactSha'], PROVENANCE,
                                                  evaluation['observedAt'], hashlib.sha256(canonical(evaluation).encode()).hexdigest(),
                                                  Jsonb(evaluation))).fetchone()[0]
    return dict(rows=len(rows), snapshot=str(snapshot) if snapshot else None)


# --- GitHub Actions entry point --------------------------------------------------------------------------------------
def collector_context(environ):
    """The trusted run that wrote the evidence (recorded in the manifest)."""
    def number(key):
        value = environ.get(key) or ''
        return int(value) if value.isdigit() and 0 < len(value) < 20 else None
    event = environ.get('GITHUB_EVENT_NAME')
    return dict(runId=number('GITHUB_RUN_ID'), runAttempt=number('GITHUB_RUN_ATTEMPT'), event=event if event in EVENTS else None,
                workflowRef=_text(environ.get('GITHUB_WORKFLOW_REF'), 300), sha=_sha(environ.get('GITHUB_SHA')))


def describe(evaluation):
    """Plain lines for the job log; public CI metadata only."""
    route = evaluation.get('pullRequest')
    head = (f"merged PR #{route['number']} (head {route['headSha'][:7]}): {route['reason'].replace('_', ' ')}"
            if route else 'no merged pull request: only exact-SHA runs can count')
    lines = [f"consumer-saas tip {evaluation['exactSha'][:7]}, {head}."]
    for check in evaluation['checks']:
        why = check['requiredReason'].replace('_', ' ') + (f" ({check['matchedPath']})" if check.get('matchedPath') else '')
        state = 'not required' if not check['required'] else check['outcome'] + (', attested' if check['attested'] else ', not attested')
        source = f", {check['source'].replace('_', ' ')} run {check['runId']}" if check.get('runId') else ''
        lines.append(f"- {check['key']}: {why}; {state}{source}")
    lines.append(f"Overall: {evaluation['qualification'].replace('_', ' ')} ({evaluation['requiredCount']} required).")
    return lines


def _summary(environ, title, lines):
    path = environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(f'## {title}\n\n' + ''.join(line + '\n' for line in lines))
    except OSError:
        pass


def main(environ=None, *, client=None, connect=None, clock=None, out=print):
    """Exit code for .github/workflows/founder-engineering-evidence.yml. Secret absent: a 'not configured' notice and a
    read-only dry run, exit 0. Configured: record the tip's evidence, exit 1 on any failure. Never prints the DSN, the
    token or a server message."""
    environ = os.environ if environ is None else environ
    clock = clock or (lambda: datetime.now(timezone.utc))
    dsn = (environ.get('RAFII_ENGINEERING_INGEST_DSN') or '').strip()
    environment = (environ.get('RAFII_ENGINEERING_ENVIRONMENT') or 'production').strip()
    title = f'Founder engineering evidence ({environment})'
    if environment not in ENVIRONMENTS:
        out('::error title=Founder engineering evidence misconfigured::RAFII_ENGINEERING_ENVIRONMENT must be local, staging or production.')
        return 1
    if not dsn:
        out('::notice title=Founder engineering evidence not configured::RAFII_ENGINEERING_INGEST_DSN is not set, so no CI evidence '
            'was recorded. Add the CI ingest login DSN as a repository secret to record it; a read-only dry run follows.')
    elif environ.get('GITHUB_ACTIONS') == 'true' and (environ.get('GITHUB_REF') != f'refs/heads/{PRODUCTION_BRANCH}'
                                                        or environ.get('GITHUB_REPOSITORY') != REPOSITORY
                                                        or environ.get('GITHUB_EVENT_NAME') not in EVENTS):
        out(f'::error title=Founder engineering evidence refused::Evidence is recorded only by {REPOSITORY} runs on {PRODUCTION_BRANCH} '
            '(push, schedule, workflow_run or workflow_dispatch), never from a pull request or another branch.')
        return 1
    if client is None:
        token = (environ.get('GITHUB_TOKEN') or '').strip()
        if not token:
            if not dsn:
                return 0
            out('::error title=Founder engineering evidence misconfigured::GITHUB_TOKEN is not available to the job.')
            return 1
        client = GitHub(token)
    try:
        evaluation = evaluate(gather(client), observed_at=clock().isoformat(), collector=collector_context(environ))
    except Exception as error:
        code = error.code if isinstance(error, CollectorError) else type(error).__name__
        if not dsn:
            out(f'::warning title=Founder engineering evidence dry run unavailable::{code}')
            return 0
        out(f'::error title=Founder engineering evidence cannot read GitHub::{code}')
        return 1
    lines = describe(evaluation)
    for line in lines:
        out(line)
    if not dsn:
        _summary(environ, title + ': not configured (dry run)', lines)
        return 0
    try:
        result = write(dsn, environment, evaluation, connect=connect)
    except IngestRefused as refused:
        out(f'::error title=Founder engineering evidence refused the login::{refused}')
        return 1
    except Exception as error:
        out(f'::error title=Founder engineering evidence cannot write::{type(error).__name__}')
        return 1
    recorded = 'new manifest recorded' if result['snapshot'] else 'manifest unchanged'
    out(f"::notice title={title}::{evaluation['exactSha'][:7]}: {evaluation['qualification'].replace('_', ' ')} "
        f"({result['rows']} required checks; {recorded}).")
    _summary(environ, title, lines + [f'Recorded {result["rows"]} required-check rows; {recorded}.'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
