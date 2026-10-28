"""Signed synthetic HTTPS interactions. No real commands/installations/tokens."""
import importlib.util
import json
import unittest
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from postriff_alpha.domain import AlphaError

APP, USER, CMD, IID = '1234567', '4242424', '88112233', '99112233'
NOW = 1800000000

class InteractionFixture:
    def setUp(self):
        spec = importlib.util.find_spec('postriff_phase2.discord.interactions')
        self.assertIsNotNone(spec, 'signed interaction implementation is missing')
        from postriff_phase2.discord.interactions import DiscordInteractions
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.config = {'applicationId': APP, 'publicKey': public, 'commandId': CMD, 'commandVersion': '77112233',
                       'commandName': 'rafii-drafts', 'integrationTypes': [1], 'contexts': [1, 2],
                       'qualified': True, 'endpoint': 'https://rafii.example.invalid/api/discord/interactions'}
        provider = SimpleNamespace(client_id=APP, user_install_v1_enabled=True, interaction_config_raw=self.config, execution_enabled=True)
        self.seen = set(); self.links = [{'workspaceId': 'workspace', 'memberId': 'actor'}]
        self.service = DiscordInteractions(provider, None, 'https://rafii.example.invalid', clock=lambda: NOW)
        def claim(app, iid):
            k = (app, iid)
            if k in self.seen: return False
            self.seen.add(k); return True
        self.service.claim = claim
        self.service.resolve = lambda subject: self.links
        def process(subject, iid):
            if not self.service.claim(APP, iid): raise AlphaError('replay', 409)
            return self.service.resolve(subject)
        self.service.process = process
    def packet(self, **changes):
        return {'id': IID, 'application_id': APP, 'type': 2, 'context': 2,
                'authorizing_integration_owners': {'1': USER}, 'user': {'id': USER},
                'data': {'id': CMD, 'name': 'rafii-drafts', 'type': 1},
                'token': 'synthetic-never-persist-this', **changes}
    def send(self, packet, *, timestamp=None, raw=None, signature=None):
        body = raw if raw is not None else json.dumps(packet).encode()
        ts = str(NOW if timestamp is None else timestamp)
        sig = signature or self.key.sign(ts.encode() + body).hex()
        return self.service.receive(body, ts, sig)


class InteractionTests(InteractionFixture, unittest.TestCase):
    def test_signed_ping_and_modified_raw_body(self):
        self.assertEqual(self.send({'type': 1, 'application_id': APP}), {'type': 1})
        with self.assertRaises(AlphaError): self.send(self.packet(), signature='00' * 64)
        with self.assertRaises(AlphaError): self.send(self.packet(), timestamp=NOW - 301)
    def test_ephemeral_private_drafts_link_and_persistent_claim(self):
        result = self.send(self.packet())
        self.assertEqual(result['type'], 4); self.assertEqual(result['data']['flags'], 64)
        self.assertIn('/queue', result['data']['content'])
        self.assertNotIn('synthetic-never', json.dumps(result)); self.assertNotIn('draft content', json.dumps(result))
        with self.assertRaises(AlphaError): self.send(self.packet())
    def test_private_reply_uses_signed_discord_locale_with_safe_english_fallback(self):
        for locale, linked, unlinked in [
                ('en-US', 'Open your private Rafii drafts', 'Open Rafii and link'),
                ('zh-TW', '開啟你的私密 Rafii 草稿', '開啟 Rafii 並連結'),
                ('zh-CN', '打开你的私密 Rafii 草稿', '打开 Rafii 并关联'),
                ('unknown', 'Open your private Rafii drafts', 'Open Rafii and link'),
                ({'untrusted': 'locale'}, 'Open your private Rafii drafts', 'Open Rafii and link')]:
            for links, expected in [([{'workspaceId': 'workspace', 'identityId': 'identity'}], linked), ([], unlinked)]:
                with self.subTest(locale=locale, linked=bool(links)):
                    self.seen.clear(); self.links = links
                    result = self.send(self.packet(locale=locale))
                    self.assertIn(expected, result['data']['content'])
                    self.assertEqual(result['data']['flags'], 64)
                    self.assertEqual(result['data']['allowed_mentions'], {'parse': []})
                    self.assertNotIn('synthetic-never', json.dumps(result))
    def test_application_user_owner_context_and_command_fail_closed(self):
        for changes in [{'application_id': USER}, {'context': 0}, {'authorizing_integration_owners': {'1': APP}},
                        {'user': {'id': APP}}, {'data': {'id': USER, 'name': 'rafii-drafts', 'type': 1}},
                        {'data': {'id': CMD, 'name': 'rafii-drafts', 'type': 1, 'options': [{'name': 'workspace', 'value': 'other'}]}},
                        {'member': {'user': {'id': APP}}}]:
            with self.subTest(changes=changes), self.assertRaises(AlphaError): self.send(self.packet(**changes))
    def test_unlinked_ambiguous_and_unqualified_never_read_drafts(self):
        for links in [[], [{'workspaceId': 'a'}, {'workspaceId': 'b'}]]:
            self.links = links; self.seen.clear()
            result = self.send(self.packet())
            self.assertIn('/channels', result['data']['content']); self.assertNotIn('workspaceId=', result['data']['content'])
        self.service.provider.interaction_config_raw = {**self.config, 'qualified': False}
        with self.assertRaises(AlphaError): self.send(self.packet(id='99112234'))
    def test_bounds_duplicate_keys_and_strict_json(self):
        for raw in [b'{' + b' ' * 65537 + b'}', b'{"type":1,"type":2}', b'[]', b'{"type":NaN}']:
            with self.subTest(size=len(raw)), self.assertRaises(AlphaError): self.send({}, raw=raw)

