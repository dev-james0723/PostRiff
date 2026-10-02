"""Opportunity brief composition and delivery rules (PRD R-BRF-01/02): AC24 (at most three sourced items, zero when
coverage is empty or unsupported, nothing fabricated) and the pure parts of AC25 (edition windows and the daily cap
across DST, weekly cadence, material-change dedupe)."""
import copy
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.briefs import composer, sources

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=ZoneInfo("UTC")).timestamp()   # a Wednesday
DAY = 86400


def at(zone, *parts):
    return datetime(*parts, tzinfo=ZoneInfo(zone)).timestamp()


def candidate(ref, **extra):
    base = {"source": "listening", "sourceRef": ref, "sourceRevision": 1, "kind": "signal", "title": f"Piano practice routine {ref}",
            "evidence": [{"url": f"https://example.org/{ref}", "label": "example.org", "publishedAt": NOW - 2 * DAY, "retrievedAt": NOW - DAY}],
            "publishedAt": NOW - 2 * DAY, "retrievedAt": NOW - DAY, "expiresAt": NOW + 5 * DAY,
            "coverage": {"availability": "available", "completeness": "partial"}, "angle": {"id": None, "text": f"Angle for {ref}"},
            "interests": [{"label": "piano practice", "via": "watchlist"}], "action": {"kind": "save_idea"}}
    base.update(extra)
    return base


CONTEXT = {"goals": ["Grow piano students"], "material": [{"id": "s1", "title": "Practice routine handout"}], "brand": None, "recentAngles": []}


