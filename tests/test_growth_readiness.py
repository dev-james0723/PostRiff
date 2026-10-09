"""Growth Studio readiness (CONTRACTS.md §1): one honest state per tab, no provider or model call, no write."""
import copy
import re
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2 import feature_readiness as fr
from postriff_phase2.growth import readiness as R
from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE
from postriff_phase2.growth.service import ROUTES, GrowthService
from postriff_phase2.permissions import Membership

WID = "267f7d90-b11c-470c-9880-733ea7c1d483"
OTHER = "e1586423-0000-4000-8000-000000000002"
ENV = {"POSTRIFF_GROWTH": "1", "POSTRIFF_POSTMORTEM": "1", "POSTRIFF_AUDIENCE_MINER": "1", "POSTRIFF_GENOME": "1",
       "POSTRIFF_GROWTH_DAILY_USD_CAP": "5", "POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP": "1",
       "POSTRIFF_METRIC_READS": "1", "POSTRIFF_METRIC_WORKSPACE_ALLOWLIST": WID}


def facts(**changes):
    base = {"flags": {"growth": True, "postmortem": True, "audience": True, "genome": True}, "tables": set(R.ALL_TABLES),
            "role": "owner", "canEdit": True, "canManageConnections": True, "connections": 1, "analyticsDirect": 1,
            "commentsDirect": 1, "measurement": {"on": True, "admitted": True, "legacy": True, "enrolled": False, "eligibility": None},
            "verifiedPublications": 2, "historyPosts": 0, "ownedCommentPosts": 2, "eligibleComments": 4,
            "consent": {"summary": True, "audience": True}, "capsConfigured": True, "dailyUsed": {}, "largestCohort": 60,
            "lastReadAt": datetime(2026, 10, 4, 22, 57, 20, tzinfo=timezone.utc)}
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


