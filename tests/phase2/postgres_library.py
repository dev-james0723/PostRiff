"""Migration 089 Universal Library: normalized rows, full-text index and service-only RLS."""
import json,psycopg
DSN="host=127.0.0.1 port=55438 dbname=postgres";ONE="00000000-0000-0000-0000-000000000001";checks=[]
def connection():return psycopg.connect(DSN,client_encoding="utf8")
with connection() as db:
 for table in ("pr_library_assets","pr_library_chunks"):
  row=db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",(f"public.{table}",)).fetchone();assert row and all(row),row
 checks.append("asset and chunk tables force RLS")
 wid=str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s",(ONE,)).fetchone()[0]);aid="11111111-2222-4333-8444-555555555555"
 db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,kind,mime,extension,bytes,bucket,object_name,processing_status,analysis_status,indexing_status) VALUES(%s,%s,%s,'notes.txt','Rehearsal notes','document','text/plain','txt',12,'postriff-library','11111111222243338444555555555555.txt','ready','not_applicable','ready')",(aid,wid,ONE))
 db.execute("INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,0,'Brahms rehearsal fingering notes')",(aid,wid))
 hit=db.execute("SELECT count(*) FROM public.pr_library_chunks WHERE workspace_id=%s AND search_vector@@plainto_tsquery('simple','Brahms fingering')",(wid,)).fetchone()[0];assert hit==1,hit
 checks.append("workspace-scoped chunk full-text search works")
 db.rollback()
for statement in ("SELECT * FROM public.pr_library_assets","SELECT * FROM public.pr_library_chunks"):
 with connection() as db:
  db.execute("SET ROLE authenticated");db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)",(ONE,))
  try:db.execute(statement)
  except psycopg.errors.InsufficientPrivilege:db.rollback()
  else:raise AssertionError("browser role could read "+statement)
checks.append("authenticated browser role cannot read normalized Library tables")
with connection() as db:
 db.execute("SET ROLE service_role");db.execute("SELECT count(*) FROM public.pr_library_assets");db.rollback()
checks.append("service_role can access normalized Library tables")
print(json.dumps({"status":"pass","execution":"disposable-local-postgres","checks":checks},indent=2))
