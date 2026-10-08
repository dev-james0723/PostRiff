"""T04 shared Library search against disposable PostgreSQL (acceptance A025, A027, A028, A029, A030, A023; A004 counts).

Run by scripts/library-intelligence-validation.sh in cloud CI, twice:
- LIBRARY_PG_PHASE=no_vector: migration 097 found no pgvector, so semantic/visual modes must report themselves
  unavailable while exact and lexical results stay correct and labelled (honest degradation, A030).
- LIBRARY_PG_PHASE=vector: pgvector is installed. Text kNN uses SYNTHETIC deterministic fixture vectors (labelled as
  fixtures; they prove the SQL path, model/generation separation and fusion, not semantic quality). Visual kNN uses
  real local perceptual vectors computed from generated images.

Identity, storage and the embedding provider are synthetic; budget admission is stubbed and labelled; no network.
"""
import hashlib
import io
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.library_intelligence import api, index, providers, search, textnorm  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402
from postriff_phase2.site_agent.library_reads import library_read, library_search  # noqa: E402
from postriff_phase2.site_agent.tools import Context  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
assert PHASE in ("no_vector", "vector"), PHASE
os.environ["RAFII_LIBRARY_RETRIEVAL_ENABLED"] = "1"
ONE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000044"
MODEL = "openai/text-embedding-3-large"
N = 1200
BASE = time.time() - 40 * 86400
clock = [time.time()]
checks, timings = [], {}


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "other"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else OTHER


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


def hot(dims, values):
    """Synthetic deterministic fixture vector (not a semantic embedding)."""
    v = [0.0] * dims
    for i, w in values.items():
        v[i] = float(w)
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


class FixtureEmbedder:
    """Synthetic provider: returns a fixed fixture vector; proves the adapter path only."""

    def __init__(self, vector=None, unavailable=None):
        self.vector, self.unavailable, self.calls = vector, unavailable, 0

    def model(self, capability):
        return MODEL

    def require(self, capability):
        if self.unavailable:
            raise providers.ProviderUnavailable(capability, self.unavailable)

    def estimate(self, capability, *, units):
        return 1

    def embed(self, texts, *, dims=1024):
        self.calls += 1
        return providers.ProviderResult([list(self.vector) for _ in texts], "fixture", MODEL, 1)


index._reserve = lambda *a, **k: {"status": "reserved", "reservationId": "synthetic-fixture"}  # labelled synthetic budget admission
index._settle = lambda *a, **k: None


def run(ws, params, *, principal=ONE, embedder=None):
    service = SimpleNamespace(library_intelligence=SimpleNamespace(providers=embedder or FixtureEmbedder(unavailable="embeddings_disabled")))
    started = time.monotonic()
    with connection() as db, db.cursor() as cur:
        result = api.search(cur, principal, ws, params, service=service)
    timings.setdefault(params.get("query") or "browse", []).append(round((time.monotonic() - started) * 1000, 1))
    return result


def refused(ws, params, **kw):
    try:
        run(ws, params, **kw)
    except AlphaError as error:
        return error
    return None


def keys(result):
    return [h["assetRef"]["versionId"] for h in result["hits"]]


def png(colour, stripes=None, size=(96, 64)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, colour)
    if stripes:
        draw = ImageDraw.Draw(image)
        for x in range(0, size[0], 12):
            draw.rectangle([x, 0, x + 5, size[1]], fill=stripes)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


ASSET_SQL = ("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,"
             "processing_status,analysis_status,indexing_status,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),now())")
LATE_SQL = ("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,"
            "processing_status,analysis_status,indexing_status,created_at,updated_at) VALUES(%s,%s,%s,'late.md','document','text/markdown','md',5,%s,"
            "'postriff-library',%s,'ready','not_applicable','ready',now(),now())")
SEGMENT_SQL = ("INSERT INTO public.pr_library_segments(id,workspace_id,asset_key,version_key,ordinal,kind,text,language,locator,extractor,extractor_version,"
               "text_hash,source_sha256,origin,normalizer_version,search_terms,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'t04-fixture','1',%s,%s,"
               "'extracted',%s,%s,to_timestamp(%s))")


