"""Signature Series service (PRD R-SER-01/02, R-ENG-02; AC20, AC21, AC28/AC29 shapes) against an in-memory repository
with the PostgreSQL repository's contract. The disposable-database run is tests/phase2/postgres_series.py.

    PYTHONPATH=src:tests python -m unittest tests.test_series_service
"""
import copy
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns
from postriff_phase2.coworker import overlays
from postriff_phase2.series import jobs, model as m
from postriff_phase2.series.service import SeriesService
from series_fixtures import DAY, NOW, Flags, Hosted, Repository, case, post, source, variant, workspace

EN = case("en-series-evergreen")["source"]


class Base(unittest.TestCase):
    adaptive = False

    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True, RAFII_ADAPTIVE_SKILLS_ENABLED=self.adaptive).__enter__()
        self.clock = [NOW]
        self.repo = Repository()
        self.repo.tokens.update({"owner": "owner-1", "editor": "editor-1", "viewer": "viewer-1", "stranger": "stranger-1"})
        state = workspace("w1")
        state["phase2"]["jobs"] += [post("old", EN, 45), post("other", "A different post about scales and arpeggios for adult learners.", 90)]
        state["sources"].append(source("s1", "Lessons run on Saturdays.\nEach group has six learners."))
        self.repo.add("w1", state, {"owner-1": "owner", "editor-1": "editor", "viewer-1": "viewer"})
        other = workspace("w2")
        other["variants"].append(variant("foreign", "A draft in another workspace."))
        self.repo.add("w2", other, {"stranger-1": "owner"})
        self.service = SeriesService(Hosted(self.repo, lambda: self.clock[0]))
        self.keys = 0

    def tearDown(self):
        self.flags.__exit__()

    def key(self):
        self.keys += 1
        return f"test-key-{self.keys:04d}"

    def state(self):
        return self.repo.workspaces["w1"]["state"]

    def create(self, token="owner", **payload):
        body = {"origin": {"kind": "post", "id": "old"}, "audienceQuestion": "How should adult beginners practise?", "goal": "Practice habits",
                "idempotencyKey": self.key(), **payload}
        return self.service.create("w1", token, body)

    def act(self, method, *args, token="owner", **payload):
        series_id = args[0]
        revision = self.service.get("w1", token, series_id)["series"]["revision"]
        body = {"idempotencyKey": self.key(), "expectedRevision": revision, **payload}
        return getattr(self.service, method)("w1", token, *args, body)

    def episodes(self, view):
        return [e for e in view["series"]["episodes"] if e["workflowState"] != "skipped"]


