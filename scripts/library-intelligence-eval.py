#!/usr/bin/env python3
"""Library retrieval evaluation with REAL embeddings (acceptance A026 semantic/hybrid Recall@10, A027 multilingual). NOT RUN
by default; the coordinator runs it once James's provider credentials exist.

Data: the coordinator's FROZEN relevance set tests/fixtures/library_intelligence/eval/{corpus,queries}.json (64 documents,
100 judged queries: lexical, semantic, cross_lingual, code_switch) plus 940 deterministic templated distractors from
`distractors()` below (1,004 documents). The corpus, queries and judgments are never modified, and ranking is not tuned
to them. The same distractors seed the real-SQL suite tests/phase2/postgres_library_intelligence_eval.py.

What runs:
  * every document and query is embedded through the production seam providers.embed (Vercel AI Gateway,
    openai/text-embedding-3-large at 1024 dimensions unless overridden), one vector per document (each corpus document
    is a single passage, which is what structure extraction produces for it);
  * semantic-only = exact cosine over all document vectors, top search.SEMANTIC_K. An in-memory cosine stands in for
    pgvector here; the pgvector/HNSW path itself is proven by the PG suite;
  * lexical-only = an in-memory reproduction of the SQL lexical stage: the same textnorm terms with AND semantics over
    segment terms (ranked like ts_rank with length normalization), plus the real search._metadata_matches, fused by the
    real search.rrf. The authoritative lexical baseline is the PG suite's real SQL;
  * hybrid = the real ordering of search_library: search._exact identity matches first, then search.rrf over the lexical
    and semantic lists (k=60, equal weights, 'rrf-60-v1').
Recall@10 = mean over queries of |relevant ∩ top10| / min(10, |relevant|), reported per type for each mode. The A026
target (>= 0.90) applies to semantic/hybrid on this set.

Paid calls run only when ALL hold:
  * RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION=james-2026-10-08-cap-10usd;
  * --confirm-paid-inference;
  * --budget-usd greater than 0 and at most 10, tracked from each call's reported cost (actual, else the larger of the
    provider's estimate and ours, else ours); the run stops BEFORE a call that could cross the cap.
Credentials are read ONLY from --env-file (default ~/.config/rafii-library-eval/provider.env), names AI_GATEWAY_API_KEY /
OPENAI_API_KEY; process environment credentials are ignored. Values are never printed or written: the output contains
no credentials. --cache FILE stores the vectors (no credentials) so --from-cache can re-score without any provider call.

Usage:
  scripts/library-intelligence-eval.py --out evidence/retrieval-eval.json --budget-usd 10 --confirm-paid-inference --cache evidence/vectors.json
  scripts/library-intelligence-eval.py --out evidence/retrieval-rescore.json --from-cache evidence/vectors.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

AUTH_ENV = "RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION"
AUTH_VALUE = "james-2026-10-08-cap-10usd"
MAX_BUDGET_USD = 10.0
ALLOWED_CREDENTIALS = ("AI_GATEWAY_API_KEY", "OPENAI_API_KEY")
DEFAULT_ENV_FILE = "~/.config/rafii-library-eval/provider.env"
CORPUS = ROOT / "tests/fixtures/library_intelligence/eval/corpus.json"
QUERIES = ROOT / "tests/fixtures/library_intelligence/eval/queries.json"
DISTRACTOR_VERSION = "rli-distractors-2026-10-08.1"
DISTRACTOR_COUNT = 940
DISTRACTOR_SEED = 20261008
TYPES = ("lexical", "semantic", "cross_lingual", "code_switch")
EMBED_BATCH = 64


# --- distractors (deterministic; shared with the PG suite) ---------------------------------------------------------------
_PIECES_EN = ["a Bach prelude", "a Mozart sonata", "a Debussy arabesque", "a Liszt etude", "a Haydn sonata", "Scarlatti sonatas", "a Rachmaninoff prelude",
              "a Chopin waltz", "a Brahms waltz", "a Beethoven bagatelle", "Czerny studies", "a Grieg lyric piece"]
_PIECES_ZH = ["巴赫前奏曲", "莫扎特奏鳴曲", "德布西阿拉伯風", "李斯特練習曲", "海頓奏鳴曲", "史卡拉第奏鳴曲", "拉赫曼尼諾夫前奏曲", "蕭邦圓舞曲", "車爾尼練習曲"]
_PIECES_HANS = ["巴赫前奏曲", "莫扎特奏鸣曲", "德彪西阿拉伯风", "李斯特练习曲", "海顿奏鸣曲", "斯卡拉蒂奏鸣曲", "拉赫玛尼诺夫前奏曲", "肖邦圆舞曲", "车尔尼练习曲"]
_FOCUS_EN = ["even semiquavers", "voicing the melody", "a relaxed thumb", "clean page turns", "steady tempo", "dynamics in the middle section", "memory slips",
             "left-hand jumps", "phrasing the cadence"]
_FOCUS_ZH = ["十六分音符平均", "旋律聲部", "放鬆拇指", "穩定速度", "中段力度", "背譜", "樂句收尾"]
_FOCUS_HANS = ["十六分音符均匀", "旋律声部", "放松拇指", "稳定速度", "中段力度", "背谱", "乐句收尾"]
_VENUES_EN = ["Riverside Hall", "Lakeview Studio", "the university auditorium", "the community arts centre", "Maple Room", "the church hall on Elm Street"]
_VENUES_ZH = ["河畔音樂廳", "湖景錄音室", "大學禮堂", "社區藝術中心", "楓葉室", "教堂禮堂"]
_VENUES_HANS = ["河畔音乐厅", "湖景录音室", "大学礼堂", "社区艺术中心", "枫叶室", "教堂礼堂"]
_ITEMS_EN = ["spare scores", "a page-turner's pencil", "the black folder", "water and snacks", "a phone tripod", "the printed setlist"]
_ITEMS_ZH = ["備用樂譜", "鉛筆", "黑色文件夾", "水同小食", "手機腳架", "曲目表"]
_TOPICS_EN = ["practice habits", "choosing repertoire", "warming up the hands", "recording at home", "travelling with scores", "answering fan questions"]
_TOPICS_ZH = ["練習習慣", "揀曲目", "熱身", "喺屋企錄音", "帶住樂譜去旅行", "答粉絲問題"]
_VENDORS = ["Maple Music Supplies", "Northwind Printing", "Bluebell Florist", "Cedar Sound Rental", "Pine Street Framing"]
_DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_CITIES_EN = ["Taipei", "Singapore", "Seoul", "Macau", "Kuala Lumpur", "Bangkok"]


def _en(r, n):
    choice = n % 6
    if choice == 0:
        return (f"practice-log-{n:04d}.md", f"Practice log {n}", f"Practice log entry {n}: worked on {r.choice(_PIECES_EN)} for {r.randint(15, 90)} minutes, "
                f"focusing on {r.choice(_FOCUS_EN)}. Next session: {r.choice(_FOCUS_EN)}.")
    if choice == 1:
        return (f"rehearsal-reminder-{n:04d}.md", f"Rehearsal reminder {n}", f"Reminder {n}: rehearsal at {r.choice(_VENUES_EN)} on {r.randint(1, 28)} "
                f"{r.choice(_MONTHS_EN)}, arrive {r.randint(10, 45)} minutes early and bring {r.choice(_ITEMS_EN)}.")
    if choice == 2:
        return (f"post-idea-{n:04d}.md", f"Post idea {n}", f"Post idea {n}: a short video about {r.choice(_TOPICS_EN)}, published on {r.choice(_DAYS_EN)} "
                f"evening with three photos from the last concert.")
    if choice == 3:
        return (f"receipt-{n:04d}.md", f"Receipt {n}", f"Receipt RC-{n:05d} from {r.choice(_VENDORS)}: {r.randint(1, 12)} items, total HKD "
                f"{r.randint(80, 4800):,}. Paid by card.")
    if choice == 4:
        return (f"lesson-plan-{n:04d}.md", f"Lesson plan {n}", f"Lesson plan {n} for intermediate students: {r.choice(_FOCUS_EN)} with {r.choice(_PIECES_EN)}, "
                f"then sight-reading for {r.randint(5, 20)} minutes.")
    return (f"travel-note-{n:04d}.md", f"Travel note {n}", f"Travel note {n}: train to {r.choice(_CITIES_EN)} on {r.randint(1, 28)} {r.choice(_MONTHS_EN)}, "
            f"hotel near the old town, practice room booked for {r.randint(1, 4)} hours.")


def _hant(r, n):
    if n % 3 == 0:
        return (f"練習紀錄-{n:04d}.md", f"練習紀錄 {n}", f"練習紀錄第{n}則：練習{r.choice(_PIECES_ZH)}共{r.randint(15, 90)}分鐘，重點在{r.choice(_FOCUS_ZH)}。")
    if n % 3 == 1:
        return (f"綵排通知-{n:04d}.md", f"綵排通知 {n}", f"綵排通知{n}：{r.randint(1, 12)}月{r.randint(1, 28)}日於{r.choice(_VENUES_ZH)}集合，請帶{r.choice(_ITEMS_ZH)}。")
    return (f"社交構思-{n:04d}.md", f"社交構思 {n}", f"社交構思{n}：{r.choice(_DAYS_ZH)}晚上發佈短片，主題是{r.choice(_TOPICS_ZH)}。")


def _hans(r, n):
    if n % 2 == 0:
        return (f"练习记录-{n:04d}.md", f"练习记录 {n}", f"练习记录第{n}条：练习{r.choice(_PIECES_HANS)}{r.randint(15, 90)}分钟，重点是{r.choice(_FOCUS_HANS)}。")
    return (f"排练通知-{n:04d}.md", f"排练通知 {n}", f"排练通知{n}：{r.randint(1, 12)}月{r.randint(1, 28)}日在{r.choice(_VENUES_HANS)}集合，请准时到场。")


def _yue(r, n):
    if n % 2 == 0:
        return (f"練琴筆記-{n:04d}.md", f"練琴筆記 {n}", f"筆記{n}：今日練咗{r.choice(_PIECES_ZH)}{r.randint(15, 90)}分鐘，{r.choice(_FOCUS_ZH)}仲未掂，聽日再練。")
    return (f"拍片諗法-{n:04d}.md", f"拍片諗法 {n}", f"諗法{n}：想拍條片講{r.choice(_TOPICS_ZH)}，{r.choice(_DAYS_ZH)}夜晚出，記得帶{r.choice(_ITEMS_ZH)}。")


def _mixed(r, n):
    return (f"memo-{n:04d}.txt", f"Memo {n}", f"Memo {n}：今日 practice {r.choice(_PIECES_EN)} {r.randint(15, 90)} 分鐘，{r.choice(_FOCUS_ZH)} 要再 work 吓，"
            f"下個月 {r.choice(_VENUES_EN)} 個 gig 要準備 {r.choice(_ITEMS_EN)}。")


def distractors(count: int = DISTRACTOR_COUNT, seed: int = DISTRACTOR_SEED) -> list[dict]:
    """Deterministic templated creator-library notes in English, Traditional/Simplified Chinese, Cantonese and mixed
    Cantonese/English. They share the domain's general vocabulary (practice, rehearsal, concerts, receipts) so ranking is
    not trivial, but carry no judged facts. Every text is unique (it carries its own number)."""
    r = random.Random(seed)
    makers = [(_en, "en")] * 8 + [(_hant, "zh-Hant")] * 4 + [(_hans, "zh-Hans")] * 3 + [(_yue, "yue")] * 3 + [(_mixed, "yue-en")] * 2
    out = []
    for n in range(1, count + 1):
        maker, lang = makers[n % len(makers)]
        filename, title, text = maker(r, n)
        out.append({"id": f"x{n:04d}", "lang": lang, "filename": filename, "title": title, "text": text, "distractor": True})
    return out


# --- pure scoring helpers ------------------------------------------------------------------------------------------------------
def recall_at(ranked: list[str], relevant, k: int = 10) -> float:
    relevant = set(relevant)
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / min(k, len(relevant))


def summarize(per_query: list[dict], key: str) -> dict:
    """{type: {queries, recallAt10}} plus overall, for the ranking stored under per_query[i][key]."""
    out = {}
    for kind in TYPES + ("all",):
        rows = [q for q in per_query if kind == "all" or q["type"] == kind]
        if rows:
            out[kind] = {"queries": len(rows), "recallAt10": round(sum(recall_at(q[key], q["relevant"]) for q in rows) / len(rows), 4)}
    return out


def items_for(documents: list[dict]) -> dict:
    """Search-universe-shaped items so the real search._exact / search._metadata_matches run unchanged."""
    import hashlib
    out = {}
    for n, d in enumerate(documents):
        out[d["id"]] = {"assetId": d["id"], "versionId": d["id"], "filename": d["filename"], "title": d["title"], "tags": [], "media": {},
                        "sha256": hashlib.sha256(d["text"].encode()).hexdigest(), "createdAt": float(n), "kind": "document", "legacy": False}
    return out


def segment_tokens(text: str) -> list[str]:
    """The lexemes PostgreSQL's 'simple' parser makes from a segment's stored search_terms (apostrophes split)."""
    from postriff_phase2.library_intelligence import textnorm
    tokens = []
    for term in textnorm.search_terms(text).split():
        tokens += [part for part in term.split("'") if part]
    return tokens


def lexical_ranking(query: str, documents: list[dict], items: dict, tokens: dict | None = None) -> tuple[list[str], list[str]]:
    """(exact, lexical) for one query: the real exact-identity and metadata functions, and an in-memory reproduction of
    the segment stage (AND over textnorm terms, ts_rank-like length normalization), fused by the real search.rrf.
    `tokens` ({document id: segment_tokens}) avoids re-tokenizing the corpus for every query."""
    from postriff_phase2.library_intelligence import search, textnorm
    exact = [k for k, _ in search._exact(query, items)]
    tsq = textnorm.tsquery(query)
    segment = []
    if tsq:
        terms = tsq.split(" & ")
        scored = []
        for order, d in enumerate(documents):
            doc_tokens = tokens[d["id"]] if tokens is not None else segment_tokens(d["text"])
            present = set(doc_tokens)
            if all(t in present for t in terms):
                rank = sum(doc_tokens.count(t) for t in terms) / (1 + math.log(1 + len(doc_tokens)))
                scored.append((-rank, order, d["id"]))
        segment = [doc_id for _, _, doc_id in sorted(scored)][:search.LEXICAL_K]
    metadata = [k for k, _ in search._metadata_matches(textnorm.query_terms(query), items)]
    return exact, search.rrf([segment, metadata])[:search.LEXICAL_K]


def cosine_ranking(query_vector: list[float], vectors: dict, limit: int) -> list[str]:
    def norm(v):
        return math.sqrt(sum(x * x for x in v)) or 1.0
    qn = norm(query_vector)
    scored = [(-(sum(a * b for a, b in zip(query_vector, v)) / (qn * norm(v))), doc_id) for doc_id, v in vectors.items()]
    return [doc_id for _, doc_id in sorted(scored)[:limit]]


def hybrid_ranking(exact: list[str], lexical: list[str], semantic: list[str]) -> list[str]:
    """search_library's order: exact identity first, then RRF (k=60, equal weights) over the mode lists."""
    from postriff_phase2.library_intelligence import search
    seen = set(exact)
    return exact + [k for k in search.rrf([lexical, semantic]) if k not in seen]


