"""Cloud-only real-PostgreSQL proofs for the G2E-A/C custody fixes (disposable cluster, synthetic Discord).

Run: CI=true RAFII_DISCORD_SYNTHETIC_FENCE=1 POSTRIFF_PG_BIN=<bin> python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_custody.py

Each scenario runs alone and records its own checks, so one failure does not hide the others. Covers: the authorizer is
checked before any Discord request (A-02), a member who is gone leaves no live credential (A-03), a stale claim and an
ambiguous refresh suspend instead of destroy and the servers come back on relink (A-01/A-04), reads are throttled before
Discord (A-05), mixed flags fail closed (A-08), the pool restores transactional mode (A-09), and the SQL conditions of the
authorizer guard (A-06).
"""
import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the approved cloud disposable-PostgreSQL harness.')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import launch_gate
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_oauth_lifecycle import LifecycleWire, APP, USER, GUILD, SECOND_GUILD
from test_discord_publish_authorization import FIRST

DSN = 'host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
TOKENS, CHECKS = {}, []


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert (db.info.host, db.info.port, db.info.dbname, db.info.user) == ('127.0.0.1', 55438, 'postgres', 'postriff_test')
        yield db


with connection() as db:
    NOW = int(db.execute('SELECT extract(epoch from now())').fetchone()[0]) // 60 * 60


def verify(token):
    if token not in TOKENS:
        raise AlphaError('Synthetic session required.', 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: 'synthetic-' + token
verify.auth_time = lambda token, principal: NOW


def new_user():
    user, token = str(uuid4()), uuid4().hex
    TOKENS[token] = user
    with connection() as db:
        db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
    return user, token


def check(name, ok, detail=None):
    CHECKS.append((name, bool(ok), detail))
    print(('OK   ' if ok else 'FAIL ') + name + ('' if ok else f' => {detail!r}'), flush=True)


def refused(call):
    try:
        call()
    except AlphaError as error:
        return error
    return None


class World:
    """A fresh workspace with an owner, a service over the synthetic wire and helpers to add members."""

    def __init__(self, flags=(True, True)):
        self.wire = LifecycleWire()
        self.provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=self.wire, production_reviewed=True)
        self.provider.authorization_v2_enabled, self.provider.connections_v2_enabled = flags
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: NOW, vault=CredentialVault(CredentialVault.generate_key()),
                                              providers={'discord': self.provider}, public_base_url='https://rafii.example.invalid')
        self.owner, self.owner_token = new_user()
        self.workspace = self.service.bootstrap(self.owner_token, 'studio')['workspaceId']
        self.oauth = self.service.oauth

    def member(self, role='admin'):
        user, token = new_user()
        with connection() as db:
            db.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (user,))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active')", (self.workspace, user, role))
        return user, token

    def start(self, token, purpose, **inputs):
        value = self.oauth.start(self.workspace, token, 'discord', 'identity' if purpose == 'identity' else 'publish', {'discordPurpose': purpose, **inputs})
        return parse_qs(urlsplit(value['authorizeUrl']).query)['state'][0]

    def link(self, token, guild=GUILD, destination=True):
        identity = self.oauth.complete(self.workspace, token, 'discord', self.start(token, 'identity', discoverGuilds=True), 'identity-code')['connectionId']
        install = self.oauth.complete(self.workspace, token, 'discord', self.start(token, 'installation', identityConnectionId=identity, guildId=guild), 'install-' + guild)['connectionId']
        if destination:
            self.oauth.choose_destination(self.workspace, token, install, FIRST)
        return identity, install

    def credential(self, connection_id):
        with connection() as db:
            return db.execute("SELECT revoked_at IS NOT NULL, access_ciphertext='', refresh_ciphertext IS NULL, authorization_generation::text, "
                              "extract(epoch from rotated_at) FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s",
                              (self.workspace, connection_id)).fetchone()

    def state(self):
        with connection() as db:
            return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]

    def identity_record(self, identity):
        return next(x for x in self.state()['phase2']['discordIdentityLinks'] if x['id'] == identity)

    def card(self, install):
        return next(c for c in self.state()['phase2']['channels'] if c['id'] == install)

    def expire(self, connection_id):
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s',
                       (NOW - 5, self.workspace, connection_id))

    def sql(self, statement, *params):
        with connection() as db:
            db.execute(statement, params)