class SeriesLifecycleTest(Base):
    def test_ac20_series_is_an_evergreen_campaign_with_distinct_episodes_and_source_refs(self):
        created = self.create(sourceIds=["s1"])
        self.assertTrue(created["verified"])
        series = created["series"]
        self.assertEqual([e["role"] for e in series["episodes"]], ["explanation", "worked_example", "faq"])
        self.assertEqual(series["origin"]["kind"], "post")
        self.assertTrue(series["origin"]["available"])
        self.assertEqual([s["sourceId"] for s in series["sources"]], ["s1"])
        self.assertTrue(all(s["versionCurrent"] for s in series["sources"]))
        self.assertTrue(any(c["support"]["kind"] == "source" for c in series["claims"]))
        self.assertTrue(all(c["reviewBy"] for c in series["claims"]))
        campaign = m.find(self.state(), series["id"])
        self.assertEqual((campaign["kind"], campaign["status"], campaign["version"]), ("series", "active", 1))
        self.assertIn(campaign["status"], ("needs_input", "draft", "active", "completed", "cancelled"))   # pr_campaigns CHECK
        # Series edits move the series revision only: the campaign brief and its version never change.
        episode = series["episodes"][0]["id"]
        self.act("approve", series["id"], episode)
        self.act("plan", series["id"], count=2)
        campaign = m.find(self.state(), series["id"])
        self.assertEqual((campaign["version"], campaign["goal"], campaign["facts"]), (1, "Practice habits", {}))
        self.assertEqual(campaign["series"]["revision"], 3)

    def test_ac21_originals_are_never_changed(self):
        before_job = copy.deepcopy(next(j for j in self.state()["phase2"]["jobs"] if j["id"] == "old"))
        before_source = copy.deepcopy(self.state()["sources"][0])
        created = self.create(sourceIds=["s1"])["series"]
        first = created["episodes"][0]["id"]
        self.act("approve", created["id"], first)
        self.repo.workspaces["w1"]["state"]["variants"].append(variant("d1", "Five focused minutes: a drill you can do tonight."))
        self.act("link", created["id"], first, variantId="d1", acknowledgedWarnings=[])
        claim = created["claims"][0]["id"]
        self.act("claim", created["id"], claim, action="update", text="Most adults stall because they rehearse whole pieces.", reviewBy="2027-01-01")
        self.assertEqual(next(j for j in self.state()["phase2"]["jobs"] if j["id"] == "old"), before_job)
        self.assertEqual(self.state()["sources"][0], before_source)
        self.assertEqual(self.state()["variants"][-1]["seriesEpisode"]["originId"], "old")   # the derivative points back

    def test_ac21_exact_duplicates_are_refused_and_near_duplicates_need_acknowledgement(self):
        series = self.create()["series"]
        first, second = series["episodes"][0]["id"], series["episodes"][1]["id"]
        self.act("approve", series["id"], first)
        variants = self.repo.workspaces["w1"]["state"]["variants"]
        variants += [variant("copy", EN.upper().replace(".", "!")), variant("published", "A DIFFERENT post about scales, and arpeggios for adult learners"),
                     variant("near", EN.replace("five minutes", "ten minutes")), variant("fresh", "Tonight: one five-minute drill, then your piece.")]
        for variant_id, kind in (("copy", "original"), ("published", "post")):
            with self.subTest(variant_id), self.assertRaises(AlphaError) as caught:
                self.act("link", series["id"], first, variantId=variant_id, acknowledgedWarnings=[])
            self.assertEqual((caught.exception.status, caught.exception.code), (409, "duplicate_episode"))
            check = self.service.draft_check("w1", "owner", series["id"], first, variant_id)
            self.assertEqual(check["refusal"]["duplicateOf"]["kind"], kind)
        check = self.service.draft_check("w1", "owner", series["id"], first, "near")
        self.assertIsNone(check["refusal"])
        self.assertEqual([w["code"] for w in check["warnings"]], ["similar_to_original"])
        with self.assertRaises(AlphaError) as caught:
            self.act("link", series["id"], first, variantId="near", acknowledgedWarnings=[])
        self.assertEqual(caught.exception.code, "warnings_unacknowledged")
        linked = self.act("link", series["id"], first, variantId="near", acknowledgedWarnings=[w["id"] for w in check["warnings"]])
        self.assertEqual(linked["series"]["episodes"][0]["drafts"][0]["warnings"][0]["code"], "similar_to_original")
        # The same text cannot become another episode, and one draft is one episode.
        self.repo.workspaces["w1"]["state"]["variants"].append(variant("again", EN.replace("five minutes", "ten minutes")))
        self.act("approve", series["id"], second)   # the first episode has its draft, so the next may be approved
        state = self.state()
        campaign = m.find(state, series["id"])
        episode = m.episode_of(campaign["series"], second)
        refusal = m.draft_checks(state, campaign, episode, "again")["refusal"]
        self.assertEqual((refusal["code"], refusal["duplicateOf"]["kind"]), ("duplicate_episode", "episode"))
        self.assertEqual(m.draft_checks(state, campaign, episode, "near")["refusal"]["code"], "duplicate_episode")

    def test_ac21_expired_claim_blocks_approval_and_gates_the_linked_draft_until_fixed(self):
        series = self.create()["series"]
        first = series["episodes"][0]["id"]
        self.act("approve", series["id"], first)
        self.repo.workspaces["w1"]["state"]["variants"].append(variant("d1", "Five focused minutes: a drill you can do tonight."))
        self.act("link", series["id"], first, variantId="d1", acknowledgedWarnings=[])
        claim = series["episodes"][0]["claimIds"][0]
        # A year later the claim's review date has passed.
        self.clock[0] = NOW + 400 * DAY
        view = self.service.get("w1", "owner", series["id"])["series"]
        self.assertEqual(view["episodes"][0]["factState"], "needs_fact_review")
        self.assertEqual(view["episodes"][0]["factReasons"], ["claim_expired"])
        self.assertEqual(view["nextAction"], {"kind": "review_facts"})
        with self.assertRaises(AlphaError) as caught:   # the next episode's facts expired too: it cannot be approved
            self.act("approve", series["id"], series["episodes"][1]["id"])
        self.assertEqual(caught.exception.code, "needs_fact_review")
        # The sweep gates the draft with Queue's own blockers (needsReview + an unknown).
        swept = jobs_tick(self)
        self.assertEqual(swept["gatedDrafts"], 1)
        draft = next(v for v in self.state()["variants"] if v["id"] == "d1")
        self.assertTrue(draft["needsReview"])
        self.assertTrue(draft["unknowns"][0].startswith(m.UNKNOWN_PREFIX))
        self.assertIn("expired", draft["unknowns"][0])
        # Confirming it is still true (with a new review date) lifts the series' own unknown.
        self.act("claim", series["id"], claim, action="reviewed", reviewBy="2027-12-31")
        draft = next(v for v in self.state()["variants"] if v["id"] == "d1")
        self.assertEqual(draft["unknowns"], [])
        self.assertEqual(self.service.get("w1", "owner", series["id"])["series"]["episodes"][0]["factState"], "ok")

    def test_ac21_deleted_source_propagates_to_episodes_drafts_and_evergreen(self):
        series = self.create(origin={"kind": "source", "id": "s1"})["series"]
        first = series["episodes"][0]["id"]
        self.act("approve", series["id"], first)
        self.repo.workspaces["w1"]["state"]["variants"].append(variant("d1", "Saturday lessons, six learners: what that means for you."))
        self.act("link", series["id"], first, variantId="d1", acknowledgedWarnings=[])
        # The source is withdrawn (retract_source keeps a tombstone without text or facts).
        source_row = self.repo.workspaces["w1"]["state"]["sources"][0]
        source_row.update(active=False, text="", facts=[], title="Withdrawn source")
        view = self.service.get("w1", "owner", series["id"])["series"]
        self.assertFalse(view["origin"]["available"])
        self.assertEqual(view["episodes"][0]["factReasons"], ["source_unavailable"])
        self.assertEqual(jobs_tick(self)["gatedDrafts"], 1)   # the sweep sees the withdrawn watched source
        self.assertTrue(any(u.startswith(m.UNKNOWN_PREFIX) for u in next(v for v in self.state()["variants"] if v["id"] == "d1")["unknowns"]))
        self.assertEqual(jobs_tick(self)["workspaces"], 0)    # nothing left to sweep
        with self.assertRaises(AlphaError) as caught:
            self.act("claim", series["id"], view["claims"][0]["id"], action="reviewed", reviewBy="2027-01-01")
        self.assertEqual(caught.exception.code, "source_unavailable")
        task = {"id": "t1", "include": {"evergreen": {"minAgeDays": 30, "seriesId": series["id"]}}}
        self.assertIsNone(m.evergreen_episode(self.state(), task, task["include"]["evergreen"], self.clock[0]))
        # Removing the unsupported fact is the other way to release the draft.
        for claim in view["claims"]:
            self.act("claim", series["id"], claim["id"], action="remove")
        self.assertEqual(next(v for v in self.state()["variants"] if v["id"] == "d1")["unknowns"], [])


