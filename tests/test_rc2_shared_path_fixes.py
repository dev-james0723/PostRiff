"""RC2 fixes for regressions the customer impact inventory found in code EXISTING customers use (Discord off).

Each class names its finding in docs/CUSTOMER-IMPACT-INVENTORY.md (branch claude/discord-impact-20261023) and pins the
behaviour of the live build, c5fc1fd1 (what rafii.io serves). Two kinds of test:

- in-tree tests assert the live behaviour directly on this tree, so they also run in a shallow CI checkout;
- differential tests run one probe script with the live tree (from `git archive`, read-only on the repository) and with
  this tree and require identical records. They skip when the live revision is not in the clone.

docs/RC2-SHARED-PATH-FIXES.md lists which of these fail on the base (the W-02 head before the fixes) and why.
No database, network, provider or credential is used here; the real-PostgreSQL proofs are in
tests/test_rc2_shared_paths_postgres.py.
"""
import atexit
import copy
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_REV = os.environ.get('RC2_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')
PROBE_TIMEOUT = 300


def _rev(rev):
    done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', '--quiet', rev + '^{commit}'],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _probe(script, tree, *args):
    done = subprocess.run([sys.executable, str(ROOT / 'tests' / script), str(tree), *map(str, args)],
                          capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    if done.returncode:
        raise AssertionError('%s failed on %s: %s' % (script, tree, done.stderr[-3000:]))
    # The probe prints one JSON line first; under the synthetic transport fence its receipt line follows.
    return json.loads(done.stdout.splitlines()[0])


class LiveTree:
    """The live source tree, extracted once per process from git (never a checkout or worktree)."""
    path = None

    @classmethod
    def get(cls):
        if cls.path is None:
            target = Path(tempfile.mkdtemp(prefix='rc2-live-'))
            atexit.register(shutil.rmtree, target, True)
            archive = subprocess.run(['git', '-C', str(ROOT), 'archive', LIVE_REV, 'src'], capture_output=True, check=True)
            subprocess.run(['tar', '-x', '-C', str(target)], input=archive.stdout, check=True)
            cls.path = target
        return cls.path


# --- FB-1: Facebook Page approvals ---------------------------------------------------------------------------------------
LIVE_JOB = {'state': 'scheduled', 'events': ['Exact local fixture approval recorded', 'Waiting for the local durable worker']}


class FacebookApprovalUnchanged(unittest.TestCase):
    """FB-1 (HIGH). RC1 refused every Facebook manifest in Phase2Store.current() unless manifest.destinationId equalled
    channel.destinationId, and nothing writes manifest.destinationId: reviews were born stale, approvals refused, and a
    post approved on the live build was held by the next invalidate() (every hosted command, every worker claim)."""

    @classmethod
    def setUpClass(cls):
        cls.record = _probe('rc2_facebook_probe.py', ROOT)

    def scenario(self, name):
        return self.record['scenarios'][name]

    def test_a_facebook_page_review_is_current_and_approvable(self):
        result = self.scenario('liveChannel')
        self.assertEqual((result['review']['status'], result['review']['current']), ('needs_review', True), result['review'])
        self.assertNotIn('refused', result['approval'], result['approval'])
        self.assertEqual({k: result['approval'][k] for k in ('state', 'events')}, LIVE_JOB)
        self.assertTrue(result['approval']['current'])
        self.assertNotIn('destinationId', result['review']['manifest'], 'the manifest is the live one: no Page id frozen')

    def test_an_approved_facebook_post_survives_invalidate_and_the_worker_claim(self):
        for name in ('liveChannel', 'channelWithPageId'):
            with self.subTest(channel=name):
                result = self.scenario(name)
                self.assertEqual(result.get('afterInvalidate'), LIVE_JOB, result['approval'])
                self.assertEqual(result.get('afterClaimInvalidation'), LIVE_JOB, result['approval'])

    def test_a_page_id_recorded_on_the_channel_changes_nothing(self):
        """A channel that already carries destinationId (written by an earlier candidate's Page choice) is treated as
        live treats it: the field is ignored, and the post is approved and kept."""
        plain, recorded = self.scenario('liveChannel'), self.scenario('channelWithPageId')
        self.assertEqual((recorded['review']['status'], recorded.get('afterClaimInvalidation')), ('needs_review', LIVE_JOB))
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(recorded, sort_keys=True))

    def test_choosing_a_facebook_page_changes_only_the_grant(self):
        """As live: the chosen Page goes into the encrypted grant; the workspace state, its revision, the channel record
        and the capability rows are untouched (RC1 relabelled the channel, rewrote nine capability rows, could clear
        capabilityVerified, bumped the revision and ran invalidate())."""
        chosen = self.record['choosePage']
        self.assertEqual(chosen.get('result'), {'connectionId': 'facebook-connection-1', 'destinationId': '100200300400'}, chosen)
        self.assertEqual(chosen['pageInGrant'], '100200300400')
        self.assertEqual(chosen['revision'], 7, 'the workspace row is not rewritten')
        self.assertNotIn('destinationId', chosen['channel'])
        self.assertEqual((chosen['channel']['account'], chosen['channel']['capabilityVerified']), ('Impact Studio', True))
        writes = [s for s in chosen['statements'] if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [
            'UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s',
            'UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND access_ciphertext=%s A',
            'INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,%s,%s,%s,%s::jsonb)'])

    def test_no_facebook_branch_in_the_approval_check_or_the_page_choice(self):
        from postriff_phase2.oauth import OAuthService
        from postriff_phase2.store import Phase2Store
        self.assertNotIn('Facebook', inspect.getsource(Phase2Store.current))
        self.assertNotIn('facebook', inspect.getsource(OAuthService.choose_destination).lower())