# --- gate, credentials, budget ------------------------------------------------------------------------------------------------
def load_env_file(path) -> dict:
    """Only the allowed credential names, from this file only. Values never leave this function's return value."""
    path = Path(os.path.expanduser(str(path)))
    if not path.is_file():
        raise SystemExit(f"Credential file not found: {path}")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name in ALLOWED_CREDENTIALS and value:
            out[name] = value
    return out


def env_file_mode_warning(path) -> str | None:
    try:
        mode = Path(os.path.expanduser(str(path))).stat().st_mode
    except OSError:
        return None
    return "credential file is readable by group/others; chmod 600 recommended" if mode & (stat.S_IRWXG | stat.S_IRWXO) else None


def authorization(environ, *, confirmed: bool, budget_usd, credentials: dict | None = None) -> dict:
    reasons = []
    if str(environ.get(AUTH_ENV) or "") != AUTH_VALUE:
        reasons.append(f"{AUTH_ENV} must be {AUTH_VALUE} (James's capped authorization)")
    if not confirmed:
        reasons.append("--confirm-paid-inference was not passed")
    if not isinstance(budget_usd, (int, float)) or isinstance(budget_usd, bool) or not 0 < float(budget_usd) <= MAX_BUDGET_USD:
        reasons.append(f"--budget-usd must be greater than 0 and at most {MAX_BUDGET_USD:g}")
    if credentials is not None and "AI_GATEWAY_API_KEY" not in credentials:
        reasons.append("AI_GATEWAY_API_KEY is missing from the credential file")
    return {"status": "AUTHORIZED"} if not reasons else {"status": "BLOCKED", "reasons": reasons}


