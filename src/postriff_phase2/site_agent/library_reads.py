"""Library retrieval for AI: approved facts only, with existing source/egress gates.

Runs in the caller's transaction; never opens another workspace lock or reads storage.
"""
from postriff_alpha.domain import AlphaError
from .. import source_policy
from . import contracts


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


def library_search(ctx, query='', limit=10):
    if ctx.cur is None:
        return contracts.result({'results': [], 'requiresDatabase': True}, now=ctx.now, verified=False)
    allowed = _admitted(ctx)
    if not allowed:
        return contracts.result({'results': [], 'total': 0}, now=ctx.now, warnings=['Import a Library source, review its facts and allow cloud sharing on Memory before AI retrieval.'])
    ctx.cur.execute("""SELECT a.id::text,a.source_id,a.display_title,a.original_filename,a.sha256
        FROM public.pr_library_assets a WHERE a.workspace_id=%s AND a.source_id=ANY(%s)
        AND a.processing_status IN ('ready','unsupported') ORDER BY a.created_at DESC LIMIT 200""", (ctx.workspace_id,list(allowed)))
    results=[]
    for asset_id, source_id, title, filename, sha in ctx.cur.fetchall():
        source, facts=allowed[source_id]
        if (source.get('origin') or {}).get('sha256') != sha:
            continue
        words=query.casefold().split()
        selected=[f for f in facts if not words or all(word in f['text'].casefold() for word in words)]
        if not selected and query and not all(word in (title or filename).casefold() for word in words):
            continue
        results.append({'assetId':asset_id.replace('-',''),'sourceId':source_id,'title':title or filename,'sha256':sha,
                        'facts':[{'id':f['id'],'text':f['text'][:1500],'locator':f.get('locator','extracted text')} for f in (selected or facts)[:8]],
                        'href':'/app/library','candidateOnly':source_policy.classify(source,'draft','cloud')[2]})
    return contracts.result({'results':results[:max(1,min(int(limit),20))],'total':len(results),'query':query,'approvedFactsOnly':True}, now=ctx.now)


def library_read(ctx, assetId):
    if ctx.cur is None:
        raise AlphaError('Library retrieval requires the workspace database.',503)
    # Direct lookup still scans only this workspace's admitted sources, bounded by 200.
    allowed=_admitted(ctx)
    ctx.cur.execute("SELECT source_id,sha256,display_title,original_filename FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s AND processing_status IN ('ready','unsupported')",(ctx.workspace_id,assetId))
    row=ctx.cur.fetchone()
    if not row or row[0] not in allowed:
        raise AlphaError('This Library source needs fact review and cloud sharing permission, or is unavailable.',404)
    source,facts=allowed[row[0]]
    if (source.get('origin') or {}).get('sha256') != row[1]:
        raise AlphaError('This Library source changed. Import it again.',409)
    return contracts.result({'assetId':assetId,'sourceId':row[0],'title':row[2] or row[3],'sha256':row[1],
        'facts':[{'id':f['id'],'text':f['text'][:1500],'locator':f.get('locator','extracted text')} for f in facts[:16]],
        'approvedFactsOnly':True,'candidateOnly':source_policy.classify(source,'draft','cloud')[2]},now=ctx.now)
