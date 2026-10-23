#!/usr/bin/env python3
"""H-07 on-call drill: every row of the owner's reply-15 policy, through the on-call engine (src/rafii_control/oncall/),
with fake push, e-mail and phone providers, on a simulated clock and a disposable PostgreSQL 16. Re-runnable; writes a
receipt (docs/ops/oncall-drill-receipt.json and ONCALL-DRILL-RECEIPT.md).

    POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin PYTHONPATH=src:tests python tests/oncall_drills.py \\
        --out docs/ops/oncall-drill-receipt.json --markdown docs/ops/ONCALL-DRILL-RECEIPT.md [--only R02,R14]

What it proves: the engine's decisions. Who is notified, on which channel, at which second, what is suppressed, what is
recorded, and that the Postgres store keeps the audit trail append-only and every notification unique. What it does
NOT prove: that anything reaches a person. A fake provider accepts whatever it is given; no push service, mail
provider, phone network, person or Production system is involved. Real delivery, acknowledgement and escalation to
named people are Production tests for the owner (docs/ops/H07-EVIDENCE.md); until they pass, H-07 is not VERIFIED.
No network except 127.0.0.1; synthetic people and destinations; secrets generated at run time.
"""
import argparse
import json
import platform
import secrets
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import discord_lane_fixture as F
import discord_ops_drills as D
from rafii_control.oncall import autohold, readiness
from rafii_control.oncall import policy as P
from rafii_control.oncall.engine import Engine, heartbeat_alerts
from rafii_control.oncall.providers import FakeProvider
from rafii_control.oncall.store import Conflict, MemoryStore, PostgresStore

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_140 = ROOT / 'migrations/postriff/140_rafii_control_oncall.sql'
PRELUDE = '''CREATE SCHEMA IF NOT EXISTS rafii_control;
DO $roles$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_control_session') THEN
    CREATE ROLE rafii_control_session NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rafii_control_reader') THEN
    CREATE ROLE rafii_control_reader NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF;
END $roles$;'''
POLICY = P.load()
SAT_3AM = datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc).timestamp()      # Saturday 03:00 EDT
TUE_2AM = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc).timestamp()      # Tuesday 02:00 EDT
TUE_9AM = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc).timestamp()     # Tuesday 09:00 EDT
TUE_10AM = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc).timestamp()
PROVES = 'the engine decision on a simulated clock'
NOT_PROVEN = 'delivery to a person: fake providers accept everything'


def roster():
    """Two synthetic people with opaque destination references (no address, number or subscription)."""
    people = {name: {'push': 'ref-%s-push' % name, 'email': 'ref-%s-mail' % name, 'phone': 'ref-%s-phone' % name}
              for name in ('primary-1', 'backup-1')}
    return {'shifts': [{'days': 'daily', 'start': '00:00', 'end': '24:00', 'primary': 'primary-1', 'backup': 'backup-1'}],
            'people': people}


def alert(rule='CROSS_TENANT_PROBE_FAILED', severity='page', scope=None):
    found = {'id': rule, 'class': rule.split('_')[0], 'severity': severity, 'message': 'drill %s' % rule, 'evidence': {}}
    if scope:
        found['scope'] = scope
    return found


class Rig:
    def __init__(self, store=None, policy=None, roster_=None, **kw):
        self.store = store or MemoryStore()
        self.fakes = {c: FakeProvider(c) for c in P.CHANNELS}
        self.engine = Engine(policy or POLICY, self.store, self.fakes, roster=roster_ or roster(), **kw)

    def timeline(self, alerts, start, seconds, step=30):
        out = {}
        for offset in range(0, seconds + 1, step):
            before = {c: len(f.sent) for c, f in self.fakes.items()}
            self.engine.process(alerts, start + offset)
            new = sorted('%s:%s' % (c, m.person) for c, f in self.fakes.items() for m in f.sent[before[c]:] if m.kind == 'page')
            if new:
                out[offset] = new
        return out

    def incident(self, rule):
        rows = [i for i in self.store.incidents() if i['rule'] == rule]
        return rows[-1] if rows else None


