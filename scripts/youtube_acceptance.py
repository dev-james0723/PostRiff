#!/usr/bin/env python3
"""Preview a trusted evidence import. Only --apply plus a reviewed digest writes DB settings.

Uses existing server-admin POSTRIFF_DATABASE_URL without loading local env files.
Never exchanges Google tokens, sends uploads, or writes approval/eligibility evidence.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.youtube.acceptance import (AcceptanceError, REQUIRED_CASES, make_preview,
    read_document, require, write_acceptance)


def current_context(cursor, bindings, action_ids, lock=False):
    cursor.execute("SELECT rolsuper OR rolbypassrls OR current_user='service_role' FROM pg_roles WHERE rolname=current_user")
    require(cursor.fetchone() == (True,), 'Use the existing trusted server-admin database role.')
    suffix = ' FOR UPDATE' if lock else ''
    cursor.execute('SELECT provider,provider_account_id,scopes,revoked_at IS NOT NULL,updated_at FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s' + suffix,
        (bindings['workspaceId'], bindings['connectionId']))
    credential = cursor.fetchone()
    require(credential is not None, 'Exact connected credential was not found.')
    cursor.execute('SELECT evidence,monetary_authorized,memberships_authorized FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s' + suffix,
        (bindings['workspaceId'], bindings['connectionId']))
    settings = cursor.fetchone() or ({}, False, False)
    actions = {}
    if action_ids:
        cursor.execute('SELECT id::text,status,manifest,manifest_digest,receipt,updated_at FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=ANY(%s)' + suffix,
            (bindings['workspaceId'], bindings['connectionId'], sorted(action_ids)))
        actions = {row[0]: {'status': row[1], 'manifest': row[2], 'manifestDigest': row[3],
            'receipt': row[4], 'updatedAt': row[5].isoformat()} for row in cursor.fetchall()}
    return {'bindings': bindings, 'provider': credential[0], 'providerAccountId': credential[1],
        'scopes': sorted(credential[2]), 'revoked': credential[3], 'credentialUpdatedAt': credential[4].isoformat(),
        'settingsEvidence': settings[0], 'authorizations': {'monetary': settings[1], 'memberships': settings[2]}, 'actions': actions}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('matrix', 'attestation', 'evidence-root', 'operator', 'workspace-id', 'connection-id', 'channel-id', 'client-id', 'project-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--capability', action='append', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-preview-digest')
    args = parser.parse_args(argv)
    if args.apply and not args.expected_preview_digest:
        parser.error('--apply requires --expected-preview-digest from a reviewed PREVIEW.')
    try:
        require(all(c in REQUIRED_CASES for c in args.capability), 'Unsupported import capability; no acceptance was written.')
        project = json.loads(os.environ.get('POSTRIFF_YOUTUBE_PROJECT_EVIDENCE', '{}'))
        from postriff_phase2.youtube.provider import YouTubeProvider
        client, _, credentials_valid, source_diagnostic = YouTubeProvider.standard_credential_pair(os.environ)
        require(credentials_valid and isinstance(project, dict) and project.get('projectId') == args.project_id and
            project.get('clientId') == client == args.client_id, 'Current server client/project binding is missing or different.')
        base = os.environ.get('POSTRIFF_PUBLIC_BASE_URL', '').rstrip('/')
        origin = urlparse(base)
        require(origin.scheme == 'https' and origin.hostname and not any((origin.username, origin.password, origin.path, origin.query, origin.fragment)), 'A fixed current HTTPS server origin is required.')
        callback_base = 'https://rafii.io' if source_diagnostic['credentialSource'] == 'dedicated_production' else base
        bindings = {'workspaceId': args.workspace_id, 'connectionId': args.connection_id,
            'channelId': args.channel_id, 'clientId': client, 'projectId': args.project_id,
            'callbackUri': callback_base + '/api/oauth/youtube/callback'}
        template = read_document(ROOT / 'docs/youtube/real-e2e-matrix.json')
        matrix, attestation = read_document(args.matrix), read_document(args.attestation)
        required = {case for cap in args.capability for case in REQUIRED_CASES[cap]}
        proofs, action_ids = {}, set()
        for row in matrix.value.get('cases', []):
            if isinstance(row, dict) and row.get('id') in required:
                reference = row.get('redactedReceipt')
                require(isinstance(reference, str) and not Path(reference).is_absolute() and '..' not in Path(reference).parts, 'A local redacted receipt is required for each case.')
                proof = proofs[reference] = read_document(Path(args.evidence_root) / reference, args.evidence_root)
                scenarios = proof.value.get('scenarioActions', {})
                require(isinstance(scenarios, dict) and len(scenarios) <= 4, 'Malformed action evidence.')
                for link in scenarios.values():
                    require(isinstance(link, dict) and isinstance(link.get('actionId'), str), 'Malformed action ID.')
                    action_ids.add(link['actionId'])
        dsn = os.environ.get('POSTRIFF_DATABASE_URL')
        require(bool(dsn), 'POSTRIFF_DATABASE_URL is required for current server-admin binding verification.')
        import psycopg
        with psycopg.connect(dsn, connect_timeout=10) as connection:
            connection.read_only = not args.apply
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("SET LOCAL statement_timeout='10s'")
                current = current_context(cursor, bindings, action_ids, lock=args.apply)
                preview = make_preview(template, matrix, attestation, proofs, current, args.capability, args.operator)
                if args.apply:
                    write_acceptance(cursor, preview, args.expected_preview_digest)
        if args.apply:
            print(json.dumps({'execution': 'APPLIED', 'applied': True, 'digest': preview['digest'], 'capabilities': sorted(preview['plan']['acceptance'])}))
        else:
            print(json.dumps(preview, indent=2, allow_nan=False))
        return 0
    except AcceptanceError as error:
        print(json.dumps({'execution': 'REJECTED', 'applied': False, 'reason': str(error)}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Evidence can contain private material. Never echo malformed inputs, DSNs or provider responses.
        print(json.dumps({'execution': 'REJECTED', 'applied': False, 'reason': 'Evidence or current server bindings failed closed; review required inputs and current acceptance contract.'}))
        return 2
    except Exception:
        print(json.dumps({'execution': 'REJECTED', 'applied': False, 'reason': 'Server-admin database verification unavailable; no successful apply is reported.'}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
