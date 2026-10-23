"""One customer scenario run against one source tree and one disposable database; prints a JSON record.

Used by tests/test_customer_impact_shared_paths.py, which runs it once with the live tree and once with the candidate
tree, each against its own copy of the same database, and compares the records. It is executed as a script with the
tree under test first on sys.path, so every postriff_phase2 import below is that tree's code.

Phases, all with synthetic users and sessions (no Supabase, no provider, no network):
  bootstrap  three people sign in for the first time (HostedWorkspaceService.bootstrap)
  prepare    one of them sets up a LinkedIn post and approves it (ordinary hosted commands)
  read       workspace read (service.get) and Channels read (oauth.channels) for every workspace
  tick       one minute tick of the hosted worker after the post is due
  shard      W-02 trees only: one /api/cron/discord-worker shard invocation with the lane flag off, then on
  surface    every Discord entry point, called by a member of a workspace with no Discord history
Each phase records the database connections opened, every SQL statement (normalised), the statements that write and
the table they write, the row count of every public table before and after, and any provider HTTP request attempted.
"""
import argparse
import base64
import contextlib
import copy
import json
import os
import re
import sys
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--tree', required=True)
parser.add_argument('--dsn', required=True)
parser.add_argument('--phases', default='bootstrap,prepare,read,tick,shard,surface')
args = parser.parse_args()
sys.path.insert(0, os.path.join(args.tree, 'src'))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.hosted_worker import PostgresWorker  # noqa: E402
from postriff_phase2.oauth import CredentialVault  # noqa: E402
from postriff_phase2 import providers as provider_registry  # noqa: E402

RECORD = {'phases': {}, 'errors': []}
CURRENT = {'phase': None}
HTTP = []


def _shape(sql):
    text = ' '.join(str(sql).split())
    text = re.sub(r"'[^']*'", "'?'", text)
    return text[:600]


def _writes(sql):
    match = re.match(r'\s*(?:WITH\b.*?\)\s*)?(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Za-z0-9_."]+)', str(sql), re.I | re.S)
    return match.group(2).replace('"', '').replace('public.', '') if match else None


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None, **kwargs):
        phase = RECORD['phases'].setdefault(CURRENT['phase'], {'connections': 0, 'statements': [], 'writes': []})
        phase['statements'].append(_shape(sql))
        table = _writes(sql)
        if table:
            phase['writes'].append(table)
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
    phase = RECORD['phases'].setdefault(CURRENT['phase'], {'connections': 0, 'statements': [], 'writes': []})
    phase['connections'] += 1
    return Connection(psycopg.connect(args.dsn, client_encoding='utf8', prepare_threshold=None, connect_timeout=5))


def counts():
    with psycopg.connect(args.dsn, autocommit=True) as db:
        tables = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1").fetchall()]
        return {t: db.execute('SELECT count(*) FROM public.%s' % t).fetchone()[0] for t in tables}


@contextlib.contextmanager
def phase(name):
    CURRENT['phase'] = name
    before = counts()
    record = RECORD['phases'].setdefault(name, {'connections': 0, 'statements': [], 'writes': []})
    try:
        yield record
    except Exception as error:  # record and continue: a refusal is part of the observable behaviour
        RECORD['errors'].append({'phase': name, 'error': type(error).__name__, 'message': str(error)[:300]})
    finally:
        CURRENT['phase'] = None
        after = counts()
        record['rowsChanged'] = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
        record['http'] = list(HTTP)
        HTTP.clear()


def refuse_http(method, url, **kwargs):
    HTTP.append({'method': method, 'host': re.sub(r'^https?://([^/]+).*$', r'\1', url)})
    raise AlphaError('Provider HTTP is disabled in this scenario.', 503)


TOKENS = {}