class Row:
    def __init__(self, ident, requirement, title):
        self.record = {'id': ident, 'requirement': requirement, 'title': title, 'checks': [], 'observed': {},
                       'proves': PROVES, 'doesNotProve': NOT_PROVEN}
        self.started = time.monotonic()

    def expect(self, name, condition, observed=None):
        self.record['checks'].append({'check': name, 'pass': bool(condition), 'observed': observed})

    def done(self):
        self.record['seconds'] = round(time.monotonic() - self.started, 1)
        self.record['result'] = 'PASS' if self.record['checks'] and all(c['pass'] for c in self.record['checks']) else 'FAIL'
        return self.record


class Lab:
    """One disposable PostgreSQL: the Discord schema (for the hold and the end-to-end row) plus migration 140."""
    def __init__(self):
        self.discord = D.Lab()
        self.cluster = self.discord.cluster
        self.discord.sql(PRELUDE)
        for _ in range(2):          # idempotent: applied twice
            done = subprocess.run([str(Path(F.PG_BIN) / 'psql'), self.cluster.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f',
                                   str(MIGRATION_140)], capture_output=True, text=True)
            if done.returncode:
                raise RuntimeError('migration 140 failed: ' + done.stderr[-800:])

    def session(self):
        import psycopg
        connection = psycopg.connect(self.cluster.dsn, autocommit=True, prepare_threshold=None)
        connection.execute('SET ROLE rafii_control_session')
        return connection

    def store(self, environment='local'):
        self.discord.sql('DELETE FROM rafii_control.oncall_deliveries')
        self.discord.sql('DELETE FROM rafii_control.oncall_heartbeat')
        self.discord.sql('ALTER TABLE rafii_control.oncall_events DISABLE TRIGGER oncall_events_no_truncate')
        self.discord.sql('TRUNCATE rafii_control.oncall_events')       # the drill's own reset, as the owner, never the engine
        self.discord.sql('ALTER TABLE rafii_control.oncall_events ENABLE TRIGGER oncall_events_no_truncate')
        self.discord.sql('DELETE FROM rafii_control.oncall_incidents')
        return PostgresStore(self.session, environment)

    def close(self):
        self.discord.close()


# --- the rows ------------------------------------------------------------------------------------------------------------

def r01_roster(lab):
    row = Row('R01', 'roster', 'A Primary and a Backup cover every minute; the shipped placeholder cannot carry P0')
    placeholder = P.roster_problems(POLICY)
    named = P.roster_problems(POLICY, P.validate_roster(roster()))
    rig = Rig(roster_=json.loads(P.DEFAULT_PATH.read_text())['roster'])
    rig.engine.process([], SAT_3AM)
    row.record['observed'] = {'placeholderProblems': placeholder, 'namedProblems': named,
                              'readinessToday': readiness.status(POLICY)['status']}
    row.expect('the shipped placeholder roster has no destinations (BLOCKED)', bool(placeholder)
               and readiness.status(POLICY)['status'] == 'BLOCKED', placeholder)
    row.expect('a named synthetic roster has no gap, a different Backup and every channel', named == [], named)
    row.expect('an invalid roster is the engine\'s own P0', (rig.incident('ONCALL_ROSTER_INVALID') or {}).get('priority') == 'P0')
    return row.done()


def r02_r03_r04_p0(lab):
    rows = []
    rig = Rig()
    line = rig.timeline([alert()], SAT_3AM, 660, step=30)
    exact = Rig()
    exact.engine.process([alert()], SAT_3AM)
    exact.engine.process([alert()], SAT_3AM + 299.9)
    early_call = len(exact.fakes['phone'].sent)
    exact.engine.process([alert()], SAT_3AM + 300)
    exact.engine.process([alert()], SAT_3AM + 599.9)
    early_backup = [m.person for m in exact.fakes['push'].sent]
    exact.engine.process([alert()], SAT_3AM + 600)
    row = Row('R02', 'routing_p0', 'P0 at 03:00 on a Saturday: push and e-mail to the Primary at once')
    row.record['observed'] = {'timeline': line}
    row.expect('second 0: push and e-mail to the Primary, nothing else', line.get(0) == ['email:primary-1', 'push:primary-1'], line.get(0))
    rows.append(row.done())
    row = Row('R03', 'escalation_5min', 'Unacknowledged P0: a call to the Primary at 5 minutes, not before')
    row.record['observed'] = {'callsAt299_9': early_call, 'timeline300': line.get(300)}
    row.expect('no call at 299.9 s', early_call == 0, early_call)
    row.expect('a call to the Primary at 300 s', line.get(300) == ['phone:primary-1'], line.get(300))
    rows.append(row.done())
    row = Row('R04', 'escalation_10min_backup', 'Unacknowledged P0: the Backup by push, e-mail and phone at 10 minutes')
    row.record['observed'] = {'pushesAt599_9': early_backup, 'timeline600': line.get(600)}
    row.expect('nothing to the Backup at 599.9 s', 'backup-1' not in early_backup, early_backup)
    row.expect('push, e-mail and phone to the Backup at 600 s', line.get(600) == ['email:backup-1', 'phone:backup-1', 'push:backup-1'],
               line.get(600))
    rows.append(row.done())
    return rows


