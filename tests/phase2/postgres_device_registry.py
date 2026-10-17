"""Disposable PostgreSQL: RAPv2 P1 device registry (migration 120). Synthetic users only, no live data.

Proves the SQL the unit tests can only describe: the browser roles have no access at all; the login ledger is
append-only for every role (the owner included); a session can only point at the same person's device; cleaning up
pr_sessions cannot silently drop enforcement state; the purge works only after an account deletion tombstone; and
observe_session + device_trust, run against the real schema, tell a new session apart from a new browser.
"""
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from psycopg import errors

from postriff_phase2 import device_trust
from postriff_phase2.coworker import flags
from postriff_phase2.hosted import observe_session

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ALICE, BOB = str(uuid.uuid4()), str(uuid.uuid4())
TABLES = ('pr_security_devices', 'pr_session_security', 'pr_security_login_events')
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', autocommit=False)


def refused(statement, params=(), error=errors.InsufficientPrivilege):
    with connection() as db:
        try:
            db.execute(statement, params)
        except error:
            db.rollback()
            return True
    return False


with connection() as db:
    for role in ('anon', 'authenticated'):
        for table in TABLES:
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                assert not db.execute('SELECT has_table_privilege(%s,%s,%s)', (role, f'public.{table}', privilege)).fetchone()[0], (role, table, privilege)
        assert not db.execute("SELECT has_function_privilege(%s,'public.pr_security_purge(uuid)','EXECUTE')", (role,)).fetchone()[0], role
    for privilege in ('UPDATE', 'DELETE', 'TRUNCATE'):
        assert not db.execute("SELECT has_table_privilege('service_role','public.pr_security_login_events',%s)", (privilege,)).fetchone()[0], privilege
    for table in TABLES:
        assert db.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (f'public.{table}',)).fetchone()[0], table
checks.append('anon and authenticated have no privilege on the three tables or the purge; the ledger grants service_role no update/delete; RLS is forced')

FLAGS = {'RAFII_ACCOUNT_PROTECTION_V2_MODE': 'observe', 'RAFII_DEVICE_TRUST_V2': '1', 'RAFII_DEVICE_COOKIE_KEYS': '2:' + 'k' * 32 + ',1:' + 'o' * 32}
flags.attach(FLAGS)


def sign_in(user, session, cookie='', site='same-origin', label='Safari on iPhone'):
    """One session route request in its own transaction; returns (fresh, issued cookie)."""
    binding = device_trust.bind({'HTTP_COOKIE': cookie, 'HTTP_SEC_FETCH_SITE': site})
    try:
        with connection() as db, db.cursor() as cur:
            fresh, _ = observe_session(cur, user, session, label)
        return fresh, device_trust.current().issued
    finally:
        device_trust.reset(binding)


def ledger(user):
    with connection() as db:
        return db.execute('SELECT event_type,session_id,device_id::text,details FROM public.pr_security_login_events WHERE user_id=%s ORDER BY occurred_at,event_type', (user,)).fetchall()


S1, S2, S3 = 'session-alice-000000000001', 'session-alice-000000000002', 'session-alice-000000000003'
fresh, cookie = sign_in(ALICE, S1)
assert fresh and cookie and len(cookie) == 43
with connection() as db:
    [(device_id, digest, version)] = db.execute('SELECT id::text,token_hash,hmac_key_version FROM public.pr_security_devices WHERE user_id=%s', (ALICE,)).fetchall()
    assert version == 2 and cookie not in digest and digest == device_trust.token_hash(b'k' * 32, ALICE, cookie)
    assert db.execute('SELECT device_id::text FROM public.pr_session_security WHERE user_id=%s AND session_id=%s', (ALICE, S1)).fetchone()[0] == device_id
kinds = [(row[0], row[3].get('device')) for row in ledger(ALICE)]
assert sorted(kinds) == [('device.first_observed', None), ('session.observed', 'new')], kinds
checks.append('a first sign-in on a new browser mints a cookie, stores only its keyed hash, links the session and records both first sightings')

fresh, issued = sign_in(ALICE, S2, cookie=f'{device_trust.COOKIE}={cookie}')
assert fresh and issued is None
assert [row[3]['device'] for row in ledger(ALICE) if row[0] == 'session.observed' and row[1] == S2] == ['known']
assert len([row for row in ledger(ALICE) if row[0] == 'device.first_observed']) == 1
checks.append('a new session on the same browser is a new session only: no new device, no second device.first_observed')

assert sign_in(ALICE, S2, cookie=f'{device_trust.COOKIE}={cookie}') == (False, None)
assert len([row for row in ledger(ALICE) if row[0] == 'session.observed' and row[1] == S2]) == 1
checks.append('a repeated request is idempotent: one session.observed per session')

# The same browser signing in to a second account is an unrelated record for that account.
fresh, issued = sign_in(BOB, 'session-bob-0000000000001', cookie=f'{device_trust.COOKIE}={cookie}')
with connection() as db:
    bob_device = db.execute('SELECT id::text,token_hash FROM public.pr_security_devices WHERE user_id=%s', (BOB,)).fetchone()
