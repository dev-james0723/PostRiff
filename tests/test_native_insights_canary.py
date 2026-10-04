import json
import io
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.metric_schedule import MetricScheduler, NATIVE_ANALYTICS_SCOPES
from postriff_phase2.providers import InstagramProvider


class NativeCanary(unittest.TestCase):
    def setUp(self):
        self.calls, self.audits = [], []
        self.role, self.eligible = "owner", "read"
        self.reply = {"status": 200, "body": {"data": [{"name": "reach", "values": [{"value": 17}]}]}}
        self.media = {"status": 200, "body": {"data": [{"id": "123456", "caption": "DO NOT RETAIN"}, {"id": "999"}],
                                                   "paging": {"next": "https://untrusted.invalid"}}}
        outer = self
        class Cur:
            def execute(self, *args): pass
            def fetchone(self): return ("instagram", "account-1")
        class Repo:
            @contextmanager
            def transaction(self, token, wid):
                if wid != "admitted" or token not in ("signed-in", "synthetic-session-" + "x" * 30):
                    raise AlphaError("Workspace unavailable.", 404)
                yield Cur(), (1, {}, outer.role, False, False, False, False), "actor"
        adapter = InstagramProvider("synthetic-client", "synthetic-secret")
        adapter.identity = lambda token: {"providerAccountId": "account-1"}
        self.grant = {"provider": "instagram", "accessToken": "synthetic-private-token",
                      "scopes": list(NATIVE_ANALYTICS_SCOPES["instagram"])}
        oauth = SimpleNamespace(repository=Repo(), providers={"instagram": adapter}, token_for_worker=lambda *args: self.grant)
        def transport(method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.media if "/media?" in url else self.reply
        self.scheduler = MetricScheduler(None, oauth, transport=transport, workspace_allowlist={"admitted"})
        self.scheduler._eligibility = lambda *args, **kwargs: self.eligible
        self.scheduler._eligible = lambda *args: self.eligible
        self.audit_patch = patch("postriff_phase2.hosted.audit", side_effect=lambda *args: self.audits.append(args[-1]))
        self.throttle_patch = patch("postriff_phase2.hosted.throttle")
        self.audit_patch.start(); self.throttle_patch.start()
        self.addCleanup(self.audit_patch.stop); self.addCleanup(self.throttle_patch.stop)

    def probe(self, payload=None, token="signed-in", wid="admitted"):
        return self.scheduler.probe(wid, token, "connection", {"confirmed": True} if payload is None else payload)

    def test_current_paid_admission_uses_locked_customer_cursor_and_revocation_has_no_calls(self):
        from unittest.mock import Mock
        access = SimpleNamespace(allowed=Mock(return_value=True))
        self.scheduler.customer_access = access
        self.scheduler.oauth.providers["instagram"].production_reviewed = True
        self.assertEqual(self.probe()['state'], 'done')
        self.assertIn('cursor', access.allowed.call_args_list[0].kwargs)
        self.assertIsNotNone(access.allowed.call_args_list[0].kwargs['cursor'])
        self.calls.clear()
        access.allowed.return_value = False
        with self.assertRaises(AlphaError): self.probe()
        self.assertEqual(self.calls, [])

    def test_host_mounts_canary_on_same_customer_policy_with_metric_cron_off(self):
        from unittest.mock import Mock
        from postriff_phase2.hosted_app import runtime_from_environment
        from postriff_phase2.oauth import CredentialVault
        values = {'POSTRIFF_CUSTOMER_STUDIO_ENABLED': '1', 'POSTRIFF_METRIC_READS': '0',
                  'POSTRIFF_DATABASE_URL': 'postgresql://synthetic@127.0.0.1:1/postgres',
                  'POSTRIFF_SUPABASE_URL': 'https://synthetic.supabase.co',
                  'POSTRIFF_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_' + 's' * 32,
                  'POSTRIFF_SUPABASE_SECRET_KEY': 'sb_secret_' + 's' * 32,
                  'POSTRIFF_CREDENTIAL_KEY': CredentialVault.generate_key()}
        no_io = Mock(side_effect=AssertionError('This configuration-only test forbids all DB/provider I/O'))
        with patch('postriff_phase2.hosted_app.postgres_factory', return_value=no_io):
            service, worker, _ = runtime_from_environment(values)
        self.assertIs(service.metric_probe.customer_access, service.customer_access)
        self.assertIsNone(getattr(service, 'metric_reads', None))
        self.assertFalse(service.metric_probe.provider_allowed('instagram'))
        no_io.assert_not_called()

    def test_one_post_and_one_insights_get_without_following_pages_or_retaining_content(self):
        result = self.probe()
        self.assertEqual((result["state"], result["http"], result["found"]), ("done", 200, {"reach": 17}))
        self.assertEqual(len(self.calls), 2)
        self.assertIn("fields=id&limit=1", self.calls[0][1])
        self.assertIn("/123456/insights?", self.calls[1][1])
        self.assertNotIn("synthetic-private-token", json.dumps(result) + json.dumps(self.audits))
        self.assertNotIn("DO NOT RETAIN", json.dumps(result) + json.dumps(self.audits))
        self.assertEqual(self.audits[-1]["availableMetrics"], ["reach"])

    def test_requires_strict_consent_interactive_session_and_connection_management(self):
        for payload in ({}, {"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"}):
            with self.assertRaises(AlphaError): self.probe(payload)
        with self.assertRaises(AlphaError) as caught: self.probe(token="prt_synthetic")
        self.assertEqual(caught.exception.code, "interactive_required")
        self.role = "viewer"
        with self.assertRaises(AlphaError): self.probe()
        self.assertEqual(self.calls, [])

    def test_foreign_or_unadmitted_workspace_has_no_provider_calls(self):
        with self.assertRaises(AlphaError): self.probe(wid="foreign")
        self.scheduler.workspace_allowlist = frozenset()
        with self.assertRaises(AlphaError): self.probe()
        self.assertEqual(self.calls, [])

    def test_purge_or_revocation_and_missing_live_scopes_prevent_provider_calls(self):
        self.eligible = "cancel"
        with self.assertRaises(AlphaError): self.probe()
        self.eligible = "read"
        self.grant["scopes"] = ["instagram_business_basic"]
        self.assertEqual(self.probe()["state"], "cancelled")
        self.assertEqual(self.calls, [])

    def test_empty_invalid_or_malformed_media_never_calls_insights(self):
        for data in ([], {}, [{"id": "../../secret"}], [{"id": 123}], [{"id": "9" * 201}]):
            self.calls.clear(); self.media = {"status": 200, "body": {"data": data}}
            self.assertEqual(self.probe()["state"], "unavailable")
            self.assertEqual(len(self.calls), 1)

    def test_empty_metrics_and_provider_denials_never_claim_success(self):
        for reply in ({"status": 200, "body": {"data": []}}, {"status": 403, "body": {"error": "PRIVATE"}}):
            self.reply = reply
            result = self.probe()
            self.assertNotEqual(result["state"], "done")
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_revocation_during_identity_prevents_media_and_insights_dispatch(self):
        def identity(token):
            self.eligible = 'cancel'
            return {'providerAccountId': 'account-1'}
        self.scheduler.oauth.providers['instagram'].identity = identity
        self.assertEqual(self.probe()['state'], 'cancelled')
        self.assertEqual(self.calls, [])

    def test_token_expiry_during_identity_prevents_media_and_insights_dispatch(self):
        def identity(token):
            self.grant['expiresAt'] = self.scheduler.clock() - 1
            return {'providerAccountId': 'account-1'}
        self.scheduler.oauth.providers['instagram'].identity = identity
        self.assertEqual(self.probe()['state'], 'cancelled')
        self.assertEqual(self.calls, [])

    def test_disconnect_during_read_suppresses_result_values(self):
        def transport(method, url, **kwargs):
            if "/insights?" in url: self.eligible = "cancel"; return self.reply
            return self.media
        self.scheduler.transport = transport
        result = self.probe()
        self.assertEqual((result["state"], result["found"]), ("cancelled", {}))

    def test_provider_exception_text_is_never_returned_or_logged(self):
        self.scheduler.transport = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic-private-token"))
        with self.assertLogs("postriff.growth.metric_reads", "WARNING") as logs: result = self.probe()
        self.assertNotIn("synthetic-private-token", json.dumps(result) + "".join(logs.output))

    def test_hosted_route_keeps_mutation_guard_and_does_not_run_other_workers(self):
        from postriff_phase2.hosted_app import HostedApplication
        from unittest.mock import Mock
        worker = Mock()
        app = HostedApplication(SimpleNamespace(oauth=self.scheduler.oauth, metric_probe=self.scheduler), worker)
        raw = b'{"confirmed":true}'
        def request(guard):
            captured = {}
            environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/workspaces/admitted/channels/connection/insights-canary",
                       "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
                       "wsgi.url_scheme": "https", "HTTP_HOST": "postriff.example", "HTTP_ORIGIN": "https://postriff.example",
                       "HTTP_AUTHORIZATION": "Bearer synthetic-session-" + "x" * 30, "HTTP_X_POSTRIFF_REQUEST": guard}
            body = b"".join(app(environ, lambda status, headers: captured.update(status=status)))
            return captured["status"], json.loads(body)
        status, _ = request("")
        self.assertTrue(status.startswith("403")); self.assertEqual(self.calls, [])
        status, body = request("founder-alpha")
        self.assertTrue(status.startswith("200"), body); self.assertEqual(body["state"], "done")
        worker.tick.assert_not_called()


if __name__ == "__main__": unittest.main()