def scenario(function):
    print(f'--- {function.__name__}', flush=True)
    try:
        function()
    except Exception:
        check(function.__name__ + ' ran to the end', False, traceback.format_exc()[-600:])
    return function


@scenario
def a02_the_authorizer_is_checked_before_any_discord_request():
    w = World()
    _, install = w.link(w.owner_token)
    admin, admin_token = w.member('admin')
    admin_identity, admin_install = w.link(admin_token, SECOND_GUILD, destination=False)
    w.oauth.choose_destination(w.workspace, w.owner_token, admin_install, FIRST)
    w.expire(admin_identity)
    before = w.credential(admin_identity)
    w.sql("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", w.workspace, admin)  # direct SQL: no hook
    calls, refreshes = len(w.wire.lifecycle_calls), w.wire.refresh_count
    error = refused(lambda: w.oauth.discord_grant_for_worker(w.workspace, admin_install))
    check('A-02 control: the worker grant of a removed authorizer is refused', error is not None, str(error))
    check('A-02 control: ... without a single Discord request', len(w.wire.lifecycle_calls) == calls, w.wire.lifecycle_calls[calls:])
    result = w.oauth.reverify_for_worker(w.workspace, admin_install)
    check('A-02 reverify_for_worker for the removed authorizer answers reauthorization_required', result['state'] == 'reauthorization_required' and not result['ready'], result)
    check('A-02 ... and made NO Discord request (no rotating refresh, no bot read)', len(w.wire.lifecycle_calls) == calls and w.wire.refresh_count == refreshes, w.wire.lifecycle_calls[calls:])
    check('A-02 ... and the removed member credential was not rotated', w.credential(admin_identity)[4] == before[4], (before, w.credential(admin_identity)))
    card = w.card(admin_install)
    check('A-02 the card is flipped (not revoked) and flagged once', not card['capabilityVerified'] and card.get('discordAuthorizerGone') is True and not card['revoked'], {k: card.get(k) for k in ('capabilityVerified', 'discordAuthorizerGone', 'revoked')})
    generation, revision = card.get('discordVerificationGeneration'), w.service.repository.get(w.workspace, w.owner_token)['revision']
    w.oauth.reverify_for_worker(w.workspace, admin_install)
    again = w.service.repository.get(w.workspace, w.owner_token)
    check('A-02 a second pass changes nothing (flipped once)', again['revision'] == revision and w.card(admin_install).get('discordVerificationGeneration') == generation, (revision, again['revision']))
    check('A-02 the owner installation is unaffected', w.oauth.reverify_for_worker(w.workspace, install)['state'] != 'reauthorization_required')


