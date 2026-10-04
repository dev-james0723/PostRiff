import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2.james_daily_call import DailyCallConfig
from postriff_phase2.productivity_connectors import ProductivityConnectorService

PERSONAL = 'personal@example.com'
BINDINGS = {p: {'account': PERSONAL, 'connectionId': 'pc_' + c * 32}
            for p, c in [('gmail', '1'), ('google_calendar', '2')]}

class IdentityTests(unittest.TestCase):
    def service(self, identities=None, missing=False):
        cur, db = MagicMock(), MagicMock()
        db.__enter__.return_value = db
        db.cursor.return_value.__enter__.return_value = cur
        cur.fetchone.side_effect = [(1,), None if missing else (BINDINGS['gmail']['connectionId'],),
                                   None if missing else (BINDINGS['google_calendar']['connectionId'],)]
        repo = SimpleNamespace(connection_factory=lambda: db)
        providers = {p: Mock() for p in BINDINGS}
        for p, provider in providers.items():
            provider.authenticated_account.return_value = (identities or {}).get(p, PERSONAL)
            provider.search.return_value = []
            provider.events_between.return_value = []
        service = ProductivityConnectorService(repo, Mock(), providers=providers,
            flags={'gmail': True, 'google_calendar': True}, clock=lambda: 1791060000)
        service._connection = Mock(return_value={})
        service._access_token = Mock(return_value='test-access')
        return service, providers, cur

    def test_unbound_sources_are_rejected(self):
        service, providers, _ = self.service()
        with self.assertRaises(AlphaError) as e:
            service.daily_brief_context('workspace', 'user', 'America/Indiana/Indianapolis')
        self.assertEqual(e.exception.code, 'briefing_identity_unbound')
        providers['gmail'].search.assert_not_called()

    def test_exact_personal_accounts_and_connections_are_selected(self):
        service, providers, cur = self.service()
        out = service.daily_brief_context('workspace', 'user', 'America/Indiana/Indianapolis', account_bindings=BINDINGS)
        for provider, bucket in [('gmail', 'gmail'), ('google_calendar', 'calendar')]:
            self.assertEqual(out[bucket]['account'], PERSONAL)
            self.assertEqual(out[bucket]['connectionId'], BINDINGS[provider]['connectionId'])
            query = next(c for c in cur.execute.call_args_list if len(c.args)>1 and len(c.args[1])==5 and c.args[1][2]==provider)
            self.assertIn('connection_id=%s AND lower(provider_account_id)=%s', query.args[0])
            self.assertNotIn('ORDER BY updated_at', query.args[0])
            self.assertEqual(query.args[1][-2:], (BINDINGS[provider]['connectionId'], PERSONAL))
        self.assertTrue(all('newer_than:1d' in c.args[1] for c in providers['gmail'].search.call_args_list))

    def test_work_identity_cannot_supply_personal_data(self):
        service, providers, _ = self.service({'gmail': 'work@example.com', 'google_calendar': 'work@example.com'})
        out = service.daily_brief_context('workspace', 'user', 'America/Indiana/Indianapolis', account_bindings=BINDINGS)
        self.assertEqual(out['gmail']['status'], 'identity_mismatch')
        self.assertEqual(out['calendar']['status'], 'identity_mismatch')
        providers['gmail'].search.assert_not_called()
        providers['google_calendar'].events_between.assert_not_called()

    def test_missing_personal_account_never_falls_back_to_work(self):
        service, providers, _ = self.service(missing=True)
        out = service.daily_brief_context('workspace', 'user', 'America/Indiana/Indianapolis', account_bindings=BINDINGS)
        self.assertEqual(out['gmail']['status'], 'not_connected')
        self.assertEqual(out['calendar']['status'], 'not_connected')
        providers['gmail'].search.assert_not_called()

    def test_daily_call_requires_both_explicit_bindings(self):
        with self.assertRaises(AlphaError):
            _ = DailyCallConfig({}).briefing_bindings

class AuditRouteTests(unittest.TestCase):
    def test_audit_is_authenticated_and_does_not_create_calls(self):
        from postriff_phase2.hosted_app import HostedApplication
        daily = Mock()
        daily.cfg.scheduled_enabled = False
        daily._context.return_value = {'timeZone': 'America/Indiana/Indianapolis',
            'gmail': {'status': 'ok', 'account': PERSONAL, 'items': [{}]},
            'calendar': {'status': 'ok', 'account': PERSONAL, 'items': []},
            'projectPulse': {'status': 'ok', 'items': [{}]}}
        daily.initial_request.return_value = 'Personal opening'
        service = SimpleNamespace(james_daily_call=daily)
        app = HostedApplication(service=service)
        app._runtime = Mock(return_value=service)
        env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/internal/james-daily-call/briefing-audit',
               'wsgi.input': io.BytesIO(b'')}
        status = Mock()
        with patch.dict(os.environ, {'JAMES_DAILY_CALL_AUDIT_TOKEN': 'a' * 40}):
            app(env, status)
            self.assertTrue(status.call_args.args[0].startswith('401'))
            daily._context.assert_not_called()
            env['HTTP_AUTHORIZATION'] = 'Bearer ' + 'a' * 40
            payload = json.loads(b''.join(app(env, status)))
            self.assertTrue(status.call_args.args[0].startswith('200'))
            self.assertEqual(payload['callsCreated'], 0)
            daily._create.assert_not_called()
            daily._dial.assert_not_called()

if __name__ == '__main__': unittest.main()
