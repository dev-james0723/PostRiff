"""Real disposable PostgreSQL; synthetic provider measurements, no external calls."""
import copy
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.coworker import flags, runtime, growth_loop

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
USERS = {name: str(uuid.uuid4()) for name in ("owner", "other", "editor", "history")}
clock = [dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc).timestamp()]


def connection(): return psycopg.connect(DSN)
def verify(token): return USERS[token]
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
runtime.attach(service, {name: '1' for name in flags.FLAGS})
with connection() as db:
    for user in USERS.values(): db.execute("INSERT INTO auth.users VALUES(%s)", (user,))
wid = service.bootstrap("owner", "studio")["workspaceId"]
other = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("editor", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (wid, USERS['editor']))
loop = service.coworker.growth_loop


def mutate(fn):
    return service.coworker._command(wid, "owner", lambda state, actor: fn(state), "owner", "growth.test_fixture")


def refused(fn, statuses=(403, 404, 409)):
    try: fn()
    except AlphaError as error:
        assert error.status in statuses, (error.status, str(error))
    else: raise AssertionError("Expected the action to be refused")


def passed(name): print("PASS growth-loop: " + name, flush=True)


mutate(lambda state: state.setdefault('phase2', {}).update({'channels': [{'id': 'channel-one', 'platform': 'Threads', 'configured': True, 'revoked': False, 'expiresAt': clock[0]+90*86400, 'identityVerified': True, 'capabilityVerified': True, 'verifiedAt': clock[0], 'account': '@fixture'}, {'id': 'channel-two', 'platform': 'Threads', 'configured': True, 'revoked': False, 'expiresAt': clock[0]+90*86400, 'identityVerified': True, 'capabilityVerified': True, 'verifiedAt': clock[0], 'account': '@other-fixture'}]}))
payload = {'name': 'Reach our audience', 'goalType': 'follower_growth', 'primaryMetric': 'followers', 'channelId': 'channel-one', 'baselineValue': 10,
           'targetValue': 100, 'targetAt': '2027-01-01', 'idempotencyKey': 'pg-goal-0001'}
goal = loop.create_goal(wid, 'owner', payload)
assert goal['verified'] and loop.create_goal(wid, 'owner', payload)['record']['id'] == goal['record']['id']
assert loop.summary(wid, 'owner')['goal']['currentValue'] is None
refused(lambda: loop.create_goal(wid, 'editor', {**payload, 'idempotencyKey': 'editor-goal'}))
refused(lambda: loop.summary(wid, 'other'))
refused(lambda: loop.goal_status(other, 'other', goal['record']['id'], {'status': 'paused'}))
passed('goal persistence, truthful missing coverage, idempotency and permission/tenant isolation')
loop.goal_status(wid, 'owner', goal['record']['id'], {'status': 'archived'})
consistency = loop.create_goal(wid, 'owner', {**payload, 'name': 'Publish each week', 'goalType': 'consistency', 'primaryMetric': 'verified_posts', 'channelId': None, 'baselineValue': 0, 'idempotencyKey': 'pg-goal-0002'})
assert loop.summary(wid, 'owner')['goal']['currentValue'] == 0
passed('one active primary goal and a real covered zero')

COHORT = {'provider': 'threads', 'connectionId': 'channel-one', 'language': 'en', 'contentTypeId': 'text', 'definitionVersion': '2026-09'}
hypothesis_id = str(uuid.uuid4())
with connection() as db:
    db.execute("""INSERT INTO public.pr_strategy_hypotheses(id,workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,confidence,expires_at,evidence_ids,counter_evidence_ids)
                  VALUES(%s,%s,'Threads','opening',%s::jsonb,'Question openings may reach more people for this account.','views','question','statement',5,5,0.5,'low',to_timestamp(%s),'["old-job"]','[]')""", (hypothesis_id, wid, json.dumps(COHORT), clock[0] + 60 * 86400))
request = {'hypothesisId': hypothesis_id, 'minimumPerArm': 5, 'windowDays': 14, 'idempotencyKey': 'pg-experiment-1'}
# PostgreSQL extract(epoch) returns Decimal; the HTTP view must remain JSON-safe.
with connection() as db:
    db.execute('UPDATE public.pr_strategy_hypotheses SET date_from=to_timestamp(%s),date_to=to_timestamp(%s) WHERE id=%s', (clock[0]-7*86400, clock[0], hypothesis_id))