@scenario
def a03_a_member_who_is_gone_leaves_no_live_credential():
    def case(how):
        w = World()
        user, token = w.member('admin')
        identity, install = w.link(token, destination=False)
        if how == 'removed':
            w.service.remove_member(w.workspace, w.owner_token, user)
        elif how == 'left':
            w.service.leave_workspace(w.workspace, token)
        elif how == 'downgraded':
            w.service.update_member(w.workspace, w.owner_token, user, 'viewer', {})
        elif how == 'kept':
            w.service.update_member(w.workspace, w.owner_token, user, 'editor', {'can_manage_connections': True})
        return w, identity, install
    for how in ('removed', 'left', 'downgraded'):
        w, identity, install = case(how)
        identity_credential, install_credential = w.credential(identity), w.credential(install)
        check(f'A-03 {how}: identity credential revoked, access and refresh ciphertext emptied', identity_credential[:3] == (True, True, True), identity_credential)
        check(f'A-03 {how}: the installation credential is revoked and emptied', install_credential[:2] == (True, True), install_credential)
        check(f'A-03 {how}: the identity record says disconnected and the card is revoked', w.identity_record(identity)['status'] == 'disconnected' and w.card(install)['revoked'] is True, w.identity_record(identity))
    w, identity, install = case('kept')
    check('A-03 control: a member who keeps manage_connections keeps everything', w.credential(identity)[:3] == (False, False, False)
          and w.identity_record(identity)['status'] == 'linked' and not w.card(install)['revoked'], w.credential(identity))
    # records created before the fix: the authorizer is gone and nothing disconnected their identity
    w = World()
    ghost, ghost_token = w.member('admin')
    ghost_identity, ghost_install = w.link(ghost_token, GUILD, destination=False)
    active, active_token = w.member('admin')
    active_identity, _ = w.link(active_token, SECOND_GUILD, destination=False)
    w.sql("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", w.workspace, ghost)
    error = refused(lambda: w.oauth.discord_connections.disconnect_identity(w.workspace, w.owner_token, active_identity))
    check("A-03 an owner still cannot disconnect an ACTIVE member's identity", error is not None and error.status == 404, str(error))
    w.oauth.discord_connections.disconnect_identity(w.workspace, w.owner_token, ghost_identity)
    check('A-03 an owner can disconnect the identity of a member who is no longer active', w.credential(ghost_identity)[:3] == (True, True, True) and w.card(ghost_install)['revoked'] is True, w.credential(ghost_identity))
    # account deletion needs no hook: a profile that still has a membership elsewhere cannot be deleted (unconditional FK)
    blocked = None
    try:
        with connection() as db:
            db.execute('DELETE FROM public.pr_profiles WHERE user_id=%s', (active,))
    except psycopg.errors.ForeignKeyViolation as error:
        blocked = error
    check('A-03 account deletion: a person who still belongs to another workspace cannot complete deletion (FK), so leave_workspace is the only way out', blocked is not None)


@scenario
def a06_the_sql_conditions_of_the_authorizer_guard():
    w = World()
    admin, admin_token = w.member('admin')
    identity, install = w.link(admin_token, destination=False)
    w.oauth.choose_destination(w.workspace, w.owner_token, install, FIRST)
    check('A-06 baseline: an active admin authorizer gets a worker grant', w.oauth.discord_grant_for_worker(w.workspace, install)['provider'] == 'discord')
    for label, break_it, mend_it in (
            ("m.status = 'active'", "UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", "UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s AND user_id=%s"),
            ('p.deleted_at IS NULL', "UPDATE public.pr_profiles SET deleted_at=now() WHERE user_id=%s", "UPDATE public.pr_profiles SET deleted_at=NULL WHERE user_id=%s"),
            ('manage_connections (role below admin)', "UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", "UPDATE public.pr_memberships SET role='admin' WHERE workspace_id=%s AND user_id=%s")):
        params = (admin,) if 'profiles' in break_it else (w.workspace, admin)
        w.sql(break_it, *params)
        calls = len(w.wire.lifecycle_calls)
        error = refused(lambda: w.oauth.discord_grant_for_worker(w.workspace, install))
        check(f'A-06 {label}: the grant is refused', error is not None, str(error))
        check(f'A-06 {label}: ... before any Discord request', len(w.wire.lifecycle_calls) == calls)
        w.sql(mend_it, *params)
        check(f'A-06 {label}: restored, the grant works again', w.oauth.discord_grant_for_worker(w.workspace, install)['provider'] == 'discord')


