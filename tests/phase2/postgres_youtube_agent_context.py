"""Cloud-only, disposable PostgreSQL provider-context retention/fence checks.

No external provider, authentication endpoint, model or production database is
called. Uses the real journal fence, chat persistence and disconnect purge hook.
"""
import copy
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.agent_runtime_v2 import config, contracts
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.ideas import IdeasService
from postriff_phase2.youtube import agent_context as private
from postriff_phase2.youtube.journal import UploadJournal, purge_authorized_data

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = time.time()
ACTOR, ONE, TWO = (str(uuid4()) for _ in range(3))
CHANNEL = 'UC' + 'p' * 22
CONNECTION, OTHER_CONNECTION = 'youtube-context-one', 'youtube-context-two'
WORDS = 'Native YouTube views were 918273 on 2026-09-01.'


@contextmanager
def connection():
    with psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                         options='-c statement_timeout=10000 -c lock_timeout=8000') as db:
        assert db.info.host == '127.0.0.1' and db.info.port == 55438 and db.info.dbname == 'postgres'
        yield db


ideas = IdeasService(None, None, runtimes=[], researcher=False)
service = SimpleNamespace(ideas=ideas, youtube=SimpleNamespace(journal=UploadJournal(connection, None)), clock=lambda: NOW)
runtime = AgentRuntimeService(service, cfg=config.RuntimeConfig.from_environment({}), model_factory=lambda: None)

with connection() as db:
    for workspace in (ONE, TWO):
        db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (workspace,))
    conversations = {workspace: db.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text',
                                         (workspace, ACTOR, 'Synthetic context retention')).fetchone()[0] for workspace in (ONE, TWO)}
    generations = {}
    for workspace, connection_id, channel in ((ONE, CONNECTION, CHANNEL), (ONE, OTHER_CONNECTION, 'UC' + 'q' * 22), (TWO, CONNECTION, CHANNEL)):
        generations[workspace, connection_id] = db.execute('INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) '
            "VALUES(%s,%s,'youtube',%s,'synthetic-never-decrypted','synthetic',ARRAY[]::text[]) RETURNING authorization_generation::text",
            (workspace, connection_id, channel)).fetchone()[0]


def new_run(cur, workspace, artifact=None, key_prefix='agent:'):
    return cur.execute('INSERT INTO public.pr_agent_runs(workspace_id,conversation_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) '
        "VALUES(%s,%s,%s,'running','synthetic','standard',%s,%s,%s,%s::jsonb) RETURNING id::text",
        (workspace, conversations[workspace], ACTOR, '0' * 64, '1' * 64, key_prefix + uuid4().hex, json.dumps(artifact))).fetchone()[0]


def native_result(workspace=ONE, connection_id=CONNECTION, channel=CHANNEL, *, ingested_at=NOW, generation=None):
    value = contracts.empty_result(contracts.new_trace_id(), 'text')
    value.update(answerText=WORDS, speakableSummary=WORDS, composedBy='manager', facts=[{'kind': 'youtube_native_analytics',
        'evidence': {'connectionId': connection_id, 'channelId': channel, 'nativeObservations': [{'day': '2026-09-01', 'views': 918273}]}}])
    value[private.KEY] = [private.source(workspace, connection_id, channel, generation or generations[workspace, connection_id], ingested_at)]
    return value


def persist(workspace, value, *, clock=NOW):
    runtime.clock = lambda: clock
    with connection() as db, db.cursor() as cur:
        # HostedRepository.transaction takes this same lock before _persist.
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
        run_id = new_run(cur, workspace)
        runtime._persist(cur, workspace, conversations[workspace], run_id, copy.deepcopy(value),
            [{'type': 'text', 'text': value['answerText']}], [], [], trace={'traceId': value['traceId'], 'extension': WORDS}, status='completed', usage={'billing': 'synthetic'})
    runtime.clock = lambda: NOW
    return run_id


def bodies(workspace, run_id):
    with connection() as db:
        message = db.execute("SELECT body FROM public.pr_messages WHERE workspace_id=%s AND run_id::text=%s AND role='assistant'", (workspace, run_id)).fetchone()[0]
        artifact = db.execute('SELECT artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s', (workspace, run_id)).fetchone()[0]
        events = db.execute('SELECT kind,body FROM public.pr_agent_events WHERE workspace_id=%s AND run_id::text=%s ORDER BY seq', (workspace, run_id)).fetchall()
    return message, artifact, events


def contains_native(value):
    return '918273' in json.dumps(value)


main_run = persist(ONE, native_result())
other_channel_run = persist(ONE, native_result(connection_id=OTHER_CONNECTION, channel='UC' + 'q' * 22))
foreign_run = persist(TWO, native_result(workspace=TWO))
with connection() as db, db.cursor() as cur:
    unrelated_user = ideas._append_message(cur, ONE, conversations[ONE], 'user', {'text': 'My own notes quote 918273; keep my message.'})['messageId']
    unrelated_assistant = ideas._append_message(cur, ONE, conversations[ONE], 'assistant', {'text': 'An unrelated customer campaign answer.'})['messageId']
    unknown_legacy = ideas._append_message(cur, ONE, conversations[ONE], 'assistant', {'text': 'Historical freeform notes mentioning YouTube; provenance is unknown.'})['messageId']
    # Deterministically attributed old facts can be scrubbed; another channel on
    # the same old connection cannot be inferred to be this authorized channel.
    legacy_ids = []
    for channel in (CHANNEL, 'UC' + 'r' * 22):
        legacy = native_result(channel=channel)
        legacy.pop(private.KEY)
        legacy_ids.append(ideas._append_message(cur, ONE, conversations[ONE], 'assistant', {'text': WORDS, 'agent': legacy})['messageId'])
    task_id = new_run(cur, ONE, {'task': {'title': 'Unrelated earlier task'}, 'pendingRun': {'state': WORDS, private.KEY: native_result()[private.KEY]}}, key_prefix='task:')

