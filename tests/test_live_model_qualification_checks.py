"""The live qualification's campaign_planning check judges the model, not the app: a field is "invented" only when the
request schema does not define it (or, in the app's reading, when the app does not derive it from the schedule).
Offline: no model call."""
import copy
import importlib.util
import unittest
from pathlib import Path

from postriff_phase2 import request_model

_SPEC = importlib.util.spec_from_file_location("live_model_qualification", Path(__file__).resolve().parents[1] / "scripts" / "live_model_qualification.py")
qualification = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qualification)

ANSWER = {"action": "automation", "tier": "light", "edit": None, "explain": None,
          "automation": {"name": "Recital countdown", "topic": "autumn recital", "goal": "Count down to the recital on LinkedIn.", "schedule": None,
                         "platforms": ["LinkedIn"], "voice": False, "assumptions": []}}
# The allow-list the check used before: it predates the reading's workflow fields, so every valid reading failed it.
STALE = {'weekdays', 'monthDays', 'countdown', 'localTime', 'topic', 'goal', 'name', 'contentTypeId', 'formatId', 'voice', 'assumptions'}


class CampaignPlanningCheckTest(unittest.TestCase):
    def test_a_schema_conforming_reading_invents_nothing(self):
        reading = request_model.reading(ANSWER, {})
        self.assertEqual(qualification.invented_automation_fields(ANSWER, reading), [])
        self.assertFalse(set(reading["automation"]) <= STALE, "the old check failed this valid reading on every model")

    def test_fields_the_app_derives_from_the_schedule_are_not_invented(self):
        reading = request_model.reading(ANSWER, {})
        reading["automation"]["countdown"] = {"eventDate": "2026-10-18", "daysBefore": [14, 7, 0]}
        reading["automation"]["localTime"] = "09:00"
        self.assertEqual(qualification.invented_automation_fields(ANSWER, reading), [])

    def test_a_field_outside_the_schema_is_reported(self):
        invented = copy.deepcopy(ANSWER)
        invented["automation"]["cron"] = "0 9 * * 2"
        self.assertEqual(qualification.invented_automation_fields(invented, request_model.reading(invented, {})), ["cron"])
        reading = request_model.reading(ANSWER, {})
        reading["automation"]["repeatEvery"] = 3
        self.assertEqual(qualification.invented_automation_fields(ANSWER, reading), ["repeatEvery"])


if __name__ == "__main__":
    unittest.main()