view = json.loads(json.dumps(service.coworker.performance_view(wid, 'owner')))
assert isinstance(view['hypotheses'][0]['expiresAt'], float)
assert all(isinstance(value, float) for value in view['hypotheses'][0]['dateRange'])
proposed = loop.propose(wid, 'owner', request)['record']
eid = proposed['id']
assert loop.propose(wid, 'owner', request)['record']['id'] == eid
refused(lambda: loop.propose(other, 'other', {**request, 'idempotencyKey': 'foreign-experiment'}))
refused(lambda: loop.experiment_action(wid, 'owner', eid, {'action': 'apply'}))
for action in ('accept', 'prepare', 'start'):
    assert loop.experiment_action(wid, 'owner', eid, {'action': action})['verified']
refused(lambda: loop.experiment_action(wid, 'owner', eid, {'action': 'measure'}))
passed('approved experiment lifecycle, prospective window, no early result or automatic strategy')

start = clock[0]
jobs = []
with connection() as db:
    for index in range(10):
        jid, ref = 'experiment-job-' + str(index), 'experiment-post-' + str(index)
        question = index < 5
        text = 'Would you try this?' if question else 'Here is an observation.'
        published = start + (index + 1) * 86400
        jobs.append({'id': jid, 'state': 'verified', 'variantId': 'v-' + jid, 'providerReference': ref, 'approvedAt': published,
                     'verification': {'method': 'fixture_lookup', 'at': published},
                     'manifest': {'channelId': 'channel-one', 'platform': 'Threads', 'contentType': {'id': 'text'},
                                  'timing': {'timestamp': published, 'timeZone': 'UTC'}, 'payload': {'text': text, 'language': 'en'}}})
        metric = 50 if index == 0 else 200 if question else 100
        db.execute("""INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset)
                      VALUES(%s,'channel-one','threads',%s,%s,'views','2026-09',%s,'count','available',to_timestamp(%s),'24h')""", (wid, ref, jid, metric, published + 86400))
mutate(lambda state: state['phase2'].update({'jobs': jobs}))
clock[0] = start + 15 * 86400
result = loop.experiment_action(wid, 'owner', eid, {'action': 'measure'})['record']
assert result['status'] == 'complete' and result['result']['medianVariant'] == 200 and result['result']['counterEvidenceIds'] == ['experiment-job-0'], result
assert result['result']['causal'] is False
snapshot_before = service.get(wid, 'owner')['state']
assert loop.experiment_action(wid, 'owner', eid, {'action': 'apply'})['verified']
snapshot = service.get(wid, 'owner')['state']
assert snapshot.get('speaker') == snapshot_before.get('speaker') and snapshot.get('learning') == snapshot_before.get('learning')
slot = {'channelId': 'channel-one', 'platform': 'Threads', 'language': 'en', 'contentType': 'text'}
assert growth_loop.planning_context(snapshot, slot, clock[0])['approvedStrategyPreferences']
loop.experiment_action(wid, 'owner', eid, {'action': 'revoke'})
assert not growth_loop.planning_context(service.get(wid, 'owner')['state'], slot, clock[0])['approvedStrategyPreferences']
passed('PostgreSQL metric observations → robust measured result → explicit reversible planning preference; voice unchanged')

insufficient = loop.propose(wid, 'owner', {**request, 'idempotencyKey': 'pg-experiment-2'})['record']['id']
for action in ('accept', 'prepare', 'start'): loop.experiment_action(wid, 'owner', insufficient, {'action': action})
clock[0] += 15 * 86400
assert loop.experiment_action(wid, 'owner', insufficient, {'action': 'measure'})['record']['status'] == 'insufficient_data'
refused(lambda: loop.experiment_action(wid, 'owner', insufficient, {'action': 'apply'}))
passed('insufficient prospective data never becomes an applied strategy')

# Force a failing notification provider hook; a completed recap must still commit.
clock[0] = start + 15 * 86400
mutate(lambda state: state.setdefault('coworker', {}).setdefault('listening', {}).update({'opportunities': [
    {'id': 'unacted-suggestion', 'status': 'new', 'decidedAt': clock[0]-2*86400},
    {'id': 'decision-without-outcome', 'status': 'acted', 'decidedAt': clock[0]-2*86400}
]}))
with patch.object(service.notifications, 'emit', side_effect=RuntimeError('fixture notification failure')):
    recap = loop.generate_proof(wid, 'owner')
