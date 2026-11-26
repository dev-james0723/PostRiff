"""Deterministic classification of imported posts (spec 5.2; IMP-4, IMP-5, IMP-6). Every text here is synthetic."""
import unittest

from postriff_phase2 import voice_evidence as E

MINE = {"version": "voice-import.v1", "ownership": "mine", "voiceScope": "brand", "retainText": True}
LONG = "We moved the launch to Friday so the beta group gets one more week to test."


class LanguageTests(unittest.TestCase):
    def test_the_six_tags(self):
        cases = {
            "We ship on Friday.": "en",
            "我哋今晚八點開場，記得嚟呀！": "yue",
            "我們將於星期五推出新功能。": "zh-Hant",
            "我们将于星期五推出新功能。": "zh-Hans",
            "今晚 show 好正，thank you 大家！": "mixed",
            "🎹🎹": "und",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(E.detect_language(text), expected)

    def test_nothing_to_read_is_undetermined(self):
        for text in ("", None, "   ", "https://example.com/a #launch @someone", "12:30 — 14:00", 42):
            with self.subTest(text=text):
                self.assertEqual(E.detect_language(text), "und")

    def test_links_handles_and_hashtags_do_not_decide_the_language(self):
        # English hashtags under a Chinese caption are not code-switching.
        self.assertEqual(E.detect_language("我們下星期開始新一季的課程。 #piano #music #newseason https://example.com/x"), "zh-Hant")
        self.assertEqual(E.detect_language("今日用 Notion 整理了下星期的工作清單，感覺輕鬆了很多。"), "zh-Hant")

    def test_cantonese_needs_a_real_marker(self):
        self.assertEqual(E.detect_language("今日終於搞掂晒啲嘢，可以早啲收工。"), "yue")
        # 好正 inside 好正常, 琴日 inside 鋼琴日記, 聽日 inside 聽日本歌: one weak hit is not written Cantonese.
        for text in ("這個價錢好正常，大家可以放心。", "我的鋼琴日記更新了，歡迎大家來看。", "我最近很喜歡聽日本歌，特別是鋼琴曲。"):
            with self.subTest(text=text):
                self.assertEqual(E.detect_language(text), "zh-Hant")
        self.assertEqual(E.detect_language("客戶關係管理是我們今年的重點。"), "zh-Hant")   # 關係 is not the marker 係

    def test_script_is_decided_by_characters_that_differ(self):
        self.assertEqual(E.detect_language("今晚八點鐘在大會堂見面。"), "zh-Hant")
        self.assertEqual(E.detect_language("今晚八点钟在大会堂见面。"), "zh-Hans")
        # No character differs between the scripts: reported as Traditional, the documented default.
        self.assertEqual(E.detect_language("你好，大家好。"), "zh-Hant")

    def test_other_languages_are_not_called_english_or_chinese(self):
        for text in ("今日はいい天気ですね。散歩に行きましょう。", "오늘 저녁 여덟 시에 공연을 시작합니다.", "Сегодня вечером мы открываем новый сезон.",
                     "Bonjour à tous, nous sommes très heureux de vous retrouver.", "Hoy es un gran día para el equipo y para la ciudad."):
            with self.subTest(text=text):
                self.assertEqual(E.detect_language(text), "und")

    def test_short_english_without_function_words_is_still_english(self):
        for text in ("Shipped.", "Friday release!", "New video out now"):
            with self.subTest(text=text):
                self.assertEqual(E.detect_language(text), "en")

    def test_mixed_needs_real_code_switching(self):
        self.assertEqual(E.detect_language("Thank you 大家支持！新 video 出咗"), "mixed")
        self.assertEqual(E.detect_language("We ship on Friday and the whole team is ready for it. 多謝！"), "en")


class NormaliseTests(unittest.TestCase):
    def test_hash_ignores_case_spacing_trailing_tags_mentions_and_links(self):
        first = "We ship on  Friday.\n\nJoin us!  https://example.com/a @Team_One #launch #News"
        second = "we SHIP on friday. join us! https://other.example/b?x=1 #shipping"
        self.assertEqual(E.normalise(first), "we ship on friday. join us!")
        self.assertEqual(E.norm_hash(first), E.norm_hash(second))
        self.assertNotEqual(E.norm_hash(first), E.norm_hash("We ship on Monday. Join us!"))
        self.assertRegex(E.norm_hash(first), r"^[0-9a-f]{64}$")

    def test_inline_hashtags_keep_their_word_and_email_addresses_stay(self):
        self.assertEqual(E.normalise("I love #piano and #music lessons"), "i love piano and music lessons")
        self.assertEqual(E.normalise("Write to hello@example.com today"), "write to hello@example.com today")
        self.assertEqual(E.normalise("Thanks @someone@social.example for the idea"), "thanks for the idea")

    def test_layout_lines_between_a_caption_and_its_hashtags_are_not_wording(self):
        caption = "We ship on Friday. Join us!\n.\n.\n🎉🎉\n#launch #news\n.\n"
        self.assertEqual(E.normalise(caption), "we ship on friday. join us!")
        self.assertEqual(E.norm_hash(caption), E.norm_hash("We ship on Friday.\nJoin us!"))
        self.assertEqual(E.normalise("🎹🎹\n...\n—"), "")

    def test_width_and_chinese_tags(self):
        self.assertEqual(E.normalise("Ｈｅｌｌｏ　ｗｏｒｌｄ"), "hello world")
        self.assertEqual(E.normalise("今晚八點開場 #音樂會 #香港"), "今晚八點開場")
        self.assertEqual(E.normalise(None), "")

    def test_body_hash_is_exact(self):
        self.assertNotEqual(E.body_hash("We ship on Friday."), E.body_hash("we ship on friday."))
        self.assertRegex(E.body_hash("x"), r"^[0-9a-f]{64}$")


class ClassifyTests(unittest.TestCase):
    def classify(self, item=None, consent=MINE, journal=frozenset()):
        return E.classify({"externalId": "p1", "text": LONG, "kind": "original", **(item or {})}, consent=consent, journal=set(journal))

    def test_shape_and_an_eligible_post(self):
        result = self.classify({"contentType": "image"})
        self.assertEqual(set(result), {"language", "originality", "authorship", "generation_origin", "status", "exclusion_reason",
                                       "body_hash", "norm_hash", "content_type"})
        self.assertEqual((result["language"], result["originality"], result["authorship"], result["generation_origin"]),
                         ("en", "original", "self", "unknown"))
        self.assertEqual((result["status"], result["exclusion_reason"], result["content_type"]), ("eligible", None, "image"))
        self.assertEqual((result["body_hash"], result["norm_hash"]), (E.body_hash(LONG), E.norm_hash(LONG)))

    def test_repost_is_excluded(self):
        result = self.classify({"kind": "repost"})
        self.assertEqual((result["originality"], result["status"], result["exclusion_reason"]), ("repost", "excluded", "repost"))

    def test_a_post_rafii_published_is_marked_and_excluded(self):
        result = self.classify({"connectionId": "conn-1"}, journal={("conn-1", "p1")})
        self.assertEqual((result["generation_origin"], result["status"], result["exclusion_reason"]),
                         ("rafii_published", "excluded", "rafii_published"))
        # Another connection's id, or another post, is not a match.
        self.assertEqual(self.classify({"connectionId": "conn-2"}, journal={("conn-1", "p1")})["generation_origin"], "unknown")
        self.assertEqual(self.classify({"connectionId": "conn-1", "externalId": "p2"}, journal={("conn-1", "p1")})["status"], "eligible")

    def test_authorship_follows_the_consent_and_unknown_waits(self):
        mixed = self.classify(consent={**MINE, "ownership": "mixed_authors"})
        self.assertEqual((mixed["authorship"], mixed["status"], mixed["exclusion_reason"]), ("unknown", "retrieved", None))
        mine = self.classify(consent={**MINE, "ownership": "mine"})
        self.assertEqual((mine["authorship"], mine["status"]), ("self", "eligible"))
        team = self.classify(consent={**MINE, "ownership": "my_organisation"})
        self.assertEqual((team["authorship"], team["status"]), ("team", "eligible"))
        # No ownership on record is never read as the person's own writing.
        self.assertEqual(self.classify(consent={})["authorship"], "unknown")

    def test_text_under_twenty_characters_after_normalising_is_too_short(self):
        for text in ("Out now!", "Thanks all #launch #news #friday #team #music", "我哋今晚八點開場，記得嚟呀！"):
            with self.subTest(text=text):
                result = self.classify({"text": text})
                self.assertEqual((result["status"], result["exclusion_reason"]), ("excluded", "too_short"))
        self.assertEqual(self.classify({"text": "x" * 20})["status"], "eligible")
        self.assertEqual(E.MIN_CHARS, 20)

    def test_replies_and_quotes_are_the_persons_own_words(self):
        for kind in ("reply", "quote"):
            result = self.classify({"kind": kind})
            self.assertEqual((result["originality"], result["status"]), (kind, "eligible"))
        for kind in (None, "retweet", 7):
            self.assertEqual(self.classify({"kind": kind})["originality"], "unknown")
        self.assertEqual(self.classify({"kind": None})["status"], "eligible")

    def test_one_reason_per_post_in_a_fixed_order(self):
        both = self.classify({"kind": "repost", "text": "Out now!", "connectionId": "c"}, journal={("c", "p1")})
        self.assertEqual(both["exclusion_reason"], "repost")
        published = self.classify({"text": "Out now!", "connectionId": "c"}, journal={("c", "p1")})
        self.assertEqual(published["exclusion_reason"], "rafii_published")
        pending = self.classify({"text": "Out now!"}, consent={**MINE, "ownership": "mixed_authors"})
        self.assertEqual((pending["status"], pending["exclusion_reason"]), ("excluded", "too_short"))

    def test_content_type_is_a_short_slug(self):
        self.assertEqual(self.classify()["content_type"], "post")
        self.assertEqual(self.classify({"contentType": "Carousel"})["content_type"], "carousel")
        for junk in ("", "x" * 60, "two words", None, 3):
            self.assertEqual(self.classify({"contentType": junk})["content_type"], "post")


class JournalTests(unittest.TestCase):
    STATE = {"phase2": {"jobs": [
        {"id": "j1", "providerReference": "111", "manifest": {"platform": "Threads", "channelId": "conn-threads", "payload": {"text": LONG + " #launch"}}},
        {"id": "j2", "providerReference": 222, "manifest": {"platform": "Mastodon", "channelId": "conn-masto", "payload": {"text": "Short."}}},
        {"id": "j3", "providerReference": None, "manifest": {"platform": "X", "channelId": "conn-x", "payload": {"text": "Never published, so never a match here."}}},
        "junk", {"id": "j4", "providerReference": "444"}]}}

    def test_keys_from_the_publish_journal(self):
        journal = E.journal(self.STATE)
        self.assertIn(("conn-threads", "111"), journal)
        self.assertIn(("conn-masto", "222"), journal)
        self.assertIn(("provider:threads", "111"), journal)          # an export row has no connection id
        self.assertNotIn(("provider:mastodon", "222"), journal)      # Mastodon ids repeat across servers
        self.assertIn(("#text", E.norm_hash(LONG)), journal)
        self.assertNotIn(("#text", E.norm_hash("Short.")), journal)  # too short to identify a post
        self.assertFalse(any(key[0] == "conn-x" or key[1] == "444" for key in journal))
        self.assertEqual(E.journal({}), set())
        self.assertEqual(E.journal({"phase2": {"jobs": "junk"}}), set())

    def test_a_bluesky_post_is_known_by_its_record_key(self):
        address = "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.post/3lrafii00001a"
        journal = E.journal({"phase2": {"jobs": [{"providerReference": address, "manifest": {"platform": "Bluesky", "channelId": "conn-bsky"}}]}})
        self.assertEqual(journal, {("conn-bsky", address), ("conn-bsky", "3lrafii00001a")})
        found = E.classify({"externalId": "3lrafii00001a", "text": LONG, "connectionId": "conn-bsky", "provider": "bluesky"}, consent=MINE, journal=journal)
        self.assertEqual(found["generation_origin"], "rafii_published")
        # Record keys repeat across accounts, so another connection's post with the same key is not Rafii's.
        elsewhere = E.classify({"externalId": "3lrafii00001a", "text": LONG, "connectionId": "conn-other", "provider": "bluesky"}, consent=MINE, journal=journal)
        self.assertEqual(elsewhere["generation_origin"], "unknown")

    def test_an_export_copy_is_recognised_by_provider_id_or_by_text(self):
        journal = E.journal(self.STATE)
        by_id = E.classify({"externalId": "111", "text": "A different caption that is long enough.", "provider": "threads"}, consent=MINE, journal=journal)
        self.assertEqual(by_id["generation_origin"], "rafii_published")
        by_text = E.classify({"externalId": "export-9", "text": LONG.upper() + "  https://example.com/x", "provider": "instagram"}, consent=MINE, journal=journal)
        self.assertEqual((by_text["generation_origin"], by_text["exclusion_reason"]), ("rafii_published", "rafii_published"))
        other = E.classify({"externalId": "export-10", "text": "Our own words about the autumn timetable.", "provider": "instagram"}, consent=MINE, journal=journal)
        self.assertEqual(other["generation_origin"], "unknown")


class StatusTests(unittest.TestCase):
    def resolve(self, **facts):
        base = {"originality": "original", "generation_origin": "unknown", "authorship": "self", "label": None,
                "manual": False, "too_short": False, "duplicate": False}
        return E.resolve_status(**{**base, **facts})

    def test_every_reason(self):
        self.assertEqual(self.resolve(), ("eligible", None))
        self.assertEqual(self.resolve(authorship="team", label="representative"), ("eligible", None))
        self.assertEqual(self.resolve(label="aspirational"), ("eligible", None))
        self.assertEqual(self.resolve(authorship="unknown"), ("retrieved", None))
        for facts, reason in (({"originality": "repost"}, "repost"), ({"generation_origin": "rafii_published"}, "rafii_published"),
                              ({"manual": True}, "manual"), ({"authorship": "guest"}, "other_author"), ({"label": "outdated"}, "outdated"),
                              ({"too_short": True}, "too_short"), ({"duplicate": True}, "duplicate")):
            with self.subTest(reason=reason):
                self.assertEqual(self.resolve(**facts), ("excluded", reason))
                self.assertIn(reason, E.EXCLUSIONS)

    def test_order(self):
        self.assertEqual(self.resolve(originality="repost", generation_origin="rafii_published", duplicate=True)[1], "repost")
        self.assertEqual(self.resolve(manual=True, authorship="guest", too_short=True)[1], "manual")
        self.assertEqual(self.resolve(authorship="guest", label="outdated")[1], "other_author")
        self.assertEqual(self.resolve(too_short=True, duplicate=True)[1], "too_short")
        self.assertEqual(self.resolve(duplicate=True, authorship="unknown"), ("excluded", "duplicate"))


class GroupTests(unittest.TestCase):
    def test_group_keys(self):
        self.assertEqual(E.group_key("brand", "threads", "123"), "brand")
        self.assertEqual(E.group_key("separate", "threads", "123"), "separate:threads:123")
        self.assertEqual(E.parse_group_key(None), ("brand", None, None))
        self.assertEqual(E.parse_group_key("brand"), ("brand", None, None))
        self.assertEqual(E.parse_group_key("separate:mastodon:109@social.example.org"), ("separate", "mastodon", "109@social.example.org"))
        for junk in ("", "separate:", "separate:threads", "other", 5):
            with self.subTest(junk=junk):
                self.assertIsNone(E.parse_group_key(junk))

    def test_one_brand_group_plus_one_per_separate_account(self):
        rows = [("threads", "t1", "brand", 12), ("instagram", "i1", "brand", 3), ("mastodon", "m1@social.example.org", "separate", 7)]
        labels = {("threads", "t1"): "@studio", ("mastodon", "m1@social.example.org"): "@founder"}
        groups = E.fold_groups(rows, labels)
        self.assertEqual([g["key"] for g in groups], ["brand", "separate:mastodon:m1@social.example.org"])
        self.assertEqual(groups[0]["eligible"], 15)
        self.assertEqual(groups[0]["accounts"], [{"provider": "instagram", "accountKey": "i1", "label": "i1"},
                                                 {"provider": "threads", "accountKey": "t1", "label": "@studio"}])
        self.assertEqual((groups[1]["label"], groups[1]["eligible"]), ("@founder", 7))
        self.assertEqual(set(groups[0]), {"key", "label", "accounts", "eligible"})
        # The brand group exists even with nothing in it.
        self.assertEqual(E.fold_groups([], {}), [{"key": "brand", "label": "Brand voice", "accounts": [], "eligible": 0}])


class CoverageTests(unittest.TestCase):
    """fold_coverage takes the two aggregate queries' rows; `coverage` runs them (PostgreSQL suite)."""
    POSTS = [  # provider, account_key, voice_scope, status, exclusion_reason, language, count, oldest, newest
        ("threads", "t1", "brand", "eligible", None, "en", 30, "2026-01-02T00:00:00+00:00", "2026-10-01T00:00:00+00:00"),
        ("threads", "t1", "brand", "eligible", None, "yue", 10, "2025-06-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        ("threads", "t1", "brand", "retrieved", None, "en", 2, None, None),
        ("threads", "t1", "brand", "excluded", "repost", "und", 4, "2026-02-01T00:00:00+00:00", "2026-02-03T00:00:00+00:00"),
        ("threads", "t1", "brand", "excluded", "duplicate", "en", 3, None, None),
        ("threads", "t1", "brand", "excluded", "manual", "en", 1, None, None),
        ("x", "export", "separate", "eligible", None, "en", 5, "2024-01-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
    ]
    IMPORTS = [  # provider, account_key, label, route, status, more_remaining, total_known, voice_scope
        ("threads", "t1", "@studio", "official_api", "done", False, False, "brand"),
        ("x", "export", "X export", "platform_export", "done", False, True, "separate"),
        ("mastodon", "m1@social.example.org", "@founder", "official_api", "running", None, False, "brand"),
    ]

    def test_shape_counts_and_ranges(self):
        cover = E.fold_coverage(self.POSTS, self.IMPORTS, {})
        self.assertEqual(set(cover), {"states", "accounts", "modality"})
        self.assertEqual(cover["modality"], {"text": "analysed", "images": "not_analysed", "video": "not_analysed"})
        self.assertEqual([(a["provider"], a["accountKey"]) for a in cover["accounts"]],
                         [("mastodon", "m1@social.example.org"), ("threads", "t1"), ("x", "export")])
        threads = cover["accounts"][1]
        self.assertEqual(set(threads), {"provider", "accountKey", "label", "route", "voiceScope", "retrieved", "eligible", "excluded",
                                        "languages", "observed", "moreRemaining", "totalKnown"})
        self.assertEqual((threads["label"], threads["route"], threads["voiceScope"]), ("@studio", "official_api", "brand"))
        self.assertEqual((threads["retrieved"], threads["eligible"]), (50, 40))
        self.assertEqual(threads["excluded"], {"repost": 4, "duplicate": 3, "rafii_published": 0, "too_short": 0, "other_author": 0, "outdated": 0, "manual": 1})
        # Languages describe the writing still in play (eligible or waiting for an author), not reposts.
        self.assertEqual(threads["languages"], {"en": 32, "yue": 10})
        self.assertEqual(threads["observed"], {"oldest": "2025-06-01T00:00:00+00:00", "newest": "2026-10-01T00:00:00+00:00"})
        self.assertEqual((threads["moreRemaining"], threads["totalKnown"]), (False, False))
        # retrieved − eligible − excluded = posts waiting for an author.
        self.assertEqual(threads["retrieved"] - threads["eligible"] - sum(threads["excluded"].values()), 2)

    def test_an_account_with_a_run_and_no_posts_yet_and_an_unknown_remainder(self):
        waiting = E.fold_coverage(self.POSTS, self.IMPORTS, {})["accounts"][0]
        self.assertEqual((waiting["retrieved"], waiting["eligible"], waiting["languages"]), (0, 0, {}))
        self.assertEqual(waiting["observed"], {"oldest": None, "newest": None})
        self.assertIsNone(waiting["moreRemaining"])          # unknown stays unknown, never "no more"
        self.assertFalse(waiting["totalKnown"])

    def test_states(self):
        self.assertEqual(E.fold_coverage([], [], {})["states"],
                         {"connected": "none", "retrieved": "none", "processed": "none", "proposed": "none", "approved": "none"})
        starting = E.fold_coverage([], self.IMPORTS[2:], {})["states"]
        self.assertEqual((starting["connected"], starting["retrieved"], starting["processed"]), ("done", "pending", "none"))
        running = E.fold_coverage(self.POSTS, self.IMPORTS, {})["states"]
        self.assertEqual((running["retrieved"], running["processed"]), ("partial", "partial"))
        finished = E.fold_coverage(self.POSTS, self.IMPORTS[:2], {})["states"]
        self.assertEqual((finished["connected"], finished["retrieved"], finished["processed"]), ("done", "done", "done"))
        more = E.fold_coverage(self.POSTS, [("threads", "t1", "@studio", "official_api", "failed", True, False, "brand")], {})["states"]
        self.assertEqual(more["retrieved"], "partial")

    def test_proposed_and_approved_come_from_the_workspace_state(self):
        proposal = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed"}}}
        self.assertEqual(E.fold_coverage(self.POSTS, self.IMPORTS[:2], proposal)["states"]["proposed"], "done")
        stale = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "stale"}}}
        self.assertEqual(E.fold_coverage(self.POSTS, self.IMPORTS[:2], stale)["states"]["proposed"], "partial")
        other = {"speaker": {"provisional": {"analysisMethod": "local-rules"}, "activeRevision": 2,
                             "revisions": [{"revision": 1, "profile": {"analysisMethod": "voice_import"}},
                                           {"revision": 2, "profile": {"analysisMethod": "user-authored"}}]}}
        states = E.fold_coverage(self.POSTS, self.IMPORTS[:2], other)["states"]
        self.assertEqual((states["proposed"], states["approved"]), ("none", "none"))
        approved = {"speaker": {"provisional": None, "activeRevision": 1, "revisions": [{"revision": 1, "profile": {"analysisMethod": "voice_import"}}]}}
        self.assertEqual(E.fold_coverage(self.POSTS, self.IMPORTS[:2], approved)["states"]["approved"], "done")
        self.assertEqual(E.fold_coverage(self.POSTS, self.IMPORTS[:2], {"speaker": "junk"})["states"]["approved"], "none")


