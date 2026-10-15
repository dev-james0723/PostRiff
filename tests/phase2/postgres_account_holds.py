"""Disposable PostgreSQL: RAPv2 P1 account holds (migration 121). Synthetic users only, no live data.

Proves: the browser roles cannot touch the controls; hold_epoch only moves forward one step per change, for the owner
too; placement and release go through pr_security_set_hold and always bump the epoch; security_holds reads it and
refuses a held account or a moved epoch; the purge removes the row only after a deletion tombstone.
"""
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from psycopg import errors

from postriff_phase2 import security_holds
from postriff_phase2.coworker import flags

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ALICE, BOB = str(uuid.uuid4()), str(uuid.uuid4())
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def refused(statement, params=()):
    with connection() as db:
        try:
            db.execute(statement, params)
        except errors.InsufficientPrivilege:
            db.rollback()
            return True
    return False


with connection() as db:
    for role in ('anon', 'authenticated'):
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            assert not db.execute("SELECT has_table_privilege(%s,'public.pr_security_account_controls',%s)", (role, privilege)).fetchone()[0], (role, privilege)
        assert not db.execute("SELECT has_function_privilege(%s,'public.pr_security_set_hold(uuid,boolean,text)','EXECUTE')", (role,)).fetchone()[0]
    for privilege in ('INSERT', 'UPDATE', 'DELETE'):
        assert not db.execute("SELECT has_table_privilege('service_role','public.pr_security_account_controls',%s)", (privilege,)).fetchone()[0], privilege
    assert db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid='public.pr_security_account_controls'::regclass").fetchone()[0]
checks.append('anon/authenticated have no access; service_role may only read and call pr_security_set_hold; RLS forced')

flags.attach({'RAFII_SECURITY_INCIDENT_HOLD': '1'})
with connection() as db, db.cursor() as cur:
    assert security_holds.snapshot(cur, ALICE) == 0
    assert security_holds.place(cur, ALICE, 'incident.not_me') == 1
with connection() as db, db.cursor() as cur:
    try:
        security_holds.assert_clear(cur, ALICE)
        raise AssertionError('a held account passed')
    except security_holds.AccountHeld as error:
        assert error.code == 'security_account_hold'
    assert security_holds.place(cur, ALICE, 'incident.not_me') == 2
    assert security_holds.release(cur, ALICE, 'incident.resolved') == 3
with connection() as db, db.cursor() as cur:
    assert security_holds.assert_clear(cur, ALICE) == 3
    try:
        security_holds.assert_clear(cur, ALICE, expected_epoch=1)
        raise AssertionError('a job crossed a hold epoch change')
    except security_holds.AccountHeld as error:
        assert error.code == 'security_hold_changed'
    assert security_holds.assert_clear(cur, BOB) == 0
    placed = float(cur.execute("SELECT extract(epoch from placed_at) FROM public.pr_security_account_controls WHERE user_id=%s", (ALICE,)).fetchone()[0])
    try:
        security_holds.assert_clear(cur, ALICE, authorized_at=placed - 5)
        raise AssertionError('an approval from before the hold survived its release')
    except security_holds.AccountHeld as error:
        assert error.code == 'security_hold_changed'
    assert security_holds.assert_clear(cur, ALICE, authorized_at=placed + 5) == 3
checks.append('an approval made before the latest hold is refused after release; one made after it passes')
checks.append('place, repeat and release bump the epoch 1→2→3; a held account and a moved epoch are refused; others are unaffected')

assert refused("UPDATE public.pr_security_account_controls SET hold_active=false WHERE user_id=%s", (ALICE,))
assert refused("UPDATE public.pr_security_account_controls SET hold_epoch=1 WHERE user_id=%s", (ALICE,))
assert refused("INSERT INTO public.pr_security_account_controls(user_id,hold_epoch) VALUES(%s,7)", (BOB,))
assert refused("DELETE FROM public.pr_security_account_controls WHERE user_id=%s", (ALICE,))
assert refused("TRUNCATE public.pr_security_account_controls")
checks.append('direct writes that do not advance the epoch by one, deletes and truncate are refused, for the owner too')

with connection() as db:
    db.execute('SELECT public.pr_security_set_hold(%s,true,%s)', (BOB, 'incident.not_me'))
assert refused('SELECT public.pr_security_purge(%s)', (ALICE,))
with connection() as db:
    db.execute("INSERT INTO public.pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,'studio',now())", (ALICE,))
    db.execute('SELECT public.pr_security_purge(%s)', (ALICE,))
    assert db.execute('SELECT count(*) FROM public.pr_security_account_controls WHERE user_id=%s', (ALICE,)).fetchone()[0] == 0
    assert db.execute('SELECT hold_active FROM public.pr_security_account_controls WHERE user_id=%s', (BOB,)).fetchone()[0] is True
checks.append('the purge removes a deleted account\'s controls only, and refuses a live account')

flags.attach({})
with connection() as db, db.cursor() as cur:
    assert security_holds.assert_clear(cur, BOB) is None
checks.append('with RAFII_SECURITY_INCIDENT_HOLD off even a held account is not read (no statement)')

print(json.dumps({'status': 'pass', 'execution': 'disposable-local-postgres', 'checks': checks}, indent=2))