class ComposeTest(unittest.TestCase):
    def test_ac24_at_most_three_sourced_items_with_every_field(self):
        topics = ["Metronome drills", "Recital nerves", "Sight reading", "Scale warmups", "Pedal technique", "Hand posture"]
        result = composer.compose([candidate(f"op{i}", title=t, angle={"id": None, "text": f"Distinct angle {i}"}) for i, t in enumerate(topics)],
                                  CONTEXT, [], NOW)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["excluded"].get("over_limit"), 3)
        for item in result["items"]:
            self.assertTrue(item["id"].startswith("bi_"))
            self.assertEqual(item["source"], "listening")
            self.assertEqual(item["dataMode"], "stored")
            self.assertTrue(item["evidence"] and item["evidence"][0]["url"])
            self.assertIsNotNone(item["retrievedAt"])
            self.assertIn("availability", item["coverage"])
            self.assertTrue(item["relevance"]["reason"])
            self.assertTrue(item["angle"]["text"])
            self.assertIn(item["effort"], composer.EFFORTS)
            self.assertIn(item["action"]["kind"], composer.OPEN_ACTIONS)
        self.assertEqual(len({i["angle"]["text"] for i in result["items"]}), 3)

    def test_ac24_zero_is_valid_and_nothing_is_fabricated(self):
        self.assertEqual(composer.compose([], CONTEXT, [], NOW), {"items": [], "considered": 0, "excluded": {}})
        coverage = [sources.coverage("trends", "unavailable", "trends_not_enabled"), sources.coverage("listening", "unavailable", "listening_not_enabled"),
                    sources.coverage("radar", "unavailable", "radar_not_enabled")]
        self.assertEqual(composer.data_state(coverage), "unavailable")
        self.assertEqual(composer.data_state([sources.coverage("listening", "empty")] + coverage[:1]), "partial")
        self.assertEqual(composer.data_state([sources.coverage("listening", "empty")]), "available")

    def test_unqualified_candidates_are_excluded_with_reasons(self):
        rows = [candidate("expired", expiresAt=NOW - 1), candidate("stale", retrievedAt=NOW - 8 * DAY),
                candidate("unknown", retrievedAt=None), candidate("ws", kind="whitespace", gapEvidence=[]),
                candidate("unsafe", unsafe=True), candidate("low", lowConfidence=True),
                candidate("concern", fit={"risk": {"assessment": "concern"}}), candidate("blank", title="  "),
                candidate("noaction", action={"kind": "publish"}),
                candidate("irrelevant", title="Quarterly tax filing deadlines", interests=[], angle={"id": None, "text": "Tax angle"})]
        result = composer.compose(rows, CONTEXT, [], NOW)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["excluded"], {"expired": 1, "stale": 1, "retrieval_time_unknown": 1, "whitespace_without_evidence": 1, "unsafe_source_text": 1,
                                              "low_confidence": 1, "fit_concern": 1, "invalid": 1, "unsupported_action": 1, "no_relevance": 1})

    def test_whitespace_needs_observed_gap_evidence(self):
        with_gap = composer.compose([candidate("gap", kind="whitespace", gapEvidence=["evidence-1", "evidence-2"])], CONTEXT, [], NOW)["items"]
        self.assertEqual(with_gap[0]["gapEvidence"], ["evidence-1", "evidence-2"])
        self.assertEqual(with_gap[0]["effort"], "deep")

    def test_verified_projection_freshness_basis_for_trends(self):
        trend = candidate("t1", source="trends", retrievedAt=None, freshnessBasis="verified_unexpired_projection", action={"kind": "accept", "angleIds": ["a1"]},
                          fit={"audience": {"assessment": "supported"}}, interests=[])
        item = composer.compose([trend], {"goals": [], "material": []}, [], NOW)["items"][0]
        self.assertEqual(item["freshnessBasis"], "verified_unexpired_projection")
        self.assertEqual(item["relevance"]["matches"][0]["kind"], "fit")

    def test_history_dismiss_cooldown_not_relevant_and_restore(self):
        rows = [candidate("a"), candidate("b", title="Other piano topic b", angle={"id": None, "text": "b"}), candidate("c", title="Third piano idea c", angle={"id": None, "text": "c"})]
        history = [{"id": "1", "source": "listening", "sourceRef": "a", "action": "dismiss", "at": NOW - DAY},
                   {"id": "2", "source": "listening", "sourceRef": "b", "action": "not_relevant", "at": NOW - 30 * DAY},
                   {"id": "3", "source": "listening", "sourceRef": "c", "action": "save_idea", "at": NOW - DAY}]
        result = composer.compose(rows, CONTEXT, history, NOW)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["excluded"], {"dismissed": 1, "not_relevant": 1, "acted": 1})
        later = composer.compose([candidate("a", retrievedAt=NOW + 6 * DAY, expiresAt=NOW + 9 * DAY)], CONTEXT, history, NOW + 7 * DAY)   # the dismissal cooled down
        self.assertEqual(len(later["items"]), 1)
        restored = history + [{"id": "4", "source": "listening", "sourceRef": "b", "action": "restore", "at": NOW}]
        self.assertEqual([i["sourceRef"] for i in composer.compose(rows[1:2], CONTEXT, restored, NOW)["items"]], ["b"])

    def test_ranking_prefers_own_material_questions_and_goals_not_popularity(self):
        popular = candidate("popular", title="Viral piano trend", popularity=10**9, angle={"id": None, "text": "viral"}, publishedAt=NOW - 60)
        question = candidate("question", kind="question", title="How do adults keep a habit?", angle={"id": None, "text": "q"}, publishedAt=NOW - 3 * DAY)
        credible = candidate("credible", title="Practice routine for busy parents", angle={"id": None, "text": "r"}, publishedAt=NOW - 4 * DAY)
        order = [i["sourceRef"] for i in composer.compose([popular, question, credible], CONTEXT, [], NOW)["items"]]
        self.assertEqual(order[0], "credible")                  # builds on the person's own material
        self.assertEqual(order[1], "question")                  # then an audience question
        self.assertEqual(order[2], "popular")

    def test_duplicate_topics_and_planned_angles_are_skipped(self):
        one = candidate("one", title="Metronome practice for beginners", angle={"id": None, "text": "Use a metronome"})
        twin = candidate("twin", title="Metronome practice for beginners!", angle={"id": None, "text": "Another angle"}, publishedAt=NOW - 5 * DAY)
        planned = candidate("planned", title="Recital nerves", angle={"id": None, "text": "Calm recital nerves"})
        result = composer.compose([one, twin, planned], {**CONTEXT, "recentAngles": ["Calm recital nerves."]}, [], NOW)
        self.assertEqual([i["sourceRef"] for i in result["items"]], ["one"])
        self.assertEqual(result["excluded"], {"duplicate_topic": 1, "already_planned": 1})

    def test_material_digest_ignores_cosmetic_changes(self):
        items = composer.compose([candidate("a"), candidate("b", title="Second piano item", angle={"id": None, "text": "b"})], CONTEXT, [], NOW)["items"]
        cosmetic = copy.deepcopy(items)
        cosmetic[0]["title"] = cosmetic[0]["title"] + "!"
        cosmetic[0]["relevance"]["reason"] = "Reworded."
        cosmetic[0]["coverage"]["note"] = "Different wording."
        self.assertEqual(composer.material_digest(items), composer.material_digest(cosmetic))
        self.assertEqual(composer.material_digest(items), composer.material_digest(list(reversed(items))))
        changed = copy.deepcopy(items)
        changed[0]["sourceRevision"] = "2"
        self.assertNotEqual(composer.material_digest(items), composer.material_digest(changed))
        self.assertNotEqual(composer.material_digest(items), composer.material_digest(items[:1]))

    def test_cjk_relevance(self):
        item = candidate("zh", title="如何幫助成人學生建立練琴習慣", interests=[], angle={"id": None, "text": "練琴"})
        result = composer.compose([item], {"goals": ["幫助成人學生練琴"], "material": []}, [], NOW)
        self.assertEqual(result["items"][0]["relevance"]["matches"][0]["kind"], "goal")
        self.assertTrue(composer.is_question("如何幫助成人學生建立練琴習慣"))