class Compute(unittest.TestCase):
    def test_every_section_is_a_valid_contract_payload_and_ready_when_everything_holds(self):
        result = R.compute(facts())
        self.assertEqual(set(result), set(R.SECTIONS))
        for name, payload in result.items():
            with self.subTest(section=name):
                self.assertEqual(fr.validate(payload), payload)
                self.assertEqual((payload["state"], payload["canRead"], payload["canRun"]), ("ready", True, True))
        self.assertEqual(result["results"]["lastSuccessfulReadAt"], "2026-10-04T22:57:20Z")
        self.assertIsNone(result["audience"]["lastSuccessfulReadAt"])

    def test_flags_off_disable_reading_and_running(self):
        result = R.compute(facts(flags={"growth": False}))
        for name in ("studio", "results", "audience", "patterns"):
            with self.subTest(section=name):
                self.assertEqual((result[name]["state"], result[name]["reasonCodes"], result[name]["canRead"]),
                                 ("feature_disabled", ["growth_off"], False))
        result = R.compute(facts(flags={"postmortem": False, "audience": True}))
        self.assertEqual((result["results"]["state"], result["results"]["reasonCodes"]), ("feature_disabled", ["postmortem_off"]))
        self.assertEqual(result["audience"]["state"], "ready")
        self.assertEqual(result["studio"]["state"], "ready")
        self.assertEqual(R.compute(facts(flags={"audience": False}))["audience"]["reasonCodes"], ["audience_off"])

    def test_missing_037_038_schema_is_a_temporary_outage_that_never_asks_to_reconnect(self):
        result = R.compute(facts(tables=set(R.MEASUREMENT_TABLES)))
        for name in ("studio", "results", "audience", "patterns"):
            with self.subTest(section=name):
                payload = result[name]
                self.assertEqual((payload["state"], payload["reasonCodes"], payload["canRead"], payload["canRun"]),
                                 ("temporarily_unavailable", ["growth_schema_unavailable"], False, False))
                self.assertEqual(payload["nextStep"], {"kind": "wait"})
        self.assertEqual(result["measurement"]["state"], "ready")

    def test_no_connection_sends_managers_to_channels_and_others_to_the_owner(self):
        result = R.compute(facts(connections=0, analyticsDirect=0, commentsDirect=0))
        for name in ("results", "audience", "measurement"):
            with self.subTest(section=name):
                self.assertEqual(result[name]["state"], "setup_required")
                self.assertIn("analytics_connection_required", result[name]["reasonCodes"])
                self.assertEqual(result[name]["nextStep"], {"kind": "connect", "href": "/app/channels"})
        viewer = R.compute(facts(connections=0, analyticsDirect=0, role="viewer", canEdit=False, canManageConnections=False))
        self.assertEqual(viewer["results"]["nextStep"], {"kind": "contact_owner"})

    def test_missing_direct_analytics_or_comment_reading_names_the_permission(self):
        result = R.compute(facts(analyticsDirect=0))
        self.assertEqual(result["results"]["reasonCodes"][0], "analytics_permission_required")
        self.assertEqual(result["measurement"]["state"], "setup_required")
        self.assertEqual(R.compute(facts(commentsDirect=0))["audience"]["reasonCodes"][0], "comments_permission_required")

    def test_measurement_admission_states(self):
        enroll = R.compute(facts(measurement={"admitted": False, "legacy": False, "eligibility": {"eligible": True, "reason": "enrollment_open"}}))
        self.assertEqual((enroll["measurement"]["state"], enroll["measurement"]["reasonCodes"]),
                         ("setup_required", ["measurement_enrollment_required"]))
        self.assertEqual(enroll["measurement"]["nextStep"], {"kind": "consent", "href": "/app/growth?view=results"})
        editor = R.compute(facts(role="editor", measurement={"admitted": False, "legacy": False,
                                                             "eligibility": {"eligible": True, "reason": "enrollment_open"}}))
        self.assertEqual(editor["measurement"]["nextStep"], {"kind": "contact_owner"})
        paused = R.compute(facts(measurement={"admitted": False, "legacy": False, "eligibility": {"eligible": False, "reason": "self_serve_paused"}}))
        self.assertEqual((paused["measurement"]["state"], paused["measurement"]["reasonCodes"]), ("not_entitled", ["measurement_paused"]))
        # Results stays readable: earlier readings are still shown, collection is what is paused.
        self.assertEqual((paused["results"]["state"], paused["results"]["canRead"]), ("not_entitled", True))
        off = R.compute(facts(measurement={"on": False, "admitted": False, "eligibility": None}))
        self.assertEqual((off["measurement"]["state"], off["measurement"]["reasonCodes"]), ("feature_disabled", ["measurement_off"]))
        self.assertEqual(off["results"]["state"], "ready")

    def test_no_publications_and_no_history_is_insufficient_data_but_readable(self):
        result = R.compute(facts(verifiedPublications=0, historyPosts=0))
        self.assertEqual((result["results"]["state"], result["results"]["reasonCodes"], result["results"]["canRead"]),
                         ("insufficient_data", ["no_verified_publications"], True))
        self.assertEqual((result["measurement"]["state"], result["measurement"]["canRun"]), ("insufficient_data", True))
        with_history = R.compute(facts(verifiedPublications=0, historyPosts=1))
        self.assertEqual(with_history["results"]["state"], "ready")

    def test_consent_is_an_owner_step_and_others_are_sent_to_the_owner(self):
        owner = R.compute(facts(consent={"summary": False, "audience": False}))
        for name in ("results", "audience"):
            with self.subTest(section=name):
                self.assertEqual((owner[name]["state"], owner[name]["canRead"], owner[name]["canRun"]), ("setup_required", True, False))
                self.assertIn("growth_consent_required", owner[name]["reasonCodes"])
                self.assertEqual(owner[name]["nextStep"]["kind"], "consent")
        for role in ("admin", "editor", "approver", "viewer"):
            with self.subTest(role=role):
                other = R.compute(facts(role=role, canEdit=role in ("admin", "editor"), consent={"summary": False, "audience": False}))
                self.assertEqual(other["results"]["nextStep"], {"kind": "contact_owner"})

    def test_viewer_reads_but_never_runs(self):
        result = R.compute(facts(role="viewer", canEdit=False, canManageConnections=False))
        for name in ("results", "audience"):
            with self.subTest(section=name):
                self.assertEqual((result[name]["canRead"], result[name]["canRun"]), (True, False))
                self.assertIn("role_edit_required", result[name]["reasonCodes"])
        self.assertFalse(result["patterns"]["canRun"])
        self.assertEqual(result["patterns"]["state"], "ready")
        self.assertFalse(R.compute(facts(role="editor"))["patterns"]["canRun"])

    def test_unset_caps_and_used_allowance_keep_reading_and_stop_paid_runs(self):
        result = R.compute(facts(capsConfigured=False))
        for name in ("results", "audience"):
            with self.subTest(section=name):
                payload = result[name]
                self.assertEqual((payload["state"], payload["reasonCodes"], payload["canRead"], payload["canRun"]),
                                 ("temporarily_unavailable", ["growth_budget_unconfigured"], True, False))
                self.assertEqual(payload["nextStep"], {"kind": "wait"})
        used = R.compute(facts(dailyUsed={"audience": True}))
        self.assertEqual(used["audience"]["reasonCodes"], ["growth_daily_limit"])
        self.assertEqual(used["results"]["state"], "ready")

    def test_audience_needs_owned_posts_and_comments(self):
        self.assertEqual(R.compute(facts(ownedCommentPosts=0, eligibleComments=0))["audience"]["reasonCodes"], ["no_verified_publications"])
        no_comments = R.compute(facts(eligibleComments=0))["audience"]
        self.assertEqual((no_comments["state"], no_comments["reasonCodes"], no_comments["canRead"]), ("insufficient_data", ["no_comments"], True))

    def test_patterns_need_fifty_comparable_posts(self):
        result = R.compute(facts(largestCohort=49))["patterns"]
        self.assertEqual((result["state"], result["reasonCodes"], result["canRead"]), ("insufficient_data", ["sample_below_minimum"], True))
        self.assertEqual(R.compute(facts(largestCohort=50))["patterns"]["state"], "ready")
        self.assertEqual(R.MINIMUM_POSTS, 50)


