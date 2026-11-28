import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.creative_video_blueprint import edit_scenes


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.clip = "c" * 32
        self.first = dict(sceneId="a", direction="A", durationMs=1000, caption="", clipId=None, take="a")
        self.last = dict(self.first, sceneId="b", clipId=self.clip, take="b")
        self.scenes = [self.first, self.last]

    def edit(self, patches, **options):
        return edit_scenes(self.scenes, patches, None, lambda _: {"duration": 2.5},
                           generated_clips={"a": self.clip}, **options)

    def test_reorder_and_trim_generated_asset_without_replacing_any_take(self):
        last, first = self.edit([{"sceneId": "a", "trimStartMs": 1500}], order=["b", "a"])
        self.assertEqual(last, self.last)
        self.assertEqual(first, {**self.first, "trimStartMs": 1500})
        self.assertNotIn("trimStartMs", self.first)
        self.assertEqual(self.edit([], order=["b", "a"]), [self.last, self.first])

    def test_reject_invalid_order_or_cut_before_saving(self):
        for order in ([], ["a"], ["b", "b"], ["b", "c"], ["a", ["b"]], "ab"):
            with self.subTest(order=order), self.assertRaises(AlphaError):
                self.edit([], order=order)
        for trim in (-1, True, 1502, 90000, "12"):
            with self.subTest(trim=trim), self.assertRaises(AlphaError):
                self.edit([{"sceneId": "a", "trimStartMs": trim}])
        with self.assertRaises(AlphaError):
            self.edit([{"sceneId": "a", "retake": True, "trimStartMs": 500}])
        with self.assertRaises(AlphaError):
            self.edit([])

    def test_new_take_and_replacement_start_at_zero_by_default(self):
        self.first["trimStartMs"] = 1250
        for patch in ({"retake": True}, {"direction": "Fresh footage"},
                      {"clipId": "d" * 32, "clipRightsConfirmed": True}):
            first, _ = self.edit([{"sceneId": "a", **patch}])
            self.assertNotEqual(first["take"], self.first["take"])
            self.assertEqual(first.get("trimStartMs", 0), 0)

    def test_lengthening_within_an_existing_take_does_not_request_new_footage(self):
        first, _ = self.edit([{"sceneId": "a", "durationMs": 2000, "trimStartMs": 500}])
        self.assertEqual((first["take"], first["durationMs"], first["trimStartMs"]), ("a", 2000, 500))
        longer, _ = self.edit([{"sceneId": "a", "durationMs": 3000}])
        self.assertNotEqual(longer["take"], "a")
