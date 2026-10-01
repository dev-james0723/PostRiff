"""Signature Series routes, typed agent tools and the strategy overlay scope (AC28: text and voice share the same typed
permissions; reads create nothing).

    PYTHONPATH=src:tests python -m unittest tests.test_series_routes
"""
import io
import json
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import context as rt_context, contracts, tool_adapter
from postriff_phase2.coworker import overlays
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.permissions import Membership
from postriff_phase2.series import agent_tools, http, model as m
from postriff_phase2.series.service import SeriesService
from series_fixtures import NOW, Flags, Hosted, Repository, case, post, variant, workspace


class FakeApp:
    def __init__(self, body=None, query=""):
        self.body, self.query, self.sent = body, query, None

    def _body(self, _environ):
        return dict(self.body or {})

    def _query_int(self, _environ, key, default=0):
        from urllib.parse import parse_qs
        value = parse_qs(self.query).get(key, [None])[0]
        return default if value is None else int(value)

    def _query_str(self, _environ, key):
        from urllib.parse import parse_qs
        return parse_qs(self.query).get(key, [None])[0]

    def _json(self, _start, status, body):
        self.sent = (status, body)
        return [json.dumps(body).encode()]


class RecordingService:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args[2:], kwargs))
            return {"replayed": False, "name": name}
        return call


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True).__enter__()
        self.service = RecordingService()
        self.hosted = type("Hosted", (), {"series": self.service})()

    def tearDown(self):
        self.flags.__exit__()

    def route(self, method, rest, body=None, query=""):
        app = FakeApp(body, query)
        http.handle(app, {}, None, self.hosted, "token", method, ["api", "workspaces", "w1", "series", *rest])
        return app.sent, self.service.calls[-1]

    def test_every_route_reaches_its_service_method(self):
        sid, eid, vid = "a" * 32, "ep_1", "v1"
        cases = [
            ("GET", [], None, "limit=10&archived=1", ("list", (), {"limit": 10, "cursor": None, "archived": True})),
            ("POST", [], {"k": 1}, "", ("create", ({"k": 1},), {})),
            ("GET", ["candidates"], None, "kind=source&minAgeDays=60", ("candidates", (), {"kind": "source", "limit": 25, "cursor": None, "min_age_days": 60})),
            ("GET", [sid], None, "", ("get", (sid,), {})),
            ("POST", [sid, "plan"], {}, "", ("plan", (sid, {}), {})),
            ("POST", [sid, "status"], {}, "", ("set_status", (sid, {}), {})),
            ("POST", [sid, "episodes", eid, "angle"], {}, "", ("decide", (sid, eid, {}), {})),
            ("POST", [sid, "episodes", eid, "approve"], {}, "", ("approve", (sid, eid, {}), {})),
            ("POST", [sid, "episodes", eid, "drafts"], {}, "", ("link", (sid, eid, {}), {})),
            ("GET", [sid, "episodes", eid, "drafts", vid, "check"], None, "", ("draft_check", (sid, eid, vid), {})),
            ("POST", [sid, "episodes", eid, "drafts", vid, "unlink"], {}, "", ("unlink", (sid, eid, vid, {}), {})),
            ("POST", [sid, "claims", "cl_1"], {}, "", ("claim", (sid, "cl_1", {}), {})),
            ("POST", [sid, "decisions", "sd_1", "revoke"], {}, "", ("revoke", (sid, "sd_1", {}), {})),
        ]
        for method, rest, body, query, expected in cases:
            with self.subTest(method=method, rest=rest):
                (status, _), call = self.route(method, rest, body, query)
                self.assertEqual(call, expected)
                self.assertEqual(status, 201 if (method, rest) == ("POST", []) else 200)

    def test_unknown_routes_bad_ids_and_the_flag(self):
        for method, rest in (("DELETE", ["a" * 32]), ("POST", ["a" * 32, "publish"]), ("GET", ["../etc"]), ("GET", ["a" * 32, "episodes", "e", "drafts"])):
            with self.subTest(rest), self.assertRaises(AlphaError) as caught:
                self.route(method, rest, {})
            self.assertEqual(caught.exception.status, 404)
        with Flags(RAFII_SERIES_ENABLED=False), self.assertRaises(AlphaError) as caught:
            http.handle(FakeApp(), {}, None, self.hosted, "token", "GET", ["api", "workspaces", "w1", "series"])
        self.assertEqual(caught.exception.code, "feature_disabled")

    def test_the_program_route_table_dispatches_series(self):
        from postriff_phase2 import growth_v2_routes
        self.assertEqual(growth_v2_routes.RESOURCES["series"], "postriff_phase2.series.http")
        self.assertIn("postriff_phase2.series.jobs", growth_v2_routes.CRON)
        app = FakeApp()
        growth_v2_routes.handle(app, {}, None, self.hosted, "token", "GET", ["api", "workspaces", "w1", "series"])
        self.assertEqual(self.service.calls[-1][0], "list")


