"""AC30/AC36 for migration 081 on disposable PostgreSQL: upgrade from the pre-081 shape, replay, forced RLS, least-privilege
grants, composite same-workspace references, append-only history and the guarded result reference.

The results slice's migration 080 is not part of this branch: a minimal stand-in ``pr_result_events`` (uuid id +
workspace_id, no composite key) is created here only to prove 081's guarded block adds the key and foreign key when
the table exists. It is labelled synthetic and is not 080."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
MIGRATION = Path(__file__).resolve().parents[2] / "migrations/postriff/081_relationships.sql"
PSQL = str(Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")) / "psql")


def apply():
    subprocess.run([PSQL, DSN, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(MIGRATION)], check=True, stdout=subprocess.DEVNULL)


def refused(db, sql, params=(), error=psycopg.errors.InsufficientPrivilege):
    """Autocommit connection: each probe is its own statement, so a refusal leaves nothing behind."""
    try:
        db.execute(sql, params)
    except error:
        return True
    return False


with psycopg.connect(DSN, autocommit=True) as db:   # the pre-081 shape (rls.sql applied 081 once already)
    db.execute("DROP TABLE public.pr_relationship_events, public.pr_relationship_threads, public.pr_relationships")
    db.execute("ALTER TABLE public.pr_audience_threads DROP CONSTRAINT pr_audience_threads_workspace_id_id_key")
for _ in range(2):
    apply()

ONE, TWO = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
checks = []
with psycopg.connect(DSN, autocommit=True) as db:
    tables = ("pr_relationships", "pr_relationship_threads", "pr_relationship_events")
    for table in tables:
        assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (f"public.{table}",)).fetchone() == (True, True), table
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='public.pr_audience_threads'::regclass AND conname='pr_audience_threads_workspace_id_id_key'").fetchone()[0] == 1
    policies = dict(db.execute("SELECT tablename,count(*) FROM pg_policies WHERE schemaname='public' AND tablename=ANY(%s) GROUP BY tablename", (list(tables),)).fetchall())
    assert policies == {"pr_relationships": 2, "pr_relationship_threads": 2, "pr_relationship_events": 3}, policies
    grants = {(r[0], r[1], r[2]) for r in db.execute("SELECT table_name,grantee,privilege_type FROM information_schema.role_table_grants WHERE table_schema='public' "
                                                      "AND table_name=ANY(%s) AND grantee IN ('anon','authenticated','service_role')", (list(tables),)).fetchall()}
    for table in tables:
        assert {p for t, g, p in grants if t == table and g == "authenticated"} == {"SELECT"}, table
        assert not {p for t, g, p in grants if t == table and g == "anon"}, table
    assert {p for t, g, p in grants if t == "pr_relationship_events" and g == "service_role"} == {"SELECT", "INSERT"}
    checks += ["pre-081 upgrade and replay", "forced RLS on three tables", "browser read-only grants", "history insert/select only"]

    # Fixture rows: two workspaces from rls.sql's bootstrap (user one owns both of its own; user two was revoked there).
    db.execute("UPDATE public.pr_memberships SET status='active' WHERE user_id=%s", (TWO,))
    w1 = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 1", (ONE,)).fetchone()[0])
    w2 = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s LIMIT 1", (TWO,)).fetchone()[0])
    t1 = str(db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) "
                        "VALUES(%s,'c1','threads','1','11','How much?') RETURNING id", (w1,)).fetchone()[0])
    t2 = str(db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) "
                        "VALUES(%s,'c2','threads','2','22','Other workspace') RETURNING id", (w2,)).fetchone()[0])
    r1 = str(db.execute("INSERT INTO public.pr_relationships(workspace_id,display_name,created_by) VALUES(%s,'Mei',%s) RETURNING id", (w1, ONE)).fetchone()[0])
    db.execute("INSERT INTO public.pr_relationship_threads(workspace_id,relationship_id,thread_id) VALUES(%s,%s,%s)", (w1, r1, t1))
    # A link can never point at another workspace's thread, nor a relationship at another workspace's history.
    assert refused(db, "INSERT INTO public.pr_relationship_threads(workspace_id,relationship_id,thread_id) VALUES(%s,%s,%s)", (w1, r1, t2), psycopg.errors.ForeignKeyViolation)
    assert refused(db, "INSERT INTO public.pr_relationship_threads(workspace_id,relationship_id,thread_id) VALUES(%s,%s,%s)", (w2, r1, t2), psycopg.errors.ForeignKeyViolation)
    assert refused(db, "INSERT INTO public.pr_relationship_events(workspace_id,relationship_id,kind) VALUES(%s,%s,'created')", (w2, r1), psycopg.errors.ForeignKeyViolation)
    checks.append("composite same-workspace references")
    # Shape constraints: won needs a result, a due time needs its zone, notes are bounded, contact refs are provider-scoped.
    for sql in ("UPDATE public.pr_relationships SET state='won' WHERE id=%s",
                "UPDATE public.pr_relationships SET due_at=now() WHERE id=%s",
                "UPDATE public.pr_relationships SET notes=(SELECT jsonb_agg(n) FROM generate_series(1,21) n) WHERE id=%s",
                "UPDATE public.pr_relationships SET contact_ref='mei' WHERE id=%s",
                "UPDATE public.pr_relationships SET due_at=now(),due_time_zone='Not a zone!' WHERE id=%s",
                "UPDATE public.pr_relationships SET display_name=repeat('x',121) WHERE id=%s"):
        assert refused(db, sql, (r1,), psycopg.errors.CheckViolation), sql
    checks.append("state/due/notes/contact/name constraints")

    # Browser role: members read their own workspace only; nobody writes; anon has nothing.
    db.execute("INSERT INTO public.pr_relationship_events(workspace_id,relationship_id,kind,to_state,actor) VALUES(%s,%s,'created','new',%s)", (w1, r1, ONE))
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    assert db.execute("SELECT count(*) FROM public.pr_relationships").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM public.pr_relationship_threads").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM public.pr_relationship_events").fetchone()[0] == 1
    assert refused(db, "INSERT INTO public.pr_relationships(workspace_id,display_name,created_by) VALUES(%s,'x',%s)", (w1, ONE))
    assert refused(db, "UPDATE public.pr_relationships SET display_name='x'")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (TWO,))
    assert db.execute("SELECT count(*) FROM public.pr_relationships").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_relationship_events").fetchone()[0] == 0
    db.execute("RESET ROLE")
    db.execute("SET ROLE anon")
    assert refused(db, "SELECT count(*) FROM public.pr_relationships")
    db.execute("RESET ROLE")
    # The trusted service role writes records but cannot rewrite or delete history.
    db.execute("SET ROLE service_role")
    db.execute("UPDATE public.pr_relationships SET next_action='Send the schedule' WHERE id=%s", (r1,))
    assert refused(db, "UPDATE public.pr_relationship_events SET kind='closed'")
    assert refused(db, "DELETE FROM public.pr_relationship_events")
    db.execute("RESET ROLE")
    checks += ["member-only reads and no browser writes", "revoked/foreign member sees nothing", "anon denied", "history immutable for the service role"]

    # Results (080) precede 081 in the integrated chain: the won foreign key exists, and re-applying 081 keeps it once.
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conname='pr_relationships_won_result_fk'").fetchone()[0] == 1
    apply()
    apply()
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conname='pr_relationships_won_result_fk'").fetchone()[0] == 1

    def declared(workspace):
        return str(db.execute("INSERT INTO public.pr_result_events(workspace_id,provenance,result_type,provider_event_id,occurred_at,payload_digest,declared_by) "
                              "VALUES(%s,'user_declared','lead',%s,now(),%s,%s) RETURNING id", (workspace, "decl_" + uuid.uuid4().hex, "a" * 64, str(uuid.uuid4()))).fetchone()[0])
    mine, theirs = declared(w1), declared(w2)
    assert refused(db, "UPDATE public.pr_relationships SET state='won',won_result_id=%s WHERE id=%s", (theirs, r1), psycopg.errors.ForeignKeyViolation)
    db.execute("UPDATE public.pr_relationships SET state='won',won_result_id=%s,won_provenance='user_declared' WHERE id=%s", (mine, r1))
    assert refused(db, "UPDATE public.pr_relationships SET won_result_id=%s WHERE id=%s", (str(uuid.uuid4()), r1), psycopg.errors.ForeignKeyViolation)
    checks.append("won references a same-workspace result of the integrated results table")

    # Workspace deletion cascades through records, links and history.
    # A declared result referenced by a won follow-up cannot disappear on its own (NO ACTION); the workspace takes both.
    assert refused(db, "DELETE FROM public.pr_result_events WHERE id=%s", (mine,), psycopg.errors.ForeignKeyViolation)
    db.execute("DELETE FROM public.pr_memberships WHERE workspace_id=%s", (w1,))
    db.execute("DELETE FROM public.pr_workspaces WHERE id=%s", (w1,))
    assert db.execute("SELECT (SELECT count(*) FROM public.pr_relationships WHERE workspace_id=%s)+(SELECT count(*) FROM public.pr_relationship_threads WHERE workspace_id=%s)"
                      "+(SELECT count(*) FROM public.pr_relationship_events WHERE workspace_id=%s)", (w1, w1, w1)).fetchone()[0] == 0
    checks.append("workspace deletion cascades")

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL; migrations 080 + 081", "checks": checks}))