def asset_rows(ws, owner, count, prefix):
    rows, out = [], []
    for i in range(count):
        aid = uuid.uuid5(uuid.NAMESPACE_URL, f"rafii-t04/{ws}/{i}")
        sha = hashlib.sha256(f"{prefix}-{ws}-{i}".encode()).hexdigest()
        created = BASE + i * 60
        rows.append((aid, ws, owner, f"{prefix}-{i:04d}.md", "document", "text/markdown", "md", 100 + i, sha, "postriff-library", f"{aid.hex}.md",
                     "ready", "not_applicable", "ready", created))
        out.append({"i": i, "key": aid.hex, "sha": sha, "filename": f"{prefix}-{i:04d}.md", "created": created})
    return rows, out


def segment_row(ws, asset, text, *, ordinal=0, kind="text", language=None, locator=None):
    return (uuid.uuid4(), ws, asset["key"], asset["key"], ordinal, kind, text, language, json.dumps(locator) if locator else None,
            hashlib.sha256(text.encode()).hexdigest(), asset.get("sha") or None, textnorm.NORMALIZER_VERSION, textnorm.search_terms(text), asset["created"] + 30)


# --- fixture ---------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (OTHER,))
    has_vector = db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
                            "AND column_name='embedding'").fetchone() is not None
check(f"{PHASE}: pgvector column {'present' if PHASE == 'vector' else 'absent'} as the phase requires", has_vector == (PHASE == "vector"), has_vector)
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
wid = service.bootstrap("one", "studio")["workspaceId"]
other = service.bootstrap("other", "studio")["workspaceId"]
check("two isolated workspaces", wid != other)

rows, assets = asset_rows(wid, ONE, N, "brief")
other_rows, other_assets = asset_rows(other, OTHER, 7, "theirs")
by_position = sorted(assets, key=lambda a: -a["created"])  # newest first
p201, p1001, oldest = by_position[200], by_position[1000], by_position[-1]
special = {0: ("Brahms sonata fingering from the 2019 masterclass, bars 12 to 20.", "en", {"kind": "page", "page": 3, "section": "Masterclass"}),
           10: ("我哋喺演奏會之後去飲茶，好開心。", "yue", None), 11: ("演奏会门票已经售完，请关注下一场。", "zh-Hans", None),
           12: ("The concert tickets sold out; rehearsal moved to Friday.", "en", None), 13: ("今晚 rehearsal 喺 City Hall，記得帶樂譜。", "yue", None),
           14: ("新的头发造型照片", "zh-Hans", None), 20: ("Money planned for the spring concert season", "en", None),
           21: ("Quarterly piano recital budget", "en", None)}
segment_ids = {}
with connection() as db, db.cursor() as cur:
    cur.executemany(ASSET_SQL, rows + other_rows)
    segments = []
    for a in assets:
        text, language, locator = special.get(a["i"], (f"Studio diary entry {a['i']:04d} general notes", "en", None))
        row = segment_row(wid, a, text, language=language, locator=locator)
        segment_ids[a["i"]] = row[0].hex
        segments.append(row)
    segments.append(segment_row(wid, oldest, "Obsolete wording about Brahms masterclass fingering.", ordinal=4))
    segments += [segment_row(other, a, "Brahms masterclass fingering notes from another studio") for a in other_assets]
    cur.executemany(SEGMENT_SQL, segments)
    cur.execute("UPDATE public.pr_library_segments SET superseded_at=now() WHERE workspace_id=%s AND text LIKE 'Obsolete%%'", (wid,))
    photos = [{"id": uuid.uuid5(uuid.NAMESPACE_URL, f"rafii-t04/photo/{n}").hex, "mime": "image/png", "width": w, "height": h, "originalFilename": f"poster-{n}.png",
               "createdAt": BASE - 100 + n, "bytes": 1000} for n, (w, h) in enumerate(((1080, 1920), (1080, 1920), (1920, 1080), (1080, 1920)))]
    cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,assets}',%s::jsonb),revision=revision+1 WHERE id=%s", (json.dumps(photos), wid))
    caption = {"key": photos[3]["id"], "created": photos[3]["createdAt"], "sha": None}
    cur.execute(SEGMENT_SQL, segment_row(wid, caption, "a red sunset over the harbour", kind="caption"))
total = N + len(photos)

