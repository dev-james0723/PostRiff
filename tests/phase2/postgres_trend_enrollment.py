"""Trends self-serve enrollment on disposable PostgreSQL (found by postriff_pg_suite).

Real SQL for: enrollment + shared corpus entitlement grant ONLY under a reviewed
cross-workspace policy, revoke on leave, scope-signature change (old signed cursors
stop decoding), readiness states and tenant isolation. Identities are the synthetic
rls.sql fixtures; no provider, model or network is involved.
"""
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends import contracts, readiness
from postriff_phase2.growth.trends.enrollment import TrendEnrollment
from postriff_phase2.growth.trends.store import TrendStore
from postriff_phase2.ideas import IdeasService

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
SHARED = "shared:rafii-trend-corpus"
DENIED = "shared:rafii-trend-denied"
ON = {"RAFII_TREND_" + k + "_ENABLED": "1" for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")}
VALUES = {**ON, "RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "1",
          "RAFII_TREND_SHARED_CORPUS_SCOPE": SHARED}
MEMBER = "SELECT w.revision,w.state,m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections"


def connect():
    return psycopg.connect(DSN, client_encoding="utf8")


class Repository:
    """The verified-membership transaction shape, keyed by the fixture principal.

    Session verification is out of scope here (covered by the hosted suites); the
    membership/workspace row lock and everything after it is the real SQL path.
    """

    @contextmanager
    def transaction(self, token, workspace_id):
        principal = token.removeprefix("user:")
        with connect() as db, db.cursor() as cur:
            cur.execute(MEMBER + """ FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id
                WHERE w.id=%s AND m.user_id=%s AND m.status='active' FOR UPDATE OF w""", (workspace_id, principal))
            row = cur.fetchone()
            if not row:
                raise AlphaError("Workspace unavailable.", 403)
            yield cur, row, principal


def manager(values):
    hosted = SimpleNamespace(connection_factory=connect,
                             ideas=SimpleNamespace(_state=IdeasService._state, _member=IdeasService._member))
    return TrendEnrollment(SimpleNamespace(hosted=hosted, repository=Repository(), values=values))


def refused(code, operation):
    try:
        operation()
    except AlphaError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError("expected refusal " + code)


def shared_policy(store, scope, *, share="allow", days=20):
    now = datetime.now(timezone.utc)
    start, end = contracts.iso(now - timedelta(hours=1)), contracts.iso(now + timedelta(days=days))
    provider = "reviewed-shared-" + scope.split(":")[1]
    store.ensure_scope(scope)
    store.register_contract(provider, "review-1", list(contracts.PERMISSIONS), start, contracts.iso(now + timedelta(days=90)),
                            {"execution": "synthetic-test-only"})
    rights = {name: {"state": share if name == "share_across_workspaces" else "allow", "policy_ref": "synthetic-rights-review.v1",
                     "audience_scope": scope, "expires_at": end} for name in contracts.PERMISSIONS}
    store.register_policy({"scope_key": scope, "provider_id": provider, "version": "review-1", "rights": rights,
                           "effective_at": start, "expires_at": end, "retention_seconds": 7200, "readiness": "ready"},
                          provider_contract_version="review-1")
    return end


def readiness_for(workspace_id, role="owner", values=VALUES):
    with connect() as db, db.cursor() as cur:
        return readiness.trend_readiness(cur, workspace_id, role=role, values=values)


def main():
    with connect() as db:
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT / "migrations/postriff/040_social_trend_intelligence.sql").read_text())
        if not db.execute("SELECT to_regclass('public.pr_feature_enrollments')").fetchone()[0]:
            db.execute((ROOT / "migrations/postriff/103_feature_enrollments.sql").read_text())
        one = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
        two = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0])
        db.execute("DELETE FROM public.pr_feature_enrollments")
    store = TrendStore(connect)
    first = manager(VALUES)

    # 1. Not admitted, self-serve open: owner is asked to enroll; nothing is readable.
    state = readiness_for(one)
    assert (state["state"], state["reasonCodes"], state["nextStep"]) == (
        "setup_required", ["enrollment_required"], {"kind": "consent", "href": "/app/trends#enroll"}), state
    assert readiness_for(one, role="editor")["nextStep"] == {"kind": "contact_owner"}

    # 2. Enrolled without any reviewed shared policy: admitted, no grant, honest rights state.
    refused("self_serve_paused", lambda: manager({**VALUES, "RAFII_TREND_SELF_SERVE_ENABLED": "0"}).enroll(
        one, "user:" + ONE, {"accept": True}))
    joined = first.enroll(one, "user:" + ONE, {"accept": True})["data"]
    assert (joined["status"], joined["entitlement"], joined["admission"]) == ("active", "source_rights_pending", "self_serve"), joined
    with connect() as db:
        assert db.execute("SELECT count(*) FROM public.pr_trend_entitlements").fetchone()[0] == 0
    state = readiness_for(one)
    assert (state["state"], state["reasonCodes"], state["canRead"]) == ("unsupported", ["source_rights_pending"], False), state

    # 3. A shared policy that does not allow cross-workspace use never grants.
    shared_policy(store, DENIED, share="deny")
    refusing = manager({**VALUES, "RAFII_TREND_SHARED_CORPUS_SCOPE": DENIED})
    assert refusing.enroll(one, "user:" + ONE, {"accept": True})["data"]["entitlement"] == "source_rights_pending"
    with connect() as db:
        assert db.execute("SELECT count(*) FROM public.pr_trend_entitlements").fetchone()[0] == 0

    # 4. A reviewed policy allowing share_across_workspaces for that audience: bounded grant.
    policy_end = shared_policy(store, SHARED, days=20)
    granted = first.enroll(one, "user:" + ONE, {"accept": True})["data"]
    assert (granted["replayed"], granted["entitlement"], granted["shared_corpus"]) == (True, "granted", "granted"), granted
    with connect() as db:
        ops, expires, revoked = db.execute("""SELECT operations,expires_at,revoked_at FROM public.pr_trend_entitlements
            WHERE workspace_id=%s AND scope_key=%s""", (one, SHARED)).fetchone()
        assert sorted(ops) == ["derive_metrics", "retrieve"] and revoked is None, (ops, revoked)
        assert expires <= contracts.instant(policy_end), (expires, policy_end)
        assert expires - datetime.now(timezone.utc) <= timedelta(days=30, minutes=1)
    assert SHARED in store.authorized_scopes(one, ONE)
    state = readiness_for(one)
    assert (state["state"], state["reasonCodes"], state["canRead"]) == ("insufficient_data", ["no_projections_yet"], True), state
    signed = store.scope_signature(one, ONE)

    # 5. Isolation: the other workspace sees none of this, and only its own eligibility.
    assert SHARED not in store.authorized_scopes(two, TWO)
    second = manager(VALUES)
    view = second.get(two, "user:" + TWO)["data"]
    assert (view["status"], view["eligible"], view["reason"], view["shared_corpus"]) == (
        "not_enrolled", False, "cohort_full", "source_rights_pending"), view
    assert "1" not in json.dumps({k: v for k, v in view.items() if k != "feature"}), "no cohort counts"
    refused("cohort_full", lambda: second.enroll(two, "user:" + TWO, {"accept": True}))
    state = readiness_for(two)
    assert (state["state"], state["reasonCodes"]) == ("not_entitled", ["cohort_full"]), state
    try:
        second.get(one, "user:" + TWO)
    except AlphaError as error:
        assert error.status == 404, error.status
    else:
        raise AssertionError("foreign workspace enrollment was readable")

    # 6. Leaving revokes the entitlement and changes the scope signature (old cursors fail).
    left = first.leave(one, "user:" + ONE)["data"]
    assert (left["status"], left["replayed"], left["shared_corpus"]) == ("revoked", False, "source_rights_pending"), left
    assert SHARED not in store.authorized_scopes(one, ONE)
    assert store.scope_signature(one, ONE) != signed, "revocation must invalidate cursors signed under the old access"
    with connect() as db:
        assert db.execute("SELECT revoked_at IS NOT NULL FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s",
                          (one, SHARED)).fetchone()[0]
        assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind IN ('feature.enrolled','feature.unenrolled')",
                          (one,)).fetchone()[0] == 2
    assert first.leave(one, "user:" + ONE)["data"]["replayed"] is True
    state = readiness_for(one)
    assert state["state"] == "setup_required", state

    # 7. Enrollment never created ingestion, policies for the workspace, budgets or jobs.
    with connect() as db:
        assert db.execute("SELECT count(*) FROM public.pr_trend_jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM public.pr_trend_budget_limits").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM public.pr_trend_source_policies WHERE scope_key LIKE 'workspace:%'").fetchone()[0] == 0
    print("postgres_trend_enrollment: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