@unittest.skipUnless(_rev(LIVE_REV), 'the live revision is not in this clone (shallow checkout)')
class FacebookMatchesLive(unittest.TestCase):
    """FB-1, differential: the same probe with the live tree and with this tree gives the same record, including for a
    post approved on the live build and then handled by this build (the promotion case)."""

    @classmethod
    def setUpClass(cls):
        live = LiveTree.get()
        cls.live = _probe('rc2_facebook_probe.py', live)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump(cls.live['approvedState'], handle)
        try:
            cls.live = _probe('rc2_facebook_probe.py', live, handle.name)
            cls.mine = _probe('rc2_facebook_probe.py', ROOT, handle.name)
        finally:
            os.unlink(handle.name)

    def test_reviews_approvals_and_invalidation_are_identical_to_live(self):
        self.assertEqual(self.live['scenarios']['liveChannel']['afterClaimInvalidation'], LIVE_JOB)
        for name in ('liveChannel', 'channelWithPageId'):
            with self.subTest(channel=name):
                self.assertEqual(json.dumps(self.mine['scenarios'][name], sort_keys=True),
                                 json.dumps(self.live['scenarios'][name], sort_keys=True))

    def test_a_post_approved_on_live_is_kept_by_this_build(self):
        self.assertEqual(self.live['carried'], {'current': True, 'afterInvalidate': LIVE_JOB, 'afterClaimInvalidation': LIVE_JOB})
        self.assertEqual(self.mine['carried'], self.live['carried'])

    def test_choosing_a_facebook_page_is_identical_to_live(self):
        self.assertEqual(json.dumps(self.mine['choosePage'], sort_keys=True), json.dumps(self.live['choosePage'], sort_keys=True))

    def test_no_other_facebook_code_differs_from_live(self):
        """The only Facebook-specific line in the src/ and api/ difference to live is the Discord-only public connection
        review helper (connection_review.py, called from discord/oauth.py alone)."""
        done = subprocess.run(['git', '-C', str(ROOT), 'diff', LIVE_REV, '--', 'src', 'api'], capture_output=True, text=True, check=True)
        files, hits = None, []
        for line in done.stdout.splitlines():
            if line.startswith('diff --git'):
                files = line.split(' b/')[-1]
            elif line[:1] in '+-' and not line.startswith(('+++', '---')) and 'facebook' in line.lower():
                hits.append(files)
        self.assertEqual(sorted(set(hits)), ['src/postriff_phase2/connection_review.py'], hits)
        callers = subprocess.run(['git', '-C', str(ROOT), 'grep', '-l', 'public_connection_review', '--', 'src', 'api'],
                                 capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(callers), ['src/postriff_phase2/connection_review.py', 'src/postriff_phase2/discord/oauth.py'])


# --- CH-1: the Channels read ---------------------------------------------------------------------------------------------
class _EmptyCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(' '.join(str(sql).split())[:80])

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _CountingRepository:
    """Counts repository transactions: in Production each one verifies the session (a Supabase Auth getUser call and a
    session-flag connection) and opens one more database connection for the locked workspace row."""
    def __init__(self, state, actor):
        self.state, self.actor, self.transactions, self.statements = state, actor, 0, []

    @contextmanager
    def transaction(self, token, workspace_id, **kwargs):
        self.transactions += 1
        yield _EmptyCursor(self.statements), (1, copy.deepcopy(self.state), 'owner', True, False, False, False), self.actor

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id, allow_deleting=True) as (_, row, _):
            return {'revision': row[0], 'state': row[1]}


