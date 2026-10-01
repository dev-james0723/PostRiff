import io
import json
import unittest
from postriff_phase2.hosted_app import HostedApplication

class RequestLogsTest(unittest.TestCase):
    def test_handled_voice_failure_logs_only_safe_code_and_masked_route(self):
        from postriff_alpha.domain import AlphaError
        app = HostedApplication()
        def failed():
            raise AlphaError('PRIVATE provider response and credentials', 502, code='live_forbidden')
        app._runtime = failed
        result = {}
        def start(status, headers): result.update(status=status, headers=dict(headers))
        with self.assertLogs('postriff.request', level='INFO') as logs:
            body = b''.join(app({'REQUEST_METHOD': 'POST',
                'PATH_INFO': '/api/workspaces/5f0c1a52-8f3e-4b8e-9a53-0f5c2e1f9a10/agent/voice/sessions',
                'QUERY_STRING': 'PRIVATE', 'HTTP_X_REQUEST_ID': 'PRIVATE', 'HTTP_X_POSTRIFF_REQUEST': 'founder-alpha',
                'HTTP_HOST': 'rafii.test', 'wsgi.input': io.BytesIO()}, start))
        self.assertEqual(result['status'], '502 Bad Gateway')
        record = json.loads(logs.records[-1].getMessage())
        self.assertEqual(record['errorCode'], 'live_forbidden')
        self.assertEqual(record['routePattern'], '/api/workspaces/:id/agent/voice/sessions')
        self.assertNotIn('PRIVATE', json.dumps(record))
        self.assertNotIn('5f0c1a52', json.dumps(record))
        self.assertEqual(record['requestId'], result['headers']['X-Request-ID'])

    def test_handled_voice_failure_cannot_log_arbitrary_error_code(self):
        from postriff_alpha.domain import AlphaError
        app = HostedApplication()
        def failed(): raise AlphaError('Private message', 502, code='SECRET_INJECTED_CODE')
        app._runtime = failed
        with self.assertLogs('postriff.request', level='INFO') as logs:
            app({'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/workspaces/private-id/agent/voice/sessions/private-session/end',
                 'HTTP_X_POSTRIFF_REQUEST': 'founder-alpha', 'HTTP_HOST': 'rafii.test',
                 'wsgi.input': io.BytesIO()}, lambda *_: None)
        record = json.loads(logs.records[-1].getMessage())
        self.assertEqual(record['errorCode'], 'other')
        self.assertEqual(record['routePattern'], '/api/workspaces/:id/agent/voice/sessions/:id/end')
        self.assertNotIn('SECRET', json.dumps(record))
        self.assertNotIn('private-id', json.dumps(record))

    def test_private_exception_does_not_reach_logs_and_request_id_is_server_generated(self):
        app=HostedApplication()
        def failed():raise RuntimeError('PRIVATE provider token')
        app._runtime=failed
        result={}
        def start(status,headers):result.update(status=status,headers=dict(headers))
        with self.assertLogs('postriff.request',level='INFO') as logs:
            body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/api/auth/config','QUERY_STRING':'PRIVATE','HTTP_X_REQUEST_ID':'PRIVATE','wsgi.input':io.BytesIO()},start))
        self.assertEqual(result['status'],'500 Internal Server Error')
        request_id=result['headers']['X-Request-ID']
        self.assertRegex(request_id,r'^[a-f0-9]{32}$')
        self.assertNotIn('PRIVATE',str(logs.output)+body.decode())
        record=json.loads(logs.records[0].getMessage())
        self.assertEqual(record['requestId'],request_id)
        self.assertEqual(record['status'],500)
        self.assertEqual(set(record),{'event','requestId','method','status','durationMs','route','exceptionType','routePattern'})
        self.assertEqual((record['exceptionType'],record['routePattern']),('RuntimeError','/api/auth/config'))

    def test_route_pattern_masks_identifiers(self):
        from postriff_phase2.hosted_app import route_pattern
        self.assertEqual(route_pattern('/api/workspaces/5f0c1a52-8f3e-4b8e-9a53-0f5c2e1f9a10/ideas/runs/0123456789abcdef0123/events'),'/api/workspaces/:id/ideas/runs/:id/events')
        self.assertEqual(route_pattern('/api/invitations/AbCdEfGhIjKlMnOpQrStUvWxYz012345/accept'),'/api/invitations/:id/accept')
        self.assertEqual(route_pattern('/api/workspaces/abc/billing/credit-checkout'),'/api/workspaces/abc/billing/credit-checkout')

    def test_cron_failure_records_source_location_without_private_exception_data(self):
        from test_postriff_phase2_hosted import FakeService, invoke
        class FailingWorker:
            def tick(self):
                raise TypeError("PRIVATE payload and credentials")
        app = HostedApplication(FakeService(), FailingWorker(), {}, "c" * 24)
        with self.assertLogs("postriff.request", level="INFO") as logs:
            status, _, body = invoke(app, "GET", "/api/cron/worker", headers={"Authorization": "Bearer " + "c" * 24})
        self.assertEqual(status, 500)
        record = json.loads(logs.records[-1].getMessage())
        self.assertRegex(record["failureSite"], r"^postriff_phase2\.hosted_app:_handle:\d+$")
        self.assertEqual(record["exceptionType"], "TypeError")
        self.assertNotIn("PRIVATE", str(logs.output) + json.dumps(body))
