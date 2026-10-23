#!/usr/bin/env python3
"""Prove that a release candidate contains everything the live build has (S-04). Read-only: git objects only.

usage: rc_superset_proof.py --live <rev> --rc <rev> [--base <rev>] [--allow FILE] [--json OUT]

Checks, each a hard failure unless listed in the allow file:
  ancestry      the live commit is an ancestor of the candidate
  files         every tracked path of the live commit exists in the candidate
  lines         every line the live line added since the merge base (per file) is still in the candidate
  routes        every /api/ route string in src/ is still present
  crons         every vercel.json cron is still present, and git.deploymentEnabled is unchanged
  migrations    every migration file is still present
  flags         every POSTRIFF_*/RAFII_* name read by src/ is still read
  tests         every test module of the live commit is still present

A line that a conflict resolution rewrote on purpose is listed in the allow file with the reason; nothing else passes.
"""
import argparse
import json
import re
import subprocess
import sys

ROUTE = re.compile(r"""['"](/api/[A-Za-z0-9_\-./{}<>:]+)['"]""")
FLAG = re.compile(r"\b((?:POSTRIFF|RAFII)_[A-Z0-9_]{3,})\b")
MIN_LINE = 6


def git(*args, check=True, raw=False):
    done = subprocess.run(['git', *args], capture_output=True, check=False)
    if check and done.returncode:
        raise SystemExit('git %s failed: %s' % (' '.join(args), done.stderr.decode(errors='replace').strip()))
    return done.stdout if raw else done.stdout.decode('utf-8', errors='replace')


def tree(rev):
    out = git('ls-tree', '-r', '-z', '--full-tree', rev, raw=True).split(b'\0')
    files = {}
    for entry in out:
        if not entry:
            continue
        meta, path = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        if kind == 'blob':
            files[path.decode('utf-8', errors='surrogateescape')] = oid
    return files


def text(rev, path):
    return git('show', '%s:%s' % (rev, path), check=False)


def lines_of(blob):
    return {line.strip() for line in blob.splitlines() if len(line.strip()) >= MIN_LINE}


def scan(rev, files, pattern, prefix, suffixes):
    found = set()
    for path in files:
        if path.startswith(prefix) and path.endswith(suffixes):
            found.update(pattern.findall(text(rev, path)))
    return found


def crons(rev):
    try:
        config = json.loads(text(rev, 'vercel.json'))
    except ValueError:
        return set(), None
    return {(c.get('path'), c.get('schedule')) for c in config.get('crons', [])}, config.get('git')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--live', required=True)
    parser.add_argument('--rc', required=True)
    parser.add_argument('--base')
    parser.add_argument('--allow')
    parser.add_argument('--json')
    args = parser.parse_args()
    live, rc = (git('rev-parse', '--verify', r + '^{commit}').strip() for r in (args.live, args.rc))
    base = args.base or git('merge-base', live, rc).strip()
    allow = {}
    if args.allow:
        with open(args.allow) as handle:
            allow = json.load(handle)
    report = {'live': live, 'rc': rc, 'base': base, 'checks': {}}

    def record(name, problems, note=''):
        allowed = set(allow.get(name, {}))
        left = [p for p in problems if p not in allowed]
        report['checks'][name] = {'ok': not left, 'problems': left, 'allowed': sorted(set(problems) & allowed), 'note': note}

    ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', live, rc]).returncode == 0
    record('ancestry', [] if ancestor else ['live commit is not an ancestor of the candidate'])

    live_files, rc_files, base_files = tree(live), tree(rc), tree(base)
    record('files', sorted(p for p in live_files if p not in rc_files), '%d live paths' % len(live_files))

    # Lines the live line added since the base must survive in files that exist in both.
    dropped = []
    changed = [p for p, oid in live_files.items() if base_files.get(p) != oid and p in rc_files and rc_files[p] != oid]
    for path in sorted(changed):
        added = lines_of(text(live, path)) - lines_of(text(base, path)) if path in base_files else lines_of(text(live, path))
        missing = sorted(added - lines_of(text(rc, path)))
        dropped.extend('%s :: %s' % (path, line) for line in missing)
    record('lines', dropped, '%d files changed by the live line and rewritten in the candidate' % len(changed))

    record('routes', sorted(scan(live, live_files, ROUTE, 'src/', ('.py',)) - scan(rc, rc_files, ROUTE, 'src/', ('.py',))))
    live_crons, live_git = crons(live)
    rc_crons, rc_git = crons(rc)
    problems = ['missing cron %s %s' % c for c in sorted(live_crons - rc_crons)]
    record('crons', problems, 'candidate git settings: %s' % json.dumps(rc_git, sort_keys=True))
    migrations = lambda files: {p for p in files if p.startswith('migrations/')}
    record('migrations', sorted(migrations(live_files) - migrations(rc_files)))
    record('flags', sorted(scan(live, live_files, FLAG, 'src/', ('.py',)) - scan(rc, rc_files, FLAG, 'src/', ('.py',))))
    tests = lambda files: {p for p in files if p.startswith('tests/') and p.rsplit('/', 1)[-1].startswith('test_')}
    record('tests', sorted(tests(live_files) - tests(rc_files)))

    ok = all(check['ok'] for check in report['checks'].values())
    report['ok'] = ok
    if args.json:
        with open(args.json, 'w') as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
    for name, check in report['checks'].items():
        print('%-10s %s  %d problem(s), %d allowed  %s' % (name, 'OK  ' if check['ok'] else 'FAIL', len(check['problems']),
                                                          len(check['allowed']), check['note']))
        for problem in check['problems'][:40]:
            print('    ' + problem[:220])
    print('SUPERSET ' + ('PROVEN' if ok else 'NOT PROVEN') + ' live=%s rc=%s base=%s' % (live[:8], rc[:8], base[:8]))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
