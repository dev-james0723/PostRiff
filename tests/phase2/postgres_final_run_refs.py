"""FINAL-02 on disposable PostgreSQL: a draft refreshed in place by a later run keeps that run's reference
after the proposal is edited, so reopening the run (?run=) can show the saved text. Free preview writer only."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token != 'one':
        raise AlphaError('Verified session required.', 401)
    return ONE


verify.session_id = lambda token, principal: 'run-refs-session'
verify.auth_time = lambda token, principal: clock[0]
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
wid = service.bootstrap('one', 'studio')['workspaceId']
destinations = [{'platform': 'LinkedIn', 'language': 'en-US'}]


def draft(text, key):
    latest = service.get(wid, 'one')
    run = service.ideas.quick_start(wid, 'one', latest['revision'], {'text': text, 'ownContent': True, 'confirmUse': True, 'destinations': destinations, 'idempotencyKey': key})
    assert run['status'] == 'completed', run
    latest = service.get(wid, 'one')
    service.ideas.apply(wid, 'one', latest['revision'], run['runId'], run['artifactHash'])
    return run['runId']


first = draft('A first thought about practice.', 'refs-1')
second = draft('A second, different thought about practice.', 'refs-2')
variants = service.get(wid, 'one')['state']['variants']
slot = [v for v in variants if v['platform'] == 'LinkedIn']
assert len(slot) == 1, [v.get('provenance') for v in variants]
draft_variant = slot[0]
assert draft_variant['provenance']['runId'] == first and draft_variant['proposedUpdate']['runId'] == second, draft_variant
assert draft_variant['runRefs'] == [second], draft_variant.get('runRefs')
latest = service.get(wid, 'one')
service.mutate(wid, 'one', latest['revision'], 'variant_edit', {'variantId': draft_variant['id'], 'variantRevision': draft_variant['revision'], 'text': 'My reviewed words.'})
edited = next(v for v in service.get(wid, 'one')['state']['variants'] if v['id'] == draft_variant['id'])
assert edited['proposedUpdate'] is None and edited['runRefs'] == [second] and edited['text'] == 'My reviewed words.', edited
print('PASS: a refreshed draft keeps the refreshing run in runRefs through the edit that accepts it')