class DecisionLifecycleTest(unittest.TestCase):
    def test_restore_clears_and_a_dismissal_lapses_after_the_cooldown(self):
        self.assertIsNone(composer.active_decision(None, NOW))
        self.assertIsNone(composer.active_decision({"action": "restore", "at": NOW}, NOW))
        fresh = {"action": "dismiss", "at": NOW - DAY}
        self.assertIs(composer.active_decision(fresh, NOW), fresh)
        self.assertIsNone(composer.active_decision({"action": "dismiss", "createdAt": NOW - composer.DISMISS_COOLDOWN}, NOW))   # service rows use createdAt
        for action in ("not_relevant", "save_idea", "accept"):
            row = {"action": action, "at": NOW - 300 * DAY}
            self.assertIs(composer.active_decision(row, NOW), row)                 # these never lapse on their own

    def test_a_lapsed_dismissal_offers_the_item_again(self):
        history = [{"id": "1", "source": "listening", "sourceRef": "a", "action": "dismiss", "at": NOW - 8 * DAY, "seq": 1}]
        self.assertEqual([i["sourceRef"] for i in composer.compose([candidate("a")], CONTEXT, history, NOW)["items"]], ["a"])

    def test_same_instant_actions_keep_their_recorded_order(self):
        rows = [{"id": "z", "source": "listening", "sourceRef": "a", "action": "dismiss", "at": NOW, "seq": 1},
                {"id": "a", "source": "listening", "sourceRef": "a", "action": "restore", "at": NOW, "seq": 2}]
        self.assertEqual(composer.latest_actions(rows)[("listening", "a")]["action"], "restore")
        self.assertEqual(composer.latest_actions(list(reversed(rows)))[("listening", "a")]["action"], "restore")


class ServiceFlagTest(unittest.TestCase):
    def test_each_service_exposes_enabled_with_the_flag_semantics(self):
        from postriff_phase2.briefs import service as brief_service
        from postriff_phase2.coworker import flags
        for value, expected in (("1", True), ("true", True), ("on", True), ("yes", True), ("0", False), ("", False), ("enabled", False)):
            self.assertIs(brief_service.enabled({"RAFII_OPPORTUNITY_BRIEF_ENABLED": value}), expected, value)
        self.assertFalse(brief_service.enabled({}))
        with mock.patch.object(flags, "_values", {"RAFII_OPPORTUNITY_BRIEF_ENABLED": "1"}):
            self.assertTrue(brief_service.enabled())                           # defaults to the environment the app attached
        with mock.patch.object(flags, "_values", None), mock.patch.dict("os.environ", {"RAFII_OPPORTUNITY_BRIEF_ENABLED": "1"}, clear=False):
            self.assertTrue(brief_service.enabled())                           # or the process environment itself


