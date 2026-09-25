"""Research Broker (adaptive coworker spec §11, §16; architecture lock S1).

One provider abstraction over what research exists today (Exa search + Jina reader, `research.py`), official
owned-post APIs, approved MCP connectors and a local-only Agent Reach runtime. The broker keeps the callables the
existing pipelines already use (`Researcher(search=, read=)`, `automation_research.find(search=, read=)`) and adds
what the spec requires: every acquired item carries provider, platform, query, url, retrieval and publication time,
author, access method, raw content hash, represented scope, evidence type and rights, and fetched text is untrusted
data that is scanned for prompt injection (flagged, never obeyed).

Rules that hold for every provider:
- hosted egress needs the owner's `researchEgress` consent (`research.allowed`), checked by `readiness()`;
- a search result is a *lead* (`evidenceType: search_snippet`); it is never a verified fact;
- a provider failure is reported as a failure with its reason, never as an empty successful retrieval;
- local desktop coverage (Agent Reach) never reports ready on a hosted deployment.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from postriff_alpha.domain import AlphaError

from .. import research

KINDS = ("web_search", "web_reader", "official_api", "mcp", "local_agent_reach", "fixture")
ACCESS = {"web_search": "public_web", "web_reader": "public_web", "official_api": "official_api", "mcp": "mcp",
          "local_agent_reach": "local_desktop", "fixture": "fixture"}
READINESS = ("ready", "not_configured", "consent_required", "local_only", "disabled")
# Instruction-like text inside fetched content. A match is a warning on the item; the text stays data.
INJECTION_PATTERNS = (
    r"ignore (?:all |any |the )?(?:previous|prior|above) (?:instructions|prompts?|rules)",
    r"disregard (?:all |any |the )?(?:previous|prior|above|system)",
    r"you are now (?:a|an|the) ",
    r"(?:system|developer) prompt",
    r"act as (?:a|an) (?:different|new) (?:assistant|ai|agent)",
    r"(?:post|publish|send|tweet|share) (?:this|it) (?:now|immediately|automatically)",
    r"(?:reveal|print|show|leak) (?:your|the) (?:instructions|system prompt|api key|secret|token)",
    r"do not (?:tell|inform|mention (?:this )?to) the user",
    r"</?(?:system|assistant|tool)>",
    r"忽略(?:之前|以上|所有)(?:的)?(?:指示|指令|規則|规则)",
    r"無視(?:之前|以上)(?:的)?(?:指示|指令)",
)
_INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def content_hash(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def injection_flags(text):
    """Prompt-injection markers in fetched content: [{pattern index, excerpt}]. Data is never executed."""
    flags = []
    for index, pattern in enumerate(_INJECTION):
        match = pattern.search(text or "")
        if match:
            start = max(0, match.start() - 30)
            flags.append({"rule": f"injection.{index}", "excerpt": (text[start:match.end() + 30]).replace("\n", " ")[:120]})
    return flags


@dataclass
class Provenance:
    provider: str
    kind: str
    accessMethod: str
    query: str | None = None
    url: str | None = None
    host: str | None = None
    platform: str | None = None
    retrievedAt: float | None = None
    publishedAt: str | None = None
    author: str | None = None
    contentHash: str | None = None
    representedScope: str = "public_web"
    evidenceType: str = "search_snippet"
    rights: dict = field(default_factory=lambda: {"reuse": "reference_only", "sourcePolicy": "rewrite_approval"})
    injectionFlags: list = field(default_factory=list)
    freshnessDays: float | None = None

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()}


def _host(url):
    host = research.host_of(url) if hasattr(research, "host_of") else ""
    if not host:
        from urllib.parse import urlparse
        host = (urlparse(url or "").hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
    return host


def _age_days(published, now):
    if not published:
        return None
    try:
        from datetime import datetime
        stamp = datetime.fromisoformat(str(published).replace("Z", "+00:00")).timestamp()
        return round(max(0.0, (now - stamp) / 86400), 1)
    except ValueError:
        return None


class ResearchProvider:
    """Interface every provider implements (spec §11)."""
    id = "provider"
    kind = "fixture"
    hosted_ok = True

    def capabilities(self):
        return {"operations": [], "platforms": [], "representedScope": "none"}

    def readiness(self, state=None):
        return {"state": "not_configured", "reason": "Not implemented."}

    def search(self, query, scope=None):
        raise AlphaError(f"{self.id} cannot search.", 409, code="provider_unsupported")

    def fetch(self, ref):
        raise AlphaError(f"{self.id} cannot read pages.", 409, code="provider_unsupported")

    def provenance(self, result):
        return result.get("provenance")


def parse_search_with_author(text):
    """Exa's tool text parsed like `research.parse_search_text`, keeping `Author:` lines for provenance."""
    results, current = [], None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:"):
            current = {"title": stripped[6:].strip(), "url": "", "published": "", "snippet": "", "author": ""}
            results.append(current)
        elif current is not None and stripped.startswith("URL:"):
            current["url"] = stripped[4:].strip()
        elif current is not None and stripped.startswith("Published:"):
            current["published"] = stripped[10:].strip()
        elif current is not None and stripped.startswith("Author:"):
            current["author"] = stripped[7:].strip()[:120]
        elif current is not None and stripped and not stripped.startswith(("Highlights:", "...")):
            current["snippet"] = (current["snippet"] + " " + stripped).strip()[:600]
    return [r for r in results if r["url"].startswith("http")]


