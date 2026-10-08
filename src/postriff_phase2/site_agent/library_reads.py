"""Library retrieval for AI: an adapter onto the shared Library search (library_intelligence.search.search_library).

The Agent and the Library UI use the same eligibility, ranking and coverage. Two purposes are read, each checked before
ranking and re-checked before delivery:
- facts: `draft_evidence` — Ideas sources imported from Library whose approved facts and cloud sharing pass the existing
  source/egress gates (unchanged from the previous behaviour, now without the newest-200 window);
- passages: `answer` plus a ('cloud', 'llm') processing grant — the Agent's model may run in the cloud, so private
  passage text needs both. Passages are the source's own words with locators, attributed, never approved facts.

When RAFII_LIBRARY_RETRIEVAL_ENABLED is off or the Library intelligence schema is absent, the previous approved-facts
behaviour runs (still without any recency window). Runs in the caller's transaction; never reads storage.
"""
from postriff_alpha.domain import AlphaError
from .. import source_policy
from . import contracts

CLOUD_LLM = {'location': 'cloud', 'category': 'llm'}
PASSAGE_CHARS = 1500
READ_PASSAGES = 8
NOT_ADMITTED = 'This Library source needs fact review and cloud sharing permission, or is unavailable.'
NOTHING_ADMITTED = 'Import a Library source, review its facts and allow cloud sharing on Memory before AI retrieval.'
READ_SEGMENTS_SQL = ("/* lib:segments-for-read */ SELECT replace(id::text,'-',''),text,locator,kind,language,ordinal FROM public.pr_library_segments "
                     "WHERE workspace_id=%(w)s AND version_key=%(key)s AND superseded_at IS NULL ORDER BY ordinal LIMIT %(n)s")
_SCHEMA = {}


def _admitted(ctx):
    source_policy.stamp(ctx.state)
    # Agent tools may run on a cloud manager even with a local writer selected.
    # Requiring cloud consent is the conservative common boundary.
    result = {}
    for source in ctx.state.get('sources', []):
        origin = source.get('origin') or {}
        admitted, _, _ = source_policy.classify(source, 'draft', 'cloud')
        facts = [f for f in source.get('facts', []) if f.get('approved')]
        if admitted and facts and origin.get('kind') == 'library':
            result[source['id']] = (source, facts)
    return result


def _fact(f):
    return {'id': f['id'], 'text': f['text'][:1500], 'locator': f.get('locator', 'extracted text')}


def _ready(ctx):
    """Shared search is used when its flag is on and migration 097 is present (checked once per process)."""
    from ..library_intelligence import policy
    if not policy.enabled('retrieval'):
        return False
    if not _SCHEMA.get('present'):
        ctx.cur.execute("SELECT to_regclass('public.pr_library_segments')")
        row = ctx.cur.fetchone()
        if not row or not row[0]:
            return False
        _SCHEMA['present'] = True
    return True


def _library_context(ctx):
    from ..library_intelligence import contracts as lc
    return lc.LibraryContext(workspace_id=str(ctx.workspace_id), actor=str(ctx.principal), membership=ctx.membership, state=ctx.state,
                             cur=ctx.cur, now=ctx.now, service=ctx.service)


def _selected_facts(facts, query):
    from ..library_intelligence import textnorm
    terms = textnorm.query_terms(query)
    if not terms:
        return facts
    chosen = [f for f in facts if all(t in set(textnorm.tokens(f['text'])) or t in textnorm.fold(f['text']) for t in terms)]
    return chosen or facts


def _compact(coverage):
    return {k: coverage[k] for k in ('scopeDescription', 'accessibleAssetCount', 'indexedAssetCount', 'pendingAssetCount', 'failedAssetCount',
                                     'modesApplied', 'partial')}


