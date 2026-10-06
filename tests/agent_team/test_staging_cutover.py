import unittest

from postriff_phase2.agent_team_cutover import (
    STAGING_PROJECT_ID, call_enabled, cutover_source, staging_cutover, team_enabled,
)


class AgentTeamStagingCutoverTests(unittest.TestCase):
    def staging(self, **changes):
        return {"VERCEL_PROJECT_ID": STAGING_PROJECT_ID, "VERCEL_ENV": "production",
                "JAMES_AGENT_TEAM_ENABLED": "0", "JAMES_AGENT_TEAM_CALL_ENABLED": "0", **changes}

    def test_exact_staging_production_project_enables_team_and_report_call(self):
        values=self.staging()
        self.assertTrue(staging_cutover(values))
        self.assertTrue(team_enabled(values))
        self.assertTrue(call_enabled(values))
        self.assertEqual(cutover_source(values), "rafii_consumer_staging")

    def test_preview_and_other_projects_never_inherit_staging_cutover(self):
        for values in (
            self.staging(VERCEL_ENV="preview"),
            self.staging(VERCEL_PROJECT_ID="prj_founder_production"),
            {"VERCEL_ENV":"production","JAMES_AGENT_TEAM_ENABLED":"0","JAMES_AGENT_TEAM_CALL_ENABLED":"0"},
        ):
            with self.subTest(values=values):
                self.assertFalse(staging_cutover(values))
                self.assertFalse(team_enabled(values))
                self.assertFalse(call_enabled(values))

    def test_environment_flags_still_enable_non_staging_runtime(self):
        values={"JAMES_AGENT_TEAM_ENABLED":"1","JAMES_AGENT_TEAM_CALL_ENABLED":"1"}
        self.assertTrue(team_enabled(values))
        self.assertTrue(call_enabled(values))
        self.assertEqual(cutover_source(values), "environment")

    def test_direct_daily_call_gate_preserves_call_flag_semantics(self):
        values={"JAMES_AGENT_TEAM_ENABLED":"0","JAMES_AGENT_TEAM_CALL_ENABLED":"1"}
        self.assertFalse(team_enabled(values))
        self.assertTrue(call_enabled(values))

    def test_emergency_disable_wins_over_staging_and_environment(self):
        values=self.staging(JAMES_AGENT_TEAM_ENABLED="1",JAMES_AGENT_TEAM_CALL_ENABLED="1",
                            JAMES_AGENT_TEAM_EMERGENCY_DISABLE="1")
        self.assertFalse(team_enabled(values))
        self.assertFalse(call_enabled(values))
        self.assertEqual(cutover_source(values), "emergency_disabled")
        values=self.staging(JAMES_AGENT_TEAM_CALL_EMERGENCY_DISABLE="1")
        self.assertTrue(team_enabled(values))
        self.assertFalse(call_enabled(values))


if __name__=="__main__":
    unittest.main()
