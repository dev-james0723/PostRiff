"""Self-serve feature enrollment on disposable PostgreSQL (found by postriff_pg_suite).

Covers: forced RLS (authenticated cannot read or write), owner-only, idempotent
enroll/unenroll, cohort cap under concurrency, kill switch and denylist, audit
rows, tenant separation and the trend admission split (read admission vs egress).
All identities are the synthetic rls.sql fixtures.
"""
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import feature_enrollment as fe
from postriff_phase2.growth.trends import admission

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
OPEN = {"RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "1",
        "RAFII_TREND_INTELLIGENCE_ENABLED": "1", "POSTRIFF_METRIC_SELF_SERVE_ENABLED": "1",
        "POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES": "5"}


def connect():
    return psycopg.connect(DSN, client_encoding="utf8")


def refused(code, operation):
    try:
        operation()
    except AlphaError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError("expected refusal " + code)


def main():
    with connect() as db:
        if not db.execute("SELECT to_regclass('public.pr_feature_enrollments')").fetchone()[0]:
            db.execute((ROOT / "migrations/postriff/103_feature_enrollments.sql").read_text())
        one = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
        two = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0])
        db.execute("DELETE FROM public.pr_feature_enrollments")
        flags = db.execute("""SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c
                              JOIN pg_namespace n ON n.oid=c.relnamespace
                              WHERE n.nspname='public' AND c.relname='pr_feature_enrollments'""").fetchone()
        assert flags == (True, True), flags
        grants = db.execute("""SELECT count(*) FROM information_schema.role_table_grants
                               WHERE table_schema='public' AND table_name='pr_feature_enrollments'
                                 AND grantee IN ('anon','authenticated','PUBLIC')""").fetchone()[0]
        assert grants == 0, grants

    # Closed switch, wrong role and denylist refuse before any write.
    with connect() as db, db.cursor() as cur:
        refused("self_serve_paused", lambda: fe.enroll(cur, one, "trend_radar", actor=ONE, role="owner", values={}))
        refused("owner_required", lambda: fe.enroll(cur, one, "trend_radar", actor=ONE, role="editor", values=OPEN))
        refused("owner_required", lambda: fe.enroll(cur, one, "trend_radar", actor=ONE, role="viewer", values=OPEN))
        refused("workspace_not_eligible", lambda: fe.enroll(cur, one, "trend_radar", actor=ONE, role="owner",
                                                             values={**OPEN, fe.DENYLIST: one}))
        assert cur.execute("SELECT count(*) FROM public.pr_feature_enrollments").fetchone()[0] == 0

    # Owner enrollment is idempotent and audited once.
    with connect() as db, db.cursor() as cur:
        first = fe.enroll(cur, one, "trend_radar", actor=ONE, role="owner", values=OPEN)
        again = fe.enroll(cur, one, "trend_radar", actor=ONE, role="owner", values=OPEN)
        assert first["replayed"] is False and again["replayed"] is True, (first, again)
        audits = cur.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='feature.enrolled'",
                             (one,)).fetchone()[0]
        assert audits == 1, audits
        assert fe.admitted(cur, one, "trend_radar", OPEN) is True
        assert fe.admitted(cur, one, "trend_radar", {**OPEN, "RAFII_TREND_SELF_SERVE_ENABLED": "0"}) is False
        assert fe.admitted(cur, one, "trend_radar", {**OPEN, fe.DENYLIST: one}) is False
        assert fe.admitted(cur, two, "trend_radar", OPEN) is False
        assert fe.admitted(cur, one, "growth_measurement", OPEN) is False
        # Read admission vs egress: enrollment never admits provider dispatch.
        assert admission.admitted(cur, one, OPEN) is True
        assert admission.egress_allowed(one, OPEN) is False
        assert admission.admitted(cur, one, {**OPEN, "RAFII_TREND_INTELLIGENCE_ENABLED": "0"}) is False
        assert fe.admitted_workspaces(cur, "trend_radar", OPEN) == [one]

    # Cohort cap (1) holds for a second workspace, including a concurrent race.
    with connect() as db, db.cursor() as cur:
        refused("cohort_full", lambda: fe.enroll(cur, two, "trend_radar", actor=TWO, role="owner", values=OPEN))
        db.execute("DELETE FROM public.pr_feature_enrollments WHERE feature='trend_radar'")
    outcomes, barrier = [], threading.Barrier(2)

    def race(workspace, actor):
        with connect() as db, db.cursor() as cur:
            barrier.wait()
            try:
                outcomes.append(fe.enroll(cur, workspace, "trend_radar", actor=actor, role="owner", values=OPEN)["status"])
            except AlphaError as error:
                outcomes.append(error.code)
    threads = [threading.Thread(target=race, args=(one, ONE)), threading.Thread(target=race, args=(two, TWO))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["active", "cohort_full"], outcomes
    with connect() as db:
        active = db.execute("SELECT count(*) FROM public.pr_feature_enrollments WHERE feature='trend_radar' AND status='active'").fetchone()[0]
        assert active == 1, active

    # Leaving is owner-only, idempotent, audited, and always allowed (even when paused).
    with connect() as db, db.cursor() as cur:
        holder = cur.execute("SELECT workspace_id::text FROM public.pr_feature_enrollments WHERE feature='trend_radar' AND status='active'").fetchone()[0]
        actor = ONE if holder == one else TWO
        refused("owner_required", lambda: fe.unenroll(cur, holder, "trend_radar", actor=actor, role="admin"))
        left = fe.unenroll(cur, holder, "trend_radar", actor=actor, role="owner")
        again = fe.unenroll(cur, holder, "trend_radar", actor=actor, role="owner")
        assert left["replayed"] is False and again["replayed"] is True
        assert fe.status(cur, holder, "trend_radar") == "revoked"
        assert fe.admitted(cur, holder, "trend_radar", OPEN) is False
        # Re-enrolling bumps the revision and clears the revocation.
        fe.enroll(cur, holder, "trend_radar", actor=actor, role="owner", values=OPEN)
        row = cur.execute("SELECT status, revision, revoked_at FROM public.pr_feature_enrollments WHERE workspace_id=%s AND feature='trend_radar'",
                          (holder,)).fetchone()
        assert row[0] == "active" and row[1] == 3 and row[2] is None, row

    # Authenticated (browser JWT) role can neither read nor write the table.
    with connect() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        for statement in ("SELECT count(*) FROM public.pr_feature_enrollments",
                          "INSERT INTO public.pr_feature_enrollments(workspace_id,feature,status,policy_version,enrolled_by) "
                          "VALUES('%s','growth_measurement','active','x','%s')" % (one, ONE)):
            try:
                with db.transaction():
                    db.execute(statement)
            except psycopg.errors.InsufficientPrivilege:
                continue
            raise AssertionError("authenticated reached pr_feature_enrollments: " + statement[:40])
        db.execute("RESET ROLE")
    print("postgres_feature_enrollments: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
