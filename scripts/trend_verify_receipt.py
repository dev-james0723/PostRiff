#!/usr/bin/env python3
"""File-only receipt verifier and shared operator CLI boundary; see trend_offline_examples.md."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
MAX_BYTES = 32_000_000


class OperatorError(ValueError):
    pass


def refuse_network(event, args):
    if event.startswith('socket.') and event not in ('socket.__new__',):
        raise OperatorError('network_prohibited')
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        raise OperatorError('external_process_prohibited')


# Applies to CLI processes, including imports: no provider, model, DNS or DB access.
if __name__ == '__main__':
    sys.addaudithook(refuse_network)

from postriff_phase2.growth.trends import contracts, metrics, methods, receipts
from postriff_phase2.growth.trends.pipeline import implementation_methods, decode_manifest


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OperatorError('invalid_arguments')


def parser(description):
    p = Parser(description=description)
    p.add_argument('--scope', required=True)
    p.add_argument('--at', required=True, help='UTC evaluation instant; must equal current-rights.checked_at')
    p.add_argument('--current-rights', required=True, type=Path)
    p.add_argument('--execution', required=True, choices=('fixture', 'local'))
    p.add_argument('--output', required=True, type=Path, help='New JSON file; existing files are never overwritten')
    return p


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise OperatorError('duplicate_json_key')
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise OperatorError('input_missing_or_too_large')
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(OperatorError('nonfinite_json')))
    except (UnicodeError, json.JSONDecodeError):
        raise OperatorError('invalid_json') from None


def bounded_list(value, name, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise OperatorError(name + '_bound')
    return value


def rights_snapshot(args):
    contracts.scope(args.scope)
    contracts.instant(args.at)
    data = read_json(args.current_rights)
    if (data.get('schema') != 'rafii.trend-current-rights.v1' or data.get('scope_key') != args.scope
            or data.get('checked_at') != args.at):
        raise OperatorError('current_rights_scope_or_time_mismatch')
    for name, maximum in (('source_policies', 100), ('deleted_observation_ids', 10000),
                          ('revoked_policy_versions', 100), ('withdrawn_methods', 100)):
        bounded_list(data.get(name), name, maximum)
    if any(p.get('scope_key') != args.scope for p in data['source_policies']):
        raise OperatorError('current_policy_scope_mismatch')
    return data


def current_registry(trust):
    withdrawn = {(m['name'], m['version']) for m in trust['withdrawn_methods']}
    registry = {}
    for artifact in implementation_methods():
        if (artifact['name'], artifact['version']) not in withdrawn:
            registry = methods.register_method(registry, artifact)
    return registry


def source_status(sources, trust, at, *, manifest_digest=''):
    status = receipts.current_receipt_status({'source_revisions': sources, 'manifest_digest': manifest_digest},
        at=at, current_policies=trust['source_policies'], deleted_observation_ids=trust['deleted_observation_ids'],
        revoked_policy_versions=trust['revoked_policy_versions'])
    if status['state'] == 'verified':
        for source in sources:
            if any(not metrics.source_policy_allowed(source, trust['source_policies'], at, permission)
                   for permission in ('store_raw', 'retain_derivatives')):
                return {**status, 'state': 'policy_revoked', 'reason': 'raw_or_derivative_retention_not_permitted'}
    return status


def packs(document):
    if isinstance(document, dict) and 'receipt' in document and 'manifest' in document:
        return [document]
    if document.get('schema') == 'rafii.trend-replay-report.v1':
        return [d['bundle'] for d in bounded_list(document.get('decisions'), 'decisions', 48) if d.get('bundle')]
    if document.get('schema') == 'rafii.trend-receipt-bundles.v1':
        return bounded_list(document.get('bundles'), 'bundles', 200)
    raise OperatorError('receipt_bundle_schema_required')


def canonical_pack(pack):
    raw = pack['receipt']
    raw = raw.get('payload', raw)
    if 'pure_receipt' in raw:
        if contracts.digest(raw['pure_receipt']) != raw.get('pure_receipt_digest'):
            raise OperatorError('durable_pure_receipt_digest_mismatch')
        raw = raw['pure_receipt']
    manifest = pack['manifest']
    if manifest.get('recipe', {}).get('codec') == 'json-fragments-v1':
        manifest = decode_manifest(manifest)
    if raw.get('schema') != 'rafii.trend-trust-receipt.v2' or manifest.get('schema') != 'rafii.trend-input-manifest.v2':
        raise OperatorError('v2_receipt_and_complete_manifest_required')
    bounded_list(manifest.get('source_revisions'), 'source_revisions', 2000)
    bounded_list(manifest.get('membership_revisions'), 'membership_revisions', 10000)
    bounded_list(manifest['recipe'].get('window_specs'), 'window_specs', 200)
    bounded_list(manifest['recipe'].get('baseline_window_specs'), 'baseline_window_specs', 200)
    return {'receipt': raw, 'manifest': manifest}


def pairing_digest(pack):
    """Compare the actual sealed inputs, independently of caller-written labels."""
    manifest = pack['manifest']
    return contracts.digest({k: manifest[k] for k in
        ('source_revisions', 'membership_revisions', 'policy_versions', 'recipe')})


def verify_pack(pack, args, trust):
    pack = canonical_pack(pack)
    receipt, manifest = pack['receipt'], pack['manifest']
    if receipt['scope']['scope_key'] != args.scope or manifest['scope_key'] != args.scope:
        raise OperatorError('receipt_scope_mismatch')
    if any(o['scope_key'] != args.scope for o in manifest['source_revisions']):
        raise OperatorError('source_scope_mismatch')
    if contracts.instant(receipt['computed_at']) > contracts.instant(args.at):
        return {'state': 'pending', 'reason': 'receipt_not_available_at_evaluation'}, pack
    status = source_status(manifest['source_revisions'], trust, args.at, manifest_digest=manifest['manifest_digest'])
    if status['state'] != 'verified':
        return {'state': status['state'], 'reason': status.get('reason', status['state'])}, pack
    verification = receipts.verify_receipt(receipt, manifest, current_registry(trust), at=args.at,
        current_policies=trust['source_policies'], deleted_observation_ids=trust['deleted_observation_ids'],
        revoked_policy_versions=trust['revoked_policy_versions'])
    if verification['state'] != 'verified':
        return {k: v for k, v in verification.items() if k in ('state', 'reason', 'method_name', 'method_version')}, pack
    return {'state': 'verified', 'verification': verification,
            'projection': receipts.project_receipt(receipt, verification, at=args.at, current_status=status)}, pack


def envelope(args, schema):
    return {'schema': schema, 'scope_key': args.scope, 'checked_at': args.at,
            'execution_state': 'synthetic_fixture' if args.execution == 'fixture' else 'local_offline',
            'verification_basis': 'explicit_operator_file_snapshot', 'production_verified': False,
            'publication_state': 'shadow_only', 'provider_calls': 0, 'model_calls': 0}


def finish(args, report, *, inputs=()):
    output = args.output.resolve()
    if output in {Path(p).resolve() for p in [args.current_rights, *inputs]}:
        raise OperatorError('output_must_not_replace_input')
    body = json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
    if len(body.encode()) > 64_000_000:
        raise OperatorError('output_byte_bound')
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(body)
    print(json.dumps({'schema': report['schema'], 'status': report['status'], 'output': str(output),
                      'production_verified': False}, sort_keys=True))
    return 0 if report['status'] == 'ok' else 1


def run(main):
    try:
        return main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError, RecursionError) as exc:
        reason = str(exc) if isinstance(exc, OperatorError) else 'invalid_or_unavailable_input'
        if isinstance(exc, FileExistsError):
            reason = 'output_already_exists'
        print(json.dumps({'schema': 'rafii.trend-operator-error.v1', 'status': 'error', 'reason': reason,
                          'production_verified': False}, sort_keys=True))
        return 2


def main():
    p = parser('Recompute complete v2 receipt bundles locally; never production verification.')
    p.add_argument('--bundle', required=True, type=Path, help='Pure bundle, replay report, or explicit bundle collection')
    args = p.parse_args()
    trust = rights_snapshot(args)
    results = []
    selected = packs(read_json(args.bundle))
    if not selected:
        raise OperatorError('no_receipt_bundles')
    for pack in selected:
        verified, _ = verify_pack(pack, args, trust)
        results.append(verified)
    report = {**envelope(args, 'rafii.trend-verification-report.v1'),
              'status': 'ok' if all(v['state'] == 'verified' for v in results) else 'blocked',
              'verification_target': 'pure_receipt_and_complete_manifest', 'durable_database_checked': False,
              'wire_projection_verified': False, 'results': results}
    return finish(args, report, inputs=[args.bundle])


if __name__ == '__main__':
    sys.exit(run(main))