assert recap['verified']
assert loop.generate_proof(wid, 'owner')['record']['id'] == recap['record']['id']
assert recap['record']['counts']['verifiedPublishedPosts'] == 4, recap
assert recap['record']['counts']['opportunitiesActedOn'] == 0
assert recap['record']['timeBack']['byConfidence'] == []
assert loop.proof_action(wid, 'owner', recap['record']['id'], 'opened')['verified']
refused(lambda: loop.proof_action(other, 'other', recap['record']['id'], 'opened'))
monthly = loop.generate_proof(wid, 'owner', 'monthly')['record']
assert monthly['historyCoverage'] == 'insufficient_history'
with connection() as db:
    # Direct RLS reads cannot enumerate another workspace's new document state.
    db.execute('SET LOCAL ROLE authenticated')
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (USERS['other'],))
    assert db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,)).fetchone() is None
with connection() as db:
    events = db.execute("SELECT event,properties FROM public.pr_product_events WHERE workspace_id=%s", (wid,)).fetchall()
    assert any(name == 'growth_experiment.completed' for name, _ in events)
    assert all(set(properties) == {'recordId'} for _, properties in events)
passed('authoritative/idempotent proof, notification failure isolation, missing Time Back history, monthly honesty, RLS and content-free events')

# Missing Time Back table is handled with a savepoint and truthful coverage.
with connection() as db: db.execute('ALTER TABLE public.pr_time_savings_ledger RENAME TO pr_time_savings_ledger_fixture_hidden')
clock[0] += 8 * 86400
assert loop.generate_proof(wid, 'owner')['record']['timeBack']['coverage'] == 'unavailable'
with connection() as db: db.execute('ALTER TABLE public.pr_time_savings_ledger_fixture_hidden RENAME TO pr_time_savings_ledger')
passed('Time Back data failure is unavailable, never a fake zero or failed recap')

# A failed provider-data read must roll back its savepoint, preserve the goal,
# and return unavailable instead of a made-up audience zero.
loop.goal_status(wid, 'owner', consistency['record']['id'], {'status': 'paused'})
audience = loop.create_goal(wid, 'owner', {**payload, 'goalType': 'views_or_reach', 'primaryMetric': 'views', 'idempotencyKey': 'pg-read-failure'})
def failed_read(cur, *_args, **_kwargs):
    cur.execute('SELECT 1/0')
with patch.object(growth_loop.insights, 'summary', side_effect=failed_read):
    unavailable = loop.summary(wid, 'owner')['goal']
assert unavailable['coverage']['status'] == 'unavailable' and unavailable['currentValue'] is None
loop.goal_status(wid, 'owner', audience['record']['id'], {'status': 'archived'})
loop.goal_status(wid, 'owner', consistency['record']['id'], {'status': 'active'})
passed('provider/storage failure returns unavailable and leaves subsequent workspace commands usable')

# Sufficient real decision history enables only the measured monthly comparison.
from postriff_phase2.learning_service import insert_events
history_wid = service.bootstrap('history', 'studio')['workspaceId']
with connection() as db, db.cursor() as cur:
    for month, distance, rejected in ((9, .4, 2), (10, .1, 1)):
        at = dt.datetime(2026, month, 15, tzinfo=dt.timezone.utc).timestamp()
        insert_events(cur, history_wid, [{'kind': 'draft.approved', 'actor': USERS['history'], 'at': at+i,
                                 'features': {'editDistance': distance}} for i in range(3)] +
                                [{'kind': 'draft.rejected', 'actor': USERS['owner'], 'at': at+10+i} for i in range(rejected)])
clock[0] = dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc).timestamp()
monthly = loop.generate_proof(history_wid, 'history', 'monthly')['record']
assert monthly['historyCoverage'] == 'sufficient', monthly
assert monthly['learningSummary']['approvalRate'] == .75
assert monthly['learningSummary']['priorApprovalRate'] == .6
assert monthly['learningSummary']['medianEditDistance'] == .1
assert monthly['learningSummary']['priorMedianEditDistance'] == .4
passed('monthly improvement comparison requires sufficient authoritative decision and edit history in both periods')
