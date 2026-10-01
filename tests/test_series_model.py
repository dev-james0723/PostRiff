"""Signature Series pure logic (PRD R-SER-01/02): text normalisation, CJK-aware sentences and similarity, claim review
dates, freshness states, the deterministic episode planner, and the review-set series/freshness cases.

    PYTHONPATH=src:tests python -m unittest tests.test_series_model
"""
import copy
import datetime as dt
import unittest

from postriff_phase2.series import commands, model as m
from series_fixtures import DAY, NOW, Flags, case, post, source, variant, workspace


def create(state, origin, **extra):
    payload = {"origin": origin, "audienceQuestion": extra.pop("question", "What should beginners know?"), "goal": "A short series", **extra}
    return commands.create(state, payload, "owner-1", NOW)


class TextTest(unittest.TestCase):
    def test_normalised_digest_ignores_case_spacing_punctuation_and_width(self):
        self.assertEqual(m.text_digest("Hello, World!  "), m.text_digest("hello world"))
        self.assertEqual(m.text_digest("早鳥優惠，即將結束。"), m.text_digest("早鳥優惠 即將結束"))
        self.assertEqual(m.text_digest("ＡＢＣ１２３"), m.text_digest("abc123"))   # NFKC: full-width is the same text
        self.assertNotEqual(m.text_digest("2,800"), m.text_digest("3,000"))

    def test_similarity_is_character_trigram_and_cjk_safe(self):
        zh = "孩子幾歲開始學鋼琴最好？看專注力，不是看年齡。"
        self.assertGreaterEqual(m.similarity(zh, zh.replace("鋼琴", "琴")), m.SIMILAR)
        self.assertLess(m.similarity(zh, "週六下午有兩小時的手捏體驗課"), m.SIMILAR)
        self.assertIsNone(m.similarity("", "anything"))

    def test_sentences_split_cjk_without_spaces_and_keep_decimals(self):
        zh = case("zh-hant-series-question")["source"]
        self.assertEqual(m.sentences(zh), ["很多人問：「孩子幾歲開始學鋼琴最好？」", "我的答案是看專注力，不是看年齡。", "五分鐘能專心聽完一首短曲，就可以開始。"])
        self.assertEqual(m.sentences("Price is US$1.99 today. Ends soon."), ["Price is US$1.99 today.", "Ends soon."])

    def test_full_dates_in_several_writings(self):
        self.assertEqual(m.dates_in(case("expired-fact")["source"]), [dt.date(2026, 9, 15)])
        self.assertEqual(m.dates_in("截止日期 2026年9月15日"), [dt.date(2026, 9, 15)])
        self.assertEqual(m.dates_in("on 2026-09-15 and 3 Oct 2026, not 2026-13-40"), [dt.date(2026, 9, 15), dt.date(2026, 10, 3)])
        self.assertEqual(m.dates_in("Founded in 2019"), [])

    def test_instruction_like_text_is_dropped_as_data(self):
        found = m.analyze(case("adversarial-ignore-instructions")["source"])
        self.assertGreaterEqual(found["injectionFlags"], 2)
        self.assertFalse(any("Ignore all previous" in c for c in found["claims"]))


class ReviewDateTest(unittest.TestCase):
    def test_default_review_date_is_the_fact_pack_window_capped_at_a_year(self):
        base = dt.date(2026, 1, 10)
        self.assertEqual(m.default_review_by("We teach adults.", "statement", base), "2027-01-10")      # 3650 days → one year
        self.assertEqual(m.default_review_by("Breaking: new rules.", "news", base), "2026-01-24")        # 14 days

    def test_a_deadline_named_in_the_claim_is_its_review_date(self):
        text = case("expired-fact")["source"]
        self.assertEqual(m.default_review_by(text, m.claim_type(text), dt.date(2026, 8, 1)), "2026-09-15")
        # A date before the post was published is history, not a deadline.
        self.assertEqual(m.default_review_by("We opened on March 3, 2020.", "event", dt.date(2026, 8, 1)), "2026-09-30")