def verify(token):
    if token not in TOKENS:
        raise AlphaError('Synthetic session required.', 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: 'synthetic-' + token[:12]
verify.auth_time = lambda token, principal: time.time()


# Production's provider configuration, with fake credentials: Discord is mounted with the four v2 flags and the policy.
ENV = {'POSTRIFF_PUBLIC_BASE_URL': 'https://app.impact.invalid', 'VERCEL_ENV': 'production',
       'POSTRIFF_OAUTH_DISCORD_CLIENT_ID': '123456789012345678',
       'POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET': 'synthetic-discord-client-secret-0001',
       'POSTRIFF_DISCORD_BOT_TOKEN': 'synthetic-discord-bot-token-000000000001',
       'POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED': 'true', 'POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED': 'true',
       'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true',
       'POSTRIFF_WORKER_MAX_JOBS': '25', 'POSTRIFF_WORKER_MAX_SECONDS': '40',
       'POSTRIFF_DISCORD_RATE_POLICY': os.environ.get('IMPACT_RATE_POLICY', '')}
os.environ.update(ENV)
providers = provider_registry.registry_from_environment(dict(os.environ))
for adapter in providers.values():
    adapter.transport = refuse_http
discord = providers.get('discord')
if discord is not None and getattr(discord, 'rate_v1_enabled', False):
    # The hosted runtime attaches the shared coordinator the same way (hosted_app.runtime_from_environment).
    from postriff_phase2.discord.rate_limits import SharedPostgresBudget
    discord.rate_limiter = SharedPostgresBudget(factory, discord.client_id)
service = HostedWorkspaceService(factory, verify, clock=time.time, vault=CredentialVault(CredentialVault.generate_key()),
                                 providers=providers, public_base_url='https://app.impact.invalid')
RECORD['discordMounted'] = discord is not None
RECORD['discordConnectionsV2'] = bool(getattr(discord, 'connections_v2_enabled', False))

people = []
phases = args.phases.split(',')
if 'bootstrap' in phases:
    with phase('bootstrap'):
        for index in range(3):
            user, token = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'impact-user-%d.example.invalid' % index)), 'synthetic-session-%d-%s' % (index, 'x' * 24)
            TOKENS[token] = user
            with psycopg.connect(args.dsn, autocommit=True) as db:
                db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (user,))
            people.append({'user': user, 'token': token, 'workspace': service.bootstrap(token, 'studio')['workspaceId']})
    RECORD['workspaces'] = len(people)

if 'prepare' in phases and people:
    owner = people[0]
    with phase('prepare'):
        def act(action, **payload):
            snapshot = service.repository.get(owner['workspace'], owner['token'])
            return service.mutate(owner['workspace'], owner['token'], snapshot['revision'], action, payload)
        act('mode', mode='personal')
        act('context', purpose='Make community learning accessible', audience='Curious beginners', subject='Community workshops', speaker='My voice', layers=[])
        state = act('source', kind='sample')['state']
        source = state['sources'][-1]
        act('approve_source', sourceId=source['id'], factIds=[f['id'] for f in source['facts']])
        act('source_done')
        act('profile_propose', writing='A small step can be a useful beginning.', tone='warm')
        act('profile_decide', decision='approve')
        act('runtime', selected='deterministic-preview')
        state = act('generate', platform='LinkedIn', language='English')['state']
        variant = state['variants'][-1]
        act('p2_variant_review', variantId=variant['id'], variantRevision=variant['revision'], confirmed=True, excludedUnknowns=variant['unknowns'])
        now = time.time()
        channel = {'id': 'linkedin-impact-1', 'platform': 'LinkedIn', 'account': 'Impact Member', 'accountType': 'member',
                   'scopes': ['openid', 'profile', 'w_member_social'], 'verifiedAt': now, 'expiresAt': now + 86400 * 30,
                   'capabilityVersion': 1, 'providerAccountId': 'impact-member-1', 'language': 'English'}
        snapshot = service.repository.get(owner['workspace'], owner['token'])
        service.repository.command(owner['workspace'], owner['token'], snapshot['revision'],
                                   lambda s, actor: service.commands.upsert_verified_channel(s, actor, channel), requirement='manage_connections')
        from datetime import datetime, timezone
        local = datetime.fromtimestamp((now // 60 + 3) * 60, timezone.utc).strftime('%Y-%m-%dT%H:%M')
        snapshot = service.repository.get(owner['workspace'], owner['token'])
        # The hosted route refreshes provider grants for p2_review/p2_approve; the trusted repository path does not.
        state = service.repository.mutate(owner['workspace'], owner['token'], snapshot['revision'], 'p2_review',
                                          {'variantId': variant['id'], 'channelId': channel['id'], 'localTime': local,
                                           'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']})['state']
        review = state['phase2']['reviews'][-1]
        snapshot = service.repository.get(owner['workspace'], owner['token'])
        state = service.repository.mutate(owner['workspace'], owner['token'], snapshot['revision'], 'p2_approve',
                                          {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})['state']
        RECORD['prepared'] = {'reviewStatus': state['phase2']['reviews'][-1]['status'],
                              'jobState': state['phase2']['jobs'][-1]['state'] if state['phase2']['jobs'] else None}
    # The stored state (synthetic content only) and its revision, for tests/impact_state_probe.py.
    with psycopg.connect(args.dsn, autocommit=True) as db:
        revision, stored = db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (owner['workspace'],)).fetchone()
    RECORD['ownerState'] = {'revision': revision, 'state': stored, 'principal': owner['user']}

if 'read' in phases:
    with phase('read'):
        reads = []
        for person in people:
            shown = service.get(person['workspace'], person['token'])
            listing = service.oauth.channels(person['workspace'], person['token'])
            discord_entry = next((p for p in listing['providers'] if p.get('id') == 'discord'), {})
            reads.append({'topLevelKeys': sorted(shown), 'stateKeys': sorted(shown['state']),
                          'phase2Keys': sorted(shown['state'].get('phase2', {})),
                          'listingKeys': sorted(listing), 'channels': [c.get('platform') for c in listing['channels']],
                          'discordIdentities': listing.get('discordIdentities'),
                          'discordEntry': {k: discord_entry.get(k) for k in ('connectReady', 'discordAccess', 'discordConnectionsV2')}})
        RECORD['reads'] = reads