if __name__ == '__main__': unittest.main()

class InteractionRoutingTests(InteractionFixture, unittest.TestCase):
    def test_real_https_route_precedes_browser_guard_and_binds_raw_signature(self):
        import io
        from postriff_phase2.hosted_app import HostedApplication
        oauth = SimpleNamespace(providers={'discord': self.service.provider}, repository=SimpleNamespace(connection_factory=None), public_base_url='https://rafii.example.invalid')
        app = HostedApplication(service=SimpleNamespace(oauth=oauth))
        raw = json.dumps({'type': 1, 'application_id': APP}).encode(); ts = str(NOW)
        signature = self.key.sign(ts.encode() + raw).hex()
        from unittest.mock import patch
        for scheme, sig, expected in [('https', signature, 200), ('http', signature, 400), ('https', '00' * 64, 401)]:
            with self.subTest(scheme=scheme, signature_ok=sig == signature):
                environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/discord/interactions', 'wsgi.url_scheme': scheme,
                           'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json', 'wsgi.input': io.BytesIO(raw),
                           'HTTP_X_SIGNATURE_TIMESTAMP': ts, 'HTTP_X_SIGNATURE_ED25519': sig}
                statuses = []
                with patch('postriff_phase2.discord.interactions.time.time', return_value=NOW):
                    body = b''.join(app._handle(environ, lambda status, headers: statuses.append(int(status.split()[0]))))
                self.assertEqual(statuses, [expected], body)
                if expected == 200: self.assertEqual(json.loads(body), {'type': 1})

class InteractionDeadlineTests(unittest.TestCase):
    def test_database_path_uses_one_bounded_checkout_and_sanitized_claim(self):
        from contextlib import contextmanager
        from postriff_phase2.discord.interactions import DiscordInteractions
        class Database:
            def __init__(self): self.calls = []; self.checkouts = []; self.fresh = True
            @contextmanager
            def bounded(self, timeout):
                self.checkouts.append(timeout); yield self
            @contextmanager
            def cursor(self): yield self
            def execute(self, sql, params=()): self.calls.append((sql, params)); self.sql = sql
            def fetchone(self):
                if self.fresh: self.fresh = False; return (IID,)
                return None
            def fetchall(self): return [('workspace', 'actor', 'identity')]
        db = Database(); s = DiscordInteractions(SimpleNamespace(client_id=APP), db, 'https://rafii.example.invalid')
        self.assertTrue(callable(getattr(s, 'process', None)), 'one bounded persistence boundary is missing')
        self.assertEqual(s.process(USER, IID), [{'workspaceId': 'workspace', 'memberId': 'actor', 'identityId': 'identity'}])
        with self.assertRaises(AlphaError): s.process(USER, IID)
        self.assertEqual(db.checkouts, [0.2, 0.2])
        self.assertNotIn('synthetic-never-persist-this', repr(db.calls))

