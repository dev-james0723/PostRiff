"""Disposable PostgreSQL: RAPv2 P1 "This wasn't me" (migration 122) end to end. Synthetic users only, no live data.

Runs SecurityIncidents.report/list against the real schema: one transaction records the incident, places the hold
(epoch bumps), revokes the other sessions but never the current one, mirrors enforcement and writes the ledger; an
incident can only cite the same person's event; incidents are never deleted outside the deletion purge; the browser
roles have no access.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from psycopg import errors

from postriff_alpha.domain import AlphaError
from postriff_phase2 import device_trust, security_holds
from postriff_phase2.coworker import flags
from postriff_phase2.security_incidents import SecurityIncidents

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ALICE, BOB = str(uuid.uuid4()), str(uuid.uuid4())
CURRENT, OTHER, THIRD = 'session-alice-current-0001', 'session-alice-other-00001', 'session-alice-other-00002'
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


with connection() as db:
    for role in ('anon', 'authenticated'):
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            assert not db.execute("SELECT has_table_privilege(%s,'public.pr_security_incidents',%s)", (role, privilege)).fetchone()[0], (role, privilege)
    assert not db.execute("SELECT has_table_privilege('service_role','public.pr_security_incidents','DELETE')").fetchone()[0]
    for user, session in ((ALICE, CURRENT), (ALICE, OTHER), (ALICE, THIRD), (BOB, 'session-bob-000000000001')):
        db.execute('INSERT INTO public.pr_sessions(user_id,session_id) VALUES(%s,%s)', (user, session))
    bob_event = db.execute("INSERT INTO public.pr_security_login_events(user_id,session_id,event_type,event_key) VALUES(%s,%s,'session.observed',%s) RETURNING id::text",
                           (BOB, 'session-bob-000000000001', 'session.observed:session-bob-000000000001')).fetchone()[0]
    alice_event = db.execute("INSERT INTO public.pr_security_login_events(user_id,session_id,event_type,event_key) VALUES(%s,%s,'session.observed',%s) RETURNING id::text",
                             (ALICE, THIRD, 'session.observed:' + THIRD)).fetchone()[0]
checks.append('anon/authenticated have no access; service_role cannot delete incidents')

flags.attach({'RAFII_SECURITY_INCIDENT_HOLD': '1'})


class Identity:
    def logout_others(self, token):
        return True


def service(user, signed_in_at):
    def verify(token):
        return user
    verify.session_id = lambda token, principal: CURRENT if principal == ALICE else 'session-bob-000000000001'
    verify.method_time = lambda token, principal: ('totp', signed_in_at)
    return SimpleNamespace(verify_session=verify, connection_factory=connection, clock=lambda: 1_800_000_000.0, identity=Identity())


alice = SecurityIncidents(service(ALICE, 1_800_000_000.0 - 30))
try:
    alice.report('t' * 40, {'type': 'not_me', 'confirmed': True, 'revokeOtherSessions': False, 'sourceEventId': bob_event})
    raise AssertionError("another person's event was accepted")
except AlphaError as error:
    assert error.code == 'security_resource_not_found'
checks.append("an incident cannot cite another person's ledger event (same 404 as an unknown one)")

result = alice.report('t' * 40, {'type': 'not_me', 'confirmed': True, 'revokeOtherSessions': True, 'sourceEventId': alice_event}, 'idem-key-0123456789ab')
assert result['accountHold'] is True and result['holdEpoch'] == 1 and result['sessions'] == {'rafiiApiRevoked': 2, 'providerRefreshState': 'confirmed'}, result
assert result['connectedAccounts'] == 'not_disconnected'
with connection() as db:
    revoked = {row[0] for row in db.execute('SELECT session_id FROM public.pr_session_revocations WHERE user_id=%s', (ALICE,)).fetchall()}
    assert revoked == {OTHER, THIRD}, revoked
    assert not db.execute('SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s', (BOB,)).fetchone()[0]
    kinds = sorted(row[0] for row in db.execute("SELECT event_type FROM public.pr_security_login_events WHERE user_id=%s AND event_type<>'session.observed'", (ALICE,)).fetchall())
    assert kinds == ['account.hold_placed', 'incident.reported'], kinds
    row = db.execute('SELECT state,hold_epoch,sessions_revoked,source_event_id::text FROM public.pr_security_incidents WHERE user_id=%s', (ALICE,)).fetchone()
    assert row == ('user_confirmed', 1, 2, alice_event), row
with connection() as db, db.cursor() as cur:
    try:
        security_holds.assert_clear(cur, ALICE)
        raise AssertionError('the hold was not placed')
    except security_holds.AccountHeld:
        pass
    assert security_holds.assert_clear(cur, BOB) == 0
checks.append('one report: incident row, hold at epoch 1, the two other sessions revoked (never the current one), ledger written, Bob untouched')

replayed = alice.report('t' * 40, {'type': 'not_me', 'confirmed': True, 'revokeOtherSessions': True, 'sourceEventId': alice_event}, 'idem-key-0123456789ab')
assert replayed['replayed'] is True and replayed['incidentId'] == result['incidentId']
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s', (ALICE,)).fetchone()[0] == 1
    assert db.execute('SELECT hold_epoch FROM public.pr_security_account_controls WHERE user_id=%s', (ALICE,)).fetchone()[0] == 1
checks.append('the same Idempotency-Key replays the incident without a second hold or epoch bump')

listed = alice.list('t' * 40)['incidents']
assert [i['incidentId'] for i in listed] == [result['incidentId']] and listed[0]['accountHold'] is True
assert SecurityIncidents(service(BOB, 1_800_000_000.0)).list('t' * 40) == {'incidents': []}
checks.append('GET lists only the caller\'s own incidents')

stale = SecurityIncidents(service(BOB, 1_800_000_000.0 - 3600))
try:
    stale.report('t' * 40, {'type': 'not_me', 'confirmed': True, 'revokeOtherSessions': True})
    raise AssertionError('a stale sign-in reported')
except AlphaError as error:
    assert error.code == 'step_up_required'
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s', (BOB,)).fetchone()[0] == 0
checks.append('a sign-in older than 10 minutes cannot report, and nothing is written')

with connection() as db:
    try:
        db.execute('DELETE FROM public.pr_security_incidents WHERE user_id=%s', (ALICE,))
        raise AssertionError('an incident was deleted')
    except errors.InsufficientPrivilege:
        db.rollback()
    db.execute("INSERT INTO public.pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,'studio',now())", (ALICE,))
    db.execute('SELECT public.pr_security_purge(%s)', (ALICE,))
    assert db.execute('SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s', (ALICE,)).fetchone()[0] == 0
checks.append('incidents are never deleted, except by the purge after an account deletion tombstone')

print(json.dumps({'status': 'pass', 'execution': 'disposable-local-postgres', 'checks': checks}, indent=2))
