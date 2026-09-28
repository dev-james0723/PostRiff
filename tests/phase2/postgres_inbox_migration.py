"""Migration 047 on a disposable pre-047 shape, then replay with RLS checks."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
MIGRATION = Path(__file__).resolve().parents[2] / "migrations/postriff/047_inbox_operational_sync.sql"
with psycopg.connect(DSN) as db:
    db.execute("DROP TABLE public.pr_audience_sync")
    db.execute("ALTER TABLE public.pr_audience_threads DROP COLUMN permalink")
    db.execute("ALTER TABLE public.pr_reply_drafts DROP COLUMN dispatch_started_at,DROP COLUMN dispatch_id")
    db.execute("ALTER TABLE public.pr_reply_drafts DROP CONSTRAINT pr_reply_drafts_status_check")
    db.execute("ALTER TABLE public.pr_reply_drafts ADD CONSTRAINT pr_reply_drafts_status_check CHECK (status IN ('draft','approved','submitting','submitted','verified','failed','uncertain','cancelled'))")

for _ in range(2):
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/psql", DSN, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(MIGRATION)],
                   check=True, stdout=subprocess.DEVNULL)

with psycopg.connect(DSN) as db:
    assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_audience_sync'::regclass").fetchone() == (True, True)
    assert db.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND ((table_name='pr_audience_threads' AND column_name='permalink') OR (table_name='pr_reply_drafts' AND column_name IN ('dispatch_started_at','dispatch_id'))) ").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='pr_audience_sync'").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname IN ('pr_audience_sync_due_idx','pr_reply_drafts_claim_idx')").fetchone()[0] == 2
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',false)")
    assert db.execute("SELECT count(*) FROM public.pr_audience_sync").fetchone()[0] == 0
    try:
        db.execute("INSERT INTO public.pr_audience_sync(workspace_id,connection_id,provider) SELECT id,'x','threads' FROM public.pr_workspaces LIMIT 1")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    else:
        raise AssertionError("Browser role inserted sync state")

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL", "checks": ["pre-047 shape upgrade", "migration replay", "forced RLS", "browser read and write denial", "index and policy uniqueness"]}))
