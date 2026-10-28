"""Facebook Page approval and Page choice, run with ONE source tree; prints one JSON record (finding FB-1).

    python tests/rc2_facebook_probe.py <tree> [<approved-state.json>]

tests/test_rc2_shared_path_fixes.py runs it with the live tree (c5fc1fd1) and with this tree and compares the records,
so the fix for FB-1 is proved as "Facebook behaves exactly as live", not as a guessed expectation. It is executed as a
script with the tree under test first on sys.path, so every postriff_phase2 import below is that tree's code. No
database, provider, network or credential: the repository and the Facebook Graph API are small in-memory fakes, and
the Graph fake answers only the Page list.

Record:
  scenarios   for a Facebook Page channel as live's OAuth completion stores it, and the same channel carrying the Page
              id an earlier candidate's Page choice wrote (channel.destinationId): the review's status and current(),
              the approval (or its refusal), current() of the job, the job after the next ordinary invalidate() (every
              hosted command ends with one), and after the worker claim's invalidation (the candidate's
              PostgresWorker._invalidate_owned, or live's plain engine.invalidate, whichever this tree's claim runs)
  approvedState  the state after the approval in the first scenario (the live run's copy is handed to the other tree)
  carried     with a second argument: that approved state (approved by ANOTHER build, e.g. live before promotion),
              put through this tree's invalidate() and claim invalidation, and its job's current()
  choosePage  OAuthService.choose_destination for a Facebook Page: every SQL statement shape, the stored channel
              record after it, and the workspace revision
"""
import copy
import json
import os
import re
import secrets
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

tree = sys.argv[1]
sys.path.insert(0, os.path.join(tree, 'src'))
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.auth import initial_phase2_state  # noqa: E402
from postriff_phase2.hosted import HostedPhase2Commands  # noqa: E402
from postriff_phase2.hosted_worker import PostgresWorker  # noqa: E402
from postriff_phase2.oauth import CredentialVault, OAuthService  # noqa: E402
from postriff_phase2.wave3_connectors import FacebookPagesProvider  # noqa: E402

NOW = 1_800_000_000.0
WORKSPACE = '10000000-0000-4000-8000-0000000000fb'
OWNER = '20000000-0000-4000-8000-0000000000fb'
PERSON, PAGE, OTHER_PAGE = '7700000001', '100200300400', '100200300401'
CONNECTION = 'facebook-connection-1'
# Synthetic credentials are generated for each run (rule P2-SEC-CI-04: no literal credential, no scanner exception);
# none of them reaches the printed record.
SESSION, APP_SECRET, USER_TOKEN = ('synthetic-' + secrets.token_hex(12) for _ in range(3))


def base_state():
    state = initial_phase2_state(WORKSPACE, OWNER, 'Rafii member', 'studio', NOW - 86400, execution='hosted-candidate')
    commands = HostedPhase2Commands(clock=lambda: NOW)
    # What live's OAuthService.complete stores for a person who granted one Page (FacebookPagesProvider.identity).
    commands.upsert_verified_channel(state, OWNER, {
        'id': CONNECTION, 'platform': 'Facebook', 'account': 'Impact Studio', 'accountType': 'page',
        'scopes': ['business_management', 'pages_manage_posts', 'pages_read_engagement', 'pages_show_list'],
        'verifiedAt': NOW, 'expiresAt': NOW + 86400 * 365, 'capabilityVersion': 1, 'providerAccountId': PERSON})
    state['variants'].append({
        'id': 'facebook-draft-1', 'platform': 'Facebook', 'text': 'Community workshop this Saturday: bring a friend.',
        'language': 'en', 'revision': 1, 'voiceRevision': state['speaker']['activeRevision'],
        'briefRevision': state['brief']['revision'], 'sourceIds': [], 'needsReview': False, 'blockedByRetraction': False,
        'unknowns': [], 'warnings': [], 'contentTypeId': 'unclassified', 'contentTypeVersion': 'legacy', 'formatId': None})
    return state


def claim_invalidation(state):
    """Exactly the invalidation this tree's PostgresWorker claim runs on a workspace it locked (default lanes)."""
    worker = PostgresWorker(lambda: None, clock=lambda: NOW + 600)
    owned = getattr(worker, '_invalidate_owned', None)
    if owned is not None:
        owned(state)
    else:
        worker.commands.engine.invalidate(state)


def job_view(job):
    return {'state': job['state'], 'events': [e['message'] for e in job.get('events', [])]}


def normalized(manifest):
    """The manifest with the per-run random identifiers (brand hub, speaker, ...) and digests replaced."""
    text = json.dumps(manifest, sort_keys=True)
    text = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<uuid>', text)
    return json.loads(re.sub(r'\b[0-9a-f]{32,64}\b', '<hex>', text))


