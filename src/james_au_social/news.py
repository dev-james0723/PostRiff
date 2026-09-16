"""RSS/Atom normalization, durable evidence, health and conservative claim gates.

Acquisition is injected: this module has no network, credential or publish tools.
It parses supplied feed bytes and records what was actually observed.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .execution import instant, payload_hash


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("unsafe_source_url")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(text):
    parser = PlainText()
    parser.feed(text)
    return " ".join(" ".join(parser.parts).split())


def date(value):
    if not value:
        return None
    try:
        return instant(value).isoformat()
    except ValueError:
        parsed = parsedate_to_datetime(value)
        return instant(parsed.isoformat()).isoformat()


def extract(data):
    if len(data) > 5_000_000:
        raise ValueError("feed_too_large")
    decoded = data.decode("utf-8-sig")
    if "\x00" in decoded or "<!DOCTYPE" in decoded.upper() or "<!ENTITY" in decoded.upper():
        raise ValueError("unsafe_feed_xml")
    root = ET.fromstring(decoded)
    local = lambda t: t.split("}")[-1]
    if local(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("unsupported_feed_root")
    result = []
    for element in root.iter():
        if local(element.tag) not in {"entry", "item"}:
            continue
        fields = {}
        for child in element:
            key = local(child.tag)
            if key == "link" and child.attrib.get("rel", "alternate") == "alternate":
                fields[key] = child.attrib.get("href") or "".join(child.itertext())
            elif key != "link":
                fields[key] = "".join(child.itertext())
        result.append(fields)
    return result


def assess_claim(claim_type, evidence, *, contradictions=(), retracted=False):
    primary = [e for e in evidence if e["source"].get("source_tier") in {"primary_official", "primary_other"}
               and claim_type in e["source"].get("fact_authority", [])]
    secondary_publishers = {e["source"].get("publisher") for e in evidence
                            if e["source"].get("source_tier") == "reliable_secondary" and e["source"].get("publisher")}
    if retracted:
        status = "retracted"
    elif contradictions:
        status = "disputed"
    elif primary:
        status = "confirmed"
    elif len(secondary_publishers) >= 2 and claim_type not in {"announcement", "specification", "price", "availability"}:
        status = "corroborated"
    elif evidence and any(e["source"].get("source_tier") != "discovery_only" for e in evidence):
        status = "attributed"
    else:
        status = "unverified"
    require_primary = claim_type in {"announcement", "specification", "price", "availability"}
    usable = status in {"confirmed", "corroborated", "attributed"} and (bool(primary) or not require_primary)
    return {"status": status, "confidence": "high" if status == "confirmed" else "medium" if status == "corroborated" else "low",
            "story_state": "ready_for_brief" if usable else "awaiting_primary_source" if require_primary and not primary else "review_required",
            "usable_for_draft": usable, "establishes_james_view": False,
            "qualification_required": status != "confirmed"}


class NewsStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS health(source TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY, source TEXT, entry_id TEXT,
               content_hash TEXT, canonical_url TEXT, data TEXT, retrieved_at TEXT);
            CREATE TABLE IF NOT EXISTS artifact_sources(artifact TEXT, source_hash TEXT, published INTEGER, state TEXT,
               PRIMARY KEY(artifact,source_hash));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def health(self, source):
        with self.connection() as db:
            row = db.execute("SELECT data FROM health WHERE source=?", (source,)).fetchone()
        return json.loads(row[0]) if row else {}

    def ingest(self, source, data, *, retrieved_at, final_url, http_status=200, content_type="application/rss+xml", latency_ms=0):
        now = instant(retrieved_at)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM health WHERE source=?", (source["source_id"],)).fetchone()
            previous = json.loads(row[0]) if row else {}
            interval = source["poll_interval_seconds"]
            if not isinstance(interval, int) or interval < 60:
                raise ValueError("invalid_poll_interval")
            health = {"source_id": source["source_id"], "checked_at": retrieved_at,
                "last_success_at": previous.get("last_success_at"), "last_entry_id": previous.get("last_entry_id"),
                "http_status": http_status, "content_type": content_type, "latency_ms": latency_ms,
                "parse_status": "healthy", "consecutive_failures": previous.get("consecutive_failures", 0),
                "delivery_mode": "polling", "poll_interval_seconds": interval, "observed_delay_seconds": None,
                "entry_count": 0, "anomalies": [], "next_check_at": (now + timedelta(seconds=interval)).isoformat()}
            items = []
            try:
                if not source["enabled"]:
                    health["parse_status"] = "disabled"
                    health["next_check_at"] = None
                else:
                    if urlsplit(canonical_url(final_url)).netloc != urlsplit(canonical_url(source["feed_url"])).netloc:
                        raise ValueError("unreviewed_redirect")
                    if http_status not in {200, 304}:
                        raise ValueError("fetch_failed")
                    if http_status == 304 and not previous.get("last_success_at"):
                        raise ValueError("not_modified_without_cursor")
                    if http_status == 200 and content_type.split(";")[0] not in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
                        raise ValueError("content_type_drift")
                    fields_list = [] if http_status == 304 else extract(data)
                    for fields in fields_list:
                        try:
                            url = canonical_url(fields.get("link", ""))
                            published = date(fields.get("pubDate") or fields.get("published") or fields.get("updated"))
                            title = plain(fields.get("title", ""))
                            summary = plain(fields.get("description") or fields.get("summary") or fields.get("content", ""))
                            if not title:
                                raise ValueError("missing_title")
                            digest = payload_hash({"url": url, "title": title, "summary": summary,
                                                   "updated": fields.get("updated")})
                            entry_id = fields.get("guid") or fields.get("id") or url
                            old = db.execute("SELECT * FROM news WHERE source=? AND (entry_id=? OR canonical_url=?) ORDER BY id DESC LIMIT 1",
                                             (source["source_id"], entry_id, url)).fetchone()
                            state = "new" if old is None else "duplicate" if old["content_hash"] == digest else "updated"
                            age = (now - instant(published)).total_seconds() if published else None
                            if age is None or age < -300 or age > source.get("max_age_days", 30) * 86400:
                                state = "quarantined"
                            item = {"source_id": source["source_id"], "external_entry_id": entry_id,
                                "title": title, "canonical_url": url, "original_url": fields["link"],
                                "publisher_published_at": published, "retrieved_at": retrieved_at,
                                "summary_text": summary, "content_hash": digest,
                                "source_tier": source["source_tier"], "registry_version": source["registry_version"],
                                "ingestion_status": state}
                            db.execute("INSERT INTO news(source,entry_id,content_hash,canonical_url,data,retrieved_at) VALUES(?,?,?,?,?,?)",
                                       (source["source_id"], entry_id, digest, url, json.dumps(item), retrieved_at))
                            if state == "updated":
                                db.execute("UPDATE artifact_sources SET state=CASE WHEN published=1 THEN 'correction_required' ELSE 'review_required' END WHERE source_hash=?", (old["content_hash"],))
                            if state != "quarantined":
                                health["last_entry_id"] = entry_id
                                health["observed_delay_seconds"] = max(0, int(age))
                            items.append(item)
                        except (ValueError, TypeError, KeyError):
                            health["anomalies"].append("malformed_entry")
                            items.append({"ingestion_status": "quarantined", "reason": "malformed_entry"})
                    health["last_success_at"] = retrieved_at
                    health["consecutive_failures"] = 0
                    health["entry_count"] = len(items)
                    if any(i["ingestion_status"] == "quarantined" for i in items):
                        health["parse_status"] = "degraded"
            except (ValueError, ET.ParseError):
                health["parse_status"] = "failed"
                health["consecutive_failures"] += 1
                health["anomalies"].append("feed_rejected")
                health["next_check_at"] = (now + timedelta(seconds=min(86400, interval * 2 ** min(health["consecutive_failures"], 8)))).isoformat()
            db.execute("INSERT INTO health VALUES(?,?) ON CONFLICT(source) DO UPDATE SET data=excluded.data", (source["source_id"], json.dumps(health)))
        return {"health": health, "items": items, "external_actions": []}

    def bind_artifact(self, artifact_id, source_hash, *, published):
        with self.connection() as db:
            db.execute("INSERT INTO artifact_sources VALUES(?,?,?,'current')", (artifact_id, source_hash, bool(published)))

    def artifact_state(self, artifact_id):
        with self.connection() as db:
            rows = db.execute("SELECT state FROM artifact_sources WHERE artifact=?", (artifact_id,)).fetchall()
        states = {r[0] for r in rows}
        return "correction_required" if "correction_required" in states else "review_required" if "review_required" in states else "current" if states else "not_found"

    def evidence_count(self):
        with self.connection() as db:
            return db.execute("SELECT COUNT(*) FROM news").fetchone()[0]
