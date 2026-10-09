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
elif mode=='history':
    # One imported Instagram post with the founder's real shape: six lifetime metrics read 23 minutes after
    # publishing, five measured zeros and one metric the provider did not return.
    connection='phase2-fixture-instagram'
    with psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres') as db:
        db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'",(wid,connection))
        db.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,published_at,media_type,caption_chars,source) VALUES(%s,%s,'instagram','fixture-ig-1',now()-interval '3 days','IMAGE',42,'history_import') ON CONFLICT DO NOTHING",(wid,connection))
        db.execute("INSERT INTO public.pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at,status,observed_at) VALUES(%s,%s,'instagram','fixture-ig-1','backfill','history_import',now()-interval '3 days',now()-interval '3 days','done',now()-interval '3 days'+interval '23 minutes') ON CONFLICT DO NOTHING",(wid,connection))
        for metric,value in (('reach',0),('views',0),('likes',0),('comments',0),('saved',0),('shares',None)):
            db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,metric,definition_version,value,unit,availability,observed_at,read_offset) VALUES(%s,%s,'instagram','fixture-ig-1',%s,'2026-09',%s,'count',%s,now()-interval '3 days'+interval '23 minutes','backfill')",
                       (wid,connection,metric,value,'available' if value is not None else 'unavailable'))
    print(json.dumps({'execution':'disposable imported-history fixture'}))
else:
    assert mode=='seed','Unknown disposable scenario'
    print(json.dumps(seed(host,wid,'fixture')))
