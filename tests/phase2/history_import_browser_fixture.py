"""Seed only the Stage 3B disposable local browser database; no provider or model calls."""
import json
import sys
from pathlib import Path
from uuid import UUID
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.hosted import bucket
kind, port, principal, wid, conn = sys.argv[1:6]
assert port in ('55836', '55479'), 'Stage 3B or consumer-ready disposable database only'
UUID(principal); UUID(wid)
with psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres') as db, db.cursor() as cur:
    if kind in ('viewer', 'owner'):
        cur.execute('UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s', (kind, wid, principal))
    elif kind in ('analytics-off', 'analytics-on'):
        cur.execute("UPDATE public.pr_channel_capabilities SET level=%s WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", ('Assisted' if kind == 'analytics-off' else 'Direct', wid, conn))
    elif kind == 'ready':
        cur.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'", (wid, conn))
        cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=ARRAY['threads_basic','threads_manage_insights'] WHERE workspace_id=%s AND connection_id=%s", (wid, conn))
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,))
        state = cur.fetchone()[0]
        for channel in state['phase2']['channels']:
            if channel['id'] == conn: channel.update(scopes=['threads_basic','threads_manage_insights'], capabilityVerified=True, identityVerified=True)
        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), wid))
    elif kind == 'throttle':
        cur.execute("INSERT INTO public.pr_auth_throttle(bucket,window_start,count) VALUES(%s,now(),5) ON CONFLICT(bucket) DO UPDATE SET count=5,window_start=now()", (bucket(f'history-import:{wid}:{principal}'),))
    elif kind == 'none':
        cur.execute('DELETE FROM public.pr_growth_purges WHERE workspace_id=%s AND connection_id=%s', (wid, conn))
        cur.execute('DELETE FROM public.pr_history_imports WHERE workspace_id=%s AND connection_id=%s', (wid, conn))
        cur.execute("DELETE FROM public.pr_metric_reads WHERE workspace_id=%s AND connection_id=%s AND source='history_import'", (wid, conn))
        cur.execute('DELETE FROM public.pr_auth_throttle WHERE bucket=%s', (bucket(f'history-import:{wid}:{principal}'),))
    elif kind == 'purge':
        cur.execute('INSERT INTO public.pr_growth_purges(workspace_id,connection_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (wid, conn))
    else:
        status = {'done':'done','retry':'running','failed':'failed','cancelled':'cancelled'}[kind]
        cur.execute("UPDATE public.pr_history_imports SET status=%s,pages=2,posts=3,failure_class=%s,lease_until=CASE WHEN %s THEN now()+interval '60 seconds' ELSE NULL END,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (status, 'http_429' if kind=='retry' else ('incomplete_paging' if kind=='failed' else None), kind=='retry', wid, conn))
        if kind == 'done':
            M.schedule(cur, wid, conn, 'threads', 'synthetic-imported-post', None, 1_800_000_000, 'history_import', (('backfill', 0),))
print(json.dumps({'execution':'synthetic local fixture', 'state':kind}))