class WebSearchProvider(ResearchProvider):
    id, kind = "exa_search", "web_search"

    def __init__(self, backend=None, clock=time.time):
        self.backend = backend or research.ExaSearch()
        self.clock = clock

    def capabilities(self):
        return {"operations": ["search"], "platforms": ["web"], "representedScope": "public_web"}

    def readiness(self, state=None):
        if not research.enabled():
            return {"state": "disabled", "reason": "Web research is switched off on this deployment."}
        if research.hosted() and not research.consent(state or {}).get("web") is True:
            return {"state": "consent_required", "reason": "An owner has not allowed web research for this workspace."}
        return {"state": "ready", "reason": ""}

    def search(self, query, scope=None):
        now = self.clock()
        limit = int((scope or {}).get("limit") or research.MAX_RESULTS)
        if isinstance(self.backend, research.ExaSearch):
            _, session = self.backend._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "postriff", "version": "0.1"}})
            result, _ = self.backend._rpc("tools/call", {"name": "web_search_exa", "arguments": {"query": query, "numResults": limit}}, session, 2)
            text = "\n".join(item.get("text", "") for item in ((result.get("result") or {}).get("content") or []) if isinstance(item, dict))
            rows = parse_search_with_author(text)[:limit]
        else:
            rows = list(self.backend(query, limit))[:limit]
        items = []
        for row in rows:
            snippet = row.get("snippet") or ""
            prov = Provenance(provider=self.id, kind=self.kind, accessMethod=ACCESS[self.kind], query=query, url=row.get("url"), host=_host(row.get("url")),
                              platform="web", retrievedAt=now, publishedAt=row.get("published") or None, author=row.get("author") or None,
                              contentHash=content_hash(snippet), evidenceType="search_snippet", injectionFlags=injection_flags(snippet),
                              freshnessDays=_age_days(row.get("published"), now))
            items.append({"title": row.get("title") or "", "url": row.get("url"), "snippet": snippet, "provenance": prov.as_dict()})
        return items


class WebReaderProvider(ResearchProvider):
    id, kind = "jina_reader", "web_reader"

    def __init__(self, backend=None, clock=time.time):
        self.backend = backend or research.JinaReader()
        self.clock = clock

    def capabilities(self):
        return {"operations": ["fetch"], "platforms": ["web"], "representedScope": "public_web"}

    readiness = WebSearchProvider.readiness

    def fetch(self, ref):
        url = ref.get("url") if isinstance(ref, dict) else ref
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise AlphaError("Only public http(s) pages can be read.", 400, code="bad_ref")
        now = self.clock()
        page = self.backend(url)
        text = page.get("text") or ""
        published = ""
        for line in text.splitlines()[:8]:
            if line.startswith("Published Time:"):
                published = line[15:].strip()
        prov = Provenance(provider=self.id, kind=self.kind, accessMethod=ACCESS[self.kind], url=url, host=_host(url), platform="web",
                          retrievedAt=now, publishedAt=published or (ref.get("published") if isinstance(ref, dict) else None) or None,
                          author=(ref.get("author") if isinstance(ref, dict) else None) or None, contentHash=content_hash(text),
                          evidenceType="page_text", injectionFlags=injection_flags(text), freshnessDays=_age_days(published, now))
        return {"title": page.get("title") or "", "url": url, "text": text, "paragraphs": research.paragraphs(text), "provenance": prov.as_dict()}