# --- A025: complete scope, exact identity, old segment -------------------------------------------------------------
browse = run(wid, {"limit": 30})
check("A029 coverage counts are server-side, not the loaded page", browse["coverage"]["accessibleAssetCount"] == total and len(browse["hits"]) == 30,
      browse["coverage"])
check("A029 facets span the whole eligible scope", sum(browse["facets"]["kinds"].values()) == total, browse["facets"])
check("A025 position 201 by exact filename", keys(run(wid, {"query": p201["filename"]}))[:1] == [p201["key"]])
for label, query in (("id", p1001["key"]), ("dashed id", str(uuid.UUID(hex=p1001["key"]))), ("hash prefix", p1001["sha"][:10])):
    found = run(wid, {"query": query})
    check(f"A025 position 1001 by exact {label}", keys(found)[:1] == [p1001["key"]], keys(found)[:3])
old = run(wid, {"query": "Brahms masterclass fingering"})
check("A025 oldest asset's segment found by exact query", keys(old) == [oldest["key"]], keys(old))
check("A025 locator and snippet come from the current segment", old["hits"][0].get("locator") == {"kind": "page", "page": 3, "section": "Masterclass"}
      and "Brahms" in old["hits"][0]["snippet"] and "Obsolete" not in old["hits"][0]["snippet"], old["hits"][0])
dims = run(wid, {"query": "1080x1920"})
check("A026 dimensions are an exact match", set(keys(dims)) == {photos[0]["id"], photos[1]["id"], photos[3]["id"]}
      and all("dimensions" in {r["kind"] for r in h["matchReasons"]} for h in dims["hits"]), keys(dims))

# --- A027: Traditional, Simplified, Cantonese, English, code-switching ----------------------------------------------
k = {i: assets[i]["key"] for i in special}
for query, expected in (("演奏会", {k[10], k[11]}), ("演奏會", {k[10], k[11]}), ("演奏會 門票", {k[11]}), ("rehearsal 喺", {k[13]}),
                        ("REHEARSAL", {k[12], k[13]}), ("飲茶", {k[10]}), ("頭髮", {k[14]}), ("city hall", {k[13]})):
    got = set(keys(run(wid, {"query": query})))
    check(f"A027 {query!r} finds exactly the expected passages", got == expected, (query, got, expected))
yue = run(wid, {"query": "演奏會", "filters": {"languages": ["yue"]}})
check("A027 language filter narrows before ranking", keys(yue) == [k[10]], keys(yue))

# --- A029: paging without skips or duplicates; stale cursors refresh -----------------------------------------------
seen, cursor, pages, late = [], None, 0, None
while True:
    page = run(wid, {"limit": 100, **({"cursor": cursor} if cursor else {})})
    pages += 1
    seen += keys(page)
    if pages == 1:
        with connection() as db:
            late = uuid.uuid4()
            db.execute(LATE_SQL, (late, wid, ONE, hashlib.sha256(b"late").hexdigest(), f"{late.hex}.md"))
    cursor = page["nextCursor"]
    if not cursor:
        break
check("A029 browse pages cover every eligible item exactly once", len(seen) == total and len(set(seen)) == total, (len(seen), len(set(seen))))
check("A029 an item created mid-paging waits for a refresh", late.hex not in seen)
check("A029 a fresh search includes it", run(wid, {"limit": 1})["coverage"]["accessibleAssetCount"] == total + 1)
total += 1

first = run(wid, {"limit": 50})
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET processing_status='deleting' WHERE id=%s", (uuid.UUID(hex=assets[5]["key"]),))
error = refused(wid, {"limit": 50, "cursor": first["nextCursor"]})
check("A029 a removal between pages is a recoverable 409 refresh", error is not None and error.status == 409 and error.code == "library_cursor_stale", error)
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET processing_status='ready' WHERE id=%s", (uuid.UUID(hex=assets[5]["key"]),))

lexical_seen, cursor, bounded = [], None, None
for _ in range(12):
    page = run(wid, {"query": "studio diary", "limit": 100, **({"cursor": cursor} if cursor else {})})
    bounded = bounded or page
    lexical_seen += keys(page)
    cursor = page["nextCursor"]
    if not cursor:
        break