class Cursor:
    """Answers the readiness and overview queries from a small in-memory model; records every statement."""

    def __init__(self, world):
        self.world = world
        self.sql = []
        self._rows = []

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.sql.append((text, params))
        if re.search(r"^\s*(INSERT|UPDATE|DELETE)\b", text, re.I):
            raise AssertionError("readiness must never write: " + text[:80])
        w = self.world
        if "unnest(%s::text[]) AS name" in text:
            self._rows = [(name,) for name in params[0] if name in w["tables"]]
        elif "to_regclass('public.pr_feature_enrollments')" in text:
            self._rows = [(False,)]
        elif "FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability IN" in text:
            self._rows = [(c, cap) for (ws, c, cap) in w["capabilities"] if ws == params[0]]
        elif "FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability='comments_read'" in text:
            self._rows = [(c,) for (ws, c, cap) in w["capabilities"] if ws == params[0] and cap == "comments_read"]
        elif "FROM public.pr_owned_posts p WHERE p.workspace_id=%s AND p.source='history_import'" in text:
            self._rows = [(w["history"].get(params[0], 0),)]
        elif "FROM public.pr_owned_posts" in text:
            self._rows = []
        elif "FROM public.pr_growth_budgets" in text:
            self._rows = []
        elif "FROM public.pr_audience_threads" in text:
            self._rows = []
        elif "count(*) FROM public.pr_predictions" in text:
            self._rows = [(0,)]
        elif "max(observed_at) FROM public.pr_metric_observations" in text:
            self._rows = [(w["lastRead"].get(params[0]),)]
        else:
            raise AssertionError("unexpected statement: " + text[:120])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class Repository:
    def __init__(self, world, role="owner"):
        self.world, self.role, self.effects, self.cursors = world, role, [], []

    @contextmanager
    def transaction(self, token, workspace_id, **_):
        cur = Cursor(self.world)
        self.cursors.append(cur)
        yield cur, (1, copy.deepcopy(self.world["state"]), self.role, False, False, False, False), "actor"


class NoNetwork:
    def __getattr__(self, name):
        raise AssertionError("readiness must not touch " + name)


def service(world, role="owner", env=ENV, mounted=True):
    hosted = SimpleNamespace(repository=Repository(world, role), clock=lambda: 1_760_000_000.0,
                             ideas=SimpleNamespace(resolve_writer=lambda state, requested: (None, "fixture/writer", None)),
                             oauth=NoNetwork(), connection_factory=NoNetwork())
    if mounted:
        hosted.metric_reads = SimpleNamespace(workspace_allowed=lambda wid, cur=None: wid == WID)
    def router(*_):
        raise AssertionError("readiness must not build a model router")
    return GrowthService(hosted, env=dict(env), router_factory=router, clock=hosted.clock)