class PreferencesTest(Base):
    adaptive = True

    def test_ac21_rejected_angle_is_never_planned_again_until_revoked(self):
        series = self.create()["series"]
        faq = next(e for e in series["episodes"] if e["role"] == "faq")
        decided = self.act("decide", series["id"], faq["id"], decision="reject")
        self.assertEqual(decided["result"]["storage"], "overlay")
        after = self.act("plan", series["id"], count=3)["series"]
        keys = [e["angle"]["key"] for e in after["episodes"] if e["workflowState"] != "skipped"]
        self.assertNotIn(faq["angle"]["key"], keys)
        self.assertEqual(len(keys), 3)                       # a different angle filled the place
        record = after["decisions"][0]
        self.act("revoke", series["id"], record["id"])
        # The rejection no longer shapes the plan: with room, the angle can come back.
        again = self.act("plan", series["id"], count=6)["series"]
        self.assertIn(faq["angle"]["key"], [e["angle"]["key"] for e in again["episodes"] if e["workflowState"] != "skipped"])

    def test_accepted_preference_shapes_the_next_plan_and_revoking_stops_it_without_touching_identity(self):
        state = self.state()
        identity = (copy.deepcopy(state["brandHub"]), copy.deepcopy(state["speaker"]), overlays.revisions(state)["voiceRevision"], overlays.revisions(state)["brandRevision"])
        series = self.create()["series"]
        faq = next(e for e in series["episodes"] if e["role"] == "faq")
        self.act("decide", series["id"], faq["id"], decision="accept")
        item = overlays.scoped_items(self.state(), "strategy", seriesId=series["id"])[0]
        self.assertEqual((item["memoryType"], item["scope"], item["status"]), ("strategy", {"seriesId": series["id"]}, "active"))
        # Workspace memory is scoped: general writing never sees the series decision.
        self.assertNotIn(item["id"], [i["id"] for i in overlays.effective_view(self.state(), {"platforms": ["Threads"]})["items"]])
        self.assertIn(item["id"], [i["id"] for i in overlays.effective_view(self.state(), {"seriesId": series["id"]})["items"]])
        # The next plan puts the accepted role first.
        state = self.state()
        campaign = m.find(state, series["id"])
        self.assertEqual(m.role_order(campaign["series"]["signals"], m.preferences(state, campaign)["acceptedRoles"])[0], "faq")
        planned = self.act("plan", series["id"], count=4)["series"]
        newest = max(planned["episodes"], key=lambda e: e["index"])
        self.assertEqual((newest["role"], newest["basis"]["reason"]), ("faq", "accepted_role"))
        decision = planned["decisions"][0]
        self.act("revoke", series["id"], decision["id"])
        self.assertEqual(overlays.scoped_items(self.state(), "strategy", seriesId=series["id"])[0]["status"], "retired")
        state = self.state()
        campaign = m.find(state, series["id"])
        self.assertEqual(m.preferences(state, campaign)["acceptedRoles"], [])
        self.assertEqual(m.role_order(campaign["series"]["signals"], [])[0], "explanation")
        after = (state["brandHub"], state["speaker"], overlays.revisions(state)["voiceRevision"], overlays.revisions(state)["brandRevision"])
        self.assertEqual(after, identity)

    def test_do_not_repeat_a_role_and_who_may_keep_it_in_workspace_memory(self):
        series = self.create()["series"]
        worked = next(e for e in series["episodes"] if e["role"] == "worked_example")
        # An editor's decision stays on the series record (workspace memory is owner-only) and says so.
        result = self.act("decide", series["id"], worked["id"], token="editor", decision="do_not_repeat", level="role")["result"]
        self.assertEqual((result["storage"], result["reason"]), ("series", "owner_required"))
        planned = self.act("plan", series["id"], count=6)["series"]
        self.assertNotIn("worked_example", [e["role"] for e in planned["episodes"] if e["workflowState"] != "skipped"])
        with self.assertRaises(AlphaError) as caught:
            self.act("decide", series["id"], worked["id"], decision="reject")
        self.assertEqual(caught.exception.code, "lifecycle_transition")   # already set aside
        # An owner's decision is workspace memory: an editor cannot revoke it.
        explanation = next(e for e in planned["episodes"] if e["role"] == "explanation" and e["workflowState"] == "planned")
        owner_decision = self.act("decide", series["id"], explanation["id"], decision="accept")["result"]
        with self.assertRaises(AlphaError) as caught:
            self.act("revoke", series["id"], owner_decision["id"], token="editor")
        self.assertEqual(caught.exception.status, 403)