def r05_p1(lab):
    row = Row('R05', 'routing_p1', 'P1: push and e-mail in duty hours, the Backup after 15 duty minutes; at night e-mail now, push at 09:00')
    day = Rig().timeline([alert('RATE_429')], TUE_10AM, 960, step=60)
    night_rig = Rig()
    night = night_rig.timeline([alert('RATE_429')], TUE_2AM, int(TUE_9AM - TUE_2AM) + 960, step=60)
    nine = int(TUE_9AM - TUE_2AM)
    spring = Rig()
    late = datetime(2026, 3, 8, 3, 50, tzinfo=timezone.utc).timestamp()      # Saturday 22:50 EST
    sunday_nine = datetime(2026, 3, 8, 13, 0, tzinfo=timezone.utc).timestamp()  # Sunday 09:00 EDT
    for at in (late, late + 600, sunday_nine, sunday_nine + 299, sunday_nine + 300):
        spring.engine.process([alert('RATE_429')], at)
    backup_at = [e['at'] for e in spring.store.events() if e['kind'] == 'step' and e['detail'].get('to') == 'backup']
    row.record['observed'] = {'day': day, 'night': {str(k - nine) + ' s after 09:00' if k >= nine else str(k): v for k, v in night.items()},
                              'springForwardBackupAt': backup_at}
    row.expect('duty hours: push and e-mail at once, the Backup at 15 minutes, no call',
               day == {0: ['email:primary-1', 'push:primary-1'], 900: ['email:backup-1', 'push:backup-1']}, day)
    row.expect('night: e-mail at once, push at 09:00 New York time, the Backup at 09:15',
               night == {0: ['email:primary-1'], nine: ['push:primary-1'], nine + 900: ['email:backup-1', 'push:backup-1']}, night)
    row.expect('across the spring-forward night only duty minutes count (10 before 23:00, 5 after 09:00 EDT)',
               backup_at == [sunday_nine + 300], backup_at)
    return row.done()


def r06_p2(lab):
    row = Row('R06', 'routing_p2', 'P2: e-mail in duty hours, nothing else')
    rig = Rig()
    line = rig.timeline([alert('RATE_APP_BUDGET_SPENT', 'warn')], TUE_2AM, int(TUE_9AM - TUE_2AM) + 120, step=60)
    row.record['observed'] = {'timeline': line}
    row.expect('one e-mail at 09:00, no push and no call', line == {int(TUE_9AM - TUE_2AM): ['email:primary-1']}, line)
    return row.done()


def r07_ack(lab):
    row = Row('R07', 'acknowledgement', 'An acknowledgement from push, e-mail, phone or the dashboard stops the chain')
    results = {}
    secret = secrets.token_bytes(32)
    for channel in ('push', 'email', 'phone', 'dashboard'):
        rig = Rig(ack_secret=secret, ack_base='https://rafii.example.invalid/oncall/ack')
        rig.engine.process([alert()], SAT_3AM)
        incident = rig.incident('CROSS_TENANT_PROBE_FAILED')
        if channel in ('push', 'email'):
            token = [m for m in rig.fakes[channel].sent if m.kind == 'page'][0].ack_url.split('?t=', 1)[1]
            answer = rig.engine.acknowledge_token(token, SAT_3AM + 120, channel)
        else:
            answer = rig.engine.acknowledge(incident['id'], 'primary-1', channel, SAT_3AM + 120)
        rig.timeline([alert()], SAT_3AM + 150, 1200, step=60)
        results[channel] = {'ok': answer.get('ok'), 'calls': len(rig.fakes['phone'].sent),
                            'records': sorted('%s:%s' % (m.channel, m.person) for f in rig.fakes.values() for m in f.sent if m.kind == 'record')}
    forged = Rig(ack_secret=secret, ack_base='https://rafii.example.invalid/oncall/ack')
    forged.engine.process([alert()], SAT_3AM)
    refused = forged.engine.acknowledge_token('forged.' + secrets.token_hex(16), SAT_3AM + 60, 'push')
    row.record['observed'] = {'byChannel': results, 'forgedToken': refused}
    row.expect('each channel acknowledges and no call follows', all(r['ok'] and r['calls'] == 0 for r in results.values()), results)
    row.expect('the acknowledgement is e-mailed as a record', all(r['records'] == ['email:primary-1'] for r in results.values()), results)
    row.expect('a forged link is refused and recorded', refused.get('reason') == 'bad_token' and
               'ack_refused' in [e['kind'] for e in forged.store.events()], refused)
    return row.done()


