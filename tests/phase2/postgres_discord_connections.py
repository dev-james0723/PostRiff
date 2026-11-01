"""Approved-cloud-only P0 plus P1/P2 SQL gates in one disposable cluster."""
import json
import os
import runpy
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the separately approved cloud disposable PostgreSQL harness.')
root = Path(__file__).resolve().parents[2]
# Execute the existing P0 suite ONCE, unchanged, then reuse its guarded fixture helpers.
base = runpy.run_path(str(Path(__file__).with_name('postgres_discord_authorization.py')))
connection, verify, tokens, now = (base[k] for k in ('connection', 'verify', 'TOKENS', 'NOW'))
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from test_discord_oauth_lifecycle import LifecycleWire, APP, USER, GUILD, SECOND_GUILD
from test_discord_publish_authorization import FIRST


def denied(action):
    try:
        action()
    except AlphaError:
        return
    raise AssertionError('Expected a denied authorization boundary')


user, token = str(uuid4()), uuid4().hex
tokens[token] = user
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
wire = LifecycleWire()
provider = base['DiscordProvider'](APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=wire, production_reviewed=True)
provider.authorization_v2_enabled = provider.connections_v2_enabled = True
service = HostedWorkspaceService(connection, verify, clock=lambda: now,
    vault=CredentialVault(CredentialVault.generate_key()), providers={'discord': provider}, public_base_url='https://rafii.example.invalid')
workspace = service.bootstrap(token, 'studio')['workspaceId']; oauth = service.oauth
checks = []


def start(purpose, **inputs):
    value = oauth.start(workspace, token, 'discord', 'identity' if purpose == 'identity' else 'publish',
                        {'discordPurpose': purpose, **inputs})
    return parse_qs(urlsplit(value['authorizeUrl']).query)['state'][0]


state = start('identity', discoverGuilds=True)
identity = oauth.complete(workspace, token, 'discord', state, 'identity-code')['connectionId']
denied(lambda: oauth.complete(workspace, token, 'discord', state, 'identity-code'))
public = oauth.channels(workspace, token)
assert len(public['discordIdentities']) == 1 and not public['channels']
assert 'synthetic-access' not in json.dumps(public)
checks.append('identity grant encrypted, separate from publishing account, replay denied')

calls = len(wire.lifecycle_calls)
denied(lambda: oauth.discord_grant_for_worker(workspace, identity))
assert len(wire.lifecycle_calls) == calls
checks.append('identity credential cannot dispatch or enter bot transport')

guilds = oauth.discord_connections.guilds(workspace, token, identity)['guilds']
assert {x['id'] for x in guilds} == {GUILD, SECOND_GUILD}
installs = []
for guild in (GUILD, SECOND_GUILD):
    state = start('installation', identityConnectionId=identity, guildId=guild)
    installed = oauth.complete(workspace, token, 'discord', state, 'install-' + guild)['connectionId']
    installs.append(installed)
    oauth.choose_destination(workspace, token, installed, FIRST)
assert len(set(installs)) == 2
snap = service.repository.get(workspace, token)
assert {x['discordDestinations'][0]['guildId'] for x in snap['state']['phase2']['channels']} == {GUILD, SECOND_GUILD}
checks.append('two guilds use durable independent installations and exact destinations')

with connection() as db:
    generation = db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (workspace, identity)).fetchone()[0]
    db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s', (now - 1, workspace, identity))