class CursorFunctionTests(unittest.TestCase):
    """Statement shapes only; the rows themselves are checked on PostgreSQL."""
    class Cursor:
        def __init__(self, rows):
            self.rows, self.calls = rows, []

        def execute(self, sql, params=None):
            self.calls.append((" ".join(sql.split()), params))

        def fetchall(self):
            return self.rows

    ROW = ("11111111-1111-1111-1111-111111111111", "threads", "t1", "2026-10-01T00:00:00+00:00", LONG, "en", "text", "brand", "https://www.threads.net/@studio/post/1")

    def test_eligible_posts_rows_and_the_brand_default(self):
        cur = self.Cursor([self.ROW])
        rows = E.eligible_posts(cur, "w1")
        self.assertEqual(rows, [{"id": self.ROW[0], "provider": "threads", "account_key": "t1", "published_at": self.ROW[3], "body": LONG,
                                 "language": "en", "content_type": "text", "voice_scope": "brand", "permalink": self.ROW[8]}])
        sql, params = cur.calls[0]
        self.assertIn("status='eligible'", sql)
        self.assertIn("voice_scope='brand'", sql)      # no group named = the workspace's one brand voice, never a blend
        self.assertNotIn("LIMIT", sql)
        self.assertEqual(params, ("w1",))

    def test_a_separate_account_is_read_alone_and_limits_are_bounded(self):
        cur = self.Cursor([])
        E.eligible_posts(cur, "w1", group_key="separate:mastodon:m1@social.example.org", limit=40)
        sql, params = cur.calls[0]
        self.assertIn("voice_scope='separate'", sql)
        self.assertIn("LIMIT", sql)
        self.assertEqual(params, ("w1", "mastodon", "m1@social.example.org", 40))
        self.assertEqual(E.eligible_posts(self.Cursor([self.ROW]), "w1", group_key="nonsense"), [])
        for bad in (0, -1, "40", True):
            with self.assertRaises(ValueError):
                E.eligible_posts(self.Cursor([]), "w1", limit=bad)


if __name__ == "__main__":
    unittest.main()