def r08_delivery(lab):
    row = Row('R08', 'delivery_fallback', 'A failed channel brings the next step forward; all failing opens the engine\'s own P0')
    push_down = Rig()
    push_down.fakes['push'].fail_for('primary-1')
    first = push_down.timeline([alert()], SAT_3AM, 0)
    dead = Rig()
    for channel in P.CHANNELS:
        dead.fakes[channel].fail_for('primary-1')
    dead.fakes['email'].raise_next(1)
    dead.timeline([alert()], SAT_3AM, 120, step=60)
    meta = dead.incident('ONCALL_DELIVERY_FAILED') or {}
    to_backup = sorted('%s:%s' % (m.channel, m.person) for f in dead.fakes.values() for m in f.sent if m.rule == 'ONCALL_DELIVERY_FAILED')
    row.record['observed'] = {'pushDownSecond0': first.get(0), 'metaPriority': meta.get('priority'), 'metaDeliveries': to_backup,
                              'statuses': sorted({d['status'] + '/' + str(d['reason']) for d in dead.store.deliveries()})}
    row.expect('a failed push brings the call forward to second 0', first.get(0) == ['email:primary-1', 'phone:primary-1', 'push:primary-1'],
               first.get(0))
    row.expect('every channel failing opens ONCALL_DELIVERY_FAILED (P0) once', meta.get('priority') == 'P0'
               and len([i for i in dead.store.incidents() if i['rule'] == 'ONCALL_DELIVERY_FAILED']) == 1)
    row.expect('the failure alert reaches the Backup', any(x.endswith('backup-1') for x in to_backup), to_backup)
    row.expect('a provider exception is a failed delivery, not a crash',
               'failed/provider_exception' in {d['status'] + '/' + str(d['reason']) for d in dead.store.deliveries()})
    return row.done()


def r09_dedupe(lab):
    row = Row('R09', 'dedupe', 'A repeating alert is one incident and one notification per step and channel')
    rig = Rig()
    for minute in range(30):
        for _ in range(2):
            rig.engine.process([alert()], SAT_3AM + 60 * minute)
    keys = [d['key'] for d in rig.store.deliveries()]
    row.record['observed'] = {'incidents': len([i for i in rig.store.incidents() if i['rule'] == 'CROSS_TENANT_PROBE_FAILED']),
                              'deliveries': len(keys), 'unique': len(set(keys)), 'seen': rig.incident('CROSS_TENANT_PROBE_FAILED')['seenCount']}
    row.expect('one incident for 60 evaluations', row.record['observed']['incidents'] == 1)
    row.expect('every notification key is unique', len(keys) == len(set(keys)), len(keys))
    return row.done()


