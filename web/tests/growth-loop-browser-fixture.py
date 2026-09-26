"""Browser-only fixture. Refuses all but the caller's disposable loopback DB."""
import json
import sys
import time
import uuid
import psycopg
from psycopg.conninfo import conninfo_to_dict

workspace_id, dsn = sys.argv[1:]
uuid.UUID(workspace_id)
parts = conninfo_to_dict(dsn)
if parts.get('host') != '127.0.0.1' or parts.get('port') != '55459':
    raise SystemExit('Fixture requires the dedicated disposable browser database.')
cohort = {'provider': 'threads', 'connectionId': 'browser-fixture', 'language': 'en', 'contentTypeId': 'text', 'definitionVersion': '2026-09'}
hid = str(uuid.uuid4())
with psycopg.connect(dsn) as db:
    db.execute("""INSERT INTO public.pr_strategy_hypotheses(id,workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,confidence,expires_at)
                  VALUES(%s,%s,'Threads','opening',%s::jsonb,'Question openings may reach more people for this account.','views','question','statement',5,5,0.5,'low',to_timestamp(%s))""", (hid, workspace_id, json.dumps(cohort), time.time()+60*86400))
print(json.dumps({'hypothesisId': hid, 'execution': 'synthetic local browser fixture'}))
