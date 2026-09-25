import io
import json
import unittest
from postriff_phase2.hosted_app import HostedApplication

class RequestLogsTest(unittest.TestCase):
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
