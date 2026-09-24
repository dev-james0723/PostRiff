"""An automation run's research step: publisher filtering, recency, scoring, the decision and its reason, and quote
verification. Every backend is a fake; nothing touches the network and nothing sleeps."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import automation_research as ar  # noqa: E402
from postriff_phase2 import workflow  # noqa: E402

NOON = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)
NOW = NOON.timestamp()


def days_ago(days):
    return (NOON - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def spec(**fields):
    return workflow.normalize_research(fields)


def result(url, title, published="", snippet=""):
    return {"title": title, "url": url, "published": published, "snippet": snippet}


def reader(title, paragraphs, published=None):
    """Reader text shaped like JinaReader's output."""
    head = [f"Title: {title}", "", "URL Source: https://example.org/page", ""]
    if published:
        head += [f"Published Time: {published}", ""]
    return {"title": title, "text": "\n".join(head + ["Markdown Content:", ""] + [f"{p}\n" for p in paragraphs])}


def on_topic(subject, count=5):
    return [f"Finding {n}: the team described how {subject} changed over the months they spent observing the volunteers closely." for n in range(1, count + 1)]


def off_topic(count=5):
    return [f"Match report {n}: the home side pressed high, won the ball back often and finally scored in the last minute of play." for n in range(1, count + 1)]


class Search:
    def __init__(self, answer=(), fail=False):
        self.answer, self.fail, self.calls = answer, fail, []

    def __call__(self, query, limit):
        self.calls.append((query, limit))
        if self.fail:
            raise TimeoutError("search timed out")
        answer = self.answer(query) if callable(self.answer) else self.answer
        return [dict(item) for item in answer]


class Read:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.calls = pages, set(fail), []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.fail or url not in self.pages:
            raise ConnectionError("refused")
        return dict(self.pages[url])


def find(settings, search, read, **options):
    sleeps = options.pop("sleeps", [])
    options.setdefault("clock", lambda: 100.0)
    return ar.find(settings, search=search, read=read, now=NOW, sleep=sleeps.append, **options)


