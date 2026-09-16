"""Web research for a drafting turn (agent chat design §11, Phase 5 slice 1).

When a turn needs facts the workspace does not hold (a topic, a product, a news item, or a pasted
link), PostRiff looks them up before writing instead of declining: search the web, read the best
pages, keep their paragraphs as source facts with provenance. The facts enter the workspace as
ordinary third-party sources, so the existing policy still applies: the draft is a candidate the
person reviews and approves before anything is scheduled. Nothing here publishes.

Backends are plain HTTP so the same code runs on the person's machine and on a hosted API:
`ExaSearch` speaks MCP JSON-RPC to Exa's public search server (the one agent-reach uses), and
`JinaReader` fetches a page as clean text through the r.jina.ai reader. Both are injectable.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ENABLE_ENV = "POSTRIFF_RESEARCH"          # "0" turns web research off for this deployment
EXA_URL_ENV = "POSTRIFF_EXA_MCP_URL"
READER_URL_ENV = "POSTRIFF_READER_URL"
DEFAULT_EXA_URL = "https://mcp.exa.ai/mcp"
DEFAULT_READER_URL = "https://r.jina.ai/"
USER_AGENT = "PostRiff research/0.1"
SEARCH_TIMEOUT = 12
READ_TIMEOUT = 15
TOTAL_BUDGET_SECONDS = 30
MAX_RESULTS = 6
MAX_PAGES = 2
MAX_FACTS = 12
MAX_FACT_CHARS = 500
MIN_FACT_CHARS = 60
MIN_PAGE_CHARS = 400
MAX_PAGE_BYTES = 400_000
# Walled or noisy hosts whose reader text is login prompts, not the article.
SKIP_DOMAINS = {"x.com", "twitter.com", "instagram.com", "facebook.com", "tiktok.com", "linkedin.com", "youtube.com", "youtu.be", "pinterest.com", "threads.net", "reddit.com"}

_URL = re.compile(r"https?://[^\s<>\"'）)\]]+")
# Follow-up edits ("shorter", "another angle", 改短啲) never trigger a search.
_REVISION = re.compile(r"^\s*(?:please\s+)?(?:make (?:it|this|that|them)|shorter|longer|tighter|rewrite|redo|revise|try|again|another|different|change|swap|use|add|remove|drop|cut|keep|fix|translate|more|less|less formal|more casual|same|再|改|短啲|長啲|換|另一|一樣|重寫|翻譯)\b", re.I)
_FIRST_PERSON = re.compile(r"(?<![A-Za-z])(I|I'm|I’m|I've|I’ve|I'd|I’d|my|me|we|we're|we’re|our)(?![A-Za-z])|我|我哋|我們|我们|自己|本人")
_LEAD = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+|help me\s+)?(?:write|draft|create|make|compose|do|prepare|give me|generate)(?:\s+me)?(?:\s+(?:a|an|the|one|some))?(?:\s+(?:short|quick|long|new|linkedin|instagram|threads|facebook|x|twitter))*\s+(?:post|posts|thread|threads|article|caption|piece|update|carousel|story|script|blog)?\s*(?:about|on|regarding|re|covering|introducing)?\s*", re.I)
_CHANNEL_TAIL = re.compile(r"\b(?:for|to|on)\s+(?:linkedin|instagram|threads|facebook|x|twitter|tiktok|youtube|bluesky|mastodon|xiaohongshu|小紅書)\b.*$", re.I)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKUP = re.compile(r"[*_`>#]+")
# Consent banners, cookie tables, newsletter and account prompts read as paragraphs but carry no facts.
_BOILERPLATE = re.compile(r"\b(cookie|cookies|consent|gdpr|privacy policy|terms of (use|service)|all rights reserved|subscribe|newsletter|sign (in|up)|log ?in|create an account|advertis(ing|ement)|analytics|tracking|opt[- ]out|manage (your )?preferences|accept all|reject all)\b", re.I)


def enabled():
    return os.environ.get(ENABLE_ENV, "1") != "0"


def urls_in(text):
    """Distinct http(s) links in the message, in order, trailing punctuation removed."""
    seen, found = set(), []
    for match in _URL.findall(text or ""):
        url = match.rstrip(".,;:!?。，；")
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def needs_research(text, intent="draft", has_facts=False):
    """Research when the message links somewhere or asks for it, or when the idea is about something in
    the world rather than the person's own experience. `has_facts` means the person supplied material
    for this very turn (explicitly selected sources with approved facts), which is then used as is."""
    text = (text or "").strip()
    if urls_in(text):
        return True
    if intent == "research":
        return True
    if has_facts or len(text) < 8 or _REVISION.match(text) or _FIRST_PERSON.search(text):
        return False
    return len(query_for(text).split()) >= 2 or len(query_for(text)) >= 6


def query_for(text):
    """The topic, without the instruction around it: "write me a post about X for LinkedIn" → "X"."""
    query = _URL.sub(" ", text or "")
    query = _LEAD.sub("", query, count=1)
    query = _CHANNEL_TAIL.sub("", query)
    query = re.sub(r"\s+", " ", query).strip(" .,:;-–—\"'“”")
    return query[:200] or (text or "").strip()[:200]


def host_of(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def skip_host(host):
    return any(host == domain or host.endswith("." + domain) for domain in SKIP_DOMAINS)


def paragraphs(text, limit=MAX_FACTS):
    """Readable paragraphs from reader markdown: no navigation, images, headings or link lists."""
    out, seen = [], set()
    for raw in re.split(r"\n\s*\n|\n(?=[-*] )", text or ""):
        line = " ".join(raw.split())
        if not line or line.startswith(("#", "|", "Title:", "URL Source:", "Markdown Content:", "Published Time:")):
            continue
        line = _MARKDOWN_IMAGE.sub("", line)
        links = len(re.findall(r"\]\(", line))
        line = _MARKDOWN_LINK.sub(r"\1", line)
        line = _MARKUP.sub("", line).strip(" -•")
        words = line.split()
        if len(line) < MIN_FACT_CHARS or len(words) < 8 or links > max(2, len(words) // 6) or _BOILERPLATE.search(line):
            continue
        if len(line) > MAX_FACT_CHARS:
            cut = line[:MAX_FACT_CHARS]
            line = cut[: max(cut.rfind(". "), cut.rfind("。"), MAX_FACT_CHARS - 80) + 1].strip() or cut
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= limit:
            break
    return out


def _http(url, headers, timeout, data=None, limit=MAX_PAGE_BYTES):
    request = urllib.request.Request(url, method="POST" if data is not None else "GET", data=data, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, dict(response.headers), response.read(limit).decode("utf-8", "replace")


class ExaSearch:
    """Web search through Exa's MCP server (public, keyless; it refuses requests without a User-Agent)."""

    def __init__(self, url=None, timeout=SEARCH_TIMEOUT):
        self.url = url or os.environ.get(EXA_URL_ENV) or DEFAULT_EXA_URL
        self.timeout = timeout

    def _rpc(self, method, params, session=None, request_id=1):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session:
            headers["Mcp-Session-Id"] = session
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
        status, response_headers, text = self._post(headers, body)
        if "data:" in text:  # server-sent events framing
            text = "".join(line[5:].strip() for line in text.splitlines() if line.startswith("data:"))
        session = next((v for k, v in response_headers.items() if k.lower() == "mcp-session-id"), session)
        return (json.loads(text) if text.strip() else {}), session

    def _post(self, headers, body):
        return _http(self.url, headers, self.timeout, data=body, limit=2_000_000)

    def __call__(self, query, limit=MAX_RESULTS):
        _, session = self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "postriff", "version": "0.1"}})
        result, _ = self._rpc("tools/call", {"name": "web_search_exa", "arguments": {"query": query, "numResults": limit}}, session, 2)
        content = ((result.get("result") or {}).get("content") or [])
        text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        return parse_search_text(text)[:limit]


