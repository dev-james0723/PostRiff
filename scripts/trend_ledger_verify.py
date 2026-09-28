"""Offline integrity check for the managed Trends requirement/evidence ledger.

No re-extraction, state promotion, provider access or model calls. A passing
result proves ledger integrity only; it is not feature/release qualification.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/design/social-trend-intelligence'
PROTECTED = ('requirement_id', 'source_lines', 'source_section', 'exact_requirement', 'source_text_sha256')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    ledger = json.loads((DOC / 'requirements.json').read_text())
    baseline = json.loads(subprocess.check_output(['git', '-C', str(ROOT), 'show',
        '595eab656841fcd5ddd0c61c337947323dc83418:docs/design/social-trend-intelligence/requirements.json']))
    rows = ledger['requirements']
    errors = []
    if [[r[k] for k in PROTECTED] for r in rows] != [[r[k] for k in PROTECTED] for r in baseline['requirements']]:
        errors.append('Stable IDs/order/exact source fields differ from visual candidate baseline')
    spec = DOC / 'RAFII_SOCIAL_TREND_INTELLIGENCE_MASTER_SPEC_2026-09-27.md'
    if digest(spec) != ledger['source_sha256']:
        errors.append('Canonical specification fingerprint changed')
    if len(rows) != 1771 or len({r['requirement_id'] for r in rows}) != 1771:
        errors.append('Expected exactly1771 unique stable requirement IDs')
    for row in rows:
        ident = row['requirement_id']
        if row['state'] not in ledger['allowed_states']:
            errors.append(ident + ': unknown state')
        if hashlib.sha256(row['exact_requirement'].encode()).hexdigest() != row['source_text_sha256']:
            errors.append(ident + ': exact-text hash mismatch')
        if row['state'] == 'NOT_APPLICABLE' and (row['mandatory'] or not row.get('not_applicable_rationale')):
            errors.append(ident + ': invalid not-applicable classification')
        if row['state'] == 'BLOCKED_EXTERNAL' and not row.get('external_blocker'):
            errors.append(ident + ': missing concrete external blocker')
        if row['state'] == 'VERIFIED':
            evidence = row.get('verification_evidence', [])
            if not evidence:
                errors.append(ident + ': VERIFIED without actual evidence')
            for item in evidence:
                path = ROOT / item['path']
                if not path.is_file() or digest(path) != item['sha256']:
                    errors.append(ident + ': evidence missing or changed: ' + item['path'])
                test = next((t for t in row['tests'] if t['test_id'] == item.get('test_id')), None)
                if not test or test.get('observed_outcome') != 'PASS' or digest(ROOT / test['file']) != test['sha256']:
                    errors.append(ident + ': assertion does not bind a current passing test')
    counts = dict(Counter(r['state'] for r in rows))
    for filename in ('ledger-coverage.json', 'ledger-validation.json', 'ledger-closeout-validation.json'):
        report = json.loads((DOC / filename).read_text())
        reported = report['counts'].get('states', report['counts'])
        if reported != counts:
            errors.append(filename + ': stale requirement counts')
    if ledger['closeout']['counts'] != counts:
        errors.append('Current closeout counts differ')
    return {'status': 'FAIL' if errors else 'PASS', 'scope': 'ledger_integrity_not_release_qualification',
            'records': len(rows), 'counts': counts, 'requirements_sha256': digest(DOC / 'requirements.json'),
            'errors': errors, 'provider_calls': 0, 'model_calls': 0, 'production_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Optional local result JSON')
    args = parser.parse_args()
    result = verify()
    payload = json.dumps(result, indent=2) + '\n'
    if args.out:
        args.out.write_text(payload)
    print(payload, end='')
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