def world(**changes):
    state = {"phase2": {"channels": [{"id": "ig", "platform": "Instagram", "revoked": False}], "jobs": []},
             "growthConsent": {"routes": [*ROUTES, SUMMARY_ROUTE], "audience": True}}
    base = {"tables": set(R.ALL_TABLES), "state": state,
            "capabilities": [(WID, "ig", "analytics"), (WID, "ig", "comments_read"), (OTHER, "ig", "analytics")],
            "history": {WID: 1, OTHER: 7},
            "lastRead": {WID: datetime(2026, 10, 4, 22, 57, 20, tzinfo=timezone.utc), OTHER: datetime(2026, 10, 8, tzinfo=timezone.utc)}}
    base.update(changes)
    return base


class Catalog(unittest.TestCase):
    def test_catalog_keeps_existing_keys_and_adds_readiness_without_calls_or_writes(self):
        w = world()
        growth = service(w)
        result = growth.catalog(WID, "session")
        for key in ("radar", "postDoctorV2", "postDoctor", "genome", "postmortem", "audienceMiner", "summaryRoute",
                    "audienceConsent", "consented", "routes", "allowedRoutes", "writer", "writerRoute",
                    "maxHistoryPosts", "checksPerDay", "rewritesPerDay"):
            self.assertIn(key, result)
        self.assertEqual(set(result["readiness"]), set(R.SECTIONS))
        for payload in result["readiness"].values():
            fr.validate(payload)
        # The founder's real shape: one Instagram account with Direct analytics, one imported post, no publications.
        self.assertEqual(result["readiness"]["results"]["state"], "ready")
        self.assertEqual(result["readiness"]["measurement"]["state"], "ready")
        self.assertEqual(result["readiness"]["results"]["lastSuccessfulReadAt"], "2026-10-04T22:57:20Z")
        self.assertEqual(result["readiness"]["audience"]["reasonCodes"], ["no_verified_publications"])
        statements = [sql for cur in growth.repository.cursors for sql, _ in cur.sql]
        self.assertTrue(all(not re.match(r"(INSERT|UPDATE|DELETE)", s) for s in statements))

    def test_last_read_and_history_come_only_from_this_workspace(self):
        w = world(history={OTHER: 7}, lastRead={OTHER: datetime(2026, 10, 8, tzinfo=timezone.utc)})
        result = service(w).catalog(WID, "session")["readiness"]
        self.assertIsNone(result["results"]["lastSuccessfulReadAt"])
        self.assertEqual(result["results"]["reasonCodes"], ["no_verified_publications"])

    def test_missing_schema_is_reported_not_raised(self):
        w = world(tables=set(R.MEASUREMENT_TABLES))
        result = service(w).catalog(WID, "session")["readiness"]
        self.assertEqual((result["results"]["state"], result["results"]["reasonCodes"]),
                         ("temporarily_unavailable", ["growth_schema_unavailable"]))
        self.assertEqual(result["studio"]["reasonCodes"], ["growth_schema_unavailable"])

    def test_flags_absent_in_production_shape(self):
        env = {"POSTRIFF_METRIC_READS": "1", "POSTRIFF_METRIC_WORKSPACE_ALLOWLIST": WID}
        result = service(world(tables=set(R.MEASUREMENT_TABLES)), env=env).catalog(WID, "session")
        self.assertFalse(result["postmortem"] or result["audienceMiner"])
        self.assertEqual(result["readiness"]["studio"]["reasonCodes"], ["growth_off"])
        self.assertEqual(result["readiness"]["measurement"]["state"], "ready")

    def test_unset_caps_block_paid_runs_only(self):
        env = {k: v for k, v in ENV.items() if "USD_CAP" not in k}
        result = service(world(), env=env).catalog(WID, "session")["readiness"]
        self.assertEqual(result["results"]["reasonCodes"], ["growth_budget_unconfigured"])
        self.assertFalse(result["results"]["canRun"])
        self.assertTrue(result["results"]["canRead"])

    def test_viewer_and_editor_never_get_an_owner_control(self):
        w = world()
        w["state"]["growthConsent"] = {}
        for role in ("viewer", "editor"):
            with self.subTest(role=role):
                result = service(w, role=role).catalog(WID, "session")["readiness"]
                for name in ("results", "audience"):
                    self.assertEqual(result[name]["nextStep"], {"kind": "contact_owner"})
                    self.assertFalse(result[name]["canRun"])

    def test_api_tokens_are_refused(self):
        with self.assertRaises(AlphaError):
            service(world()).catalog(WID, "prt_token")