def parse_search_text(text):
    """Exa's tool text: blocks of `Title:` / `URL:` / `Published:` / `Highlights:` lines."""
    results, current = [], None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:"):
            current = {"title": stripped[6:].strip(), "url": "", "published": "", "snippet": ""}
            results.append(current)
        elif current is not None and stripped.startswith("URL:"):
            current["url"] = stripped[4:].strip()
        elif current is not None and stripped.startswith("Published:"):
            current["published"] = stripped[10:].strip()
        elif current is not None and stripped and not stripped.startswith(("Author:", "Highlights:", "...")):
            current["snippet"] = (current["snippet"] + " " + stripped).strip()[:600]
    return [r for r in results if r["url"].startswith("http")]


class JinaReader:
    """A page as clean text through the reader proxy: `Title:` first line, then markdown content."""

    def __init__(self, base=None, timeout=READ_TIMEOUT):
        self.base = (base or os.environ.get(READER_URL_ENV) or DEFAULT_READER_URL).rstrip("/") + "/"
        self.timeout = timeout

    def __call__(self, url):
        _, _, text = _http(self.base + url, {"Accept": "text/plain"}, self.timeout)
        title = ""
        for line in text.splitlines()[:5]:
            if line.startswith("Title:"):
                title = line[6:].strip()
                break
        return {"title": title, "text": text}


