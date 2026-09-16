"""Web research for a turn: when it runs, what it asks, what it keeps, how it fails softly. No network."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import research  # noqa: E402

READER_TEXT = """Title: Introducing v6 - Suno AI

URL Source: https://suno.com/blog/introducing-v6

Markdown Content:
[![Image 1: Suno](https://blog.suno.com/logo.svg)](https://suno.com/home)[Studio](https://suno.com/studio)

[About](https://suno.com/about)[Contact Us](https://help.suno.com/)[Help](https://help.suno.com/)

# Introducing v6

Today we’re taking our biggest step yet toward that vision. We’re introducing v6, a new generation of music models developed with our industry partners, including Warner Music Group, BMG and Believe.

v6 models are our best yet. They are faster, more expressive and higher quality, with powerful new features that give creators greater control over their music.

- v6 is our flagship model for Pro and Premier subscribers. It is reliable, precise and consistently delivers polished music across every genre and style.
- v6-mini is a faster, more efficient version available to everyone. It makes it easier than ever to turn an idea into a song.

Short line.

Today we’re taking our biggest step yet toward that vision. We’re introducing v6, a new generation of music models developed with our industry partners, including Warner Music Group, BMG and Believe.
"""

EXA_TEXT = """Title: Introducing v6 - Suno AI
URL: https://suno.com/blog/introducing-v6
Published: 2026-09-09T10:34:56.084Z
Author: N/A
Highlights:
Suno | Introducing v6
...
v6 models are our best yet.

Title: Suno v6 thread
URL: https://x.com/suno/status/1
Published: 2026-09-09
Highlights:
Big news.

Title: Suno v6 review
URL: https://www.example-news.com/suno-v6-review
Published: 2026-09-10
Highlights:
A hands-on review of the three v6 models.
"""


class ResearchRulesTest(unittest.TestCase):
    def test_research_runs_for_topics_links_and_explicit_asks_but_not_for_first_person_ideas(self):
        self.assertTrue(research.needs_research("write a post about the most advanced model of Suno AI"))
        self.assertTrue(research.needs_research("write about climate change"))
        self.assertTrue(research.needs_research("Thoughts on https://suno.com/blog/introducing-v6 please"))
        self.assertTrue(research.needs_research("something", intent="research"))
        self.assertFalse(research.needs_research("Practice was rough today; my left hand kept rushing the Chopin coda."))
        self.assertFalse(research.needs_research("I keep noticing how much slower I play when I record myself."))
        self.assertFalse(research.needs_research("今日我練琴練到好攰"))
        self.assertFalse(research.needs_research("write a post about the newest Suno model", has_facts=True), "the person supplied material for this turn")
        self.assertFalse(research.needs_research("hi"))
        # A first-person sentence about something in the world is still a topic.
        self.assertTrue(research.needs_research("I want to express my excitement about the most advanced models that were just announced in Suno AI."))
        self.assertTrue(research.needs_research("I tried Suno v6 yesterday and it surprised me."))
        self.assertTrue(research.needs_research("I keep thinking about the new Claude release."))
        self.assertTrue(research.needs_research("write a post about the newest Suno model"), "other facts in the workspace say nothing about this topic")
        for edit in ("make it shorter", "Shorter, please", "another angle", "改短啲", "translate to Cantonese", "use the second one"):
            self.assertFalse(research.needs_research(edit), edit)

    def test_query_strips_the_instruction_and_the_channel(self):
        self.assertEqual(research.query_for("write me a post about the most advanced model of Suno AI for LinkedIn"), "the most advanced model of Suno AI")
        self.assertEqual(research.query_for("Write a LinkedIn post on Suno v6"), "Suno v6")
        self.assertEqual(research.query_for("climate change"), "climate change")
        self.assertEqual(research.query_for("Thoughts on https://suno.com/blog/introducing-v6 please"), "Thoughts on please")
        self.assertEqual(research.query_for("I want to express my excitement about the most advanced models that were just announced in Suno AI. Make it warm."), "the most advanced models that were just announced in Suno AI")
        self.assertEqual(research.query_for("I'm curious about Suno v6 for Instagram"), "Suno v6")

    def test_paragraphs_keep_prose_and_drop_navigation_headings_and_duplicates(self):
        facts = research.paragraphs(READER_TEXT)
        self.assertEqual(len(facts), 4, facts)
        self.assertTrue(facts[0].startswith("Today we’re taking our biggest step"))
        self.assertTrue(any(f.startswith("v6 is our flagship model") for f in facts))
        self.assertFalse(any("Image 1" in f or f.startswith("#") or "Contact Us" in f for f in facts))
        junk = research.paragraphs("We use cookies and similar technologies to personalise content and analyse our traffic; manage your preferences below.\n\nSign up to our newsletter for the latest music business news delivered every morning to your inbox.\n\nA real paragraph about the v6 models with enough words to be kept as a fact about the launch.")
        self.assertEqual(len(junk), 1, junk)
        long = research.paragraphs("A" * 40 + ". " + "word " * 200)
        self.assertLessEqual(len(long[0]), research.MAX_FACT_CHARS)

    def test_exa_text_parses_into_results(self):
        results = research.parse_search_text(EXA_TEXT)
        self.assertEqual([r["url"] for r in results], ["https://suno.com/blog/introducing-v6", "https://x.com/suno/status/1", "https://www.example-news.com/suno-v6-review"])
        self.assertEqual(results[0]["published"], "2026-09-09T10:34:56.084Z")
        self.assertIn("v6 models are our best yet", results[0]["snippet"])


class ConsentTest(unittest.TestCase):
    def test_local_is_always_on_and_hosted_needs_the_owner(self):
        with mock.patch.dict(os.environ, {"POSTRIFF_HOSTED": "", "VERCEL": "", "POSTRIFF_RESEARCH": "1"}):
            self.assertTrue(research.allowed({}))
            self.assertEqual((research.consent_summary({})["web"], research.consent_summary({})["hosted"]), (True, False))
        with mock.patch.dict(os.environ, {"POSTRIFF_HOSTED": "1", "VERCEL": "", "POSTRIFF_RESEARCH": "1"}):
            state = {}
            self.assertFalse(research.allowed(state))
            self.assertFalse(research.apply_research_action(state, "memory_egress", {"cloud": True}, "u1", 1.0))
            with self.assertRaises(AlphaError):
                research.apply_research_action(state, "research_egress", {"web": True}, "u1", 1.0)
            self.assertTrue(research.apply_research_action(state, "research_egress", {"web": True, "confirmed": True}, "u1", 1789524000.0))
            self.assertTrue(research.allowed(state))
            summary = research.consent_summary(state)
            self.assertEqual((summary["web"], summary["hosted"], summary["decidedBy"], summary["decidedAt"]), (True, True, "u1", 1789524000.0))
            research.apply_research_action(state, "research_egress", {"web": False, "confirmed": True}, "u1", 2.0)
            self.assertFalse(research.allowed(state))
        with mock.patch.dict(os.environ, {"POSTRIFF_RESEARCH": "0", "POSTRIFF_HOSTED": "", "VERCEL": ""}):
            self.assertFalse(research.allowed({}))
            self.assertFalse(research.consent_summary({})["web"])
        self.assertIn("Memory → Web research", research.off_record("x")["warnings"][0])
        self.assertTrue(research.off_record("x")["off"])


class ResearcherTest(unittest.TestCase):
    def researcher(self, pages=None, fail=(), budget=30, clock=None):
        review = "Title: Review\n\n" + "\n\n".join(f"Review paragraph {n}: the {name} model was tested on three genres with enough words to count as a fact about how it behaves in practice." for n, name in enumerate(("v6", "v6-wild", "v6-mini"), 1))
        pages = pages or {"https://suno.com/blog/introducing-v6": READER_TEXT, "https://www.example-news.com/suno-v6-review": review}

        def search(query, limit):
            return research.parse_search_text(EXA_TEXT)

        def read(url):
            if url in fail:
                raise TimeoutError("slow")
            return {"title": pages[url].splitlines()[0][6:].strip(), "text": pages[url]}
        return research.Researcher(search=search, read=read, budget=budget, clock=clock or (lambda: 0.0))

    def test_search_then_read_skips_walled_hosts_and_keeps_two_pages_of_facts(self):
        out = self.researcher().run("write a post about the most advanced model of Suno AI")
        self.assertEqual(out["query"], "the most advanced model of Suno AI")
        self.assertEqual([p["host"] for p in out["pages"]], ["suno.com", "example-news.com"])
        self.assertNotIn("https://x.com/suno/status/1", out["searched"])
        self.assertEqual(out["pages"][0]["title"], "Introducing v6 - Suno AI")
        self.assertEqual(out["pages"][0]["published"], "2026-09-09T10:34:56.084Z")
        self.assertEqual(len(out["pages"][0]["facts"]), 4)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(research.source_title(out["pages"][0]), "Introducing v6 - Suno AI — suno.com")
        self.assertEqual(research.source_body(out["pages"][0]).count("\n\n"), 3)
        record = research.summary(out)
        self.assertEqual(record["pages"][0]["facts"], 4)
        self.assertNotIn("text", record["pages"][0])

    def test_pasted_links_are_read_directly_without_searching(self):
        calls = []

        def search(query, limit):
            calls.append(query)
            return []
        researcher = research.Researcher(search=search, read=lambda url: {"title": "Introducing v6", "text": READER_TEXT}, clock=lambda: 0.0)
        out = researcher.run("Thoughts on https://suno.com/blog/introducing-v6 please")
        self.assertEqual(calls, [])
        self.assertEqual([p["url"] for p in out["pages"]], ["https://suno.com/blog/introducing-v6"])

    def test_read_failures_and_thin_pages_become_warnings_not_errors(self):
        out = self.researcher(fail=("https://suno.com/blog/introducing-v6",)).run("Suno v6")
        self.assertEqual([p["host"] for p in out["pages"]], ["example-news.com"])
        self.assertTrue(any("Could not read suno.com (TimeoutError)" in w for w in out["warnings"]))
        thin = research.Researcher(search=lambda q, n: research.parse_search_text(EXA_TEXT), read=lambda url: {"title": "t", "text": "Title: t\n\nshort"}, clock=lambda: 0.0).run("Suno v6")
        self.assertEqual(thin["pages"], [])
        self.assertTrue(any("no readable article text" in w for w in thin["warnings"]))
        self.assertTrue(any("found nothing readable" in w for w in thin["warnings"]))

    def test_search_outage_is_a_warning_and_the_time_budget_stops_reading(self):
        def boom(query, limit):
            raise ConnectionError("down")
        naps = []
        out = research.Researcher(search=boom, read=lambda url: {"title": "", "text": ""}, clock=lambda: 0.0, sleep=naps.append).run("Suno v6")
        self.assertEqual(out["pages"], [])
        self.assertTrue(any("Web search was unavailable after 3 attempts (ConnectionError)" in w for w in out["warnings"]))
        self.assertEqual(len(naps), 2, "two pauses between three attempts")

    def test_a_transient_search_failure_is_retried(self):
        attempts = []

        def flaky(query, limit):
            attempts.append(query)
            if len(attempts) == 1:
                raise ConnectionRefusedError("refused")
            return research.parse_search_text(EXA_TEXT)
        researcher = self.researcher()
        researcher.search, researcher.sleep = flaky, lambda seconds: None
        out = researcher.run("Suno v6")
        self.assertEqual(len(attempts), 2)
        self.assertEqual([p["host"] for p in out["pages"]], ["suno.com", "example-news.com"])
        self.assertEqual(out["warnings"], [])
        ticks = iter([0.0, 0.0, 40.0, 40.0, 40.0])
        slow = self.researcher(budget=30, clock=lambda: next(ticks)).run("Suno v6")
        self.assertEqual(len(slow["pages"]), 1)
        self.assertTrue(any("time limit" in w for w in slow["warnings"]))


if __name__ == "__main__":
    unittest.main()
