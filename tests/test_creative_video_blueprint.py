import copy
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.creative_video_blueprint import adapt, edit_scenes, generation_prompt, project_context, validate_brief

BRIEF = {"requestId": "request_creative_0001", "referenceAssetId": "b" * 32, "rightsConfirmed": True,
         "title": "A new release", "brief": "Introduce our fountain pen", "platform": "Instagram", "aspectRatio": "9:16"}


class BlueprintTests(unittest.TestCase):
    def test_reference_requires_rights_and_scoped_library_id(self):
        for delta in ({"rightsConfirmed": False}, {"rightsConfirmed": 1}, {"referenceAssetId": "https://invalid.example/a"},
                      {"brief": ""}, {"aspectRatio": "5:7"}, {"scenes": []}):
            with self.subTest(delta=delta), self.assertRaises(AlphaError):
                validate_brief({**BRIEF, **delta})

    def test_scene_planning_preserves_duration_and_has_traceable_measures(self):
        context = {"brand": "Ink House", "subject": "pens", "audience": "artists", "tone": "", "preferences": []}
        analysis = {"durationMs": 10000, "scenes": [{"startMs": 0, "endMs": 1200, "durationMs": 1200,
                     "pacing": "quick"}, {"startMs": 1200, "endMs": 10000, "durationMs": 8800, "pacing": "lingering"}]}
        shots = adapt(BRIEF, analysis, context)
        self.assertEqual(sum(s["durationMs"] for s in shots), 10000)
        self.assertTrue(all(42 <= s["durationMs"] <= 8000 for s in shots))
        self.assertEqual([s["sourceStartMs"] for s in shots], [0, 1200, 5600])
        self.assertIn("Ink House", shots[0]["direction"])
        self.assertTrue(all(s["clipId"] is None for s in shots))

    def test_edit_preserves_other_take_and_composition_only_edits(self):
        shots = [{"sceneId": k,"durationMs": 1000,"direction": "An original motion","caption": "","take": k,
                  "clipId": None,"purpose": "Show the product"} for k in ("a", "b")]
        def resolve(asset_id):
            return {"id": asset_id, "duration": 2}
        caption = edit_scenes(shots, [{"sceneId":"a","caption":"New caption"}], BRIEF["referenceAssetId"], resolve)
        self.assertEqual(caption[0]["take"], "a")
        revised = edit_scenes(caption, [{"sceneId":"a","direction":"A different action"}], BRIEF["referenceAssetId"], resolve)
        self.assertNotEqual(revised[0]["take"], "a")
        self.assertEqual(revised[1], shots[1])
        self.assertEqual(shots[0]["caption"], "")
        another = edit_scenes(shots, [{"sceneId":"a","retake":True}], BRIEF["referenceAssetId"], resolve)
        self.assertNotEqual(another[0]["take"], "a")
        self.assertEqual(another[0]["direction"], shots[0]["direction"])
        self.assertEqual(another[1], shots[1])
        for bad in ({"clipId":"c"*32}, {"clipId":BRIEF["referenceAssetId"],"clipRightsConfirmed":True}, {"durationMs":True}):
            with self.assertRaises(AlphaError):
                edit_scenes(shots, [{"sceneId":"a",**bad}], BRIEF["referenceAssetId"], resolve)

    def test_suggestions_change_with_brief_and_reference_measurements(self):
        context = {"brand":"Ink House","subject":"fountain pens","audience":"artists","tone":"gentle",
                   "preferences":["Hold the last mark."]}
        analysis = {"durationMs":2000, "scenes":[{"startMs":0,"endMs":2000,"measurements":{"meanLuma":0.9}}]}
        first, = adapt(BRIEF, analysis, context)
        second, = adapt({**BRIEF, "brief":"Demonstrate the refill"}, analysis, context)
        self.assertNotEqual(first["direction"], second["direction"])
        for sample in ("refill", "bright setting", "gentle", "Hold the last mark."):
            self.assertIn(sample, second["direction"])
        self.assertIn("fountain pens", first["caption"])
        analysis["overlaySignals"] = {"frames":[{"sceneIndex":0,"timeMs":210,"interpretiveClues":["question"]},
                                                {"sceneIndex":0,"timeMs":1720,"interpretiveClues":[]}]}
        question, = adapt(BRIEF, analysis, context)
        self.assertIn("original opening question", question["direction"])

    def test_preference_omitted_by_canonical_projection_never_reaches_writer(self):
        state = {"memoryEgress":{"cloud":True}, "learning":{"revision":3, "active":[
            {"id":"quiet","statement":"Secret preference withheld","status":"active","scope":{},
             "confirmedBy":"test-owner","evidenceState":"user_confirmed"}]}}
        context, receipt = project_context(state, "Instagram")
        self.assertEqual(context["preferences"], [])
        prompt = generation_prompt({**BRIEF, "context":context, "memoryReceipt":receipt},
                                   {"direction":"Write normally."}, state)
        self.assertNotIn("Secret preference withheld", prompt)

    def test_context_uses_approved_memory_and_refuses_cloud_without_grant(self):
        state = {"brandHub":{"speaker":"Ink House","subject":"Pens","audience":"Artists"},
                 "speaker":{"activeRevision":2,"revisions":[{"revision":2,"profile":{"tone":"Precise"}}],
                            "provisional":{"tone":"Unapproved"}}}
        before = copy.deepcopy(state)
        context, _ = project_context(state, "Instagram")
        self.assertEqual((context["brand"], context["tone"], context["cloudAllowed"]), ("Ink House","Precise",False))
        self.assertEqual(state, before)
