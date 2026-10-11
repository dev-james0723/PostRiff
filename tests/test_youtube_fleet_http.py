"""Fleet routes accept server cron authority only, before application runtime initialization."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from postriff_phase2.hosted_app import HostedApplication


def invoke(app, suffix, authorization='', method='GET', query=''):
    result = {}
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': '/api/cron/youtube/' + suffix,
               'QUERY_STRING': query, 'HTTP_AUTHORIZATION': authorization,
               'wsgi.input': io.BytesIO(), 'CONTENT_LENGTH': '0'}

    def response(status, headers):
        result['status'] = int(status.split()[0])
        result['headers'] = dict(headers)

    result['body'] = json.loads(b''.join(app(environ, response)))
    return result


class FleetHttpTest(unittest.TestCase):
    def test_missing_and_user_tokens_do_not_initialize_runtime(self):
        for authorization in ('', 'Bearer dev:someone', 'Bearer prt_not-cron-authority', 'Bearer non-ascii-é'):
            with self.subTest(authorization=authorization):
                app = HostedApplication(cron_secret='c' * 24)
                app._runtime = Mock(side_effect=AssertionError('unauthorized runtime initialization'))
                self.assertEqual(invoke(app, 'uploads', authorization)['status'], 401)
                app._runtime.assert_not_called()

    def test_short_or_missing_server_secret_fails_closed(self):
        for secret in ('', 'short', None):
            with self.subTest(secret=secret), patch.dict('os.environ', {'CRON_SECRET': ''}):
                app = HostedApplication(cron_secret=secret)
                app._runtime = Mock(side_effect=AssertionError('unauthorized runtime initialization'))
                self.assertEqual(invoke(app, 'identity', 'Bearer ' + (secret or ''))['status'], 401)
                app._runtime.assert_not_called()

    def test_cold_start_uses_server_secret_and_fixed_lane(self):
        service, worker = object(), object()
        app = HostedApplication(worker=worker)
        app._runtime = Mock(return_value=service)
        with patch.dict('os.environ', {'CRON_SECRET': 'c' * 24}), patch('postriff_phase2.youtube.fleet.run_lane', return_value={'enabled': False}) as run:
            result = invoke(app, 'uploads', 'Bearer ' + 'c' * 24, query='maxJobs=9999&maxSeconds=9999&lane=planner')
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body'], {'enabled': False})
        self.assertEqual(result['headers']['Cache-Control'], 'no-store')
        run.assert_called_once_with(service, worker, 'upload')

    def test_all_supported_routes_keep_lane_identity(self):
        service, worker = object(), object()
        for suffix, lane in (('uploads', 'upload'), ('identity', 'identity'), ('planner', 'planner')):
            with self.subTest(suffix=suffix):
                app = HostedApplication(service, worker, cron_secret='c' * 24)
                with patch('postriff_phase2.youtube.fleet.run_lane', return_value={'lane': lane}) as run:
                    self.assertEqual(invoke(app, suffix, 'Bearer ' + 'c' * 24)['body'], {'lane': lane})
                run.assert_called_once_with(service, worker, lane)

    def test_other_methods_and_paths_cannot_dispatch(self):
        for suffix, method in (('uploads', 'POST'), ('identity', 'DELETE'), ('planner/extra', 'GET'), ('anything', 'GET')):
            with self.subTest(suffix=suffix, method=method):
                app = HostedApplication(cron_secret='c' * 24)
                app._runtime = Mock(side_effect=AssertionError('invalid route initialization'))
                self.assertEqual(invoke(app, suffix, 'Bearer ' + 'c' * 24, method=method)['status'], 404)
                app._runtime.assert_not_called()
