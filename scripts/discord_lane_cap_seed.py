#!/usr/bin/env python3
"""Seeder for the W-02 capacity harness: workspaces, Discord connections and approved scheduled posts.

Runs in its own process with the tested source tree on sys.path (never the harness's own tree), against the admin
(direct) database connection, and builds every row with the application's own code, the way a person's actions
would, so the worker meets production-shaped data:

  1. the person's account: auth.users, then HostedWorkspaceService.bootstrap (pr_bootstrap: workspace, owner
     membership, profile, trial), so billing.require_publishing passes for real (no billing patch);
  2. the Discord identity link: DiscordConnections.save_identity with a 7-day token (Discord's real lifetime), as
     the OAuth callback stores it after the token exchange;
  3. the server installation: the callback's own guild read and destination check, then
     DiscordConnections.save_installation;
  4. the channel authorization: OAuthService.choose_destination (live permission evidence, register_destination);
  5. each post: a synthetic draft, then the hosted commands p2_review and p2_approve (HostedPhase2Commands, the
     object the repository applies inside its transaction) with the scheduled local time T; the approval's expiry
     is the application's own (scheduled time + 3600 s). The finished state is written once per workspace.

Steps 2 to 4 talk to the deterministic mock world in-process (no HTTP, no latency, not in the run's request log)
through the real DiscordProvider and the real shared request coordinator, under a separate high-capacity seeding
policy, so the coordinator has learned the server routes exactly as production's connect flow would have. The
token exchange itself is not replayed. Every id and text is synthetic.

Output: one JSON line per post (workspace index, workspace id, job id, nonce, due and expiry) for the analysis.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_tree(source_tree):
    source_tree = Path(source_tree).resolve()
    for path in (str(source_tree), str(source_tree / 'src')):
        if path not in sys.path:
            sys.path.insert(0, path)
    # The harness's mock world is the only module taken from the harness directory.
    import importlib.util
    spec = importlib.util.spec_from_file_location('discord_lane_cap_mock', HERE / 'discord_lane_cap_mock.py')
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    return mock


def principal_for(index, run_tag):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'rafii-capacity-harness:%s:user:%d' % (run_tag, index)))


def post_text(index, number, post_id):
    return 'Capacity harness post %d of synthetic workspace %d [cap-post %s]' % (number, index, post_id)


class Seeder:
    def __init__(self, source_tree, admin_dsn, env, *, workspaces_total, run_tag):
        self.mock = load_tree(source_tree)
        import psycopg
        from postriff_phase2.hosted import HostedWorkspaceService
        from postriff_phase2.oauth import CredentialVault
        from postriff_phase2.providers import registry_from_environment
        from postriff_phase2.discord import authorization
        self.psycopg, self.authorization = psycopg, authorization
        self.run_tag = run_tag
        self.world = self.mock.World(workspaces=workspaces_total, read_limit=(1000, 1.0), global_ceiling=10 ** 6,
                                     policy_ceiling=10 ** 6)
        self.transport = self.mock.InProcessTransport(self.world)
        self.env = dict(env)
        providers = registry_from_environment(self.env, transport=self.transport)
        self.provider = providers.get('discord')
        if self.provider is None:
            raise RuntimeError('the Discord provider did not mount from the harness environment')
        self.provider.authorization_v2_enabled = self.env.get('POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED') == 'true'
        self.provider.connections_v2_enabled = self.env.get('POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED') == 'true'
        self.provider.rate_v1_enabled = self.env.get('POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED') == 'true'
        self.read_retries = {}
        if os.environ.get('CAP_SEED_IMPATIENT') != '1':  # '1' only for the negative control in the harness self-checks
            self._patient_reads()
        self.tokens = {}
        dsn = admin_dsn

        def factory():
            return psycopg.connect(dsn, client_encoding='utf8', prepare_threshold=None, connect_timeout=8)
        self.factory = factory

        def verify(token):
            return self.tokens[token]
        verify.session_id = lambda token, principal: 'cap-session-' + principal
        verify.auth_time = lambda token, principal: time.time()
        verify.aal = lambda token, principal: 'aal1'
        verify.method_time = lambda token, principal: time.time()
        verify.passkey_time = lambda token, principal: None
        verify.amr = lambda token, principal: []
        verify.proof = verify
        self.service = HostedWorkspaceService(factory, verify, clock=time.time,
                                              vault=CredentialVault(self.env['POSTRIFF_CREDENTIAL_KEY']),
                                              providers={'discord': self.provider},
                                              public_base_url=self.env['POSTRIFF_PUBLIC_BASE_URL'])
        if self.provider.rate_v1_enabled and (self.provider.rate_limiter is None or self.provider.rate_limiter.policy is None):
            raise RuntimeError('the seeding rate policy was not accepted by the coordinator')

    def _patient_reads(self):
        """Seeding only: a read the shared coordinator delays is tried again, as a person would click again.

        Several seeding processes start together and share the bot's own routes (GET /users/@me and GET
        /oauth2/applications/@me, no major parameter): while such a route is still unknown the coordinator admits one
        discovery request per second for all of them, and the provider waits at most one second before it raises
        ReadAdmissionDelayed ("no request was sent"). One seeding process then died at its first workspace (seen on
        the GitHub-hosted runner and reproduced here with four processes starting at once). Retrying a GET that was
        never sent is safe and changes nothing the run measures: seeding requests are not in the run's log, and the
        harness checks afterwards that seeding left no admission open. Writes are never retried."""
        from postriff_phase2.discord.rate_limits import RateDelayed
        original = self.provider._discord_http
        counts = self.read_retries

        def patient(method, path, **kwargs):
            for attempt in range(80):
                try:
                    return original(method, path, **kwargs)
                except RateDelayed as error:
                    if method != 'GET' or attempt == 79:
                        raise
                    key = '%s %s (%s, %s)' % (method, self.mock.route_class(method, path).split(' ', 1)[1],
                                              getattr(error, 'rate_scope_kind', '?'), getattr(error, 'rate_cause', '?'))
                    counts[key] = counts.get(key, 0) + 1
                    time.sleep(min(2.0, max(0.05, error.retry_after_seconds)) + (os.getpid() % 7) * 0.03 + attempt * 0.01)
        self.provider._discord_http = patient

    def connect(self, index):
        mock, service = self.mock, self.service
        principal = principal_for(index, self.run_tag)
        token = 'cap-session-token-%d' % index
        self.tokens[token] = principal
        with self.factory() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (principal,))
        workspace = service.bootstrap(token, 'studio')['workspaceId']
        connections = service.oauth.discord_connections
        user = {'id': mock.user_id(index), 'username': 'capuser%d' % index, 'global_name': 'Capacity user %d' % index}
        body = {'access_token': mock.bearer(index), 'refresh_token': mock.refresh_token(index), 'expires_in': 604800,
                'token_type': 'Bearer', 'scope': 'identify guilds'}
        identity = connections.save_identity(workspace, token, {'memberId': principal, 'identityGenerations': {}},
                                             body, user, ['identify', 'guilds'])['connectionId']
        state = self.state(workspace)
        record = next(x for x in state['phase2']['discordIdentityLinks'] if x['id'] == identity)
        guild = mock.guild_id(index)
        envelope = {'v': 2, 'kind': 'installation', 'applicationId': self.provider.client_id,
                    'botUserId': self.provider._bot_identity(), 'user': user['id'], 'guild': guild, 'channel': None,
                    'identityConnectionId': identity, 'identityGeneration': record['authorizationGeneration']}
        # The callback's own reads before it stores an installation (discord/oauth.py complete()).
        guild_body = self.provider._json(self.provider._bot('GET', '/guilds/' + guild), dict)
        if not self.provider.destinations(json.dumps(envelope)):
            raise RuntimeError('the synthetic server offers no publishable channel')
        envelope['authorization'] = {'bearerScopes': ['identify'], 'installationScopes': ['bot']}
        context = {'identityConnectionId': identity, 'identityGeneration': record['authorizationGeneration'],
                   'guildId': guild, 'connectionId': None, 'installationGeneration': None, 'userId': user['id']}
        installed = connections.save_installation(workspace, token, context, envelope, ['bot', 'identify'],
                                                  guild_body)['connectionId']
        service.oauth.choose_destination(workspace, token, installed, mock.channel_id(index))
        return {'index': index, 'principal': principal, 'token': token, 'workspace': workspace,
                'connection': installed, 'guild': guild, 'channel': mock.channel_id(index)}

    def state(self, workspace):
        with self.factory() as db:
            raw = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,)).fetchone()[0]
        return json.loads(raw) if isinstance(raw, str) else raw

    def schedule(self, fixture, dues, *, clock_offset=0.0):
        """One approved Discord post per entry of `dues` (epoch seconds), by the hosted review and approval commands.

        `clock_offset` (seconds, default 0) shifts the clock the commands see, never the tested worker's: the approval
        expiry scenario approves and schedules its posts an hour in the past, so their approvals (scheduled time plus
        3,600 s, the application's own rule) lapse a few minutes into the run.

        Every hosted command ends with engine.invalidate(state), which re-validates every job and review of the
        workspace, so building one workspace's n posts costs O(n^2) (about 50 minutes for 3,000). Nothing changes
        between these commands, so for seeding the per-command invalidate is applied to the jobs and reviews that
        command created (the same narrowing the worker's own claim uses for its platform filter), and the real,
        unnarrowed invalidate runs once at the end; the seeder fails if that final pass changes anything.
        """
        commands = self.service.commands
        engine = commands.engine
        posts = len(dues)
        workspace, principal = fixture['workspace'], fixture['principal']
        state = self.state(workspace)
        real_clock = (commands.clock, engine.clock)
        if clock_offset:
            shifted = lambda: time.time() + clock_offset
            commands.clock = engine.clock = shifted
        validated = {'jobs': {j.get('id') for j in state['phase2']['jobs']},
                     'reviews': {r.get('id') for r in state['phase2']['reviews']}}
        original_invalidate = engine.invalidate

        def narrowed_invalidate(target, *args, **kwargs):
            data = target.get('phase2') or {}
            jobs, reviews = data.get('jobs', []), data.get('reviews', [])
            data['jobs'] = [j for j in jobs if j.get('id') not in validated['jobs']]
            data['reviews'] = [r for r in reviews if r.get('id') not in validated['reviews']]
            try:
                return original_invalidate(target, *args, **kwargs)
            finally:
                fresh_jobs, fresh_reviews = data['jobs'], data['reviews']
                kept_jobs = [j for j in jobs if j.get('id') in validated['jobs']]
                kept_reviews = [r for r in reviews if r.get('id') in validated['reviews']]
                data['jobs'], data['reviews'] = kept_jobs + fresh_jobs, kept_reviews + fresh_reviews
                validated['jobs'].update(j.get('id') for j in fresh_jobs)
                validated['reviews'].update(r.get('id') for r in fresh_reviews if r.get('status') == 'approved')
        if posts > 20:
            engine.invalidate = narrowed_invalidate
        destination = self.authorization.destination_id(workspace, fixture['connection'], fixture['guild'],
                                                        fixture['channel'])
        records = []
        for number, due in enumerate(dues):
            moment = datetime.fromtimestamp(due, timezone.utc)
            local_time = moment.strftime('%Y-%m-%dT%H:%M') if moment.second == 0 else moment.strftime('%Y-%m-%dT%H:%M:%S')
            post_id = 'w%d-p%d' % (fixture['index'], number)
            variant = {'id': 'cap-draft-%d' % number, 'platform': 'Discord',
                       'text': post_text(fixture['index'], number, post_id), 'language': 'en', 'revision': 1,
                       'voiceRevision': None, 'briefRevision': 1, 'sourceIds': [], 'needsReview': False,
                       'blockedByRetraction': False, 'unknowns': [], 'warnings': [], 'contentTypeId': 'unclassified',
                       'contentTypeVersion': 'legacy', 'formatId': None, 'revisions': []}
            state['variants'].append(variant)
            state = commands(state, principal, 'p2_review', {
                'variantId': variant['id'], 'channelId': fixture['connection'], 'destinationId': destination,
                'localTime': local_time, 'timeZone': 'UTC', 'acknowledgedWarnings': []})
            entry = state['phase2']['reviews'][-1]
            state = commands(state, principal, 'p2_approve', {'reviewId': entry['id'], 'digest': entry['digest'],
                                                             'confirmed': True})
            job = next(j for j in reversed(state['phase2']['jobs']) if j['id'] == entry['manifest']['discord']['publicationId'])
            manifest = job['manifest']
            records.append({'index': fixture['index'], 'workspace': workspace, 'post': post_id, 'job': job['id'],
                            'nonce': hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()[:25],
                            'due': float(job.get('nextAt') or due), 'scheduled': due,
                            'expiresAt': float(manifest['expiresAt']), 'state': job['state']})
        engine.invalidate = original_invalidate
        commands.clock, engine.clock = real_clock
        before = json.dumps(state, sort_keys=True)
        original_invalidate(state)
        if json.dumps(state, sort_keys=True) != before:
            raise RuntimeError('the final full invalidate changed the seeded workspace; the narrowed seeding is not '
                               'equivalent for workspace %d' % fixture['index'])
        jobs = {job['id']: job for job in state['phase2']['jobs']}
        for record in records:
            record['state'] = jobs[record['job']]['state']
            if record['state'] != 'scheduled':
                raise RuntimeError('a seeded post is %s, not scheduled' % record['state'])
        with self.factory() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                       (json.dumps(state), workspace))
        return records


def main(argv=None):
    parser = argparse.ArgumentParser(description='Seed synthetic workspaces and approved Discord posts.')
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--admin-dsn', required=True)
    parser.add_argument('--env', required=True, help='JSON file with the application environment (seeding policy)')
    parser.add_argument('--plan', required=True, help='JSON file: {"workspaces": [[index, [offsets from T]], ...]}')
    parser.add_argument('--out', required=True)
    parser.add_argument('--slice', default='0/1')
    args = parser.parse_args(argv)
    env = json.loads(Path(args.env).read_text())
    plan = json.loads(Path(args.plan).read_text())
    part, parts = (int(x) for x in args.slice.split('/'))
    os.environ.update(env)
    seeder = Seeder(args.source_tree, args.admin_dsn, env, workspaces_total=plan['workspacesTotal'],
                    run_tag=plan['runTag'])
    mine = [item for position, item in enumerate(plan['workspaces']) if position % parts == part]
    # Every slice starts its first workspace at the same moment (as on an idle runner, where imports take the same
    # time everywhere): the shared bot routes then meet their worst case in every run, not only on a fast machine.
    Path(args.out + '.ready').write_text('ready')
    go = Path(args.plan + '.go')
    while not go.exists():
        if time.time() > plan['deadline']:
            raise SystemExit('the harness never released the seeding processes')
        time.sleep(0.02)
    started = time.time()
    if os.environ.get('CAP_SEED_FAIL_SLICE') == str(part):  # harness self-check only: a slice that fails on purpose
        raise RuntimeError('capacity harness self-check: seeding slice %s fails on purpose' % args.slice)
    # Phase 1: every workspace and its Discord connection (the slow part; no due time is needed for it).
    fixtures = [(seeder.connect(index), offsets) for index, offsets in mine]
    connected = time.time()
    Path(args.out + '.connected').write_text(json.dumps({'workspaces': len(fixtures), 'seconds': connected - started}))
    # Phase 2: the harness picks T once every slice is connected, then the posts are approved for it.
    due_file = Path(args.plan + '.due')
    while not due_file.exists():
        if time.time() > plan['deadline']:
            raise SystemExit('no due time arrived from the harness')
        time.sleep(0.2)
    due = json.loads(due_file.read_text())
    posts = 0
    with open(args.out + '.tmp', 'w') as handle:
        for fixture, offsets in fixtures:
            for record in seeder.schedule(fixture, [due['due'] + offset for offset in offsets],
                                          clock_offset=due.get('clockOffset') or 0.0):
                handle.write(json.dumps(record, separators=(',', ':')) + '\n')
                posts += 1
            if time.time() > due['deadline']:
                raise SystemExit('seeding overran its deadline (T minus the lead time); rerun with a larger --lead')
    os.replace(args.out + '.tmp', args.out)
    print(json.dumps({'event': 'seed.slice_done', 'slice': args.slice, 'workspaces': len(fixtures), 'posts': posts,
                      'connectSeconds': round(connected - started, 1), 'scheduleSeconds': round(time.time() - connected, 1),
                      'seedingRequests': seeder.transport.calls, 'delayedReadsRetried': seeder.read_retries}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
