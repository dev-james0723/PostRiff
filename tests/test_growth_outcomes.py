"""SYNTHETIC FIXTURES ONLY: no row below is a real post or a real creator."""
import csv
import importlib.util
import io
import os
import random
import tempfile
import unittest
from pathlib import Path

from postriff_phase2.growth import outcomes as O
from postriff_phase2.growth import questions as Q
from postriff_phase2.growth.judgments import Judgment, validate_answers

QS = Q.get("postdoctor", 1)
INVERTED = {i["q"] for d in QS.dimensions.values() for i in d["items"] if i.get("invert")}
ROOT = Path(__file__).resolve().parents[1]
def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _script("growth_collect_common")
C = _script("growth_collect_bluesky")
M = _script("growth_collect_mastodon")


def judgment(p):
    raw = {n: {"type": "boolean", "probability": 0.05 if n.startswith("risk_") else (1 - p if n in INVERTED else p)} for n in QS.names}
    answers, invalid = validate_answers(QS, raw)
    return Judgment(QS.key, QS.digest, "typesafe-ai/jev", "primary", True, answers, invalid, None, "unknown", None, 5, "k")


def dataset(authors=16, per=24, lang="en", signal=True, seed=1):
    """Each synthetic creator has a different audience size; within a creator, 'quality' drives engagement."""
    rng = random.Random(seed)
    rows, quality = [], {}
    for a in range(authors):
        base = rng.choice([5, 50, 500, 5000])
        for i in range(per):
            q = rng.random()
            eng = int(base * (0.3 + 1.4 * q if signal else rng.random() * 1.7))
            pid = f"{lang}-a{a}-p{i}"
            quality[pid] = q
            rows.append({"id": pid, "platform": "other", "lang": lang, "author": f"{lang}-creator{a}", "created_at": "1780000000",
                         "text": "synthetic fixture text", "likes": eng, "reposts": 0, "replies": 0, "quotes": 0,
                         "has_media": "1" if i % 3 == 0 else "0", "collected_at": "1790000000", "source_uri": f"at://x/{pid}"})
    return rows, quality