@scenario
def a01_a04_an_ambiguous_refresh_suspends_and_the_same_user_brings_the_servers_back():
    w = World()
    identity, install = w.link(w.owner_token)
    installation_credential = w.credential(install)
    before = w.identity_record(identity)
    # a 502 on the rotating refresh: ambiguous
    w.expire(identity)
    w.wire.route_overrides[('POST', '/oauth2/token')] = {'status': 502, 'headers': {'content-type': 'text/html', 'cf-ray': 'x'}, 'body': {'raw': '<html>Bad gateway</html>'}}
    error = refused(lambda: w.oauth.discord_connections.guilds(w.workspace, w.owner_token, identity))
    record, card = w.identity_record(identity), w.card(install)
    check('A-01 an ambiguous refresh closes the identity visibly', error is not None and record['status'] == 'reconnect_required' and record.get('dependentsSuspended') is True and 'refreshClaim' not in record, record)
    check('A-01 ... but the server is suspended, not destroyed', not card['revoked'] and card.get('discordSuspended') is True and not card['capabilityVerified'] and card['discordDestinations'][0]['status'] == 'authorized', card)
    check('A-01 ... and its credential row is untouched', w.credential(install) == installation_credential, (w.credential(install), installation_credential))
    # nothing can use it meanwhile
    check('A-01 a suspended installation cannot produce a worker grant', refused(lambda: w.oauth.discord_grant_for_worker(w.workspace, install)) is not None)
    # the same Discord user links again
    w.wire.route_overrides.clear()
    relinked = w.oauth.complete(w.workspace, w.owner_token, 'discord', w.start(w.owner_token, 'identity', discoverGuilds=True), 'identity-code')['connectionId']
    record, card = w.identity_record(identity), w.card(install)
    check('A-01 relinking the same Discord user restores the SAME identity and consent generation', relinked == identity and record['status'] == 'linked' and record['authorizationGeneration'] == before['authorizationGeneration'], (relinked, record))
    check('A-01 ... the server is back (not revoked, unsuspended) and still needs an explicit verification', not card['revoked'] and 'discordSuspended' not in card and card['capabilityVerified'] is False and card['discordDestinations'][0]['status'] == 'authorized', card)
    check('A-01 ... and the installation credential generation is unchanged', w.credential(install)[3] == installation_credential[3])
    grant = refused(lambda: w.oauth.discord_grant_for_worker(w.workspace, install))
    check('A-01 ... a worker grant is possible again', grant is None, str(grant))
    verified = w.oauth.verify(w.workspace, w.owner_token, install)
    check('A-01 ... one explicit Verify makes it ready again', verified['state'] == 'read_verified' and w.card(install)['capabilityVerified'] is True, verified)
    # Discord's own refusal still destroys
    w.expire(identity)
    w.wire.route_overrides[('POST', '/oauth2/token')] = {'status': 400, 'headers': {'content-type': 'application/json'}, 'body': {'error': 'invalid_grant'}}
    refused(lambda: w.oauth.discord_connections.guilds(w.workspace, w.owner_token, identity))
    check("A-01 invalid_grant (Discord's own refusal) still revokes the server and zeroes its credential", w.card(install)['revoked'] is True and w.credential(install)[:2] == (True, True), w.card(install))
    # a stale claim (A-04)
    w2 = World()
    identity2, install2 = w2.link(w2.owner_token)
    state = w2.state()
    record = next(x for x in state['phase2']['discordIdentityLinks'] if x['id'] == identity2)
    record.update(refreshClaim='dead-worker', refreshStartedAt=NOW - 3600)
    w2.sql('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', json.dumps(state), w2.workspace)
    calls = len(w2.wire.lifecycle_calls)
    error = refused(lambda: w2.oauth.discord_connections.guilds(w2.workspace, w2.owner_token, identity2))
    record = w2.identity_record(identity2)
    check('A-04 an hour-old claim is reaped into a persisted reconnect_required, servers suspended, no Discord request',
          error is not None and record['status'] == 'reconnect_required' and 'refreshClaim' not in record and w2.card(install2).get('discordSuspended') is True
          and not w2.card(install2)['revoked'] and len(w2.wire.lifecycle_calls) == calls, record)


