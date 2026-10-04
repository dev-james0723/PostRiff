"""Only the dedicated disposable Phase 2 browser database is accepted."""
import sys,json,uuid,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from growth_phase2_fixtures import seed
port,principal,wid=sys.argv[1:4]
assert port==os.environ.get('POSTRIFF_GROWTH_TEST_PG_PORT','55796') and port.isdecimal(),'Only the explicitly selected disposable Phase 2 harness port'
uuid.UUID(principal);uuid.UUID(wid)
host=HostedWorkspaceService(lambda:psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres'),lambda t:principal)
mode=sys.argv[4] if len(sys.argv)>4 else 'seed'
if mode=='empty':
    def empty(state,actor):
        state['phase2']['jobs']=[]
        state['phase2']['channels']=[]
        return state
    host.repository.command(wid,'fixture',host.repository.get(wid,'fixture')['revision'],empty)
    print(json.dumps({'execution':'disposable empty-workspace fixture'}))
elif mode in ('role-owner','role-editor','role-viewer'):
    with host.connection_factory() as db:
        db.execute("UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s AND status='active'",(mode.removeprefix('role-'),wid,principal))
    print(json.dumps({'execution':'disposable membership fixture','role':mode.removeprefix('role-')}))
else:
    assert mode=='seed','Unknown disposable scenario'
    print(json.dumps(seed(host,wid,'fixture')))