class PrivateEntryTests(unittest.TestCase):
    def test_authenticated_entry_rechecks_actor_identity_generation_and_mapping(self):
        from contextlib import contextmanager
        from unittest.mock import Mock
        from postriff_phase2.discord.interactions import DiscordInteractions
        record = {'id': 'identity', 'workspaceId': 'workspace', 'authorizedBy': 'actor', 'status': 'linked', 'userId': USER}
        state = {'workspace': {'id': 'workspace'}, 'phase2': {'discordIdentityLinks': [record]}}
        cur = Mock(); cur.fetchone.return_value = (True,)
        @contextmanager
        def local(workspace, token): yield cur, state, 'actor'
        connections = SimpleNamespace(local=local, bind_identity=lambda *_: ((None, None, None, NOW + 500, 'generation'), {}))
        endpoint = DiscordInteractions(SimpleNamespace(client_id=APP), None, 'https://rafii.example.invalid', clock=lambda: NOW)
        self.assertTrue(callable(getattr(endpoint, 'review_entry', None)), 'authenticated linked-actor entry is missing')
        self.assertEqual(endpoint.review_entry(connections, 'workspace', 'synthetic-session', 'identity'), {'workspaceId': 'workspace', 'ready': True})
        cur.fetchone.return_value = None
        with self.assertRaises(AlphaError): endpoint.review_entry(connections, 'workspace', 'synthetic-session', 'identity')
        record['authorizedBy'] = 'other'
        with self.assertRaises(AlphaError): endpoint.review_entry(connections, 'workspace', 'synthetic-session', 'identity')

class ConfigurationReadbackTests(unittest.TestCase):
    def test_dry_run_never_registers_and_rejects_wrong_install_configuration(self):
        from scripts.discord_user_install_config import candidate
        from postriff_phase2.discord.interactions import COMMAND
        app = {'id': APP, 'verify_key': 'ab' * 32, 'interactions_endpoint_url': 'https://rafii.example.invalid/api/discord/interactions',
               'integration_types_config': {'1': {'oauth2_install_params': {'scopes': ['applications.commands'], 'permissions': '0'}}}}
        command = {**COMMAND, 'application_id': APP, 'id': CMD, 'version': '77112233'}
        preview = candidate(app, command)
        self.assertEqual(preview['execution'], 'dry-run'); self.assertFalse(preview['qualified']); self.assertFalse(preview['liveRegistered'])
        for changes in [{'verify_key': ''}, {'interactions_endpoint_url': 'http://evil.invalid/hook'},
                        {'integration_types_config': {'1': {'oauth2_install_params': {'scopes': ['identify', 'bot'], 'permissions': '8'}}}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): candidate({**app, **changes}, command)

class StrictConfigTests(InteractionFixture, unittest.TestCase):
    def test_boolean_context_configuration_and_malformed_options_rejected(self):
        self.service.provider.interaction_config_raw = {**self.config, 'contexts': [True, 2]}
        with self.assertRaises(AlphaError): self.send(self.packet())
        self.service.provider.interaction_config_raw = self.config
        self.seen.clear()
        packet = self.packet(data={'id': CMD, 'name': 'rafii-drafts', 'type': 1, 'options': {}})
        with self.assertRaises(AlphaError): self.send(packet)

class CommandCliTests(unittest.TestCase):
    def test_actual_dry_run_entrypoint_runs_from_owned_repository(self):
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run([sys.executable, 'scripts/discord_user_install_config.py'], cwd=root,
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0, run.stderr[-1000:])
        # The opt-in provider fence appends a separate zero-I/O receipt.
        # A dry-run command has exactly one JSON result plus that known receipt.
        text = run.stdout.lstrip()
        value, end = json.JSONDecoder().raw_decode(text)
        suffix = text[end:].strip()
        if suffix:
            self.assertTrue(suffix.startswith('RAFII_SYNTHETIC_FENCE_JSON '), suffix[:120])
            witness = json.loads(suffix.removeprefix('RAFII_SYNTHETIC_FENCE_JSON '))
            self.assertEqual(witness['unexpectedTransportAttempts'], 0)
            self.assertEqual(witness['realProviderRequests'], 0)
        self.assertEqual(value['execution'], 'dry-run')
        self.assertFalse(value['liveRegistered']); self.assertFalse(value['qualified'])

class EndpointQualificationTests(InteractionFixture, unittest.TestCase):
    def test_unqualified_signed_ping_can_verify_endpoint_without_activating_commands(self):
        self.service.provider.interaction_config_raw = {k: self.config[k] for k in ('applicationId', 'publicKey', 'endpoint')}
        self.assertEqual(self.send({'type': 1, 'application_id': APP}), {'type': 1})
        with self.assertRaises(AlphaError): self.send(self.packet())
        from postriff_phase2.discord.interactions import available
        self.assertFalse(available(self.service.provider))
