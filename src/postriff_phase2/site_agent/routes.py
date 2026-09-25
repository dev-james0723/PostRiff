"""The route manifest: every Rafii page the site agent may describe, link to or treat as page context (site agent §6.1).

`route_manifest.json` is the one allowlist. The browser's page context is matched against it (an unknown route is
stale context, not an error the model can talk around), navigation cards are built only from its entries with their
allowlisted query parameters, and help documents may only link to routes it knows. The web keeps a byte-identical
twin at `web/src/lib/site-agent/route-manifest.json`; `tests/test_site_agent.py` fails when they drift or when a
pattern has no page in `web/src/app`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

MANIFEST_PATH = Path(__file__).parent / "route_manifest.json"
PARAM = re.compile(r"^\[([a-zA-Z]+)\]$")
ID_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def entries() -> list[dict]:
    return manifest()["routes"]


def by_id(route_id: str) -> dict | None:
    return next((r for r in entries() if r["id"] == route_id), None)


@lru_cache(maxsize=1)
def families() -> frozenset[str]:
    return frozenset(r["family"] for r in entries())


def match(pathname: str) -> dict | None:
    """{route, params} for an app pathname (no query/fragment), or None when the manifest does not know it."""
    if not isinstance(pathname, str) or not pathname.startswith("/") or len(pathname) > 300:
        return None
    parts = [p for p in pathname.split("?")[0].split("#")[0].rstrip("/").split("/") if p] or []
    for route in entries():
        pattern = [p for p in route["pattern"].split("/") if p]
        if len(pattern) != len(parts):
            continue
        params = {}
        for want, got in zip(pattern, parts):
            name = PARAM.match(want)
            if name:
                if not ID_VALUE.match(got):
                    break
                params[name.group(1)] = got
            elif want != got:
                break
        else:
            return {"route": route, "params": params}
    return None


def href(route_id: str, *, params: dict | None = None, query: dict | None = None) -> str | None:
    """A validated in-app link, or None. Path parameters must match their slot; only the route's allowlisted query
    keys survive, each value checked against its declared kind (`id` or one of the listed values)."""
    route = by_id(route_id)
    if route is None:
        return None
    segments = []
    for part in [p for p in route["pattern"].split("/") if p]:
        name = PARAM.match(part)
        if name:
            value = (params or {}).get(name.group(1))
            if not isinstance(value, str) or not ID_VALUE.match(value):
                return None
            segments.append(value)
        else:
            segments.append(part)
    path = "/" + "/".join(segments)
    allowed = route.get("query") or {}
    kept = {}
    for key, value in (query or {}).items():
        spec = allowed.get(key)
        if spec is None or not isinstance(value, str):
            continue
        if spec == "id" and ID_VALUE.match(value):
            kept[key] = value
        elif isinstance(spec, list) and value in spec:
            kept[key] = value
    return path + ("?" + urlencode(kept) if kept else "")


def describe(route_id: str) -> dict | None:
    route = by_id(route_id)
    if route is None:
        return None
    return {key: route.get(key) for key in ("id", "pattern", "family", "title", "summary", "entityTypes", "helpDocs", "access")}


def listing(*, family: str | None = None) -> list[dict]:
    return [{"id": r["id"], "title": r["title"], "pattern": r["pattern"], "family": r["family"], "summary": r["summary"]}
            for r in entries() if r.get("navigable", True) and (family is None or r["family"] == family)]