def library_search(ctx, query='', limit=10):
    if ctx.cur is None:
        return contracts.result({'results': [], 'requiresDatabase': True}, now=ctx.now, verified=False)
    limit = max(1, min(int(limit), 20))
    if not _ready(ctx):
        return _legacy_search(ctx, query, limit)
    from ..library_intelligence import search
    lctx = _library_context(ctx)
    request = {'query': str(query or '')[:500], 'limit': limit}
    facts_page = search.search_library(lctx, {**request, 'purpose': 'draft_evidence'})
    passages_page = search.search_library(lctx, {**request, 'purpose': 'answer'}, processing=CLOUD_LLM, passage_chars=PASSAGE_CHARS)
    allowed = _admitted(ctx)
    results, order = {}, []
    for hit in facts_page['hits']:
        source_id = hit.get('sourceId')
        if source_id not in allowed:
            continue
        _, facts = allowed[source_id]
        key = hit['assetRef']['versionId']
        results[key] = {'assetId': key, 'assetRef': hit['assetRef'], 'sourceId': source_id, 'title': hit['displayTitle'], 'sha256': hit['assetRef']['sha256'],
                        'facts': [_fact(f) for f in _selected_facts(facts, request['query'])[:8]], 'passages': [], 'href': '/app/library',
                        'candidateOnly': bool(hit['sourceStatus'].get('candidateOnly')), 'attributionOnly': False,
                        'matchReasons': [r['kind'] for r in hit['matchReasons']]}
        order.append(key)
    for hit in passages_page['hits']:
        key = hit['assetRef']['versionId']
        entry = results.get(key)
        if entry is None:
            entry = results[key] = {'assetId': key, 'assetRef': hit['assetRef'], 'sourceId': hit.get('sourceId'), 'title': hit['displayTitle'],
                                    'sha256': hit['assetRef']['sha256'], 'facts': [], 'passages': [], 'href': '/app/library', 'candidateOnly': False,
                                    'matchReasons': [r['kind'] for r in hit['matchReasons']]}
            order.append(key)
        entry['attributionOnly'] = True
        entry['passages'] = [{'segmentId': p.get('segmentId'), 'text': p['snippet'], 'locator': p.get('locator'), 'locatorLabel': p.get('locatorLabel'),
                              'language': p.get('language')} for p in hit.get('passages') or []][:3]
    totals = [facts_page['totalHits'], passages_page['totalHits']]
    warnings = list(dict.fromkeys(facts_page['warnings'] + passages_page['warnings']))
    if not order and not allowed and not passages_page['coverage']['accessibleAssetCount']:
        warnings.insert(0, NOTHING_ADMITTED)
    data = {'results': [results[k] for k in order][:limit], 'total': max(t['value'] for t in totals),
            'totalRelation': 'gte' if any(t['relation'] == 'gte' for t in totals) or all(t['value'] for t in totals) else 'eq',
            'query': request['query'], 'approvedFactsOnly': True, 'passagesAreAttributedSourceText': True,
            'coverage': {'facts': _compact(facts_page['coverage']), 'passages': _compact(passages_page['coverage'])},
            'ranking': facts_page['ranking']['version']}
    return contracts.result(data, now=ctx.now, warnings=warnings)


def _legacy_search(ctx, query, limit):
    allowed = _admitted(ctx)
    if not allowed:
        return contracts.result({'results': [], 'total': 0}, now=ctx.now, warnings=[NOTHING_ADMITTED])
    # Every admitted source is considered (admission is bounded by the workspace's sources); no recency window.
    ctx.cur.execute("""SELECT a.id::text,a.source_id,a.display_title,a.original_filename,a.sha256
        FROM public.pr_library_assets a WHERE a.workspace_id=%s AND a.source_id=ANY(%s)
        AND a.processing_status IN ('ready','unsupported') ORDER BY a.created_at DESC""", (ctx.workspace_id, list(allowed)))
    results = []
    for asset_id, source_id, title, filename, sha in ctx.cur.fetchall():
        source, facts = allowed[source_id]
        if (source.get('origin') or {}).get('sha256') != sha:
            continue
        words = query.casefold().split()
        selected = [f for f in facts if not words or all(word in f['text'].casefold() for word in words)]
        if not selected and query and not all(word in (title or filename).casefold() for word in words):
            continue
        results.append({'assetId': asset_id.replace('-', ''), 'sourceId': source_id, 'title': title or filename, 'sha256': sha,
                        'facts': [_fact(f) for f in (selected or facts)[:8]], 'passages': [],
                        'href': '/app/library', 'candidateOnly': source_policy.classify(source, 'draft', 'cloud')[2]})
    return contracts.result({'results': results[:limit], 'total': len(results), 'query': query, 'approvedFactsOnly': True}, now=ctx.now)


