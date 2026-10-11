"""Real disposable PostgreSQL policy/OAuth/dispatch regression; synthetic Google only.

Runs in its own cloud harness group after rls.sql. It never registers real legal
copy, accesses production accounts, or performs real Google/AI/provider calls.
"""
import io
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.youtube.model import READ, UPLOAD
from postriff_phase2.youtube.provider import YouTubeProvider
from youtube_policy_fixture import register_synthetic_policy, accept_synthetic_policy

ORIGIN = 'https://rafii.example'
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
USERS = {name: str(uuid4()) for name in ('holder', 'other')}
CHANNEL = 'UC' + 'p'*22
CLIENT = 'synthetic-policy.apps.googleusercontent.com'
WORKSPACES = []


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=5000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        yield db


def verify(token):
    if token.startswith('synthetic-policy-interactive-session-'):
        token = token.removeprefix('synthetic-policy-interactive-session-')
    return USERS[token]


verify.session_id = lambda token, actor: 'synthetic-policy-session-' + token
verify.auth_time = lambda token, actor: time.time()


class Google:
    def __init__(self):
        self.scopes = [READ]
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url))
        parsed = urlsplit(url)
        if method == 'POST' and url == YouTubeProvider.TOKEN:
            return {'status': 200, 'body': {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
                    'expires_in': 3600, 'scope': ' '.join(self.scopes)}}
        if method == 'GET' and url.startswith(YouTubeProvider.TOKENINFO + '?'):
            return {'status': 200, 'body': {'aud': CLIENT, 'scope': ' '.join(self.scopes)}}
        if method == 'POST' and url == YouTubeProvider.REVOKE:
            return {'status': 200, 'body': {}}
        if method == 'GET' and parsed.netloc == 'www.googleapis.com' and parsed.path == '/youtube/v3/channels':
            return {'status': 200, 'body': {'items': [{'id': CHANNEL, 'snippet': {'title': 'SYNTHETIC policy creator'},
                'statistics': {'viewCount': '1'}, 'status': {},
                'contentDetails': {'relatedPlaylists': {'uploads': 'UU' + 'p'*22}}}]}}
        if method == 'GET' and parsed.netloc == 'www.googleapis.com' and parsed.path == '/youtube/v3/playlistItems':
            return {'status': 200, 'body': {'items': []}}
        raise AssertionError(('Unexpected synthetic transport request; no network', method, url))


def expect_error(call, codes, *, no_calls=True):
    before = len(google.calls)
    try:
        call()
        raise AssertionError('Expected fail-closed policy boundary')
    except AlphaError as error:
        assert error.code in codes if isinstance(codes, tuple) else error.code == codes, error
    if no_calls:
        assert len(google.calls) == before, 'A blocked admission dispatched a provider request.'


def start(capability='identity', token='holder'):
    begun = service.oauth.start(workspace, token, 'youtube', capability)
    return parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]


def complete(state, token='holder'):
    return service.oauth.complete(workspace, token, 'youtube', state, 'synthetic-code')


