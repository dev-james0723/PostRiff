"""Only the dedicated disposable Phase 2 browser database is accepted."""
import sys,json,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from growth_phase2_fixtures import seed
port,principal,wid=sys.argv[1:4]
assert port=='55796','Only the disposable Phase 2 harness port'
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
else:
    assert mode in ('seed', 'official-contract'), 'Unknown disposable scenario'
    # Exercise the positive provider trust contract only after the browser has
    # proved that explicitly synthetic observations cannot create a lesson.
    # These simulated fields are confined to this guarded disposable database;
    # they are never a receipt for a real publication or measured outcome.
    result = seed(host, wid, 'fixture', simulate_official_contract=mode == 'official-contract')
    print(json.dumps({**result, 'execution': 'disposable simulated provider contract' if mode == 'official-contract' else 'disposable synthetic observations'}))
