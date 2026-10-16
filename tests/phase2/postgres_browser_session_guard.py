"""Disposable PostgreSQL: RAPv2 H-1. A browser JWT read straight through the Data API obeys the hosted API's
session rules: a revoked session, a missing session, a deleted account and an AAL1 session of an account that
enforces two-factor sign-in read nothing, while a live session still reads its own workspace. No live data."""
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
USER = str(uuid.uuid4())
LIVE, REVOKED = 'session-live-0000000000001', 'session-revoked-00000000001'


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (USER,))
    wid = str(db.execute("SELECT public.pr_bootstrap(%s,'studio')", (USER,)).fetchone()[0])
    db.execute('INSERT INTO storage.objects(bucket_id,name) VALUES(%s,%s)', ('postriff-private', f'{wid}/synthetic/object.bin'))
    db.execute('INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s)', (USER, REVOKED))
    # Every RLS table the browser role can read carries the guard, and so does storage.objects.
    unguarded = db.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                              WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relrowsecurity
                                AND has_table_privilege('authenticated', c.oid, 'SELECT')
                                AND NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname='public' AND p.tablename=c.relname
                                                AND p.policyname='rapv2_browser_session' AND p.permissive='RESTRICTIVE')""").fetchall()
    assert unguarded == [], unguarded
    assert db.execute("SELECT count(*) FROM pg_policies WHERE schemaname='storage' AND tablename='objects' AND policyname='rapv2_browser_session' AND permissive='RESTRICTIVE'").fetchone()[0] == 1


def browser_reads(session=None, aal=None, claims_json=False):
    """(workspaces, private objects) a browser JWT for USER can read. A fresh connection per check: SET ROLE and the
    claim settings are session state."""
    with connection() as db:
        db.execute('SET ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (USER,))
        if claims_json:
            # Production PostgREST sets one JSON object; the per-claim settings stay empty there.
            db.execute("SELECT set_config('request.jwt.claim.session_id','',false)")
            db.execute("SELECT set_config('request.jwt.claims',%s,false)", (json.dumps({'sub': USER, 'session_id': session, 'aal': aal or 'aal1'}),))
        else:
            db.execute("SELECT set_config('request.jwt.claim.session_id',%s,false)", (session or '',))
            db.execute("SELECT set_config('request.jwt.claim.aal',%s,false)", (aal or '',))
        workspaces = db.execute('SELECT count(*) FROM public.pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
        objects = db.execute("SELECT count(*) FROM storage.objects WHERE bucket_id='postriff-private' AND name LIKE %s", (wid + '/%',)).fetchone()[0]
        return workspaces, objects


checks = []
assert browser_reads(LIVE) == (1, 1)
assert browser_reads(LIVE, claims_json=True) == (1, 1)
checks.append('a live session still reads its own workspace and private objects (per-claim and JSON claims)')
assert browser_reads(REVOKED) == (0, 0)
assert browser_reads(REVOKED, claims_json=True) == (0, 0)
checks.append('a revoked session reads nothing, although its JWT is still valid')
assert browser_reads(None) == (0, 0)
checks.append('a token without a session id reads nothing')

with connection() as db:
    db.execute('INSERT INTO public.pr_mfa_enforcement(user_id) VALUES(%s)', (USER,))
assert browser_reads(LIVE, aal='aal1') == (0, 0)
assert browser_reads(LIVE, aal='aal2') == (1, 1)
assert browser_reads(LIVE, aal='aal2', claims_json=True) == (1, 1)
checks.append('with two-factor enforced, AAL1 reads nothing and AAL2 reads as before')

with connection() as db:
    db.execute("INSERT INTO public.pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,'studio',now())", (USER,))
assert browser_reads(LIVE, aal='aal2') == (0, 0)
checks.append('a deleted account reads nothing')

print(json.dumps({'status': 'pass', 'execution': 'disposable-local-postgres', 'checks': checks}, indent=2))