class Researcher:
    """Search, read up to MAX_PAGES pages, keep their paragraphs. Every step is time-boxed and every
    failure becomes a warning, never an exception: a draft with fewer facts beats no draft."""

    def __init__(self, search=None, read=None, clock=time.monotonic, budget=TOTAL_BUDGET_SECONDS, max_pages=MAX_PAGES):
        self.search = search or ExaSearch()
        self.read = read or JinaReader()
        self.clock = clock
        self.budget = budget
        self.max_pages = max_pages

    def run(self, text, intent="draft"):
        started = self.clock()
        query = query_for(text)
        pages, warnings, searched, results = [], [], [], []
        candidates = urls_in(text)
        if not candidates:
            try:
                results = self.search(query, MAX_RESULTS)
            except Exception as error:  # noqa: BLE001 - a search outage must not fail the turn
                warnings.append(f"Web search was unavailable ({type(error).__name__}); the draft used only what the workspace holds.")
            hosts = set()
            for result in results:
                host = host_of(result["url"])
                if not host or skip_host(host) or host in hosts:
                    continue
                hosts.add(host)
                candidates.append(result["url"])
        for url in candidates:
            if len(pages) >= self.max_pages:
                break
            if self.clock() - started > self.budget:
                warnings.append("Research stopped at its time limit; later pages were not read.")
                break
            searched.append(url)
            try:
                page = self.read(url)
            except Exception as error:  # noqa: BLE001
                warnings.append(f"Could not read {host_of(url) or url} ({type(error).__name__}).")
                continue
            facts = paragraphs(page.get("text", ""))
            if len(page.get("text", "")) < MIN_PAGE_CHARS or len(facts) < 2:
                warnings.append(f"{host_of(url) or url} had no readable article text.")
                continue
            meta = next((r for r in results if r["url"] == url), {})
            pages.append({"title": (page.get("title") or meta.get("title") or host_of(url) or url)[:200], "url": url, "host": host_of(url), "published": meta.get("published", ""), "facts": facts, "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        if not pages and not any("unavailable" in w for w in warnings):
            warnings.append(f"Web research found nothing readable for “{query}”." if query else "Web research found nothing readable.")
        return {"query": query, "pages": pages, "searched": searched, "warnings": warnings, "elapsed": round(self.clock() - started, 2)}


def source_title(page):
    return f"{page['title']} — {page['host']}"[:200] if page.get("host") else page["title"][:200]


def source_body(page):
    """What is stored as the source text: one paragraph per fact, so the workspace's own
    paragraph-splitting yields exactly these facts."""
    return "\n\n".join(page["facts"])


def summary(research):
    """Content-free record for the run and the assistant message."""
    return {"query": research["query"], "pages": [{"title": p["title"], "url": p["url"], "facts": len(p["facts"]), "fetchedAt": p["fetchedAt"]} for p in research["pages"]],
            "searched": research["searched"], "warnings": research["warnings"], "elapsed": research["elapsed"]}