check("A029 lexical paging has no duplicates", len(lexical_seen) == len(set(lexical_seen)), len(lexical_seen))
check("A029 a candidate bound is reported, never hidden", bounded["totalHits"]["relation"] == "gte" and "lexical" in bounded["ranking"]["boundsReached"]
      and len(lexical_seen) == search.LEXICAL_K and bounded["totalHits"]["value"] >= N - len(special) - 1 and bounded["warnings"], bounded["totalHits"])

# --- A004: counts and identities never leak across workspaces ------------------------------------------------------
theirs = run(other, {"query": "Brahms masterclass fingering"}, principal=OTHER)
check("A004 the other workspace sees only its own items", set(keys(theirs)) == {a["key"] for a in other_assets}, keys(theirs))
check("A004 the other workspace's coverage counts only its own items", theirs["coverage"]["accessibleAssetCount"] == 7
      and sum(theirs["facets"]["kinds"].values()) == 7, theirs["coverage"])
check("A004 a foreign id finds nothing", run(other, {"query": p1001["key"]}, principal=OTHER)["hits"] == [])
foreign = refused(other, {"scope": {"kind": "selection", "assetRefs": [{"assetId": p1001["key"], "versionId": p1001["key"], "sha256": ""}]}}, principal=OTHER)
missing = refused(other, {"scope": {"kind": "selection", "assetRefs": [{"assetId": "f" * 32, "versionId": "f" * 32, "sha256": ""}]}}, principal=OTHER)
check("A004 a foreign selection is indistinguishable from a missing one", foreign is not None and missing is not None
      and (foreign.status, str(foreign), foreign.code) == (missing.status, str(missing), missing.code) == (404, str(missing), "library_unavailable"))
check("A004 a member cannot search a workspace it does not belong to", refused(wid, {"query": ""}, principal=OTHER) is not None)

# --- A028: UI and Agent share one policy; purposes filter before ranking -------------------------------------------
source_asset = p1001
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET source_id='src-t04' WHERE id=%s", (uuid.UUID(hex=source_asset["key"]),))
sources = [{"id": "src-t04", "kind": "document", "active": True, "sourcePolicy": "rewrite_approval", "egressConsent": ["local", "cloud"],
            "useApprovals": [], "facts": [{"id": "f1", "text": "Studio diary approved fact", "approved": True}],
            "origin": {"kind": "library", "assetId": source_asset["key"], "sha256": source_asset["sha"]}, "createdAt": time.time()}]
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{sources}',%s::jsonb),revision=revision+1 WHERE id=%s", (json.dumps(sources), wid))
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state = json.loads(state) if isinstance(state, str) else state
fact_query = f"studio diary {source_asset['i']:04d}"
ui_side = run(wid, {"query": fact_query, "purpose": "draft_evidence"})
with connection() as db, db.cursor() as cur:
    tool = library_search(Context(state=state, membership=Membership("owner"), principal=ONE, workspace_id=wid, cur=cur,
                                  service=SimpleNamespace(library_intelligence=SimpleNamespace(providers=FixtureEmbedder(unavailable="embeddings_disabled"))),
                                  now=time.time()), fact_query)
found = {r["assetId"]: r for r in tool["data"]["results"]}
check("A028 the Agent finds a source far outside the former newest-200 window", source_asset["key"] in found and found[source_asset["key"]]["facts"][0]["id"] == "f1",
      tool["data"])
check("A028 UI and Agent routes report the same eligibility and coverage", tool["data"]["coverage"]["facts"]["accessibleAssetCount"] == 1
      == ui_side["coverage"]["accessibleAssetCount"] and keys(ui_side) == [source_asset["key"]], (tool["data"]["coverage"], ui_side["coverage"]))

with connection() as db:
    db.execute("INSERT INTO public.pr_library_policy(workspace_id) VALUES(%s) ON CONFLICT DO NOTHING", (wid,))