def r10_suppression(lab):
    row = Row('R10', 'suppression', 'Maintenance and a cause hold their symptoms; a security alert pages in any window; flapping is damped')
    raw = json.loads(P.DEFAULT_PATH.read_text())
    raw['suppression']['maintenance'] = [{'start': SAT_3AM - 60, 'end': SAT_3AM + 600, 'rules': ['*']}]
    window = P.validate(raw)
    maintenance = Rig(policy=window).timeline([alert('SILENT_HALT_DATABASE')], SAT_3AM, 900, step=60)
    security = Rig(policy=window).timeline([alert()], SAT_3AM, 0)
    inhibited = Rig()
    inhibited.timeline([alert('SILENT_HALT_DATABASE'), alert('SILENT_HALT_NO_PROGRESS'), alert('BACKLOG_LAG')], SAT_3AM, 0)
    flap = Rig()
    flap.engine.process([alert()], SAT_3AM)
    flap.engine.process([], SAT_3AM + 60)
    flap.engine.process([], SAT_3AM + 120)
    flap.engine.process([alert()], SAT_3AM + 180)
    row.record['observed'] = {'maintenanceFirstPage': sorted(maintenance)[:1], 'securityInWindow': security.get(0),
                              'inhibitedRules': sorted({m.rule for m in inhibited.fakes['push'].sent}),
                              'flapIncidents': len(flap.store.incidents()), 'flapPushes': len(flap.fakes['push'].sent)}
    row.expect('nothing pages inside the window; the chain starts when it ends', sorted(maintenance)[:1] == [600], sorted(maintenance))
    row.expect('a security alert pages inside the window', security.get(0) == ['email:primary-1', 'push:primary-1'], security)
    row.expect('the database alarm pages; no-progress and backlog are held as its symptoms',
               {m.rule for m in inhibited.fakes['push'].sent} == {'SILENT_HALT_DATABASE'})
    row.expect('a flap within ten minutes reopens the incident without resending', len(flap.store.incidents()) == 1
               and len(flap.fakes['push'].sent) == 1)
    return row.done()


def r11_storm(lab):
    row = Row('R11', 'storm', 'A storm: at most six pushes per person in ten minutes, one summary, the rest later')
    rig = Rig()
    storm = [alert('RATE_429', scope='route%d' % n) for n in range(9)]
    rig.engine.process(storm, TUE_10AM)
    first = len(rig.fakes['push'].to('primary-1', 'page'))
    summaries = len(rig.fakes['push'].to('primary-1', 'summary'))
    rig.engine.process(storm, TUE_10AM + 601)
    later = len([m for m in rig.fakes['push'].to('primary-1', 'page') if m.rule == 'RATE_429'])
    row.record['observed'] = {'pushesAtOnce': first, 'summaries': summaries, 'pushesAfterWindow': later}
    row.expect('six pushes and one summary at once', first == 6 and summaries == 1, [first, summaries])
    row.expect('the held three after the window', later == 9, later)
    return row.done()


def r12_audit(lab):
    import psycopg
    row = Row('R12', 'audit_trail', 'PostgreSQL store (migration 140): an append-only timeline and unique notifications')
    store = lab.store()
    rig = Rig(store=store)
    rig.timeline([alert()], SAT_3AM, 660, step=60)
    incident = rig.incident('CROSS_TENANT_PROBE_FAILED')
    rig.engine.acknowledge(incident['id'], 'backup-1', 'phone', SAT_3AM + 700)
    rig.engine.process([], SAT_3AM + 760)
    rig.engine.process([], SAT_3AM + 820)
    kinds = [e['kind'] for e in store.events(incident['id'])]
    refused = []
    with lab.session() as db:
        for statement in ('UPDATE rafii_control.oncall_events SET kind = %s', 'DELETE FROM rafii_control.oncall_events WHERE kind = %s'):
            try:
                db.execute(statement, ('opened',))
                refused.append(False)
            except psycopg.errors.InsufficientPrivilege:
                refused.append(True)
    try:
        lab.discord.sql("UPDATE rafii_control.oncall_events SET kind = 'opened'")
        owner_refused = False
    except psycopg.errors.RaiseException:
        owner_refused = True
    duplicate = store.claim({'key': store.deliveries()[0]['key'], 'incidentId': incident['id'], 'person': 'primary-1',
                             'channel': 'push', 'kind': 'page', 'step': '0.0', 'claimedAt': SAT_3AM})
    other = PostgresStore(lab.session, 'staging')
    fresh = dict(store.incident(incident['id']), id=str(uuid.uuid4()), state='open', resolvedAt=None, resolution=None,
                 acknowledgedAt=None, acknowledgedBy=None, ackChannel=None)
    store.insert_incident(fresh)                         # allowed: the earlier episode is resolved
    try:
        store.insert_incident(dict(fresh, id=str(uuid.uuid4())))
        live_twice = True
    except Conflict:
        live_twice = False
    row.record['observed'] = {'timeline': kinds, 'sessionUpdateDeleteRefused': refused, 'ownerUpdateRefusedByTrigger': owner_refused,
                              'duplicateClaim': duplicate, 'otherEnvironmentSees': len(other.incidents())}
    row.expect('every step, delivery, acknowledgement and resolution is in the timeline in order',
               kinds[0] == 'opened' and {'step', 'delivery', 'acknowledged', 'resolved'} <= set(kinds)
               and kinds.index('acknowledged') < kinds.index('resolved'), kinds)
    row.expect('the session role cannot update or delete an event; the trigger refuses even the owner', refused == [True, True] and owner_refused,
               [refused, owner_refused])
    row.expect('a notification key can be claimed once only', duplicate is False, duplicate)
    row.expect('one live incident per key; another environment sees nothing', not live_twice and len(other.incidents()) == 0)
    return row.done()