def http(method, path, body=None, token='holder'):
    captured = {}
    payload = json.dumps(body or {}).encode()
    raw = b''.join(app({'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '',
        'HTTP_AUTHORIZATION': 'Bearer synthetic-policy-interactive-session-' + token, 'HTTP_X_POSTRIFF_REQUEST': 'founder-alpha',
        'HTTP_ORIGIN': ORIGIN, 'HTTP_HOST': 'rafii.example', 'wsgi.url_scheme': 'https',
        'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(payload)), 'wsgi.input': io.BytesIO(payload)},
        lambda status, headers: captured.update(status=int(status.split()[0]))))
    return captured['status'], json.loads(raw)


google = Google()
provider = YouTubeProvider(CLIENT, 'synthetic-secret', transport=google)
service = HostedWorkspaceService(connection, verify, vault=CredentialVault(CredentialVault.generate_key()),
                                 providers={'youtube': provider}, public_base_url=ORIGIN)
app = HostedApplication(service)
checks = []
try:
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_revisions').fetchone()[0] == 0
        migration = (ROOT / 'migrations/postriff/099_youtube_policy_acceptance.sql').read_text()
        db.execute(migration)
        db.execute(migration)
        assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_revisions').fetchone()[0] == 0
        for user in USERS.values():
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
    for token in USERS:
        WORKSPACES.append(service.bootstrap(token, 'studio')['workspaceId'])
    workspace, foreign = WORKSPACES
    service.oauth.youtube_public_base_url = ORIGIN
    status, missing = http('GET', f'/api/workspaces/{workspace}/youtube-policy')
    assert status == 200 and not missing['ready'] and missing['policy'] is None
    expect_error(start, 'youtube_policy_not_ready')
    checks.append('idempotent migration seeds no active approval; PUBLIC identity onboarding fails before Google')

    # Compatibility is strictly nonpublic standard READ-only.
    service.oauth.youtube_public_base_url = None
    provider.callback_origin = 'https://legacy-router.example'
    legacy = complete(start())['connectionId']
    service.oauth.token_for_worker(workspace, legacy)
    with connection() as db:
        assert db.execute('SELECT count(*) FROM public.pr_youtube_policy_bindings').fetchone()[0] == 0
    before_channels = sum(urlsplit(url).path == '/youtube/v3/channels' for _, url in google.calls)
    google.scopes = [READ, UPLOAD]
    expect_error(lambda: complete(start()), 'youtube_policy_acceptance_required', no_calls=False)
    assert sum(urlsplit(url).path == '/youtube/v3/channels' for _, url in google.calls) == before_channels
    google.scopes = [READ]
    expect_error(lambda: start('publish'), 'youtube_policy_not_ready')
    provider.agentic_provider = YouTubeProvider('synthetic-agentic-client', 'synthetic-secret',
        transport=google, authorization_lane='agentic')
    provider.agentic_provider.execution_enabled = True
    expect_error(lambda: service.oauth.start(workspace, 'holder', 'youtube', 'autopilot',
        {'authorizationLane': 'agentic', 'agenticConsent': True}), 'youtube_policy_not_ready')
    provider.creator_enabled = True
    expect_error(start, 'youtube_policy_not_ready')
    expect_error(lambda: service.youtube.read(workspace, 'holder', legacy, 'videos'), 'youtube_policy_not_ready')
    expect_error(lambda: service.oauth.token_for_worker(workspace, legacy), 'youtube_policy_not_ready')
    checks.append('pinned legacy READ-only remains; broader grants, publish, agentic and Creator flags cannot bypass readiness')

    register_synthetic_policy(connection, ORIGIN)
    policy = service.oauth.youtube_policy.status(workspace, 'holder')['policy']
    body = {'policyId': policy['id'], 'privacyRevision': policy['privacy']['revision'],
            'termsRevision': policy['terms']['revision'], 'confirmed': True}
    assert http('POST', f'/api/workspaces/{workspace}/youtube-policy', {**body, 'userId': USERS['other']})[0] == 400
    assert http('POST', f'/api/workspaces/{foreign}/youtube-policy', body)[0] == 403
    status, accepted = http('POST', f'/api/workspaces/{workspace}/youtube-policy', body)
    assert status == 200 and accepted['receipt']['userId'] == USERS['holder']
    assert accepted['receipt']['workspaceId'] == workspace and accepted['receipt']['acceptedAt'] > 0
    assert service.oauth.youtube_policy.accept(workspace, 'holder', body)['receipt'] == accepted['receipt']
    with connection() as db:
        # Same workspace authority does not inherit another holder's receipt.
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_manage_connections) VALUES(%s,%s,'admin','active',true)",
                   (workspace, USERS['other']))
    expect_error(lambda: service.oauth.start(workspace, 'other', 'youtube', 'identity'), 'youtube_policy_acceptance_required')
    foreign_receipt = accept_synthetic_policy(service, foreign, 'other')['receipt']
    with service.repository.transaction('other', workspace) as (cur, _, actor):
        expect_error(lambda: service.oauth.youtube_policy.require_pending(cur, workspace, actor, 'other', provider,
            [READ], {'policyAcceptance': {'policyId': policy['id'], 'receiptId': foreign_receipt['id']}}),
            'youtube_policy_acceptance_required')
    checks.append('HTTP explicit holder receipt is timestamped, idempotent and tenant/user bound; spoof and foreign receipts denied')

    pending = start()
    register_synthetic_policy(connection, ORIGIN, replace=True)
    expect_error(lambda: complete(pending), 'youtube_policy_acceptance_required')
    accept_synthetic_policy(service, workspace, 'holder')
    expect_error(lambda: complete(pending), 'youtube_policy_acceptance_required')
    service.oauth.youtube_public_base_url = ORIGIN
    google.scopes = [READ, UPLOAD]
    connected = complete(start('publish'))['connectionId']
    grant = service.oauth.token_for_worker(workspace, connected)
    held = service.oauth.provider_for_grant(grant)
    assert service.youtube.read(workspace, 'holder', connected, 'videos')['items'] == []
    expect_error(lambda: service.youtube.read(workspace, 'other', connected, 'videos'), 'youtube_policy_acceptance_required')
    checks.append('policy changes invalidate pending OAuth even after renewed acceptance; new OAuth and Creator read succeed')

    # Exercise the real shared-composer gate even though a fresh channel needs
    # no OAuth revalidation. The connecting holder's receipt is not the second
    # active actor's agreement. This is preflight only, never a publication.
    composer_variant = 'synthetic-policy-composer-' + uuid4().hex
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET can_publish=true WHERE workspace_id=%s AND user_id=%s AND status='active'",
                   (workspace, USERS['other']))
        db.execute("""UPDATE public.pr_workspaces
            SET state=jsonb_set(state,'{variants}',coalesce(state->'variants','[]'::jsonb)||jsonb_build_array(%s::jsonb)),
                revision=revision+1 WHERE id=%s""",
            (json.dumps({'id': composer_variant, 'platform': 'YouTube', 'channelId': connected}), workspace))
    composer_snapshot = service.repository.get(workspace, 'other')
    composer_channel = next(item for item in composer_snapshot['state']['phase2']['channels'] if item['id'] == connected)
    assert service.commands.engine.hosted_entitlements is True
    assert composer_channel['configured'] and composer_channel['identityVerified'] and composer_channel['capabilityVerified']
    assert composer_channel['expiresAt'] > service.clock() and composer_channel['verifiedAt'] + 3600 >= service.clock()
    assert service.commands.engine.channel_reverification_due(composer_channel) is False
    assert service.oauth.youtube_policy.status(workspace, 'holder')['accepted'] is True
    assert service.oauth.youtube_policy.status(workspace, 'other')['accepted'] is False
    composer_payload = {'variantId': composer_variant, 'channelId': connected}
    before_composer = len(google.calls)
    expect_error(lambda: service.oauth.refresh_for_composer(workspace, 'other', composer_snapshot['revision'],
        'p2_review', composer_payload), 'youtube_policy_acceptance_required')
    assert service.repository.get(workspace, 'other') == composer_snapshot
    second_receipt = accept_synthetic_policy(service, workspace, 'other')['receipt']
    assert second_receipt['userId'] == USERS['other'] and second_receipt['workspaceId'] == workspace
    assert service.oauth.refresh_for_composer(workspace, 'other', composer_snapshot['revision'],
        'p2_review', composer_payload) is None
    assert len(google.calls) == before_composer, 'Fresh composer admission must neither revalidate nor dispatch Google.'
    assert service.repository.get(workspace, 'other') == composer_snapshot
    checks.append('fresh generic p2_review requires actual second-actor agreement; the same preflight passes after their acceptance without Google or state changes')

    register_synthetic_policy(connection, ORIGIN, replace=True)
    expect_error(lambda: held.identity(grant['accessToken']), 'youtube_policy_acceptance_required')
    expect_error(lambda: service.oauth.token_for_worker(workspace, connected), 'youtube_policy_acceptance_required')
    expect_error(lambda: service.youtube.read(workspace, 'holder', connected, 'videos'), 'youtube_policy_acceptance_required')
    accept_synthetic_policy(service, workspace, 'holder')
    held.identity(grant['accessToken'])
    generation = grant['authorizationGeneration']
    complete(start('publish'))
    expect_error(lambda: held.identity(grant['accessToken']), 'youtube_policy_acceptance_required')
    fresh = service.oauth.token_for_worker(workspace, connected)
    assert fresh['authorizationGeneration'] != generation
    checks.append('held provider and worker admission recheck revision/receipt and exact OAuth generation before transport')

    # Registry is immutable; browser roles cannot read or write receipts/approvals.
    with connection() as db:
        tables = ('pr_youtube_policy_revisions', 'pr_youtube_policy_acceptances', 'pr_youtube_policy_bindings')
        for table in tables:
            row = db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('public.'+table,)).fetchone()
            assert row == (True, True)
            assert not db.execute('SELECT has_table_privilege(%s,%s,%s)', ('authenticated', 'public.'+table, 'INSERT')).fetchone()[0]
            assert not db.execute('SELECT has_table_privilege(%s,%s,%s)', ('anon', 'public.'+table, 'SELECT')).fetchone()[0]
        for role in ('anon', 'authenticated'):
            with db.transaction(force_rollback=True):
                db.execute('SET LOCAL ROLE ' + role)
                try:
                    with db.transaction():
                        db.execute('SELECT * FROM public.pr_youtube_policy_acceptances')
                    raise AssertionError('Browser role read service-only receipt rows')
                except psycopg.errors.InsufficientPrivilege:
                    pass
        try:
            with db.transaction():
                db.execute("UPDATE public.pr_youtube_policy_revisions SET privacy_revision='forged' WHERE is_current")
            raise AssertionError('Published document content changed in place')
        except psycopg.errors.RaiseException:
            pass
    checks.append('all three tables force RLS, deny browser grants, and freeze published document metadata')

    # Cleanup can continue without current acceptance and without a mounted provider gate.
    register_synthetic_policy(connection, ORIGIN, replace=True)
    expect_error(lambda: service.youtube._member(workspace, 'holder', connected), 'youtube_policy_acceptance_required')
    service.youtube._member(workspace, 'holder', connected, policy_required=False)
    policy_id = 'synthetic-cleanup-policy'
    with connection() as db:
        db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{youtubeAgent}',%s::jsonb),revision=revision+1 WHERE id=%s",
            (json.dumps({'drafts': [], 'policies': [{'id': policy_id, 'connectionId': connected, 'channelId': CHANNEL, 'status': 'active'}]}), workspace))
    assert service.youtube.agent.overview(workspace, 'holder', connected)['autopilotGate']['canActivate'] is False
    before_cleanup = len(google.calls)
    for action, expected in (('pause', 'paused'), ('revoke', 'revoked')):
        revision = service.repository.get(workspace, 'holder')['revision']
        assert service.youtube.agent.policy_action(workspace, 'holder', connected, policy_id, action,
            {'revision': revision})['result']['status'] == expected
    assert len(google.calls) == before_cleanup
    saved_provider = service.oauth.providers.pop('youtube')
    expect_error(lambda: service.youtube._member(workspace, 'holder', connected), 'youtube_policy_acceptance_required')
    service.oauth.providers['youtube'] = saved_provider
    result = service.oauth.disconnect(workspace, 'holder', connected)
    assert result['disconnected']
    checks.append('local cleanup overview, actual Autopilot pause/revoke and disconnect remain available while agreement is stale')
    print(json.dumps({'execution': 'CLOUD_SYNTHETIC', 'externalProviderCalls': 0, 'productionAcceptance': False, 'checks': checks}))
finally:
    with connection() as db:
        for workspace_id in WORKSPACES:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace_id,))
