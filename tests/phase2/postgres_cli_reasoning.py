"""Five CLI effort values survive API selection and PostgreSQL persistence; no CLI is spawned."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_phase2.cli_runtime import ClaudeCliRuntime
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_alpha.domain import AlphaError

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
def connection(): return psycopg.connect(DSN)
def verify(token): return ONE
verify.session_id = lambda token, principal: 'session-one-0123456789abcdef'
verify.auth_time = lambda token, principal: __import__('time').time()
class Cli(ClaudeCliRuntime):
    def list_supported_models(self):
        return [{'id': self.model, 'qualified': True, 'label': 'Test CLI', 'route': 'claude-code'}]
    def describe(self): return None
    def dispatch(self, run_id, request, sink):
        self.last = request
        sink.fail('Synthetic run; no executable or model called.')

with connection() as db:
    db.execute(Path('migrations/postriff/017_cli_reasoning.sql').read_text())
service = HostedWorkspaceService(connection, verify)
snap = service.bootstrap('one', 'studio')
wid = snap['workspaceId']
cli = Cli()
service.ideas.runtimes = [cli]
service.ideas.researcher = None
catalog = service.ideas.model_catalog()
assert [v['id'] for v in catalog['models'][0]['reasoning']] == ['low','medium','high','xhigh','max']
for level in ['low','medium','high','xhigh','max','quick','standard','deep']:
    snap = service.get(wid, 'one')
    result = service.ideas.quick_start(wid, 'one', snap['revision'], {'text':f'A note from my work for {level}.', 'ownContent':True, 'confirmUse':True, 'model':cli.model, 'reasoning':level})
    expected = cli.effort(level)
    assert cli.last['reasoning'] == expected
    with connection() as db:
        assert db.execute('SELECT reasoning FROM public.pr_agent_runs WHERE id=%s', (result['runId'],)).fetchone()[0] == expected
before = service.get(wid, 'one')['revision']
try:
    service.ideas.quick_start(wid, 'one', before, {'text':'Invalid effort', 'confirmUse':True, 'model':cli.model, 'reasoning':'ultra'})
    raise AssertionError('invalid effort accepted')
except AlphaError as error:
    assert error.status == 400
assert service.get(wid, 'one')['revision'] == before
print('PASS: five CLI levels, legacy aliases, SQL persistence, invalid effort before source mutation; no model calls')