class OverlaysOffTest(Base):
    adaptive = False

    def test_with_workspace_memory_off_the_decision_stays_on_the_series_and_says_so(self):
        series = self.create()["series"]
        result = self.act("decide", series["id"], series["episodes"][2]["id"], decision="reject")["result"]
        self.assertEqual((result["storage"], result["reason"], result["overlayId"]), ("series", "overlays_disabled", None))
        self.assertEqual(overlays.scoped_items(self.state(), "strategy", seriesId=series["id"]), [])
        view = self.service.get("w1", "owner", series["id"])["series"]
        self.assertEqual(view["decisions"][0]["status"], "active")
        self.assertTrue(view["decisions"][0]["canRevoke"])


class ContractTest(Base):
    def test_ac29_revision_and_idempotency_conflicts(self):
        series = self.create()["series"]
        first = series["episodes"][0]["id"]
        body = {"idempotencyKey": "approve-once-0001", "expectedRevision": series["revision"]}
        approved = self.service.approve("w1", "owner", series["id"], first, dict(body))
        self.assertTrue(approved["verified"])
        commands_before = self.repo.commands
        replay = self.service.approve("w1", "owner", series["id"], first, dict(body))      # same key, same request
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.repo.commands, commands_before)                               # nothing written twice
        with self.assertRaises(AlphaError) as caught:                                       # same key, another target
            self.service.approve("w1", "owner", series["id"], series["episodes"][1]["id"], dict(body))
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "idempotency_conflict"))
        with self.assertRaises(AlphaError) as caught:                                       # stale revision
            self.service.plan("w1", "owner", series["id"], {"idempotencyKey": "plan-stale-0001", "expectedRevision": series["revision"], "count": 2})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "revision_conflict"))
        with self.assertRaises(AlphaError):
            self.service.plan("w1", "owner", series["id"], {"idempotencyKey": "short", "expectedRevision": 2})
        create_body = {"origin": {"kind": "post", "id": "other"}, "audienceQuestion": "Scales?", "goal": "Scales series", "idempotencyKey": "create-scales-01"}
        first_create = self.service.create("w1", "owner", dict(create_body))
        again = self.service.create("w1", "owner", dict(create_body))
        self.assertEqual((again["replayed"], again["series"]["id"]), (True, first_create["series"]["id"]))
        with self.assertRaises(AlphaError) as caught:
            self.service.create("w1", "owner", {**create_body, "goal": "Something else"})
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        with self.assertRaises(AlphaError) as caught:                                       # one series per original
            self.service.create("w1", "owner", {**create_body, "idempotencyKey": "create-scales-02"})
        self.assertEqual(caught.exception.code, "duplicate_series")

    def test_ac29_one_approved_episode_at_a_time(self):
        series = self.create()["series"]
        self.act("approve", series["id"], series["episodes"][0]["id"])
        with self.assertRaises(AlphaError) as caught:
            self.act("approve", series["id"], series["episodes"][1]["id"])
        self.assertEqual(caught.exception.code, "episode_pending")
        view = self.service.get("w1", "owner", series["id"])["series"]
        self.assertEqual(view["nextAction"], {"kind": "add_draft", "episodeId": series["episodes"][0]["id"]})
        self.assertEqual(view["episodes"][1]["blockedReason"], "episode_pending")

    def test_ac28_permissions_tenancy_and_the_flag(self):
        series = self.create()["series"]
        self.assertEqual(self.service.get("w1", "viewer", series["id"])["series"]["id"], series["id"])   # read
        with self.assertRaises(AlphaError) as caught:
            self.act("approve", series["id"], series["episodes"][0]["id"], token="viewer")
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(AlphaError) as caught:                                       # not a member of w1
            self.service.get("w1", "stranger", series["id"])
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(AlphaError) as caught:                                       # w1's series is not in w2
            self.service.get("w2", "stranger", series["id"])
        self.assertEqual(caught.exception.status, 404)
        self.act("approve", series["id"], series["episodes"][0]["id"])
        with self.assertRaises(AlphaError) as caught:                                       # w2's draft id in w1
            self.act("link", series["id"], series["episodes"][0]["id"], variantId="foreign", acknowledgedWarnings=[])
        self.assertEqual(caught.exception.status, 404)
        with Flags(RAFII_SERIES_ENABLED=False):
            for call in (lambda: self.service.list("w1", "owner"), lambda: self.create()):
                with self.assertRaises(AlphaError) as caught:
                    call()
                self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))

    def test_ac29_cursor_pagination_is_deterministic_and_bounded(self):
        state = self.state()
        for i in range(4):
            state["phase2"]["jobs"].append(post(f"p{i}", f"Post number {i} about practice habits for adults, with its own idea {i}.", 40 + i))
        ids = []
        for i in range(4):
            self.clock[0] = NOW + i
            ids.append(self.create(origin={"kind": "post", "id": f"p{i}"})["series"]["id"])
        first = self.service.list("w1", "owner", limit=3)
        self.assertEqual([s["id"] for s in first["items"]], list(reversed(ids))[:3])
        rest = self.service.list("w1", "owner", limit=3, cursor=first["nextCursor"])
        self.assertEqual([s["id"] for s in rest["items"]], [ids[0]])
        self.assertIsNone(rest["nextCursor"])
        for bad in ({"limit": 0}, {"limit": 51}, {"cursor": "not-a-cursor"}):
            with self.subTest(bad), self.assertRaises(AlphaError) as caught:
                self.service.list("w1", "owner", **bad)
            self.assertEqual(caught.exception.status, 400)
        self.act("set_status", ids[0], status="archived")
        self.assertNotIn(ids[0], [s["id"] for s in self.service.list("w1", "owner", limit=50)["items"]])
        self.assertIn(ids[0], [s["id"] for s in self.service.list("w1", "owner", limit=50, archived=True)["items"]])
        self.assertEqual(m.find(self.state(), ids[0])["status"], "cancelled")

    def test_candidates_show_eligibility_and_prior_use_without_inventing_metrics(self):
        series = self.create()["series"]
        posts = self.service.candidates("w1", "owner", kind="post", min_age_days=30)
        by_id = {p["id"]: p for p in posts["items"]}
        self.assertEqual(set(by_id), {"old", "other"})
        self.assertEqual(by_id["old"]["priorUse"], [{"kind": "series", "id": series["id"]}])
        self.assertIsNone(by_id["old"]["observed"])            # no comparable cohort: no number at all
        self.assertEqual(posts["observedState"], "unavailable")
        self.assertEqual([p["id"] for p in self.service.candidates("w1", "owner", kind="post", min_age_days=60)["items"]], ["other"])
        sources = self.service.candidates("w1", "owner", kind="source")
        self.assertEqual([s["id"] for s in sources["items"]], ["s1"])

    def test_approval_records_one_episode_accepted_event_and_a_content_free_audit(self):
        series = self.create()["series"]
        self.act("approve", series["id"], series["episodes"][0]["id"])
        inserts = [params for sql, params in self.repo.sql if "pr_product_events" in sql]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][2], "series.episode_accepted")
        self.assertIn('"role": "explanation"', inserts[0][3])
        kinds = [entry[2] for entry in self.repo.audits]
        self.assertEqual(kinds, ["series.created", "series.episode_approved"])
        self.assertNotIn("practise", repr(self.repo.audits))   # ids, enums and counts only

    def test_episode_images_are_references_to_library_images_and_a_deleted_one_shows(self):
        series = self.create()["series"]
        first = series["episodes"][0]["id"]
        assets = self.repo.workspaces["w1"]["state"]["phase2"]["assets"]
        assets += [{"id": "img1", "mime": "image/jpeg", "hash": "h1"}, {"id": "vid1", "mime": "video/mp4", "hash": "h2"}]
        with self.assertRaises(AlphaError) as caught:   # not before the episode is approved
            self.act("link_asset", series["id"], first, assetId="img1")
        self.assertEqual(caught.exception.code, "approval_required")
        self.act("approve", series["id"], first)
        linked = self.act("link_asset", series["id"], first, assetId="img1")["series"]["episodes"][0]
        self.assertEqual(linked["assets"], [{"assetId": "img1", "available": True}])
        for asset_id, status in (("vid1", 409), ("img1", 409), ("nope", 404)):
            with self.subTest(asset_id), self.assertRaises(AlphaError) as caught:
                self.act("link_asset", series["id"], first, assetId=asset_id)
            self.assertEqual(caught.exception.status, status)
        self.repo.workspaces["w1"]["state"]["phase2"]["assets"][0]["deleted"] = True
        self.assertEqual(self.service.get("w1", "owner", series["id"])["series"]["episodes"][0]["assets"], [{"assetId": "img1", "available": False}])
        self.assertEqual(self.act("unlink_asset", series["id"], first, "img1")["series"]["episodes"][0]["assets"], [])

    def test_a_series_campaign_is_never_rescheduled_or_rewritten_as_a_plain_brief(self):
        series = self.create()["series"]
        state = self.state()
        for action, payload in (("raffi_campaign_update", {"campaignId": series["id"], "goal": "Rewritten"}),
                                ("raffi_recurrence_preview", {"campaignId": series["id"], "schedule": {"weekday": "Monday", "localTime": "09:00", "timeZone": "UTC"}})):
            with self.subTest(action), self.assertRaises(AlphaError) as caught:
                campaigns.apply_action(state, action, payload, "owner-1", NOW)
            self.assertEqual(caught.exception.status, 409)