class SchemaSafety(unittest.TestCase):
    def test_overview_and_audience_return_a_structured_503_before_any_growth_table_is_read(self):
        w = world(tables=set(R.MEASUREMENT_TABLES))
        growth = service(w)
        for call in (lambda: growth.closed_loop.overview(WID, "session"), lambda: growth.closed_loop.audience(WID, "session"),
                     lambda: growth.genome(WID, "session")):
            with self.assertRaises(AlphaError) as caught:
                call()
            self.assertEqual((caught.exception.status, caught.exception.code), (503, "growth_schema_unavailable"))
        statements = [sql for cur in growth.repository.cursors for sql, _ in cur.sql]
        self.assertFalse(any("pr_postmortems" in s or "pr_predictions" in s or "pr_genome_versions" in s for s in statements))

    def test_require_schema_lists_only_present_tables(self):
        cur = Cursor(world(tables={"pr_postmortems"}))
        with self.assertRaises(AlphaError) as caught:
            R.require_schema(cur, ("pr_postmortems", "pr_predictions"))
        self.assertEqual(caught.exception.code, "growth_schema_unavailable")
        R.require_schema(cur, ("pr_postmortems",))



class EnrollmentCursor:
    """Just enough of pr_feature_enrollments / pr_metric_reads for the owner enrollment routes."""

    def __init__(self, store):
        self.store, self.rows, self.rowcount = store, [], 0

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        st = self.store
        st["sql"].append(text)
        self.rowcount = 0
        if "to_regclass('public.pr_feature_enrollments')" in text:
            self.rows = [(True,)]
        elif text.startswith("SELECT status FROM public.pr_feature_enrollments"):
            self.rows = [(st["status"],)] if st["status"] else []
        elif "pg_advisory_xact_lock" in text:
            self.rows = [(None,)]
        elif text.startswith("SELECT count(*) FROM public.pr_feature_enrollments"):
            self.rows = [(st["cohort"],)]
        elif text.startswith("INSERT INTO public.pr_feature_enrollments"):
            st["status"] = "active"
            self.rows, self.rowcount = [], 1
        elif text.startswith("UPDATE public.pr_feature_enrollments"):
            self.rowcount = 1 if st["status"] == "active" else 0
            st["status"] = "revoked" if st["status"] else None
        elif text.startswith("INSERT INTO public.pr_audit_events"):
            st["audit"].append(params[2])
        elif text.startswith("UPDATE public.pr_metric_reads"):
            st["closed"] += st["open_reads"]
            self.rowcount, st["open_reads"] = st["open_reads"], 0
        else:
            raise AssertionError("unexpected statement: " + text[:100])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class EnrollmentRepository:
    def __init__(self, store, role):
        self.store, self.role, self.effects = store, role, []

    @contextmanager
    def transaction(self, token, workspace_id, **_):
        yield EnrollmentCursor(self.store), (1, {}, self.role, False, False, False, False), "3f10b38f-0000-4000-8000-000000000009"


