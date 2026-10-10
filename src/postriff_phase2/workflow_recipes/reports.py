"""Stored-data reports. The task receipt contains only report references, never report bodies."""
from __future__ import annotations
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from ..agent_runtime_v2.ui_domain.common import DomainContext, bind
from ..agent_runtime_v2.ui_domain.analytics import analytics_posts
from ..agent_runtime_v2 import library_browse


def performance(service, cur, w, principal, member, state, row, inputs, now):
    dctx = DomainContext(SimpleNamespace(service=service), cur, None, w, principal, member, state, int(row[0]), {}, {}, now, inputs['timeZone'])
    report = analytics_posts(dctx, {key: inputs[key] for key in ('connectionId', 'start', 'end', 'timeZone')}, None)
    # Preserve unavailable/null/cohort/definition semantics and make the page bound explicit.
    report['truncated'] = report['nextCursor'] is not None
    report['nextCursor'] = None  # this is an immutable report, not a live-query cursor
    if report['truncated']:
        report['state'] = 'partial'
        report['warnings'].append('Only the first 50 posts are included. Open Analytics for the full period.')
    return {'kind': 'performance', **report, 'providerRequests': 0, 'costUsdMicro': 0}


def library(service, cur, w, principal, _member, _state, _row, inputs, now):
    selected = inputs['assetIds']
    if selected:
        # Event scope is persisted server-side. Read only allowlisted columns; never a blob/text/excerpt/hash.
        cur.execute("""SELECT replace(a.id::text,'-',''),a.kind,a.display_title,a.tags,a.processing_status,
           coalesce((SELECT array_agg(replace(i.collection_id::text,'-','') ORDER BY i.collection_id)
            FROM public.pr_library_collection_items i WHERE i.workspace_id=a.workspace_id AND i.asset_key=replace(a.id::text,'-','')),ARRAY[]::text[])
           FROM public.pr_library_assets a WHERE a.workspace_id=%s AND a.id=ANY(%s::uuid[])
             AND a.processing_status NOT IN ('pending','deleting') ORDER BY a.created_at,a.id""", (w, selected))
        records = [{'assetId': ident, 'kind': kind, 'title': title, 'tags': tags, 'processing': status, 'collections': collections} for ident, kind, title, tags, status, collections in cur.fetchall()]
        if len(records) != len(selected) or (inputs['collectionId'] and any(inputs['collectionId'] not in r['collections'] for r in records)):
            raise AlphaError('A selected upload left the recipe scope. Review it in Library.', 409, code='recipe_scope_changed')
        truncated = False
    else:
        page = bind(service, cur, principal, w).library.list(w, None, query='', limit=20, collection=inputs['collectionId'], sort='newest')
        assets = page.get('assets') or []
        records = [library_browse.candidate(asset, dates={}) for asset in assets[:20]]
        truncated = len(assets) > 20 or page.get('nextOffset') is not None
    # Build new dictionaries, never return a stored object; keep human-readable output bounded.
    items = []
    for record in records:
        title, tags = library_browse.visible(record)
        ident = record['assetId']
        items.append({'assetId': ident, 'title': title, 'tags': tags, 'kind': record['kind'],
                      'collections': list(record.get('collections') or [])[:10], 'href': '/app/library?asset=' + ident})
    return {'kind': 'library', 'state': 'partial' if truncated else 'available' if items else 'empty', 'asOf': now,
            'items': items, 'truncated': truncated, 'included': len(items), 'total': None if truncated else len(items),
            'note': 'Bounded metadata review; no file contents were read or sent to a model. ' + ('More assets exist outside this report.' if truncated else 'This report covers the selected scope at this time.'),
            'providerRequests': 0, 'costUsdMicro': 0}