def library_read(ctx, assetId):
    if ctx.cur is None:
        raise AlphaError('Library retrieval requires the workspace database.', 503)
    if not _ready(ctx):
        return _legacy_read(ctx, assetId)
    from ..library_intelligence import contracts as lc, policy, versions
    lctx = _library_context(ctx)
    try:
        version = versions.get(lctx, assetId)
    except AlphaError:
        raise AlphaError(NOT_ADMITTED, 404) from None
    allowed = _admitted(ctx)
    facts = None
    if version.get('sourceId') in allowed and version['status'] in ('ready', 'unsupported'):
        source, approved = allowed[version['sourceId']]
        if (source.get('origin') or {}).get('sha256') != version['sha256']:
            raise AlphaError('This Library source changed. Import it again.', 409)
        facts = (source, approved)
    passages = []
    decision = policy.authorize_source(lctx, version, 'answer', CLOUD_LLM)
    if decision.allowed and policy.recheck(lctx, decision).allowed:
        lctx.cur.execute(READ_SEGMENTS_SQL, {'w': lctx.workspace_id, 'key': version['versionId'], 'n': READ_PASSAGES})
        for segment_id, text, locator, kind, language, _ordinal in lctx.cur.fetchall():
            try:
                loc = lc.locator(locator) if isinstance(locator, dict) else None
            except AlphaError:
                loc = None  # an unverifiable locator is dropped, never invented
            passages.append({'segmentId': segment_id, 'text': ' '.join(str(text).split())[:PASSAGE_CHARS], 'locator': loc,
                             'locatorLabel': lc.locator_label(loc) if loc else None, 'kind': kind, 'language': language})
    if facts is None and not passages:
        raise AlphaError(NOT_ADMITTED, 404)
    source, approved = facts if facts else (None, [])
    return contracts.result({'assetId': version['versionId'], 'assetRef': versions.ref(version), 'sourceId': version.get('sourceId') if facts else None,
                             'title': version['title'], 'sha256': version['sha256'], 'facts': [_fact(f) for f in approved[:16]], 'passages': passages,
                             'approvedFactsOnly': True, 'passagesAreAttributedSourceText': True, 'attributionOnly': bool(passages),
                             'candidateOnly': source_policy.classify(source, 'draft', 'cloud')[2] if source else False}, now=ctx.now)


def _legacy_read(ctx, assetId):
    allowed = _admitted(ctx)
    ctx.cur.execute("SELECT source_id,sha256,display_title,original_filename FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s AND processing_status IN ('ready','unsupported')", (ctx.workspace_id, assetId))
    row = ctx.cur.fetchone()
    if not row or row[0] not in allowed:
        raise AlphaError(NOT_ADMITTED, 404)
    source, facts = allowed[row[0]]
    if (source.get('origin') or {}).get('sha256') != row[1]:
        raise AlphaError('This Library source changed. Import it again.', 409)
    return contracts.result({'assetId': assetId, 'sourceId': row[0], 'title': row[2] or row[3], 'sha256': row[1],
                             'facts': [_fact(f) for f in facts[:16]], 'approvedFactsOnly': True,
                             'candidateOnly': source_policy.classify(source, 'draft', 'cloud')[2]}, now=ctx.now)
