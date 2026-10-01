"""Routes, flags, cron steps, catalogue and agent tools of the G4-LOOP slice (AC24, AC25, AC28): default-off flags
answer feature_disabled, API tokens never reach the routes, read tools are READ and never create paid work, the
brief notification is an opportunities-category digest event that never interrupts and never displaces operational
alerts."""
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2 import growth_v2_routes
from postriff_phase2.briefs import http as brief_http, jobs as brief_jobs
from postriff_phase2.coworker import attention, flags
from postriff_phase2.notifications import catalog, email_render, planner
from postriff_phase2.permissions import Membership
from postriff_phase2.proof import http as proof_http, jobs as proof_jobs

ON = {"RAFII_OPPORTUNITY_BRIEF_ENABLED": "1", "RAFII_PROOF_V2_ENABLED": "1"}


class App:
    def __init__(self, body=None):
        self.body, self.sent = body or {}, None

    def _json(self, start_response, status, value):
        self.sent = (status, value)
        return [b""]

    def _body(self, environ):
        return self.body


def call(module, method, rest, token="session", body=None, query="", hosted=None):
    app = App(body)
    module.handle(app, {"QUERY_STRING": query}, None, hosted or types.SimpleNamespace(), token, method, ["api", "workspaces", "w1", "x", *rest])
    return app.sent


class FlagAndRouteTest(unittest.TestCase):
    def test_flags_default_off_answer_feature_disabled(self):
        with mock.patch.object(flags, "_values", {}):
            for module in (brief_http, proof_http):
                with self.assertRaises(AlphaError) as caught:
                    call(module, "GET", ["current"])
                self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))
            self.assertEqual(brief_jobs.tick(object(), time.monotonic() + 5), {"status": "disabled"})
            self.assertEqual(proof_jobs.tick(object(), time.monotonic() + 5), {"status": "disabled"})

    def test_routes_are_registered_and_api_tokens_refused(self):
        self.assertEqual(growth_v2_routes.RESOURCES["briefs"], "postriff_phase2.briefs.http")
        self.assertEqual(growth_v2_routes.RESOURCES["proof"], "postriff_phase2.proof.http")
        self.assertIn("postriff_phase2.briefs.jobs", growth_v2_routes.CRON)
        self.assertIn("postriff_phase2.proof.jobs", growth_v2_routes.CRON)
        with mock.patch.object(flags, "_values", ON):
            for module in (brief_http, proof_http):
                with self.assertRaises(AlphaError) as caught:
                    call(module, "GET", ["current"], token="prt_123")
                self.assertEqual(caught.exception.status, 403)

    def test_brief_routes_dispatch_to_the_service(self):
        service = mock.Mock()
        service.current.return_value = {"edition": "c"}
        service.history.return_value = {"editions": []}
        service.edition.return_value = {"edition": "e"}
        service.action.return_value = {"action": "a"}
        hosted = types.SimpleNamespace(briefs=service)
        with mock.patch.object(flags, "_values", ON):
            self.assertEqual(call(brief_http, "GET", ["current"], hosted=hosted), (200, {"edition": "c"}))
            call(brief_http, "GET", ["editions"], query="cursor=abc&limit=10", hosted=hosted)
            service.history.assert_called_once_with("w1", "session", "abc", "10")
            call(brief_http, "GET", ["editions", "e1"], hosted=hosted)
            service.edition.assert_called_once_with("w1", "session", "e1")
            call(brief_http, "POST", ["items", "bi_1", "action"], body={"action": "dismiss"}, hosted=hosted)
            service.action.assert_called_once_with("w1", "session", "bi_1", {"action": "dismiss"})
            with self.assertRaises(AlphaError) as caught:
                call(brief_http, "DELETE", ["current"], hosted=hosted)
            self.assertEqual(caught.exception.status, 404)

    def test_proof_routes_dispatch_to_the_service(self):
        service = mock.Mock()
        hosted = types.SimpleNamespace(proof=service)
        with mock.patch.object(flags, "_values", ON):
            call(proof_http, "GET", ["proofs"], query="frequency=weekly&limit=5", hosted=hosted)
            service.list.assert_called_once_with("w1", "session", "weekly", None, "5")
            call(proof_http, "GET", ["proofs", "gp_1"], hosted=hosted)
            service.get.assert_called_once_with("w1", "session", "gp_1")
            call(proof_http, "GET", ["proofs", "gp_1", "revisions", "2"], hosted=hosted)
            service.revision.assert_called_once_with("w1", "session", "gp_1", "2")
            call(proof_http, "POST", ["refresh"], body={"frequency": "monthly"}, hosted=hosted)
            service.refresh.assert_called_once_with("w1", "session", {"frequency": "monthly"})
            call(proof_http, "GET", ["strategy"], query="status=accepted", hosted=hosted)
            service.strategy.assert_called_once_with("w1", "session", "accepted", None, None)
            call(proof_http, "POST", ["strategy", "sd_1", "decide"], body={"action": "accept"}, hosted=hosted)
            service.decide.assert_called_once_with("w1", "session", "sd_1", {"action": "accept"})

    def test_cron_steps_delegate_when_on(self):
        hosted = types.SimpleNamespace(briefs=mock.Mock(), proof=mock.Mock())
        hosted.briefs.cron.return_value = {"status": "ok"}
        hosted.proof.cron.return_value = {"status": "ok"}
        with mock.patch.object(flags, "_values", ON):
            self.assertEqual(brief_jobs.tick(hosted, 9.0), {"status": "ok"})
            self.assertEqual(proof_jobs.tick(hosted, 9.0), {"status": "ok"})
        hosted.briefs.cron.assert_called_once_with(9.0, brief_jobs.MAX_RECIPIENTS)
        hosted.proof.cron.assert_called_once_with(9.0, proof_jobs.MAX_WORKSPACES)


