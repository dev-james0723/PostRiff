"""Trends self-serve enrollment HTTP/service rules (offline, in-memory SQL double).

The real SQL (RLS, cohort cap under concurrency, entitlement grant/revoke and
cursor invalidation) is exercised in tests/phase2/postgres_trend_enrollment.py.
"""
import copy
import io
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import http as coworker_http
from postriff_phase2.growth.trends import enrollment
from postriff_phase2.growth.trends.service import TrendService
from postriff_phase2.ideas import IdeasService

WID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
ACTOR = "00000000-0000-4000-8000-000000000003"
SHARED = "shared:rafii-trend-corpus"
NOW = datetime.now(timezone.utc)
ON = {"RAFII_TREND_" + k + "_ENABLED": "1" for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")}
OPEN = {**ON, "RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "2",
        "RAFII_TREND_SHARED_CORPUS_SCOPE": SHARED}


def grant(scope, *, deny=(), end=None):
    end = (end or NOW + timedelta(days=60)).isoformat().replace("+00:00", "Z")
    return {name: {"state": "deny" if name in deny else "allow", "policy_ref": "reviewed-shared.v1",
                   "audience_scope": scope, "expires_at": end}
            for name in ("retrieve", "derive_metrics", "share_across_workspaces", "display_excerpt")}


class Database:
    """Only the statements enrollment may issue. Anything else fails the test."""

    def __init__(self):
        self.enrollments = {}      # workspace -> status
        self.others_active = 0     # other workspaces' active enrollments (never revealed)
        self.policies = []         # (rights, policy_end, contract_end)
        self.entitlements = {}     # (workspace, scope) -> {"operations", "expires_at", "revoked_at"}
        self.audit = []
        self.statements = []


class Cursor:
    def __init__(self, db, workspace):
        self.db, self.workspace, self.result, self.rowcount = db, workspace, [], 0

    def execute(self, sql, args=()):
        q = " ".join(sql.split())
        db = self.db
        db.statements.append(q)
        self.result, self.rowcount = [], 0
        if q.startswith("SELECT to_regclass"):
            self.result = [(True,)]
        elif q.startswith("SELECT status FROM public.pr_feature_enrollments"):
            status = db.enrollments.get(args[0])
            self.result = [(status,)] if status else []
        elif q.startswith("SELECT count(*) FROM public.pr_feature_enrollments"):
            self.result = [(db.others_active + sum(1 for s in db.enrollments.values() if s == "active"),)]
        elif q.startswith("SELECT pg_advisory_xact_lock"):
            pass
        elif q.startswith("INSERT INTO public.pr_feature_enrollments"):
            db.enrollments[args[0]] = "active"
        elif q.startswith("UPDATE public.pr_feature_enrollments"):
            if db.enrollments.get(args[1]) == "active":
                db.enrollments[args[1]] = "revoked"
                self.rowcount = 1
        elif q.startswith("INSERT INTO public.pr_audit_events"):
            db.audit.append(args[2])
        elif "FROM public.pr_trend_source_policies p" in q:
            assert args[0] == SHARED
            self.result = [(r, p, c) for r, p, c in db.policies]
        elif q.startswith("INSERT INTO public.pr_trend_entitlements"):
            db.entitlements[(args[0], args[1])] = {"operations": list(args[2]), "expires_at": args[3], "revoked_at": None}
        elif q.startswith("UPDATE public.pr_trend_entitlements"):
            row = db.entitlements.get((args[0], args[1]))
            if row and row["revoked_at"] is None:
                row["revoked_at"] = "now"
                self.rowcount = 1
        elif q.startswith("SELECT EXISTS(SELECT 1 FROM public.pr_trend_entitlements"):
            row = db.entitlements.get((args[0], args[1]))
            self.result = [(bool(row and row["revoked_at"] is None and "retrieve" in row["operations"]),)]
        else:
            raise AssertionError("unexpected SQL: " + q[:120])

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class Repository:
    def __init__(self, db):
        self.db, self.role, self.effects = db, "owner", []
        self.connection_factory = lambda: (_ for _ in ()).throw(AssertionError("independent connection"))

    @contextmanager
    def transaction(self, token, wid):
        if token != "session":
            raise AlphaError("bad session", 401)
        if wid != WID:
            raise AlphaError("Workspace unavailable.", 403)
        snapshot = copy.deepcopy((self.db.enrollments, self.db.entitlements))
        try:
            yield Cursor(self.db, wid), (1, {}, self.role, False, False, False, False), ACTOR
        except Exception:
            self.db.enrollments, self.db.entitlements = snapshot
            raise


def make(values=None):
    db = Database()
    repo = Repository(db)
    hosted = SimpleNamespace(repository=repo, connection_factory=repo.connection_factory,
                             ideas=SimpleNamespace(_state=IdeasService._state, _member=IdeasService._member))
    coworker = SimpleNamespace(hosted=hosted, repository=repo, clock=lambda: NOW.timestamp(), values=dict(values or OPEN))
    return TrendService(coworker, cursor_secret=b"x" * 32), repo, db


class AppStub:
    @staticmethod
    def _json(start, status, value):
        start(str(status) + " Status", [("Content-Type", "application/json")])
        return [json.dumps(value).encode()]

    @staticmethod
    def _body(environ):
        return json.loads(environ["wsgi.input"].read() or b"{}")


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.db = make()

    def call(self, method, payload=None, token="session", wid=WID):
        try:
            return 200, self.svc.enrollment(wid, token, method, payload)
        except AlphaError as exc:
            return exc.status, {"code": exc.code}

    def test_any_member_reads_only_its_own_status(self):
        self.db.others_active = 1
        for role in ("owner", "editor", "viewer"):
            self.repo.role = role
            status, body = self.call("GET")
            self.assertEqual(status, 200)
            data = body["data"]
            self.assertEqual(set(data), {"feature", "status", "admission", "eligible", "reason", "can_manage", "shared_corpus"})
            self.assertEqual((data["status"], data["eligible"], data["reason"]), ("not_enrolled", True, "enrollment_open"))
            self.assertEqual(data["can_manage"], role == "owner")
            self.assertNotIn("1", json.dumps(data), "never a cohort count")

    def test_session_tenant_and_token_boundaries(self):
        self.assertEqual(self.call("GET", token="")[0], 401)
        self.assertEqual(self.call("GET", token="prt_api")[0], 403)
        self.assertEqual(self.call("GET", wid=OTHER)[0], 404)
        self.assertEqual(self.call("GET", token="bad")[0], 401)

    def test_owner_enrolls_with_explicit_accept_and_replays(self):
        self.assertEqual(self.call("POST", {})[0], 400)
        self.assertEqual(self.call("POST", {"accept": "yes"})[0], 400)
        status, body = self.call("POST", {"accept": True})
        self.assertEqual(status, 200)
        self.assertEqual((body["data"]["status"], body["data"]["replayed"], body["data"]["admission"]), ("active", False, "self_serve"))
        self.assertEqual(self.db.audit, ["feature.enrolled"])
        again = self.call("POST", {"accept": True})[1]
        self.assertTrue(again["data"]["replayed"])
        self.assertEqual(self.db.audit, ["feature.enrolled"], "replay writes nothing new")

    def test_non_owner_flags_and_cohort_refusals_are_explicit(self):
        for role in ("admin", "editor", "viewer"):
            self.repo.role = role
            self.assertEqual(self.call("POST", {"accept": True}), (403, {"code": "owner_required"}))
            self.assertEqual(self.call("DELETE"), (403, {"code": "owner_required"}))
        self.repo.role = "owner"
        self.db.others_active = 2
        self.assertEqual(self.call("POST", {"accept": True}), (409, {"code": "cohort_full"}))
        svc, _, _ = make({**ON})
        with self.assertRaises(AlphaError) as raised:
            svc.enrollment(WID, "session", "POST", {"accept": True})
        self.assertEqual((raised.exception.status, raised.exception.code), (409, "self_serve_paused"))
        svc, _, _ = make({"RAFII_TREND_INTELLIGENCE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_ENABLED": "1",
                          "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "2"})
        with self.assertRaises(AlphaError) as raised:
            svc.enrollment(WID, "session", "POST", {"accept": True})
        self.assertEqual(raised.exception.status, 403, "Trends switched off: nothing to join")
        self.assertEqual(self.db.enrollments, {})

    def test_no_entitlement_without_a_reviewed_cross_workspace_policy(self):
        body = self.call("POST", {"accept": True})[1]["data"]
        self.assertEqual((body["entitlement"], body["shared_corpus"]), ("source_rights_pending", "source_rights_pending"))
        self.assertEqual(self.db.entitlements, {})
        # A policy whose rights deny cross-workspace sharing for that audience grants nothing.
        self.db.enrollments.clear()
        self.db.policies = [(grant(SHARED, deny=("share_across_workspaces",)), NOW + timedelta(days=60), NOW + timedelta(days=60))]
        self.assertEqual(self.call("POST", {"accept": True})[1]["data"]["entitlement"], "source_rights_pending")
        # Rights granted to a different audience do not count either.
        self.db.policies = [(grant("workspace:" + OTHER), NOW + timedelta(days=60), NOW + timedelta(days=60))]
        self.assertEqual(self.call("POST", {"accept": True})[1]["data"]["entitlement"], "source_rights_pending")
        self.assertEqual(self.db.entitlements, {})
        # No configured shared scope: never a grant, whatever policies exist.
        svc, _, db = make({k: v for k, v in OPEN.items() if k != "RAFII_TREND_SHARED_CORPUS_SCOPE"})
        db.policies = [(grant(SHARED), NOW + timedelta(days=60), NOW + timedelta(days=60))]
        self.assertEqual(svc.enrollment(WID, "session", "POST", {"accept": True})["data"]["entitlement"], "source_rights_pending")
        self.assertEqual(db.entitlements, {})

    def test_reviewed_shared_policy_grants_bounded_retrieve_and_derive_only(self):
        policy_end = NOW + timedelta(days=10)
        self.db.policies = [(grant(SHARED), policy_end, NOW + timedelta(days=90))]
        with patch("postriff_phase2.growth.trends.store.TrendStore.grant_entitlement", autospec=True,
                   side_effect=lambda store, wid, scope, ops, expires, cursor: cursor.execute(
                       "INSERT INTO public.pr_trend_entitlements(workspace_id,scope_key,operations,expires_at) VALUES(%s,%s,%s,%s)",
                       (wid, scope, ops, expires))) as granted:
            body = self.call("POST", {"accept": True})[1]["data"]
        self.assertEqual((body["entitlement"], body["shared_corpus"]), ("granted", "granted"))
        wid, scope, ops, expires = granted.call_args.args[1:5]
        self.assertEqual((wid, scope, ops), (WID, SHARED, ["retrieve", "derive_metrics"]))
        self.assertLessEqual(datetime.fromisoformat(expires.replace("Z", "+00:00")), policy_end)
        self.db.policies = [(grant(SHARED), NOW + timedelta(days=365), NOW + timedelta(days=365))]
        self.db.enrollments.clear()
        with patch("postriff_phase2.growth.trends.store.TrendStore.grant_entitlement", autospec=True) as granted:
            self.call("POST", {"accept": True})
        expires = datetime.fromisoformat(granted.call_args.args[4].replace("Z", "+00:00"))
        self.assertLessEqual(expires - NOW, timedelta(days=30, minutes=1), "grants are short-lived and renewed by policy")

    def test_leave_revokes_enrollment_and_its_entitlement_only_once(self):
        self.db.enrollments[WID] = "active"
        self.db.entitlements[(WID, SHARED)] = {"operations": ["retrieve", "derive_metrics"], "expires_at": "x", "revoked_at": None}
        status, body = self.call("DELETE")
        self.assertEqual((status, body["data"]["status"], body["data"]["replayed"]), (200, "revoked", False))
        self.assertEqual(self.db.entitlements[(WID, SHARED)]["revoked_at"], "now")
        self.assertEqual(body["data"]["shared_corpus"], "source_rights_pending")
        statements = len(self.db.statements)
        replay = self.call("DELETE")[1]["data"]
        self.assertTrue(replay["replayed"])
        self.assertFalse(any(s.startswith("UPDATE public.pr_trend_entitlements") for s in self.db.statements[statements:]))

    def test_allowlisted_workspace_reports_reviewed_cohort_without_enrolling(self):
        svc, _, db = make({**OPEN, "RAFII_TREND_WORKSPACE_ALLOWLIST": WID})
        data = svc.enrollment(WID, "session", "GET")["data"]
        self.assertEqual((data["admission"], data["status"]), ("reviewed_cohort", "not_enrolled"))
        self.assertEqual(db.enrollments, {})


class EnrollmentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.db = make()
        self.hosted = SimpleNamespace(coworker=SimpleNamespace(trends=self.svc), notifications=SimpleNamespace())

    def request(self, method, payload=None, query=""):
        seen = []
        env = {"QUERY_STRING": query, "wsgi.input": io.BytesIO(json.dumps(payload).encode() if payload is not None else b"")}
        with patch("postriff_phase2.coworker.runtime.ensure", lambda service: service):
            raw = coworker_http.handle(AppStub(), env, lambda s, h: seen.append((s, h)), self.hosted, "session", method,
                                       ["api", "workspaces", WID, "coworker", "trends", "enrollment"])
        headers = dict(seen[0][1])
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        return int(seen[0][0].split()[0]), json.loads(b"".join(raw))

    def test_static_route_before_trend_ids_and_safe_codes(self):
        self.assertEqual(self.request("GET")[0], 200)
        self.assertEqual(self.request("GET", query="x=1")[0], 400)
        self.assertEqual(self.request("PATCH", {})[0], 404)
        self.assertEqual(self.request("POST", {"accept": True})[1]["data"]["status"], "active")
        self.repo.role = "viewer"
        status, body = self.request("DELETE")
        self.assertEqual((status, body["code"]), (403, "owner_required"))


if __name__ == "__main__":
    unittest.main()