class DeliveryRulesTest(unittest.TestCase):
    def test_ac25_edition_window_is_the_local_iso_week(self):
        key, start, end = composer.edition_window(at("Asia/Hong_Kong", 2026, 10, 5, 0, 30), "Asia/Hong_Kong")
        self.assertEqual(key, "2026-W41")
        self.assertEqual(start, at("Asia/Hong_Kong", 2026, 10, 5, 0, 0))
        self.assertEqual(end - start, 7 * DAY)
        key_utc, *_ = composer.edition_window(at("Asia/Hong_Kong", 2026, 10, 5, 0, 30), "UTC")
        self.assertEqual(key_utc, "2026-W40")                   # still Sunday in UTC

    def test_ac25_dst_weeks_and_days_follow_the_wall_clock(self):
        zone = "America/New_York"
        _key, start, end = composer.edition_window(at(zone, 2026, 11, 1, 12, 0), zone)     # the week containing the fall-back Sunday
        self.assertEqual(end - start, 7 * DAY + 3600)
        day_start, day_end = composer.local_day(at(zone, 2026, 11, 1, 0, 30), zone)
        self.assertEqual(day_end - day_start, 25 * 3600)
        self.assertEqual(composer.local_day(at(zone, 2026, 11, 1, 23, 30), zone), (day_start, day_end))   # 24 h later, same local day
        spring_start, spring_end = composer.local_day(at(zone, 2027, 3, 14, 12, 0), zone)
        self.assertEqual(spring_end - spring_start, 23 * 3600)
        self.assertEqual(composer.zone("Not/AZone").key, "UTC")

    def test_ac25_weekly_cadence_daily_cap_and_new_material(self):
        decide = composer.delivery_decision
        self.assertEqual(decide(items=0, new_items=0, cadence="weekly", edition_delivered=False, delivered_today=False), "empty_edition")
        self.assertIsNone(decide(items=2, new_items=2, cadence="weekly", edition_delivered=False, delivered_today=False))
        self.assertEqual(decide(items=3, new_items=1, cadence="weekly", edition_delivered=True, delivered_today=False), "edition_already_delivered")
        self.assertEqual(decide(items=2, new_items=2, cadence="weekly", edition_delivered=False, delivered_today=True), "daily_cap")
        self.assertEqual(decide(items=2, new_items=0, cadence="daily", edition_delivered=True, delivered_today=False), "no_new_items")
        self.assertIsNone(decide(items=2, new_items=1, cadence="daily", edition_delivered=True, delivered_today=False))
        self.assertEqual(decide(items=2, new_items=1, cadence="daily", edition_delivered=True, delivered_today=True), "daily_cap")
        with self.assertRaises(ValueError):
            decide(items=1, new_items=1, cadence="hourly", edition_delivered=False, delivered_today=False)

    def test_notification_copy_follows_the_recipient_locale(self):
        self.assertEqual(composer.notification_copy("en-GB", 1)["title"], "1 opportunity to consider this week")
        self.assertEqual(composer.notification_copy("zh-Hant-HK", 3)["title"], "本週有 3 個值得考慮的機會")
        self.assertEqual(composer.copy_locale("yue"), "zh-Hant")
        self.assertEqual(composer.copy_locale(None), "en")
        self.assertNotIn("today", composer.notification_copy("en", 2)["why"].lower())