before_grant = run(wid, {"limit": 100})
with connection() as db:
    revision = db.execute("UPDATE public.pr_library_policy SET grant_revision=grant_revision+1 WHERE workspace_id=%s RETURNING grant_revision", (wid,)).fetchone()[0]
    db.execute("INSERT INTO public.pr_library_grants(id,workspace_id,grant_type,scope_kind,scope_key,purpose,granted_by,granted_revision) "
               "VALUES(%s,%s,'purpose','asset',%s,'answer',%s,%s)", (uuid.uuid4(), wid, assets[13]["key"], ONE, revision))
    db.execute("INSERT INTO public.pr_library_grants(id,workspace_id,grant_type,scope_kind,scope_key,location,category,granted_by,granted_revision) "
               "VALUES(%s,%s,'processing','workspace','*','cloud','llm',%s,%s)", (uuid.uuid4(), wid, ONE, revision))
stale = refused(wid, {"limit": 100, "cursor": before_grant["nextCursor"]})
check("A029 a grant change makes old cursors refresh", stale is not None and stale.code == "library_cursor_stale", stale)
answer = run(wid, {"query": "rehearsal", "purpose": "answer"})
check("A028 purpose filtering happens before ranking", keys(answer) == [k[13]] and answer["coverage"]["accessibleAssetCount"] == 1, (keys(answer), answer["coverage"]))
check("A028 answer hits are attribution-only", answer["hits"][0]["sourceStatus"]["attributionOnly"] is True)
with connection() as db, db.cursor() as cur:
    ctx = Context(state=state, membership=Membership("owner"), principal=ONE, workspace_id=wid, cur=cur,
                  service=SimpleNamespace(library_intelligence=SimpleNamespace(providers=FixtureEmbedder(unavailable="embeddings_disabled"))), now=time.time())
    agent = library_search(ctx, "rehearsal")
    read = library_read(ctx, assets[13]["key"])
passage_hits = {r["assetId"]: r for r in agent["data"]["results"]}
check("A028 the Agent gets the same purpose-filtered passages", set(passage_hits) == {k[13]} and passage_hits[k[13]]["passages"]
      and passage_hits[k[13]]["attributionOnly"], agent["data"])
check("A028 the Agent read returns attributed passages only where allowed", read["data"]["passages"] and read["data"]["facts"] == [], read["data"])

# --- A030 / A026 / A023: semantic and visual, honest by phase -------------------------------------------------------
semantic_target, lexical_target = assets[20], assets[21]
caption_photo = photos[3]["id"]
if PHASE == "no_vector":
    embedder = FixtureEmbedder(hot(1024, {1: 1.0}))
    degraded = run(wid, {"query": "recital budget"}, embedder=embedder)
    check("A030 lexical-only results are labelled without pgvector", degraded["coverage"]["modesApplied"] == ["lexical"] and degraded["coverage"]["partial"]
          and keys(degraded) == [lexical_target["key"]] and any("not installed" in w for w in degraded["warnings"]), degraded)
    check("A030 no paid query embedding when the index cannot be searched", embedder.calls == 0)
    visual = run(wid, {"similarTo": {"assetId": photos[0]["id"], "versionId": photos[0]["id"], "sha256": ""}})
    check("A023 visual similarity reports itself unavailable without pgvector", visual["coverage"]["modesApplied"] == [] and visual["hits"] == [] and visual["warnings"])
    with connection() as db, db.cursor() as cur:
        honest = index.write_embeddings(cur, wid, {"assetId": photos[0]["id"], "versionId": photos[0]["id"]},
                                        [{"modality": "visual", "modelId": index.VISUAL_MODEL, "dims": 256, "vector": index.visual_features(png((200, 30, 30))), "segmentId": None}],
                                        consent_revision=0, index_generation=1)
    check("A030 embedding writes degrade honestly without pgvector", honest == {"stored": 0, "superseded": 0, "vector": False, "reason": "vector_unavailable"}, honest)