@scenario
def a05_reads_are_throttled_before_discord_and_served_from_one_fetch():
    w = World()
    _, install = w.link(w.owner_token)
    channel_reads = lambda: len([c for c in w.wire.lifecycle_calls if c[1] == '/guilds/' + GUILD + '/channels'])
    before = channel_reads()
    for _ in range(28):  # link() already spent two of the thirty allowed in this minute (the installation start and choose_destination)
        w.oauth.destinations(w.workspace, w.owner_token, install)
    check('A-05 twenty-eight channel-list requests make exactly ONE set of Discord reads', channel_reads() - before == 1, channel_reads() - before)
    calls = len(w.wire.lifecycle_calls)
    error = refused(lambda: w.oauth.destinations(w.workspace, w.owner_token, install))
    check('A-05 the thirty-first request of the minute is refused with 429 before any Discord request', error is not None and error.status == 429 and len(w.wire.lifecycle_calls) == calls, str(error))
    with connection() as db:
        rows = db.execute('SELECT count(*) FROM public.pr_auth_throttle').fetchone()[0]
    check('A-05 the counters live in the shared throttle table', rows >= 2, rows)
    viewer, viewer_token = w.member('viewer')
    calls = len(w.wire.lifecycle_calls)
    error = refused(lambda: w.oauth.destinations(w.workspace, viewer_token, install))
    check('A-05 a viewer is refused by role and spends none of the allowance', error is not None and error.status == 403 and len(w.wire.lifecycle_calls) == calls, str(error))
    # a throttled start costs Discord nothing (P10)
    identity = w.oauth.discord_connections.public_identities(w.workspace, w.owner_token)[0]['id']
    with connection() as db:
        db.execute("INSERT INTO public.pr_auth_throttle(bucket,window_start,count) VALUES(encode(sha256(convert_to(%s,'UTF8')),'hex'),now(),20) ON CONFLICT(bucket) DO UPDATE SET count=20,window_start=now()", (f'oauth-start:{w.workspace}',))
    calls = len(w.wire.lifecycle_calls)
    error = refused(lambda: w.start(w.owner_token, 'installation', identityConnectionId=identity, guildId=SECOND_GUILD))
    check('A-05 a start over the oauth-start limit is refused with 429 and costs Discord nothing', error is not None and error.status == 429 and len(w.wire.lifecycle_calls) == calls, (str(error), w.wire.lifecycle_calls[calls:]))


@scenario
def a08_mixed_flags_fail_closed():
    w = World()
    _, install = w.link(w.owner_token)
    w.provider.connections_v2_enabled = False  # AUTHORIZATION_V2 on, CONNECTIONS_V2 mistyped
    for label, call in (('start', lambda: w.oauth.start(w.workspace, w.owner_token, 'discord', 'publish')),
                        ('worker grant', lambda: w.oauth.discord_grant_for_worker(w.workspace, install))):
        calls = len(w.wire.lifecycle_calls)
        error = refused(call)
        check(f'A-08 {label} refused with 503 in the mixed-flag mode', error is not None and error.status == 503 and len(w.wire.lifecycle_calls) == calls, str(error))
    w.provider.connections_v2_enabled = True
    check('A-08 control: with both flags on the worker grant works', w.oauth.discord_grant_for_worker(w.workspace, install)['provider'] == 'discord')


@scenario
def a09_the_pool_restores_transactional_mode():
    from postriff_phase2.postgres_pool import PooledPostgresFactory
    factory = PooledPostgresFactory(DSN, max_size=1, max_waiting=4, timeout=5)
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS public.zz_pool_probe(id int primary key)')
        db.execute('INSERT INTO public.zz_pool_probe VALUES (1) ON CONFLICT DO NOTHING')
    with factory() as db:
        db.autocommit = True  # exactly what account_deletion.delete_account does to its lock connection
    with factory() as db2:
        check('A-09 the next borrower does not inherit autocommit', db2.autocommit is False, db2.autocommit)
        with db2.cursor() as cur:
            cur.execute('SELECT id FROM public.zz_pool_probe WHERE id=1 FOR UPDATE')
            cur.fetchall()
            held = False
            with psycopg.connect(DSN, autocommit=True, options='-c lock_timeout=500') as other:
                try:
                    other.execute('SELECT id FROM public.zz_pool_probe WHERE id=1 FOR UPDATE NOWAIT')
                except psycopg.errors.LockNotAvailable:
                    held = True
            check('A-09 a FOR UPDATE row lock now survives until the transaction ends', held)
    factory.close()


@scenario
def p5_a_reconnect_naming_another_server_takes_no_free_cap_slot():
    saved = {k: os.environ.get(k) for k in ('VERCEL_ENV', launch_gate.ENV_WORKSPACES, launch_gate.ENV_CAP)}
    try:
        w = World()
        identity, card = w.link(w.owner_token)
        os.environ.update({'VERCEL_ENV': 'production', launch_gate.ENV_WORKSPACES: '*', launch_gate.ENV_CAP: '1'})  # the house is full
        fresh = '6000001'  # a server no workspace of this run has ever held a row for (a known one is admitted at any fill)
        w.wire.route_overrides[('GET', '/users/@me/guilds')] = {'status': 200, 'body': [{'id': GUILD, 'name': 'one', 'permissions': '32'}, {'id': fresh, 'name': 'new', 'permissions': '32'}]}
        control = refused(lambda: w.start(w.owner_token, 'installation', identityConnectionId=identity, guildId=fresh))
        check('P5 control: a new server at a full house is refused', control is not None and control.code == 'discord_capacity_reached', str(control))
        forged = refused(lambda: w.start(w.owner_token, 'installation', identityConnectionId=identity, guildId=fresh, connectionId=card))
        check('P5 a reconnect that names the OLD card with a NEW guild id is refused', forged is not None, str(forged))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


