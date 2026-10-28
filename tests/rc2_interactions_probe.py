"""POST /api/discord/interactions with Discord's user-install feature off, run with ONE source tree; prints JSON (PR-1).

    python tests/rc2_interactions_probe.py <tree>

tests/test_rc2_shared_path_fixes.py runs it with the live tree (c5fc1fd1, which has no such route) and with this tree.
Each case sends the request through HostedApplication.__call__, as the serverless entry point does, and records the
status, the error code, the level of the request.completed log line and whether the hosted runtime (database, identity
and provider clients) was started. No database, network or credential.

  cold     a new process: no runtime built yet, the feature flag unset
  (each case also sends a GET, a POST over http and a text/plain POST: "variants")
  warm     a process whose runtime is already running, with Discord mounted and its user-install flag off (Production)
  killed   the same with the Discord kill switch on (execution disabled)
  absent   the same with no Discord adapter mounted at all
"""
import io
import json
import logging
import os
import sys
from types import SimpleNamespace

tree = sys.argv[1]
sys.path.insert(0, os.path.join(tree, 'src'))
os.environ.pop('POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED', None)
from postriff_phase2 import hosted_app  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402

started = []
hosted_app.runtime_from_environment = lambda *a, **k: started.append(1) or (_ for _ in ()).throw(RuntimeError('runtime started'))


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.levels = []

    def emit(self, record):
        if '"request.completed"' in record.getMessage():
            self.levels.append(record.levelname)


def send(app, body=b'{"type":1,"application_id":"123456789012345678"}', signed=True, method='POST', scheme='https',
         content_type='application/json'):
    capture = Capture()
    logging.getLogger('postriff.request').addHandler(capture)
    statuses = []
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': '/api/discord/interactions', 'wsgi.url_scheme': scheme,
               'CONTENT_TYPE': content_type, 'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body),
               'HTTP_HOST': 'rafii.invalid', 'REMOTE_ADDR': '203.0.113.9'}
    if signed:
        environ.update(HTTP_X_SIGNATURE_TIMESTAMP='1800000000', HTTP_X_SIGNATURE_ED25519='00' * 64)
    try:
        raw = b''.join(app(environ, lambda status, headers, exc_info=None: statuses.append(int(status.split()[0]))))
    finally:
        logging.getLogger('postriff.request').removeHandler(capture)
    try:
        code = json.loads(raw).get('code')
    except ValueError:
        code = None
    return {'status': statuses[-1], 'code': code, 'logLevels': capture.levels}


def service(providers):
    oauth = SimpleNamespace(providers=providers, repository=SimpleNamespace(connection_factory=None),
                            public_base_url='https://rafii.invalid')
    return SimpleNamespace(oauth=oauth)


def discord(user_install, execution):
    return SimpleNamespace(client_id='123456789012345678', user_install_v1_enabled=user_install,
                           execution_enabled=execution, interaction_config_raw=None)


record = {}
for name, app in (('cold', HostedApplication()),
                  ('warm', HostedApplication(service=service({'discord': discord(False, True)}))),
                  ('killed', HostedApplication(service=service({'discord': discord(True, False)}))),
                  ('absent', HostedApplication(service=service({})))):
    started.clear()
    record[name] = {**send(app), 'unsigned': send(app, signed=False)['status'], 'runtimeStarted': bool(started)}
    # Other methods, schemes and bodies on the same path (statuses only; the live tree answers GET through its
    # session path, which needs the runtime this probe refuses to start).
    started.clear()
    record[name]['variants'] = {'get': send(app, method='GET')['status'], 'http': send(app, scheme='http')['status'],
                                'textPlain': send(app, content_type='text/plain')['status'],
                                'runtimeStarted': bool(started)}
print(json.dumps(record, sort_keys=True))