class ChannelsReadAddsNoTransaction(unittest.TestCase):
    """CH-1 (MEDIUM). With POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED=true (set in Production) OAuthService.channels()
    called discord_connections.public_identities() for EVERY workspace: a third repository transaction (one more
    Supabase Auth getUser call and two more database connections in Production) to return [] where no Discord identity
    was ever linked. Live's Channels read is two repository transactions: get() and the capability read."""
    WORKSPACE, ACTOR = '10000000-0000-4000-8000-0000000000c1', '20000000-0000-4000-8000-0000000000c1'

    def read(self, links=None, connections_v2=True):
        from postriff_phase2.auth import initial_phase2_state
        from postriff_phase2.hosted import HostedPhase2Commands
        from postriff_phase2.oauth import CredentialVault, OAuthService
        from postriff_phase2.social_connectors import DiscordProvider
        state = initial_phase2_state(self.WORKSPACE, self.ACTOR, 'Rafii member', 'studio', 1_800_000_000.0, execution='hosted-candidate')
        if links is not None:
            state['phase2']['discordIdentityLinks'] = links
        discord = DiscordProvider('123456789012345678', 'synthetic-secret', 'synthetic.bot.token', 'https://app.rafii.invalid',
                                  transport=lambda *a, **k: self.fail('no Discord request on a Channels read'))
        discord.connections_v2_enabled = connections_v2
        repository = _CountingRepository(state, self.ACTOR)
        service = OAuthService(repository, HostedPhase2Commands(lambda: 1_800_000_000.0), CredentialVault(CredentialVault.generate_key()),
                               {'discord': discord}, 'https://app.rafii.invalid', clock=lambda: 1_800_000_000.0)
        listing = service.channels(self.WORKSPACE, 'synthetic-session')
        return listing, repository.transactions

    def link(self, **changes):
        return {'id': 'discord-identity-1', 'workspaceId': self.WORKSPACE, 'authorizedBy': self.ACTOR, 'account': 'synthetic#0001',
                'userId': '4242424242', 'status': 'linked', 'expiresAt': 1_800_086_400.0, 'discoverGuilds': False, **changes}

    def test_a_workspace_without_discord_identity_links_costs_what_live_costs(self):
        for links in (None, []):
            with self.subTest(links=links):
                listing, transactions = self.read(links)
                self.assertEqual(listing['discordIdentities'], [])
                self.assertEqual(transactions, 2, 'get() and the capability read, as live')

    def test_a_linked_identity_is_still_listed_through_its_own_read(self):
        listing, transactions = self.read([self.link()])
        self.assertEqual(transactions, 3, 'unchanged: the identity read stays for a workspace that has links')
        self.assertEqual(listing['discordIdentities'], [{
            'id': 'discord-identity-1', 'account': 'synthetic#0001', 'userId': '4242424242', 'status': 'linked',
            'expiresAt': 1_800_086_400.0, 'discoverGuilds': False, 'canPublish': False, 'canSchedule': False,
            'capabilityReason': 'discord_identity_only', 'connectionKind': 'identity', 'postAsPersonalUser': False, 'senderKind': 'none'}])

    def test_another_members_link_is_not_listed_as_before(self):
        listing, _ = self.read([self.link(authorizedBy='20000000-0000-4000-8000-0000000000c2')])
        self.assertEqual(listing['discordIdentities'], [])

    def test_connections_v2_off_reads_nothing_more(self):
        listing, transactions = self.read([self.link()], connections_v2=False)
        self.assertEqual((listing['discordIdentities'], transactions), ([], 2))


# --- PR-1: the public Discord interactions route while the feature is off ---------------------------------------------
QUIET_OFF = {'status': 401, 'code': 'discord_interaction_unavailable', 'logLevels': ['INFO'], 'unsigned': 401, 'runtimeStarted': False}