PROJECTION_OWNERS = """SELECT 'table ' || c.relname AS object, r.rolname AS owner, r.rolsuper, r.rolbypassrls
  FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
 WHERE c.relnamespace = 'public'::regnamespace AND c.relname = 'pr_discord_worker_projection'
UNION ALL
SELECT 'function ' || p.proname, r.rolname, r.rolsuper, r.rolbypassrls
  FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proname IN ('pr_discord_projection_refresh', 'pr_discord_workspace_projection_trigger')"""
PROJECTION_FUNCTIONS = ('pr_discord_projection_refresh(uuid,jsonb,bigint)', 'pr_discord_queue_number(jsonb)', 'pr_discord_workspace_projection_trigger()')


@scenario
def a10_the_projection_owner_must_bypass_row_level_security():
    """Migration 126's SECURITY DEFINER trigger writes a FORCE-RLS table: the same query as docs/discord-custody-20261023/G2A-NOTES.md."""
    with psycopg.connect(DSN, autocommit=True) as db:  # the harness loads rls.sql only; migration 126 brings its own BEGIN/COMMIT
        if db.execute("SELECT to_regclass('public.pr_discord_worker_projection')").fetchone()[0] is None:
            db.execute((ROOT / 'migrations/postriff/126_discord_worker_projection.sql').read_text())
    with connection() as db:
        rows = db.execute(PROJECTION_OWNERS).fetchall()
    check('A-10 the projection table and both definer functions are owned by a role that bypasses RLS', len(rows) == 3 and all(r[2] or r[3] for r in rows), rows)
    w = World()
    with connection() as db:
        db.execute('DROP ROLE IF EXISTS g2a_nobypass')
        db.execute('CREATE ROLE g2a_nobypass NOLOGIN')
        db.execute('GRANT USAGE ON SCHEMA public TO g2a_nobypass')
        db.execute('ALTER TABLE public.pr_discord_worker_projection OWNER TO g2a_nobypass')
        for function in PROJECTION_FUNCTIONS:
            db.execute(f'ALTER FUNCTION public.{function} OWNER TO g2a_nobypass')
    try:
        with connection() as db:
            flagged = [r for r in db.execute(PROJECTION_OWNERS).fetchall() if not (r[2] or r[3])]
        check('A-10 the diagnostic flags the objects of an owner without BYPASSRLS', len(flagged) == 3, flagged)
        failure = None
        try:
            w.sql('UPDATE public.pr_workspaces SET revision = revision + 1 WHERE id = %s', w.workspace)
        except psycopg.errors.Error as error:
            failure = error
        check('A-10 with such an owner EVERY workspace update fails (what the check guards against)', failure is not None and 'row-level security' in str(failure), str(failure)[:120])
    finally:
        with connection() as db:
            db.execute('ALTER TABLE public.pr_discord_worker_projection OWNER TO postriff_test')
            for function in PROJECTION_FUNCTIONS:
                db.execute(f'ALTER FUNCTION public.{function} OWNER TO postriff_test')
            db.execute('REVOKE USAGE ON SCHEMA public FROM g2a_nobypass')
            db.execute('DROP ROLE g2a_nobypass')
    w.sql('UPDATE public.pr_workspaces SET revision = revision + 1 WHERE id = %s', w.workspace)
    check('A-10 restored, workspace updates work again', True)


failed = [name for name, ok, _ in CHECKS if not ok]
print('RAFII_G2A_CUSTODY_JSON ' + json.dumps({'checks': len(CHECKS), 'failed': failed}))
sys.exit(1 if failed or not CHECKS else 0)
