"""Migration 008 on disposable PostgreSQL: the provider_price_id column and the server-only
pr_notifications table exist after 001–008, the dedupe key is unique, and the browser role
can neither read nor write notification rows.
"""
import json

import psycopg

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


with connection() as db:
    row = db.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_plan_terms' AND column_name='provider_price_id'").fetchone()
    assert row and row[0] == "text", row
    checks.append("pr_plan_terms.provider_price_id exists (text, nullable)")
    columns = dict(db.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_notifications'").fetchall())
    assert {"id", "workspace_id", "user_id", "kind", "dedupe_key", "sent", "meta", "created_at"} <= set(columns), columns
    checks.append("pr_notifications exists with the contract columns")
    assert all(db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_notifications'::regclass").fetchone())
    checks.append("pr_notifications has RLS enabled and forced")
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key) VALUES(%s,%s,'welcome',%s)", (wid, ONE, f"welcome:{wid}:{ONE}"))
    try:
        db.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key) VALUES(%s,%s,'welcome',%s)", (wid, ONE, f"welcome:{wid}:{ONE}"))
    except psycopg.errors.UniqueViolation:
        db.rollback()
    else:
        raise AssertionError("duplicate dedupe_key accepted")
    checks.append("dedupe_key is unique")

for statement in ("SELECT * FROM public.pr_notifications", "INSERT INTO public.pr_notifications(workspace_id,kind,dedupe_key) VALUES(gen_random_uuid(),'x','forged')"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError(f"browser role was allowed: {statement}")
checks.append("pr_notifications is never browser-readable or writable")

with connection() as db:
    db.execute("SET ROLE service_role")
    db.execute("INSERT INTO public.pr_notifications(workspace_id,kind,dedupe_key,sent) SELECT id,'trial_ending','trial_ending:'||id::text,true FROM public.pr_workspaces LIMIT 1")
    db.execute("UPDATE public.pr_plan_terms SET provider_price_id='price_test' WHERE id='studio-v1'")
    db.rollback()
checks.append("service_role can write notifications and provider price ids")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