def r13_heartbeat(lab):
    row = Row('R13', 'heartbeat', 'The alert about the alerting: a stale heartbeat for the watchdog, a gap noticed after a restart')
    import psycopg
    store = lab.store()
    rig = Rig(store=store)
    rig.engine.process([alert()], SAT_3AM)
    with lab.cluster.connect(autocommit=True) as db:
        db.execute('SET ROLE rafii_control_watchdog')
        db.execute("SELECT set_config('rafii_control.environment', 'local', false)")
        beat = db.execute('SELECT payload FROM rafii_control.oncall_heartbeat').fetchone()[0]
        try:
            db.execute('SELECT 1 FROM rafii_control.oncall_incidents')
            watchdog_sees_incidents = True
        except psycopg.errors.InsufficientPrivilege:
            watchdog_sees_incidents = False
    fresh = heartbeat_alerts(beat, SAT_3AM + 60, POLICY)
    stale = [a['id'] for a in heartbeat_alerts(beat, SAT_3AM + 181, POLICY)]
    rig.engine.process([alert()], SAT_3AM + 1800)
    gap = rig.incident('ONCALL_ENGINE_GAP') or {}
    row.record['observed'] = {'watchdogReadsHeartbeat': beat.get('unacknowledgedP0'), 'watchdogReadsIncidents': watchdog_sees_incidents,
                              'freshAlerts': fresh, 'staleAlerts': stale, 'gapPriority': gap.get('priority')}
    row.expect('the watchdog role reads the heartbeat and nothing else', beat.get('unacknowledgedP0') == 1 and not watchdog_sees_incidents)
    row.expect('fresh: nothing; older than 180 s: ONCALL_HEARTBEAT_STALE', fresh == [] and stale == ['ONCALL_HEARTBEAT_STALE'], stale)
    row.expect('after a gap the engine opens ONCALL_ENGINE_GAP (P1)', gap.get('priority') == 'P1')
    return row.done()


def r14_end_to_end(lab):
    row = Row('R14', 'end_to_end', 'Real evaluator alerts from the real payload into the engine, through to the Backup and resolution')
    lab.discord.fresh([F.Tenant(n) for n in range(4)], 1, due_ago=400)
    snapshot, alerts = lab.discord.look(phase='open')
    store = lab.store()
    rig = Rig(store=store)
    start = SAT_3AM
    pages = {}
    for offset in range(0, 661, 60):
        before = {c: len(f.sent) for c, f in rig.fakes.items()}
        rig.engine.process(alerts, start + offset)
        new = sorted('%s:%s:%s' % (m.rule, c, m.person) for c, f in rig.fakes.items() for m in f.sent[before[c]:] if m.kind == 'page')
        if new:
            pages[offset] = new
    halt = rig.incident('SILENT_HALT_NO_PROGRESS') or {}
    ack = rig.engine.acknowledge(halt.get('id'), 'backup-1', 'phone', start + 700)
    lab.discord.drain(loops=2, seconds=20)
    snapshot, cleared = lab.discord.look(phase='open')
    for offset in (760, 820):
        rig.engine.process(cleared, start + offset)
    final = rig.incident('SILENT_HALT_NO_PROGRESS') or {}
    row.record['observed'] = {'evaluatorAlerts': sorted('%s:%s' % (a['id'], a['severity']) for a in alerts), 'pages': pages,
                              'acknowledged': ack, 'afterDrain': sorted(a['id'] for a in cleared), 'finalState': final.get('state'),
                              'records': sorted('%s:%s' % (m.channel, m.person) for f in rig.fakes.values() for m in f.sent if m.kind == 'record')}
    row.expect('the evaluator pages SILENT_HALT_NO_PROGRESS on the real payload', 'SILENT_HALT_NO_PROGRESS:page' in row.record['observed']['evaluatorAlerts'])
    row.expect('P0 chain: Primary at once, call at 5 minutes, Backup at 10',
               'SILENT_HALT_NO_PROGRESS:push:primary-1' in pages.get(0, []) and 'SILENT_HALT_NO_PROGRESS:phone:primary-1' in pages.get(300, [])
               and 'SILENT_HALT_NO_PROGRESS:phone:backup-1' in pages.get(600, []), pages)
    row.expect('the Backup acknowledges by phone; after the senders drain it resolves by itself',
               ack.get('ok') and final.get('state') == 'resolved', [ack, final.get('state')])
    row.expect('the resolution is e-mailed to both people paged', {'email:primary-1', 'email:backup-1'} <= set(row.record['observed']['records']))
    return row.done()


