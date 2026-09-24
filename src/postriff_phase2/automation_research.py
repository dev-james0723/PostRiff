"""The research step of an automation run: find one article worth posting about, or one well-attributed quote.

A person describes the step in their own words: "every Wednesday find a notable BBC News article about X", "find
something interesting from a reputable science publication that relates to creativity; skip the week if nothing is
genuinely worth posting", "use a quote from a famous scientist". workflow.normalize_research turns that into settings;
`find` turns the settings into one decision the run can act on and explain afterwards:

    chosen         a readable, recent, on-topic article from an allowed publisher cleared the bar (or a quote was found)
    nothing_worth  the backends answered but nothing cleared the bar; the caller skips the run when onNothing is "skip"
    unavailable    search or reading failed outright (the run's source_unavailable), which is not "nothing good"

Why it works this way:
- The person's constraints are enforced, not suggested. Exa's web_search_exa takes only {query, numResults} and has
  no domain filter, so the publisher goes into the query words to steer the search and every result is then checked
  by host. "BBC only" means results from other sites are set aside and never used. A free-text description such as
  "reputable science publications" cannot be enforced, so it only steers the query.
- Every score can be explained. A candidate carries plain reasons (topic words matched, readable text, age,
  publisher), so run history can say why one article was picked and another was not.
- Nothing is tied to a publisher or a topic: every word comes from the settings.
- A quote counts as verified only when two independent sites carry the same words with the same author. With one
  site it is not verified, and the draft must say "often attributed to".
- Backends are injected. Every failure is retried, then recorded as a warning. Nothing here raises for a backend
  failure, and nothing here publishes. The same backend answers and clocks always give the same record.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import re
import time
import unicodedata
from collections import Counter

from postriff_alpha.domain import AlphaError
from postriff_phase2 import research, workflow

MAX_CANDIDATES = 8
MAX_DOMAIN_SEARCHES = 3        # one search per named publisher, up to this many per run
SEARCH_LIMIT = 8
SEARCH_ATTEMPTS = research.SEARCH_ATTEMPTS
READ_ATTEMPTS = research.READ_ATTEMPTS
RETRY_DELAY_SECONDS = research.RETRY_DELAY_SECONDS
MIN_FACTS = 3                  # a readable article has at least this many prose paragraphs ...
MIN_PAGE_CHARS = research.MIN_PAGE_CHARS   # ... and at least this much text
FULL_QUALITY_FACTS = 6
TITLE_CHARS = 200
QUOTE_CHARS = 400
REASON_CHARS = 200
QUERY_CHARS = 300
DAY = 86400

# score = relevance × (BASE + (1 − BASE) × support). Topic relevance dominates, so an off-topic article cannot clear
# the bar however fresh or well written it is. Support blends readability, date and publisher.
BASE = 0.55
SUPPORT = {"quality": 0.4, "recency": 0.35, "source": 0.25}
RELEVANCE = {"title": 0.35, "body": 0.40, "focus": 0.25}   # after reading; the listing uses title and snippet equally
UNREAD_QUALITY = 0.6           # readability is unknown until the page is opened
UNDATED_RECENCY = 0.5          # an unknown date counts like the oldest article still inside the window
ANY_SOURCE = 0.7               # no publisher was named, so any readable site counts, a little less
NEUTRAL_RELEVANCE = 0.6        # the settings name no topic words at all

UNVERIFIED_NOTE = "Attribution could not be confirmed on two independent sites; present it as “often attributed to {author}” or choose another."

# Request words ("find", "notable", "article", "this week") and grammar words say nothing about the topic.
STOPWORDS = frozenset("""
a an the and or but nor if then than so as of to in on at by for with from into onto over under about above below
between through during before after up down out off again further once
is are was were be been being am do does did doing have has had having
it its this that these those there here what which who whom whose when where why how
i me my mine we us our ours you your yours he him his she her hers they them their theirs one ones
not no yes very too also just only even still more most less least much many some any each every all both either
neither other such own same can could will would shall should may might must need let
find finding look looking search get pick choose use using share sharing post posting write writing draft make
something anything everything nothing thing stuff someone anyone
notable interesting good great best top nice worth worthy genuine genuinely really truly
article story piece item link headline news latest recent recently new newest
relate related relating relevant regarding concerning around
reputable trusted credible publication publisher source site website outlet
quote quotation famous well known
week weekly day daily month monthly year yearly today tonight tomorrow yesterday
monday tuesday wednesday thursday friday saturday sunday morning afternoon evening
www com org net http https
""".split())

_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_PUBLISHED_LINE = re.compile(r"^Published Time:\s*(\S.*)$", re.M)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?")
_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.I)
# When the run happens and the command itself are not search words: "Every Wednesday find a notable …" → "a notable …".
_SCHEDULE = re.compile(r"\b(?:every|each)\s+(?:other\s+)?(?:day|week|month|morning|evening|weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b,?", re.I)
_COMMAND = re.compile(r"^\s*(?:please\s+)?(?:find|look for|search for|get|pick|choose|share|post)(?:\s+me)?\s+", re.I)
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go"}

# --- quotes: attribution patterns ---------------------------------------------------------------------------------
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKUP = re.compile(r"[*_`>#]+")
_CAP = "A-ZÀ-ÖØ-ÞĀ-ſ"
_NAME_TOKEN = rf"[{_CAP}][\w'’.\-]*"
_PARTICLE = r"(?:de|da|di|del|della|van|von|der|den|la|le|du|bin|ibn|al|y)"
_NAME = rf"(?P<a>{_NAME_TOKEN}(?:\s+(?:{_PARTICLE}\s+)?{_PARTICLE}?{_NAME_TOKEN}){{0,3}})"   # "van Gogh", "deGrasse"
_Q = r"(?P<q>[^“”\"«»]{12,400}?)"
_OPEN = r"(?:“|«|(?<![\w\"])\")"
_CLOSE = r"(?:”|»|\"(?!\w))"
_DASH = r"(?:—|–|―|--?|~)"
_VERB = r"(?:famously said|once said|once wrote|put it|said|says|wrote|writes|observed|remarked|noted|declared)"
QUOTE_PATTERNS = [re.compile(p) for p in (
    rf"{_OPEN}{_Q}{_CLOSE}\s*[,.]?\s*{_DASH}\s*{_NAME}",           # “…” — Name
    rf"{_OPEN}{_Q}{_CLOSE}\s*,?\s*{_VERB}\s+{_NAME}",              # “…,” said Name
    rf"{_OPEN}{_Q}{_CLOSE}\s*,?\s*{_NAME}\s+{_VERB}\b",            # “…,” Name wrote
    rf"\b[Aa]s\s+{_NAME}\s+{_VERB}\s*[,:]?\s*{_OPEN}{_Q}{_CLOSE}",  # As Name said, “…”
    rf"{_NAME}\s+{_VERB}\s*[,:]\s*{_OPEN}{_Q}{_CLOSE}",            # Name said: “…”
)]
_ATTRIBUTION_LINE = re.compile(rf"^{_DASH}\s*[{_CAP}]")
_QUOTE_LINE = re.compile(r"^[“\"«].{12,400}[”\"»]$")
_NAME_LINE = re.compile(rf"^{_NAME}$")
# Words that start a sentence or describe the person rather than name them ("Physicist Richard Feynman said").
_LEADING = {"As", "And", "But", "So", "Then", "When", "While", "Here", "Once", "Later", "Famously", "Dr", "Dr.", "Prof", "Prof.", "Professor",
            "Physicist", "Scientist", "Chemist", "Biologist", "Mathematician", "Astronomer", "Astrophysicist", "Inventor", "Engineer",
            "Naturalist", "Author", "Writer", "Novelist", "Poet", "Philosopher", "Painter", "Composer", "Pianist", "Artist",
            "Economist", "Psychologist", "Neuroscientist"}
_NOT_A_NAME = {"He", "She", "They", "It", "I", "We", "You", "One", "Someone", "Anonymous", "Unknown", "The", "A", "An", "This", "That",
               "Source", "Photo", "Image", "Getty", "Share", "Read", "Tweet", "Click", "Quote", "Quotes"}
_TRAILING = {"Share", "Read", "More", "Tweet", "Click", "Copy", "Like", "Save", "Quote", "Quotes", "Image", "Photo", "Source", "Via"}


# --- small helpers ------------------------------------------------------------------------------------------------
def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _fold(text):
    """Lowercase, accents removed, curly apostrophes straightened: "Café’s" → "cafe's"."""
    text = unicodedata.normalize("NFKD", str(text or "")).replace("’", "'").replace("‘", "'")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _stem(word):
    """Simple plural folding, the same on both sides of a comparison: studies → study, researchers → researcher."""
    word = word.strip("'")
    if word.endswith("'s"):
        word = word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes", "zzes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _tokens(text):
    return {_stem(word) for word in _WORD.findall(_fold(text))}


def words(text):
    """The meaningful words of `text`, in order and once each: lowercase, stopwords removed, plurals folded."""
    out = []
    for raw in _WORD.findall(_fold(text)):
        word = _stem(raw)
        if len(word) < 2 or raw in STOPWORDS or word in STOPWORDS or word in out:
            continue
        out.append(word)
    return out


def topic(spec):
    """The subject in the person's words for the search query, without the schedule or the command around it."""
    query = " ".join(_COMMAND.sub("", " ".join(_SCHEDULE.sub(" ", spec.get("query") or "").split()), count=1).split())
    about = spec.get("about") or ""
    if about and about.lower() not in query.lower():
        return f"{query} {about}".strip()
    return query or about