else:
    with connection() as db, db.cursor() as cur:
        for target, vector in ((semantic_target, hot(1024, {1: 1.0, 2: 0.2})), (lexical_target, hot(1024, {0: 1.0}))):
            written = index.write_embeddings(cur, wid, {"assetId": target["key"], "versionId": target["key"]},
                                             [{"modality": "text", "modelId": MODEL, "dims": 1024, "vector": vector, "segmentId": segment_ids[target["i"]]}],
                                             consent_revision=0, index_generation=1)
            assert written["stored"] == 1, written
        index.write_embeddings(cur, wid, {"assetId": assets[30]["key"], "versionId": assets[30]["key"]},
                               [{"modality": "text", "modelId": "other/model", "dims": 1024, "vector": hot(1024, {1: 1.0}), "segmentId": segment_ids[30]}],
                               consent_revision=0, index_generation=1)
        for photo, image in zip(photos[:3], (png((200, 30, 30)), png((190, 40, 35), (170, 20, 20)), png((20, 40, 200), (240, 240, 240)))):
            index.write_embeddings(cur, wid, {"assetId": photo["id"], "versionId": photo["id"]},
                                   [{"modality": "visual", "modelId": index.VISUAL_MODEL, "dims": 256, "vector": index.visual_features(image), "segmentId": None}],
                                   consent_revision=0, index_generation=1)
    embedder = FixtureEmbedder(hot(1024, {1: 1.0}))
    hybrid = run(wid, {"query": "recital budget"}, embedder=embedder)
    reasons = {h["assetRef"]["versionId"]: {r["kind"] for r in h["matchReasons"]} for h in hybrid["hits"]}
    check("A026 fixture kNN joins lexical results (synthetic vectors, not semantic quality)", hybrid["coverage"]["modesApplied"] == ["lexical", "semantic"]
          and keys(hybrid)[0] == lexical_target["key"] and "semantic" in reasons.get(semantic_target["key"], set()), reasons)
    check("A026 vectors from another model are never compared", assets[30]["key"] not in reasons, reasons)
    with connection() as db, db.cursor() as cur:
        cur.execute("SET LOCAL enable_seqscan = off")
        cur.execute("SET LOCAL enable_sort = off")
        params = {"vec": index.vector_literal(hot(1024, {1: 1.0})), "w": wid, "modality": "text", "dims": 1024, "model": MODEL, "gen": 1, "t": time.time(),
                  "keys": [a["key"] for a in assets], "k": search.SEMANTIC_K}
        cur.execute("EXPLAIN " + search.KNN_TEXT_SQL.format(open="", close=""), params)
        text_plan = "\n".join(r[0] for r in cur.fetchall())
        cur.execute("EXPLAIN " + search.KNN_VISUAL_SQL.format(open="", close=""), {**params, "vec": index.vector_literal(index.visual_features(png((1, 2, 3)))),
                                                                                  "modality": "visual", "dims": 256, "model": index.VISUAL_MODEL})
        visual_plan = "\n".join(r[0] for r in cur.fetchall())
    check("A031 text kNN matches the partial HNSW expression index", "pr_library_embeddings_text_1024" in text_plan, text_plan)
    check("A031 visual kNN matches the partial HNSW expression index", "pr_library_embeddings_visual_256" in visual_plan, visual_plan)
    similar = run(wid, {"similarTo": {"assetId": photos[0]["id"], "versionId": photos[0]["id"], "sha256": ""}})
    check("A023 local perceptual vectors rank the similar image first", similar["coverage"]["modesApplied"] == ["visual"]
          and keys(similar) == [photos[1]["id"], photos[2]["id"]], keys(similar))
    check("A023 a caption-only photo is not a visual result and makes coverage partial", caption_photo not in keys(similar) and similar["coverage"]["partial"])
    words = run(wid, {"query": "red", "modes": ["lexical", "visual"]})
    check("A023 a caption match is labelled lexical, never visual", keys(words) == [caption_photo]
          and {r["kind"] for r in words["hits"][0]["matchReasons"]} == {"lexical"} and words["coverage"]["modesApplied"] == ["lexical"], words)
    db_failure = run(wid, {"query": "recital budget"}, embedder=FixtureEmbedder(unavailable="gateway_credential_missing"))
    check("A030 provider outage keeps labelled lexical results", db_failure["coverage"]["modesApplied"] == ["lexical"] and db_failure["warnings"]
          and keys(db_failure) == [lexical_target["key"]], db_failure)

latency = {name: max(values) for name, values in timings.items()}
print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable PostgreSQL; synthetic identity, storage, provider and budget admission; "
                  "text vectors are fixtures, visual vectors are real local perceptual features", "assets": total, "checks": checks,
                  "maxLatencyMsBySearch": latency, "note": "latency here is a functional-suite observation, not the A031 benchmark"}, indent=2, ensure_ascii=False))