class OfficialPlatformApiProvider(ResearchProvider):
    """Owned-account posts through the platform's official API (social_history). It represents only the connected
    account's own posts, never platform-wide search."""
    id, kind = "official_owned_posts", "official_api"

    def __init__(self, fetch_page=None, clock=time.time):
        self.fetch_page = fetch_page
        self.clock = clock

    def capabilities(self):
        return {"operations": ["fetch"], "platforms": ["Instagram", "LinkedIn"], "representedScope": "owned_account_posts"}

    def readiness(self, state=None):
        if self.fetch_page is None:
            return {"state": "not_configured", "reason": "No connected account with history access."}
        return {"state": "ready", "reason": ""}

    def fetch(self, ref):
        if self.fetch_page is None:
            raise AlphaError("No connected account can be read.", 409, code="provider_not_configured")
        now = self.clock()
        page = self.fetch_page(ref)
        posts = []
        for post in page.get("posts") or []:
            text = post.get("text") or ""
            prov = Provenance(provider=self.id, kind=self.kind, accessMethod=ACCESS[self.kind], url=post.get("url"), platform=ref.get("platform"),
                              retrievedAt=now, publishedAt=post.get("publishedAt"), author=ref.get("accountLabel"), contentHash=content_hash(text),
                              representedScope="owned_account_posts", evidenceType="owned_post", injectionFlags=injection_flags(text))
            posts.append({"text": text, "url": post.get("url"), "provenance": prov.as_dict()})
        return {"posts": posts, "coverage": page.get("coverage"), "partialCoverage": page.get("partialCoverage")}


class MCPResearchProvider(ResearchProvider):
    """An approved MCP research connector. None is registered on this deployment, so it reports not configured."""
    id, kind = "mcp_connector", "mcp"

    def __init__(self, connector=None):
        self.connector = connector

    def capabilities(self):
        return {"operations": ["search", "fetch"] if self.connector else [], "platforms": [], "representedScope": "connector_defined"}

    def readiness(self, state=None):
        if self.connector is None:
            return {"state": "not_configured", "reason": "No approved research connector is registered."}
        return {"state": "ready", "reason": ""}


class LocalAgentReachProvider(ResearchProvider):
    """Agent Reach on the person's own machine. Ready only when this is not a hosted deployment, the local harness
    explicitly opted in (POSTRIFF_AGENT_REACH=1) and the runtime is installed. Readiness never runs `agent-reach
    doctor` (it makes network calls) and never reads cookies or sessions."""
    id, kind, hosted_ok = "agent_reach_local", "local_agent_reach", False
    OPT_IN = "POSTRIFF_AGENT_REACH"

    def __init__(self, home=None, env=None):
        self.home = Path(home or Path.home() / ".agent-reach")
        self.env = env if env is not None else os.environ

    def capabilities(self):
        return {"operations": ["search", "fetch"], "platforms": ["local-desktop"], "representedScope": "local_desktop_session"}

    def readiness(self, state=None):
        if research.hosted() or self.env.get("VERCEL") == "1":
            return {"state": "local_only", "reason": "Agent Reach runs only in a local Rafii harness, never on the hosted service."}
        if self.env.get(self.OPT_IN) != "1":
            return {"state": "disabled", "reason": f"Set {self.OPT_IN}=1 in the local harness to use Agent Reach."}
        binary = self.home / "venv" / "bin" / "agent-reach"
        if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
            return {"state": "not_configured", "reason": "Agent Reach is not installed on this machine."}
        version = None
        for meta in (self.home / "venv").glob("lib/python*/site-packages/agent_reach-*.dist-info/METADATA"):
            for line in meta.read_text("utf-8", "replace").splitlines():
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
        return {"state": "ready", "reason": "", "diagnostics": {"version": version, "ytDlp": bool(shutil.which("yt-dlp")), "gh": bool(shutil.which("gh")),
                                                               "representedScope": "local_desktop_session"}}