if 'tick' in phases:
    with phase('tick'):
        social = HostedSocial(service.oauth, providers)
        due = time.time() + 600
        worker = PostgresWorker(factory, social=social, clock=lambda: due, worker_id='impact-worker')
        result = worker.tick()
        RECORD['tick'] = {'processed': result.get('processed'), 'budget': result.get('budget'),
                          'keys': sorted(result), 'discordWorker': result.get('discordWorker')}
        with psycopg.connect(args.dsn, autocommit=True) as db:
            rows = db.execute("SELECT state FROM public.pr_workspaces WHERE state ? 'phase2' ORDER BY id").fetchall()
        RECORD['jobsAfterTick'] = [{'platform': j['manifest']['platform'], 'state': j['state'],
                                    'events': [e.get('message') for e in j.get('events', [])]}
                                   for (s,) in rows for j in s['phase2'].get('jobs', [])]
        RECORD['phase2KeysAfterTick'] = sorted({k for (s,) in rows for k in s.get('phase2', {})})

if 'shard' in phases:
    # W-02 (RC2 and later): one cron shard invocation with the lane flag off, then on, with no Discord work anywhere.
    try:
        from postriff_phase2.discord import lane
    except ImportError:
        lane = None
    RECORD['laneAvailable'] = lane is not None
    if lane is not None:
        social = HostedSocial(service.oauth, providers)
        worker = PostgresWorker(factory, social=social, clock=time.time, worker_id='impact-minute-worker')
        for flag in ('off', 'on'):
            values = {**os.environ, **({'POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED': 'true'} if flag == 'on' else {})}
            with phase('shard-' + flag):
                result = lane.run(worker, 0, values=values)
                RECORD['shard-' + flag] = {'enabled': result.get('enabled'), 'processed': result.get('processed'),
                                           'stoppedBy': result.get('stoppedBy'), 'status': result.get('status')}

if 'surface' in phases and len(people) > 1:
    # Every Discord entry point a signed-in member of an ordinary workspace (no Discord history) can reach, with the gate
    # unset on production. Each call's outcome is recorded; the phase records any write and any provider request.
    person = people[1]
    ws, tok = person['workspace'], person['token']
    calls = {
        'oauth.start publish': lambda: service.oauth.start(ws, tok, 'discord', 'publish'),
        'oauth.start identity': lambda: service.oauth.start(ws, tok, 'discord', 'identity'),
        'oauth.complete': lambda: service.oauth.complete(ws, tok, 'discord', 's' * 43, 'synthetic-code'),
        'identities.guilds': lambda: service.oauth.discord_connections.guilds(ws, tok, 'discord-identity-impact'),
        'identities.disconnect': lambda: service.oauth.discord_connections.disconnect_identity(ws, tok, 'discord-identity-impact'),
        'channels.destinations': lambda: service.oauth.destinations(ws, tok, 'discord-impact-channel'),
        'channels.remove_destination': lambda: service.oauth.remove_discord_destination(ws, tok, 'discord-impact-channel', 'destination-x'),
        'engagement.status': lambda: service.discord_engagement.status(ws, tok, 'discord-impact-channel'),
        'jobs.execute': lambda: PostgresWorker(factory, social=HostedSocial(service.oauth, providers)).execute_job(service.repository, ws, tok, 'job-impact', 'a' * 64),
    }
    try:
        from postriff_phase2.discord.interactions import DiscordInteractions
        endpoint = DiscordInteractions(providers.get('discord'), factory, 'https://app.impact.invalid')
        calls.update({
            'interactions.review_entry': lambda: endpoint.review_entry(service.oauth.discord_connections, ws, tok, 'discord-identity-impact'),
            'interactions.bind': lambda: endpoint.bind(service.oauth.discord_connections, ws, tok, 'discord-identity-impact'),
            'interactions.receive': lambda: endpoint.receive(b'{"type":1}', str(int(time.time())), '0' * 128),
        })
    except ImportError:
        pass
    outcomes = {}
    with phase('surface'):
        for name, call in calls.items():
            try:
                value = call()
                outcomes[name] = {'outcome': 'answered', 'keys': sorted(value) if isinstance(value, dict) else type(value).__name__}
            except AlphaError as error:
                outcomes[name] = {'outcome': 'refused', 'status': error.status, 'code': getattr(error, 'code', None)}
            except AttributeError:
                outcomes[name] = {'outcome': 'absent'}
            except Exception as error:  # noqa: BLE001 - record the class only
                outcomes[name] = {'outcome': 'error', 'error': type(error).__name__}
    RECORD['surface'] = outcomes

print(json.dumps(RECORD, sort_keys=True, default=str))
