"""Injected checked-in methods only; no provider, SQL or optional dependencies.

This narrow release-gate contract is not application or live acceptance.
"""
import ast
import itertools
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'postriff_phase2'
qualified = runpy.run_path(str(SOURCE / 'mastodon_release.py'))['write_qualified']


class Refusal(Exception):
    def __init__(self, message, status, code=None):
        super().__init__(message)
        self.status, self.code = status, code


def method(filename, owner, name, namespace=None):
    tree = ast.parse((SOURCE / filename).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    scope = {'AlphaError': Refusal, 'mastodon_write_qualified': qualified, **(namespace or {})}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), filename, 'exec'), scope)
    return scope[name]


class WriteReleaseContract(unittest.TestCase):
    def test_injected_dispatch_and_connection_boundary(self):
        api = method('social_connectors.py', 'MastodonProvider', 'api')
        revoke = method('social_connectors.py', 'MastodonProvider', 'revoke')
        select = method('hosted_social.py', 'HostedSocial', '_provider',
                        {'HOSTED_PUBLISHERS': {'Mastodon': 'mastodon'}})
        execute = method('mastodon_management.py', 'MastodonManagement', 'execute')
        for reviewed, tested, approved in itertools.product((False, True), repeat=3):
            with self.subTest(reviewed=reviewed, tested=tested, approved=approved):
                events = []
                def transport(verb, url, **kwargs):
                    events.append((verb, url))
                    return {'status': 200, 'body': {}}
                def resolve(host):
                    events.append(('resolve', host))
                    return host
                provider = SimpleNamespace(id='mastodon', production_reviewed=reviewed,
                    publish_live_tested=tested, publishing_permission=approved,
                    execution_enabled=True, _server=resolve, transport=transport)
                session = {'instance': 'social.example', 'at': 'synthetic',
                           'clientId': 'client', 'clientSecret': 'secret'}
                provider.session = lambda token: session
                ready = reviewed and tested and approved
                self.assertEqual(qualified(provider), ready)
                self.assertIs(select(SimpleNamespace(providers={'mastodon': provider}),
                                     {'platform': 'Mastodon'}), provider if ready else None)
                if not ready:
                    manager = SimpleNamespace(_grant=lambda *args: (provider, {}, session))
                    with self.assertRaises(Refusal) as refusal:
                        execute(manager, 'workspace', 'actor', 'connection', 'action',
                                {'confirmed': True, 'digest': 'exact'})
                    self.assertEqual(refusal.exception.code, 'mastodon_write_release_required')
                for verb in ('POST', 'PUT', 'PATCH', 'DELETE'):
                    if ready:
                        api(provider, session, verb, '/api/v1/statuses/1')
                    else:
                        with self.assertRaises(Refusal) as refusal:
                            api(provider, session, verb, '/api/v1/statuses/1')
                        self.assertEqual(refusal.exception.code, 'mastodon_write_release_required')
                if not ready:
                    self.assertEqual(events, [])
                # Connection verification and withdrawal remain available before write acceptance.
                api(provider, session, 'GET', '/api/v1/accounts/verify_credentials')
                self.assertTrue(revoke(provider, 'synthetic'))
                self.assertEqual(events[-1], ('POST', 'https://social.example/oauth/revoke'))
                provider.publishing_permission = False
                before = list(events)
                with self.assertRaises(Refusal):
                    api(provider, session, 'POST', '/api/v1/statuses')
                self.assertEqual(events, before)
        self.assertFalse(qualified(SimpleNamespace(id='mastodon', production_reviewed=True)))
        self.assertFalse(qualified(SimpleNamespace(id='mastodon', production_reviewed=True,
            publish_live_tested='true', publishing_permission=True)))

    def test_capability_projection_keeps_identity_and_reads_independent(self):
        tree = ast.parse((SOURCE / 'channels.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in ('CAPABILITIES', 'LEVELS') for t in n.targets)]
        nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name in ('unsupported_matrix', 'assisted_matrix', 'set_level')]
        scope = {'AlphaError': Refusal}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), 'channels.py', 'exec'), scope)
        capabilities = method('oauth.py', 'OAuthService', '_capabilities',
                              {**scope, 'PUBLISH_CAPABILITIES': ('publish', 'schedule')})
        scopes = {'identity': ['read:accounts'], 'publish': ['write:statuses'],
                  'schedule': ['write:statuses'], 'analytics': ['read:statuses'],
                  'comments_read': ['read:notifications'], 'reply': ['write:statuses'],
                  'moderate': ['write:blocks']}
        provider = SimpleNamespace(id='mastodon', platform='Mastodon', production_reviewed=True,
            execution_enabled=True, publish_live_tested=False, publishing_permission=False,
            assisted_fallback=True, capability_version=2, capability_scopes=lambda name: scopes.get(name, []))
        granted = sorted({s for values in scopes.values() for s in values})
        matrix = capabilities(provider, 'identity', granted, [], 1)
        for name in ('identity', 'analytics', 'comments_read'):
            self.assertEqual(matrix[name]['level'], 'Direct')
        for name in ('publish', 'schedule', 'reply', 'moderate'):
            self.assertNotEqual(matrix[name]['level'], 'Direct')
        provider.publish_live_tested = provider.publishing_permission = True
        matrix = capabilities(provider, 'identity', granted, [], 1)
        self.assertEqual(matrix['publish']['level'], 'Direct')
        self.assertEqual(matrix['reply']['level'], 'Direct')
