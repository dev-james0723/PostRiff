"""Disposable PostgreSQL: audit API and RLS agree on owner/admin access; no live data."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'
def connection(): return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres', client_encoding='utf8')
service = HostedWorkspaceService(connection, lambda token: ONE if token == 'one' else TWO)
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    db.execute(Path('migrations/postriff/015_audit_visibility.sql').read_text())
    db.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind) VALUES(%s,%s,'synthetic.audit.test')", (wid, ONE))
for role in ('owner', 'admin', 'editor', 'approver', 'viewer'):
    with connection() as db:
        db.execute('UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s', (role, wid, ONE))
    allowed = role in ('owner', 'admin')
    try:
        result = service.audit_events(wid, 'one')
        assert allowed and any(row['kind'] == 'synthetic.audit.test' for row in result['events'])
    except AlphaError as error:
        assert not allowed and error.status == 403 and error.code == 'audit_access_required'
    with connection() as db:
        db.execute('SET ROLE authenticated')
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        rows = db.execute('SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s', (wid,)).fetchall()
        assert bool(rows) == allowed
with connection() as db:
    db.execute('UPDATE public.pr_memberships SET role=\'owner\' WHERE workspace_id=%s AND user_id=%s', (wid, ONE))
    assert db.execute('SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s', (wid,)).fetchone()[0] > 0
    db.execute('SET ROLE authenticated')
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (TWO,))
    assert db.execute('SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s', (wid,)).fetchall() == []
print(json.dumps({'status':'pass','execution':'disposable-local-postgres','checks':['owner/admin API and RLS read','editor/approver/viewer denied by API and RLS','cross-workspace read denied','audit records retained']}))