def scenario(page_on_channel):
    commands = HostedPhase2Commands(clock=lambda: NOW)
    engine, state = commands.engine, base_state()
    if page_on_channel:
        next(c for c in state['phase2']['channels'] if c['id'] == CONNECTION)['destinationId'] = PAGE
    out = {}
    local = datetime.fromtimestamp(NOW + 3600, timezone.utc).strftime('%Y-%m-%dT%H:%M')
    commands(state, OWNER, 'p2_review', {'variantId': 'facebook-draft-1', 'channelId': CONNECTION, 'localTime': local,
                                         'timeZone': 'UTC', 'acknowledgedWarnings': []})
    review = state['phase2']['reviews'][-1]
    out['review'] = {'status': review['status'], 'current': engine.current(state, review['manifest']),
                     'manifest': normalized(review['manifest'])}
    try:
        commands(state, OWNER, 'p2_approve', {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
    except AlphaError as error:
        out['approval'] = {'refused': str(error), 'status': error.status}
        return out, None
    job = state['phase2']['jobs'][-1]
    out['approval'] = job_view(job)
    out['approval']['current'] = engine.current(state, job['manifest'])
    approved = copy.deepcopy(state)
    engine.invalidate(state)
    out['afterInvalidate'] = job_view(job)
    claim_invalidation(state)
    out['afterClaimInvalidation'] = job_view(job)
    return out, approved


def carried(path):
    """A post approved by another build, put through this build's invalidation."""
    with open(path) as handle:
        state = json.load(handle)
    engine = HostedPhase2Commands(clock=lambda: NOW).engine
    job = state['phase2']['jobs'][-1]
    out = {'current': engine.current(state, job['manifest'])}
    engine.invalidate(state)
    out['afterInvalidate'] = job_view(job)
    claim_invalidation(state)
    out['afterClaimInvalidation'] = job_view(job)
    return out


class Cursor:
    def __init__(self, repo):
        self.repo, self.result, self.rowcount = repo, None, 0

    def execute(self, sql, params=()):
        text = ' '.join(str(sql).split())
        self.repo.statements.append(re.sub(r"'[^']*'", "'?'", text)[:160])
        credential = self.repo.credential
        if text.startswith('SELECT provider FROM public.pr_encrypted_credentials'):
            self.result = ('facebook',)
        elif text.startswith('SELECT provider,access_ciphertext,refresh_ciphertext,key_id'):
            self.result = ('facebook', credential['access'], None, credential['key'], None, False, False,
                           credential['scopes'], PERSON, NOW - 3600)
        elif text.startswith('SELECT provider,access_ciphertext,key_id'):
            self.result = ('facebook', credential['access'], credential['key'])
        elif text.startswith('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s'):
            ciphertext, key_id, _workspace, _connection, expected = params
            self.rowcount = 0
            if expected == credential['access']:
                credential.update(access=ciphertext, key=key_id)
                self.rowcount = 1
        elif text.startswith('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1'):
            self.repo.state, self.repo.revision = json.loads(params[0]), self.repo.revision + 1
            self.rowcount = 1
        else:
            # Capability rows, audit events, savepoints and anything else: recorded above, nothing stored.
            self.result, self.rowcount = None, 1

    def fetchone(self):
        return self.result

    def fetchall(self):
        return [self.result] if self.result else []


class Repository:
    """The two repository calls a Page choice uses, around one locked workspace row."""
    def __init__(self, state, vault):
        self.state, self.revision, self.statements = state, 7, []
        access, key = vault.encrypt(json.dumps({'v': 1, 'user': PERSON, 'name': 'Impact Member', 'ut': USER_TOKEN,
                                                'scope': list(GRANTED), 'page': None}))
        self.credential = {'access': access, 'key': key, 'scopes': list(GRANTED)}

    @contextmanager
    def transaction(self, token, workspace_id, **kwargs):
        if token != SESSION or workspace_id != WORKSPACE:
            raise AlphaError('Workspace unavailable.', 403)
        # (revision, state, role, can_publish, ...) as PostgresWorkspaceRepository selects MEMBER_COLUMNS.
        yield Cursor(self), (self.revision, copy.deepcopy(self.state), 'owner', True, False, False, False), OWNER

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id) as (_, row, _):
            return {'revision': row[0], 'state': row[1]}

    @contextmanager
    def connection_factory(self):
        @contextmanager
        def cursor():
            yield Cursor(self)
        class Db:
            pass
        db = Db()
        db.cursor = cursor
        yield db


GRANTED = ['business_management', 'pages_manage_posts', 'pages_read_engagement', 'pages_show_list']


def graph(method, url, **kwargs):
    if method == 'GET' and '/me/accounts' in url:
        pages = [{'id': page, 'name': name, 'tasks': ['CREATE_CONTENT', 'MANAGE'], 'access_token': USER_TOKEN + '-' + page}
                 for page, name in ((PAGE, 'Impact Studio Page'), (OTHER_PAGE, 'Second Page'))]
        return {'status': 200, 'body': {'data': pages}}
    if method == 'GET' and '/me/permissions' in url:
        return {'status': 200, 'body': {'data': [{'permission': name, 'status': 'granted'} for name in GRANTED]}}
    raise AlphaError('Only the Page list and the granted permissions are answered in this probe.', 503)


def choose_page():
    vault = CredentialVault(CredentialVault.generate_key())
    repository = Repository(base_state(), vault)
    facebook = FacebookPagesProvider('123456789012345', APP_SECRET, transport=graph)
    service = OAuthService(repository, HostedPhase2Commands(lambda: NOW), vault, {'facebook': facebook},
                           'https://app.rafii.invalid', clock=lambda: NOW)
    out = {}
    try:
        out['result'] = service.choose_destination(WORKSPACE, SESSION, CONNECTION, PAGE)
    except AlphaError as error:
        out['refused'] = str(error)
    out['statements'] = repository.statements
    out['channel'] = next(c for c in repository.state['phase2']['channels'] if c['id'] == CONNECTION)
    out['revision'] = repository.revision
    out['pageInGrant'] = (json.loads(vault.decrypt(repository.credential['access'], repository.credential['key'])).get('page') or {}).get('id')
    return out


record = {'scenarios': {}}
for name, page_on_channel in (('liveChannel', False), ('channelWithPageId', True)):
    record['scenarios'][name], approved = scenario(page_on_channel)
    if name == 'liveChannel':
        record['approvedState'] = approved
if len(sys.argv) > 2:
    record['carried'] = carried(sys.argv[2])
record['choosePage'] = choose_page()
print(json.dumps(record, sort_keys=True, default=str))