def r15_auto_hold(lab):
    row = Row('R15', 'auto_hold_owner_decision', 'Option D1 (off by default, advised against): the runbook HOLD_ON on a failed probe only')
    lab.discord.fresh([F.Tenant(n) for n in range(3)], 1)
    with F.no_billing():
        lab.discord.worker.step(discord_only=True)    # one post sent: the coordinator's policy row exists; two stay due

    def executor(sql):
        with lab.cluster.connect(autocommit=True) as db:
            cur = db.execute(sql)
            return [dict(zip([c.name for c in cur.description], r)) for r in cur.fetchall()] if cur.description else []
    store = MemoryStore()
    rig = Rig(store=store)
    rig.engine.hold = autohold.AutoHold(POLICY, executor)
    rig.engine.process([alert('CROSS_TENANT_PROBING', 'page')], SAT_3AM)
    after_probing = lab.discord.named(D.runbook_statements()['HOLD_READBACK'])
    rig.engine.process([alert()], SAT_3AM + 60)
    held = lab.discord.named(D.runbook_statements()['HOLD_READBACK'])
    results, _ = F.run_lanes(lab.discord.worker, 1, seconds=5)
    rig.engine.process([alert()], SAT_3AM + 120)
    rig.engine.process([], SAT_3AM + 180)
    rig.engine.process([], SAT_3AM + 240)
    still = lab.discord.named(D.runbook_statements()['HOLD_READBACK'])
    lab.discord.sql(D.runbook_statements()['HOLD_OFF'])           # a person lifts it
    row.record['observed'] = {'afterProbing': after_probing, 'afterProbeFailed': held, 'laneStops': sorted({r['stoppedBy'] for r in results if r}),
                              'afterAlertCleared': still, 'engaged': (rig.incident('ONCALL_AUTO_HOLD_ENGAGED') or {}).get('priority')}
    row.expect('probing never holds (a refusal is the gate working)', after_probing.get('held') == 0, after_probing)
    row.expect('a failed probe holds, read back held 1, and the lanes stop with operator_hold',
               held.get('held') == 1 and {r['stoppedBy'] for r in results if r} == {'operator_hold'}, [held, results and results[0].get('stoppedBy')])
    row.expect('the engine opens its own P0 and never lifts the hold, even after the alert clears',
               (rig.incident('ONCALL_AUTO_HOLD_ENGAGED') or {}).get('priority') == 'P0' and still.get('held') == 1, still)
    return row.done()


ROWS = (r01_roster, r02_r03_r04_p0, r05_p1, r06_p2, r07_ack, r08_delivery, r09_dedupe, r10_suppression, r11_storm,
        r12_audit, r13_heartbeat, r14_end_to_end, r15_auto_hold)