def topic_terms(spec):
    """Words a candidate should mention, weighted: `about` (the subject) counts double, the query once. The
    publisher's own words ("BBC", "Nature", "science publications") are dropped: every page there carries them."""
    publisher = set()
    for domain in spec.get("domains") or []:
        publisher.update(domain.split("."))
    publisher.update(words(spec.get("publications") or ""))
    terms = {}
    for word in words(spec.get("query") or ""):
        if word not in publisher:
            terms.setdefault(word, 1)
    for word in words(spec.get("about") or ""):
        if word not in publisher:
            terms[word] = 2
    return terms


def host_allowed(host, domains):
    """A host belongs to an allowed publisher when it is the domain or a subdomain of it: bbc.co.uk allows
    www.bbc.co.uk and news.bbc.co.uk, never bbc.co.uk.evil.com or notbbc.co.uk."""
    host = (host or "").lower().rstrip(".").removeprefix("www.")
    return bool(host) and any(host == domain or host.endswith("." + domain) for domain in domains)


def site_of(host):
    """The site a host belongs to, so two subdomains of one publisher never count as independent:
    news.bbc.co.uk → bbc.co.uk, m.example.com → example.com."""
    labels = (host or "").lower().removeprefix("www.").split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def published_at(value):
    """Epoch seconds for "2026-09-09", "2026-09-09T10:34:56.084Z" or an RFC 2822 date; None when unknown."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return None
    parsed = None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            match = _DATE.search(text)
            if match:
                try:
                    parsed = dt.datetime(*(int(part or 0) for part in match.groups()))
                except ValueError:
                    parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def _age(ts, now):
    days = max(0.0, (now - ts) / DAY)
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    return f"{int(days)} days ago"


def _coverage(terms, tokens):
    total = sum(terms.values())
    return sum(weight for term, weight in terms.items() if term in tokens) / total if total else 0.0


def _title_reason(terms, title):
    hit = [term for term in terms if term in _tokens(title)]
    return ("Title mentions " + ", ".join(hit[:5])) if hit else ("Title does not mention " + ", ".join(list(terms)[:5]))


def score(relevance, quality, recency, source):
    """One number in [0, 1]: relevance scaled by how readable, recent and well sourced the candidate is."""
    support = SUPPORT["quality"] * quality + SUPPORT["recency"] * recency + SUPPORT["source"] * source
    return round(max(0.0, min(1.0, relevance * (BASE + (1 - BASE) * support))), 3)


def listing_relevance(terms, title, snippet):
    """Relevance from a search listing (before the page is opened)."""
    if not terms:
        return NEUTRAL_RELEVANCE, ["No topic words to match; judged on readability, date and publisher"]
    title_cov = _coverage(terms, _tokens(title))
    listing_cov = _coverage(terms, _tokens(f"{title} {snippet}"))
    hit = sum(1 for term in terms if term in _tokens(f"{title} {snippet}"))
    return 0.5 * title_cov + 0.5 * listing_cov, [_title_reason(terms, title), f"Search listing mentions {hit} of {len(terms)} topic words"]


def page_relevance(terms, title, facts):
    """Relevance from the article itself: the title, how many topic words the text covers, and how much of the
    text is about them (a single passing mention in a long article is not "about creativity")."""
    if not terms:
        return NEUTRAL_RELEVANCE, ["No topic words to match; judged on readability, date and publisher"]
    body = set().union(*(_tokens(fact) for fact in facts)) if facts else set()
    on_topic = sum(1 for fact in facts if _tokens(fact) & terms.keys())
    focus = min(1.0, 2 * on_topic / len(facts)) if facts else 0.0
    relevance = RELEVANCE["title"] * _coverage(terms, _tokens(title)) + RELEVANCE["body"] * _coverage(terms, body) + RELEVANCE["focus"] * focus
    hit = sum(1 for term in terms if term in body)
    return relevance, [_title_reason(terms, title), f"Text mentions {hit} of {len(terms)} topic words; {on_topic} of {len(facts)} paragraphs are on topic"]


def _listing(results):
    out = []
    for item in results if isinstance(results, (list, tuple)) else []:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.strip().startswith(("http://", "https://")):
            out.append({"url": url.strip(), "title": str(item.get("title") or ""), "published": str(item.get("published") or ""), "snippet": str(item.get("snippet") or "")})
    return out


def _url_key(url):
    return url.split("#", 1)[0].rstrip("/")


def _where(spec):
    """Where the person asked Raffi to look, in their terms."""
    domains = spec["domains"]
    if domains:
        shown = " or ".join(domains[:3])
        return shown + (" and the other publishers you named" if len(domains) > 3 else "")
    return spec.get("publications") or "the web"


def _window(days):
    return "the last day" if days == 1 else f"the last {days} days"


def _then(spec):
    return "so this run was skipped" if spec["onNothing"] == "skip" else "so the draft goes ahead without an article"


# --- quotes -------------------------------------------------------------------------------------------------------
def _quote_key(text):
    return " ".join(re.sub(r"[^\w]+", " ", _fold(text)).split())


def _author(raw):
    """A clean author name, or "" when the capture is a pronoun, a caption or a sentence fragment."""
    tokens = raw.replace("’", "'").split()
    while tokens and tokens[0].rstrip(".,") in _LEADING:
        tokens.pop(0)
    for index, token in enumerate(tokens):
        if token.rstrip(".,") in _TRAILING:
            tokens = tokens[:index]
            break
    tokens = [token.rstrip(",;:") for token in tokens]
    if tokens:
        tokens[-1] = tokens[-1].rstrip(".").removesuffix("'s")
    if not tokens or tokens[0] in _NOT_A_NAME or tokens[-1] in _NOT_A_NAME or len(tokens[-1]) < 2:
        return ""
    if not all(token[0].isupper() or re.fullmatch(_PARTICLE, token) or re.match(rf"{_PARTICLE}[{_CAP}]", token) for token in tokens):
        return ""
    return " ".join(tokens)


def _lines(text):
    """Reader text as lines of plain prose. An attribution on its own line ("— Albert Einstein", or a bare name under
    a quote, as quote sites lay them out) is joined to the quote above it."""
    lines = []
    for raw in (text or "").splitlines():
        line = _MARKDOWN_LINK.sub(r"\1", _MARKDOWN_IMAGE.sub("", raw))
        line = " ".join(_MARKUP.sub(" ", line).split())
        if not line:
            continue
        previous = lines[-1] if lines else ""
        if previous.endswith(("”", '"', "»")) and _ATTRIBUTION_LINE.match(line):
            lines[-1] = f"{previous} {line}"
        elif _QUOTE_LINE.match(previous) and len(line.split()) <= 4 and _NAME_LINE.match(line):
            lines[-1] = f"{previous} — {line}"
        else:
            lines.append(line)
    return lines


def extract_quotes(text):
    """Attributed quotes on a page as [(quote, author)], in page order, each once: “…” — Name, “…,” said Name,
    “…,” Name wrote, As Name said, “…”, Name said: “…”. Curly or straight quotation marks."""
    found, seen = [], set()
    for line in _lines(text):
        hits = []
        for pattern in QUOTE_PATTERNS:
            for match in pattern.finditer(line):
                hits.append((match.start("q"), match.group("q"), match.group("a")))
        for _, quote, raw_author in sorted(hits, key=lambda hit: hit[0]):
            quote = " ".join(quote.split()).strip(" ,;:")
            author = _author(raw_author)
            if not author or len(quote.split()) < 3 or "http" in quote or "](" in quote or "|" in quote:
                continue
            surname = _quote_key(author).split()
            key = (_quote_key(quote), surname[-1] if surname else "")
            if not surname or key in seen:
                continue
            seen.add(key)
            found.append((_clip(quote, QUOTE_CHARS), author))
    return found


# --- the run ------------------------------------------------------------------------------------------------------
class _Run:
    def __init__(self, spec, search, read, now, clock, budget, max_reads, sleep):
        self.spec, self.search, self.read, self.now = spec, search, read, float(now)
        self.clock, self.budget, self.max_reads, self.sleep = clock, budget, max(0, int(max_reads)), sleep
        self.terms = topic_terms(spec)
        self.warnings = []
        self.started = clock()

    def warn(self, text):
        text = _clip(text, REASON_CHARS)
        if text not in self.warnings:
            self.warnings.append(text)

    def out_of_time(self):
        return self.clock() - self.started > self.budget

    def attempt(self, call, attempts):
        """research.Researcher._attempt with the number of tries: run `call` up to `attempts` times inside the budget."""
        error, tries = None, 0
        for attempt in range(attempts):
            if attempt and self.out_of_time():
                break
            tries += 1
            try:
                return call(), None, tries
            except Exception as caught:  # noqa: BLE001 - a backend failure is recorded, never raised
                error = caught
                if attempt + 1 < attempts:
                    self.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
        return None, error, tries

    def open(self, url):
        page, error, tries = self.attempt(lambda: self.read(url), READ_ATTEMPTS)
        if error is not None:
            return None, error, tries
        page = page if isinstance(page, dict) else {}
        return {"title": str(page.get("title") or ""), "text": str(page.get("text") or "")}, None, tries

    def candidate(self, pool, seen, url, meta, supplied):
        key = _url_key(url)
        if key in seen:
            return None
        seen.add(key)
        entry = {"url": url, "host": research.host_of(url), "title": meta.get("title", ""), "published": meta.get("published", ""),
                 "snippet": meta.get("snippet", ""), "supplied": supplied, "order": len(pool), "state": "listed", "score": 0.0, "reasons": [],
                 "facts": [], "text": ""}
        pool.append(entry)
        return entry

    def page(self, entry, facts):
        """The chosen page in research.py's shape, so the caller stores it as a source like IdeasService._research."""
        return {"title": _clip(entry["title"] or entry["host"] or entry["url"], TITLE_CHARS), "url": entry["url"], "host": entry["host"],
                "published": entry["published"], "facts": list(facts), "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now))}

    def record(self, query, pool, chosen, decision, reason, page=None, quote=None, rank=None):
        order = {"read": 0, "listed": 1, "unreadable": 2, "failed": 2, "old": 3}
        ranked = sorted(pool, key=rank or (lambda c: (order[c["state"]], -c["score"], c["order"])))[:MAX_CANDIDATES]
        candidates = [{"url": c["url"], "title": _clip(c["title"] or c["host"], TITLE_CHARS), "host": c["host"], "published": c["published"],
                       "score": c["score"], "reasons": [_clip(r, REASON_CHARS) for r in c["reasons"]]} for c in ranked]
        chosen_record = None
        if chosen is not None:
            chosen_record = {"url": chosen["url"], "title": _clip(chosen["title"] or chosen["host"], TITLE_CHARS), "host": chosen["host"],
                             "published": chosen["published"], "score": chosen["score"]}
        return {"query": _clip(query, QUERY_CHARS), "domains": list(self.spec["domains"]), "candidates": candidates, "chosen": chosen_record,
                "decision": decision, "reason": _clip(reason, 300), "page": page, "quote": quote, "warnings": list(self.warnings),
                "elapsed": round(self.clock() - self.started, 2)}

    # --- articles -----------------------------------------------------------------------------------------------
    def queries(self):
        subject = topic(self.spec)
        if self.spec["domains"]:
            if len(self.spec["domains"]) > MAX_DOMAIN_SEARCHES:
                self.warn(f"Only the first {MAX_DOMAIN_SEARCHES} publishers were searched this time.")
            return [_clip(f"{subject} from {domain}", QUERY_CHARS) for domain in self.spec["domains"][:MAX_DOMAIN_SEARCHES]]
        return [_clip(f"{subject} {self.spec['publications']}".strip(), QUERY_CHARS)]

    def recency(self, entry):
        """(credit, reason, too old) for a candidate's publication date."""
        days = self.spec["recencyDays"]
        ts = published_at(entry["published"])
        if ts is None:
            return UNDATED_RECENCY, "Publication date unknown, so it counts a little less", False
        if ts < self.now - days * DAY:
            return 0.0, f"Published {_age(ts, self.now)}, outside the {days}-day window", True
        age = max(0.0, (self.now - ts) / DAY)
        return 1 - 0.5 * (age / days), f"Published {_age(ts, self.now)}", False

    def source(self, entry):
        if entry["supplied"]:
            return 1.0, "A link you supplied, so its publisher and date are not held against it"
        if self.spec["domains"]:
            return 1.0, f"From {entry['host']}, a publisher you named"
        return ANY_SOURCE, f"From {entry['host']}; no publisher was named, so any readable site counts"

    def judge(self, entry, page):
        """Score an opened page, or mark it too old or unreadable."""
        text = page["text"]
        facts = research.paragraphs(text)
        entry["title"] = page["title"] or entry["title"] or entry["host"]
        if not entry["published"]:
            match = _PUBLISHED_LINE.search("\n".join(text.splitlines()[:40]))
            entry["published"] = match.group(1).strip()[:40] if match else ""
        source, source_why = self.source(entry)
        if entry["supplied"]:
            recency, recency_why = 1.0, None
        else:
            recency, recency_why, too_old = self.recency(entry)
            if too_old:
                entry.update(state="old", score=0.0, reasons=[recency_why])
                return
        if len(text) < MIN_PAGE_CHARS or len(facts) < MIN_FACTS:
            entry.update(state="unreadable", score=0.0, reasons=["No readable article text"])
            return
        relevance, why = page_relevance(self.terms, entry["title"], facts)
        quality = min(1.0, len(facts) / FULL_QUALITY_FACTS)
        entry["score"] = score(relevance, quality, recency, source)
        entry["reasons"] = [*why, f"Readable article ({len(facts)} paragraphs)", *([recency_why] if recency_why else []), source_why,
                            f"Score {entry['score']:.2f} against a bar of {self.spec['minScore']:.2f}"]
        entry.update(state="read", facts=facts)

    def articles(self):
        spec = self.spec
        pool, seen, set_aside, walled = [], set(), [], []
        for url in spec["urls"]:
            self.candidate(pool, seen, url, {}, True)
        queries = self.queries()
        searched = failed = 0
        failure = None
        for query in queries:
            if self.out_of_time():
                self.warn("Research stopped at its time limit before every search ran.")
                break
            results, error, tries = self.attempt(lambda q=query: self.search(q, SEARCH_LIMIT), SEARCH_ATTEMPTS)
            searched += 1
            if error is not None:
                failed, failure = failed + 1, (error, tries)
                continue
            for item in _listing(results):
                host = research.host_of(item["url"])
                if not host:
                    continue
                if research.skip_host(host):
                    walled.append(host)
                elif spec["domains"] and not host_allowed(host, spec["domains"]):
                    set_aside.append(host)
                else:
                    self.candidate(pool, seen, item["url"], item, False)
        if failure and failed < searched:
            self.warn(f"{failed} of {searched} searches failed ({type(failure[0]).__name__}); the others were used.")
        if set_aside:
            hosts = list(dict.fromkeys(set_aside))
            self.warn(f"Set aside {len(set_aside)} result(s) from other sites ({', '.join(hosts[:4])}); only {_where(spec)} was allowed.")
        if walled:
            self.warn(f"Skipped {', '.join(list(dict.fromkeys(walled))[:4])}: pages there cannot be read without an account.")

        # Score every listing first, so the most promising pages are the ones opened.
        for entry in pool:
            if entry["supplied"]:
                continue
            recency, recency_why, too_old = self.recency(entry)
            if too_old:
                entry.update(state="old", score=0.0, reasons=[recency_why])
                continue
            source, source_why = self.source(entry)
            relevance, why = listing_relevance(self.terms, entry["title"], entry["snippet"])
            entry["score"] = score(relevance, UNREAD_QUALITY, recency, source)
            entry["reasons"] = [*why, recency_why, source_why]

        to_open = [e for e in pool if e["supplied"]] + sorted((e for e in pool if not e["supplied"] and e["state"] == "listed"), key=lambda e: (-e["score"], e["order"]))
        opened = opened_ok = 0
        stop = f"the reading limit of {self.max_reads} was reached"
        read_error = None
        for entry in to_open:
            if opened >= self.max_reads:
                break
            if self.out_of_time():
                self.warn("Research stopped at its time limit; later candidates were not opened.")
                stop = "the time limit was reached"
                break
            opened += 1
            page, error, tries = self.open(entry["url"])
            if error is not None:
                read_error = error
                entry.update(state="failed", score=0.0, reasons=[f"Could not be opened after {tries} attempt{'s' if tries != 1 else ''} ({type(error).__name__})"])
                self.warn(f"Could not open {entry['host'] or entry['url']} ({type(error).__name__}).")
                continue
            opened_ok += 1
            self.judge(entry, page)
        for entry in pool:
            if entry["state"] == "listed":
                if entry["supplied"]:
                    entry["reasons"] = ["A link you supplied", f"Not opened ({stop})"]
                else:
                    entry["reasons"].append(f"Not opened ({stop}); scored from its search listing")

        readable = sorted((e for e in pool if e["state"] == "read"), key=lambda e: (-e["score"], not e["supplied"], e["order"]))
        best = readable[0] if readable and readable[0]["score"] >= spec["minScore"] else None
        query = "; ".join(queries)
        subject = _clip(spec["about"] or spec["query"], 80)
        if best is not None:
            ts = published_at(best["published"])
            when = f", published {_age(ts, self.now)}," if ts is not None else ""
            reason = f"Picked “{_clip(best['title'], 80)}” from {best['host']}{when} as the strongest match for “{subject}”; it cleared the quality bar."
            return self.record(query, pool, best, "chosen", reason, page=self.page(best, best["facts"]))
        if searched and failed == searched:
            where = " or ".join(spec["domains"][:MAX_DOMAIN_SEARCHES]) if spec["domains"] else "Web search"
            return self.record(query, pool, None, "unavailable", f"{where} could not be reached after {failure[1]} attempts.")
        if opened and not opened_ok:
            hosts = ", ".join(dict.fromkeys(e["host"] for e in pool if e["state"] == "failed")) or "the pages found"
            return self.record(query, pool, None, "unavailable", f"The articles found on {hosts} could not be opened after {READ_ATTEMPTS} attempts each ({type(read_error).__name__}).")
        if pool and all(e["state"] == "old" for e in pool):
            reason = f"Only articles older than {spec['recencyDays']} days turned up from {_where(spec)} for “{subject}”, {_then(spec)}."
        elif pool:
            reason = f"Nothing from {_where(spec)} in {_window(spec['recencyDays'])} cleared the bar for “{subject}”, {_then(spec)}."
        else:
            reason = f"Nothing from {_where(spec)} in {_window(spec['recencyDays'])} turned up for “{subject}”, {_then(spec)}."
        return self.record(query, pool, None, "nothing_worth", reason)

    # --- quotes -------------------------------------------------------------------------------------------------
    def quotes(self):
        spec = self.spec
        who = _ARTICLE.sub("", spec["quote"]["about"]).strip() or "notable person"
        # The subject, not the request sentence: "use a quote from a famous scientist" adds nothing to "famous scientist".
        subject = spec["about"] or " ".join(w for w in words(spec["query"]) if w not in words(who))
        query = _clip(f"{who} quotes about {subject}" if subject else f"{who} quotes", QUERY_CHARS)
        if spec["domains"]:
            self.warn("Quotes are checked across independent sites, so the publisher list was not applied to the quote search.")
        pool, seen, walled = [], set(), []
        for url in spec["urls"]:
            self.candidate(pool, seen, url, {}, True)
        results, error, search_tries = self.attempt(lambda: self.search(query, SEARCH_LIMIT), SEARCH_ATTEMPTS)
        search_down = error is not None
        for item in _listing(results):
            host = research.host_of(item["url"])
            if not host:
                continue
            if research.skip_host(host):
                walled.append(host)
                continue
            self.candidate(pool, seen, item["url"], item, False)
        if walled:
            self.warn(f"Skipped {', '.join(list(dict.fromkeys(walled))[:4])}: pages there cannot be read without an account.")
        for entry in pool:
            relevance, why = listing_relevance(self.terms, entry["title"], entry["snippet"])
            entry["score"] = round(relevance, 3)
            entry["reasons"] = why if not entry["supplied"] else ["A link you supplied"]

        # One page per site before a second page from any site: two pages of one site cannot verify a quote.
        first, rest, sites = [], [], set()
        for entry in [e for e in pool if e["supplied"]] + [e for e in pool if not e["supplied"]]:
            (rest if site_of(entry["host"]) in sites else first).append(entry)
            sites.add(site_of(entry["host"]))
        groups, opened, opened_ok, read_error = {}, 0, 0, None
        for entry in first + rest:
            if opened >= self.max_reads:
                break
            if self.out_of_time():
                self.warn("Research stopped at its time limit; later pages were not opened.")
                break
            opened += 1
            page, error, tries = self.open(entry["url"])
            if error is not None:
                read_error = error
                entry.update(state="failed", reasons=[f"Could not be opened after {tries} attempt{'s' if tries != 1 else ''} ({type(error).__name__})"])
                self.warn(f"Could not open {entry['host'] or entry['url']} ({type(error).__name__}).")
                continue
            opened_ok += 1
            entry["title"] = page["title"] or entry["title"] or entry["host"]
            entry["text"] = page["text"]
            found = extract_quotes(page["text"])
            entry["state"] = "read" if found else "unreadable"
            entry["reasons"] = [*entry["reasons"], f"{len(found)} attributed quote{'s' if len(found) != 1 else ''} found" if found else "No attributed quotes found"]
            for text, author in found:
                key = (_quote_key(text), _quote_key(author).split()[-1])   # same words, same surname (extract_quotes ensures one)
                group = groups.setdefault(key, {"text": text, "authors": [], "sites": {}, "pages": [], "order": len(groups)})
                group["authors"].append(author)
                group["sites"].setdefault(site_of(entry["host"]), entry["host"])
                if entry not in group["pages"]:
                    group["pages"].append(entry)

        def relevance(group):
            if not self.terms:
                return 0.0
            return max([_coverage(self.terms, _tokens(group["text"]))] + [0.5 * _coverage(self.terms, _tokens(p["title"])) for p in group["pages"]])

        best = max(groups.values(), key=lambda g: (relevance(g) > 0, len(g["sites"]) >= 2, len(g["sites"]), relevance(g), -g["order"]), default=None)
        if best is None:
            if search_down and not opened_ok:
                return self.record(query, pool, None, "unavailable", f"Web search could not be reached after {search_tries} attempts.")
            if opened and not opened_ok:
                return self.record(query, pool, None, "unavailable", f"The pages found could not be opened after {READ_ATTEMPTS} attempts each ({type(read_error).__name__}).")
            about = f" about “{_clip(spec['about'] or spec['query'], 80)}”" if (spec["about"] or spec["query"]) else ""
            then = "so this run was skipped" if spec["onNothing"] == "skip" else "so the draft goes ahead without a quote"
            return self.record(query, pool, None, "nothing_worth", f"No quote by {spec['quote']['about']}{about} with a clear attribution turned up, {then}.")
        author = Counter(best["authors"]).most_common(1)[0][0]
        hosts = list(best["sites"].values())
        verified = len(hosts) >= 2
        if verified:
            note = f"Found with the same words and author on {len(hosts)} independent sites."
            reason = f"Found a quote by {author} that {len(hosts)} independent sites attribute the same way ({', '.join(hosts[:3])})."
        else:
            note = UNVERIFIED_NOTE.format(author=author)
            reason = f"Found a quote attributed to {author}, but only {hosts[0]} carries it, so the attribution is not verified."
        for entry in best["pages"]:
            entry["reasons"].append("Carries the chosen quote")
        source = best["pages"][0]
        facts = research.paragraphs(source["text"])
        if not any(_quote_key(best["text"]) in _quote_key(fact) for fact in facts):
            facts = [f"“{best['text']}” — {author}", *facts][: research.MAX_FACTS]
        quote = {"text": _clip(best["text"], QUOTE_CHARS), "author": _clip(author, TITLE_CHARS), "verified": verified, "hosts": hosts, "note": note}
        carries = {entry["order"] for entry in best["pages"]}

        def rank(entry):  # pages carrying the chosen quote first, then pages with quotes, then the rest
            return (entry["order"] not in carries, entry["state"] != "read", -entry["score"], entry["order"])
        return self.record(query, pool, source, "chosen", reason, page=self.page(source, facts), quote=quote, rank=rank)


def find(spec, *, search, read, now, clock=time.monotonic, budget=45, max_reads=4, sleep=time.sleep):
    """Run an automation's research step and return its occurrence record (orchestration §2 `research`, plus the
    chosen `page` for the caller to store as a source). `search(query, limit)` returns [{title,url,published,snippet}];
    `read(url)` returns {title,text}; either may raise. `now` is wall-clock epoch seconds (recency, fetchedAt);
    `clock` measures the time budget. Raises AlphaError only for invalid settings."""
    if not isinstance(spec, dict):
        raise AlphaError("Research settings must be structured.")
    normalized = workflow.normalize_research(spec)
    if normalized is None:
        raise AlphaError("Say what Raffi should look for.")
    run = _Run(normalized, search, read, now, clock, budget, max_reads, sleep)
    return run.quotes() if normalized["quote"] else run.articles()