class FreshnessTest(unittest.TestCase):
    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True).__enter__()
        self.state = workspace()

    def tearDown(self):
        self.flags.__exit__()

    def test_review_set_expired_fact_needs_fact_review_with_reason_claim_expired(self):
        fixture = case("expired-fact")
        self.state["phase2"]["jobs"].append(post("old", fixture["source"], 60))
        campaign = create(self.state, {"kind": "post", "id": "old"}, question=fixture["audience"], reviewBy=fixture["reviewBy"])
        series = campaign["series"]
        self.assertEqual([c["reviewBy"] for c in series["claims"]], ["2026-09-15"])
        today = m._day(NOW)
        episode = series["episodes"][0]
        self.assertEqual(m.fact_state(self.state, series, episode, today), fixture["expected"]["state"])
        self.assertEqual([m.REASON_CODES[s] for _, s, _ in m.episode_issues(self.state, series, episode, today)], [fixture["expected"]["reason"]])
        # The same post without the explicit date still expires on the day the claim itself names.
        other = workspace("w2")
        other["phase2"]["jobs"].append(post("old", fixture["source"], 60))
        self.assertEqual(create(other, {"kind": "post", "id": "old"})["series"]["claims"][0]["reviewBy"], "2026-09-15")

    def test_withdrawn_deleted_changed_and_unapproved_support(self):
        self.state["sources"].append(source("s1", "Classes run on Saturdays.\nEach class has six seats."))
        campaign = create(self.state, {"kind": "source", "id": "s1"})
        series, today = campaign["series"], m._day(NOW)
        claim = series["claims"][0]
        self.assertEqual(m.claim_state(self.state, claim, today), ("ok", None))
        src = self.state["sources"][0]
        src["facts"][1]["approved"] = False      # re-approval with different facts: a new source version
        self.assertEqual(m.claim_state(self.state, claim, today)[0], "source_changed")
        self.assertEqual(m.claim_state(self.state, series["claims"][1], today)[0], "missing_support")
        src["active"] = False
        self.assertEqual(m.claim_state(self.state, claim, today), ("source_unavailable", "withdrawn"))
        self.state["sources"].clear()
        self.assertEqual(m.claim_state(self.state, claim, today), ("source_unavailable", "deleted"))
        claim["status"] = "removed"
        self.assertEqual(m.claim_state(self.state, claim, today), ("removed", None))


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True).__enter__()

    def tearDown(self):
        self.flags.__exit__()

    def test_review_set_series_cases_give_their_distinct_roles(self):
        for case_id, language in (("en-series-evergreen", "en"), ("zh-hant-series-question", "zh-Hant")):
            fixture = case(case_id)
            with self.subTest(case_id):
                state = workspace()
                state["phase2"]["jobs"].append(post("p", fixture["source"], 45, language=language))
                series = create(state, {"kind": "post", "id": "p"}, question=fixture["audience"])["series"]
                roles = [e["role"] for e in series["episodes"]]
                self.assertTrue(set(fixture["expected"]["distinctRoles"]) <= set(roles), roles)
                self.assertEqual(len(roles), m.DEFAULT_PLAN)
                self.assertEqual(len({e["angle"]["key"] for e in series["episodes"]}), len(roles))
                self.assertEqual(series["language"], language)
        en = workspace()
        en["phase2"]["jobs"].append(post("p", case("en-series-evergreen")["source"], 45))
        self.assertEqual([e["role"] for e in create(en, {"kind": "post", "id": "p"})["series"]["episodes"]], ["explanation", "worked_example", "faq"])

    def test_plan_is_bounded_two_to_six_and_never_repeats_an_angle(self):
        state = workspace()
        state["phase2"]["jobs"].append(post("p", case("en-series-evergreen")["source"], 45))
        for bad in (1, 7, "3"):
            with self.subTest(bad), self.assertRaises(Exception):
                create(copy.deepcopy(state), {"kind": "post", "id": "p"}, episodeCount=bad)
        campaign = create(state, {"kind": "post", "id": "p"}, episodeCount=6)
        episodes = campaign["series"]["episodes"]
        self.assertLessEqual(len(episodes), 6)
        self.assertEqual(len({e["angle"]["key"] for e in episodes}), len(episodes))
        self.assertEqual(m.plan(state, campaign, 6, NOW), [])   # six already wait: no indefinite queue

    def test_original_must_be_old_enough_verified_and_from_this_workspace(self):
        state = workspace()
        state["phase2"]["jobs"] += [post("new", "Fresh post about practice routines.", 3), {**post("draft", "Not published yet.", 90), "state": "approved"}]
        with self.assertRaises(Exception) as too_new:
            create(state, {"kind": "post", "id": "new"})
        self.assertEqual((too_new.exception.status, too_new.exception.code), (409, "unsupported_input"))
        self.assertIn("30 days ago", str(too_new.exception))
        for missing in ("draft", "elsewhere"):
            with self.subTest(missing), self.assertRaises(Exception) as caught:
                create(state, {"kind": "post", "id": missing})
            self.assertEqual(caught.exception.status, 404)

    def test_drafts_link_lineage_and_translations_attach_to_the_same_episode(self):
        state = workspace()
        state["phase2"]["jobs"].append(post("p", case("en-series-evergreen")["source"], 45))
        campaign = create(state, {"kind": "post", "id": "p"})
        episode = campaign["series"]["episodes"][0]
        commands.approve(state, campaign, episode["id"], "owner-1", NOW)
        state["variants"] += [variant("en1", "Why five focused minutes beat a whole piece."), variant("zh1", "為甚麼專注五分鐘勝過彈完整首曲子。", language="zh-Hant")]
        for variant_id in ("en1", "zh1"):
            commands.link_draft(state, campaign, episode["id"], {"variantId": variant_id, "acknowledgedWarnings": []}, "owner-1", NOW)
        self.assertEqual([r["variantId"] for r in episode["draftRefs"]], ["en1", "zh1"])
        self.assertEqual(len([e for e in campaign["series"]["episodes"] if e["state"] != "skipped"]), 3)   # still three episodes
        lineage = state["variants"][-1]["seriesEpisode"]
        self.assertEqual((lineage["originKind"], lineage["originId"], lineage["episodeId"]), ("post", "p", episode["id"]))


if __name__ == "__main__":
    unittest.main()
