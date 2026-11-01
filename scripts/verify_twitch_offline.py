#!/usr/bin/env python3
"""Run the actual Twitch suites and write an auditable, non-inflated receipt.

The PostgreSQL suite accepts only localhost:55439/rafii_twitch_test and is skipped
unless its explicit test DSN is supplied. This script does not provision a DB,
register an app, deploy, or make a live Twitch request.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
MODULES = ('test_twitch_native', 'test_twitch_oauth', 'test_twitch_agent',
           'test_twitch_eventsub', 'test_twitch_http', 'test_twitch_postgres',
           'test_twitch_runtime', 'test_twitch_refresh_projection')


class ReceiptResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.current = None

    def startTest(self, test):
        self.current = {'id': test.id(), 'status': 'pass'}
        self.cases.append(self.current)
        super().startTest(test)

    def addFailure(self, test, err):
        self.current['status'] = 'fail'
        super().addFailure(test, err)

    def addError(self, test, err):
        if self.current is not None:
            self.current['status'] = 'error'
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.current.update(status='skip', reason=reason)
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.current['status'] = 'fail'
        super().addSubTest(test, subtest, err)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'docs/twitch-20261018')
    parser.add_argument('--require-postgres', action='store_true')
    args = parser.parse_args()
    if args.require_postgres and not os.environ.get('RAFII_TWITCH_TEST_DSN'):
        parser.error('Supply the explicitly isolated RAFII_TWITCH_TEST_DSN; production targets are refused by the suite.')
    loader = unittest.TestLoader()
    seen = set()
    selected = []
    for module in MODULES:
        for test in flatten(loader.loadTestsFromName(module)):
            if test.id() not in seen:
                selected.append(test)
                seen.add(test.id())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    with (args.output_dir / 'acceptance.log').open('w') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ReceiptResult).run(unittest.TestSuite(selected))
    groups = {}
    for case in result.cases:
        counts = groups.setdefault(case['id'].split('.')[0], Counter())
        counts['run'] += 1
        counts[case['status']] += 1
    source_paths = sorted({*ROOT.glob('src/postriff_phase2/twitch_*.py'),
                           *ROOT.glob('tests/test_twitch_*.py'),
                           ROOT / 'migrations/postriff/134_twitch_native.sql'})
    receipt = {'kind': 'offline-candidate-acceptance', 'startedAt': started,
        'finishedAt': datetime.now(timezone.utc).isoformat(), 'durationSeconds': round(time.monotonic()-clock, 3),
        'python': platform.python_version(), 'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
        'sourceBaseCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'workingTreeCandidate': True, 'liveTwitchCalls': False, 'productionDatabaseUsed': False,
        'postgresTarget': '127.0.0.1:55439/rafii_twitch_test' if os.environ.get('RAFII_TWITCH_TEST_DSN') else None,
        'testsRun': result.testsRun, 'uniqueTestIds': len({case['id'] for case in result.cases}),
        'totals': dict(Counter(case['status'] for case in result.cases)), 'groups': groups,
        'successful': result.wasSuccessful(), 'caseResults': result.cases,
        'sourceSha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}}
    (args.output_dir / 'acceptance-results.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    print(json.dumps({key: receipt[key] for key in ('testsRun', 'uniqueTestIds', 'totals', 'groups', 'successful')}, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