baseline = bodies(ONE, main_run)
try:
    with connection() as db, db.cursor() as cur:
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
        purge_authorized_data(cur, ONE, CONNECTION)
        cur.execute("SELECT body->>'text' FROM public.pr_messages WHERE workspace_id=%s AND run_id::text=%s AND role='assistant'", (ONE, main_run))
        assert cur.fetchone()[0] == private.NOTICE
        raise RuntimeError('Synthetic rollback after scrub.')
except RuntimeError as error:
    assert str(error) == 'Synthetic rollback after scrub.'
assert bodies(ONE, main_run) == baseline, 'Purge must roll back with the revocation transaction.'

with connection() as db, db.cursor() as cur:
    cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ONE,))
    cur.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (ONE, CONNECTION))
    purge_authorized_data(cur, ONE, CONNECTION)
assert not contains_native(bodies(ONE, main_run)), 'Assistant text, facts, artifact result, trace extension and events must all be scrubbed.'
assert contains_native(bodies(ONE, other_channel_run)), 'Another channel in this workspace must survive.'
assert contains_native(bodies(TWO, foreign_run)), 'Another tenant with identical channel/connection labels must survive.'
with connection() as db:
    for identifier in (unrelated_user, unrelated_assistant, unknown_legacy):
        body = db.execute('SELECT body FROM public.pr_messages WHERE workspace_id=%s AND id::text=%s', (ONE, identifier)).fetchone()[0]
        assert not body.get(private.REMOVED), 'Never guess provenance from user or freeform text.'
    assert db.execute('SELECT body->>\'text\' FROM public.pr_messages WHERE id::text=%s', (legacy_ids[0],)).fetchone()[0] == private.NOTICE
    assert db.execute('SELECT body->>\'text\' FROM public.pr_messages WHERE id::text=%s', (legacy_ids[1],)).fetchone()[0] == WORDS
    task = db.execute('SELECT artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s', (ONE, task_id)).fetchone()[0]
    assert 'pendingRun' not in task and task['task']['title'] == 'Unrelated earlier task'

late_run = persist(ONE, native_result())
assert not contains_native(bodies(ONE, late_run)), 'An already-running model response cannot recreate revoked data.'
with connection() as db:
    generations[ONE, CONNECTION] = db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=NULL,provider_account_id=%s,youtube_identity_ingested_at=to_timestamp(%s),authorization_generation=gen_random_uuid() '
        'WHERE workspace_id=%s AND connection_id=%s RETURNING authorization_generation::text', (CHANNEL, NOW, ONE, CONNECTION)).fetchone()[0]
stale_run = persist(ONE, native_result(generation=baseline[1]['result'][private.KEY][0]['authorizationGeneration']))
assert not contains_native(bodies(ONE, stale_run)), 'Replacement consent cannot revive old model context.'
fresh_run = persist(ONE, native_result())
assert contains_native(bodies(ONE, fresh_run))

expired_at = NOW - 31 * 86400
expired_run = persist(ONE, native_result(ingested_at=expired_at), clock=expired_at)
with connection() as db, db.cursor() as cur:
    expired_task = new_run(cur, ONE, {'task': {'title': 'Keep this earlier task'},
        'pendingRun': {'state': WORDS, private.KEY: native_result(ingested_at=expired_at)[private.KEY]}}, key_prefix='task:')
    expired_legacy = native_result()
    expired_legacy.pop(private.KEY)
    expired_legacy_run = new_run(cur, ONE, {'result': expired_legacy})
    expired_legacy_message = ideas._append_message(cur, ONE, conversations[ONE], 'assistant', {'text': WORDS, 'agent': expired_legacy}, expired_legacy_run)['messageId']
    cur.execute('UPDATE public.pr_agent_runs SET created_at=to_timestamp(%s) WHERE id::text=%s', (expired_at, expired_legacy_run))
    cur.execute('UPDATE public.pr_messages SET created_at=to_timestamp(%s) WHERE id::text=%s', (expired_at, expired_legacy_message))
    private.purge_expired(cur, now=NOW)
assert not contains_native(bodies(ONE, expired_run)), 'Scheduled cleanup must remove expired native context copies.'
assert not contains_native(bodies(ONE, expired_legacy_run)), 'Deterministically attributed old native facts also expire.'
with connection() as db:
    expired_state = db.execute('SELECT artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s', (ONE, expired_task)).fetchone()[0]
    assert 'pendingRun' not in expired_state and expired_state['task']['title'] == 'Keep this earlier task'
assert contains_native(bodies(ONE, fresh_run)), 'Fresh exact-grant data remains visible until deletion or expiry.'
with connection() as db, db.cursor() as cur:
    history = runtime._history(cur, ONE, conversations[ONE])
    # The person's own text remains eligible. No assistant native analytics,
    # including still-authorized fresh answers, enters a later AI request.
    assert all('918273' not in item['text'] for item in history if item['role'] == 'assistant')

print(json.dumps({'script': 'postgres_youtube_agent_context', 'status': 'passed', 'execution': 'disposable_postgres_synthetic_providers',
                  'cases': ['exact_connection', 'foreign_tenant', 'unrelated_human_and_customer_text', 'legacy_native_fact_attribution',
                            'message_run_event_state_copies', 'transaction_rollback', 'late_revoked_persistence', 'replacement_generation',
                            'fresh_generation', 'scheduled_expiry', 'ai_history_exclusion']}), flush=True)