class HelpersTest(unittest.TestCase):
    def test_a_publisher_domain_allows_its_subdomains_and_nothing_else(self):
        for host in ("bbc.co.uk", "www.bbc.co.uk", "news.bbc.co.uk", "BBC.co.uk"):
            self.assertTrue(ar.host_allowed(host, ["bbc.co.uk"]), host)
        for host in ("bbc.co.uk.evil.com", "cnn.com", "notbbc.co.uk", "bbc.com", ""):
            self.assertFalse(ar.host_allowed(host, ["bbc.co.uk"]), host)

    def test_sites_group_subdomains_so_they_are_not_independent(self):
        self.assertEqual(ar.site_of("news.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(ar.site_of("m.quotesite.com"), "quotesite.com")
        self.assertEqual(ar.site_of("quotesite.com"), "quotesite.com")
        self.assertEqual(ar.site_of("www.abc.net.au"), "abc.net.au")

    def test_publication_dates_parse_or_are_unknown(self):
        self.assertEqual(ar.published_at("2026-09-24T12:00:00Z"), NOW)
        self.assertEqual(ar.published_at("2026-09-24T12:00:00.000Z"), NOW)
        self.assertEqual(ar.published_at("2026-09-24"), NOW - 12 * 3600)
        self.assertEqual(ar.published_at("Thu, 24 Sep 2026 12:00:00 GMT"), NOW)
        self.assertEqual(ar.published_at("Published 2026-09-24 12:00 (updated)"), NOW)
        for unknown in ("", None, "last Tuesday", "2026-13-45"):
            self.assertIsNone(ar.published_at(unknown), unknown)

    def test_topic_words_drop_request_words_publishers_and_plurals(self):
        self.assertEqual(ar.words("Find notable BBC News articles about the latest sleep studies"), ["bbc", "sleep", "study"])
        settings = spec(query="Every Wednesday find a notable BBC News article about creativity", about="creativity", domains=["bbc.co.uk"])
        self.assertEqual(ar.topic_terms(settings), {"creativity": 2})
        settings = spec(query="something interesting from a reputable science publication", about="creativity", publications="reputable science publications")
        self.assertEqual(ar.topic_terms(settings), {"creativity": 2})

    def test_score_is_bounded_and_led_by_relevance(self):
        self.assertEqual(ar.score(1, 1, 1, 1), 1.0)
        self.assertEqual(ar.score(0, 1, 1, 1), 0.0)
        self.assertLess(ar.score(0.4, 1, 1, 1), 0.55, "an article that is mostly off topic cannot clear the default bar")
        self.assertGreater(ar.score(0.9, 1, 0.5, 0.7), 0.55)


class ArticleTest(unittest.TestCase):
    def test_only_the_named_publisher_is_used_and_one_search_runs_per_domain(self):
        results = [
            result("https://bbc.co.uk.evil.com/news/creativity", "Creativity secrets", days_ago(1), "creativity"),
            result("https://edition.cnn.com/creativity", "Creativity at work", days_ago(1), "creativity"),
            result("https://x.com/bbc/status/1", "Creativity thread", days_ago(1)),
            result("https://www.bbc.co.uk/news/articles/1", "Why boredom fuels creativity", days_ago(2), "Researchers link boredom and creativity."),
            result("https://news.bbc.co.uk/2/hi/2", "Creativity in the classroom", days_ago(3), "Teachers on creativity."),
        ]
        pages = {r["url"]: reader(r["title"], on_topic("creativity")) for r in results}
        search, read = Search(results), Read(pages)
        record = find(spec(query="notable BBC News article about creativity", about="creativity", domains=["bbc.co.uk"]), search, read)
        self.assertEqual(search.calls, [("notable BBC News article about creativity from bbc.co.uk", ar.SEARCH_LIMIT)])
        self.assertEqual({c["host"] for c in record["candidates"]}, {"bbc.co.uk", "news.bbc.co.uk"})
        self.assertFalse({"https://bbc.co.uk.evil.com/news/creativity", "https://edition.cnn.com/creativity", "https://x.com/bbc/status/1"} & set(read.calls))
        self.assertEqual(record["decision"], "chosen")
        self.assertEqual(record["chosen"]["host"], "bbc.co.uk")
        self.assertTrue(any("Set aside 2 result(s)" in w and "bbc.co.uk.evil.com" in w and "edition.cnn.com" in w for w in record["warnings"]), record["warnings"])
        self.assertTrue(any("x.com" in w for w in record["warnings"]))

        many = Search([])
        find(spec(about="jazz", domains=["a-news.com", "b-news.com", "c-news.com", "d-news.com"]), many, Read({}))
        self.assertEqual([call[0] for call in many.calls], ["jazz from a-news.com", "jazz from b-news.com", "jazz from c-news.com"])

    def test_old_articles_are_excluded_with_a_reason(self):
        results = [
            result("https://www.bbc.co.uk/news/old", "Creativity and sleep", days_ago(12), "creativity"),
            result("https://www.bbc.co.uk/news/new", "Creativity at any age", days_ago(1), "creativity"),
        ]
        pages = {r["url"]: reader(r["title"], on_topic("creativity")) for r in results}
        read = Read(pages)
        record = find(spec(about="creativity", domains=["bbc.co.uk"], recencyDays=7), Search(results), read)
        self.assertEqual(record["chosen"]["url"], "https://www.bbc.co.uk/news/new")
        self.assertNotIn("https://www.bbc.co.uk/news/old", read.calls, "an out-of-window article is not opened")
        old = next(c for c in record["candidates"] if c["url"].endswith("/old"))
        self.assertEqual(old["score"], 0.0)
        self.assertEqual(old["reasons"], ["Published 12 days ago, outside the 7-day window"])

        only_old = find(spec(about="creativity", domains=["bbc.co.uk"], recencyDays=7), Search(results[:1]), Read(pages))
        self.assertEqual(only_old["decision"], "nothing_worth")
        self.assertEqual(only_old["reason"], "Only articles older than 7 days turned up from bbc.co.uk for “creativity”, so this run was skipped.")

        # A date only the page itself reveals still counts.
        undated = [result("https://www.bbc.co.uk/news/undated", "Creativity at work", "", "creativity")]
        late = {undated[0]["url"]: reader("Creativity at work", on_topic("creativity"), published=days_ago(30))}
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), Search(undated), Read(late))
        self.assertEqual(record["decision"], "nothing_worth")
        self.assertIn("outside the 7-day window", record["candidates"][0]["reasons"][0])

    def test_weak_candidates_mean_nothing_worth_with_a_plain_reason(self):
        tangential = on_topic("the budget", 5) + ["One minister said the arts budget would protect creativity in schools for several more years."]
        results = [
            result("https://www.bbc.co.uk/sport/1", "Late goal settles the derby", days_ago(1), "Football."),
            result("https://www.bbc.co.uk/news/budget", "Chancellor sets out the budget", days_ago(1), "The budget."),
        ]
        pages = {results[0]["url"]: reader(results[0]["title"], off_topic()), results[1]["url"]: reader(results[1]["title"], tangential)}
        search = Search(results)
        record = find(spec(query="Every Wednesday find a notable BBC News article about creativity", about="creativity", domains=["bbc.co.uk"]), search, Read(pages))
        self.assertEqual(search.calls[0][0], "a notable BBC News article about creativity from bbc.co.uk", "the schedule and the command are not search words")
        self.assertEqual(record["decision"], "nothing_worth")
        self.assertIsNone(record["chosen"])
        self.assertIsNone(record["page"])
        self.assertEqual(record["reason"], "Nothing from bbc.co.uk in the last 7 days cleared the bar for “creativity”, so this run was skipped.")
        self.assertTrue(all(c["score"] < 0.55 for c in record["candidates"]))
        budget = next(c for c in record["candidates"] if c["url"].endswith("/budget"))
        self.assertTrue(any("1 of 6 paragraphs are on topic" in r for r in budget["reasons"]), budget["reasons"])

        empty = find(spec(about="creativity", publications="reputable science publications", onNothing="draft_without"), Search([]), Read({}))
        self.assertEqual(empty["decision"], "nothing_worth")
        self.assertEqual(empty["reason"], "Nothing from reputable science publications in the last 7 days turned up for “creativity”, so the draft goes ahead without an article.")

    def test_a_backend_failure_is_unavailable_not_nothing_worth(self):
        sleeps = []
        search = Search(fail=True)
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), search, Read({}), sleeps=sleeps)
        self.assertEqual(record["decision"], "unavailable")
        self.assertEqual(record["reason"], "bbc.co.uk could not be reached after 3 attempts.")
        self.assertEqual(len(search.calls), 3)
        self.assertEqual(sleeps, [ar.RETRY_DELAY_SECONDS, ar.RETRY_DELAY_SECONDS * 2], "retries back off through the injected sleep")
        self.assertIsNone(record["chosen"])

        no_domain = find(spec(about="creativity"), Search(fail=True), Read({}))
        self.assertEqual(no_domain["reason"], "Web search could not be reached after 3 attempts.")

        results = [result("https://www.bbc.co.uk/news/1", "Creativity", days_ago(1)), result("https://www.bbc.co.uk/news/2", "Creativity again", days_ago(1))]
        read = Read({}, fail=[r["url"] for r in results])
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), Search(results), read)
        self.assertEqual(record["decision"], "unavailable")
        self.assertEqual(len(read.calls), 4, "each read is tried twice")
        self.assertIn("could not be opened after 2 attempts each", record["reason"])

    def test_the_budget_stops_reading_and_is_reported(self):
        ticks = iter(range(0, 10_000, 20))
        results = [result(f"https://www.bbc.co.uk/news/{n}", f"Creativity {n}", days_ago(1), "creativity") for n in range(4)]
        pages = {r["url"]: reader(r["title"], on_topic("creativity")) for r in results}
        read = Read(pages)
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), Search(results), read, clock=lambda: next(ticks), budget=45)
        self.assertLess(len(read.calls), 4)
        self.assertTrue(any("time limit" in w for w in record["warnings"]))

    def test_a_supplied_link_is_read_first_and_counts_whatever_its_publisher(self):
        supplied = "https://blog.example.org/creativity-notes"
        results = [result("https://www.bbc.co.uk/news/1", "Creativity and play", days_ago(1), "creativity")]
        pages = {supplied: reader("Notes on creativity", on_topic("creativity", 6)), results[0]["url"]: reader("Creativity and play", on_topic("creativity"))}
        read = Read(pages)
        record = find(spec(about="creativity", domains=["bbc.co.uk"], urls=[supplied]), Search(results), read)
        self.assertEqual(read.calls[0], supplied)
        self.assertEqual(record["decision"], "chosen")
        self.assertEqual(record["chosen"]["url"], supplied)
        self.assertIn("A link you supplied", " ".join(record["candidates"][0]["reasons"]))

    def test_the_chosen_page_has_the_research_page_shape(self):
        results = [result("https://www.bbc.co.uk/news/articles/c1", "How boredom fuels creativity", days_ago(2), "creativity")]
        pages = {results[0]["url"]: reader("How boredom fuels creativity - BBC News", on_topic("creativity", 7))}
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), Search(results), Read(pages))
        self.assertEqual(set(record), {"query", "domains", "candidates", "chosen", "decision", "reason", "page", "quote", "warnings", "elapsed"})
        self.assertEqual(record["decision"], "chosen")
        self.assertEqual(set(record["chosen"]), {"url", "title", "host", "published", "score"})
        self.assertEqual(set(record["candidates"][0]), {"url", "title", "host", "published", "score", "reasons"})
        page = record["page"]
        self.assertEqual(set(page), {"title", "url", "host", "published", "facts", "fetchedAt"})
        self.assertEqual((page["url"], page["host"], page["published"]), (results[0]["url"], "bbc.co.uk", results[0]["published"]))
        self.assertEqual(page["title"], "How boredom fuels creativity - BBC News")
        self.assertEqual(page["fetchedAt"], "2026-09-24T12:00:00Z")
        self.assertEqual(len(page["facts"]), 7)
        self.assertEqual(record["domains"], ["bbc.co.uk"])
        self.assertIsNone(record["quote"])
        self.assertTrue(record["reason"].startswith("Picked “How boredom fuels creativity - BBC News” from bbc.co.uk, published 2 days ago,"), record["reason"])
        self.assertGreaterEqual(record["chosen"]["score"], 0.55)
        self.assertEqual(record["elapsed"], 0.0)

    def test_relevance_ranking_picks_the_on_topic_article(self):
        results = [
            result("https://www.bbc.co.uk/sport/derby", "Late goal settles the derby", days_ago(0), "Football."),
            result("https://www.bbc.co.uk/news/creative", "Daydreaming and creativity", days_ago(3), "Why a wandering mind helps creativity."),
        ]
        pages = {results[0]["url"]: reader(results[0]["title"], off_topic(8)), results[1]["url"]: reader(results[1]["title"], on_topic("creativity"))}
        record = find(spec(about="creativity", domains=["bbc.co.uk"]), Search(results), Read(pages))
        self.assertEqual(record["chosen"]["url"], "https://www.bbc.co.uk/news/creative")
        self.assertEqual(record["candidates"][0]["url"], record["chosen"]["url"])
        self.assertGreater(record["candidates"][0]["score"], record["candidates"][1]["score"])
        self.assertIn("Title mentions creativity", record["candidates"][0]["reasons"])

    def test_unseen_publishers_and_topics_work_the_same_way(self):
        reuters = [
            result("https://www.reuters.com/markets/oil-prices", "Oil prices slip on demand worries", days_ago(1), "Crude."),
            result("https://www.reuters.com/sustainability/solar", "Renewable energy capacity hits a record", days_ago(2), "Solar and wind renewable energy."),
            result("https://www.bbc.co.uk/news/renewables", "Renewable energy in the UK", days_ago(1), "renewable energy"),
        ]
        pages = {r["url"]: reader(r["title"], on_topic("renewable energy") if "Renewable" in r["title"] else off_topic()) for r in reuters}
        search = Search(reuters)
        record = find(spec(query="Reuters story on renewable energy", about="renewable energy", domains=["reuters.com"]), search, Read(pages))
        self.assertEqual(search.calls[0][0], "Reuters story on renewable energy from reuters.com")
        self.assertEqual(record["decision"], "chosen")
        self.assertEqual(record["chosen"]["url"], "https://www.reuters.com/sustainability/solar")
        self.assertNotIn("bbc.co.uk", {c["host"] for c in record["candidates"]})

        nature = [
            result("https://www.nature.com/articles/sleep-1", "Deep sleep clears the brain", days_ago(4), "sleep research"),
            result("https://www.nature.com/articles/quantum-2", "A new quantum material", days_ago(1), "physics"),
        ]
        pages = {nature[0]["url"]: reader(nature[0]["title"], on_topic("sleep research")), nature[1]["url"]: reader(nature[1]["title"], off_topic())}
        record = find(spec(about="sleep research", domains=["nature.com"], publications="Nature", recencyDays=14), Search(nature), Read(pages))
        self.assertEqual(record["chosen"]["url"], "https://www.nature.com/articles/sleep-1")
        self.assertEqual(ar.topic_terms(spec(about="sleep research", domains=["nature.com"], publications="Nature")), {"sleep": 2, "research": 2})

    def test_without_publishers_any_readable_site_counts_and_the_description_steers_the_query(self):
        results = [
            result("https://www.instagram.com/p/1", "Creativity", days_ago(1)),
            result("https://www.sciencenews.org/article/creativity-brain", "The brain on creativity", days_ago(2), "creativity"),
        ]
        pages = {results[1]["url"]: reader(results[1]["title"], on_topic("creativity"))}
        search = Search(results)
        record = find(spec(query="something interesting that relates to creativity", about="creativity", publications="reputable science publications"), search, Read(pages))
        self.assertEqual(search.calls[0][0], "something interesting that relates to creativity reputable science publications")
        self.assertEqual(record["chosen"]["host"], "sciencenews.org")
        self.assertTrue(any("instagram.com" in w for w in record["warnings"]))

    def test_records_are_clipped_and_repeatable(self):
        title = "Creativity " + "x" * 400
        results = [result("https://www.bbc.co.uk/news/long", title, days_ago(1), "creativity")]
        pages = {results[0]["url"]: reader(title, on_topic("creativity"))}
        settings = spec(about="creativity", domains=["bbc.co.uk"])
        first = find(settings, Search(results), Read(pages))
        self.assertLessEqual(len(first["chosen"]["title"]), ar.TITLE_CHARS)
        self.assertLessEqual(len(first["page"]["title"]), ar.TITLE_CHARS)
        self.assertTrue(all(len(r) <= ar.REASON_CHARS for c in first["candidates"] for r in c["reasons"]))
        self.assertEqual(first, find(settings, Search(results), Read(pages)))

    def test_invalid_settings_raise(self):
        for bad in ("find me something", None, {}, {"about": "x", "domains": ["not a domain"]}, {"about": "x", "recencyDays": 0}):
            with self.assertRaises(AlphaError):
                ar.find(bad, search=Search(), read=Read({}), now=NOW)


