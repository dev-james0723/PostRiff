"""One shared-path scenario, run with ONE source tree against one disposable PostgreSQL database; prints JSON.

    python tests/rc2_shared_path_scenario.py --tree T --dsn D --phases bootstrap,facebook,command,tick,channels --handoff F

tests/test_rc2_shared_paths_postgres.py runs it with the live tree (c5fc1fd1) and with this tree, each against its own
copy of the same schema, and compares the records (findings FB-1 and CH-1 of docs/CUSTOMER-IMPACT-INVENTORY.md). It is
executed as a script with the tree under test first on sys.path, so every postriff_phase2 import is that tree's code.
Adapted from the impact agent's tests/impact_scenario.py (branch claude/discord-impact-20261023).

Synthetic users and sessions only: no Supabase, no network. Provider HTTP goes to an in-memory fake that answers only
the Facebook Graph calls a Page post needs (the permission list, the Page list, one Page feed create) and refuses
everything else. Production's Discord configuration is mounted (fake credentials, the v2 flags on) so the Channels read
takes the candidate's Discord branch.

Phases (state between processes travels in the database and the --handoff file):
  bootstrap  two people sign in for the first time; person B's workspace then gets one linked Discord identity record
  facebook   person A prepares an ordinary Facebook Page post and approves it (ordinary hosted commands)
  command    person A runs one more ordinary hosted command (every hosted command ends with invalidate())
  tick       one minute tick of the hosted worker after the post is due
  channels   the Channels read for both workspaces, counting session verifications (in Production one Supabase Auth
             getUser call and one session-flag connection each), database connections and repository transactions
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument('--tree', required=True)
parser.add_argument('--dsn', required=True)
parser.add_argument('--phases', required=True)
parser.add_argument('--handoff', required=True)
args = parser.parse_args()
sys.path.insert(0, os.path.join(args.tree, 'src'))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import providers as provider_registry  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.hosted_worker import PostgresWorker  # noqa: E402
from postriff_phase2.oauth import CredentialVault  # noqa: E402

RECORD = {'phases': {}, 'errors': []}
CURRENT = {'phase': None}
HTTP = []
PAGE, PERSON = '100200300400', '7700000001'
GRANTED = ['business_management', 'pages_manage_posts', 'pages_read_engagement', 'pages_show_list']


def _phase():
    return RECORD['phases'].setdefault(CURRENT['phase'], {'connections': 0, 'statements': [], 'verifications': 0})


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None, **kwargs):
        _phase()['statements'].append(re.sub(r"'[^']*'", "'?'", ' '.join(str(sql).split()))[:300])
        return self._cursor.execute(sql, params, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._cursor.__exit__(*exc)


class Connection:
    def __init__(self, db):
        self._db = db

    def cursor(self, *a, **k):
        return Cursor(self._db.cursor(*a, **k))

    def execute(self, sql, params=None, **kwargs):
        cursor = self.cursor()
        cursor.execute(sql, params, **kwargs)
        return cursor

    def __getattr__(self, name):
        return getattr(self._db, name)

    def __enter__(self):
        self._db.__enter__()
        return self

    def __exit__(self, *exc):
        return self._db.__exit__(*exc)


def factory():
    _phase()['connections'] += 1
    return Connection(psycopg.connect(args.dsn, client_encoding='utf8', prepare_threshold=None, connect_timeout=5))


def graph(method, url, **kwargs):
    host_path = re.sub(r'^https?://([^?]+).*$', r'\1', url)
    HTTP.append({'method': method, 'url': re.sub(r'/v[0-9.]+/', '/v*/', host_path)})
    if method == 'GET' and host_path.endswith('/me/permissions'):
        return {'status': 200, 'body': {'data': [{'permission': name, 'status': 'granted'} for name in GRANTED]}}
    if method == 'GET' and host_path.endswith('/me/accounts'):
        return {'status': 200, 'body': {'data': [{'id': PAGE, 'name': 'Impact Studio Page', 'tasks': ['CREATE_CONTENT'],
                                                  'access_token': 'synthetic-page-token'}]}}
    if method == 'POST' and host_path.endswith('/%s/feed' % PAGE):
        return {'status': 200, 'body': {'id': PAGE + '_555000111'}}
    raise AlphaError('Provider HTTP is disabled in this scenario.', 503)


TOKENS = {}


def verify(token):
    _phase()['verifications'] += 1
    if token not in TOKENS:
        raise AlphaError('Synthetic session required.', 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: 'synthetic-' + token[:12]
verify.auth_time = lambda token, principal: time.time()

handoff = json.load(open(args.handoff)) if os.path.exists(args.handoff) else {'vaultKey': CredentialVault.generate_key(), 'people': []}
ENV = {'POSTRIFF_PUBLIC_BASE_URL': 'https://app.impact.invalid', 'VERCEL_ENV': 'production',
       'POSTRIFF_OAUTH_FACEBOOK_CLIENT_ID': '123456789012345', 'POSTRIFF_OAUTH_FACEBOOK_CLIENT_SECRET': 'synthetic-facebook-app-secret-01',
       'POSTRIFF_OAUTH_FACEBOOK_REVIEWED': 'true',
       'POSTRIFF_OAUTH_DISCORD_CLIENT_ID': '123456789012345678',
       'POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET': 'synthetic-discord-client-secret-0001',
       'POSTRIFF_DISCORD_BOT_TOKEN': 'synthetic-discord-bot-token-000000000001',
       'POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED': 'true', 'POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED': 'true'}
os.environ.update(ENV)
providers = provider_registry.registry_from_environment(dict(os.environ))
for adapter in providers.values():
    adapter.transport = graph
vault = CredentialVault(handoff['vaultKey'])
service = HostedWorkspaceService(factory, verify, clock=time.time, vault=vault, providers=providers,
                                 public_base_url='https://app.impact.invalid')
RECORD['mounted'] = sorted(providers)
for person in handoff['people']:
    TOKENS[person['token']] = person['user']


class phase:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        CURRENT['phase'] = self.name
        HTTP.clear()
        return _phase()

    def __exit__(self, kind, error, trace):
        record = _phase()
        record['http'] = list(HTTP)
        CURRENT['phase'] = None
        if error is not None and isinstance(error, Exception):
            RECORD['errors'].append({'phase': self.name, 'error': type(error).__name__, 'message': str(error)[:300]})
            return True
        return False


def act(person, action, **payload):
    snapshot = service.repository.get(person['workspace'], person['token'])
    return service.mutate(person['workspace'], person['token'], snapshot['revision'], action, payload)


def job_view(job):
    return {'state': job['state'], 'events': [e.get('message') for e in job.get('events', [])], 'attempts': len(job.get('attempts', []))}


def jobs_of(person):
    with psycopg.connect(args.dsn, autocommit=True) as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (person['workspace'],)).fetchone()[0]
    return [job_view(j) for j in state.get('phase2', {}).get('jobs', [])]


phases = args.phases.split(',')
if 'bootstrap' in phases:
    with phase('bootstrap'):
        for index in range(2):
            user = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'rc2-user-%d.example.invalid' % index))
            token = 'synthetic-session-%d-%s' % (index, 'x' * 24)
            TOKENS[token] = user
            with psycopg.connect(args.dsn, autocommit=True) as db:
                db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (user,))
            handoff['people'].append({'user': user, 'token': token, 'workspace': service.bootstrap(token, 'studio')['workspaceId']})
        # Person B linked a Discord identity on a candidate build (the record discord/oauth.py keeps in the state).
        b = handoff['people'][1]
        link = {'id': 'discord-identity-1', 'workspaceId': b['workspace'], 'authorizedBy': b['user'], 'account': 'synthetic#0001',
                'userId': '4242424242', 'status': 'linked', 'expiresAt': time.time() + 86400, 'discoverGuilds': False,
                'authorizationGeneration': '30000000-0000-4000-8000-000000000001'}
        with psycopg.connect(args.dsn, autocommit=True) as db:
            db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,discordIdentityLinks}',%s::jsonb,true) WHERE id=%s",
                       (json.dumps([link]), b['workspace']))

a = handoff['people'][0] if handoff['people'] else None
if 'facebook' in phases and a:
    with phase('facebook') as record:
        act(a, 'mode', mode='personal')
        act(a, 'context', purpose='Make community learning accessible', audience='Curious beginners', subject='Community workshops',
            speaker='My voice', layers=[])
        state = act(a, 'source', kind='sample')['state']
        source = state['sources'][-1]
        act(a, 'approve_source', sourceId=source['id'], factIds=[f['id'] for f in source['facts']])
        act(a, 'source_done')
        act(a, 'profile_propose', writing='A small step can be a useful beginning.', tone='warm')
        act(a, 'profile_decide', decision='approve')
        act(a, 'runtime', selected='deterministic-preview')
        # The deterministic writer drafts for LinkedIn, Instagram, Threads, X and Xiaohongshu only; the reviewed draft is
        # then marked as a Facebook draft (as the impact agent's state probe does), so every later step is the real path.
        state = act(a, 'generate', platform='LinkedIn', language='English')['state']
        variant = state['variants'][-1]
        act(a, 'p2_variant_review', variantId=variant['id'], variantRevision=variant['revision'], confirmed=True,
            excludedUnknowns=variant['unknowns'])
        with psycopg.connect(args.dsn, autocommit=True) as db:
            stored = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (a['workspace'],)).fetchone()[0]
            index = next(i for i, v in enumerate(stored['variants']) if v['id'] == variant['id'])
            db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,%s,'\"Facebook\"'::jsonb) WHERE id=%s",
                       (['variants', str(index), 'platform'], a['workspace']))
        variant = service.repository.get(a['workspace'], a['token'])['state']['variants'][index]
        now = time.time()
        # What live's OAuthService.complete stores for a person who granted one Page, and the grant behind it.
        channel = {'id': 'facebook-impact-1', 'platform': 'Facebook', 'account': 'Impact Studio Page', 'accountType': 'page',
                   'scopes': list(GRANTED), 'verifiedAt': now, 'expiresAt': now + 86400 * 365, 'capabilityVersion': 1,
                   'providerAccountId': PERSON, 'language': 'English'}
        session = {'v': 1, 'user': PERSON, 'name': 'Impact Member', 'ut': 'synthetic-user-token', 'scope': list(GRANTED),
                   'page': {'id': PAGE, 'name': 'Impact Studio Page', 'token': 'synthetic-page-token'}}
        access, key_id = vault.encrypt(json.dumps(session))
        with psycopg.connect(args.dsn, autocommit=True) as db:
            db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) "
                       "VALUES(%s,%s,'facebook',%s,%s,%s,%s)", (a['workspace'], channel['id'], PERSON, access, key_id, list(GRANTED)))
        snapshot = service.repository.get(a['workspace'], a['token'])
        service.repository.command(a['workspace'], a['token'], snapshot['revision'],
                                   lambda s, actor: service.commands.upsert_verified_channel(s, actor, channel), requirement='manage_connections')
        local = datetime.fromtimestamp((now // 60 + 3) * 60, timezone.utc).strftime('%Y-%m-%dT%H:%M')
        snapshot = service.repository.get(a['workspace'], a['token'])
        state = service.repository.mutate(a['workspace'], a['token'], snapshot['revision'], 'p2_review',
                                          {'variantId': variant['id'], 'channelId': channel['id'], 'localTime': local,
                                           'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']})['state']
        review = state['phase2']['reviews'][-1]
        RECORD['review'] = review['status']
        snapshot = service.repository.get(a['workspace'], a['token'])
        try:
            service.repository.mutate(a['workspace'], a['token'], snapshot['revision'], 'p2_approve',
                                      {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
        except AlphaError as error:
            RECORD['approvalRefused'] = str(error)
        RECORD['afterApproval'] = jobs_of(a)

if 'command' in phases and a:
    with phase('command'):
        act(a, 'runtime', selected='deterministic-preview')
        RECORD['afterCommand'] = jobs_of(a)

if 'tick' in phases and a:
    with phase('tick') as record:
        social = HostedSocial(service.oauth, providers)
        due = time.time() + 600
        result = PostgresWorker(factory, social=social, clock=lambda: due, worker_id='rc2-worker').tick()
        RECORD['tick'] = {'processed': result.get('processed')}
        RECORD['afterTick'] = jobs_of(a)

if 'channels' in phases:
    with phase('channels'):
        RECORD['channels'] = []
        for person in handoff['people']:
            counted = _phase()
            before = {'verifications': counted['verifications'], 'connections': counted['connections'],
                      'statements': len(counted['statements'])}
            listing = service.oauth.channels(person['workspace'], person['token'])
            RECORD['channels'].append({
                'verifications': counted['verifications'] - before['verifications'],
                'connections': counted['connections'] - before['connections'],
                'transactions': sum(s.startswith('SELECT w.revision,w.state') for s in counted['statements'][before['statements']:]),
                'statements': len(counted['statements']) - before['statements'],
                'channels': [c.get('platform') for c in listing['channels']],
                'keys': sorted(listing), 'discordIdentities': listing.get('discordIdentities')})

with open(args.handoff, 'w') as out:
    json.dump(handoff, out)
for name, record in RECORD['phases'].items():
    record['statementCount'] = len(record.pop('statements'))
print(json.dumps(RECORD, sort_keys=True, default=str))
