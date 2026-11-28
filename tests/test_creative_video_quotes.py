"""Studio preflight and the grants that authorize a reviewed scene."""
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2 import creative_video_blueprint as blueprint
from postriff_phase2.creative_video import CreativeVideoService


class ReviewedScene(unittest.TestCase):
    def test_brief_only_plan_has_no_inferred_reference_evidence(self):
        brief = blueprint.validate_brief(dict(title="Spring", brief="Introduce the new tea.",
            platform="Instagram", aspectRatio="9:16", requestId="0123456789abcdef",
            rightsConfirmed=False, referenceAssetId=None))
        analysis = blueprint.brief_analysis()
        plan = blueprint.adapt(brief, analysis, {"brand":"Studio","subject":"tea","audience":"readers"})
        self.assertEqual(analysis["source"], "brief")
        self.assertEqual(len(plan), 3)
        self.assertTrue(all(not row["evidence"] for row in plan))
        self.assertNotIn("sha256", analysis)

    def test_submit_needs_separate_server_quote(self):
        for invalid in ({}, {"confirmed":True,"maxUsdMicro":900000,"revision":1,"sceneId":"scene-1"},
                        {"confirmed":True,"quoteId":"guess","settings":{"model":"injected"}}):
            with self.assertRaises(AlphaError):
                CreativeVideoService(object()).generate("workspace","session","project", invalid)
