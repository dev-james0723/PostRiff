"""FINAL-04 on disposable PostgreSQL: an image made by a provider outside the approved set is not kept, the
member's media credit is given back, and the known provider cost is booked (not left as unknown). A normal
image whose cost is reported only in gateway metadata settles as actual instead of waiting for
reconciliation. Synthetic transport only; no provider is called.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.image_runtime import GatewayImageRuntime, ImageGenerationError
from consumer_fixtures import approve_budgets

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic-image'
clock = [1_800_000_000.0]


def connection():
    return psycopg.connect(DSN)


def verify(token):
    if token != 'one':
        raise AlphaError('Verified session required.', 401)
    return ONE


verify.session_id = lambda token, principal: 'image-routing-session'
verify.auth_time = lambda token, principal: clock[0]


class Transport:
    def __init__(self):
        self.reply = None
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append(kwargs['body'])
        return self.reply


class Assets:
    """Private media storage double: keeps staged bytes in memory."""

    def __init__(self):
        self.staged = {}

    def stage_upload(self, workspace_id, payload):
        raw = base64.b64decode(payload['data'])
        asset = {'id': f'img-{len(self.staged) + 1}', 'hash': f'h{len(self.staged) + 1}', 'mime': 'image/png', 'width': 1, 'height': 1, 'bytes': len(raw), 'processing': 'decoded', 'deleted': False, 'name': 'generated.png'}
        self.staged[asset['id']] = raw
        return asset

    def remove(self, workspace_id, asset):
        self.staged.pop(asset['id'], None)


def reply(provider, cost):
    return {'status': 200, 'body': {'data': [{'b64_json': base64.b64encode(PNG).decode()}], 'providerMetadata': {'gateway': {'routing': {'finalProvider': provider}, 'cost': cost}}}}


transport = Transport()
runtime = GatewayImageRuntime('synthetic-key', 'openai/gpt-image-2', transport=transport)
service = HostedWorkspaceService(connection, verify, assets=Assets(), image_runtime=runtime, clock=lambda: clock[0])
wid = service.bootstrap('one', 'studio')['workspaceId']
approve_budgets(connection, wid)
conversation = service.ideas.create_conversation(wid, 'one', 'Images')['conversationId']


def media_credits():
    with connection() as db:
        return db.execute('SELECT media_credits_remaining FROM pr_entitlements WHERE workspace_id=%s', (wid,)).fetchone()[0]


def ledger_for(run_id):
    with connection() as db:
        return db.execute("SELECT kind,cost_state,actual_usd_micro FROM pr_usage_ledger WHERE workspace_id=%s AND run_id::text=%s ORDER BY at,kind", (wid, run_id)).fetchall()


def run_of(key):
    with connection() as db:
        return db.execute('SELECT id::text,status FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s', (wid, key)).fetchone()


checks = []
with connection() as db:
    service.ledger.ensure_entitlement(db.cursor(), wid, None)
before = media_credits()

# 1. Served outside the approved set: refused, credit returned, known cost booked as released.
transport.reply = reply('runware', '0.05')
try:
    service.ideas.turn(wid, 'one', conversation, {'text': 'A red piano on cream paper', 'imageGeneration': True, 'idempotencyKey': 'image-outside'})
except ImageGenerationError as error:
    assert 'outside' in str(error), error
else:
    raise AssertionError('an image served by an unapproved provider was kept')
assert transport.calls[-1]['providerOptions'] == {'gateway': {'only': ['openai']}}, transport.calls[-1]
run_id, status = run_of('image-outside')
assert status == 'failed', status
rows = ledger_for(run_id)
assert ('release', 'released', 50_000) in rows and not any(r[1] == 'estimated_unknown' for r in rows), rows
assert media_credits() == before, (before, media_credits())
assert not service.ideas.assets.staged, 'no image bytes were kept'
checks.append('an image made outside the approved providers is not kept; the media credit is given back and the known $0.05 provider cost is booked, not left unknown')

# 2. Approved provider, cost only in gateway metadata: completed and settled as actual.
transport.reply = reply('openai', '0.04')
service.ideas.turn(wid, 'one', conversation, {'text': 'A quiet practice room', 'imageGeneration': True, 'idempotencyKey': 'image-approved'})
run_id, status = run_of('image-approved')
assert status == 'completed', status
rows = ledger_for(run_id)
assert ('settle', 'actual', 40_000) in rows and not any(r[1] == 'estimated_unknown' for r in rows), rows
with connection() as db:
    usage = db.execute('SELECT usage FROM pr_agent_runs WHERE id::text=%s', (run_id,)).fetchone()[0]
assert usage.get('executionProvider') == 'openai' and usage.get('provenance') == 'provider_reported', usage
checks.append('an approved image whose cost is reported only in gateway metadata settles as actual ($0.04) with the serving provider recorded, instead of waiting for reconciliation')

for line in checks:
    print('PASS:', line)