class CatalogTest(unittest.TestCase):
    EVENT = "opportunity.brief_ready"

    def test_ac25_brief_event_is_actor_scoped_opportunities_digest(self):
        spec = catalog.spec(self.EVENT)
        self.assertEqual((spec["category"], spec["audience"], spec["severity"], spec["email"], spec["push"], spec["sms"]),
                         ("opportunities", "actor", "info", "digest", "off", "off"))
        self.assertNotIn(spec["severity"], catalog.BREAKS_QUIET_HOURS)
        self.assertIn(spec["template"], email_render.TEMPLATES)
        self.assertFalse(catalog.transactional(self.EVENT))
        self.assertEqual(catalog.CATALOG_VERSION, "2026-10-01.1")

    def _plan(self, prefs, now, zone="America/New_York", recent=None):
        event = {"event_type": self.EVENT, "workspace_id": "ws"}
        return {r["channel"]: r for r in planner.plan(event, {"userId": "u1", "time_zone": zone}, prefs, now, push_available=True, recent=recent)}

    def test_ac25_quiet_hours_dst_mute_unsubscribe_and_off(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        # 23:30 on the night before the fall-back change; quiet 22:00–07:00 → the wall-clock 07:00, 25 hours later in UTC terms + 0.5 h.
        now = datetime(2026, 10, 31, 23, 30, tzinfo=tz).timestamp()
        quiet = {("*", "*"): {"quiet_start": 22 * 60, "quiet_end": 7 * 60, "email_mode": "immediate"}}
        plan = self._plan(quiet, now)
        self.assertEqual(plan["in_app"]["status"], "delivered")
        self.assertEqual(plan["email"]["reason"], "quiet_hours")
        self.assertEqual(plan["email"]["next_attempt_at"], datetime(2026, 11, 1, 7, 0, tzinfo=tz).timestamp())
        self.assertNotIn("push", plan)                           # push is off for briefs
        self.assertEqual(self._plan({("*", "*"): {"muted_until": now + 3600}}, now)["email"]["reason"], "muted")
        self.assertEqual(self._plan({("*", "*"): {"email_unsubscribed": True}}, now)["email"]["reason"], "unsubscribed")
        self.assertEqual(self._plan({("ws", "opportunities"): {"digest_frequency": "off"}}, now)["email"]["status"], "suppressed")
        self.assertEqual(self._plan({("ws", "opportunities"): {"in_app": False}}, now)["in_app"]["status"], "suppressed")
        digest = self._plan({}, now)["email"]
        self.assertEqual((digest["mode"], digest["status"]), ("digest", "pending"))

    def test_ac25_operational_priority_is_never_displaced(self):
        members = [{"userId": "u1", "membership": Membership("owner"), "active": True}, {"userId": "u2", "membership": Membership("editor"), "active": True}]
        self.assertEqual([m["userId"] for m in planner.audience(members, {"event_type": self.EVENT}, "u2")], ["u2"])
        # Briefs never use the immediate lanes, so they never count toward the hourly rate limit that could downgrade an operational alert.
        failure = {r["channel"]: r for r in planner.plan({"event_type": "publish.failed", "workspace_id": "ws"}, {"userId": "u1"}, {}, 1.0e9,
                                                         push_available=True, recent={"email": 0, "push": 0})}
        self.assertEqual((failure["email"]["mode"], failure["push"]["status"]), ("immediate", "pending"))
        self.assertGreater(attention.PRIORITY.get(self.EVENT, 90), attention.PRIORITY["publish.failed"])
        self.assertNotIn(self.EVENT, attention.URGENT)


class AgentToolTest(unittest.TestCase):
    def setUp(self):
        from postriff_phase2.agent_runtime_v2 import tool_adapter
        self.registry = tool_adapter.REGISTRY
        from postriff_phase2.briefs import agent_tools as brief_tools
        from postriff_phase2.proof import agent_tools as proof_tools
        brief_tools.register()
        proof_tools.register()
        brief_tools.register()                                  # idempotent

    def test_ac28_tool_contracts(self):
        from postriff_phase2.agent_runtime_v2 import contracts
        expected = {"brief_read": (contracts.READ, "read"), "brief_action": (contracts.MUTATE_REVERSIBLE, "edit"),
                    "proof_read": (contracts.READ, "read"), "strategy_decide": (contracts.MUTATE_REVERSIBLE, "owner")}
        for name, (effect, permission) in expected.items():
            spec = self.registry[name].spec
            self.assertEqual((spec.effect, spec.permission, spec.voice, spec.approval), (effect, permission, True, False), name)

    def test_tools_answer_feature_disabled_when_off(self):
        ctx = types.SimpleNamespace(service=None, workspace_id="w", token="t", run_id="r", trace_id="t", ledger=types.SimpleNamespace(changed=[], reference=lambda *a: None))
        with mock.patch.object(flags, "_values", {}):
            for name in ("brief_read", "brief_action", "proof_read", "strategy_decide"):
                self.assertEqual(self.registry[name].executor(ctx, {"itemId": "bi_1", "action": "dismiss", "decisionId": "sd_1", "expectedRevision": 1})["code"], "feature_disabled")

    def test_ac28_read_tools_only_read_the_stored_composition(self):
        service = mock.Mock()
        service.current.return_value = {"dataMode": "stored", "dataState": "available", "coverage": [], "edition": {
            "id": None, "persisted": False, "editionKey": "2026-W41", "revision": None, "materialDigest": "0" * 64, "items": []}}
        hosted = types.SimpleNamespace(briefs=service)
        references = []
        ctx = types.SimpleNamespace(service=hosted, workspace_id="w", token="t", run_id="r", trace_id="t",
                                    ledger=types.SimpleNamespace(changed=[], reference=lambda *a: references.append(a)))
        with mock.patch.object(flags, "_values", ON):
            result = self.registry["brief_read"].executor(ctx, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["dataMode"], "stored")
        self.assertEqual([c[0] for c in service.method_calls], ["current"])     # nothing but the stored read
        self.assertEqual(ctx.ledger.changed, [])

    def test_brief_action_tool_derives_a_stable_idempotency_key(self):
        service = mock.Mock()
        service.action.return_value = {"action": {"itemId": "bi_1", "action": "dismiss"}, "outcome": None, "verified": True, "replayed": False}
        ctx = types.SimpleNamespace(service=types.SimpleNamespace(briefs=service), workspace_id="w", token="t", run_id="run-1", trace_id="t",
                                    ledger=types.SimpleNamespace(changed=[], reference=lambda *a: None))
        with mock.patch.object(flags, "_values", ON):
            self.registry["brief_action"].executor(ctx, {"itemId": "bi_1", "action": "dismiss", "reasonCode": "not_now", "materialDigest": "a" * 64})
            self.registry["brief_action"].executor(ctx, {"itemId": "bi_1", "action": "dismiss", "reasonCode": "not_now", "materialDigest": "a" * 64})
        first, second = (c.args[3]["idempotencyKey"] for c in service.action.call_args_list)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[A-Za-z0-9_-]{8,80}$")


if __name__ == "__main__":
    unittest.main()
