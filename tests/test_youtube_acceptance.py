"""Synthetic validator contracts only. Fixtures never constitute real creator acceptance."""
import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from postriff_phase2.youtube.acceptance import (AcceptanceError, METHOD_GROUPS, REQUIRED_CASES,
    ROUTES, TEMPLATE_SHA256, digest, document, make_preview, read_document, write_acceptance)
from postriff_phase2.youtube.model import MANAGE, READ

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, 12, 2, tzinfo=timezone.utc)
START, OBSERVED, VERIFIED, ATTESTED = ('2026-10-08T11:59:00Z', '2026-10-08T11:59:30Z', '2026-10-08T12:00:00Z', '2026-10-08T12:01:00Z')
CHANNEL, VIDEO = 'UC' + 'a' * 22, 'abcdefghijk'
BINDINGS = {'workspaceId': '00000000-0000-4000-8000-000000000001', 'connectionId': 'youtube:' + CHANNEL,
    'channelId': CHANNEL, 'clientId': '12345-validclient.apps.googleusercontent.com',
    'projectId': 'rafii-509720', 'callbackUri': 'https://rafii.example/api/oauth/youtube/callback'}


def doc(value):
    return document(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def bundle(selected=('identity',)):
    template = read_document(ROOT / 'docs/youtube/real-e2e-matrix.json')
    matrix = copy.deepcopy(template.value)
    current = {'bindings': copy.deepcopy(BINDINGS), 'provider': 'youtube', 'providerAccountId': CHANNEL,
        'revoked': False, 'scopes': [MANAGE, READ], 'credentialUpdatedAt': VERIFIED,
        'settingsEvidence': {'eligibility': {'live': {'verified': False}}, 'acceptance': {'reply': {'status': 'unverified'}}},
        'authorizations': {'monetary': False, 'memberships': False}, 'actions': {}}
    required = {case for cap in selected for case in REQUIRED_CASES[cap]}
    matrix.update(execution='real', ordinaryCreatorChannelId=CHANNEL, googleProjectId=BINDINGS['projectId'],
        updatedAt=VERIFIED, realPassCount=len(required))
    proofs = {}
    for row in matrix['cases']:
        if row['id'] not in required:
            continue
        row.update(state='PASS', execution='real', realE2ETested=True, blocker='', channelId=CHANNEL,
            resourceIds={'channelId': CHANNEL}, startedAt=START, verifiedAt=VERIFIED, redactedReceipt=row['id'] + '.json')
        if row['id'] == 'video.edit':
            row['resourceIds']['videoId'] = VIDEO
        proof = {'schemaVersion': 1, 'execution': 'real', 'source': 'google_platform', 'caseId': row['id'],
            'bindings': copy.deepcopy(BINDINGS), 'resourceIds': copy.deepcopy(row['resourceIds']),
            'provenance': {'execution': 'real', 'transport': 'official_https'}, 'runId': 'original-' + row['id'],
            'observedAt': OBSERVED, 'observations': []}
        for label in row['officialMethods']:
            for method in METHOD_GROUPS.get(label, (label,)):
                response = {'items': [{'id': CHANNEL}]} if method == 'channels.list' else {}
                if row['id'] == 'connection.actual_scopes':
                    response = {'aud': BINDINGS['clientId'], 'scope': ' '.join(current['scopes'])}
                if row['id'] == 'connection.revoked':
                    response = {'error': 'invalid_grant'}
                if row['id'] == 'connection.client_failure':
                    response = {'error': 'invalid_client'}
                proof['observations'].append({'method': method, 'httpMethod': ROUTES[method][0],
                    'sourceUrl': ROUTES[method][1], 'resourceIds': copy.deepcopy(row['resourceIds']),
                    'status': 400 if row['id'] in ('connection.revoked', 'connection.client_failure') else 200, 'response': response})
        if row['id'] == 'video.edit':
            proof['observations'], proof['scenarioActions'] = [], {}
            values = {'snippet': {'title': 'Reviewed title'}, 'status': {'embeddable': False},
                'recordingDetails': {'recordingDate': '2026-10-01T00:00:00Z'}, 'localizations': {'en': {'title': 'Reviewed title'}}}
            for number, (part, fields) in enumerate(values.items(), 1):
                ident = '00000000-0000-4000-8000-' + str(number).zfill(12)
                body = {'id': VIDEO, part: copy.deepcopy(fields)}
                manifest = {k: BINDINGS[k] for k in ('workspaceId', 'connectionId', 'channelId')}
                manifest.update(action='video.edit', plan={'method': 'videos.update', 'body': body})
                observed = {'id': VIDEO, 'snippet': {'channelId': CHANNEL}}
                observed.setdefault(part, {}).update(fields)
                receipt = {'execution': 'real', 'source': 'YouTube Data API', 'channelId': CHANNEL,
                    'action': 'video.edit', 'acceptedAt': datetime.fromisoformat(OBSERVED.replace('Z', '+00:00')).timestamp(),
                    'result': {'id': VIDEO}, 'verification': {'verified': True, 'method': 'videos.list', 'resourceId': VIDEO, 'observed': observed}}
                current['actions'][ident] = {'status': 'verified', 'manifest': manifest, 'manifestDigest': digest(manifest), 'receipt': receipt, 'updatedAt': OBSERVED}
                proof['scenarioActions'][part] = {'actionId': ident, 'manifestDigest': digest(manifest), 'receiptSha256': digest(receipt)}
                for method in ('videos.update', 'videos.list'):
                    proof['observations'].append({'method': method, 'httpMethod': ROUTES[method][0],
                        'sourceUrl': ROUTES[method][1], 'resourceIds': copy.deepcopy(row['resourceIds']), 'actionId': ident,
                        'status': 200, 'response': {'id': VIDEO} if method == 'videos.update' else {'items': [{'id': VIDEO}]}})
        proofs[row['redactedReceipt']] = doc(proof)
    matrix = doc(matrix)
    reviews = {row['id']: {'receiptSha256': proofs[row['redactedReceipt']].sha256,
        'expectedEvidenceSha256': digest(row['expectedEvidence']), 'originalRunVerified': True,
        'requiredBehaviorVerified': True, 'methodResourceLinkageVerified': True}
        for row in matrix.value['cases'] if row['id'] in required}
    attestation = doc({'schemaVersion': 1, 'operator': 'reviewing-operator', 'trustedOperator': True,
        'reviewedOriginalRealRuns': True, 'bindings': copy.deepcopy(BINDINGS), 'templateSha256': template.sha256,
        'matrixSha256': matrix.sha256, 'attestedAt': ATTESTED, 'caseReviews': reviews})
    return {'template': template, 'matrix': matrix, 'attestation': attestation, 'proofs': proofs,
        'current': current, 'capabilities': selected, 'operator': 'reviewing-operator', 'now': NOW}


def mutate_proof(args, case_id, change):
    reference = case_id + '.json'
    value = copy.deepcopy(args['proofs'][reference].value)
    change(value)
    args['proofs'][reference] = doc(value)
    attestation = copy.deepcopy(args['attestation'].value)
    attestation['caseReviews'][case_id]['receiptSha256'] = args['proofs'][reference].sha256
    args['attestation'] = doc(attestation)


class AcceptancePreviewTests(unittest.TestCase):
    def test_identity_preview_is_deterministic_and_does_not_mutate_settings(self):
        args = bundle()
        original = copy.deepcopy(args['current'])
        first, second = make_preview(**args), make_preview(**args)
        self.assertEqual(first, second)
        self.assertEqual(first['execution'], 'PREVIEW')
        self.assertFalse(first['applied'])
        self.assertEqual(set(first['plan']['acceptance']), {'identity'})
        self.assertEqual(first['plan']['acceptance']['identity']['caseIds'], list(REQUIRED_CASES['identity']))
        self.assertEqual(args['current'], original)

    def test_connected_requires_all_ten_connection_cases(self):
        args = bundle(('connected',))
        self.assertEqual(len(make_preview(**args)['plan']['acceptance']['connected']['caseIds']), 10)
        args['capabilities'] = ('identity', 'connected')
        self.assertEqual(set(make_preview(**args)['plan']['acceptance']), {'identity', 'connected'})

    def test_unsupported_upload_and_sensitive_imports_are_rejected(self):
        for capability in ('upload', 'private_publish', 'public_publish', 'shorts', 'schedule', 'monetary_analytics', 'memberships', 'community_posts', 'article'):
            with self.subTest(capability=capability), self.assertRaises(AcceptanceError):
                args = bundle(); args['capabilities'] = (capability,); make_preview(**args)

    def test_a_single_case_cannot_mark_identity_ready(self):
        args = bundle()
        matrix = copy.deepcopy(args['matrix'].value)
        next(r for r in matrix['cases'] if r['id'] == 'connection.workspace_isolation')['state'] = 'FAIL'
        args['matrix'] = doc(matrix)
        with self.assertRaises(AcceptanceError):
            make_preview(**args)

    def test_template_and_canonical_case_changes_are_rejected(self):
        for mode in ('hash', 'missing', 'duplicate', 'spec'):
            with self.subTest(mode=mode), self.assertRaises(AcceptanceError):
                args = bundle()
                if mode == 'hash':
                    args['template'] = doc({'cases': args['template'].value['cases']})
                else:
                    matrix = copy.deepcopy(args['matrix'].value)
                    if mode == 'missing': matrix['cases'].pop()
                    if mode == 'duplicate': matrix['cases'][-1] = matrix['cases'][0]
                    if mode == 'spec': matrix['cases'][0]['expectedEvidence'] = 'One successful request'
                    args['matrix'] = doc(matrix)
                make_preview(**args)

    def test_fixture_injected_missing_and_secret_provenance_are_rejected(self):
        mutations = [lambda p: p.update(execution='transport-injected'), lambda p: p.update(fixture=True),
            lambda p: p.pop('provenance'), lambda p: p['provenance'].update(transport='transport-injected'),
            lambda p: p.update(source='YouTube Data API'), lambda p: p.update(access_token='secret'),
            lambda p: p.update(runId='fixture-run')]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(AcceptanceError):
                args = bundle(); mutate_proof(args, 'connection.identity', change); make_preview(**args)

    def test_foreign_response_route_method_and_resource_are_rejected(self):
        mutations = [lambda p: p['observations'][0].update(sourceUrl='https://example.com/youtube'),
            lambda p: p['observations'][0].update(method='videos.insert'),
            lambda p: p['observations'][0]['resourceIds'].update(channelId='UC' + 'b' * 22),
            lambda p: p['observations'][0]['response']['items'][0].update(id='UC' + 'b' * 22),
            lambda p: p['bindings'].update(workspaceId='00000000-0000-4000-8000-000000000002')]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(AcceptanceError):
                args = bundle(); mutate_proof(args, 'connection.identity', change); make_preview(**args)

    def test_foreign_client_or_actual_scopes_are_rejected(self):
        for field, value in [('aud', 'other-client'), ('scope', READ)]:
            with self.subTest(field=field), self.assertRaises(AcceptanceError):
                args = bundle()
                mutate_proof(args, 'connection.actual_scopes', lambda p: p['observations'][0]['response'].update({field: value}))
                make_preview(**args)

    def test_revoked_or_foreign_active_credential_is_rejected(self):
        for field, value in [('revoked', True), ('providerAccountId', 'UC' + 'b' * 22), ('provider', 'instagram')]:
            with self.subTest(field=field), self.assertRaises(AcceptanceError):
                args = bundle(); args['current'][field] = value; make_preview(**args)

    def test_stale_future_and_unzoned_proof_is_rejected(self):
        for value in ('2026-08-01T12:00:00Z', '2026-10-09T12:00:00Z', '2026-10-08T12:00:00'):
            with self.subTest(value=value), self.assertRaises(AcceptanceError):
                args = bundle(); mutate_proof(args, 'connection.identity', lambda p: p.update(observedAt=value)); make_preview(**args)

    def test_hash_and_complete_behavior_attestation_are_required(self):
        for field, value in [('receiptSha256', '0' * 64), ('requiredBehaviorVerified', False), ('originalRunVerified', False)]:
            with self.subTest(field=field), self.assertRaises(AcceptanceError):
                args = bundle(); attestation = copy.deepcopy(args['attestation'].value)
                attestation['caseReviews']['connection.identity'][field] = value
                args['attestation'] = doc(attestation); make_preview(**args)

    def test_metadata_needs_four_verified_real_bound_actions(self):
        args = bundle(('metadata_edit',))
        self.assertIn('metadata_edit', make_preview(**args)['plan']['acceptance'])
        for mutation in ('status', 'injected', 'false_readback', 'manifest', 'resource', 'hash', 'stale'):
            with self.subTest(mutation=mutation), self.assertRaises(AcceptanceError):
                args = bundle(('metadata_edit',)); action = next(iter(args['current']['actions'].values()))
                if mutation == 'status': action['status'] = 'accepted'
                if mutation == 'injected': action['receipt']['execution'] = 'transport-injected'
                if mutation == 'false_readback': action['receipt']['verification']['verified'] = False
                if mutation == 'manifest': action['manifest']['channelId'] = 'UC' + 'b' * 22
                if mutation == 'resource': action['receipt']['verification']['resourceId'] = 'ZZZZZZZZZZZ'
                if mutation == 'hash': action['manifestDigest'] = '0' * 64
                if mutation == 'stale': action['updatedAt'] = '2026-08-01T00:00:00Z'
                make_preview(**args)

    def test_single_metadata_action_and_missing_readback_links_are_rejected(self):
        for mode in ('one_action', 'missing_readback'):
            with self.subTest(mode=mode), self.assertRaises(AcceptanceError):
                args = bundle(('metadata_edit',))
                def change(proof):
                    if mode == 'one_action':
                        first = next(iter(proof['scenarioActions'].values()))
                        proof['scenarioActions'] = {part: first for part in proof['scenarioActions']}
                    else:
                        proof['observations'].pop()
                mutate_proof(args, 'video.edit', change); make_preview(**args)

    def test_apply_requires_exact_snapshot_digest_and_merges_only_acceptance(self):
        args = bundle(); preview = make_preview(**args)
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, query, params): self.calls.append((query, params))
        cursor = Cursor()
        with self.assertRaises(AcceptanceError): write_acceptance(cursor, preview, '0' * 64)
        self.assertEqual(cursor.calls, [])
        write_acceptance(cursor, preview, preview['digest'])
        query, params = cursor.calls[0]
        self.assertIn("jsonb_set(pr_youtube_settings.evidence,'{acceptance}'", query)
        self.assertNotIn('monetary_authorized', query)
        self.assertNotIn('memberships_authorized', query)
        self.assertNotIn('eligibility', query)
        self.assertEqual(set(json.loads(params[2])), {'identity'})
        args['current']['authorizations']['monetary'] = True
        with self.assertRaises(AcceptanceError): write_acceptance(cursor, make_preview(**args), preview['digest'])

    def test_json_duplicates_nonfinite_and_path_escape_are_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e400}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(AcceptanceError): document(raw)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'allowed').mkdir(); (root / 'outside.json').write_text('{}')
            with self.assertRaises(AcceptanceError): read_document(root / 'outside.json', root / 'allowed')

    def test_cli_apply_without_digest_stops_before_database_access(self):
        spec = importlib.util.spec_from_file_location('youtube_acceptance_cli', ROOT / 'scripts/youtube_acceptance.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        argv = []
        for field in ('matrix', 'attestation', 'evidence-root', 'operator', 'workspace-id', 'connection-id', 'channel-id', 'client-id', 'project-id'):
            argv += ['--' + field, 'unused']
        argv += ['--capability', 'identity', '--apply']
        with patch.dict('os.environ', {}, clear=True), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(argv)
        self.assertEqual(raised.exception.code, 2)