class AgentToolsTest(unittest.TestCase):
    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True).__enter__()
        agent_tools.register()
        agent_tools.register()   # idempotent
        self.repo = Repository()
        self.repo.tokens.update({"t": "owner-1", "viewer": "viewer-1"})
        state = workspace("ws")
        state["phase2"]["jobs"].append(post("old", case("en-series-evergreen")["source"], 45))
        self.repo.add("ws", state, {"owner-1": "owner", "viewer-1": "viewer"})
        self.hosted = Hosted(self.repo, lambda: NOW)
        self.hosted.series = SeriesService(self.hosted)

    def tearDown(self):
        self.flags.__exit__()

    def ctx(self, role="owner", modality="text", token="t"):
        return rt_context.RafiiRunContext(service=self.hosted, workspace_id="ws", token=token, principal="owner-1" if role == "owner" else "viewer-1",
                                          membership=Membership.from_row(role), conversation_id="c1", trace_id=contracts.new_trace_id(),
                                          modality=modality, now=lambda: NOW)

    def run_tool(self, name, args, **kw):
        return tool_adapter.execute(self.ctx(**kw), tool_adapter.REGISTRY[name], args)

    def test_specs_are_typed_voice_equal_and_never_external(self):
        specs = {name: tool_adapter.REGISTRY[name].spec for name in agent_tools.TOOL_SCOPES}
        self.assertEqual({n: (s.effect, s.permission, s.voice, s.approval) for n, s in specs.items()},
                         {"series_list": ("READ", "read", True, False), "series_prepare": ("CREATE_DRAFT", "edit", True, False),
                          "episode_prepare": ("CREATE_DRAFT", "edit", True, False)})

    def test_ac28_text_and_voice_prepare_the_same_series_and_reads_change_nothing(self):
        listed = self.run_tool("series_list", {}, modality="voice")
        self.assertEqual((listed["ok"], listed["series"]["data"]), (True, []))
        self.assertEqual(self.repo.commands, 0)
        args = {"originKind": "post", "originId": "old", "audienceQuestion": "How should adults practise?", "goal": "Habits"}
        voice = self.run_tool("series_prepare", args, modality="voice")
        self.assertTrue(voice["ok"] and voice["verified"])
        self.assertEqual(voice["series"]["kind"], "APP_STATE")   # series content reaches a model as data only
        episodes = voice["series"]["data"]["episodes"]
        self.assertEqual([e["role"] for e in episodes], ["explanation", "worked_example", "faq"])
        self.assertTrue(all(e["approvalRequired"] for e in episodes))
        again = self.run_tool("series_prepare", args)   # same request from text in another run: one series per original
        self.assertEqual((again["ok"], again["code"]), (False, "duplicate_series"))
        series_id = voice["series"]["data"]["id"]
        prepared = self.run_tool("episode_prepare", {"seriesId": series_id})
        self.assertEqual(prepared["episode"]["data"]["role"], "explanation")
        self.assertEqual(prepared["nextAction"]["kind"], "approve_next")
        before = self.repo.commands
        viewer = self.run_tool("series_prepare", {**args, "originId": "old"}, role="viewer", token="viewer")
        self.assertEqual(viewer["code"], "tool_forbidden")
        self.assertEqual(self.repo.commands, before)

    def test_episode_prepare_attaches_clean_drafts_and_hands_near_duplicates_back(self):
        created = self.run_tool("series_prepare", {"originKind": "post", "originId": "old", "audienceQuestion": "Q?", "goal": "G"})
        series_id = created["series"]["data"]["id"]
        first = created["series"]["data"]["episodes"][0]["episodeId"]
        self.hosted.series.approve("ws", "t", series_id, first, {"idempotencyKey": "approve-0001", "expectedRevision": 1})
        self.repo.workspaces["ws"]["state"]["variants"] += [variant("clean", "Tonight: one five-minute drill before your piece."),
                                                            variant("near", case("en-series-evergreen")["source"].replace("five", "ten"))]
        result = self.run_tool("episode_prepare", {"seriesId": series_id, "episodeId": first, "variantIds": ["clean", "near"]})
        self.assertEqual(result["episode"]["data"]["draftIds"], ["clean"])
        self.assertEqual(result["needsUser"][0]["variantId"], "near")
        self.assertEqual(result["needsUser"][0]["warnings"][0]["code"], "similar_to_original")

    def test_tools_answer_feature_disabled_when_off(self):
        with Flags(RAFII_SERIES_ENABLED=False):
            for name, args in (("series_list", {}), ("episode_prepare", {"seriesId": "x"})):
                self.assertEqual(self.run_tool(name, args)["code"], "feature_disabled")


class StrategyOverlayTest(unittest.TestCase):
    def test_series_strategy_items_never_reach_general_writing(self):
        state = workspace()
        overlays.add_item(state, {"id": "ov_series", "memoryType": "strategy", "statement": "Do not repeat the FAQ angle.", "scope": {"seriesId": "s1"},
                                  "status": "active", "createdAt": NOW}, "owner-1", NOW)
        overlays.add_item(state, {"id": "ov_voice", "memoryType": "voice", "statement": "No emoji.", "scope": {}, "status": "active"}, "owner-1", NOW)
        general = [i["id"] for i in overlays.effective_view(state, {"platforms": ["LinkedIn"], "locales": ["en"]})["items"]]
        self.assertEqual(general, ["ov_voice"])
        self.assertEqual([i["id"] for i in overlays.effective_view(state, {"seriesId": "s1"})["items"]], ["ov_series", "ov_voice"])
        self.assertEqual([i["memoryType"] for i in overlays.explicit_items(state)], ["strategy", "voice"])   # not coerced to voice
        self.assertTrue(overlays.set_status(state, "ov_series", "retired", "owner-1", NOW))
        self.assertFalse(overlays.set_status(state, "missing", "retired", "owner-1", NOW))
        self.assertEqual(overlays.scoped_items(state, "strategy", seriesId="s1")[0]["status"], "retired")

    def test_the_general_note_editor_still_takes_voice_and_brand_only(self):
        self.assertEqual(overlays.NOTE_TYPES, ("voice", "brand"))
        service = CoworkerService(type("Hosted", (), {"repository": None})(), clock=lambda: NOW)
        with Flags(RAFII_ADAPTIVE_SKILLS_ENABLED=True), self.assertRaisesRegex(AlphaError, "voice or brand"):
            service.overlay_note("w1", "t", {"memoryType": "strategy", "statement": "x"})


if __name__ == "__main__":
    unittest.main()