def run(out=None, only=None):
    receipt = {'kind': 'rafii.oncall.drill-receipt', 'version': 1, 'environment': 'isolated', 'sourceRevision': D.source_revision(),
               'startedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'python': platform.python_version(),
               'postgres': None, 'policy': 'docs/ops/h07-oncall-policy.json',
               'command': 'POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin PYTHONPATH=src:tests python tests/oncall_drills.py',
               'providers': 'fake (tests prove the decisions, not delivery)', 'rows': []}
    lab = Lab()
    try:
        receipt['postgres'] = lab.discord.sql('SHOW server_version')[0][0]
        for function in ROWS:
            ident = function.__name__.split('_', 1)[0].upper()
            if only and ident not in only and not (ident == 'R02' and only & {'R03', 'R04'}):
                continue
            try:
                result = function(lab)
                records = result if isinstance(result, list) else [result]
            except Exception as error:
                records = [{'id': ident, 'result': 'FAIL', 'error': type(error).__name__, 'trace': traceback.format_exc()[-1500:]}]
            for record in records:
                receipt['rows'].append(record)
                print('%s %s %s' % (record['id'], record['result'], record.get('seconds', '')), flush=True)
            if out:
                Path(out).write_text(json.dumps(receipt, indent=1, sort_keys=True, default=str) + '\n')
    finally:
        lab.close()
    receipt['finishedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    receipt['result'] = 'PASS' if receipt['rows'] and all(r['result'] == 'PASS' for r in receipt['rows']) else 'FAIL'
    if out:
        Path(out).write_text(json.dumps(receipt, indent=1, sort_keys=True, default=str) + '\n')
    return receipt


def render_markdown(receipt):
    checks = [c for r in receipt['rows'] for c in r.get('checks', [])]
    out = ['# ON-CALL DRILL RECEIPT (isolated): H-07 policy rows through the on-call engine', '',
           'Generated by `tests/oncall_drills.py` from `docs/ops/oncall-drill-receipt.json`; do not edit by hand.', '',
           '**What this proves and what it does not.** Each row runs the engine (`src/rafii_control/oncall/`) on a simulated '
           'clock with fake push, e-mail and phone providers; rows R12 to R15 use a disposable PostgreSQL with migration 140 '
           '(and the Discord schema for R14 and R15). It proves the engine\'s decisions: who is notified, on which channel, at '
           'which second, what is held back and what is recorded. **It proves nothing about delivery**: a fake provider '
           'accepts everything, and no push service, mail provider, phone network or person was involved. The matching real '
           'tests, and the H-07 status, are in `H07-EVIDENCE.md`.', '',
           '| Run | Value |', '|---|---|',
           '| Started, finished (UTC) | %s, %s |' % (receipt.get('startedAt'), receipt.get('finishedAt')),
           '| Source revision | `%s` |' % receipt.get('sourceRevision'),
           '| Database | disposable PostgreSQL %s (tests/phase2/rls.sql, migrations 060, 124, 126, 128, and 140 applied twice) |' % receipt.get('postgres'),
           '| Providers | fake, recording; no network except 127.0.0.1 |',
           '| Policy | `%s` with a synthetic two-person roster (the shipped roster is a placeholder) |' % receipt.get('policy'),
           '| Command | `%s --out docs/ops/oncall-drill-receipt.json --markdown docs/ops/ONCALL-DRILL-RECEIPT.md` |' % receipt.get('command'),
           '| Result | **%s** (%d rows, %d checks, %d failed) |' % (receipt.get('result'), len(receipt['rows']), len(checks),
                                                               sum(1 for c in checks if not c['pass'])), '',
           '| Row | Requirement | Result | Seconds | Checks |', '|---|---|---|---|---|']
    for r in receipt['rows']:
        cs = r.get('checks', [])
        out.append('| %s %s | `%s` | **%s** | %s | %d/%d |' % (r['id'], r.get('title', ''), r.get('requirement', ''), r['result'],
                                                           r.get('seconds', ''), sum(c['pass'] for c in cs), len(cs)))
    for r in receipt['rows']:
        out += ['', '## %s %s: %s' % (r['id'], r.get('title', ''), r['result']), '']
        if r.get('error'):
            out += ['Error: `%s`' % r['error'], '']
        for c in r.get('checks', []):
            out.append('- %s %s (observed: `%s`)' % ('PASS' if c['pass'] else 'FAIL', c['check'], json.dumps(c.get('observed'), default=str)[:300]))
        if r.get('observed'):
            out += ['', 'Observed: `%s`' % json.dumps(r['observed'], default=str, sort_keys=True)[:1200]]
        out += ['', 'Proves: %s. Does not prove: %s.' % (r.get('proves', PROVES), r.get('doesNotProve', NOT_PROVEN))]
    return '\n'.join(out) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--out')
    parser.add_argument('--markdown')
    parser.add_argument('--render', help='only render an existing JSON receipt to --markdown')
    parser.add_argument('--only', help='comma-separated row ids, e.g. R02,R14')
    args = parser.parse_args(argv)
    if args.render:
        Path(args.markdown).write_text(render_markdown(json.loads(Path(args.render).read_text())))
        return 0
    if not F.AVAILABLE:
        print('needs POSTRIFF_PG_BIN and psycopg', file=sys.stderr)
        return 2
    receipt = run(args.out, set(args.only.split(',')) if args.only else None)
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(receipt))
    print('overall', receipt['result'])
    return 0 if receipt['result'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