class MeasurementEnrollment(unittest.TestCase):
    SELF_SERVE = {"POSTRIFF_METRIC_READS": "1", "POSTRIFF_METRIC_SELF_SERVE_ENABLED": "1", "POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES": "3"}

    def growth(self, role="owner", env=None, **store):
        state = {"status": None, "cohort": 0, "sql": [], "audit": [], "open_reads": 2, "closed": 0, **store}
        hosted = SimpleNamespace(repository=EnrollmentRepository(state, role), clock=lambda: 1.0, metric_reads=object(),
                                 ideas=NoNetwork(), oauth=NoNetwork(), connection_factory=NoNetwork())
        return GrowthService(hosted, env=dict(self.SELF_SERVE if env is None else env)), state

    def test_owner_enrolls_and_leaves_with_only_own_status_returned(self):
        growth, store = self.growth()
        view = growth.measurement_enrollment(OTHER, "session", "GET")
        self.assertEqual(view, {"feature": "growth_measurement", "status": "none", "eligible": True, "reason": "enrollment_open",
                                "admitted": False, "collecting": True})
        with self.assertRaises(AlphaError):
            growth.measurement_enrollment(OTHER, "session", "POST", {})
        joined = growth.measurement_enrollment(OTHER, "session", "POST", {"confirmed": True})
        self.assertEqual((joined["status"], joined["admitted"], joined["reason"]), ("active", True, "already_enrolled"))
        self.assertEqual(store["audit"], ["feature.enrolled"])
        left = growth.measurement_enrollment(OTHER, "session", "DELETE")
        self.assertEqual((left["status"], left["admitted"]), ("revoked", False))
        self.assertEqual(store["closed"], 2)
        self.assertNotIn("cohort", json_keys(left))

    def test_leaving_keeps_reads_when_the_reviewed_env_list_still_admits_the_workspace(self):
        env = {**self.SELF_SERVE, "POSTRIFF_METRIC_WORKSPACE_ALLOWLIST": OTHER}
        growth, store = self.growth(env=env, status="active")
        left = growth.measurement_enrollment(OTHER, "session", "DELETE")
        self.assertEqual((left["status"], left["admitted"], left["reason"]), ("revoked", True, "reviewed_cohort"))
        self.assertEqual(store["closed"], 0)

    def test_only_an_interactive_owner_can_read_join_or_leave(self):
        for role in ("admin", "editor", "approver", "viewer"):
            growth, store = self.growth(role=role)
            for method, body in (("GET", None), ("POST", {"confirmed": True}), ("DELETE", None)):
                with self.subTest(role=role, method=method):
                    with self.assertRaises(AlphaError) as caught:
                        growth.measurement_enrollment(OTHER, "session", method, body)
                    self.assertEqual(caught.exception.status, 403)
            self.assertIsNone(store["status"])
            self.assertEqual(store["closed"], 0)
        growth, _ = self.growth()
        with self.assertRaises(AlphaError) as caught:
            growth.measurement_enrollment(OTHER, "prt_api_token", "POST", {"confirmed": True})
        self.assertEqual(caught.exception.status, 403)

    def test_paused_or_full_cohorts_refuse_without_writing(self):
        growth, store = self.growth(env={"POSTRIFF_METRIC_READS": "1"})
        self.assertEqual(growth.measurement_enrollment(OTHER, "session", "GET")["reason"], "self_serve_paused")
        with self.assertRaises(AlphaError) as caught:
            growth.measurement_enrollment(OTHER, "session", "POST", {"confirmed": True})
        self.assertEqual(caught.exception.code, "self_serve_paused")
        growth, store = self.growth(cohort=3)
        self.assertEqual(growth.measurement_enrollment(OTHER, "session", "GET")["reason"], "cohort_full")
        with self.assertRaises(AlphaError) as caught:
            growth.measurement_enrollment(OTHER, "session", "POST", {"confirmed": True})
        self.assertEqual(caught.exception.code, "cohort_full")
        self.assertIsNone(store["status"])

    def test_route_is_mounted_for_get_post_and_delete(self):
        from postriff_phase2.growth import http
        calls = []
        growth = SimpleNamespace(measurement_enrollment=lambda wid, token, method, body=None: calls.append((wid, method, body)) or {"ok": True})
        app = SimpleNamespace(_body=lambda environ: {"confirmed": True}, _json=lambda start, status, value: (status, value))
        hosted = SimpleNamespace(growth=growth)
        parts = ["api", "workspaces", OTHER, "growth", "measurement", "enrollment"]
        for method in ("GET", "POST", "DELETE"):
            self.assertEqual(http.handle(app, {}, None, hosted, "session", method, parts), (200, {"ok": True}))
        self.assertEqual(calls, [(OTHER, "GET", None), (OTHER, "POST", {"confirmed": True}), (OTHER, "DELETE", None)])
        with self.assertRaises(AlphaError):
            http.handle(app, {}, None, hosted, "session", "PUT", parts)


def json_keys(value):
    return set(value)

if __name__ == "__main__":
    unittest.main()