assert bob_device[0] != device_id and bob_device[1] != digest
checks.append('one browser used by two accounts is two unrelated device records')

# Server-side first request (SSR prefetch): the session is recorded and its device stays pending, no cookie minted.
fresh, issued = sign_in(ALICE, S3, site='')
assert fresh and issued is None
with connection() as db:
    assert db.execute('SELECT device_id FROM public.pr_session_security WHERE user_id=%s AND session_id=%s', (ALICE, S3)).fetchone()[0] is None
assert sign_in(ALICE, S3, cookie=f'{device_trust.COOKIE}={cookie}')[0] is False
with connection() as db:
    assert db.execute('SELECT device_id::text FROM public.pr_session_security WHERE user_id=%s AND session_id=%s', (ALICE, S3)).fetchone()[0] == device_id
checks.append('a server-side first request leaves the device pending; the browser request then links it')

# Key rotation: a device stored under the old key is found and re-hashed under the current key.
flags.attach({**FLAGS, 'RAFII_DEVICE_COOKIE_KEYS': '1:' + 'o' * 32})
fresh, old_cookie = sign_in(ALICE, 'session-alice-000000000004')
flags.attach(FLAGS)
sign_in(ALICE, 'session-alice-000000000005', cookie=f'{device_trust.COOKIE}={old_cookie}')
with connection() as db:
    assert db.execute('SELECT hmac_key_version,token_hash FROM public.pr_security_devices WHERE user_id=%s AND token_hash=%s', (ALICE, device_trust.token_hash(b'k' * 32, ALICE, old_cookie))).fetchone()[0] == 2
checks.append('a device seen under the retiring key is re-hashed under the current key')

# Revoked browser: a new token and a new record, never the old one revived.
with connection() as db:
    db.execute("UPDATE public.pr_security_devices SET state='revoked',revoked_at=now() WHERE id=%s", (device_id,))
fresh, renewed = sign_in(ALICE, 'session-alice-000000000006', cookie=f'{device_trust.COOKIE}={cookie}')
assert renewed and renewed != cookie
with connection() as db:
    assert db.execute('SELECT state FROM public.pr_security_devices WHERE id=%s', (device_id,)).fetchone()[0] == 'revoked'
checks.append('a revoked browser gets a new token and record; the revoked one is never reused')

# Append-only, for the owner too; a cross-person device link is refused; pr_sessions cleanup cannot drop state.
assert refused('UPDATE public.pr_security_login_events SET details=%s::jsonb WHERE user_id=%s', ('{}', ALICE))
assert refused('DELETE FROM public.pr_security_login_events WHERE user_id=%s', (ALICE,))
# Refused by the trigger, or (once migration 122's incidents reference the ledger) by the foreign key first.
assert refused('TRUNCATE public.pr_security_login_events', error=(errors.InsufficientPrivilege, errors.FeatureNotSupported))
assert refused('UPDATE public.pr_session_security SET device_id=%s WHERE user_id=%s', (device_id, BOB), errors.ForeignKeyViolation)
assert refused('DELETE FROM public.pr_sessions WHERE user_id=%s AND session_id=%s', (ALICE, S1), errors.ForeignKeyViolation)
checks.append('the ledger refuses update, delete and truncate even for the owner; a session cannot point at another person\'s device; pr_sessions cleanup is refused while security state exists')

# The purge: refused for a live account, complete after the deletion tombstone.
assert refused('SELECT public.pr_security_purge(%s)', (ALICE,))
with connection() as db:
    db.execute("INSERT INTO public.pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,'studio',now())", (ALICE,))
    db.execute('SELECT public.pr_security_purge(%s)', (ALICE,))
    left = [db.execute(f'SELECT count(*) FROM public.{table} WHERE user_id=%s', (ALICE,)).fetchone()[0] for table in TABLES]
    bob_left = db.execute('SELECT count(*) FROM public.pr_security_login_events WHERE user_id=%s', (BOB,)).fetchone()[0]
assert left == [0, 0, 0] and bob_left > 0, (left, bob_left)
assert refused('DELETE FROM public.pr_security_login_events WHERE user_id=%s', (BOB,))
checks.append('the purge refuses a live account and erases only the deleted person\'s state')

# Flags off: observe_session writes nothing to the new tables.
flags.attach({'RAFII_ACCOUNT_PROTECTION_V2_MODE': 'observe'})
CAROL = str(uuid.uuid4())
assert sign_in(CAROL, 'session-carol-000000000001') == (True, None)
with connection() as db:
    assert [db.execute(f'SELECT count(*) FROM public.{table} WHERE user_id=%s', (CAROL,)).fetchone()[0] for table in TABLES] == [0, 0, 0]
checks.append('with RAFII_DEVICE_TRUST_V2 off nothing is written and no cookie is minted')

print(json.dumps({'status': 'pass', 'execution': 'disposable-local-postgres', 'checks': checks}, indent=2))