def jobs_tick(test):
    """Run the sweep against the in-memory repository: the SQL selection is replaced by the same predicate in Python."""
    import contextlib
    import json
    import time

    class Cursor:
        def __init__(self):
            self.rows = []

        def execute(self, sql, params=None):
            if "FROM public.pr_workspaces w" in sql:
                now = params[0]
                self.rows = [(wid, json.dumps(ws["state"])) for wid, ws in test.repo.workspaces.items()
                             if any(jobs._due(c, ws["state"], now) for c in m.all_series(ws["state"]))]
            elif sql.startswith("UPDATE public.pr_workspaces"):
                state, wid = params
                test.repo.workspaces[wid]["state"] = json.loads(state)
                test.repo.workspaces[wid]["revision"] += 1

        def fetchall(self):
            return self.rows

    @contextlib.contextmanager
    def connection():
        cursor = Cursor()
        yield type("Db", (), {"cursor": lambda _self: contextlib.nullcontext(cursor)})()

    hosted = type("Hosted", (), {"connection_factory": staticmethod(connection), "clock": staticmethod(lambda: test.clock[0]), "commands": None})()
    import unittest.mock as mock
    with mock.patch("postriff_phase2.planning_store.sync"), mock.patch("postriff_phase2.hosted.audit"):
        return jobs.tick(hosted, time.monotonic() + 5)


if __name__ == "__main__":
    unittest.main()