class DiscordInteractionsOffIsQuiet(unittest.TestCase):
    """PR-1 (LOW). POST /api/discord/interactions is answered before the bearer and origin checks. With the user-install
    flag unset RC1 answered 503 discord_interaction_unavailable, which the request logger writes at ERROR, after starting
    the hosted runtime in a cold process: any scanner could create ERROR lines and 5xx counts. Live answers the same
    request 403 (application guard) at INFO without the runtime. Off now answers 401 at INFO without the runtime."""

    @classmethod
    def setUpClass(cls):
        cls.record = _probe('rc2_interactions_probe.py', ROOT)

    def test_every_off_state_is_a_quiet_401_without_the_runtime(self):
        for case in ('cold', 'warm', 'killed', 'absent'):
            with self.subTest(case=case):
                self.assertEqual(self.record[case], QUIET_OFF)

    def test_on_keeps_signature_verification_and_reports_misconfiguration(self):
        import io
        import logging
        from types import SimpleNamespace
        from unittest.mock import patch
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from postriff_phase2.hosted_app import HostedApplication
        app_id, now = '1234567', 1800000000
        key = Ed25519PrivateKey.generate()
        config = {'applicationId': app_id, 'publicKey': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(),
                  'endpoint': 'https://rafii.example.invalid/api/discord/interactions'}
        provider = SimpleNamespace(client_id=app_id, user_install_v1_enabled=True, interaction_config_raw=config, execution_enabled=True)
        oauth = SimpleNamespace(providers={'discord': provider}, repository=SimpleNamespace(connection_factory=None),
                                public_base_url='https://rafii.example.invalid')
        app = HostedApplication(service=SimpleNamespace(oauth=oauth))
        raw = json.dumps({'type': 1, 'application_id': app_id}).encode()

        def send(signature):
            environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/discord/interactions', 'wsgi.url_scheme': 'https',
                       'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json', 'wsgi.input': io.BytesIO(raw),
                       'HTTP_X_SIGNATURE_TIMESTAMP': str(now), 'HTTP_X_SIGNATURE_ED25519': signature,
                       'HTTP_HOST': 'rafii.example.invalid', 'REMOTE_ADDR': '203.0.113.9'}
            statuses = []
            with patch('postriff_phase2.discord.interactions.time.time', return_value=now), \
                    self.assertLogs('postriff.request', 'INFO') as logged:
                body = b''.join(app(environ, lambda status, headers, exc_info=None: statuses.append(int(status.split()[0]))))
            return statuses[-1], json.loads(body), [r.levelname for r in logged.records]

        self.assertEqual(send(key.sign(str(now).encode() + raw).hex()), (200, {'type': 1}, ['INFO']))
        status, body, levels = send('00' * 64)
        self.assertEqual((status, body.get('code'), levels), (401, 'discord_interaction_unavailable', ['INFO']))
        provider.interaction_config_raw = None  # on, but not configured: the operator must see it
        status, body, levels = send(key.sign(str(now).encode() + raw).hex())
        self.assertEqual((status, body.get('code'), levels), (503, 'discord_interaction_unavailable', ['ERROR']))

    def test_the_route_reads_the_flag_exactly_as_the_adapter_does(self):
        """The cold-process shortcut reads the variable the provider registry reads, with the same exact-string rule."""
        source = inspect.getsource(__import__('postriff_phase2.social_connectors', fromlist=['x']).DiscordProvider.mount)
        self.assertIn("values.get('POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED') == 'true'", source)
        from postriff_phase2 import hosted_app
        self.assertIn("os.environ.get('POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED') != 'true'", inspect.getsource(hosted_app.HostedApplication._handle))


@unittest.skipUnless(_rev(LIVE_REV), 'the live revision is not in this clone (shallow checkout)')
class DiscordInteractionsOffMatchesLiveLogging(unittest.TestCase):
    """PR-1, differential: live has no such route and answers the application guard's 403. Both builds answer with a
    4xx at INFO without starting the runtime, in every off state; the status differs on purpose (401, see receive())."""

    def test_same_log_level_status_class_and_no_runtime_as_live(self):
        live, mine = _probe('rc2_interactions_probe.py', LiveTree.get()), _probe('rc2_interactions_probe.py', ROOT)
        for case in ('cold', 'warm', 'killed', 'absent'):
            with self.subTest(case=case):
                self.assertEqual((live[case]['status'], live[case]['logLevels'], live[case]['runtimeStarted']), (403, ['INFO'], False))
                self.assertEqual((mine[case]['logLevels'], mine[case]['runtimeStarted'], mine[case]['status'] // 100),
                                 (live[case]['logLevels'], live[case]['runtimeStarted'], live[case]['status'] // 100))


if __name__ == '__main__':
    unittest.main()