grant = oauth.discord_grant_for_worker(workspace, installs[0])
assert grant['provider'] == 'discord' and wire.refresh_count == 1
with connection() as db:
    assert db.execute('SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (workspace, identity)).fetchone()[0] == generation
checks.append('worker preflight refresh is outside final locks and preserves consent generation')

denied(lambda: start('installation', identityConnectionId=identity, guildId='999888'))
state = start('installation', identityConnectionId=identity, guildId=GUILD, connectionId=installs[0])
wire.install_guild = SECOND_GUILD
denied(lambda: oauth.complete(workspace, token, 'discord', state, 'install-' + GUILD))
wire.install_guild = None
denied(lambda: oauth.complete(workspace, token, 'discord', state, 'install-' + GUILD))
checks.append('unmanaged/wrong guild callback denied, failed exchange state remains consumed')

# Same workspace serializes the new installation -> identity read against reconnect.
state = start('installation', identityConnectionId=identity, guildId=GUILD, connectionId=installs[0])
barrier = Barrier(2)
def concurrent_read():
    barrier.wait(timeout=10)
    return oauth.discord_grant_for_worker(workspace, installs[0])
def concurrent_reconnect():
    barrier.wait(timeout=10)
    return oauth.complete(workspace, token, 'discord', state, 'install-' + GUILD)
with ThreadPoolExecutor(max_workers=2) as workers:
    reader, reconnect = workers.submit(concurrent_read), workers.submit(concurrent_reconnect)
    assert reader.result(timeout=20)['provider'] == 'discord'
    assert reconnect.result(timeout=20)['connected'] is True
checks.append('concurrent credential read and installation reconnect complete without lock collision')

pending_install = start('installation', identityConnectionId=identity, guildId=GUILD, connectionId=installs[0])
oauth.disconnect(workspace, token, installs[0])
denied(lambda: oauth.complete(workspace, token, 'discord', pending_install, 'install-' + GUILD))
assert next(x for x in service.repository.get(workspace, token)['state']['phase2']['channels'] if x['id'] == installs[0])['revoked']
fresh_install = start('installation', identityConnectionId=identity, guildId=GUILD, connectionId=installs[0])
assert oauth.complete(workspace, token, 'discord', fresh_install, 'install-' + GUILD)['connected']
checks.append('late pre-disconnect installation completion denied; explicitly started reconnect accepted')

# A stale application session cannot revoke identity even if it can list connections.
original_auth_time = verify.auth_time
try:
    verify.auth_time = lambda token, principal: now - 86400
    denied(lambda: oauth.discord_connections.disconnect_identity(workspace, token, identity))
finally:
    verify.auth_time = original_auth_time
assert oauth.channels(workspace, token)['discordIdentities'][0]['status'] == 'linked'
denied(lambda: oauth.disconnect(workspace, token, identity))
checks.append('fresh-auth gate and generic disconnect purpose guard preserve owned identity')

wire.identity_revoked = True
calls = wire.refresh_count
denied(lambda: oauth.discord_grant_for_worker(workspace, installs[0]))
assert wire.refresh_count == calls
assert oauth.channels(workspace, token)['discordIdentities'][0]['status'] == 'reconnect_required'
wire.identity_revoked = False
checks.append('unexpired remotely revoked identity blocks bot dispatch without refresh retry')

foreign_user, foreign_token = str(uuid4()), uuid4().hex
tokens[foreign_token] = foreign_user
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (foreign_user,))
foreign_workspace = service.bootstrap(foreign_token, 'studio')['workspaceId']
denied(lambda: oauth.discord_connections.guilds(foreign_workspace, foreign_token, identity))
denied(lambda: oauth.discord_connections.disconnect_identity(workspace, foreign_token, identity))
checks.append('foreign tenant/member cannot discover or disconnect identity')

state = start('identity', discoverGuilds=True, connectionId=identity)
oauth.complete(workspace, token, 'discord', state, 'identity-reconnect')
snap = service.repository.get(workspace, token)
assert all(x['revoked'] and all(d['status'] == 'revoked' for d in x['discordDestinations']) for x in snap['state']['phase2']['channels'])
denied(lambda: oauth.discord_grant_for_worker(workspace, installs[0]))
assert not any(method == 'DELETE' for method, _ in wire.lifecycle_calls)
checks.append('identity reconnect rotates authority and holds dependent installations without bot removal')

pending = start('identity', discoverGuilds=True, connectionId=identity)
oauth.discord_connections.disconnect_identity(workspace, token, identity)
denied(lambda: oauth.complete(workspace, token, 'discord', pending, 'identity-pre-disconnect'))
checks.append('late pre-disconnect OAuth completion cannot restore withdrawn identity')
with connection() as db:
    row = db.execute('SELECT access_ciphertext,refresh_ciphertext,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (workspace, identity)).fetchone()
    assert row == ('', None, True)
assert not any(method == 'DELETE' for method, _ in wire.lifecycle_calls)
checks.append('local disconnect destroys workspace credential access and preserves shared bot')
print('RAFII_DISCORD_CONNECTIONS_SQL_JSON ' + json.dumps({'status': 'PASS', 'execution': 'disposable-postgres-synthetic-provider', 'checks': checks, 'realDiscordAcceptance': 'NOT_RUN'}))
