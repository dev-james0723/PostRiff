"""Trusted operator import of reviewed real evidence; never a customer-facing API."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import UUID
from urllib.parse import urlparse

from .model import MANAGE, READ, has_scopes

TEMPLATE_SHA256 = 'a38092b4b9d3640f8b258f4758a8c930e3886c472206550c6092173aeb13dd99'
IDENTITY_CASES = ('connection.identity', 'connection.actual_scopes', 'connection.workspace_isolation')
REQUIRED_CASES = {
    'identity': IDENTITY_CASES,
    'connected': IDENTITY_CASES + ('connection.oauth', 'connection.refresh', 'connection.reconnect',
        'connection.disconnect', 'connection.revoked', 'connection.client_failure', 'connection.brand_channel'),
    'metadata_edit': IDENTITY_CASES + ('video.edit',),
}
METHOD_GROUPS = {
    'Google OAuth authorization/token': ('oauth.authorization', 'oauth.token'),
    'Google OAuth token': ('oauth.token',),
    'Google OAuth tokeninfo': ('oauth.tokeninfo',),
    'Google OAuth token/tokeninfo': ('oauth.token', 'oauth.tokeninfo'),
    'Google OAuth revoke': ('oauth.revoke',),
}
ROUTES = {
    'oauth.authorization': ('GET', 'https://accounts.google.com/o/oauth2/v2/auth'),
    'oauth.token': ('POST', 'https://oauth2.googleapis.com/token'),
    'oauth.tokeninfo': ('GET', 'https://oauth2.googleapis.com/tokeninfo'),
    'oauth.revoke': ('POST', 'https://oauth2.googleapis.com/revoke'),
    'channels.list': ('GET', 'https://www.googleapis.com/youtube/v3/channels'),
    'videos.list': ('GET', 'https://www.googleapis.com/youtube/v3/videos'),
    'videos.update': ('PUT', 'https://www.googleapis.com/youtube/v3/videos'),
}
SECRET_KEYS = {'access_token', 'refresh_token', 'client_secret', 'authorization', 'cookie',
    'code', 'state', 'code_verifier', 'streamName', 'password', 'api_key', 'accessToken', 'refreshToken'}


class AcceptanceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Document:
    value: dict
    sha256: str


def document(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'Duplicate JSON key.')
            out[key] = value
        return out
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(AcceptanceError('Non-finite JSON value.')))
    except (ValueError, UnicodeError) as error:
        raise AcceptanceError('Malformed evidence JSON.') from error
    require(isinstance(value, dict), 'Evidence must be a JSON object.')
    try:
        digest(value)
    except (ValueError, OverflowError) as error:
        raise AcceptanceError('Non-finite JSON value.') from error
    return Document(value, digest(raw))


def read_document(path, root=None):
    path = Path(path)
    require(not path.is_symlink() and path.suffix == '.json', 'Use a regular redacted JSON file.')
    resolved = path.resolve()
    if root is not None:
        require(resolved.is_relative_to(Path(root).resolve()), 'Evidence path escapes its reviewed directory.')
    require(resolved.is_file() and resolved.stat().st_size <= 2 * 1024 * 1024, 'Evidence file unavailable or too large.')
    return document(resolved.read_bytes())


def instant(value):
    try:
        require(isinstance(value, str), 'Evidence timestamp must be a zoned string.')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'Evidence timestamp needs a time zone.')
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise AcceptanceError('Malformed evidence timestamp.') from error


def fresh(value, now):
    stamp = instant(value)
    require(-300 <= (now - stamp).total_seconds() <= 30 * 86400, 'Evidence is stale or future dated.')
    return stamp


def redacted_real(value):
    if isinstance(value, dict):
        for key, item in value.items():
            require(key not in SECRET_KEYS, 'Evidence contains an unredacted credential field.')
            if key in ('fixture', 'synthetic', 'mock', 'injected'):
                require(item is False, 'Fixture or injected proof is not real acceptance.')
            if key == 'execution':
                require(item == 'real', 'Only explicit real execution is accepted.')
            if key == 'transport':
                require(item == 'official_https', 'Injected or missing official transport provenance.')
            redacted_real(item)
    elif isinstance(value, list):
        for item in value:
            redacted_real(item)
    elif isinstance(value, str):
        require(not re.search(r'(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}', value), 'Evidence contains a bearer credential.')


def reviewed_rows(template, matrix, bindings, now):
    require(template.sha256 == TEMPLATE_SHA256, 'The reviewed 151-case template changed; review its mapping first.')
    baseline = template.value.get('cases', [])
    require(len(baseline) == 151, 'Expected the complete 151-case template.')
    trusted = {row['id']: row for row in baseline}
    data = matrix.value
    rows = data.get('cases', [])
    require(isinstance(rows, list) and len(rows) == 151 and all(isinstance(r, dict) for r in rows), 'Use the complete reviewed matrix.')
    indexed = {row.get('id'): row for row in rows}
    require(len(indexed) == 151 and set(indexed) == set(trusted), 'Matrix case IDs are missing, duplicated or foreign.')
    require(data.get('schemaVersion') == 1 and data.get('execution') == 'real', 'Matrix must record real execution.')
    require(data.get('ordinaryCreatorChannelId') == bindings['channelId'] and
        data.get('googleProjectId') == bindings['projectId'], 'Matrix project or channel does not match.')
    fresh(data.get('updatedAt'), now)
    for case_id, row in indexed.items():
        require(all(row.get(key) == trusted[case_id].get(key) for key in
            ('family', 'expectedEvidence', 'officialMethods', 'realE2ERequired')), 'A canonical case requirement was altered.')
        if row.get('state') == 'PASS':
            require(row.get('execution') == 'real' and row.get('realE2ETested') is True and
                row.get('realE2ERequired') is True and row.get('channelId') == bindings['channelId'], 'Invalid real PASS in the matrix.')
    require(type(data.get('realPassCount')) is int and data['realPassCount'] ==
        sum(row.get('state') == 'PASS' for row in rows), 'Matrix realPassCount does not match its cases.')
    return trusted, indexed


def verify_observations(case_id, row, proof, bindings, scopes):
    expected = {method for label in row['officialMethods'] for method in METHOD_GROUPS.get(label, (label,))}
    observations = proof.get('observations')
    require(isinstance(observations, list) and 0 < len(observations) <= 100, 'Official observations are required.')
    require({item.get('method') for item in observations if isinstance(item, dict)} == expected, 'Official method coverage is incomplete or foreign.')
    for item in observations:
        require(isinstance(item, dict), 'Malformed observation.')
        method = item.get('method')
        require(method in ROUTES and (item.get('httpMethod'), item.get('sourceUrl')) == ROUTES[method], 'Observation is not a supported official route.')
        ids = item.get('resourceIds', {})
        require(isinstance(ids, dict) and ids.get('channelId') == bindings['channelId'] and
            all(ids.get(k) == v for k, v in row['resourceIds'].items()), 'Official method/resource linkage does not match.')
        response = item.get('response')
        require(isinstance(response, dict) and type(item.get('status')) is int, 'A redacted official response is required.')
        allowed = (200, 400, 401) if case_id in ('connection.revoked', 'connection.client_failure') else (200, 302) if method == 'oauth.authorization' else (200,)
        require(item['status'] in allowed, 'Official response does not establish the required outcome.')
        if method == 'channels.list':
            require(isinstance(response.get('items'), list) and response['items'] and
                all(x.get('id') == bindings['channelId'] for x in response['items'] if isinstance(x, dict)) and
                all(isinstance(x, dict) for x in response['items']), 'Official channel identity is missing or foreign.')
        if method == 'videos.update':
            require(response.get('id') == ids.get('videoId'), 'Official write response does not match the Video ID.')
        if method == 'videos.list':
            require(isinstance(response.get('items'), list) and response['items'] and all(
                isinstance(x, dict) and x.get('id') == ids.get('videoId') for x in response['items']), 'Official readback does not match the Video ID.')
        if case_id == 'connection.actual_scopes':
            require(response.get('aud') == bindings['clientId'] and isinstance(response.get('scope'), str) and
                set(response['scope'].split()) == set(scopes), 'Actual tokeninfo audience/scopes do not match the active connection.')
        if case_id == 'connection.revoked':
            require(response.get('error') in ('invalid_grant', 'invalid_token'), 'Revocation needs the official error outcome.')
        if case_id == 'connection.client_failure':
            require(response.get('error') == 'invalid_client', 'Client failure needs the official invalid_client outcome.')


def verify_metadata_actions(proof, current, bindings, row, now):
    scenarios = proof.get('scenarioActions', {})
    require(isinstance(scenarios, dict) and set(scenarios) == {'snippet', 'status', 'recordingDetails', 'localizations'}, 'Metadata acceptance needs all four omitted-field scenarios.')
    require(len({link.get('actionId') for link in scenarios.values() if isinstance(link, dict)}) == 4, 'A single action cannot prove the whole metadata capability.')
    video = proof['resourceIds'].get('videoId', '')
    require(isinstance(video, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video), 'Metadata evidence needs the exact Video ID.')
    for part, link in scenarios.items():
        require(isinstance(link, dict), 'Malformed action linkage.')
        action = current.get('actions', {}).get(link.get('actionId'), {})
        manifest, receipt = action.get('manifest', {}), action.get('receipt', {})
        plan, verification = manifest.get('plan', {}), receipt.get('verification', {})
        require(action.get('status') == 'verified' and receipt.get('execution') == 'real' and
            verification.get('verified') is True, 'Action lacks verified real execution and successful current readback.')
        fresh(action.get('updatedAt'), now)
        accepted = receipt.get('acceptedAt')
        require(type(accepted) in (int, float) and math.isfinite(accepted), 'Action acceptance timestamp is missing or malformed.')
        require(instant(row['startedAt']).timestamp() <= accepted <= instant(row['verifiedAt']).timestamp() and
            instant(action['updatedAt']) <= instant(row['verifiedAt']), 'Action/readback chronology is outside the reviewed case.')
        require(all(manifest.get(k) == bindings[k] for k in ('workspaceId', 'connectionId', 'channelId')) and
            manifest.get('action') == 'video.edit' and plan.get('method') == 'videos.update', 'Action manifest binding is foreign.')
        require(action.get('manifestDigest') == digest(manifest) == link.get('manifestDigest') and
            digest(receipt) == link.get('receiptSha256'), 'Action manifest or receipt hash changed.')
        body, observed = plan.get('body', {}), verification.get('observed', {})
        require(body.get('id') == video and part in body and isinstance(body[part], dict) and
            receipt.get('channelId') == bindings['channelId'] and receipt.get('action') == 'video.edit' and
            receipt.get('source') == 'YouTube Data API' and
            receipt.get('result', {}).get('id') == video and verification.get('method') == 'videos.list' and
            verification.get('resourceId') == video and observed.get('id') == video and
            observed.get('snippet', {}).get('channelId') == bindings['channelId'], 'Action/resource readback is incomplete or foreign.')
        require(all(p == 'id' or isinstance(fields, dict) and isinstance(observed.get(p), dict) and
            all(observed[p].get(k) == v for k, v in fields.items()) for p, fields in body.items()), 'Saved action readback no longer matches its manifest.')
        seen = {o['method'] for o in proof['observations'] if o.get('actionId') == link['actionId']}
        require({'videos.update', 'videos.list'} <= seen, 'Every metadata scenario needs linked official write and readback observations.')


def make_preview(template, matrix, attestation, proofs, current, capabilities, operator, now=None):
    now = now or datetime.now(timezone.utc)
    selected = sorted(set(capabilities))
    require(selected and all(cap in REQUIRED_CASES for cap in selected), 'Unsupported import capability; uploads and other unimplemented imports remain blocked.')
    require(isinstance(operator, str) and 0 < len(operator) <= 200 and not any(ord(c) < 32 for c in operator), 'Identify the trusted operator explicitly.')
    bindings, scopes = current.get('bindings', {}), current.get('scopes', [])
    require(set(bindings) == {'workspaceId', 'connectionId', 'channelId', 'clientId', 'projectId', 'callbackUri'}, 'Current server bindings are incomplete.')
    try:
        UUID(bindings['workspaceId'])
    except (ValueError, TypeError, AttributeError) as error:
        raise AcceptanceError('Invalid workspace binding.') from error
    require(re.fullmatch(r'UC[A-Za-z0-9_-]{22}', str(bindings['channelId'])) and
        re.fullmatch(r'[A-Za-z0-9._:-]{8,80}', str(bindings['connectionId'])), 'Invalid channel or connection binding.')
    callback = urlparse(str(bindings['callbackUri']))
    require(re.fullmatch(r'\d+-[a-z0-9]+\.apps\.googleusercontent\.com', str(bindings['clientId'])) and
        re.fullmatch(r'[a-z][a-z0-9-]{4,62}', str(bindings['projectId'])) and callback.scheme == 'https' and
        callback.hostname and not callback.username and not callback.password and not callback.query and
        not callback.fragment and callback.port in (None, 443) and callback.path == '/api/oauth/youtube/callback', 'Invalid current client/project/callback binding.')
    require(isinstance(current.get('settingsEvidence'), dict) and
        isinstance(current['settingsEvidence'].get('acceptance', {}), dict), 'Existing settings evidence is malformed.')
    require(current.get('provider') == 'youtube' and current.get('revoked') is False and
        current.get('providerAccountId') == bindings['channelId'], 'The exact active YouTube credential is required.')
    require(has_scopes(scopes, (MANAGE,) if 'metadata_edit' in selected else (READ,)), 'The current grant lacks required capability scopes.')
    trusted, rows = reviewed_rows(template, matrix, bindings, now)
    assertion = attestation.value
    redacted_real(assertion)
    require(assertion.get('schemaVersion') == 1 and assertion.get('operator') == operator and
        assertion.get('trustedOperator') is True and assertion.get('reviewedOriginalRealRuns') is True and
        assertion.get('bindings') == bindings and assertion.get('templateSha256') == template.sha256 and
        assertion.get('matrixSha256') == matrix.sha256, 'Trusted operator attestation does not bind the exact reviewed inputs.')
    attested = fresh(assertion.get('attestedAt'), now)
    required = sorted({case for cap in selected for case in REQUIRED_CASES[cap]})
    evidence, reviews = {}, assertion.get('caseReviews', {})
    require(isinstance(reviews, dict) and set(reviews) <= set(trusted), 'Attestation case IDs are foreign.')
    for case_id in required:
        row = rows[case_id]
        require(row.get('state') == 'PASS' and row.get('execution') == 'real' and row.get('realE2ETested') is True and
            row.get('channelId') == bindings['channelId'], 'Every required case needs its own real PASS.')
        verified = fresh(row.get('verifiedAt'), now)
        require(instant(row.get('startedAt')) <= verified <= attested and row.get('blocker') in ('', None), 'Case chronology or blocker is inconsistent.')
        ids = row.get('resourceIds')
        require(isinstance(ids, dict) and ids.get('channelId') == bindings['channelId'] and
            all(isinstance(k, str) and isinstance(v, str) for k, v in ids.items()), 'Case resource linkage is missing or malformed.')
        reference = row.get('redactedReceipt')
        require(isinstance(reference, str) and not Path(reference).is_absolute() and '..' not in Path(reference).parts and reference in proofs, 'A reviewed local redacted receipt is required.')
        source, review = proofs[reference], reviews.get(case_id, {})
        proof = source.value
        redacted_real(proof)
        require(proof.get('schemaVersion') == 1 and proof.get('execution') == 'real' and
            proof.get('source') == 'google_platform' and proof.get('caseId') == case_id and
            proof.get('bindings') == bindings and proof.get('resourceIds') == ids and
            proof.get('provenance') == {'execution': 'real', 'transport': 'official_https'}, 'Source proof is missing real channel/project/resource provenance.')
        run_id = proof.get('runId')
        require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', run_id) and
            not re.search(r'(?i)(?:^|[-_:])(fixture|synthetic|mock|injected)(?:[-_:]|$)', run_id), 'Source needs an original real-run identifier.')
        require(instant(row['startedAt']) <= fresh(proof.get('observedAt'), now) <= verified, 'Receipt observation is outside the case run.')
        require(isinstance(review, dict) and review.get('receiptSha256') == source.sha256 and
            review.get('expectedEvidenceSha256') == digest(trusted[case_id]['expectedEvidence']) and
            all(review.get(key) is True for key in ('originalRunVerified', 'requiredBehaviorVerified', 'methodResourceLinkageVerified')), 'Each complete case needs an explicit hash-bound original-run review.')
        verify_observations(case_id, row, proof, bindings, scopes)
        if case_id == 'video.edit':
            verify_metadata_actions(proof, current, bindings, row, now)
        evidence[case_id] = {'reference': reference, 'sha256': source.sha256, 'verifiedAt': row['verifiedAt']}
    acceptance = {}
    for cap in selected:
        cases = REQUIRED_CASES[cap]
        acceptance[cap] = {'status': 'PASS', 'execution': 'real', 'channelId': bindings['channelId'],
            'verifiedAt': min((rows[c]['verifiedAt'] for c in cases), key=instant),
            'reference': 'sha256:' + matrix.sha256, 'source': 'trusted_operator_case_import',
            'operator': operator, 'caseIds': list(cases), 'caseEvidence': {c: evidence[c] for c in cases},
            'attestationSha256': attestation.sha256, 'templateSha256': template.sha256,
            'clientId': bindings['clientId'], 'projectId': bindings['projectId']}
    plan = {'bindings': bindings, 'acceptance': acceptance, 'currentSnapshotSha256': digest(current),
        'matrixSha256': matrix.sha256, 'attestationSha256': attestation.sha256}
    return {'execution': 'PREVIEW', 'applied': False, 'digest': digest(plan), 'plan': plan}


def write_acceptance(cursor, preview, expected_digest):
    require(isinstance(expected_digest, str) and re.fullmatch(r'[a-f0-9]{64}', expected_digest) and
        expected_digest == preview.get('digest') == digest(preview['plan']), 'Preview changed; review a fresh digest before applying.')
    require(preview['plan'].get('acceptance') and set(preview['plan']['acceptance']) <= set(REQUIRED_CASES), 'Unsupported acceptance update.')
    bindings = preview['plan']['bindings']
    cursor.execute("""INSERT INTO public.pr_youtube_settings(workspace_id,connection_id,evidence)
        VALUES(%s,%s,jsonb_build_object('acceptance',%s::jsonb))
        ON CONFLICT(workspace_id,connection_id) DO UPDATE SET
          evidence=jsonb_set(pr_youtube_settings.evidence,'{acceptance}',
            coalesce(pr_youtube_settings.evidence->'acceptance','{}'::jsonb)||(excluded.evidence->'acceptance')),
          updated_at=now()""", (bindings['workspaceId'], bindings['connectionId'],
            json.dumps(preview['plan']['acceptance'], allow_nan=False)))