class FixtureProvider(ResearchProvider):
    """Deterministic provider for tests and local scenarios: canned search rows and pages, no network."""
    id, kind = "fixture", "fixture"

    def __init__(self, results=None, pages=None, fail=None, clock=time.time):
        self.results, self.pages, self.fail, self.clock = results or {}, pages or {}, fail or set(), clock

    def capabilities(self):
        return {"operations": ["search", "fetch"], "platforms": ["web"], "representedScope": "fixture"}

    def readiness(self, state=None):
        return {"state": "ready", "reason": ""}

    def search(self, query, scope=None):
        if "search" in self.fail:
            raise AlphaError("The fixture search provider is failing.", 503, code="provider_failed")
        now = self.clock()
        items = []
        for row in self.results.get(query, self.results.get("*", [])):
            prov = Provenance(provider=self.id, kind=self.kind, accessMethod="fixture", query=query, url=row["url"], host=_host(row["url"]), platform="web",
                              retrievedAt=now, publishedAt=row.get("published"), author=row.get("author"), contentHash=content_hash(row.get("snippet", "")),
                              evidenceType="search_snippet", injectionFlags=injection_flags(row.get("snippet", "")), freshnessDays=_age_days(row.get("published"), now))
            items.append({"title": row.get("title", ""), "url": row["url"], "snippet": row.get("snippet", ""), "provenance": prov.as_dict()})
        return items

    def fetch(self, ref):
        url = ref.get("url") if isinstance(ref, dict) else ref
        if "fetch" in self.fail or url not in self.pages:
            raise AlphaError("The page could not be read.", 502, code="provider_failed")
        page, now = self.pages[url], self.clock()
        text = page["text"]
        prov = Provenance(provider=self.id, kind=self.kind, accessMethod="fixture", url=url, host=_host(url), platform="web", retrievedAt=now,
                          publishedAt=page.get("published"), author=page.get("author"), contentHash=content_hash(text), evidenceType="page_text",
                          injectionFlags=injection_flags(text), freshnessDays=_age_days(page.get("published"), now))
        return {"title": page.get("title", ""), "url": url, "text": text, "paragraphs": research.paragraphs(text), "provenance": prov.as_dict()}


class ResearchBroker:
    """Routes search/fetch to ready providers and records what happened, failures included."""

    def __init__(self, providers=None, state=None):
        self.providers = list(providers) if providers is not None else [WebSearchProvider(), WebReaderProvider(), OfficialPlatformApiProvider(),
                                                                         MCPResearchProvider(), LocalAgentReachProvider()]
        self.state = state
        self.log = []

    def diagnostics(self):
        return [{"id": p.id, "kind": p.kind, "hostedOk": p.hosted_ok, "capabilities": p.capabilities(), "readiness": p.readiness(self.state)}
                for p in self.providers]

    def _ready(self, operation):
        for provider in self.providers:
            if operation in provider.capabilities().get("operations", []) and provider.readiness(self.state).get("state") == "ready":
                yield provider

    def search_items(self, query, scope=None):
        errors = []
        for provider in self._ready("search"):
            try:
                items = provider.search(query, scope)
                self.log.append({"op": "search", "provider": provider.id, "query": query, "status": "ok", "count": len(items)})
                return {"status": "ok", "provider": provider.id, "items": items, "errors": errors}
            except (AlphaError, OSError, ValueError) as error:
                errors.append({"provider": provider.id, "error": str(error)[:200]})
                self.log.append({"op": "search", "provider": provider.id, "query": query, "status": "failed", "error": str(error)[:200]})
        status = "failed" if errors else "unavailable"
        return {"status": status, "provider": None, "items": [], "errors": errors or [{"provider": None, "error": "No ready search provider."}]}

    def fetch_item(self, ref):
        errors = []
        for provider in self._ready("fetch"):
            if provider.kind == "official_api":
                continue
            try:
                page = provider.fetch(ref)
                self.log.append({"op": "fetch", "provider": provider.id, "url": page.get("url"), "status": "ok"})
                return {"status": "ok", "provider": provider.id, "page": page, "errors": errors}
            except (AlphaError, OSError, ValueError) as error:
                errors.append({"provider": provider.id, "error": str(error)[:200]})
                self.log.append({"op": "fetch", "provider": provider.id, "url": ref.get("url") if isinstance(ref, dict) else ref, "status": "failed"})
        return {"status": "failed" if errors else "unavailable", "provider": None, "page": None,
                "errors": errors or [{"provider": None, "error": "No ready reader."}]}

    # Callables compatible with research.Researcher(search=, read=) and automation_research.find(search=, read=).
    def search(self, query, limit=research.MAX_RESULTS):
        outcome = self.search_items(query, {"limit": limit})
        if outcome["status"] != "ok":
            raise AlphaError("Search failed: " + "; ".join(e["error"] for e in outcome["errors"])[:300], 503, code="research_failed")
        return [{"title": i["title"], "url": i["url"], "published": i["provenance"].get("publishedAt") or "", "snippet": i["snippet"]} for i in outcome["items"]]

    def read(self, url):
        outcome = self.fetch_item({"url": url})
        if outcome["status"] != "ok":
            raise AlphaError("Reading the page failed: " + "; ".join(e["error"] for e in outcome["errors"])[:300], 502, code="research_failed")
        return {"title": outcome["page"]["title"], "text": outcome["page"]["text"]}