class BudgetGuard:
    """Hard cap in USD micro-units; refuses any call that could cross it."""

    def __init__(self, cap_usd: float):
        self.cap_micro = int(round(float(cap_usd) * 1_000_000))
        self.spent_micro = 0
        self.calls = 0
        self.kinds: dict = {}

    def allows(self, estimate_micro: int) -> bool:
        return self.spent_micro + max(0, int(estimate_micro)) <= self.cap_micro

    def record(self, cost: dict | None, *, estimate: int):
        cost = cost or {}
        kind = cost.get("kind") or "unknown"
        reported = cost.get("usdMicro") if isinstance(cost.get("usdMicro"), int) else None
        charge = reported if kind == "actual" and reported is not None else max(reported or 0, int(estimate))
        self.spent_micro += max(0, charge)
        self.calls += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def receipt(self) -> dict:
        return {"capUsd": self.cap_micro / 1_000_000, "spentUsd": round(self.spent_micro / 1_000_000, 6), "calls": self.calls, "costKinds": self.kinds}


def provider_environ(credentials: dict, model: str | None) -> dict:
    """The only environment the provider seam sees: flags plus the file's credentials (never the process environment)."""
    env = {"RAFII_LIBRARY_ENRICHMENT_ENABLED": "1", "RAFII_LIBRARY_EMBEDDINGS_ENABLED": "1", **credentials}
    if model:
        env["RAFII_LIBRARY_EMBEDDING_MODEL"] = model
    return env


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _embed_all(prov, guard, texts: dict, dims: int) -> dict | None:
    """{id: vector}, batch by batch; None when the budget would be crossed (nothing partial is scored)."""
    vectors, ids = {}, list(texts)
    for start in range(0, len(ids), EMBED_BATCH):
        batch = ids[start:start + EMBED_BATCH]
        estimate = prov.estimate("embedding", units=sum(len(texts[i]) for i in batch))  # characters as a token upper bound
        if not guard.allows(estimate):
            return None
        result = prov.embed([texts[i] for i in batch], dims=dims)
        guard.record(result.cost, estimate=estimate)
        vectors.update(dict(zip(batch, result.value)))
    return vectors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--confirm-paid-inference", action="store_true")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--model", help="override the embedding model (default: the provider seam's default)")
    parser.add_argument("--cache", help="write document/query vectors here (no credentials) for later re-scoring")
    parser.add_argument("--from-cache", help="re-score vectors captured earlier; no provider call, no authorization")
    args = parser.parse_args(argv)
    from postriff_phase2.library_intelligence import providers, search, textnorm
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    qset = json.loads(QUERIES.read_text(encoding="utf-8"))
    documents = corpus["documents"] + distractors()
    queries = qset["queries"]
    receipt = {"candidateSha": _sha(), "corpus": corpus["version"], "queries": qset["version"], "distractors": DISTRACTOR_VERSION,
               "documents": len(documents), "rankingVersion": search.RANKING_VERSION, "normalizerVersion": textnorm.NORMALIZER_VERSION,
               "startedAt": time.time(),
               "labels": ["in-memory exact cosine stands in for pgvector; the PG suite proves the pgvector/HNSW path",
                          "lexical-only is an in-memory reproduction of the SQL lexical stage; the PG suite gives the authoritative lexical baseline",
                          "one embedding per document: each corpus document is a single passage"]}
    if args.from_cache:
        cached = json.loads(Path(args.from_cache).read_text(encoding="utf-8"))
        doc_vectors, query_vectors = cached["documents"], cached["queries"]
        receipt.update(execution="offline-cache", model=cached.get("model"), dims=cached.get("dims"), budget=None)
    else:
        credentials = load_env_file(args.env_file) if Path(os.path.expanduser(args.env_file)).is_file() else {}
        gate = authorization(os.environ, confirmed=args.confirm_paid_inference, budget_usd=args.budget_usd, credentials=credentials)
        if gate["status"] != "AUTHORIZED":
            print(json.dumps({**gate, "candidateSha": receipt["candidateSha"], "execution": "not-run", "credentialNames": sorted(credentials)}, indent=2))
            return 3
        warning = env_file_mode_warning(args.env_file)
        prov = providers.Providers(environ=provider_environ(credentials, args.model))
        status = prov.status()["embedding"]
        if not status["available"]:
            print(json.dumps({"status": "BLOCKED", "reasons": [f"embedding provider unavailable: {status['reason']}"], "execution": "not-run"}, indent=2))
            return 3
        guard = BudgetGuard(args.budget_usd)
        dims = providers.EMBED_DIMS
        doc_vectors = _embed_all(prov, guard, {d["id"]: d["text"] for d in documents}, dims)
        query_vectors = _embed_all(prov, guard, {q["id"]: q["query"] for q in queries}, dims) if doc_vectors is not None else None
        receipt.update(execution="real-provider", authorization=AUTH_VALUE, model=prov.model("embedding"), dims=dims, budget=guard.receipt(),
                       credentialNames=sorted(credentials), warnings=[w for w in (warning,) if w])
        if doc_vectors is None or query_vectors is None:
            receipt.update(status="STOPPED_AT_BUDGET", finishedAt=time.time())
            Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"status": "STOPPED_AT_BUDGET", "budget": receipt["budget"]}, indent=2))
            return 1
        if args.cache:
            Path(args.cache).write_text(json.dumps({"model": receipt["model"], "dims": dims, "documents": doc_vectors, "queries": query_vectors}), encoding="utf-8")
    items = items_for(documents)
    tokens = {d["id"]: segment_tokens(d["text"]) for d in documents}
    per_query = []
    for q in queries:
        exact, lexical = lexical_ranking(q["query"], documents, items, tokens)
        semantic = cosine_ranking(query_vectors[q["id"]], doc_vectors, search.SEMANTIC_K)
        per_query.append({"id": q["id"], "type": q["type"], "relevant": q["relevant"], "lexicalOnly": (exact + [k for k in lexical if k not in exact])[:10],
                          "semanticOnly": semantic[:10], "hybrid": hybrid_ranking(exact, lexical, semantic)[:10]})
    receipt["recallAt10"] = {mode: summarize(per_query, mode) for mode in ("lexicalOnly", "semanticOnly", "hybrid")}
    receipt["hybridMisses"] = [{"id": q["id"], "type": q["type"], "relevant": q["relevant"], "top10": q["hybrid"]} for q in per_query
                               if recall_at(q["hybrid"], q["relevant"]) < 1.0]
    receipt["perQuery"] = per_query
    receipt["status"] = "complete"
    receipt["finishedAt"] = time.time()
    Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "execution": receipt["execution"], "recallAt10": receipt["recallAt10"], "budget": receipt.get("budget")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