class SourcesTest(unittest.TestCase):
    def test_trend_pool_items_keep_receipt_angles_and_fit(self):
        envelope = {"data": [{"id": "11111111-1111-4111-8111-111111111111", "revision": 3, "title": "Practice streak challenge", "trust_receipt_id": "r-1",
                              "verification_state": "verified", "expires_at": "2026-10-12T00:00:00+00:00", "platform_targets": ["threads"],
                              "workspace_fit": {"audience": {"assessment": "supported"}, "risk": {"assessment": "low"}},
                              "angles": [{"id": "ang-1", "title": "Your own 7-day streak", "factual_requirements": []}], "uncertainty": "Fit is a hypothesis."}],
                    "coverage": {"latest_successful_read": "2026-10-06T10:00:00+00:00", "completeness": "complete_within_scope"}}
        [item] = sources.trend_candidates(envelope)
        self.assertEqual(item["action"], {"kind": "accept", "requires": ["angleId", "channelId"], "angleIds": ["ang-1"],
                                          "angles": [{"id": "ang-1", "text": "Your own 7-day streak"}], "revision": 3, "platforms": ["threads"]})
        self.assertEqual(item["evidence"][0]["ref"], "r-1")
        self.assertEqual(item["retrievedAt"], at("UTC", 2026, 10, 6, 10, 0))
        self.assertEqual(item["freshnessBasis"], "verified_unexpired_projection")
        brief = composer.compose([item], {"goals": [], "material": []}, [], NOW)["items"][0]
        self.assertEqual(brief["effort"], "quick")
        self.assertEqual(brief["action"]["angles"], item["action"]["angles"])

    def test_every_trend_angle_option_carries_its_own_words(self):
        """The accept form offers up to three angles; each comes with text (title, else its contribution), aligned with
        angleIds, so no option is a bare id. Angle text never enters the material digest."""
        angles = [{"id": "ang-1", "title": "Your own 7-day streak"}, {"id": "ang-2", "contribution": "  A  student's\nfirst month  "},
                  {"id": "ang-3"}, {"id": "ang-4", "title": "A fourth angle"}, {"title": "no id"}]
        envelope = {"data": [{"id": "22222222-2222-4222-8222-222222222222", "revision": 1, "title": "Streaks", "contribution": "Show the routine",
                              "verification_state": "verified", "angles": angles}], "coverage": {}}
        [item] = sources.trend_candidates(envelope)
        self.assertEqual(item["action"]["angleIds"], ["ang-1", "ang-2", "ang-3"])
        self.assertEqual(item["action"]["angles"], [{"id": "ang-1", "text": "Your own 7-day streak"}, {"id": "ang-2", "text": "A student's first month"},
                                                    {"id": "ang-3", "text": "Show the routine"}])
        [renamed] = sources.trend_candidates({**envelope, "data": [{**envelope["data"][0], "angles": [{**angles[0], "title": "Renamed"}] + angles[1:]}]})
        self.assertNotEqual(renamed["action"]["angles"][0]["text"], item["action"]["angles"][0]["text"])
        self.assertEqual(composer.material_digest([{**item, "effort": "quick"}]), composer.material_digest([{**renamed, "effort": "quick"}]))

    def test_listening_reads_open_stored_opportunities_only(self):
        state = {"coworker": {"listening": {"watchlists": [{"id": "wl1", "query": "adult piano", "goal": "students"}], "opportunities": [
            {"id": "op1", "watchlistId": "wl1", "title": "Why do adults quit piano?", "url": "https://news.example/a", "status": "open", "confidence": "high",
             "createdAt": NOW - DAY, "expiresAt": NOW + 9 * DAY, "evidence": [{"url": "https://news.example/a", "snippet": "long text " * 50,
                                                                             "provenance": {"retrievedAt": NOW - DAY, "publishedAt": "2026-10-05", "injectionFlags": []}}]},
            {"id": "op2", "watchlistId": "wl1", "title": "Dismissed", "status": "dismissed", "createdAt": NOW, "expiresAt": NOW + DAY, "evidence": []}]}}}
        items, cov = sources.listening_candidates(state, True)
        self.assertEqual([i["sourceRef"] for i in items], ["op1"])
        self.assertEqual(items[0]["kind"], "question")
        self.assertIsNone(items[0]["excerpt"])                  # search snippets are not copied into the brief
        self.assertEqual(items[0]["evidence"][0]["label"], "news.example")
        self.assertEqual(items[0]["publishedAt"], at("UTC", 2026, 10, 5))
        self.assertEqual(cov["state"], "available")
        self.assertEqual(sources.listening_candidates(state, False)[1]["reason"], "listening_not_enabled")

    def test_radar_reads_current_stored_scans_and_skips_stale_consent(self):
        from postriff_phase2.radar.service import Radar
        state = {"radarConsent": {"sources": ["news"]}}
        current = Radar.context(state)
        body = {"query": "piano practice", "finishedAt": NOW - DAY, "notice": "Signals for your review.",
                "opportunities": [{"id": "o1", "title": "New practice research", "eligible": True, "evidenceIds": ["e1"], "angle": "What changes for you?",
                                   "expiresAt": NOW + 9 * DAY, "evidence": [{"url": "https://site.example/x", "source": "news", "publishedAt": NOW - 2 * DAY,
                                                                              "retrievedAt": NOW - DAY, "excerpt": "kept", "rights": {"displayExcerpt": True}}]},
                                  {"id": "o2", "title": "Ineligible", "eligible": False, "evidence": [], "expiresAt": NOW + DAY}]}

        class Cursor:
            def __init__(self, rows): self.rows, self.sql = rows, []
            def execute(self, sql, params=None): self.sql.append(sql)
            def fetchall(self): return self.rows
        rows = [("run-1", current, body, NOW - DAY), ("run-0", "old-context", body, NOW - 2 * DAY)]
        items, cov = sources.radar_candidates(Cursor(rows), "w1", state, NOW, {"POSTRIFF_GROWTH": "1", "POSTRIFF_RADAR": "1"})
        self.assertEqual([i["sourceRef"] for i in items], ["run-1:o1"])
        self.assertEqual(items[0]["action"], {"kind": "save_idea", "via": "radar", "scanId": "run-1", "opportunityId": "o1"})
        self.assertEqual(items[0]["excerpt"], "kept")
        self.assertEqual(cov["staleScans"], 1)
        cursor = Cursor(rows)
        self.assertEqual(sources.radar_candidates(cursor, "w1", state, NOW, {})[1]["reason"], "radar_not_enabled")
        self.assertEqual(cursor.sql, [])                         # a disabled source is not even read

    def test_trend_reader_never_calls_the_trend_service_when_disabled_and_reports_errors(self):
        hosted = types.SimpleNamespace()
        with mock.patch.object(sources, "trends_allowed", return_value=False):
            self.assertEqual(sources.read_trends(hosted, "w", "t"), ([], {"source": "trends", "state": "unavailable", "reason": "trends_not_enabled", "considered": 0}))
        failing = types.SimpleNamespace(trends=types.SimpleNamespace(list=mock.Mock(side_effect=AlphaError("no", 403))))
        with mock.patch.object(sources, "trends_allowed", return_value=True), mock.patch("postriff_phase2.coworker.runtime.ensure", return_value=types.SimpleNamespace(coworker=failing)):
            self.assertEqual(sources.read_trends(hosted, "w", "t")[1]["reason"], "trends_not_permitted")
        working = types.SimpleNamespace(trends=types.SimpleNamespace(list=mock.Mock(return_value={"data": [], "coverage": {}})))
        with mock.patch.object(sources, "trends_allowed", return_value=True), mock.patch("postriff_phase2.coworker.runtime.ensure", return_value=types.SimpleNamespace(coworker=working)):
            self.assertEqual(sources.read_trends(hosted, "w", "t")[1]["state"], "empty")
        working.trends.list.assert_called_once_with("w", "t", {"pool": "weekly"}, kind="opportunity")

    def test_templated_angles_stay_distinct_per_item(self):
        state = {"coworker": {"listening": {"watchlists": [{"id": "wl1", "query": "adult piano"}], "opportunities": [
            {"id": f"op{i}", "watchlistId": "wl1", "title": title, "status": "open", "confidence": "high", "createdAt": NOW - DAY, "expiresAt": NOW + 9 * DAY,
             "evidence": [{"url": f"https://a.example/{i}", "provenance": {"retrievedAt": NOW - DAY}}]} for i, title in enumerate(("Practice journals", "Teaching scales"))]}}}
        items, _ = sources.listening_candidates(state, True)
        chosen = composer.compose(items, CONTEXT, [], NOW)["items"]
        self.assertEqual(len(chosen), 2)
        self.assertNotEqual(chosen[0]["angle"]["text"], chosen[1]["angle"]["text"])
        from postriff_phase2.radar import core
        self.assertIn(sources.RADAR_GENERIC_ANGLE, str(core.opportunities.__code__.co_consts))   # the placeholder radar writes

    def test_context_uses_goals_material_and_planned_angles(self):
        state = {"coworker": {"growthLoop": {"goals": [{"id": "g1", "name": "Fill autumn classes", "status": "active"}]},
                              "weekly": {"recipes": [{"status": "active", "goals": ["Teach practice habits"]}],
                                         "weeks": [{"slots": [{"angle": "Teach practice habits — tutorial how to"}]}]}},
                 "sources": [{"id": "s1", "active": True, "kind": "text", "title": "Studio handbook"}, {"id": "s2", "active": False, "title": "Old"},
                             {"id": "s3", "active": True, "kind": "voice_sample", "title": "Voice"}]}
        context = sources.context(state)
        self.assertEqual(context["goals"], ["Fill autumn classes", "Teach practice habits"])
        self.assertEqual(context["material"], [{"id": "s1", "title": "Studio handbook"}])
        self.assertEqual(context["recentAngles"], ["Teach practice habits — tutorial how to"])
        self.assertEqual(context["goalId"], "g1")


if __name__ == "__main__":
    unittest.main()
