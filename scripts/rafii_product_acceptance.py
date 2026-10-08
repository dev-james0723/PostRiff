#!/usr/bin/env python3
"""Validate the complete product receipt, without making provider/model calls or granting access."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_phase2.growth.observation_windows import MAX_LATENESS_SECONDS

IDS = {f'{prefix}{n:02}' for prefix, count in [('G', 58), ('T', 66), ('S', 15)] for n in range(1, count + 1)}
STATES = {'NOT_RUN', 'PENDING', 'PASS', 'FAIL', 'BLOCKED', 'UNAVAILABLE'}


def earliest_time(row_id, requirements, anchor_at):
    row = next(row for row in requirements['functions'] if row['id'] == row_id)
    rule = row['earliestAcceptance']
    if rule['kind'] != 'verified-publication-plus-offset' or type(anchor_at) not in (int, float) or not math.isfinite(anchor_at):
        return None
    return anchor_at + rule['seconds']


def validate(requirements, matrix):
    errors = []
    for name, rows in [('requirements', requirements.get('functions', [])), ('matrix', matrix.get('functions', []))]:
        ids = [row.get('id') for row in rows]
        if len(ids) != len(IDS) or set(ids) != IDS or len(set(ids)) != len(ids):
            errors.append(f'{name}: all 139 unique G/T/S IDs are required')
    definitions = requirements.get('dependencies', {})
    by_id = {row.get('id'): row for row in requirements.get('functions', [])}
    for row in by_id.values():
        if not row.get('dependencies') or any(dep not in definitions for dep in row['dependencies']):
            errors.append(f"{row.get('id')}: undefined or missing dependencies")
        for axis in ('productionDependencies', 'dataDependencies', 'uiStateDependencies'):
            if axis in row and (not isinstance(row[axis],list) or any(dep not in definitions for dep in row[axis])):
                errors.append(f"{row.get('id')}.{axis}: undefined dependencies")
    for row in matrix.get('functions', []):
        rid = row.get('id')
        for axis in ('code', 'production', 'data'):
            proof = row.get(axis, {})
            if proof.get('status') not in STATES:
                errors.append(f'{rid}.{axis}: explicit evidence state required')
            if proof.get('status') != 'PASS':
                continue
            if not proof.get('evidence'):
                errors.append(f'{rid}.{axis}: PASS needs evidence')
            q = proof.get('qualification', {})
            # Anonymous authorization checks have no paid principal and must prove the actual denial.
            if axis == 'production' and rid in ('S14', 'S15'):
                if q.get('execution') != 'real' or q.get('environment') != 'production' or q.get('httpStatus') not in (401, 403):
                    errors.append(f'{rid}: real anonymous production denial required')
            elif axis == 'production':
                if (q.get('execution') != 'real' or q.get('environment') != 'production'
                        or q.get('ordinaryPaid') is not True or q.get('founder') is not False
                        or q.get('providerAppRole') is not False
                        or not all(q.get(key) for key in ('liveBillingEvidence', 'principalId', 'workspaceId', 'sourceSha', 'flowEvidence'))):
                    errors.append(f'{rid}: ordinary live paid production flow proof required')
            elif axis == 'data':
                if q.get('execution') != 'real' or q.get('reconstructed') is not False:
                    errors.append(f'{rid}: real non-reconstructed data qualification required')
                rule = by_id.get(rid, {}).get('earliestAcceptance', {})
                if rule.get('kind') == 'verified-publication-plus-offset':
                    anchor, observed = q.get('anchorAt'), q.get('observedAt')
                    valid = (type(anchor) in (int, float) and type(observed) in (int, float)
                             and math.isfinite(anchor) and math.isfinite(observed)
                             and anchor + rule['seconds'] <= observed <= anchor + rule['seconds'] + MAX_LATENESS_SECONDS
                             and q.get('horizon') == rule['horizon']
                             and q.get('provenance') == 'official'
                             and all(q.get(key) for key in ('providerReadId', 'providerPostId', 'connectionId')))
                    if not valid:
                        errors.append(f'{rid}: native observation after the real horizon anchor required')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrix', type=Path)
    parser.add_argument('--requirements', type=Path, default=Path(__file__).resolve().parents[1] / 'docs/design/studio-customer-growth/requirements.json')
    args = parser.parse_args()
    errors = validate(json.loads(args.requirements.read_text()), json.loads(args.matrix.read_text()))
    print(json.dumps({'execution': 'receipt validation only; no provider calls', 'valid': not errors, 'rows': 139, 'errors': errors}, indent=2))
    return int(bool(errors))


if __name__ == '__main__': raise SystemExit(main())
