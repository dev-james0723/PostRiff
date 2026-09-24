"""Rafii's product knowledge: a versioned help corpus, checked at load and searched per turn (site agent §7).

The corpus is the markdown under `site_agent/help/` (shipped with the API; `docs/` is not deployed). Every file opens
with a small front matter block (`key: value` or `key: [a, b]`), then `# Title` and `## Section` headings. A section is
the unit of retrieval and citation: `/app/help/<documentId>#<anchor>`.

Loading fails closed (`KnowledgeError`) when a document has no owner or effective version, links to a route the route
manifest does not know, claims a capability without qualification, is support-only but marked public, duplicates or
silently conflicts with another document, or contains something that looks like a credential. A failed corpus is
never half-served.

Retrieval is lexical (BM25 over sections, CJK bigrams, a small bilingual glossary) with a route-family boost and an
authority rerank. There is no embedding index yet: no embedding provider is qualified for this deployment, so the
`vector` hook stays empty and results say `retrieval: "lexical"`. Retrieved text is data for the answer, never
instructions, and never authorization for anything.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import routes

HELP_DIR = Path(__file__).parent / "help"
SOURCE_TYPES = ("product_help", "capability_explanations", "troubleshooting", "workflow_playbooks", "release_notes", "support_runbooks")
VISIBILITIES = ("public", "workspace", "support")
AUTHORITY = {"capability_explanations": 1.15, "troubleshooting": 1.1, "workflow_playbooks": 1.05, "product_help": 1.0,
             "release_notes": 0.85, "support_runbooks": 0.8}
REQUIRED = ("documentId", "sourceType", "title", "routeFamilies", "locales", "productVersion", "effectiveFrom", "visibility", "owner")
MAX_PASSAGE_CHARS = 1400

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"), re.compile(r"ghp_[A-Za-z0-9]{20,}"), re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S{12,}"),
)
# A capability claim must be qualified by the live state ("when", "if", "only", "after", …) in the same sentence.
CLAIM = re.compile(r"(?i)\b(always|automatically|directly)\b[^.\n]{0,60}\b(publish(es|ed)?|post(s|ed)?)\b|\b(publish(es)?|posts?) (directly|automatically) to\b")
QUALIFIER = re.compile(r"(?i)\b(when|if|only|after|once|unless|until|approved|approval|verified|capability|can't|cannot|never|not)\b")
LINK = re.compile(r"\]\((/[^)\s#]*)(#[^)\s]*)?\)")
STOP = frozenset("a an and are as at be by can do does for from how i if in is it its me my of on or so that the this to was what when where which who why will with you your mean means meaning please work works working".split())
# zh-Hant / Cantonese words people use for the things the corpus describes → the English terms the corpus uses.
GLOSSARY = {
    "發佈": "publish", "發布": "publish", "發文": "publish post", "出post": "publish post", "出街": "publish", "貼文": "post",
    "排程": "schedule", "預約": "schedule", "日曆": "calendar", "行事曆": "calendar", "月曆": "calendar", "時間表": "schedule calendar",
    "草稿": "draft", "審批": "approve approval review", "批准": "approve approval", "審核": "review approval", "核准": "approve",
    "自動化": "automation", "自動": "automation automatically", "定期": "recurring automation", "每週": "weekly automation",
    "頻道": "channel", "帳戶": "account", "帳號": "account", "連接": "connect connection", "連結": "connect link", "斷開": "disconnect",
    "授權": "authorize permission", "權限": "permission role", "角色": "role", "成員": "member", "邀請": "invite member",
    "記憶": "memory", "記住": "memory remember", "聲音": "voice", "語氣": "voice tone", "品牌": "brand",
    "模型": "model", "供應商": "provider", "私隱": "privacy", "隱私": "privacy", "資料": "data", "雲端": "cloud",
    "費用": "billing cost", "收費": "billing plan", "計劃": "plan", "方案": "plan", "額度": "allowance credits", "點數": "credits",
    "錯誤": "error failed", "失敗": "failed", "唔得": "not working failed", "唔work": "not working", "點解": "why",
    "點樣": "how", "點用": "how use", "喺邊": "where", "邊度": "where", "頁": "page", "呢頁": "this page",
    "佇列": "queue", "隊列": "queue", "收件": "inbox", "回覆": "reply", "分析": "analytics", "數據": "analytics data",
    "素材": "source idea", "靈感": "idea", "想法": "idea", "來源": "source", "圖片": "image media", "媒體": "media library",
    "研究": "research", "刪除": "delete", "匯出": "export", "登入": "sign in", "密碼": "password", "通知": "notification",
}


class KnowledgeError(ValueError):
    """The corpus failed an ingestion check; nothing from it is served."""


def _front_matter(text: str, name: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise KnowledgeError(f"{name}: missing front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise KnowledgeError(f"{name}: unterminated front matter")
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise KnowledgeError(f"{name}: bad front matter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        else:
            meta[key.strip()] = value or None
    return meta, text[end + 5:]


def slug(heading: str) -> str:
    text = unicodedata.normalize("NFKD", heading).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "section"


def _sections(body: str, name: str) -> tuple[str, list[dict]]:
    title = None
    sections: list[dict] = []
    current = None
    for line in body.splitlines():
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
            current = {"heading": "Overview", "anchor": "overview", "lines": []}
            sections.append(current)
        elif line.startswith("## "):
            heading = line[3:].strip()
            current = {"heading": heading, "anchor": slug(heading), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)
    if title is None:
        raise KnowledgeError(f"{name}: missing '# Title'")
    out = []
    seen = set()
    for section in sections:
        text = "\n".join(section.pop("lines")).strip()
        if not text:
            continue
        if section["anchor"] in seen:
            raise KnowledgeError(f"{name}: duplicate section heading {section['heading']!r}")
        seen.add(section["anchor"])
        out.append({**section, "text": text})
    return title, out


def _check(doc: dict, name: str) -> None:
    meta = doc["meta"]
    for key in REQUIRED:
        if not meta.get(key):
            raise KnowledgeError(f"{name}: missing {key}")
    if meta["sourceType"] not in SOURCE_TYPES:
        raise KnowledgeError(f"{name}: unknown sourceType {meta['sourceType']!r}")
    if meta["visibility"] not in VISIBILITIES:
        raise KnowledgeError(f"{name}: unknown visibility {meta['visibility']!r}")
    if meta["sourceType"] == "support_runbooks" and meta["visibility"] != "support":
        raise KnowledgeError(f"{name}: a support runbook must not be visible to customers")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["effectiveFrom"]):
        raise KnowledgeError(f"{name}: effectiveFrom must be YYYY-MM-DD")
    for family in meta["routeFamilies"]:
        if family not in routes.families():
            raise KnowledgeError(f"{name}: unknown route family {family!r}")
    raw = doc["raw"]
    for pattern in SECRET_PATTERNS:
        if pattern.search(raw):
            raise KnowledgeError(f"{name}: looks like it contains a credential")
    for match in LINK.finditer(raw):
        path = match.group(1)
        if path.startswith("/app") and routes.match(path) is None:
            raise KnowledgeError(f"{name}: links to unknown route {path}")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", raw):
        if CLAIM.search(sentence) and not QUALIFIER.search(sentence):
            raise KnowledgeError(f"{name}: unqualified capability claim: {sentence.strip()[:120]!r}")


def load(directory: Path | None = None) -> dict:
    """Read, check and index the corpus. Returns the snapshot {id, productVersion, documents, passages}."""
    directory = directory or HELP_DIR
    documents: dict[str, dict] = {}
    for path in sorted(directory.rglob("*.md")):
        name = str(path.relative_to(directory))
        raw = path.read_text(encoding="utf-8")
        meta, body = _front_matter(raw, name)
        title, sections = _sections(body, name)
        if meta.get("title") and meta["title"] != title:
            raise KnowledgeError(f"{name}: front matter title differs from '# {title}'")
        doc = {"meta": meta, "raw": raw, "title": title, "sections": sections, "path": name,
               "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}
        _check(doc, name)
        document_id = meta["documentId"]
        if document_id in documents:
            raise KnowledgeError(f"{name}: duplicate documentId {document_id!r}")
        documents[document_id] = doc
    retired = set()
    for document_id, doc in documents.items():
        old = doc["meta"].get("supersedes")
        if old:
            if old not in documents and old not in doc["meta"].get("retired", []):
                raise KnowledgeError(f"{doc['path']}: supersedes unknown document {old!r}")
            retired.add(old)
    topics: dict[str, str] = {}
    for document_id, doc in documents.items():
        topic = doc["meta"].get("topic")
        if topic and document_id not in retired:
            if topic in topics:
                raise KnowledgeError(f"{doc['path']}: topic {topic!r} is also covered by {topics[topic]!r}; supersede one of them")
            topics[topic] = document_id
    live = {k: v for k, v in documents.items() if k not in retired}
    passages = []
    for document_id, doc in live.items():
        keywords = " ".join(doc["meta"].get("keywords") or [])
        for section in doc["sections"]:
            text = section["text"][:MAX_PASSAGE_CHARS]
            passages.append({
                "documentId": document_id, "title": doc["title"], "section": section["heading"], "anchor": section["anchor"],
                "text": text, "sourceType": doc["meta"]["sourceType"], "visibility": doc["meta"]["visibility"],
                "routeFamilies": list(doc["meta"]["routeFamilies"]), "locales": list(doc["meta"]["locales"]),
                "fields": {"title": _tokens(doc["title"]), "heading": _tokens(section["heading"]), "keywords": _tokens(keywords),
                           "body": _tokens(text)},
            })
    digest = hashlib.sha256("\n".join(f"{k}:{v['sha256']}" for k, v in sorted(live.items())).encode()).hexdigest()
    versions = sorted({doc["meta"]["productVersion"] for doc in live.values()})
    return {"id": f"kb_{digest[:12]}", "productVersion": versions[-1] if versions else None, "documents": live,
            "retired": sorted(retired), "passages": passages, "stats": _stats(passages)}


@lru_cache(maxsize=1)
def snapshot() -> dict:
    return load()


def _stem(word: str) -> str:
    for suffix, keep in (("ing", 4), ("ed", 4), ("es", 4), ("s", 3)):
        if word.endswith(suffix) and len(word) - len(suffix) >= keep:
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text or "").lower()
    out: list[str] = []
    for chunk in re.findall(r"[a-z0-9][a-z0-9'_-]*|[㐀-鿿豈-﫿]+", text):
        if chunk[0] >= "㐀":
            out.extend(chunk[i:i + 2] for i in range(max(1, len(chunk) - 1)))
        else:
            for part in re.split(r"[-_']", chunk):
                if part and part not in STOP:
                    out.append(_stem(part))
    return out


def expand(query: str) -> str:
    """The query plus the English words for any zh-Hant/Cantonese terms it uses (retrieval only)."""
    extra = [english for term, english in GLOSSARY.items() if term in query]
    return query + (" " + " ".join(extra) if extra else "")


FIELD_WEIGHT = {"title": 2.5, "heading": 2.0, "keywords": 2.5, "body": 1.0}


def _stats(passages: list[dict]) -> dict:
    df: dict[str, int] = {}
    lengths = []
    for passage in passages:
        seen = set()
        length = 0
        for field, tokens in passage["fields"].items():
            length += len(tokens)
            seen.update(tokens)
        lengths.append(length)
        for token in seen:
            df[token] = df.get(token, 0) + 1
    return {"df": df, "n": len(passages), "avg": (sum(lengths) / len(lengths)) if lengths else 1.0}


def _score(passage: dict, terms: list[str], stats: dict, k1: float = 1.2, b: float = 0.75) -> float:
    length = sum(len(tokens) for tokens in passage["fields"].values())
    score = 0.0
    for term in set(terms):
        df = stats["df"].get(term)
        if not df:
            continue
        idf = math.log(1 + (stats["n"] - df + 0.5) / (df + 0.5))
        tf = sum(FIELD_WEIGHT[field] * tokens.count(term) for field, tokens in passage["fields"].items())
        if tf:
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / stats["avg"]))
    return score


def search(query: str, *, route_family: str | None = None, locale: str | None = None, k: int = 5, documents=(),
           visibility: tuple[str, ...] = ("public", "workspace"), min_score: float = 1.2, kb: dict | None = None) -> dict:
    """Hybrid-ready retrieval. Returns {snapshot, retrieval, passages:[…with citation…], sufficient}.

    Visibility is enforced here: customers never receive support runbooks. A route-family match and the procedure's
    own articles (`documents`) boost a passage but never let it outrank a clearly better answer; source authority
    reranks near-ties."""
    kb = kb or snapshot()
    terms = _tokens(expand(query))
    if not terms:
        return {"snapshot": kb["id"], "retrieval": "lexical", "passages": [], "sufficient": False}
    scored = []
    for passage in kb["passages"]:
        if passage["visibility"] not in visibility:
            continue
        base = _score(passage, terms, kb["stats"])
        if base <= 0:
            continue
        boost = AUTHORITY.get(passage["sourceType"], 1.0)
        if route_family and route_family in passage["routeFamilies"]:
            boost *= 1.25
        if passage["documentId"] in documents:
            # The procedure knows which articles own this question (the page's own help, the matching runbook).
            boost *= 1.6
        scored.append((base * boost, base, passage))
    scored.sort(key=lambda item: (-item[0], item[2]["documentId"], item[2]["anchor"]))
    out, per_doc = [], {}
    for final, base, passage in scored:
        if per_doc.get(passage["documentId"], 0) >= 2:
            continue
        per_doc[passage["documentId"]] = per_doc.get(passage["documentId"], 0) + 1
        out.append({**{key: passage[key] for key in ("documentId", "title", "section", "anchor", "text", "sourceType", "routeFamilies")},
                    "score": round(final, 3), "href": f"/app/help/{passage['documentId']}#{passage['anchor']}"})
        if len(out) >= k:
            break
    sufficient = bool(out) and out[0]["score"] >= min_score
    return {"snapshot": kb["id"], "retrieval": "lexical", "passages": out, "sufficient": sufficient}


def get(document_id: str, *, visibility: tuple[str, ...] = ("public", "workspace"), kb: dict | None = None) -> dict | None:
    """One document for the help page (sections in order), or None when unknown or not visible."""
    kb = kb or snapshot()
    doc = kb["documents"].get(document_id)
    if doc is None or doc["meta"]["visibility"] not in visibility:
        return None
    meta = doc["meta"]
    return {"documentId": document_id, "title": doc["title"], "sourceType": meta["sourceType"], "owner": meta["owner"],
            "productVersion": meta["productVersion"], "effectiveFrom": meta["effectiveFrom"], "routeFamilies": list(meta["routeFamilies"]),
            "summary": meta.get("summary"), "snapshot": kb["id"], "sha256": doc["sha256"],
            "sections": [{"heading": s["heading"], "anchor": s["anchor"], "text": s["text"]} for s in doc["sections"]]}


def catalogue(*, visibility: tuple[str, ...] = ("public", "workspace"), kb: dict | None = None) -> list[dict]:
    kb = kb or snapshot()
    return [{"documentId": k, "title": d["title"], "summary": d["meta"].get("summary"), "sourceType": d["meta"]["sourceType"],
             "routeFamilies": list(d["meta"]["routeFamilies"])}
            for k, d in sorted(kb["documents"].items(), key=lambda item: item[1]["title"]) if d["meta"]["visibility"] in visibility]