def write(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=O.COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    handle.close()
    return handle.name


def score_as(quality, noise=0.0, seed=2):
    """Judgments whose answer probabilities follow a post's quality (plus noise), kept outside the abstain band."""
    rng = random.Random(seed)
    out = {}
    for pid, q in quality.items():
        p = min(0.95, max(0.05, q + rng.uniform(-noise, noise)))
        p = 0.3 if 0.35 <= p < 0.5 else (0.7 if 0.5 <= p <= 0.65 else p)
        out[pid] = judgment(p)
    return out


class Metrics(unittest.TestCase):
    def test_spearman_and_auc(self):
        self.assertAlmostEqual(O.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(O.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)
        self.assertIsNone(O.spearman([1, 1, 1], [1, 2, 3]))
        self.assertEqual(O.auc([3, 4], [1, 2]), 1.0)
        self.assertEqual(O.auc([1, 2], [1, 2]), 0.5)

    def test_outcomes_are_within_creator(self):
        rows, _ = dataset(authors=2, per=21)
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, problems = O.parse(path)
        outs = O.relative_outcomes(posts)
        by_creator = {}
        for p in posts:
            by_creator.setdefault(p.author, []).append(outs[p.id][0])
        for values in by_creator.values():
            self.assertAlmostEqual(sorted(values)[len(values) // 2], 0.0)   # each creator centred on its own median
        terciles = [outs[p.id][1] for p in posts if p.author == posts[0].author]
        self.assertEqual((terciles.count("top"), terciles.count("bottom")), (7, 7))


class Parse(unittest.TestCase):
    def test_problems_and_eligibility(self):
        rows, _ = dataset(authors=2, per=20)
        rows[0]["likes"] = "-3"
        rows[1]["id"] = rows[2]["id"]
        rows[3]["created_at"] = "yesterday"
        rows.append(dict(rows[5], id="lonely", author="small-creator"))
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, problems = O.parse(path)
        self.assertEqual(len(problems), 3)
        self.assertNotIn("small-creator", {p.author for p in O.eligible(posts)})
        out = io.StringIO()
        self.assertEqual(O.main(["summarize", path], out=out), 1)
        self.assertIn("needs at least 15", out.getvalue())


class LinkFeeds(unittest.TestCase):
    def test_link_feeds_are_excluded_writers_with_links_are_not(self):
        self.assertTrue(O.mostly_link("New study out https://example.com/a/b #science"))
        self.assertTrue(O.mostly_link("Breaking: markets fall example.com/news/123"))
        self.assertFalse(O.mostly_link("I spent ten years teaching scales before I understood why students hate them. "
                                       "Here is what changed my mind: https://example.com/essay"))
        self.assertFalse(O.mostly_link("No link here at all, just a short thought."))
        rows, _ = dataset(authors=2, per=20)
        for r in rows[:20]:
            r["text"] = f"Headline number {r['id']} https://news.example/{r['id']}"
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse(path)
        self.assertEqual({p.author for p in O.eligible(posts)}, {"en-creator1"})
        self.assertEqual(O.summarize(posts)["other/en"]["link_feeds_excluded"], 1)


class Evaluate(unittest.TestCase):
    def test_a_score_that_tracks_quality_passes(self):
        rows, quality = dataset()
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse(path)
        report = O.evaluate(posts, score_as(quality, noise=0.1), QS, rounds=300)
        en = report["groups"]["en"]
        self.assertEqual((en["creators"], en["passes"]), (16, True), en)
        self.assertGreater(en["spearman"], 0.5)
        self.assertGreater(en["spearman_ci"][0], 0)
        self.assertGreater(en["auc_top_vs_bottom"], 0.8)
        self.assertIn("hook", en["per_dimension_spearman"])

    def test_a_score_that_ignores_quality_fails(self):
        rows, quality = dataset()
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse(path)
        rng = random.Random(9)
        shuffled = dict(zip(quality, rng.sample(list(quality.values()), len(quality))))
        en = O.evaluate(posts, score_as(shuffled), QS, rounds=300)["groups"]["en"]
        self.assertFalse(en["passes"])
        self.assertIn("interval_includes_zero", en["reasons"])

    def test_few_creators_never_pass(self):
        rows, quality = dataset(authors=4)
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse(path)
        en = O.evaluate(posts, score_as(quality, noise=0.05), QS, rounds=200)["groups"]["en"]
        self.assertIn("too_few_creators", en["reasons"])
        self.assertFalse(en["passes"])

    def test_popular_creators_do_not_fake_a_signal(self):
        # Scores follow audience size, not within-creator quality: a raw like-count comparison would reward this.
        rows, quality = dataset(signal=False)
        base = {}
        for r in rows:
            base.setdefault(r["author"], []).append(r["likes"])
        size = {a: sum(v) / len(v) for a, v in base.items()}
        biggest = max(size.values())
        by_size = {r["id"]: min(0.95, 0.1 + 0.8 * size[r["author"]] / biggest) for r in rows}
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse(path)
        en = O.evaluate(posts, score_as(by_size), QS, rounds=300)["groups"]["en"]
        self.assertFalse(en["passes"], en)


class Sampling(unittest.TestCase):
    def test_deterministic_caps_and_platform_report(self):
        rows, quality = dataset(authors=18, per=25)
        for r in rows[: 18 * 25 // 2]:
            r["platform"] = "mastodon"
        path = write(rows)
        self.addCleanup(os.unlink, path)
        posts, _ = O.parse_many([path])
        small = O.sample(posts, max_creators=5, max_posts=21)
        cells = {}
        for p in small:
            cells.setdefault((p.platform, p.author), 0)
            cells[(p.platform, p.author)] += 1
        self.assertEqual(len([k for k in cells if k[0] == "mastodon"]), 5)
        self.assertTrue(all(n <= 21 for n in cells.values()))
        self.assertEqual([p.id for p in small], [p.id for p in O.sample(posts, max_creators=5, max_posts=21)])
        report = O.evaluate(posts, score_as(quality, noise=0.1), QS, rounds=200)
        self.assertEqual(set(report["platforms"]), {"mastodon", "other"})
        self.assertIn("mastodon/en", report["platform_languages"])


class CompareOutcomes(unittest.TestCase):
    def test_dry_run_then_faked_live_run(self):
        from postriff_phase2.growth import compare as CMP
        from postriff_phase2.growth import jev as J
        rows, quality = dataset(authors=15, per=20)
        path = write(rows)
        self.addCleanup(os.unlink, path)
        calls = []
        class FakeJev:
            def evaluate(self, state, questions, *, timeout_s):
                calls.append(1)
                answers = {n: {"type": "boolean", "probability": 0.8} for n in questions}
                return J.RawEvaluation("typesafe-ai/jev", answers, 1, 1, 0.0001, "gateway", "g", "typesafe-ai", 5)
        out = io.StringIO()
        args = ["--outcomes", path, "--models", "jev", "--price", "jev=1,5", "--max-usd", "20"]
        self.assertEqual(CMP.main(args, env={}, out=out, factories=(FakeJev, None)), 0)
        self.assertEqual(calls, [])
        target = tempfile.mktemp(suffix=".json")
        self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))
        self.assertEqual(CMP.main(args + ["--confirm-live", "--out", target], env={}, out=io.StringIO(), factories=(FakeJev, None)), 0)
        import json
        with open(target, encoding="utf-8") as handle:
            report = json.load(handle)
        en = report["results"]["typesafe-ai/jev"]["groups"]["en"]
        self.assertEqual((len(calls), en["creators"], en["passes"]), (300, 15, False))   # a constant score cannot pass
        self.assertIn("preregistered", report["results"]["typesafe-ai/jev"])


class Collector(unittest.TestCase):
    NOW = 1_790_000_000.0

    def item(self, text, days=30, reply=False, repost=False, likes=3, embed=False, langs=("en",)):
        created = self.NOW - days * 86400
        from datetime import datetime, timezone
        rec = {"text": text, "langs": list(langs), "createdAt": datetime.fromtimestamp(created, timezone.utc).isoformat().replace("+00:00", "Z")}
        if reply:
            rec["reply"] = {"parent": {}}
        post = {"uri": "at://did:plc:x/app.bsky.feed.post/1", "author": {"did": "did:plc:x"}, "record": rec,
                "likeCount": likes, "repostCount": 1, "replyCount": 0, "quoteCount": 0}
        if embed:
            post["embed"] = {"$type": "app.bsky.embed.images#view"}
        item = {"post": post}
        if repost:
            item["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
        return item

    def test_filters(self):
        en = "Three things I stopped doing in my first piano lessons, and what I teach instead now after ten years."
        zh = "教咗十幾年琴，發現學生最常卡住嘅唔係手指，而係練習方法，今日同大家分享三個慢練方法。"
        row = C.row_from_feed_item(self.item(en, embed=True), "en", self.NOW)
        self.assertEqual((row["likes"], row["reposts"], row["has_media"], row["lang"]), (3, 1, "1", "en"))
        self.assertNotIn("did:plc:x", row["author"])                      # creators are hashed
        self.assertIsNotNone(C.row_from_feed_item(self.item(zh), "zh-HK", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item(en, repost=True), "en", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item(en, reply=True), "en", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item(en, days=2), "en", self.NOW))       # engagement not settled
        self.assertIsNone(C.row_from_feed_item(self.item(en, days=400), "en", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item("too short"), "en", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item(zh), "en", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item("这个问题我们说过很多次了，为什么还会这样呢？今天再说一次吧大家"), "zh-HK", self.NOW))
        self.assertIsNone(C.row_from_feed_item(self.item(en, langs=()), "en", self.NOW))      # untagged Latin text is unclear
        self.assertEqual(C.row_from_feed_item(self.item(en), "en", self.NOW)["platform"], "bluesky")

    def test_language_detection(self):
        self.assertEqual(K.detect("今日はピアノの練習をしました。先生にほめられてとても嬉しかったです。"), "ja")
        self.assertEqual(K.detect("오늘은 피아노 연습을 했어요. 선생님께 칭찬을 받아서 정말 기뻤어요."), "ko")
        self.assertEqual(K.detect("今天練琴練了三個小時，老師說我的手型進步很多，真的很開心。"), "zh-TW")
        self.assertEqual(K.detect("今日練咗三個鐘琴，老師話我手型進步咗好多，真係好開心呀。"), "zh-HK")
        self.assertEqual(K.detect("Hoy practiqué piano tres horas y mi profesora dijo que mejoré mucho la postura.", ["es"]), "es")
        self.assertIsNone(K.detect("Hoy practiqué piano tres horas y mi profesora dijo que mejoré mucho la postura.", []))

    def test_mastodon_rules(self):
        base = {"id": "1", "acct": "a", "statuses_count": 500, "discoverable": True}
        self.assertTrue(M.eligible_account(base))
        for flag in ({"noindex": True}, {"indexable": False}, {"bot": True}, {"group": True}, {"statuses_count": 3}):
            self.assertFalse(M.eligible_account(dict(base, **flag)), flag)
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(self.NOW - 30 * 86400, timezone.utc).isoformat()
        status = {"id": "9", "uri": "https://m.example/users/a/statuses/9", "account": {"url": "https://m.example/@a"},
                  "created_at": ts, "visibility": "public", "language": "en", "favourites_count": 4, "reblogs_count": 2,
                  "replies_count": 1, "content": "<p>Three things I stopped doing in my first piano lessons,<br>and what I teach instead after ten years.</p>"}
        row = M.row_from_status(status, "m.example", self.NOW)
        self.assertEqual((row["platform"], row["lang"], row["likes"], row["reposts"], row["replies"]), ("mastodon", "en", 4, 2, 1))
        self.assertIn("\n", row["text"])
        for change in ({"spoiler_text": "cw"}, {"visibility": "unlisted"}, {"in_reply_to_id": "8"}, {"reblog": {"id": "x"}}):
            self.assertIsNone(M.row_from_status(dict(status, **change), "m.example", self.NOW), change)

    def test_never_writes_inside_a_repository(self):
        self.assertIsNone(K.outside_repo(str(ROOT / "data" / "x.csv")))


if __name__ == "__main__":
    unittest.main()
