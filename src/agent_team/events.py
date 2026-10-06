"""Sanitized observation journal. This is evidence/outbox state, never a project todo registry."""
from dataclasses import dataclass, asdict
import hashlib
import ipaddress
import json
import math
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from .periods import aware

SOURCES = frozenset({"typeless", "luci", "codex", "claude", "browser", "health", "mission", "git", "token_pilot", "acceptance", "incident"})
SAFE_KEYS = frozenset({"state", "status", "app", "mode", "textLength", "audioAvailable", "kind", "count", "sha", "deploymentId", "url", "requirements", "evidenceRefs", "scopeVersion", "verified", "withoutHuman", "phase", "accepted", "total", "summary", "gaps", "sourceFreshAt", "sourceStatus", "origin", "sessionHandle", "timestamp", "reportedState", "scanComplete"})
SECRET = re.compile(r"(?i)(?:\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_\w+)|\bBearer\s+\S+|\b(?:password|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|secret)\s*[:=]\s*\S+)")
_URL_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_PHONE = re.compile(r"(?<!\d)(?:\+\d{10,15}|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})(?!\d)|(?:^|/)\d{10,15}(?=/|$)")
_URL_LOCAL_PATH = re.compile(r"(?i)/(?:Users|home|private|var|tmp|etc|Volumes|Library|Applications)(?:/|$)|(?:^|/)[a-z]:[/\\]|(?:^|/)file:")
_URL_SECRET_PATH = re.compile(r"(?i)(?:^|/)(?:api[_-]?key|token|access[_-]?token|refresh[_-]?token|password|secret|authorization|bearer)(?:[/=:]|$)|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}|\bAIza[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_URL_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_URL_LOCAL_SUFFIXES = (".local", ".internal", ".localhost", ".test", ".invalid", ".localdomain", ".lan", ".home", ".home.arpa")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_text(value, limit=240):
    text = " ".join(str(value).split())
    text = SECRET.sub("[REDACTED]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(r"(?:\+\d{10,15}\b|\(?\d{3}\)?[ -]\d{3}[ -]\d{4}\b)", "[PHONE]", text)
    text = re.sub(r"/(?:Users|home|private|var)/[^\s]+", "[LOCAL_REFERENCE]", text)
    return text[:limit]


def safe_url(value):
    """Offline privacy gate, not DNS/publication proof or permission to fetch.

    Reject ambiguous/nested escaping and private-looking path contents. Query
    and fragment are discarded, never inspected or returned as evidence. Only
    port 443 is accepted and canonical output omits it. Reserved local domain
    suffixes and nonglobal literal IPs are rejected without resolving a host.
    Caller-specific evidence host/repository/path registration remains required.
    """
    if (not isinstance(value, str) or not 1 <= len(value) <= 2_048
            or any(char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
            or "\\" in value):
        raise ValueError("evidence_url_invalid")
    try:
        u = urlsplit(value)
        host, port = u.hostname, u.port
        if (u.scheme != "https" or not host or u.username is not None or u.password is not None
                or "@" in u.netloc or "%" in u.netloc or port not in {None, 443}):
            raise ValueError("evidence_url_requires_public_https")
        if not host.isascii() or host.endswith(".") or len(host) > 253:
            raise ValueError("evidence_url_requires_public_https")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if (len(labels) < 2 or any(not _URL_LABEL.fullmatch(label) for label in labels)
                    or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", labels[-1])
                    or host == "localhost" or host.endswith(_URL_LOCAL_SUFFIXES)):
                raise ValueError("evidence_url_requires_public_https")
            authority = host
        else:
            mapped = getattr(address, "ipv4_mapped", None)
            if (not address.is_global or address.is_multicast or address.is_reserved
                    or mapped is not None and not mapped.is_global):
                raise ValueError("evidence_url_requires_public_https")
            authority = "[" + address.compressed + "]" if address.version == 6 else address.compressed
        # Reject empty/ambiguous ports and parser/browser authority differences.
        raw_authority = u.netloc.lower()
        lexical_authority = "[" + host + "]" if ":" in host else host
        if raw_authority not in {lexical_authority, lexical_authority + ":443"}:
            raise ValueError("evidence_url_invalid")
        if re.search(r"%(?![0-9a-fA-F]{2})", u.path):
            raise ValueError("evidence_url_invalid")
        decoded = unquote(u.path, encoding="utf-8", errors="strict")
        normalized = unicodedata.normalize("NFKC", decoded)
        if ("%" in normalized or "\\" in normalized
                or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in normalized)
                or any(part in {".", ".."} for part in normalized.split("/"))
                or SECRET.search(normalized) or _URL_SECRET_PATH.search(normalized)
                or _URL_LOCAL_PATH.search(normalized) or _URL_EMAIL.search(normalized)
                or _URL_PHONE.search(normalized)):
            raise ValueError("evidence_url_path_not_public")
        return urlunsplit(("https", authority, u.path, "", ""))
    except (ValueError, UnicodeError):
        # Do not retain original values or low-level parser errors in receipts.
        raise ValueError("evidence_url_not_public") from None


def projection(payload):
    if not isinstance(payload, dict) or set(payload)-SAFE_KEYS:
        raise ValueError("non_allowlisted_event_fields")
    def clean(v):
        if isinstance(v, str): return safe_text(v, 500)
        if isinstance(v, float) and not math.isfinite(v):raise ValueError('non_finite_event_value')
        if isinstance(v, (int, float, bool)) or v is None: return v
        if isinstance(v, list):
            if len(v)>50: raise ValueError("event_array_limit")
            return [clean(x) for x in v]
        if isinstance(v, dict):
            if set(v)-{"id", "status", "evidenceRefs", "sourceVersion", "scopeVersion"}:
                raise ValueError("non_allowlisted_nested_fields")
            return {k:clean(x) for k,x in v.items()}
        raise ValueError("unsupported_event_value")
    out = {k:clean(v) for k,v in payload.items()}
    if "url" in out: out["url"] = safe_url(payload["url"])
    if len(canonical(out).encode())>12000: raise ValueError("event_size_limit")
    return out


@dataclass(frozen=True)
class Event:
    source: str
    source_id: str
    revision: str
    happened_at: str
    observed_at: str
    payload: dict
    mission_id: str | None = None
    project_id: str | None = None

    def validate(self):
        if self.source not in SOURCES: raise ValueError("unsupported_event_source")
        for value in [self.source_id, self.revision]:
            if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}",value):
                raise ValueError("invalid_source_identity")
        for value in [self.mission_id, self.project_id]:
            if value is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}",value):
                raise ValueError("invalid_mission_identity")
        a,b = aware(self.happened_at),aware(self.observed_at)
        if a>b: raise ValueError("observation_precedes_source")
        projection(self.payload)
        if 'sourceFreshAt' in self.payload:
            if aware(self.payload['sourceFreshAt'])>b:raise ValueError('source_update_after_observation')
        if self.source=='acceptance':
            req=self.payload.get('requirements')
            if not isinstance(req,list) or not req or any(not isinstance(x,dict) for x in req):
                raise ValueError('acceptance_requirements_required')
            for r in req:
                refs=r.get('evidenceRefs')
                if not isinstance(refs,list) or not refs or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{64}',x) for x in refs):
                    raise ValueError('acceptance_evidence_required')
        return self

    @property
    def key(self):
        return hashlib.sha256(canonical([self.source,self.source_id,self.revision]).encode()).hexdigest()

    def cloud(self):
        self.validate()
        d=asdict(self);d["payload"]=projection(self.payload);d["key"]=self.key
        return d