QUOTE_PAGE_A = """Title: 25 scientist quotes about creativity

Markdown Content:
# Scientist quotes about creativity

“Creativity is intelligence having fun.” — Albert Einstein

"The best way to have a good idea is to have lots of ideas." - Linus Pauling

As Carl Sagan said, “Imagination will often carry us to worlds that never were.”

[Share this quote](https://quotes-a.com/share)
"""

QUOTE_PAGE_B = """Title: Great minds on creativity

Markdown Content:
> "Creativity is intelligence having fun"
>
> — Albert Einstein

“Imagination will often carry us to worlds that never were,” wrote Carl Sagan in 1980.
"""


class QuoteTest(unittest.TestCase):
    settings = spec(query="use a quote from a famous scientist", about="creativity", quote={"about": "a famous scientist"})

    def test_attributions_are_extracted_from_common_layouts(self):
        found = ar.extract_quotes(QUOTE_PAGE_A + "\n“Nothing in life is to be feared, it is only to be understood,” Marie Curie said.\n\nPhysicist Richard Feynman once said: “The first principle is that you must not fool yourself.”\n\n“Stay curious and keep asking questions.”\nNeil deGrasse Tyson\n\nHe said, “this is not a real attribution at all.”\n")
        self.assertEqual(found, [
            ("Creativity is intelligence having fun.", "Albert Einstein"),
            ("The best way to have a good idea is to have lots of ideas.", "Linus Pauling"),
            ("Imagination will often carry us to worlds that never were.", "Carl Sagan"),
            ("Nothing in life is to be feared, it is only to be understood", "Marie Curie"),
            ("The first principle is that you must not fool yourself.", "Richard Feynman"),
            ("Stay curious and keep asking questions.", "Neil deGrasse Tyson"),
        ])

    def test_a_quote_on_two_independent_sites_is_verified(self):
        results = [result("https://quotes-a.com/creativity", "Scientist quotes about creativity"), result("https://www.minds-b.org/creativity", "Great minds on creativity")]
        pages = {results[0]["url"]: {"title": "25 scientist quotes about creativity", "text": QUOTE_PAGE_A}, results[1]["url"]: {"title": "Great minds on creativity", "text": QUOTE_PAGE_B}}
        search = Search(results)
        record = find(self.settings, search, Read(pages))
        self.assertEqual(search.calls[0][0], "famous scientist quotes about creativity")
        self.assertEqual(record["decision"], "chosen")
        quote = record["quote"]
        self.assertEqual((quote["text"], quote["author"], quote["verified"]), ("Creativity is intelligence having fun.", "Albert Einstein", True))
        self.assertEqual(quote["hosts"], ["quotes-a.com", "minds-b.org"])
        self.assertIn("2 independent sites", quote["note"])
        self.assertEqual(record["chosen"]["url"], "https://quotes-a.com/creativity")
        self.assertEqual(set(record["page"]), {"title", "url", "host", "published", "facts", "fetchedAt"})
        self.assertTrue(any("Creativity is intelligence having fun" in fact for fact in record["page"]["facts"]))
        self.assertEqual(record["reason"], "Found a quote by Albert Einstein that 2 independent sites attribute the same way (quotes-a.com, minds-b.org).")

    def test_a_quote_on_one_site_is_not_verified(self):
        results = [result("https://quotes-a.com/creativity", "Scientist quotes about creativity")]
        pages = {results[0]["url"]: {"title": "25 scientist quotes about creativity", "text": QUOTE_PAGE_A}}
        record = find(self.settings, Search(results), Read(pages))
        self.assertEqual(record["decision"], "chosen")
        quote = record["quote"]
        self.assertFalse(quote["verified"])
        self.assertEqual(quote["hosts"], ["quotes-a.com"])
        self.assertEqual(quote["note"], "Attribution could not be confirmed on two independent sites; present it as “often attributed to Albert Einstein” or choose another.")

    def test_two_pages_of_one_site_do_not_verify_a_quote(self):
        results = [result("https://www.quotes-a.com/creativity", "Quotes"), result("https://m.quotes-a.com/creativity", "Quotes")]
        pages = {r["url"]: {"title": "Scientist quotes about creativity", "text": QUOTE_PAGE_A} for r in results}
        record = find(self.settings, Search(results), Read(pages))
        self.assertFalse(record["quote"]["verified"])
        self.assertEqual(record["quote"]["hosts"], ["quotes-a.com"])

    def test_no_quote_is_nothing_worth_and_a_failed_search_is_unavailable(self):
        results = [result("https://quotes-a.com/empty", "Quotes")]
        pages = {results[0]["url"]: reader("Quotes", off_topic())}
        record = find(self.settings, Search(results), Read(pages))
        self.assertEqual(record["decision"], "nothing_worth")
        self.assertIsNone(record["quote"])
        self.assertEqual(record["reason"], "No quote by a famous scientist about “creativity” with a clear attribution turned up, so this run was skipped.")

        failed = find(self.settings, Search(fail=True), Read({}))
        self.assertEqual(failed["decision"], "unavailable")
        self.assertEqual(failed["reason"], "Web search could not be reached after 3 attempts.")
        self.assertIsNone(failed["quote"])

    def test_quotes_about_another_person_and_topic_are_not_hard_coded(self):
        page_one = "Title: Composers on silence\n\n“The music is not in the notes, but in the silence between.” — Wolfgang Amadeus Mozart\n"
        page_two = "Title: Silence\n\nAs Wolfgang Amadeus Mozart said, “The music is not in the notes, but in the silence between.”\n"
        results = [result("https://one.example/silence", "Composers on silence"), result("https://two.example/silence", "Silence")]
        pages = {results[0]["url"]: {"title": "Composers on silence", "text": page_one}, results[1]["url"]: {"title": "Silence", "text": page_two}}
        search = Search(results)
        record = find(spec(about="silence", quote={"about": "a great composer"}), search, Read(pages))
        self.assertEqual(search.calls[0][0], "great composer quotes about silence")
        self.assertTrue(record["quote"]["verified"])
        self.assertEqual(record["quote"]["author"], "Wolfgang Amadeus Mozart")


if __name__ == "__main__":
    unittest.main()