class Journal:
    def __init__(self, path):
        p=Path(path)
        if p.is_symlink(): raise ValueError("symlink_journal")
        p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(p,timeout=5)
        p.chmod(0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observations(key TEXT PRIMARY KEY, source TEXT NOT NULL,
                source_id TEXT NOT NULL, revision TEXT NOT NULL, happened_at TEXT NOT NULL,
                observed_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
                delivered_at TEXT);
            CREATE TABLE IF NOT EXISTS observer_cursors(source TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS observations_time ON observations(happened_at);
        """)

    def ingest(self, events, source=None, cursor=None):
        rows=[x.cloud() for x in events]
        if len(rows)>200: raise ValueError("batch_size_limit")
        added=0
        with self.db:
            for row in rows:
                raw=canonical(row)
                immutable={k:v for k,v in row.items() if k!='observed_at'}
                digest=hashlib.sha256(canonical(immutable).encode()).hexdigest()
                old=self.db.execute("SELECT digest FROM observations WHERE key=?",(row["key"],)).fetchone()
                if old:
                    if old[0]!=digest: raise ValueError("immutable_event_conflict")
                    continue
                self.db.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,NULL)",
                    (row["key"],row["source"],row["source_id"],row["revision"],row["happened_at"],row["observed_at"],raw,digest));added+=1
            if cursor is not None:
                if source not in SOURCES: raise ValueError("cursor_requires_source")
                self.db.execute("INSERT INTO observer_cursors VALUES(?,?) ON CONFLICT(source) DO UPDATE SET value=excluded.value",(source,canonical(cursor)))
        return added

    def cursor(self, source):
        r=self.db.execute("SELECT value FROM observer_cursors WHERE source=?",(source,)).fetchone()
        return json.loads(r[0]) if r else None

    def pending(self, limit=100):
        return [json.loads(x[0]) for x in self.db.execute("SELECT payload FROM observations WHERE delivered_at IS NULL ORDER BY observed_at,key LIMIT ?",(min(limit,100),))]

    def acknowledge(self, keys, delivered_at):
        aware(delivered_at)
        with self.db:
            for k in keys: self.db.execute("UPDATE observations SET delivered_at=? WHERE key=?",(delivered_at,k))

    def all(self, limit=10000):
        return [json.loads(x[0]) for x in self.db.execute("SELECT payload FROM observations ORDER BY observed_at,key LIMIT ?",(limit,))]

    def close(self): self.db.close()
